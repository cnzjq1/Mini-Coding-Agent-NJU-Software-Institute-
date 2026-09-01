"""Local tools exposed to the model. No server-hosted file or execution tools are used."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .methodology import CheckpointManager, FailureMemory, MethodologyStore


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory; default is workspace root"},
                    "recursive": {"type": "boolean", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a UTF-8 text file, including parent directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Replace one exact text occurrence in an existing UTF-8 file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run one command in the workspace and return exit code/stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_project",
            "description": "Request completion after the project has been created and verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "run_command": {"type": "string"},
                    "entrypoints": {"type": "array", "items": {"type": "string"}},
                    "test_command": {"type": "string"},
                },
                "required": ["summary", "run_command", "entrypoints"],
            },
        },
    },
]

TOOL_SCHEMAS.extend([
    {"type": "function", "function": {
        "name": "set_acceptance_criteria",
        "description": "Define the executable acceptance checklist before implementation.",
        "parameters": {"type": "object", "properties": {"criteria": {"type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "description": {"type": "string"},
                "verification": {"type": "string"}},
            "required": ["id", "description", "verification"]}}}, "required": ["criteria"]},
    }},
    {"type": "function", "function": {
        "name": "record_evidence", "description": "Bind a successful command to one acceptance criterion.",
        "parameters": {"type": "object", "properties": {
            "criterion_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["criterion_id", "note"]},
    }},
    {"type": "function", "function": {
        "name": "record_assumption", "description": "Record an explicit design assumption and its risk.",
        "parameters": {"type": "object", "properties": {
            "assumption_id": {"type": "string"}, "statement": {"type": "string"},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "reversible": {"type": "boolean"}},
            "required": ["assumption_id", "statement", "risk", "reversible"]},
    }},
    {"type": "function", "function": {
        "name": "resolve_assumption", "description": "Resolve a recorded assumption with evidence or a decision.",
        "parameters": {"type": "object", "properties": {
            "assumption_id": {"type": "string"}, "resolution": {"type": "string"}},
            "required": ["assumption_id", "resolution"]},
    }},
    {"type": "function", "function": {
        "name": "compare_architecture_options",
        "description": "Run a bounded competition between 2-3 architecture alternatives and record the winner.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string"},
            "alternatives": {"type": "array", "minItems": 2, "maxItems": 3, "items": {
                "type": "object", "properties": {
                    "name": {"type": "string"}, "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}}, "score": {"type": "number"}},
                "required": ["name", "pros", "cons", "score"]}},
            "selected": {"type": "string"}, "rationale": {"type": "string"}},
            "required": ["question", "alternatives", "selected", "rationale"]},
    }},
    {"type": "function", "function": {
        "name": "record_adversarial_check",
        "description": "Record counterexample cases after their exact command has passed.",
        "parameters": {"type": "object", "properties": {
            "cases": {"type": "array", "items": {"type": "string"}},
            "findings": {"type": "string"}},
            "required": ["cases", "findings"]},
    }},
    {"type": "function", "function": {
        "name": "rollback_changes", "description": "Rollback all unverified file mutations in the active checkpoint.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    }},
    {"type": "function", "function": {
        "name": "methodology_status", "description": "Inspect acceptance, assumption, decision, and adversarial progress.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "inspect_other_branch_decisions",
        "description": "Inspect decisions from other branches only when the current branch has not achieved its goal.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "decide_branch_strategy",
        "description": "Decide to continue the current approach or switch strategy. A goal-achieved branch is locked to continue.",
        "parameters": {"type": "object", "properties": {
            "goal_achieved": {"type": "boolean"},
            "action": {"type": "string", "enum": ["continue", "switch"]},
            "reason": {"type": "string"}, "decision_id": {"type": "string"},
            "alternative": {"type": "string"}},
            "required": ["goal_achieved", "action", "reason"]},
    }},
])


class LocalTools:
    def __init__(self, workspace: Path, timeout: int = 120, max_output_chars: int = 30000):
        self.workspace = workspace.resolve()
        self.timeout = timeout
        self.max_output_chars = max_output_chars
        self.successful_commands: list[str] = []
        self.finished: dict[str, Any] | None = None
        self.methodology = MethodologyStore(self.workspace)
        self.failures = FailureMemory(self.workspace)
        self.checkpoints = CheckpointManager(self.workspace)
        self.session: Any | None = None

    def attach_session(self, session: Any) -> None:
        self.session = session

    def _path(self, relative: str = ".") -> Path:
        candidate = (self.workspace / relative).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Path escapes the workspace") from exc
        internal = self.workspace / ".mini_coding_agent"
        if candidate == internal or internal in candidate.parents:
            raise ValueError("Agent session metadata is protected")
        return candidate

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _clip(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        kept = self.max_output_chars // 2
        return text[:kept] + "\n...[output truncated]...\n" + text[-kept:]

    def execute(self, name: str, arguments: str | dict[str, Any]) -> str:
        try:
            if self.methodology.status()["objective_satisfied"] and name != "finish_project":
                raise ValueError(
                    "All acceptance gates already passed; the task is complete. "
                    "Call finish_project now; do not explore another approach or modify the project."
                )
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be a JSON object")
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")
            result = handler(**args)
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)

    def _tool_list_files(self, path: str = ".", recursive: bool = False) -> dict[str, Any]:
        root = self._path(path)
        if not root.exists():
            raise FileNotFoundError(path)
        if not root.is_dir():
            raise NotADirectoryError(path)
        entries = root.rglob("*") if recursive else root.iterdir()
        values = []
        for item in sorted(entries):
            if item == self.workspace / ".mini_coding_agent" or (self.workspace / ".mini_coding_agent") in item.parents:
                continue
            rel = item.relative_to(self.workspace).as_posix()
            values.append(rel + ("/" if item.is_dir() else ""))
            if len(values) >= 1000:
                values.append("...[listing truncated]...")
                break
        return {"entries": values}

    def _tool_read_file(self, path: str) -> dict[str, Any]:
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return {"path": path, "content": self._clip(target.read_text(encoding="utf-8"))}

    def _tool_write_file(self, path: str, content: str) -> dict[str, Any]:
        target = self._path(path)
        self.checkpoints.before_mutation(target)
        self._atomic_write(target, content)
        return {"path": path, "bytes": len(content.encode("utf-8"))}

    def _tool_replace_in_file(self, path: str, old: str, new: str) -> dict[str, Any]:
        target = self._path(path)
        content = target.read_text(encoding="utf-8")
        count = content.count(old)
        if count != 1:
            raise ValueError(f"Expected exactly one match, found {count}")
        updated = content.replace(old, new, 1)
        self.checkpoints.before_mutation(target)
        self._atomic_write(target, updated)
        return {"path": path, "replacements": 1}

    def _tool_run_command(self, command: str) -> dict[str, Any]:
        if not command.strip():
            raise ValueError("Command cannot be empty")
        env = os.environ.copy()
        try:
            process = subprocess.run(
                command,
                cwd=self.workspace,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
            )
            result = {
                "exit_code": process.returncode,
                "stdout": self._clip(process.stdout),
                "stderr": self._clip(process.stderr),
            }
            if process.returncode == 0:
                self.successful_commands.append(command)
            else:
                failure = self.failures.record(command, process.stderr or process.stdout)
                result["failure_signature"] = failure["signature"]
                result["failure_count"] = failure["count"]
                if failure["count"] > 1:
                    result["guidance"] = "Repeated failure: do not repeat the same unsuccessful approach"
            return result
        except subprocess.TimeoutExpired as exc:
            failure = self.failures.record(
                command, str((exc.stderr or "") or (exc.stdout or "") or "command timed out")
            )
            return {
                "exit_code": None,
                "timed_out": True,
                "stdout": self._clip(exc.stdout or ""),
                "stderr": self._clip(exc.stderr or ""),
                "failure_signature": failure["signature"],
                "failure_count": failure["count"],
            }

    def _tool_finish_project(
        self,
        summary: str,
        run_command: str,
        entrypoints: list[str],
        test_command: str = "",
    ) -> dict[str, Any]:
        if not summary.strip() or not run_command.strip():
            raise ValueError("summary and run_command cannot be empty")
        if not self.successful_commands:
            raise ValueError("Run at least one successful validation command before finishing")
        self.methodology.require_finish_ready()
        project_files = [
            item for item in self.workspace.rglob("*")
            if item.is_file() and ".mini_coding_agent" not in item.parts
        ]
        if not project_files:
            raise ValueError("Workspace contains no project files")
        if not entrypoints:
            raise ValueError("Declare at least one entrypoint")
        missing = [path for path in entrypoints if not self._path(path).is_file()]
        if missing:
            raise ValueError(f"Entrypoints not found: {missing}")
        self.finished = {
            "summary": summary.strip(),
            "run_command": run_command.strip(),
            "test_command": test_command.strip(),
            "entrypoints": entrypoints,
            "validated_command": self.successful_commands[-1],
        }
        return {"accepted": True, **self.finished}

    def _tool_set_acceptance_criteria(self, criteria: list[dict[str, str]]) -> dict[str, Any]:
        return self.methodology.set_criteria(criteria)

    def _tool_record_evidence(self, criterion_id: str, note: str) -> dict[str, Any]:
        result = self.methodology.add_evidence(criterion_id, note, self.successful_commands)
        checkpoint = self.checkpoints.commit(result["command"])
        return {"evidence": result, "checkpoint_committed": checkpoint}

    def _tool_record_assumption(self, assumption_id: str, statement: str, risk: str,
                                reversible: bool) -> dict[str, Any]:
        return self.methodology.add_assumption(assumption_id, statement, risk, reversible)

    def _tool_resolve_assumption(self, assumption_id: str, resolution: str) -> dict[str, Any]:
        return self.methodology.resolve_assumption(assumption_id, resolution)

    def _tool_compare_architecture_options(self, question: str, alternatives: list[dict[str, Any]],
                                           selected: str, rationale: str) -> dict[str, Any]:
        return self.methodology.add_decision(question, alternatives, selected, rationale)

    def _tool_record_adversarial_check(self, cases: list[str], findings: str) -> dict[str, Any]:
        result = self.methodology.record_adversarial(cases, findings, self.successful_commands)
        checkpoint = self.checkpoints.commit(result["command"])
        return {"adversarial": result, "checkpoint_committed": checkpoint}

    def _tool_rollback_changes(self, reason: str) -> dict[str, Any]:
        return self.checkpoints.rollback(reason)

    def _tool_methodology_status(self) -> dict[str, Any]:
        return self.methodology.status()

    def _tool_inspect_other_branch_decisions(self) -> dict[str, Any]:
        status = self.methodology.status()
        if status["objective_satisfied"] or status["branch_decisions_locked"] or status["branch_goal_achieved"]:
            return {
                "locked": True, "decisions": [],
                "message": "Current branch achieved its goal; other branch decisions are intentionally hidden",
            }
        if self.session is None:
            raise RuntimeError("Session tree is not attached")
        decisions = self.session.other_branch_experiments()
        return {
            "locked": False, "decisions": decisions,
            "message": "Use another decision only if it is better than continuing the current branch",
        }

    def _tool_decide_branch_strategy(
        self,
        goal_achieved: bool,
        action: str,
        reason: str,
        decision_id: str = "",
        alternative: str = "",
    ) -> dict[str, Any]:
        selected = None
        if action == "switch" and decision_id:
            if self.session is None:
                raise RuntimeError("Session tree is not attached")
            available = {item["id"]: item for item in self.session.other_branch_experiments()}
            selected = available.get(decision_id)
            if selected is None:
                raise ValueError("decision_id is not available from another branch")
        rollback = None
        if action == "switch" and self.checkpoints.active is not None:
            rollback = self.checkpoints.rollback("strategy switch: " + reason)
        transition = self.methodology.branch_strategy(
            goal_achieved, action, reason, decision_id, alternative
        )
        return {"transition": transition, "adopted_decision": selected, "rollback": rollback}
