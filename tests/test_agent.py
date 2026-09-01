import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from coding_agent import AgentConfig, CodingAgent


def tool_response(call_id, name, arguments):
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return tool_response("c1", "set_acceptance_criteria", '{"criteria":[{"id":"AC-1",'
                                 '"description":"hello runs","verification":"python hello.py"}]}')
        if self.calls == 2:
            return tool_response("c2", "write_file", '{"path":"hello.py","content":"print(\\"hello\\")\\n"}')
        if self.calls == 3:
            return tool_response("c3", "run_command", '{"command":"python hello.py"}')
        if self.calls == 4:
            return tool_response("c4", "record_evidence", '{"criterion_id":"AC-1",'
                                 '"note":"exit zero"}')
        if self.calls == 5:
            return tool_response("c5", "record_adversarial_check", '{"cases":["repeat execution"],'
                                 '"findings":"stable"}')
        self.last_messages = list(kwargs["messages"])
        return tool_response(
            "c6", "finish_project",
            '{"summary":"created hello","run_command":"python hello.py",'
            '"entrypoints":["hello.py"],"test_command":"python hello.py"}',
        )


class PlainTextCompletions:
    def create(self, **kwargs):
        message = SimpleNamespace(content="done", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class AgentTests(unittest.TestCase):
    @staticmethod
    def config(steps=30):
        return AgentConfig(api_key="test", base_url="http://example.test/v1", model="test",
                           max_steps=steps, terminal_visuals=False)

    def test_verified_tool_loop_finishes_and_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            completions = FakeCompletions()
            client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
            agent = CodingAgent(self.config(), Path(folder), client=client)
            result = agent.run("create hello")
            self.assertEqual((Path(folder) / "hello.py").read_text(), 'print("hello")\n')
            self.assertIn("python hello.py", result)
            self.assertTrue((Path(folder) / ".mini_coding_agent" / "session.json").is_file())
            self.assertEqual(completions.last_messages[-1]["role"], "tool")

    def test_plain_text_cannot_bypass_finish_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            client = SimpleNamespace(chat=SimpleNamespace(completions=PlainTextCompletions()))
            agent = CodingAgent(self.config(steps=3), Path(folder), client=client)
            with self.assertRaisesRegex(RuntimeError, "finish_project"):
                agent.run("pretend done")

    def test_sdk_retry_and_timeout_are_configured(self):
        with tempfile.TemporaryDirectory() as folder, patch("coding_agent.agent.OpenAI") as factory:
            config = AgentConfig(
                api_key="test", base_url="http://example.test/v1", model="test",
                api_max_retries=7, api_timeout=42, terminal_visuals=False,
            )
            CodingAgent(config, Path(folder))
            factory.assert_called_once_with(
                api_key="test", base_url="http://example.test/v1", max_retries=7, timeout=42
            )


if __name__ == "__main__":
    unittest.main()
