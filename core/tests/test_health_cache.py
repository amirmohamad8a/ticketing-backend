from unittest.mock import patch

from django.test import SimpleTestCase

from core import health


class CachedChecksTests(SimpleTestCase):
    def setUp(self):
        health.clear_cached_checks()
        self.addCleanup(health.clear_cached_checks)
        self.calls = []

    def _check(self):
        self.calls.append(1)

    def _run(self, clock_values):
        results = []
        with (
            patch("core.health.CHECKS", (("cache", self._check),)),
            patch("core.health.time") as clock,
        ):
            for moment in clock_values:
                clock.monotonic.return_value = moment
                results.append(health.cached_run_checks())
        return results

    def test_checks_run_once_within_the_ttl(self):
        first, second = self._run([100.0, 100.0 + health.RESULTS_TTL_SECONDS - 0.1])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first, second)

    def test_checks_run_again_once_the_ttl_has_passed(self):
        self._run([100.0, 100.0 + health.RESULTS_TTL_SECONDS])
        self.assertEqual(len(self.calls), 2)

    def test_clearing_the_cache_forces_a_fresh_run(self):
        self._run([100.0])
        health.clear_cached_checks()
        self._run([101.0])
        self.assertEqual(len(self.calls), 2)

    def test_callers_cannot_change_the_cached_results(self):
        with patch("core.health.CHECKS", (("cache", self._check),)):
            with patch("core.health.time") as clock:
                clock.monotonic.return_value = 100.0
                results = health.cached_run_checks()
                results["cache"] = "error"
                self.assertEqual(health.cached_run_checks(), {"cache": "ok"})
