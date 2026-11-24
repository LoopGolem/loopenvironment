# SPDX-License-Identifier: Apache-2.0
"""Numeric correlation and clock rejection in the disposable presentation probe."""
import unittest

from tools.presentation_pipeline import NS_PER_MS, PipelineProbe, compatible_offset, stats_ms


class PipelineProbeTests(unittest.TestCase):
    def test_clock_calibration_rejects_uncertainty_and_realtime_steps(self):
        self.assertEqual(compatible_offset((100, 1), (102, 2)), 101)
        self.assertIsNone(compatible_offset((100, NS_PER_MS + 1), (100, 2)))
        self.assertIsNone(compatible_offset((100, 1), (100 + 3 * NS_PER_MS, 2)))

    def test_correlates_phases_and_gates_browser_clock_separately(self):
        probe = PipelineProbe()
        ms = NS_PER_MS
        probe('wire', 11, 10 * ms, 11 * ms, 13 * ms)
        probe('decode', 11, 13 * ms, 14 * ms, (1, 109))
        probe('mailbox', 11, 14 * ms)
        probe('idle', 11, 15 * ms)
        probe('draw', 11, 16 * ms, 17 * ms, 18 * ms)
        probe('paint', 11, 19 * ms)
        probe('feedback', 11, 20 * ms)
        probe('wire', 12, 20 * ms, 22 * ms, 25 * ms)
        probe('decode', 12, 25 * ms, 26 * ms, (3, 119))
        probe('mailbox', 12, 26 * ms)
        probe('overwrite', 12, 29 * ms)
        probe('status', 0, 28 * ms, 29 * ms)
        stable = (100 * ms, 1), (100 * ms, 1)

        result = probe.report(1 * ms, 35 * ms, stable)
        self.assertEqual(result['frames']['painted'], 1)
        self.assertEqual(result['frames']['feedback'], 1)
        self.assertEqual(result['mailbox_overwrite_pct'], 50)
        self.assertEqual(result['source']['absent_at_client_between_markers'], 1)
        self.assertEqual(result['overhead_ms']['origin_to_feedback']['median'], 11)
        self.assertEqual(result['overhead_ms']['texture']['median'], 1)
        self.assertEqual(result['overhead_ms']['status_callback']['n'], 1)
        self.assertEqual(result['overhead_ms']['header_to_payload']['median'], 2.5)
        unstable = stable[0], (150 * ms, 1)
        result = probe.report(1 * ms, 35 * ms, unstable)
        self.assertIsNone(result['overhead_ms']['origin_to_feedback'])
        self.assertEqual(result['overhead_ms']['assign_to_paint']['median'], 1)

    def test_missing_or_negative_durations_are_excluded(self):
        self.assertIsNone(stats_ms([-1]))
        self.assertEqual(stats_ms([-1, 0, 5 * NS_PER_MS]), dict(n=2, median=2.5, p95=5.0))
