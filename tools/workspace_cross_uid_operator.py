# SPDX-License-Identifier: Apache-2.0
"""Root operator provisioning, retained evidence, and guarded cleanup for D.2C.2."""
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import stat
import subprocess
import tarfile
import sqlite3
from contextlib import closing
from time import monotonic, time

from experiments.registry_operational import POLICY_FILE
from experiments.registry_storage import trusted_directory
from experiments.workspace_document import FINAL, resource_path, stage_name
from experiments.workspace_effect_lab import DATABASE
from loopbridge.service_ingress import ACCESS_ACL, DEFAULT_ACL, named_user_acl, path_inode, read_acl
from tools import sway_baseline
from tools.registry_cross_uid import check_metadata, require
from tools.workspace_cross_uid import (APPROVAL, CHALLENGE, DESKTOP, EVIDENCE, EXECUTION, INSPECTION, LIFECYCLE,
                                       MARKER, MAX_WINDOW, PROFILE, REVISION, SERVICE, SNAPSHOT, SOURCE, THIRD,
                                       json_file, kernel_identity,
                                       parse_approval, process_record, read_approval,
                                       read_marker, root_only, run_session, write_json)
from tools.workspace_cross_uid_fixture import CASES, HEX
from tools.workspace_cross_uid_flow import Verifier

MAX_ARCHIVE = 32 * 1024 * 1024


def sha_file(path, *, limit=MAX_ARCHIVE):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'unsafe_digest_input')
        result = file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'digest_input_changed')
    return result


def trusted_source(source, archive, revision, expected):
    """Check the deployed tree byte-for-byte against the independently approved Git TAR."""
    require(source == Path('/opt') / f'loop-d2c2-{revision}' and archive.is_absolute()
            and HEX.fullmatch(expected) and sha_file(archive) == expected, 'source_archive_mismatch')
    with trusted_directory(source) as fd:
        check_metadata(os.fstat(fd), (0, 0), 0o755, stat.S_ISDIR, 'unsafe_source_root')
        require(read_acl(fd) is None and read_acl(fd, DEFAULT_ACL) is None, 'unsafe_source_acl')
    actual = {}
    # Bound enumeration and reject symlinks before descending their paths.
    for parent, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            info = path.lstat()
            require(len(actual) < 2000 and (info.st_uid, info.st_gid) == (0, 0)
                    and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                    and read_acl(path) is None and read_acl(path, DEFAULT_ACL) is None,
                    'unsafe_source_artifact')
            actual[path.relative_to(source).as_posix()] = info
    with tarfile.open(archive, mode='r:') as tar:
        require(tar.pax_headers.get('comment') == revision, 'archive_revision_mismatch')
        for member in tar:
            name = PurePosixPath(member.name)
            require(not name.is_absolute() and '..' not in name.parts and name.as_posix() in actual
                    and (member.isdir() or member.isfile()), 'unexpected_archive_entry')
            info = actual.pop(name.as_posix())
            if member.isdir():
                require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755,
                        'source_directory_mode')
            else:
                path = source / name.as_posix()
                mode = 0o755 if member.mode & 0o111 else 0o644
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == mode
                        and info.st_size == member.size, 'source_file_mode_or_size')
                with tar.extractfile(member) as archived:
                    require(sha_file(path) == file_digest(archived, 'sha256').hexdigest(), 'source_bytes_changed')
    require(not actual and sha_file(archive) == expected and (source / 'tools/sway_baseline.py').is_file(),
            'source_tree_mismatch')


def installed_unit():
    args = ['/usr/bin/systemctl']
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'SYSTEMD_PAGER': 'cat'}
    show = subprocess.check_output(args + ['show', 'loopbridge.service',
                                           '--property=ActiveState,UnitFileState,FragmentPath,MainPID'],
                                   env=env, stderr=subprocess.DEVNULL, timeout=5)
    fields = dict(line.split(b'=', 1) for line in show.splitlines())
    require(fields.keys() == {b'ActiveState', b'UnitFileState', b'FragmentPath', b'MainPID'}
            and fields[b'ActiveState'] == b'inactive' and fields[b'UnitFileState'] == b'disabled'
            and fields[b'MainPID'] == b'0' and fields[b'FragmentPath'].startswith(b'/'),
            'installed_unit_baseline_invalid')
    body = subprocess.check_output(args + ['cat', 'loopbridge.service'],
                                   env=env, stderr=subprocess.DEVNULL, timeout=5)
    return sha256(show + b'\0' + body).hexdigest()


def verify_accounts():
    names = ('loopbridge-svc', 'vboxuser', 'nobody')
    for name, pair in zip(names, (SERVICE, DESKTOP, THIRD), strict=True):
        account = pwd.getpwnam(name)
        require((account.pw_uid, account.pw_gid) == pair and pwd.getpwuid(pair[0]).pw_name == name,
                'unexpected_lab_account')
        if pair == THIRD:
            require(account.pw_shell in ('/usr/sbin/nologin', '/bin/false')
                    and os.getgrouplist(name, pair[1]) == [pair[1]], 'invalid_non_admitted_peer')
    release = Path('/etc/os-release').read_text().splitlines()
    require('ID=debian' in release, 'debian_lab_required')


def prepare(args, layout):
    verify_accounts()
    kernel = kernel_identity()
    require(kernel == dict(clone_dmi=args.clone_dmi, machine_id=args.machine_id,
                           boot_id=args.boot_id, hostname=args.hostname)
            and args.source_dmi != args.clone_dmi, 'clone_binding_mismatch')
    require(REVISION.fullmatch(args.revision) and SNAPSHOT.fullmatch(args.snapshot), 'invalid_source_or_snapshot')
    os.close(os.pidfd_open(os.getpid()))
    trusted_source(SOURCE, args.archive, args.revision, args.archive_sha256)
    baseline_hash = sha_file(args.sway_before, limit=16384)
    baseline = sway_baseline.load_snapshot(args.sway_before)
    require(sway_baseline.compare(baseline, baseline)['result'] == 'unchanged'
            and sha_file(args.sway_before, limit=16384) == baseline_hash, 'incomplete_sway_baseline')
    unit = installed_unit()
    layout.root.mkdir(mode=0o755)
    for child, uid in ((layout.private, None), (layout.ingress, DESKTOP[0]), (layout.challenge, THIRD[0])):
        child.mkdir(mode=0o700)
        os.chown(child, *SERVICE)
        if uid is not None:
            os.setxattr(child, ACCESS_ACL, named_user_acl(uid, 7, 1))
    marker = dict(version=1, profile=PROFILE, run_id=args.run_id, revision=args.revision, snapshot=args.snapshot,
                  archive_sha256=args.archive_sha256, source_dmi=args.source_dmi, **kernel,
                  sway_before_sha256=baseline_hash, unit_before_sha256=unit,
                  root_pin=list(path_inode(layout.root.lstat())),
                  children={name: list(path_inode((layout.root / name).lstat()))
                            for name in ('private', 'ingress', 'challenge')},
                  identities=dict(service=list(SERVICE), desktop=list(DESKTOP), third=list(THIRD)))
    write_json(layout.root / MARKER, marker)
    read_marker(layout, args.run_id)
    print(json.dumps(dict(status='PREPARED / NOT EXECUTED', fixture=marker), sort_keys=True))


def approve(args, layout):
    marker = read_marker(layout, args.run_id)
    require(args.confirm_run == args.run_id and args.snapshot == marker['snapshot']
            and 0 < args.seconds <= MAX_WINDOW and not os.path.lexists(layout.root / EXECUTION),
            'operator_approval_required')
    issued, elapsed = int(time()), int(monotonic())
    approval = dict(version=1, profile=PROFILE, fixture=marker, issued_unix=issued, issued_monotonic=elapsed,
                    expires_unix=issued + args.seconds, expires_monotonic=elapsed + args.seconds)
    parse_approval(approval, marker, wall=time(), elapsed=monotonic(), fresh=True)
    write_json(layout.root / APPROVAL, approval)
    print(json.dumps(dict(status='approved', run_id=args.run_id, expires_unix=approval['expires_unix'],
                          expires_monotonic=approval['expires_monotonic']), sort_keys=True))


def execute(args, layout):
    marker, _ = read_approval(layout, args.run_id, fresh=True)
    trusted_source(SOURCE, args.archive, marker['revision'], marker['archive_sha256'])
    verify_accounts()
    require(installed_unit() == marker['unit_before_sha256'], 'installed_unit_baseline_changed')
    marker, window = read_approval(layout, args.run_id, fresh=True)
    write_json(layout.root / EXECUTION, dict(controller=process_record(os.getpid()), run_id=args.run_id))
    path = layout.root / EVIDENCE
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600),
                   'w') as out:
        result = run_session(layout, args.run_id, window, out, real=True, marker=marker)
        os.fsync(out.fileno())
    print(json.dumps(dict(run_id=args.run_id, evidence=str(path), exit_code=result), sort_keys=True))
    return result


def decode_mount_path(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def mount_free(root):
    with open('/proc/self/mountinfo') as records:
        for record in records:
            path = Path(decode_mount_path(record.split()[4]))
            require(path != root and root not in path.parents, 'fixture_contains_mount')


def occupants_exited(lifecycle):
    require(lifecycle.keys() == {'pins', 'processes', 'endpoint_pin'} and
            type(lifecycle['processes']) is list and bool(lifecycle['processes']), 'lifecycle_missing')
    identities = set()
    for process in lifecycle['processes']:
        require(type(process['exit_code']) is int and type(process['identity']) is dict
                and process['pid'] == process['identity']['pid'] and process['pid'] > 1,
                'process_lifecycle_incomplete')
        identity = process['identity']
        pid = identity['pid']
        key = (pid, identity['start_ticks'])
        require(key not in identities, 'duplicate_process_lifecycle')
        identities.add(key)
        try:
            current = process_record(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
        require(current['start_ticks'] != key[1], 'fixture_process_still_live')


def expected_inventory(layout, lifecycle):
    pin = lifecycle['pins']
    require(pin is not None, 'fixture_pins_unavailable')
    verifier = Verifier(layout, pin, SERVICE)
    verifier.policy_and_storage()
    files = {DATABASE, POLICY_FILE}
    stages = {resource: {} for resource in verifier.resources}
    # Derive exact entries from durable operation IDs. A lookalike basename
    # with no durable attribution is grounds to retain the whole fixture.
    final_pins = {resource: set() for resource in verifier.resources}
    with closing(sqlite3.connect((layout.private / DATABASE).as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        rows = db.execute('SELECT id FROM workspace_attempts').fetchall()
    case_names = {case.scope.attempt_id: name for name, case in CASES.items()}
    for (attempt_id,) in rows:
        require(attempt_id in case_names, 'unrecognized_durable_attempt')
        entry, _ = verifier.durable(case_names[attempt_id])
        if entry['stage_ino'] is not None:
            resource = entry['resource_id']
            pin = (entry['stage_dev'], entry['stage_ino'])
            stages[resource][stage_name(entry['operation_id'])] = pin
            final_pins[resource].add(pin)
    require({p.name for p in layout.private.iterdir()} ==
            files | {resource_path(layout.private, resource).name for resource in verifier.resources},
            'unexpected_private_artifact')
    inventory = {}

    def record(path, owner, mode, kind):
        info = check_metadata(path.lstat(), owner, mode, kind, 'unexpected_cleanup_metadata')
        inventory[str(path.relative_to(layout.root))] = dict(pin=path_inode(info), mode=mode, uid=info.st_uid,
                                                              gid=info.st_gid, nlink=info.st_nlink)

    for path in (layout.root / name for name in (MARKER, APPROVAL, EXECUTION, LIFECYCLE, EVIDENCE)):
        record(path, (0, 0), 0o444 if path.name in (MARKER, APPROVAL, EXECUTION) else 0o600, stat.S_ISREG)
        require(path.lstat().st_nlink == 1 and read_acl(path) is None, 'unexpected_control_artifact')
    for file in files:
        path = layout.private / file
        record(path, SERVICE, 0o600, stat.S_ISREG)
        require(path.lstat().st_nlink == 1 and read_acl(path) is None, 'unexpected_private_artifact')
    for resource in verifier.resources:
        path = resource_path(layout.private, resource)
        record(path, SERVICE, 0o700, stat.S_ISDIR)
        for child in path.iterdir():
            allowed = final_pins[resource] if child.name == FINAL else {stages[resource].get(child.name)}
            record(child, SERVICE, 0o600, stat.S_ISREG)
            info = child.lstat()
            require(path_inode(info) in allowed and info.st_nlink in (1, 2) and read_acl(child) is None,
                    'unexpected_resource_artifact')
    for directory, mode in ((layout.private, 0o700), (layout.ingress, 0o710), (layout.challenge, 0o710)):
        record(directory, SERVICE, mode, stat.S_ISDIR)
    return inventory


def cleanup_observation(layout, run_id, *, has_inspection):
    marker = read_marker(layout, run_id)
    mount_free(layout.root)
    lifecycle = json_file(layout.root / LIFECYCLE, owner=(0, 0), mode=0o600)
    occupants_exited(lifecycle)
    broker = [record for record in lifecycle['processes'] if record['role'] == 'broker']
    require(broker and not any(layout.ingress.iterdir()) and not any(layout.challenge.iterdir()),
            'fixture_ingress_not_empty')
    with open('/proc/net/unix') as sockets:
        require(not any(line.split(maxsplit=7)[-1].strip().startswith(str(layout.root) + '/')
                        for line in sockets if line.strip()), 'fixture_has_live_unix_endpoint')
    expected = {MARKER, APPROVAL, EXECUTION, LIFECYCLE, EVIDENCE, 'private', 'ingress', 'challenge'}
    if has_inspection:
        expected.add(INSPECTION)
    require({p.name for p in layout.root.iterdir()} == expected, 'fixture_root_inventory_changed')
    require(installed_unit() == marker['unit_before_sha256'], 'installed_unit_baseline_changed')
    return dict(fixture=marker, broker_pids=[record['pid'] for record in broker],
                identified_processes=len(lifecycle['processes']), all_identified_exited=True,
                sockets_absent=True, mounts_absent=True, installed_unit_sha256=marker['unit_before_sha256'],
                evidence_sha256=sha_file(layout.root / EVIDENCE), entries=expected_inventory(layout, lifecycle))


def inspect(args, layout):
    result = cleanup_observation(layout, args.run_id, has_inspection=False)
    write_json(layout.root / INSPECTION, result, mode=0o600)
    print(json.dumps(dict(status='inspection_recorded', inspection=str(layout.root / INSPECTION),
                          inspection_sha256=sha_file(layout.root / INSPECTION),
                          evidence_sha256=result['evidence_sha256']), sort_keys=True))


def cleanup(args, layout):
    require(args.confirm_run == args.run_id and HEX.fullmatch(args.inspection_sha256)
            and args.retained_evidence.is_absolute() and args.retained_evidence.resolve() == args.retained_evidence
            and layout.root not in args.retained_evidence.parents, 'separate_cleanup_decision_required')
    current = cleanup_observation(layout, args.run_id, has_inspection=True)
    record = layout.root / INSPECTION
    require(sha_file(record) == args.inspection_sha256
            and json_file(record, owner=(0, 0), mode=0o600) == json.loads(json.dumps(current))
            and sha_file(args.retained_evidence) == current['evidence_sha256'], 'cleanup_evidence_mismatch')
    for relative, expected in sorted(current['entries'].items(), key=lambda entry: -entry[0].count('/')):
        path = layout.root / relative
        # Exact named paths only, after inventory, mount, ownership and inode checks.
        mount_free(layout.root)
        with trusted_directory(path.parent) as directory:
            info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            require(path_inode(info) == expected['pin'] and (info.st_uid, info.st_gid) == (expected['uid'],
                    expected['gid']) and stat.S_IMODE(info.st_mode) == expected['mode'], 'cleanup_entry_changed')
            remove = os.rmdir if stat.S_ISDIR(info.st_mode) else os.unlink
            remove(path.name, dir_fd=directory)
    mount_free(layout.root)
    with trusted_directory(layout.root) as directory:
        require(list(path_inode(os.fstat(directory))) == current['fixture']['root_pin']
                and sha_file(record) == args.inspection_sha256, 'cleanup_fixture_changed')
        os.unlink(INSPECTION, dir_fd=directory)
    layout.root.rmdir()
    final = installed_unit()
    require(final == current['installed_unit_sha256'], 'installed_unit_baseline_changed')
    print(json.dumps(dict(status='cleanup_complete', run_id=args.run_id, installed_unit_sha256=final,
                          evidence_sha256=current['evidence_sha256'], fixture_absent=not layout.root.exists()),
                     sort_keys=True))


def add_operator_commands(commands):
    setup = commands.add_parser('prepare')
    setup.add_argument('--archive', required=True, type=Path)
    setup.add_argument('--sway-before', required=True, type=Path)
    for field in ('revision', 'archive-sha256', 'hostname', 'machine-id', 'boot-id', 'clone-dmi', 'source-dmi',
                  'snapshot'):
        setup.add_argument('--' + field, required=True)
    approve_parser = commands.add_parser('approve')
    approve_parser.add_argument('--confirm-run', required=True)
    approve_parser.add_argument('--snapshot', required=True)
    approve_parser.add_argument('--seconds', required=True, type=int)
    commands.add_parser('execute').add_argument('--archive', required=True, type=Path)
    commands.add_parser('inspect')
    remove = commands.add_parser('cleanup')
    remove.add_argument('--confirm-run', required=True)
    remove.add_argument('--inspection-sha256', required=True)
    remove.add_argument('--retained-evidence', required=True, type=Path)


def operator_command(args, layout):
    root_only()
    actions = dict(prepare=prepare, approve=approve, execute=execute, inspect=inspect, cleanup=cleanup)
    return actions[args.command](args, layout) or 0
