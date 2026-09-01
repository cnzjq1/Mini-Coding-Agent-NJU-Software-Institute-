import json
import tempfile
import unittest
from pathlib import Path

from coding_agent.session import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_resume_and_fork_preserve_both_leaves(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = SessionStore(root)
            first = store.add({"role": "user", "content": "root"})
            old_leaf = store.add({"role": "assistant", "content": "old"})
            store.checkout(first)
            new_leaf = store.add({"role": "assistant", "content": "new"})
            self.assertEqual([m["content"] for m in store.current_messages()], ["root", "new"])
            self.assertEqual({b["id"] for b in store.branches()}, {old_leaf, new_leaf})
            self.assertEqual(len(store.history()), 3)
            self.assertEqual(store.history()[1]["parent_id"], first)
            self.assertEqual(SessionStore(root).current_id, new_leaf)

    def test_turn_batch_has_parent_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStore(Path(folder))
            ids = store.add_many([
                {"role": "assistant", "content": ""},
                {"role": "tool", "content": "ok"},
            ])
            data = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(data["nodes"][ids[1]]["parent_id"], ids[0])

    def test_corrupt_session_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / SessionStore.DIRECTORY
            directory.mkdir()
            (directory / "session.json").write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Cannot load"):
                SessionStore(Path(folder))

    def test_architecture_experiment_is_attached_to_source_node(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStore(Path(folder))
            node = store.add({"role": "tool", "content": "decision"})
            store.record_experiment(node, {
                "id": "DEC-1", "question": "storage", "selected": "sqlite",
                "alternatives": [{"name": "sqlite", "score": 9}, {"name": "json", "score": 5}],
                "rationale": "better transactions",
            })
            self.assertEqual(store.experiments()[0]["source_node"], node)

    def test_other_branch_experiments_exclude_current_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStore(Path(folder))
            root = store.add({"role": "user", "content": "root"})
            branch_a = store.add({"role": "tool", "content": "A"})
            store.record_experiment(branch_a, {
                "id": "DEC-A", "question": "A", "selected": "a", "alternatives": [], "rationale": "a"
            })
            store.checkout(root)
            branch_b = store.add({"role": "tool", "content": "B"})
            store.record_experiment(branch_b, {
                "id": "DEC-B", "question": "B", "selected": "b", "alternatives": [], "rationale": "b"
            })
            self.assertEqual([item["id"] for item in store.other_branch_experiments()], ["DEC-A"])


if __name__ == "__main__":
    unittest.main()
