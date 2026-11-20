# SPDX-License-Identifier: Apache-2.0
import unittest

from loopbridge.observation import classify, observe


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ObservationTests(unittest.TestCase):
    def test_intermediate_browser_states_are_not_success(self):
        self.assertEqual(classify({'notices': ['Verificando segurança...']}), 'verifying')
        self.assertEqual(classify({'notices': ['Enviando sua solicitação...']}), 'submitting')
        self.assertEqual(classify({'notices': ['Solicitação recebida · Protocolo ABC']}), 'received')
        self.assertEqual(classify({'notices': ['Protocolo ABC', 'Processando']}), 'processing')
        self.assertEqual(classify({'notices': ['Completed']}), 'pending')
        self.assertEqual(classify({'status': 'processing'}), 'processing')
        self.assertEqual(classify({'status': 'completed'}), 'success')
        self.assertEqual(classify({'status': 'noOffers'}), 'complete_no_offers')
        self.assertEqual(classify({'status': 'unknown'}), 'unknown')

    def test_delayed_transitions_10_30_60_120_seconds_are_read_only(self):
        for delay in (10, 30, 60, 120):
            with self.subTest(delay=delay):
                clock = Clock()
                calls = []

                def read():
                    calls.append(clock.now)
                    return {'status': 'verifying' if clock.now < delay else 'completed'}

                result = observe(read, timeout=delay + 5, interval=1,
                                clock=clock.monotonic, sleep=clock.sleep)
                self.assertEqual(result['state'], 'success')
                self.assertEqual(result['elapsedSeconds'], delay)
                self.assertEqual([row['state'] for row in result['transitions']],
                                 ['verifying', 'success'])
                self.assertEqual(len(calls), delay + 1)

    def test_deadline_and_disconnect_are_unknown_without_retry(self):
        clock = Clock()
        result = observe(lambda: {'status': 'processing'}, timeout=5, interval=1,
                         clock=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['reason'], 'observation_deadline')
        self.assertEqual(result['lastState'], 'processing')

        calls = []

        def disconnected():
            calls.append(1)
            raise ConnectionError

        result = observe(disconnected, timeout=10, clock=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(len(calls), 1)

    def test_terminal_response_after_deadline_does_not_count(self):
        clock = Clock()

        def read():
            clock.sleep(6)
            return {'status': 'completed'}

        result = observe(read, timeout=5, clock=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['reason'], 'observation_deadline')
        self.assertEqual(result['transitions'], [])


if __name__ == '__main__':
    unittest.main()
