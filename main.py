"""Command-line entry point for the coding agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coding_agent import AgentConfig, CodingAgent
from coding_agent.requirements import load_requirement_file
from coding_agent.session import SessionStore
from coding_agent.methodology import FailureMemory, MethodologyStore
from coding_agent.console import ConsoleReporter
from config import (
    API_KEY, API_MAX_RETRIES, API_TIMEOUT, BASE_URL, COMMAND_TIMEOUT,
    CONTEXT_KEEP_RECENT_CHARS, MAX_HISTORY_CHARS, MAX_STEPS,
    MAX_TOOL_OUTPUT_CHARS, MODEL, REQUIREMENT_MAX_CHARS, TERMINAL_VISUALS,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Turn a software requirement into an executable local project."
    )
    parser.add_argument("requirement", nargs="?", help="Programming project requirement")
    parser.add_argument(
        "--requirement-file", metavar="PATH",
        help="Read requirement from PDF, DOCX, TXT, or Markdown",
    )
    parser.add_argument("--workspace", default="generated_project", help="Output workspace")
    parser.add_argument("--base-url", default=BASE_URL, help="OpenAI-compatible API base URL")
    parser.add_argument("--model", default=MODEL, help="Model name")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    parser.add_argument("--quiet", action="store_true", help="Disable terminal dashboard output")
    session = parser.add_mutually_exclusive_group()
    session.add_argument("--resume", action="store_true", help="Continue the current session branch")
    session.add_argument("--fork", metavar="NODE_ID", help="Continue from a historical node")
    session.add_argument("--list-branches", action="store_true", help="List saved branch leaves and exit")
    session.add_argument("--history", action="store_true", help="List every saved session node and exit")
    session.add_argument("--audit", action="store_true", help="Show methodology and evidence dashboard")
    session.add_argument("--experiments", action="store_true", help="Show architecture option competitions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if args.list_branches:
        for branch in SessionStore(workspace).branches():
            marker = "*" if branch["current"] else " "
            print(f"{marker} {branch['id']} {branch['role']}: {branch['preview']}")
        return 0
    if args.history:
        for node in SessionStore(workspace).history():
            marker = "*" if node["current"] else ("+" if node["leaf"] else " ")
            parent = node["parent_id"] or "ROOT"
            print(f"{marker} {node['id']} <- {parent} {node['role']}: {node['preview']}")
        return 0
    if args.audit:
        method = MethodologyStore(workspace)
        failures = FailureMemory(workspace)
        ConsoleReporter(True).audit(method.data, failures.data)
        return 0
    if args.experiments:
        store = SessionStore(workspace)
        for experiment in store.experiments():
            print(f"{experiment['id']} @ node:{experiment['source_node']}  {experiment['question']}")
            for option in experiment["alternatives"]:
                marker = "*" if option.get("name") == experiment["selected"] else " "
                print(f"  {marker} {option.get('name')} score={option.get('score')}")
        for transition in store.strategy_transitions():
            target = transition.get("decision_id") or transition.get("alternative") or "current"
            print(f"{transition['id']} @ node:{transition['source_node']}  "
                  f"{transition['action']} -> {target}  goal={transition['goal_achieved']}")
        return 0
    if args.requirement and args.requirement_file:
        print("错误：文本要求和 --requirement-file 不能同时使用。", file=sys.stderr)
        return 2
    requirement = args.requirement
    if args.requirement_file:
        try:
            requirement = load_requirement_file(args.requirement_file, REQUIREMENT_MAX_CHARS)
        except Exception as exc:
            print(f"需求文件读取失败：{exc}", file=sys.stderr)
            return 2
    if not requirement and not args.requirement_file and not sys.stdin.isatty():
        requirement = sys.stdin.read().strip()
    if not requirement and not args.resume:
        requirement = input("请输入编程项目要求：\n> ").strip()
    if not requirement and not args.resume:
        print("错误：项目要求不能为空。", file=sys.stderr)
        return 2
    if not API_KEY:
        print("错误：请通过环境变量 OPENAI_API_KEY 提供密钥。", file=sys.stderr)
        return 2

    workspace.mkdir(parents=True, exist_ok=True)
    config = AgentConfig(
        api_key=API_KEY,
        base_url=args.base_url,
        model=args.model,
        max_steps=args.max_steps,
        max_history_chars=MAX_HISTORY_CHARS,
        context_keep_recent_chars=CONTEXT_KEEP_RECENT_CHARS,
        command_timeout=COMMAND_TIMEOUT,
        max_tool_output_chars=MAX_TOOL_OUTPUT_CHARS,
        api_max_retries=API_MAX_RETRIES,
        api_timeout=API_TIMEOUT,
        terminal_visuals=TERMINAL_VISUALS and not args.quiet,
    )
    agent = CodingAgent(config=config, workspace=workspace)
    print(f"工作区：{workspace}")
    try:
        result = agent.run(requirement or "", resume=args.resume, fork_from=args.fork)
    except KeyboardInterrupt:
        print("\n已由用户中止。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1
    print("\n=== 完成 ===")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
