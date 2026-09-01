"""Atomic, tree-shaped local conversation persistence."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


class SessionStore:
    DIRECTORY = ".mini_coding_agent"

    def __init__(self, workspace: Path):
        self.directory = workspace.resolve() / self.DIRECTORY
        self.path = self.directory / "session.json"
        self.data: dict[str, Any] = {
            "version": 1, "current_id": None, "nodes": {}, "summaries": {},
            "experiments": {}, "strategy_transitions": []
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot load session file {self.path}: {exc}") from exc
        if loaded.get("version") != 1 or not isinstance(loaded.get("nodes"), dict):
            raise RuntimeError("Unsupported or invalid session format")
        self.data = loaded
        self.data.setdefault("summaries", {})
        self.data.setdefault("experiments", {})
        self.data.setdefault("strategy_transitions", [])

    def _save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix="session-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @property
    def current_id(self) -> str | None:
        return self.data.get("current_id")

    def start_new_root(self) -> None:
        self.data["current_id"] = None
        self._save()

    def checkout(self, node_id: str) -> None:
        if node_id not in self.data["nodes"]:
            raise ValueError(f"Unknown session node: {node_id}")
        self.data["current_id"] = node_id
        self._save()

    def add(self, message: dict[str, Any]) -> str:
        return self.add_many([message])[-1]

    def add_many(self, messages: list[dict[str, Any]]) -> list[str]:
        """Append a complete logical turn and persist it with one atomic replace."""
        ids: list[str] = []
        parent_id = self.current_id
        for message in messages:
            node_id = uuid.uuid4().hex[:12]
            self.data["nodes"][node_id] = {
                "id": node_id,
                "parent_id": parent_id,
                "created_at": time.time(),
                "message": message,
            }
            ids.append(node_id)
            parent_id = node_id
        self.data["current_id"] = parent_id
        self._save()
        return ids

    def current_messages(self) -> list[dict[str, Any]]:
        return [entry["message"] for entry in self.current_entries()]

    def current_entries(self) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        node_id = self.current_id
        while node_id:
            if node_id in seen:
                raise RuntimeError("Cycle detected in session tree")
            seen.add(node_id)
            node = self.data["nodes"].get(node_id)
            if node is None:
                raise RuntimeError(f"Broken session parent link: {node_id}")
            chain.append(node)
            node_id = node.get("parent_id")
        return list(reversed(chain))

    def set_summary(self, summary: str) -> None:
        if self.current_id:
            self.data["summaries"][self.current_id] = summary
            self._save()

    def nearest_summary(self) -> str | None:
        node_id = self.current_id
        while node_id:
            summary = self.data["summaries"].get(node_id)
            if summary:
                return summary
            node_id = self.data["nodes"].get(node_id, {}).get("parent_id")
        return None

    def branches(self) -> list[dict[str, Any]]:
        parents = {node.get("parent_id") for node in self.data["nodes"].values()}
        leaves = [node for node_id, node in self.data["nodes"].items() if node_id not in parents]
        return [{
            "id": node["id"],
            "current": node["id"] == self.current_id,
            "role": node["message"].get("role"),
            "preview": str(node["message"].get("content", ""))[:80],
        } for node in sorted(leaves, key=lambda item: item["created_at"])]

    def history(self) -> list[dict[str, Any]]:
        parents = {node.get("parent_id") for node in self.data["nodes"].values()}
        return [{
            "id": node["id"],
            "parent_id": node.get("parent_id"),
            "current": node["id"] == self.current_id,
            "leaf": node["id"] not in parents,
            "role": node["message"].get("role"),
            "preview": str(node["message"].get("content", ""))[:80],
        } for node in sorted(self.data["nodes"].values(), key=lambda item: item["created_at"])]

    def record_experiment(self, source_node: str, decision: dict[str, Any]) -> None:
        decision_id = decision.get("id")
        if decision_id:
            self.data["experiments"][decision_id] = {
                "source_node": source_node,
                "question": decision.get("question"),
                "alternatives": decision.get("alternatives", []),
                "selected": decision.get("selected"),
                "rationale": decision.get("rationale"),
            }
            self._save()

    def experiments(self) -> list[dict[str, Any]]:
        return [{"id": key, **value} for key, value in self.data["experiments"].items()]

    def current_path_ids(self) -> set[str]:
        ids: set[str] = set()
        node_id = self.current_id
        while node_id:
            if node_id in ids:
                raise RuntimeError("Cycle detected in session tree")
            ids.add(node_id)
            node_id = self.data["nodes"].get(node_id, {}).get("parent_id")
        return ids

    def other_branch_experiments(self) -> list[dict[str, Any]]:
        current_path = self.current_path_ids()
        return [item for item in self.experiments() if item.get("source_node") not in current_path]

    def record_strategy_transition(self, source_node: str, transition: dict[str, Any]) -> None:
        self.data["strategy_transitions"].append({"source_node": source_node, **transition})
        self._save()

    def strategy_transitions(self) -> list[dict[str, Any]]:
        return list(self.data["strategy_transitions"])
