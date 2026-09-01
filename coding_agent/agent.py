"""Model/tool loop with durable sessions, compaction, and verified completion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from .context import SUMMARY_INSTRUCTION, ContextManager
from .console import ConsoleReporter
from .prompts import SYSTEM_PROMPT
from .session import SessionStore
from .tools import TOOL_SCHEMAS, LocalTools


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    base_url: str
    model: str
    max_steps: int = 30
    max_history_chars: int = 120000
    context_keep_recent_chars: int = 40000
    command_timeout: int = 120
    max_tool_output_chars: int = 30000
    api_max_retries: int = 4
    api_timeout: float = 180
    terminal_visuals: bool = True


class CodingAgent:
    def __init__(self, config: AgentConfig, workspace: Path, client: Any | None = None):
        self.config = config
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.client = client or OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=config.api_max_retries,
            timeout=config.api_timeout,
        )
        self.tools = LocalTools(
            self.workspace,
            timeout=config.command_timeout,
            max_output_chars=config.max_tool_output_chars,
        )
        self.session = SessionStore(self.workspace)
        self.tools.attach_session(self.session)
        self.context = ContextManager(config.max_history_chars, config.context_keep_recent_chars)
        self.reporter = ConsoleReporter(config.terminal_visuals)

    @staticmethod
    def _assistant_message(message: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            result["tool_calls"] = [{
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            } for call in message.tool_calls]
        return result

    def _summarize(self, source: str) -> str:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SUMMARY_INSTRUCTION},
                {"role": "user", "content": source},
            ],
        )
        if not response.choices:
            raise RuntimeError("Summary model call returned no choices")
        return response.choices[0].message.content or ""

    def _final_text(self, result: dict[str, Any]) -> str:
        lines = [result["summary"], "", f"运行：{result['run_command']}"]
        if result.get("test_command"):
            lines.append(f"测试：{result['test_command']}")
        lines.append("入口：" + ", ".join(result["entrypoints"]))
        lines.append(f"已验证：{result['validated_command']}")
        status = self.tools.methodology.status()
        lines.append(
            f"验收证据：{status['criteria_verified']}/{status['criteria_total']}；"
            f"反例验证：{'通过' if status['adversarial_completed'] else '未完成'}"
        )
        return "\n".join(lines)

    def run(self, requirement: str, *, resume: bool = False, fork_from: str | None = None) -> str:
        if fork_from:
            self.session.checkout(fork_from)
        elif not resume:
            self.session.start_new_root()

        if requirement.strip() or fork_from or not resume:
            self.tools.methodology.reset_for_scope()

        history_entries = self.session.current_entries()
        history = [entry["message"] for entry in history_entries]
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
        node_ids: list[str | None] = [None, *[entry["id"] for entry in history_entries]]
        if requirement.strip():
            user_message = {"role": "user", "content": requirement.strip()}
            messages.append(user_message)
            node_ids.append(self.session.add(user_message))
        elif not history:
            raise ValueError("A requirement is needed for a new session")

        previous_summary = self.session.nearest_summary()
        reminder_count = 0
        self.reporter.banner(str(self.workspace), resume or bool(fork_from))
        for step in range(1, self.config.max_steps + 1):
            view, summary, view_node_ids = self.context.prepare(
                messages, self._summarize, previous_summary, node_ids
            )
            if summary and summary != previous_summary:
                previous_summary = summary
                self.session.set_summary(summary)
                messages = view
                node_ids = view_node_ids
                self.reporter.compacted()

            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=view,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
            if not response.choices:
                raise RuntimeError("Model returned no choices")
            message = response.choices[0].message
            assistant = self._assistant_message(message)
            calls = message.tool_calls or []

            if not calls:
                assistant_id = self.session.add(assistant)
                messages.append(assistant)
                node_ids.append(assistant_id)
                reminder_count += 1
                if reminder_count > 2:
                    raise RuntimeError("Model repeatedly stopped without finish_project")
                reminder = {
                    "role": "user",
                    "content": "Do not stop with plain text. Validate the project, then call finish_project.",
                }
                messages.append(reminder)
                node_ids.append(self.session.add(reminder))
                continue

            turn_messages = [assistant]
            for call in calls:
                self.reporter.step(
                    step, self.config.max_steps,
                    call.function.name, call.function.arguments,
                )
                output = self.tools.execute(call.function.name, call.function.arguments)
                self.reporter.result(output)
                turn_messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
            messages.extend(turn_messages)
            turn_node_ids = self.session.add_many(turn_messages)
            node_ids.extend(turn_node_ids)
            for index, call in enumerate(calls):
                if call.function.name == "compare_architecture_options":
                    try:
                        decision = json.loads(turn_messages[index + 1]["content"])
                    except (json.JSONDecodeError, KeyError):
                        continue
                    if decision.get("ok"):
                        self.session.record_experiment(turn_node_ids[index + 1], decision)
                elif call.function.name == "decide_branch_strategy":
                    try:
                        strategy = json.loads(turn_messages[index + 1]["content"])
                    except (json.JSONDecodeError, KeyError):
                        continue
                    if strategy.get("ok") and strategy.get("transition"):
                        self.session.record_strategy_transition(
                            turn_node_ids[index + 1], strategy["transition"]
                        )
            self.reporter.methodology(self.tools.methodology.status())

            if self.tools.finished is not None:
                return self._final_text(self.tools.finished)

        raise RuntimeError(f"达到最大循环次数 {self.config.max_steps}，项目尚未通过验收")

    def branches(self) -> list[dict[str, Any]]:
        return self.session.branches()
