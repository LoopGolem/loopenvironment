# SPDX-License-Identifier: Apache-2.0
"""Collect and compare read-only Sway baseline digests for lab qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct

from loopbridge.linux_desktop import process_identity
from loopbridge.service_ingress import peer_identity

SCHEMA = 'sway-baseline/1'
STRUCTURAL = ('compositor', 'ipc_socket', 'version', 'config_file_identity',
              'config_file_content', 'loaded_config', 'output_identity')
DYNAMIC = ('workspaces', 'focus', 'containers_and_visual_state',
           'output_modes_and_geometry', 'output_state')
OUTPUT_IDENTITY = ('name', 'make', 'model', 'serial')
OUTPUT_GEOMETRY = ('modes', 'current_mode', 'rect', 'scale', 'transform')
IPC_HEADER = struct.Struct('=6sII')
QUERY_TYPES = {'workspaces': 1, 'outputs': 3, 'tree': 4, 'version': 7, 'config': 9}
CAPTURE_ERRORS = (OSError, ValueError, TypeError, LookupError, struct.error, RecursionError)


def digest(value):
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def query(socket_path, pid, name):
    # Only the fixed GET requests above can be sent. No command or event subscription.
    command = QUERY_TYPES[name]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect(str(socket_path))
        if peer_identity(conn)[:2] != (pid, os.geteuid()):
            raise ValueError('unexpected IPC peer')
        conn.sendall(IPC_HEADER.pack(b'i3-ipc', 0, command))
        with conn.makefile('rb') as reply:
            magic, size, received_type = IPC_HEADER.unpack(reply.read(IPC_HEADER.size))
            if magic != b'i3-ipc' or received_type != command or size > 16 * 1024 * 1024:
                raise ValueError('invalid IPC reply header')
            payload = reply.read(size)
            if len(payload) != size:
                raise ValueError('incomplete IPC reply')
            return json.loads(payload)


def file_identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)


def session_identity(pid, socket_path):
    process = process_identity(pid)
    if process[2] != os.geteuid() or not socket_path.is_absolute():
        raise ValueError('expected the desktop UID and an absolute socket path')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    info = socket_path.lstat()
    if not boot or not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError('invalid desktop socket or boot identity')
    return (boot, process), (str(socket_path), file_identity(info))


def config_components(path):
    if not path.is_absolute():
        raise ValueError('expected an absolute configuration path')
    resolved = path.resolve(strict=True)
    fd = os.open(resolved, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('configuration must be a regular file')
        content = hashlib.sha256()
        while chunk := source.read(65536):
            content.update(chunk)
        after = os.fstat(source.fileno())
        current = path.stat()
    if (path.resolve(strict=True) != resolved
            or file_identity(before) != file_identity(after)
            or file_identity(after) != file_identity(current)
            or not before.st_mtime_ns == after.st_mtime_ns == current.st_mtime_ns
            or not before.st_ctime_ns == after.st_ctime_ns == current.st_ctime_ns):
        raise ValueError('configuration changed during read')
    return {
        'config_file_identity': digest((str(path), str(resolved), file_identity(before))),
        'config_file_content': content.hexdigest(),
    }


def by_name(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('expected a nonempty list of desktop objects')
    names = [row['name'] for row in rows]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise ValueError('invalid desktop object names')
    return sorted(rows, key=lambda row: row['name'])


def output_components(rows):
    identities, geometry, state = [], [], []
    for row in by_name(rows):
        identity = {key: row[key] for key in OUTPUT_IDENTITY}
        if (any(not isinstance(value, str) for value in identity.values())
                or type(row['active']) is not bool):
            raise ValueError('invalid output identity or activity')
        if row['active']:
            for field in ('current_mode', 'rect'):
                size = row[field]
                if any(type(size[key]) is not int or size[key] <= 0 for key in ('width', 'height')):
                    raise ValueError('invalid active output dimensions')
        identities.append(identity)
        geometry.append({key: row[key] for key in OUTPUT_GEOMETRY if key in row})
        state.append({key: value for key, value in row.items()
                      if key not in OUTPUT_IDENTITY and key not in OUTPUT_GEOMETRY})
    return {'output_identity': digest(identities), 'output_modes_and_geometry': digest(geometry),
            'output_state': digest(state)}


def tree_without_focus(node, focus):
    if (type(node['id']) is not int or type(node['focused']) is not bool
            or not isinstance(node['focus'], list)
            or any(type(child) is not int for child in node['focus'])):
        raise ValueError('invalid tree focus data')
    focus.append((node['id'], node['focused'], node['focus']))
    result = {key: value for key, value in node.items() if key not in ('focus', 'focused')}
    for kind in ('nodes', 'floating_nodes'):
        if not isinstance(node[kind], list):
            raise ValueError('invalid tree children')
        result[kind] = [tree_without_focus(child, focus) for child in node[kind]]
    return result


def capture(pid, socket_path):
    components = dict.fromkeys(STRUCTURAL + DYNAMIC)
    try:
        first = session_identity(pid, socket_path)
    except CAPTURE_ERRORS:
        return {'schema': SCHEMA, 'components': components}

    try:
        version = query(socket_path, pid, 'version')
        config_path = version.pop('loaded_config_file_name')
        if (not isinstance(version['human_readable'], str) or not version['human_readable']
                or any(type(version[key]) is not int for key in ('major', 'minor', 'patch'))):
            raise ValueError('missing compositor version')
        components['version'] = digest(version)
        components.update(config_components(Path(config_path)))
    except CAPTURE_ERRORS:
        pass
    try:
        loaded = query(socket_path, pid, 'config')['config']
        if not isinstance(loaded, str):
            raise ValueError('invalid loaded configuration')
        components['loaded_config'] = hashlib.sha256(loaded.encode()).hexdigest()
    except CAPTURE_ERRORS:
        pass
    try:
        components.update(output_components(query(socket_path, pid, 'outputs')))
    except CAPTURE_ERRORS:
        pass

    workspace_focus = tree_focus = None
    try:
        workspaces = by_name(query(socket_path, pid, 'workspaces'))
        flags = [(row['name'], row['focused']) for row in workspaces]
        if any(type(focused) is not bool for _, focused in flags):
            raise ValueError('invalid workspace focus')
        components['workspaces'] = digest([
            {key: value for key, value in row.items() if key != 'focused'} for row in workspaces
        ])
        workspace_focus = flags
    except CAPTURE_ERRORS:
        pass
    try:
        focus = []
        tree = query(socket_path, pid, 'tree')
        if tree['type'] != 'root':
            raise ValueError('invalid desktop tree root')
        components['containers_and_visual_state'] = digest(tree_without_focus(tree, focus))
        tree_focus = sorted(focus)
    except CAPTURE_ERRORS:
        pass
    if workspace_focus is not None and tree_focus is not None:
        components['focus'] = digest((workspace_focus, tree_focus))

    try:
        if session_identity(pid, socket_path) != first:
            raise ValueError('session identity changed during capture')
        components['compositor'], components['ipc_socket'] = map(digest, first)
    except CAPTURE_ERRORS:
        components = dict.fromkeys(components)
    return {'schema': SCHEMA, 'components': components}


def snapshot_components(snapshot):
    if isinstance(snapshot, dict) and snapshot.get('schema') == SCHEMA:
        values = snapshot.get('components')
        if isinstance(values, dict):
            return {key: value for key, value in values.items()
                    if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)}
    return {}


def compare(before, after, expected_dynamic=()):
    old, new = map(snapshot_components, (before, after))
    missing = [key for key in STRUCTURAL + DYNAMIC if key not in old or key not in new]
    structural = [key for key in STRUCTURAL if key not in missing and old[key] != new[key]]
    dynamic = [key for key in DYNAMIC if key not in missing and old[key] != new[key]]
    unexpected = [key for key in dynamic if key not in expected_dynamic]
    if missing:
        result = 'insufficient_evidence'
    elif structural or unexpected:
        result = 'unexpected_change'
    elif dynamic:
        result = 'expected_dynamic_change'
    else:
        result = 'unchanged'
    return {'result': result, 'missing_components': missing, 'structural_changed': structural,
            'dynamic_changed': dynamic, 'unexpected_dynamic': unexpected}


def load_snapshot(path):
    try:
        return json.loads(path.read_text())
    except CAPTURE_ERRORS:
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    collect = actions.add_parser('capture')
    collect.add_argument('--pid', type=int, required=True)
    collect.add_argument('--socket', type=Path, required=True)
    diff = actions.add_parser('compare')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    diff.add_argument('--expect-dynamic', choices=DYNAMIC, action='append', default=[])
    args = parser.parse_args()
    if args.action == 'capture':
        report = capture(args.pid, args.socket)
        exit_code = 2 if None in report['components'].values() else 0
    else:
        report = compare(load_snapshot(args.before), load_snapshot(args.after), args.expect_dynamic)
        exit_code = {'insufficient_evidence': 2, 'unexpected_change': 1}.get(report['result'], 0)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
