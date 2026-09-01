"""Dependency-free terminal dashboard."""

from __future__ import annotations

import os
import sys
import json
from typing import Any


class ConsoleReporter:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.color = enabled and sys.stdout.isatty() and "NO_COLOR" not in os.environ

    def _paint(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def banner(self, workspace: str, resumed: bool) -> None:
        if not self.enabled:
            return
        mode = "RESUME" if resumed else "NEW"
        print(self._paint("1;36", "╔══════ Coding Agent ════════════════════════════════╗"))
        print(f"║ mode: {mode:<8} workspace: {workspace}")
        print(self._paint("1;36", "╚════════════════════════════════════════════════════╝"))

    @staticmethod
    def _tool_detail(tool: str, arguments: str | dict[str, Any] | None) -> str:
        """Return a compact, human-readable description of a tool call."""
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(args, dict):
            return ""

        path_tools = {"list_files", "read_file", "write_file", "replace_in_file"}
        if tool in path_tools:
            path = args.get("path", ".")
            if tool == "list_files" and args.get("recursive"):
                return f"{path} (recursive)"
            return str(path)
        if tool == "run_command":
            return str(args.get("command", ""))
        if tool == "set_acceptance_criteria":
            return f"{len(args.get('criteria', []))} criteria"
        if tool == "record_evidence":
            return str(args.get("criterion_id", ""))
        if tool in {"record_assumption", "resolve_assumption"}:
            assumption = str(args.get("assumption_id", ""))
            risk = args.get("risk")
            return f"{assumption} ({risk} risk)" if risk else assumption
        if tool == "compare_architecture_options":
            question = str(args.get("question", ""))
            selected = args.get("selected")
            return f"{question} -> {selected}" if selected else question
        if tool == "record_adversarial_check":
            return f"{len(args.get('cases', []))} cases"
        if tool == "rollback_changes":
            return str(args.get("reason", ""))
        if tool == "decide_branch_strategy":
            action = str(args.get("action", ""))
            target = args.get("decision_id") or args.get("alternative")
            return f"{action} -> {target}" if target else action
        if tool == "finish_project":
            entrypoints = args.get("entrypoints", [])
            return ", ".join(map(str, entrypoints))
        return ""

    def step(self, current: int, total: int, tool: str,
             arguments: str | dict[str, Any] | None = None) -> None:
        if self.enabled:
            width = 18
            filled = max(1, int(width * current / total))
            bar = "█" * filled + "░" * (width - filled)
            detail = self._tool_detail(tool, arguments)
            suffix = f"  {detail[:240]}" if detail else ""
            print(f"{self._paint('36', bar)} {current:02d}/{total:02d}  "
                  f"{self._paint('1', tool)}{suffix}")

    def result(self, output: str) -> None:
        if not self.enabled:
            return
        try:
            data = __import__("json").loads(output)
        except Exception:
            data = {"ok": False}
        symbol = self._paint("32", "✓") if data.get("ok") else self._paint("31", "✗")
        detail = data.get("error") or data.get("path") or data.get("exit_code")
        print(f"   {symbol} {str(detail)[:160] if detail is not None else 'recorded'}")

    def methodology(self, status: dict[str, Any]) -> None:
        if not self.enabled:
            return
        done, total = status["criteria_verified"], status["criteria_total"]
        adv = "✓" if status["adversarial_completed"] else "·"
        print(f"   acceptance {done}/{total} │ adversarial {adv} │ decisions {status['decisions']}"
              f" │ assumptions {status['assumption_budget_used']}/{status['assumption_budget_limit']}"
              f" │ high-risk {len(status['high_risk_assumptions_open'])}")

    def compacted(self) -> None:
        if self.enabled:
            print(self._paint("33", "   ↳ context compacted with source-node provenance"))

    def audit(self, methodology: dict[str, Any], failures: dict[str, Any]) -> None:
        if not self.enabled:
            return
        print(self._paint("1;36", "╔══ Methodology Audit ═══════════════════════════════╗"))
        criteria = list(methodology.get("criteria", {}).values())
        for item in criteria:
            mark = "✓" if item.get("status") == "verified" else "·"
            print(f"║ {mark} {item.get('id')}: {item.get('description')}")
        if not criteria:
            print("║ · no acceptance criteria")
        adversarial = methodology.get("adversarial", {})
        print(f"║ counterexamples: {len(adversarial.get('cases', []))}"
              f"  completed={bool(adversarial.get('completed'))}")
        print(f"║ decisions: {len(methodology.get('decisions', []))}"
              f"  assumptions: {len(methodology.get('assumptions', {}))}"
              f"  failure signatures: {len(failures.get('failures', {}))}")
        strategy = methodology.get("branch_strategy", {})
        print(f"║ branch goal: {bool(strategy.get('goal_achieved'))}"
              f"  locked: {bool(strategy.get('locked'))}"
              f"  transitions: {len(strategy.get('history', []))}")
        print(self._paint("1;36", "╚════════════════════════════════════════════════════╝"))
