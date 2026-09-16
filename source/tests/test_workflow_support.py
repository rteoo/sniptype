import threading
import unittest

from workflow_support import SnippetRef, WorkflowState


class SnippetRefTests(unittest.TestCase):
    def test_static_dynamic_and_mapping_identities(self):
        self.assertEqual(SnippetRef("static", "xhello"), SnippetRef("static", "xhello"))
        self.assertEqual("xrate", SnippetRef("dynamic", "xrate").key)
        self.assertEqual("_codes", SnippetRef("mapping", "city", "_codes").container)

    def test_rejects_ambiguous_or_invalid_identities(self):
        invalid = [
            ("unknown", "x", None),
            ("static", "", None),
            ("static", "x", "_codes"),
            ("mapping", "city", None),
        ]
        for kind, key, container in invalid:
            with self.subTest(kind=kind, key=key, container=container):
                with self.assertRaises(ValueError):
                    SnippetRef(kind, key, container)


class WorkflowStateTests(unittest.TestCase):
    def test_starts_empty_and_records_only_explicit_successes(self):
        state = WorkflowState()
        self.assertIsNone(state.last_successful_item)
        self.assertEqual((), state.recent_items())

        item = SnippetRef("static", "xhello")
        state.record_success(item)

        self.assertEqual(item, state.last_successful_item)
        self.assertEqual((item,), state.recent_items())

    def test_recent_is_unique_newest_first_and_bounded(self):
        state = WorkflowState(recent_limit=3)
        one = SnippetRef("static", "one")
        two = SnippetRef("static", "two")
        three = SnippetRef("dynamic", "three")
        four = SnippetRef("mapping", "four", "_codes")
        for item in (one, two, three, one, four):
            state.record_success(item)

        self.assertEqual((four, one, three), state.recent_items())
        self.assertEqual(four, state.last_successful_item)

    def test_concurrent_records_remain_internally_consistent(self):
        state = WorkflowState(recent_limit=20)
        items = [SnippetRef("static", f"x{index}") for index in range(40)]
        threads = [threading.Thread(target=state.record_success, args=(item,)) for item in items]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        recent = state.recent_items()
        self.assertEqual(20, len(recent))
        self.assertEqual(20, len(set(recent)))
        self.assertIn(state.last_successful_item, recent)

    def test_rejects_invalid_limit_and_non_reference_record(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    WorkflowState(limit)
        with self.assertRaises(TypeError):
            WorkflowState().record_success("xhello")


if __name__ == "__main__":
    unittest.main()
