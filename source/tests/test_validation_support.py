import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validation_support import validate_trigger


class ValidateTriggerTests(unittest.TestCase):
    def test_clean_trigger_has_no_warnings(self):
        self.assertEqual(validate_trigger("xhello", {"xother"}, set()), [])

    def test_whitespace_warns(self):
        warnings = validate_trigger("x hi", set(), set())
        self.assertTrue(any("espaços" in w for w in warnings))

    def test_terminator_char_warns(self):
        warnings = validate_trigger("x.hi", set(), set())
        self.assertTrue(any("pontuação" in w.lower() or "terminador" in w.lower() for w in warnings))

    def test_short_trigger_warns(self):
        self.assertTrue(any("curto" in w for w in validate_trigger("ab", set(), set())))

    def test_shadowed_by_dynamic_warns(self):
        warnings = validate_trigger("xhj", set(), {"xhj", "xdolar"})
        self.assertTrue(any("dinâmico" in w for w in warnings))

    def test_suffix_conflict_warns(self):
        # "ecban" is a suffix of the proposed "iecban"
        warnings = validate_trigger("iecban", {"ecban"}, set())
        self.assertTrue(any("ecban" in w for w in warnings))

    def test_existing_ends_with_new_warns(self):
        warnings = validate_trigger("ban", {"ecban"}, set())
        self.assertTrue(any("ecban" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
