# SPDX-License-Identifier: Apache-2.0
"""Verify authorized virtual pointer and keyboard effects through MCP and AT-SPI."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

from loopbridge.__main__ import provision, read_private
from loopbridge.protocol import Fault
from loopbridge.service import DESKTOP_SESSION, Journal

from .loopbridge_demo import Process
from .loopbridge_desktop_demo import grant
from .loopbridge_private_demo import connect_rpc
from .loopbridge_view import capture
from .mcp_mission import Client, SESSION, require, window


def node(client, app, predicate):
    ref, offset = window(client, app), 0
    while offset is not None:
        page = client.call('element_tree', **SESSION, ref=ref, offset=offset, depth=40)
        for item in page['elements']:
            if predicate(item):
                return item['ref']
        offset = page['next']
    raise RuntimeError('atspi_target_not_found')


def display(client):
    ref = node(client, 'calculator', lambda item: item['role'] == 'text' and 'Text' in item['interfaces'])
    return client.call('element_get_text', **SESSION, ref=ref)['text']


def confirmed(client, method, **params):
    reply = client.call(method, **params)
    require(reply['status'] == 'confirmed', 'unexpected_tool_result')
    return reply


def run(root, proof, override=None, screenshot=None):
    with ExitStack() as stack:
        creds = root / 'credentials'
        provision(creds)
        token = read_private(creds / 'owner.token').strip()
        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private', '--root',
                                  root / 'private', '--credentials', creds / 'service.json'])
        require(manager.line() == b'ready\n', 'manager_not_ready')
        private = connect_rpc(stack, root / 'private/manager.sock', token).call('private.start')
        owner = connect_rpc(stack, private['socket'], token)
        for cap in ('session.discover', 'desktop.input', 'desktop.capture', 'workspace.read', 'workspace.write'):
            grant(owner, 'delegate', cap)
        for app in ('calculator', 'editor'):
            for cap in ('app.launch', 'app.close', 'desktop.observe'):
                grant(owner, 'delegate', cap, 'app:' + app)
        command = [sys.executable, '-B', '-m', 'tools.loopbridge_mcp_sandbox', '--socket',
                   private['socket'], '--token-file', creds / 'delegate.token']
        with Client(command, modern=True) as client:
            permit = client.call('lease_acquire', **SESSION, ttl=150)
            lease = dict(**SESSION, lease=permit['id'], generation=permit['generation'], epoch=permit['epoch'])

            def fresh():
                return client.call('session_capture', **SESSION)['ref']

            proof['stage'] = 'calculator'
            confirmed(client, 'app_launch', **lease, app='calculator')
            before = display(client)
            seven = node(client, 'calculator', lambda item: item['name'] == '7' and 'click' in item['actions'])
            client.call('element_inspect', **SESSION, ref=seven)
            if screenshot:
                screenshot.write_bytes(capture(private['socket'], token, DESKTOP_SESSION))
            require(override is not None, 'choose_the_calculator_button_visually')
            proof['clickTarget'] = dict(name='7', position=override, source='lab_visual')
            confirmed(client, 'session_pointer_click', **lease, ref=fresh(), x=override[0], y=override[1])
            after = display(client)
            require(after != before and after.strip() == '7', 'calculator_click_not_confirmed_by_atspi')
            proof['calculator'] = dict(before=before, after=after, independent='atspi_display')
            confirmed(client, 'app_close', **lease, app='calculator')

            proof['stage'] = 'editor'
            confirmed(client, 'workspace_write', **lease, path='keyboard.txt', text='')
            confirmed(client, 'app_open_document', **lease, app='editor', document='keyboard.txt')
            entry = lambda: node(client, 'editor', lambda item: item['editable'] and 'multi_line' in item['state'])
            require(client.call('element_get_text', **SESSION, ref=entry())['text'] == '', 'editor_not_empty')
            confirmed(client, 'session_pointer_click', **lease, ref=fresh(), x=400, y=300)
            typed = 'Private keyboard 42!'
            confirmed(client, 'session_keyboard_type', **lease, ref=fresh(), text=typed)
            require(client.call('element_get_text', **SESSION, ref=entry())['text'] == typed,
                    'editor_typing_not_confirmed_by_atspi')
            confirmed(client, 'session_keyboard_key', **lease, ref=fresh(), key='BackSpace')
            state = ''
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and state != typed[:-1]:
                state = client.call('element_get_text', **SESSION, ref=entry())['text']
                if state != typed[:-1]:
                    time.sleep(.05)
            proof['editor'] = dict(characters=len(typed), backspace=(state == typed[:-1]),
                                   observedCharactersAfterKey=len(state), independent='atspi_text')
            require(state == typed[:-1], 'editor_key_not_confirmed_by_atspi')
        proof['stage'] = 'completed'
        proof['result'] = 'GO'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visual-point', nargs=2, type=int)
    parser.add_argument('--lab-screenshot', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='lb6-input-'))
    proof = dict(result='PARTIAL', stage='startup')
    start = time.monotonic()
    try:
        run(root, proof, args.visual_point, args.lab_screenshot)
    except (RuntimeError, OSError, EOFError, ValueError, KeyError, Fault) as error:
        proof['failure'] = str(error) if type(error) in (RuntimeError, Fault) else type(error).__name__
    finally:
        if any(Journal(path).blocked(DESKTOP_SESSION) for path in root.glob('private/*/runtime')):
            shutil.rmtree(root / 'credentials', ignore_errors=True)
            proof['blockedRootPreserved'] = True
        else:
            shutil.rmtree(root)
    proof['elapsedSeconds'] = round(time.monotonic() - start, 3)
    with args.evidence.open('x') as stream:
        print(json.dumps(proof, indent=2), file=stream)
    print(proof['result'], proof['stage'], proof.get('failure', ''))
    return int(proof['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
