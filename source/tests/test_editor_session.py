import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from editor_session import (
    CHANGED,
    EMPTY,
    GONE,
    ITEM,
    MISSING,
    NEW,
    UNCHANGED,
    EditorSession,
    mapping_draft_problem,
    static_draft_problem,
)

RICH = {"__kind__": "rich_text", "text": "Olá", "spans": [{"tag": "bold", "start": 0, "end": 3}]}


class EditorSessionTests(unittest.TestCase):
    def test_a_new_session_shows_nothing_and_is_clean_when_empty(self):
        session = EditorSession("static")
        self.assertIsNone(session.ref)
        self.assertEqual(EMPTY, session.mode)
        self.assertFalse(session.is_dirty("", ""))
        self.assertFalse(session.is_dirty("   ", ""), "spaces around a trigger are not a change")
        self.assertTrue(session.is_dirty("xola", ""))
        self.assertTrue(session.is_dirty("", "texto"))

    def test_a_loaded_item_is_clean_until_its_trigger_or_value_changes(self):
        session = EditorSession("static")
        session.load("xola", "xola", "Olá", source="Olá")
        self.assertEqual(("xola", ITEM), (session.ref, session.mode))
        self.assertFalse(session.is_dirty("xola", "Olá"))
        self.assertFalse(session.is_dirty(" xola ", "Olá"))
        self.assertTrue(session.is_dirty("xola", "Olá!"))
        self.assertTrue(session.is_dirty("xolb", "Olá"))
        # A formatting change alone is a change: the serialized value differs.
        self.assertTrue(session.is_dirty("xola", RICH))

    def test_rich_values_compare_as_serialized(self):
        session = EditorSession("static")
        session.load("xsig", "xsig", dict(RICH), source=dict(RICH))
        self.assertFalse(session.is_dirty("xsig", dict(RICH)))
        self.assertTrue(session.is_dirty("xsig", "Olá"))

    def test_mark_saved_makes_the_draft_the_baseline(self):
        session = EditorSession("static")
        self.assertTrue(session.is_dirty("xnovo", "texto"))
        session.mark_saved("xnovo", "xnovo", "texto", source="texto")
        self.assertEqual(("xnovo", ITEM), (session.ref, session.mode))
        self.assertFalse(session.is_dirty("xnovo", "texto"))

    def test_reset_returns_to_nothing_or_to_a_fresh_draft(self):
        session = EditorSession("mapping", container="_cpf_numbers")
        session.load("alice", "alice", "1", source="1", container="_cpf_numbers")
        session.reset(new=True, container="_cnpj_numbers")
        self.assertEqual((None, NEW, "_cnpj_numbers"), (session.ref, session.mode, session.container))
        self.assertFalse(session.is_dirty("", ""))
        session.reset()
        self.assertEqual((EMPTY, None), (session.mode, session.container))

    def test_reconcile_tells_unchanged_changed_and_gone(self):
        session = EditorSession("static")
        self.assertEqual(UNCHANGED, session.reconcile(MISSING), "nothing open, nothing to reconcile")
        session.load("xola", "xola", "Olá", source="Olá")
        self.assertEqual(UNCHANGED, session.reconcile("Olá"))
        self.assertEqual(CHANGED, session.reconcile("Olá do backup"))
        self.assertEqual(GONE, session.reconcile(MISSING))

    def test_reconcile_compares_rich_values_by_content(self):
        session = EditorSession("static")
        session.load("xsig", "xsig", dict(RICH), source=dict(RICH))
        self.assertEqual(UNCHANGED, session.reconcile(dict(RICH)))
        self.assertEqual(CHANGED, session.reconcile({**RICH, "spans": []}))

    def test_a_kept_draft_stays_unsaved_and_follows_the_new_version(self):
        session = EditorSession("static")
        session.load("xola", "xola", "Olá", source="Olá")
        session.keep_draft("Olá do backup")
        self.assertEqual("xola", session.ref)
        self.assertEqual(UNCHANGED, session.reconcile("Olá do backup"), "the warning does not come back")
        # Even typed back to the old text it differs from the library now.
        self.assertTrue(session.is_dirty("xola", "Olá"))
        session.mark_saved("xola", "xola", "Olá", source="Olá")
        self.assertFalse(session.is_dirty("xola", "Olá"))

    def test_keeping_a_draft_of_a_deleted_item_makes_it_a_new_draft(self):
        session = EditorSession("static")
        session.load("xola", "xola", "Olá", source="Olá")
        session.keep_draft(MISSING)
        self.assertEqual((None, NEW), (session.ref, session.mode))
        self.assertTrue(session.is_dirty("xola", "Olá"))
        self.assertEqual(UNCHANGED, session.reconcile(MISSING))

    def test_retarget_follows_a_rename_and_keeps_the_draft(self):
        session = EditorSession("static")
        session.load("xola", "xola", "Olá", source="Olá")
        session.retarget("xoi", "xoi")
        self.assertEqual("xoi", session.ref)
        self.assertFalse(session.is_dirty("xoi", "Olá"))
        self.assertTrue(session.is_dirty("xoi", "Olá, rascunho"))
        session.keep_draft(MISSING)
        with self.assertRaises(ValueError):
            session.retarget("outro", "outro")

    def test_load_validates_the_ref_and_the_mapping_type(self):
        with self.assertRaises(ValueError):
            EditorSession("dynamic")
        session = EditorSession("mapping")
        with self.assertRaises(ValueError):
            session.load("", "", "1", source="1", container="_cpf_numbers")
        with self.assertRaises(ValueError):
            session.load("alice", "alice", "1", source="1")
        session.load("alice", "alice", "1", source="1", container="_cpf_numbers")
        self.assertEqual("_cpf_numbers", session.container)


class DraftProblemTests(unittest.TestCase):
    def test_static_drafts_need_a_free_trigger_and_a_value(self):
        self.assertEqual("Informe um trigger.", static_draft_problem("  ", "texto"))
        self.assertEqual("Triggers com '_' são reservados.", static_draft_problem("_x", "texto"))
        self.assertEqual("Informe um valor para o snippet.", static_draft_problem("xola", " \n"))
        self.assertIsNone(static_draft_problem(" xola ", "Olá"))

    def test_mapping_drafts_need_an_identifier_that_is_not_the_prefix_key(self):
        self.assertEqual("Informe um identificador.", mapping_draft_problem("", "1"))
        self.assertEqual(
            "'__prefix__' é reservado para o prefixo do tipo de mapeamento.",
            mapping_draft_problem("__prefix__", "1"),
        )
        self.assertEqual("Informe um valor.", mapping_draft_problem("alice", ""))
        self.assertIsNone(mapping_draft_problem("alice", "123"))


if __name__ == "__main__":
    unittest.main()
