import unittest

from coding_agent.context import ContextManager


class ContextManagerTests(unittest.TestCase):
    def test_compaction_keeps_summary_and_complete_recent_tool_group(self):
        manager = ContextManager(max_chars=350, keep_recent_chars=120)
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "requirement"},
            {"role": "assistant", "content": "old " * 100},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "write"}}]},
            {"role": "tool", "content": "wrote app.py"},
        ]
        compacted, summary, ids = manager.prepare(
            messages, lambda source: "[node:old] durable summary",
            node_ids=[None, "root", "old", "call", "result"],
        )
        self.assertEqual(summary, "[node:old] durable summary")
        self.assertIn("project_state_summary", compacted[2]["content"])
        self.assertEqual(compacted[-2]["role"], "assistant")
        self.assertEqual(compacted[-1]["role"], "tool")
        self.assertEqual(ids[-1], "result")

    def test_summary_failure_uses_local_fallback(self):
        manager = ContextManager(max_chars=100, keep_recent_chars=20)
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "r"},
            {"role": "assistant", "content": "important decision " * 20},
            {"role": "assistant", "content": "recent"},
        ]
        _, summary, _ = manager.prepare(
            messages, lambda source: (_ for _ in ()).throw(RuntimeError()),
            node_ids=[None, "u1", "a1", "a2"],
        )
        self.assertIn("important decision", summary)
        self.assertIn("[node:a1]", summary)


if __name__ == "__main__":
    unittest.main()
