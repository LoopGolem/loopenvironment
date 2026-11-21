# SPDX-License-Identifier: Apache-2.0
"""Isolated Python worker startup checks without a desktop or installed unit."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from loopbridge.identity import Identities
from loopbridge.private_session import isolated_python, terminate, wait_ready
from loopbridge.service_diagnostics import Diagnostic, Phase, Reason


CHECKOUT = Path(__file__).resolve().parents[1]
BOOTSTRAP = '''
import sys
from pathlib import Path

app = sys.argv[1]
assert sys.flags.isolated and sys.dont_write_bytecode
assert app not in sys.path
sys.path.insert(0, app)
'''

FIXTURE_WORKER = '''
from loopbridge.adapter import Adapter, StartupFailed

if sys.argv[2] == 'remove_worker_path':
    from multiprocessing import spawn
    get_data = spawn.get_preparation_data

    def without_app(name):
        data = get_data(name)
        data['sys_path'].remove(app)
        return data

    spawn.get_preparation_data = without_app

try:
    adapter = Adapter('fixture')
except StartupFailed as error:
    raise SystemExit(str(error)) from None
try:
    assert adapter.source == 'fixture_query'
    argv = Path(f'/proc/{adapter.process.pid}/cmdline').read_bytes().split(b'\\0')
    assert b'-I' in argv and b'-B' in argv
    assert adapter.call('snapshot')[0] == {'display': ''}
    print('fixture worker ready')
finally:
    adapter.close()
'''

FAILED_DESKTOP = '''
from loopbridge import adapter, private_session
from multiprocessing.context import SpawnContext, SpawnProcess

def fail(*args, **kwargs):
    raise OSError('private synthetic startup error')

case = sys.argv[3]
if case == 'spawn':
    SpawnProcess.start = fail
elif case == 'pipe':
    SpawnContext.Pipe = fail
elif case == 'timeout':
    adapter.STARTUP_TIMEOUT = .1
elif case == 'broker_write':
    import builtins
    original = builtins.print

    def print_failure(value, *args, **kwargs):
        if value.startswith('error:'):
            raise BrokenPipeError('private synthetic startup error')
        original(value, *args, **kwargs)

    builtins.print = print_failure

private_session.PRIVATE = Path(sys.argv[2])
raise SystemExit(private_session.inside_service(hardened=True))
'''

DESKTOP_STUB = '''
class Desktop:
    source = 'sway_atspi_workspace'

    def __init__(self, *args):
        %s

    def close(self):
        pass
'''


class AdapterSpawnTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='d42c-adapter-test-')))
        self.app = self.root / 'app'
        shutil.copytree(CHECKOUT / 'loopbridge', self.app / 'loopbridge',
                        ignore=shutil.ignore_patterns('__pycache__'))
        self.command = isolated_python('inside_service')[:-1]
        self.env = {'PATH': '/usr/bin', 'LANG': 'C.UTF-8', 'PYTHONPATH': str(self.app)}

    def run_worker(self, case):
        return subprocess.run([*self.command, BOOTSTRAP + FIXTURE_WORKER, self.app, case],
                              cwd=self.app, env=self.env, capture_output=True, text=True,
                              timeout=10, check=False)

    def test_spawn_imports_worker_from_explicit_package_path_with_isolation(self):
        outcome = self.run_worker('normal')
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        self.assertEqual(outcome.stdout, 'fixture worker ready\n')

    def test_missing_spawn_package_path_fails_before_worker_entry(self):
        outcome = self.run_worker('remove_worker_path')
        self.assertEqual(outcome.returncode, 1)
        self.assertIn("ModuleNotFoundError: No module named 'loopbridge'", outcome.stderr)
        self.assertEqual(outcome.stderr.splitlines()[-1], Reason.ADAPTER_STARTUP_EOF)
        self.assertEqual(outcome.stdout, '')

    def check_broker_failure(self, reason, *, case='normal', desktop=DESKTOP_STUB % 'pass', change=None):
        (self.app / 'loopbridge/desktop.py').write_text(desktop, encoding='utf-8')
        if change is not None:
            source = self.app / 'loopbridge/adapter.py'
            previous = (CHECKOUT / 'loopbridge/adapter.py').read_text(encoding='utf-8')
            self.assertIn(change[0], previous)
            source.write_text(previous.replace(*change, 1), encoding='utf-8')
        work = Path(self.enterContext(tempfile.TemporaryDirectory(dir=self.root)))
        for name in ('workspace', 'state'):
            (work / name).mkdir(mode=0o700)
        identities = Identities()
        identities.provision()
        progress = []
        with subprocess.Popen([*self.command, BOOTSTRAP + FAILED_DESKTOP, self.app, work, case],
                              cwd=self.app, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as broker:
            try:
                broker.stdin.write((json.dumps(identities.manifest()) + '\n').encode('ascii'))
                broker.stdin.close()
                with self.assertRaises(Diagnostic) as outcome:
                    wait_ready(broker, time.monotonic() + 10, phase=Phase.DESKTOP_BROKER,
                               progress=progress.append)
                self.assertEqual(outcome.exception.phase, Phase.BROKER_ADAPTER)
                self.assertEqual(outcome.exception.reason, reason)
                self.assertEqual(broker.wait(timeout=5), 1)
                self.assertEqual(broker.stderr.read(), b'')
                self.assertNotIn(b'ready\n', broker.stdout.read())
            finally:
                terminate(broker, timeout=2)
        self.assertEqual(progress, [Phase.BROKER_BOOTSTRAP, Phase.BROKER_STORAGE, Phase.BROKER_ADAPTER])
        self.assertTrue((work / 'state/annotations.sqlite3').is_file())
        self.assertFalse((work / 'runtime/socket/control.sock').exists())
        self.assertFalse((work / 'runtime/socket/relay.sock').exists())

    def test_spawn_failure_reaches_broker(self):
        self.check_broker_failure(Reason.ADAPTER_SPAWN, case='spawn')

    def test_pipe_creation_failure_reaches_broker(self):
        self.check_broker_failure(Reason.ADAPTER_STARTUP_CHANNEL, case='pipe')

    def test_worker_setup_failure_reaches_broker(self):
        self.check_broker_failure(Reason.ADAPTER_WORKER_INIT,
                                  change=('os.setsid()', "raise OSError('private synthetic startup error')"))

    def test_worker_import_failure_reaches_broker(self):
        self.check_broker_failure(Reason.ADAPTER_IMPORT,
                                  desktop="raise ImportError('private synthetic startup error')\n")

    def test_worker_constructor_failure_reaches_broker(self):
        self.check_broker_failure(Reason.ADAPTER_CONSTRUCT,
                                  desktop=DESKTOP_STUB % "raise OSError('private synthetic startup error')")

    def test_worker_exit_before_report_is_generic_eof(self):
        self.check_broker_failure(Reason.ADAPTER_STARTUP_EOF,
                                  desktop=DESKTOP_STUB % 'import os; os._exit(7)')

    def test_worker_startup_wait_timeout_reaches_broker(self):
        self.check_broker_failure(Reason.ADAPTER_STARTUP_TIMEOUT, case='timeout',
                                  desktop=DESKTOP_STUB % 'import time; time.sleep(30)')

    def test_invalid_startup_records_fail_closed(self):
        send_ready = 'channel.send_bytes(ready)'
        for frame in (b'ready:private synthetic', b'error:adapter_spawn', b'x' * 80):
            with self.subTest(frame=frame):
                self.check_broker_failure(Reason.ADAPTER_STARTUP_CHANNEL,
                                          change=(send_ready, f'channel.send_bytes({frame!r})'))

    def test_worker_rejects_unknown_source_before_sending_ready(self):
        self.check_broker_failure(Reason.ADAPTER_STARTUP_CHANNEL,
                                  desktop=(DESKTOP_STUB % 'pass').replace('sway_atspi_workspace', 'private synthetic'))

    def test_truncated_startup_record_with_open_pipe_fails_closed(self):
        self.check_broker_failure(
            Reason.ADAPTER_STARTUP_CHANNEL,
            change=('channel.send_bytes(ready)',
                    "os.write(channel.fileno(), b'\\x00\\x00\\x00\\x08re'); import time; time.sleep(30)"),
        )

    def test_worker_diagnostic_write_failure_falls_back_to_worker_eof(self):
        self.check_broker_failure(Reason.ADAPTER_STARTUP_EOF,
                                  desktop=DESKTOP_STUB % "raise OSError('private synthetic startup error')",
                                  change=("channel.send_bytes(b'error:' + startup_failure.encode('ascii'))",
                                          "raise BrokenPipeError('private synthetic startup error')"))

    def test_broker_diagnostic_write_failure_falls_back_to_broker_eof(self):
        self.check_broker_failure(Reason.EOF, case='broker_write',
                                  desktop=DESKTOP_STUB % "raise OSError('private synthetic startup error')")
