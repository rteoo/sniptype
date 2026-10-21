"""The health projection: what is wrong, most severe first, one action each."""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import health_support as hs
import i18n

NOW = datetime(2026, 10, 20, 14, 30)
TODAY_NOON = "2026-10-20T12:00:00"


def ids(issues):
    return [issue.id for issue in issues]


class HealthTestCase(unittest.TestCase):
    def setUp(self):
        previous = i18n.language()
        i18n.set_language("pt-BR")
        self.addCleanup(i18n.set_language, previous)

    @staticmethod
    def build(**facts):
        return hs.build_health(hs.HealthFacts(**facts), now=NOW)


class QuietWhenHealthyTests(HealthTestCase):
    def test_a_healthy_app_has_nothing_to_say(self):
        self.assertEqual([], self.build())

    def test_a_good_mirror_and_sync_are_not_issues(self):
        ok = {"ok": True, "at": TODAY_NOON, "error": None, "path": "x"}
        self.assertEqual([], self.build(last_mirror=ok, last_sync=ok))


class EachStateTests(HealthTestCase):
    def test_paused_is_a_warning_with_resume(self):
        (issue,) = self.build(enabled=False)
        self.assertEqual(("paused", hs.WARNING, "Expansão pausada", hs.RESUME),
                         (issue.id, issue.severity, issue.title, issue.action_id))
        self.assertEqual("Retomar", issue.action_label)
        self.assertFalse(issue.dismissible)

    def test_a_failed_capture_is_an_error_and_is_never_also_a_pause(self):
        # The pause is the failure's consequence; resuming would not help.
        issues = self.build(enabled=False, capture_error=OSError("hook"))
        self.assertEqual(["capture-failed"], ids(issues))
        self.assertEqual(hs.ERROR, issues[0].severity)
        self.assertEqual("Captura falhou", issues[0].title)
        self.assertEqual(hs.OPEN_LOG, issues[0].action_id)

    def test_sample_defaults_are_an_error_that_names_the_quarantined_file(self):
        (issue,) = self.build(library_recovery={
            "kind": hs.SAMPLE_DEFAULTS, "at": TODAY_NOON, "backup_at": None,
            "quarantined": "snippets.corrupt-20261020-120000.json"})
        self.assertEqual(hs.ERROR, issue.severity)
        self.assertEqual("Usando a biblioteca de exemplo", issue.title)
        self.assertIn("snippets.corrupt-20261020-120000.json", issue.body)
        self.assertEqual(hs.OPEN_FOLDER, issue.action_id)
        self.assertFalse(issue.dismissible)

    def test_sample_defaults_without_a_quarantined_file_still_say_what_happened(self):
        (issue,) = self.build(library_recovery={
            "kind": hs.SAMPLE_DEFAULTS, "at": TODAY_NOON, "backup_at": None, "quarantined": None})
        self.assertNotIn("isolado", issue.body)
        self.assertIn("não havia backup válido", issue.body)

    def test_a_restore_from_backup_is_info_that_can_be_dismissed(self):
        (issue,) = self.build(library_recovery={
            "kind": hs.RECOVERED_FROM_BACKUP, "at": TODAY_NOON,
            "backup_at": "2026-10-20T09:00:00", "quarantined": "snippets.corrupt-1.json"})
        self.assertEqual(hs.INFO, issue.severity)
        self.assertTrue(issue.dismissible)
        self.assertEqual("Biblioteca restaurada do backup · Hoje 09:00", issue.title)
        self.assertIn("snippets.corrupt-1.json", issue.body)
        self.assertEqual(hs.OPEN_BACKUPS, issue.action_id)

    def test_a_restore_with_an_unreadable_time_does_not_invent_one(self):
        (issue,) = self.build(library_recovery={
            "kind": hs.RECOVERED_FROM_BACKUP, "at": TODAY_NOON, "backup_at": "not a date",
            "quarantined": None})
        self.assertEqual("Biblioteca restaurada de um backup", issue.title)

    def test_read_only_metadata_is_a_warning_and_says_malformed_or_newer(self):
        malformed = self.build(metadata_read_only=True, metadata_malformed=True)[0]
        newer = self.build(metadata_read_only=True, metadata_malformed=False)[0]
        self.assertEqual(hs.WARNING, malformed.severity)
        self.assertIn("malformados", malformed.body)
        self.assertIn("de uma versão mais nova", newer.body)

    def test_shadowed_statics_are_a_warning_listing_the_first_names(self):
        (issue,) = self.build(shadowed=("xa", "xb"))
        self.assertEqual(("shadowed", hs.WARNING, hs.OPEN_DYNAMIC),
                         (issue.id, issue.severity, issue.action_id))
        self.assertIn("xa, xb", issue.body)
        (many,) = self.build(shadowed=tuple(f"x{i}" for i in range(7)))
        self.assertIn("x0, x1, x2, x3 e mais 3", many.body)

    def test_a_save_failure_is_an_error_with_the_last_attempt(self):
        (issue,) = self.build(last_save_error={"at": TODAY_NOON, "error": "disk full"})
        self.assertEqual(("save-failed", hs.ERROR, hs.OPEN_LOG),
                         (issue.id, issue.severity, issue.action_id))
        self.assertIn("Última tentativa: Hoje 12:00.", issue.body)
        self.assertNotIn("disk full", issue.body, "the technical error is in the log")

    def test_mirror_and_sync_failures_are_warnings_that_offer_a_retry(self):
        bad = {"ok": False, "at": TODAY_NOON, "error": "denied", "path": "X:\\mirror"}
        issues = self.build(last_mirror=bad, last_sync=bad)
        self.assertEqual(["mirror-failed", "sync-failed"], ids(issues))
        for issue in issues:
            self.assertEqual((hs.WARNING, hs.RETRY_SYNC), (issue.severity, issue.action_id))
            self.assertEqual("Tentar agora", issue.action_label)
            self.assertNotIn("X:\\mirror", issue.body, "no paths in body copy")

    def test_every_issue_has_a_translated_action_label(self):
        i18n.set_language("en-US")
        for action, label in {
            hs.RESUME: "Resume", hs.OPEN_BACKUPS: "View backups", hs.OPEN_FOLDER: "Open folder",
            hs.OPEN_LOG: "Open log", hs.RETRY_SYNC: "Try now", hs.OPEN_DYNAMIC: "View dynamic actions",
        }.items():
            with self.subTest(action):
                self.assertEqual(label, hs.Issue("i", hs.INFO, "t", "b", action).action_label)


class OrderingTests(HealthTestCase):
    EVERYTHING = dict(
        enabled=False,
        library_recovery={"kind": hs.RECOVERED_FROM_BACKUP, "at": TODAY_NOON,
                          "backup_at": TODAY_NOON, "quarantined": None},
        last_save_error={"at": TODAY_NOON, "error": "x"},
        metadata_read_only=True,
        shadowed=("xa",),
        last_mirror={"ok": False, "at": TODAY_NOON, "error": "x", "path": "p"},
        last_sync={"ok": False, "at": TODAY_NOON, "error": "x", "path": "p"},
    )

    def test_errors_come_before_warnings_before_info(self):
        issues = self.build(**self.EVERYTHING)
        self.assertEqual(
            [hs.ERROR, hs.WARNING, hs.WARNING, hs.WARNING, hs.WARNING, hs.WARNING, hs.INFO],
            [issue.severity for issue in issues])

    def test_within_a_severity_the_order_follows_how_much_of_the_job_is_lost(self):
        issues = self.build(**self.EVERYTHING)
        self.assertEqual(
            ["save-failed", "paused", "metadata-read-only", "shadowed",
             "mirror-failed", "sync-failed", "restored:" + TODAY_NOON],
            ids(issues))

    def test_an_error_outranks_a_pause_that_was_listed_first(self):
        issues = self.build(enabled=False, last_save_error={"at": TODAY_NOON, "error": "x"})
        self.assertEqual(["save-failed", "paused"], ids(issues))

    def test_a_failed_capture_and_sample_defaults_lead(self):
        issues = self.build(
            capture_error=OSError("hook"),
            last_save_error={"at": TODAY_NOON, "error": "x"},
            library_recovery={"kind": hs.SAMPLE_DEFAULTS, "at": TODAY_NOON,
                              "backup_at": None, "quarantined": None},
        )
        self.assertEqual(
            ["capture-failed", "samples:" + TODAY_NOON, "save-failed"], ids(issues))


class ExpansionStateTests(HealthTestCase):
    def test_the_three_states_never_collapse(self):
        self.assertEqual(hs.EXPANSION_OK, hs.expansion_state(True, None))
        self.assertEqual(hs.EXPANSION_PAUSED, hs.expansion_state(False, None))
        self.assertEqual(hs.EXPANSION_DOWN, hs.expansion_state(False, OSError("x")))
        # Whatever the flag says, a failed capture is down.
        self.assertEqual(hs.EXPANSION_DOWN, hs.expansion_state(True, OSError("x")))

    def test_the_written_names(self):
        self.assertEqual("Expansão ativa", hs.expansion_label(hs.EXPANSION_OK))
        self.assertEqual("Expansão pausada", hs.expansion_label(hs.EXPANSION_PAUSED))
        self.assertEqual("Captura falhou", hs.expansion_label(hs.EXPANSION_DOWN))
        i18n.set_language("en-US")
        self.assertEqual("Capture failed", hs.expansion_label(hs.EXPANSION_DOWN))


class TransferLineTests(HealthTestCase):
    def test_nothing_has_happened_before_the_first_save(self):
        self.assertEqual(("Nenhuma exportação nesta sessão ainda.", False),
                         hs.describe_transfer("export", None, NOW))
        self.assertEqual(("Nenhuma cópia nesta sessão ainda.", False),
                         hs.describe_transfer("copy", None, NOW))

    def test_a_good_export_reads_as_a_dated_ok(self):
        record = {"ok": True, "at": "2026-10-10T09:10:00", "error": None, "path": "p"}
        self.assertEqual(("Última exportação 10/10 09:10 · OK", False),
                         hs.describe_transfer("export", record, NOW))

    def test_a_good_copy_today_says_hoje(self):
        record = {"ok": True, "at": TODAY_NOON, "error": None, "path": "p"}
        self.assertEqual(("Última cópia Hoje 12:00 · OK", False),
                         hs.describe_transfer("copy", record, NOW))

    def test_a_failure_carries_its_reason(self):
        record = {"ok": False, "at": TODAY_NOON, "error": "denied", "path": "p"}
        self.assertEqual(("Última exportação falhou Hoje 12:00 · denied", True),
                         hs.describe_transfer("export", record, NOW))

    def test_a_failure_without_a_reason_says_so(self):
        record = {"ok": False, "at": TODAY_NOON, "error": None, "path": "p"}
        text, failed = hs.describe_transfer("copy", record, NOW)
        self.assertTrue(failed)
        self.assertTrue(text.endswith("· sem detalhe"))


if __name__ == "__main__":
    unittest.main()
