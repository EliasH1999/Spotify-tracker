"""Milestone 1 checks observable page behavior using synthetic data only."""
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from .sample_data import build_sample_dashboard


class DashboardTests(SimpleTestCase):
    def setUp(self):
        self.today = patch("django.utils.timezone.localdate", return_value=date(2026, 11, 4))
        self.today.start()
        self.addCleanup(self.today.stop)

    def test_current_month_is_clearly_a_partial_sample(self):
        response = self.client.get("/")
        self.assertContains(response, "November, in rotation")
        self.assertContains(response, "Month in progress")
        self.assertContains(response, "invented sample data")
        self.assertContains(response, "Paper Satellites")
        self.assertEqual(response.context["dashboard"]["plays"], 124)

    def test_month_selection_changes_the_results(self):
        response = self.client.get("/", {"month": "2026-10"})
        self.assertContains(response, "October, in rotation")
        self.assertContains(response, "Completed calendar month")
        self.assertNotContains(response, "Month in progress")
        self.assertEqual(response.context["dashboard"]["plays"], 100)

    def test_older_month_explains_missing_sample_data(self):
        response = self.client.get("/", {"month": "2026-09"})
        self.assertContains(response, "No sample data for September 2026")
        self.assertContains(response, "does not mean that you listened to nothing")
        self.assertNotContains(response, 'aria-label="Monthly sample statistics"')

    def test_invalid_month_has_a_useful_error(self):
        for month in ("2026-99", "not-a-month", "", "0000-01"):
            with self.subTest(month=month):
                response = self.client.get("/", {"month": month})
                self.assertContains(response, "That month isn't available", status_code=400)

    def test_future_month_is_rejected(self):
        response = self.client.get("/", {"month": "2026-12"})
        self.assertContains(response, "Choose this month or an earlier month", status_code=400)

    def test_sample_numbers_agree_across_views(self):
        summary = build_sample_dashboard(date(2026, 11, 1), date(2026, 11, 4))
        self.assertEqual(sum(day["plays"] or 0 for day in summary["activity"]), 124)
        self.assertEqual(sum(artist["plays"] for artist in summary["artists"]), 124)
        self.assertEqual(sum(count for _, count in summary["albums"]), 124)
        self.assertEqual(summary["known_duration_plays"], 113)
        self.assertEqual(summary["estimated_minutes"], 395)
        self.assertEqual(summary["duration_coverage"], 91.1)
        self.assertTrue(all(day["plays"] is None for day in summary["activity"][4:]))

    def test_sample_works_in_a_short_month_and_at_year_boundary(self):
        for today in (date(2026, 1, 1), date(2026, 2, 28), date(2028, 2, 29)):
            with self.subTest(today=today):
                summary = build_sample_dashboard(today.replace(day=1), today)
                self.assertEqual(sum(day["plays"] or 0 for day in summary["activity"]), 124)
                self.assertEqual(summary["available_days"], today.day)
