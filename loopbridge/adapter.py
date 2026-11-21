# SPDX-License-Identifier: Apache-2.0
"""Private process boundary for blocking desktop calls."""
from collections import OrderedDict
from contextlib import suppress
import multiprocessing
import os
import secrets
import signal
import time

from .protocol import encode
from .service_diagnostics import Reason


STARTUP_TIMEOUT = 40
STARTUP_SOURCES = {b'ready:' + source.encode('ascii'): source
                   for source in ('fixture_query', 'atspi_query', 'sway_atspi_workspace')}
STARTUP_FAILURES = {b'error:' + reason.encode('ascii'): reason
                    for reason in (Reason.ADAPTER_WORKER_INIT, Reason.ADAPTER_IMPORT,
                                   Reason.ADAPTER_CONSTRUCT, Reason.ADAPTER_STARTUP_CHANNEL)}
STARTUP_RECORD_LIMIT = max(map(len, STARTUP_SOURCES | STARTUP_FAILURES))


class Unavailable(RuntimeError):
    pass


class Refused(Unavailable):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class StartupFailed(Unavailable):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class Fixture:
    source = 'fixture_query'

    def __init__(self):
        self.value = ''

    def snapshot(self):
        return {'display': self.value}, self.value

    def prepare(self, reference, expected):
        if reference != self.value or expected != {'display': self.value}:
            raise Unavailable
        return self.value

    def send(self, prepared):
        self.value += '7'

    def confirm(self, prepared):
        if self.value != prepared + '7':
            raise Unavailable
        return {'display': self.value}

    def close(self):
        pass


def worker(channel, mode, runtime, workspace):
    # Only this process imports or touches session accessibility objects.
    adapter = None
    startup_failure = Reason.ADAPTER_WORKER_INIT
    try:
        os.setsid()
        startup_failure = Reason.ADAPTER_IMPORT
        if mode == 'calculator':
            from .calculator import Calculator
            factory, arguments = Calculator, ()
        elif mode == 'desktop':
            from .desktop import Desktop
            factory, arguments = Desktop, (runtime, workspace)
        else:
            factory, arguments = Fixture, ()
        startup_failure = Reason.ADAPTER_CONSTRUCT
        adapter = factory(*arguments)
        startup_failure = Reason.ADAPTER_STARTUP_CHANNEL
        ready = b'ready:' + adapter.source.encode('ascii')
        if ready not in STARTUP_SOURCES:
            raise ValueError('invalid adapter startup source')
        startup_failure = None
        channel.send_bytes(ready)
        references = OrderedDict()
        prepared = None
        while True:
            method, argument = channel.recv()
            try:
                if method == 'close':
                    return
                if method == 'snapshot':
                    state, ref = adapter.snapshot()
                    if len(encode(state)) > 4096:
                        raise Unavailable
                    token = secrets.token_hex(16)
                    references[token] = (ref, state)
                    if len(references) > 32:
                        references.popitem(last=False)
                    result = (state, token)
                elif method == 'prepare':
                    prepared = None
                    prepared = adapter.prepare(*references.pop(argument))
                    result = None
                elif method == 'desktop.prepare':
                    prepared = None
                    prepared = adapter.prepare_operation(*argument)
                    result = None
                elif method == 'send':
                    if time.monotonic() >= argument:
                        raise Unavailable
                    adapter.send(prepared)
                    result = None
                elif method == 'confirm':
                    result = adapter.confirm(prepared)
                    prepared = None
                    if len(encode(result)) > 4096:
                        raise Unavailable
                elif method == 'desktop.read':
                    result = adapter.query(*argument)
                    if len(encode(result)) > 6800:
                        raise Refused('response_limit')
                else:
                    raise Refused('unsupported_method')
                channel.send((True, result))
            except Refused as error:
                channel.send((False, error.reason))
            except Exception:
                channel.send((False, None))
    except (Exception, KeyboardInterrupt):
        if startup_failure is not None:
            with suppress(OSError, ValueError):
                channel.send_bytes(b'error:' + startup_failure.encode('ascii'))
    finally:
        channel.close()
        if adapter is not None:
            adapter.close()


class Adapter:
    def __init__(self, mode, runtime=None, workspace=None):
        ctx = multiprocessing.get_context('spawn')
        try:
            self.channel, child = ctx.Pipe()
        except OSError:
            raise StartupFailed(Reason.ADAPTER_STARTUP_CHANNEL) from None
        self.faulted = False
        process = None
        try:
            with child:
                process = ctx.Process(target=worker, args=(child, mode, runtime, workspace))
                process.start()
        except BaseException as error:
            self.channel.close()
            if process is not None:
                if process.is_alive():
                    self.process = process
                    self.faulted = True
                    self.close()
                else:
                    process.close()
            if isinstance(error, Exception):
                raise StartupFailed(Reason.ADAPTER_SPAWN) from None
            raise
        self.process = process
        try:
            self.source = self._startup_source()
        except BaseException:
            self.faulted = True
            self.close()
            raise

    def _startup_source(self):
        # The worker sends one small byte record before operation messages.
        try:
            if not self.channel.poll(STARTUP_TIMEOUT):
                raise TimeoutError
            # A readable socket can contain an incomplete record. Keep that
            # failure bounded, then restore blocking receives for operations.
            fd = self.channel.fileno()
            os.set_blocking(fd, False)
            try:
                record = self.channel.recv_bytes(STARTUP_RECORD_LIMIT)
            finally:
                os.set_blocking(fd, True)
        except TimeoutError:
            raise StartupFailed(Reason.ADAPTER_STARTUP_TIMEOUT) from None
        except EOFError:
            raise StartupFailed(Reason.ADAPTER_STARTUP_EOF) from None
        except OSError:
            raise StartupFailed(Reason.ADAPTER_STARTUP_CHANNEL) from None
        if record in STARTUP_SOURCES:
            return STARTUP_SOURCES[record]
        raise StartupFailed(STARTUP_FAILURES.get(record, Reason.ADAPTER_STARTUP_CHANNEL))

    def receive(self, timeout):
        try:
            if not self.channel.poll(timeout):
                raise TimeoutError
            ok, value = self.channel.recv()
        except (OSError, EOFError, TimeoutError):
            self.faulted = True
            raise Unavailable from None
        if not ok:
            if value is not None:
                raise Refused(value)
            raise Unavailable
        return value

    def call(self, method, argument=None):
        if self.faulted:
            raise Unavailable
        try:
            self.channel.send((method, argument))
        except (OSError, EOFError):
            self.faulted = True
            raise Unavailable from None
        return self.receive({'send': 7, 'confirm': 35}.get(method, 12))

    def close(self):
        if self.process.is_alive() and not self.faulted:
            try:
                self.channel.send(('close', None))
            except OSError:
                pass
            self.process.join(5)
        if self.process.is_alive() or self.faulted:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                if self.process.is_alive():
                    self.process.kill()
        self.process.join()
        self.channel.close()
        self.process.close()
