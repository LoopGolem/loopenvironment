# SPDX-License-Identifier: Apache-2.0
"""Run one complete suite and one real fixture; record sanitized, reproducible evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import unittest

from experiments.m1_3a.run import execute


class Results(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.ids.append(test.id())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []


def source_hashes():
    paths = sorted(Path('experiments').glob('m1_*/*.py')) + sorted(Path('tests').glob('test_m1_*.py'))
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    # Evidence path must be new before starting any experiment.
    with args.evidence.open('x') as output:
        report = dict(result='PARTIAL', started=datetime.now(timezone.utc).isoformat(),
                      base_commit='76d5504af535d17e94030b7471ca89c18fcff09c',
                      source_sha256=source_hashes(),
                      environment=dict(debian=Path('/etc/debian_version').read_text().strip(),
                                       python=platform.python_version(), kernel=platform.release()))
        packages = subprocess.check_output(['dpkg-query', '-W', '-f=${Package} ${Version}\n',
            'sway', 'bubblewrap', 'gnome-calculator', 'python3-pyatspi', 'at-spi2-core', 'libgtk-4-1'],
            text=True, timeout=3)
        report['environment']['packages'] = packages.splitlines()
        suite = unittest.defaultTestLoader.discover('tests')
        result = unittest.TextTestRunner(verbosity=1, resultclass=Results).run(suite)
        report['tests'] = dict(command='/usr/bin/python3 -m unittest discover -s tests -v',
            executed_by='unittest discovery inside experiments.m1_3a.qualify',
            run=result.testsRun, passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            failures=[t.id() for t, _ in result.failures], errors=[t.id() for t, _ in result.errors],
            skipped=[t.id() for t, _ in result.skipped], ids=result.ids)
        report['abstract_takeover'] = dict(boundary='SIMULATED POLICY ONLY',
            tests=[t for t in result.ids if 'abstract_' in t or 'simulated_barrier' in t],
            real_compositor_preemption=False)
        secret_guard = []
        if result.wasSuccessful():
            report['real'] = dict(result='PARTIAL', clients={})
            try:
                execute(report['real'], secret_guard)
            except Exception as error:
                report['real']['result'] = 'NO-GO' if type(error).__name__ in ('CheckFailed', 'AssertionError') else 'PARTIAL'
                report['real']['failure'] = type(error).__name__
            report['result'] = report['real']['result']
        else:
            report['result'] = 'NO-GO'
        if any(c in json.dumps(report) for c in secret_guard):
            report = dict(result='NO-GO', failure='sensitive_output_removed')
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['result'])
    return 0 if report['result'] == 'GO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
