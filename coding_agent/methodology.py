"""Auditable software-engineering state: acceptance, evidence, failures, and checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class MethodologyStore:
    def __init__(self, workspace: Path):
        self.path = workspace / ".mini_coding_agent" / "methodology.json"
        self.data: dict[str, Any] = {
            "version": 1,
            "criteria": {},
            "evidence": [],
            "assumptions": {},
            "decisions": [],
            "adversarial": {"completed": False, "cases": [], "command": "", "findings": ""},
            "branch_strategy": {"goal_achieved": False, "locked": False, "history": []},
        }
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("version") == 1:
                self.data.update(loaded)

    def save(self) -> None:
        atomic_json(self.path, self.data)

    def reset_for_scope(self) -> None:
        """Start a new requirement scope without erasing the audit file itself."""
        self.data.update({
            "criteria": {}, "evidence": [], "assumptions": {}, "decisions": [],
            "adversarial": {"completed": False, "cases": [], "command": "", "findings": ""},
            "branch_strategy": {"goal_achieved": False, "locked": False, "history": []},
        })
        self.save()

    def set_criteria(self, criteria: list[dict[str, str]]) -> dict[str, Any]:
        if not criteria:
            raise ValueError("At least one acceptance criterion is required")
        values: dict[str, Any] = {}
        for item in criteria:
            criterion_id = str(item.get("id", "")).strip()
            description = str(item.get("description", "")).strip()
            verification = str(item.get("verification", "")).strip()
            if not criterion_id or not description or not verification:
                raise ValueError("Each criterion needs id, description, and verification")
            if criterion_id in values:
                raise ValueError(f"Duplicate criterion id: {criterion_id}")
            values[criterion_id] = {
                "id": criterion_id,
                "description": description,
                "verification": verification,
                "status": "pending",
            }
        self.data["criteria"] = values
        self.data["evidence"] = []
        self.data["adversarial"] = {"completed": False, "cases": [], "command": "", "findings": ""}
        self.save()
        return self.status()

    def add_evidence(self, criterion_id: str, note: str, successful: list[str]) -> dict[str, Any]:
        criterion = self.data["criteria"].get(criterion_id)
        if criterion is None:
            raise ValueError(f"Unknown criterion: {criterion_id}")
        if not successful:
            raise ValueError("Run a successful command before recording evidence")
        command = successful[-1]
        record = {
            "criterion_id": criterion_id,
            "command": command,
            "note": note.strip(),
            "created_at": time.time(),
        }
        self.data["evidence"].append(record)
        criterion["status"] = "verified"
        self.save()
        return record

    def add_assumption(self, assumption_id: str, statement: str, risk: str, reversible: bool) -> dict[str, Any]:
        if risk not in {"low", "medium", "high"}:
            raise ValueError("risk must be low, medium, or high")
        if not assumption_id.strip() or not statement.strip():
            raise ValueError("assumption id and statement are required")
        value = {
            "id": assumption_id.strip(), "statement": statement.strip(), "risk": risk,
            "reversible": bool(reversible), "resolved": False, "resolution": "",
        }
        self.data["assumptions"][value["id"]] = value
        self.save()
        return value

    def resolve_assumption(self, assumption_id: str, resolution: str) -> dict[str, Any]:
        value = self.data["assumptions"].get(assumption_id)
        if value is None:
            raise ValueError(f"Unknown assumption: {assumption_id}")
        if not resolution.strip():
            raise ValueError("resolution cannot be empty")
        value.update({"resolved": True, "resolution": resolution.strip()})
        self.save()
        return value

    def add_decision(self, question: str, alternatives: list[dict[str, Any]], selected: str,
                     rationale: str) -> dict[str, Any]:
        if len(alternatives) < 2 or len(alternatives) > 3:
            raise ValueError("Architecture competition requires 2 or 3 alternatives")
        names = {str(item.get("name", "")).strip() for item in alternatives}
        if not selected.strip() or selected not in names:
            raise ValueError("selected must name one alternative")
        for item in alternatives:
            if not item.get("name") or "score" not in item:
                raise ValueError("Each alternative needs name and score")
        decision = {
            "id": "DEC-" + uuid.uuid4().hex[:6], "question": question.strip(),
            "alternatives": alternatives, "selected": selected, "rationale": rationale.strip(),
            "created_at": time.time(),
        }
        self.data["decisions"].append(decision)
        self.save()
        return decision

    def record_adversarial(self, cases: list[str], findings: str,
                           successful: list[str]) -> dict[str, Any]:
        if not cases:
            raise ValueError("At least one counterexample case is required")
        if not successful:
            raise ValueError("Run a successful adversarial command before recording the check")
        command = successful[-1]
        pending = self.status()["criteria_pending"]
        if pending:
            raise ValueError(f"Verify normal acceptance criteria before adversarial checks: {pending}")
        value = {"completed": True, "cases": cases, "command": command, "findings": findings.strip()}
        self.data["adversarial"] = value
        self.save()
        return value

    def branch_strategy(self, goal_achieved: bool, action: str, reason: str,
                        decision_id: str = "", alternative: str = "") -> dict[str, Any]:
        if action not in {"continue", "switch"}:
            raise ValueError("action must be continue or switch")
        if not reason.strip():
            raise ValueError("reason cannot be empty")
        state = self.data.setdefault(
            "branch_strategy", {"goal_achieved": False, "locked": False, "history": []}
        )
        objective_satisfied = self.status()["objective_satisfied"]
        if objective_satisfied and action == "switch":
            raise ValueError("Current branch objectively satisfies the goal; other decisions must not be used")
        if goal_achieved and not objective_satisfied:
            raise ValueError("Cannot mark goal_achieved before acceptance, risk, and adversarial gates pass")
        if state.get("locked") and action == "switch":
            raise ValueError("Current branch already achieved the goal; switching is locked")
        if goal_achieved and action != "continue":
            raise ValueError("A branch that achieved the goal must continue; do not use another branch decision")
        if action == "switch" and not (decision_id.strip() or alternative.strip()):
            raise ValueError("Switching requires another decision_id or a new alternative description")
        transition = {
            "id": "STR-" + uuid.uuid4().hex[:6], "goal_achieved": bool(goal_achieved),
            "action": action, "reason": reason.strip(), "decision_id": decision_id.strip(),
            "alternative": alternative.strip(), "created_at": time.time(),
        }
        state["history"].append(transition)
        state["goal_achieved"] = bool(goal_achieved)
        state["locked"] = bool(goal_achieved)
        if action == "switch":
            for criterion in self.data["criteria"].values():
                criterion["status"] = "pending"
            self.data["evidence"] = []
            self.data["adversarial"] = {
                "completed": False, "cases": [], "command": "", "findings": ""
            }
        self.save()
        return transition

    def status(self) -> dict[str, Any]:
        criteria = list(self.data["criteria"].values())
        verified = sum(item["status"] == "verified" for item in criteria)
        high_open = [
            item["id"] for item in self.data["assumptions"].values()
            if item["risk"] == "high" and not item["resolved"]
        ]
        medium_open = [
            item["id"] for item in self.data["assumptions"].values()
            if item["risk"] == "medium" and not item["resolved"]
        ]
        objective_satisfied = (
            len(criteria) > 0
            and verified == len(criteria)
            and not high_open
            and len(medium_open) <= 3
            and bool(self.data["adversarial"].get("completed"))
        )
        return {
            "criteria_total": len(criteria), "criteria_verified": verified,
            "criteria_pending": [item["id"] for item in criteria if item["status"] != "verified"],
            "high_risk_assumptions_open": high_open,
            "medium_risk_assumptions_open": medium_open,
            "assumption_budget_used": len(medium_open),
            "assumption_budget_limit": 3,
            "decisions": len(self.data["decisions"]),
            "adversarial_completed": bool(self.data["adversarial"].get("completed")),
            # Passing every gate is itself the completion decision.  The model does not
            # need a second, subjective "goal achieved" declaration.
            "branch_goal_achieved": objective_satisfied,
            "branch_decisions_locked": objective_satisfied,
            "objective_satisfied": objective_satisfied,
        }

    def require_finish_ready(self) -> None:
        status = self.status()
        if status["criteria_total"] == 0:
            raise ValueError("Define acceptance criteria before finishing")
        if status["criteria_pending"]:
            raise ValueError(f"Unverified acceptance criteria: {status['criteria_pending']}")
        if status["high_risk_assumptions_open"]:
            raise ValueError(f"Resolve high-risk assumptions: {status['high_risk_assumptions_open']}")
        if status["assumption_budget_used"] > status["assumption_budget_limit"]:
            raise ValueError("Too many unresolved medium-risk assumptions; resolve or reduce scope")
        if not status["adversarial_completed"]:
            raise ValueError("Complete counterexample-driven adversarial validation before finishing")


class FailureMemory:
    def __init__(self, workspace: Path):
        self.path = workspace / ".mini_coding_agent" / "failures.json"
        self.data = {"version": 1, "failures": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    @staticmethod
    def normalize(text: str) -> str:
        text = re.sub(r"[A-Za-z]:\\[^\s:]+|/[^\s:]+", "<path>", text)
        text = re.sub(r"line \d+|:\d+", "<line>", text, flags=re.IGNORECASE)
        text = re.sub(r"\b\d+(?:\.\d+)?s\b", "<time>", text)
        return re.sub(r"\s+", " ", text).strip()[-2000:]

    def record(self, command: str, output: str) -> dict[str, Any]:
        normalized = self.normalize(output) or "command failed without output"
        signature = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        entry = self.data["failures"].setdefault(signature, {
            "signature": signature, "normalized_error": normalized, "count": 0, "attempts": [],
        })
        entry["count"] += 1
        entry["attempts"].append({"command": command, "created_at": time.time()})
        atomic_json(self.path, self.data)
        return entry


class CheckpointManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.root = workspace / ".mini_coding_agent" / "checkpoints"
        self.active: dict[str, Any] | None = None
        self._restore_active()

    def _restore_active(self) -> None:
        if not self.root.exists():
            return
        candidates = []
        for manifest in self.root.glob("*/manifest.json"):
            directory = manifest.parent
            if not (directory / "commit.json").exists() and not (directory / "rollback.json").exists():
                candidates.append(manifest)
        if candidates:
            latest = max(candidates, key=lambda path: path.stat().st_mtime)
            self.active = json.loads(latest.read_text(encoding="utf-8"))

    def before_mutation(self, target: Path) -> None:
        if self.active is None:
            checkpoint_id = uuid.uuid4().hex[:10]
            self.active = {"id": checkpoint_id, "created_at": time.time(), "files": {}}
        relative = target.relative_to(self.workspace).as_posix()
        if relative in self.active["files"]:
            return
        checkpoint_dir = self.root / self.active["id"]
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        existed = target.is_file()
        backup = checkpoint_dir / (hashlib.sha256(relative.encode()).hexdigest() + ".bak")
        if existed:
            shutil.copyfile(target, backup)
        self.active["files"][relative] = {"existed": existed, "backup": str(backup)}
        atomic_json(checkpoint_dir / "manifest.json", self.active)

    def commit(self, command: str) -> dict[str, Any] | None:
        if self.active is None:
            return None
        result = {"checkpoint": self.active["id"], "files": len(self.active["files"]), "verified_by": command}
        atomic_json(self.root / self.active["id"] / "commit.json", result)
        self.active = None
        return result

    def rollback(self, reason: str) -> dict[str, Any]:
        if self.active is None:
            raise ValueError("No active unverified checkpoint")
        for relative, state in self.active["files"].items():
            target = self.workspace / relative
            if state["existed"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(state["backup"], target)
            elif target.exists():
                target.unlink()
        result = {"checkpoint": self.active["id"], "restored": len(self.active["files"]), "reason": reason}
        atomic_json(self.root / self.active["id"] / "rollback.json", result)
        self.active = None
        return result