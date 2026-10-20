"""Shared time vocabulary: record stamps, ages and their pairing, in both languages."""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import i18n
import time_format

# A Wednesday afternoon.
NOW = datetime(2026, 10, 14, 15, 30)


class AbsoluteStampTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_portuguese_stamps_follow_the_calendar_day(self):
        i18n.set_language("pt-BR")
        cases = (
            (datetime(2026, 10, 14, 14, 2), "Hoje 14:02"),
            (datetime(2026, 10, 13, 9, 10), "Ontem 09:10"),
            (datetime(2026, 10, 12, 9, 10), "seg. 12/10 09:10"),
            (datetime(2026, 10, 8, 9, 10), "qui. 08/10 09:10"),
            (datetime(2026, 10, 7, 9, 10), "07/10 09:10"),
            (datetime(2025, 10, 14, 9, 10), "14/10/2025"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, time_format.absolute_stamp(value, NOW))

    def test_english_spells_the_month_first(self):
        i18n.set_language("en-US")
        self.assertEqual("Today 14:02", time_format.absolute_stamp(datetime(2026, 10, 14, 14, 2), NOW))
        self.assertEqual("Yesterday 09:10", time_format.absolute_stamp(datetime(2026, 10, 13, 9, 10), NOW))
        self.assertEqual("Mon Oct 12 09:10", time_format.absolute_stamp(datetime(2026, 10, 12, 9, 10), NOW))
        self.assertEqual("Oct 7 09:10", time_format.absolute_stamp(datetime(2026, 10, 7, 9, 10), NOW))
        self.assertEqual("Oct 14, 2025", time_format.absolute_stamp(datetime(2025, 10, 14, 9, 10), NOW))

    def test_the_clock_is_24_hour_and_zero_padded(self):
        self.assertEqual("07:05", time_format.clock(datetime(2026, 1, 2, 7, 5)))
        self.assertEqual("22:31", time_format.clock(datetime(2026, 1, 2, 22, 31)))


class RelativeAgeTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_ages_use_the_shared_units(self):
        i18n.set_language("pt-BR")
        cases = (
            (timedelta(seconds=30), "agora"),
            (timedelta(minutes=4), "há 4 min"),
            (timedelta(hours=3, minutes=20), "há 3 h"),
            (timedelta(days=3, hours=1), "há 3 d"),
            (timedelta(minutes=-4), "em 4 min"),
        )
        for delta, expected in cases:
            with self.subTest(delta=delta):
                self.assertEqual(expected, time_format.relative_age(NOW - delta, NOW))

    def test_a_week_or_more_is_an_absolute_date(self):
        i18n.set_language("pt-BR")
        self.assertEqual("07/10 15:30", time_format.relative_age(NOW - timedelta(days=7), NOW))

    def test_english_ages(self):
        i18n.set_language("en-US")
        self.assertEqual("just now", time_format.relative_age(NOW, NOW))
        self.assertEqual("3 h ago", time_format.relative_age(NOW - timedelta(hours=3), NOW))
        self.assertEqual("in 2 d", time_format.relative_age(NOW + timedelta(days=2), NOW))

    def test_stamp_with_age_pairs_both_and_never_repeats_a_date(self):
        i18n.set_language("pt-BR")
        self.assertEqual(
            "Hoje 12:30 · há 3 h",
            time_format.stamp_with_age(NOW - timedelta(hours=3), NOW),
        )
        self.assertEqual("14/10/2025", time_format.stamp_with_age(datetime(2025, 10, 14), NOW))


class NameTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_names_follow_the_interface_language(self):
        self.assertEqual("outubro", time_format.month_name(10))
        self.assertEqual("qua.", time_format.weekday_name(NOW))
        i18n.set_language("en-US")
        self.assertEqual("October", time_format.month_name(10))
        self.assertEqual("Wed", time_format.weekday_name(NOW))

    def test_weekdays_start_on_monday_like_the_calendar(self):
        self.assertEqual(7, len(time_format.WEEKDAYS))
        self.assertEqual("seg.", time_format.WEEKDAYS[datetime(2026, 10, 12).weekday()])
        self.assertEqual(12, len(time_format.MONTHS))


if __name__ == "__main__":
    unittest.main()
