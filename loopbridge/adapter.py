# SPDX-License-Identifier: Apache-2.0
"""Private process boundary for blocking desktop calls."""
from collections import OrderedDict
import multiprocessing
import os
import secrets
import signal
import time

from .protocol import encode


class Unavailable(RuntimeError):
    pass


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


def worker(channel, mode):
    os.setsid()
    # Only this process imports or touches session accessibility objects.
    adapter = None
    try:
        if mode == 'calculator':
            from .calculator import Calculator
            adapter = Calculator()
        else:
            adapter = Fixture()
        channel.send((True, adapter.source))
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
                channel.send((True, result))
            except Exception:
                channel.send((False, None))
    except (Exception, KeyboardInterrupt):
        # The private protocol never exports raw errors or environment data.
        pass
    finally:
        if adapter is not None:
            adapter.close()
        channel.close()


class Adapter:
    def __init__(self, mode):
        ctx = multiprocessing.get_context('spawn')
        self.channel, child = ctx.Pipe()
        self.process = ctx.Process(target=worker, args=(child, mode))
        self.process.start()
        child.close()
        self.faulted = False
        try:
            self.source = self.receive(40)
        except BaseException:
            self.close()
            raise

    def receive(self, timeout):
        try:
            if not self.channel.poll(timeout):
                raise TimeoutError
            ok, value = self.channel.recv()
        except (OSError, EOFError, TimeoutError):
            self.faulted = True
            raise Unavailable from None
        if not ok:
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
        return self.receive(7 if method == 'send' else 12)

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
