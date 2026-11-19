# SPDX-License-Identifier: Apache-2.0
"""Disposable, offline Firefox fixture behind the trusted AT-SPI adapter."""
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import parse_qs, urlsplit

from .adapter import Refused
from . import browser_native
from .catalog import CATALOG
from .web_native import ROOT as SITE_ROOT, PAGES as SITE_PAGES
from .linux_desktop import process_identity, wait_for, walk
from .semantic_operations import Prepared, state_flags

EXEC = CATALOG['browser'].executable
BWRAP = '/usr/bin/bwrap'
FORM = 'file:///fixture/form.html'
RECEIPT = 'file:///fixture/receipt.html'
CONTROLS = {'demo-name': ('text', 'entry', 'editable text'), 'alpha': ('radio button',),
            'beta': ('radio button',), 'submit': ('push button', 'button')}
NAMES = {'Demo name': 'demo-name', 'Alpha': 'alpha', 'Beta': 'beta', 'Submit demo': 'submit'}


def ready():
    return all(os.access(path, os.X_OK) for path in (EXEC, BWRAP, '/usr/bin/dbus-run-session'))


def mounted_socket(path):
    if not path.is_absolute() or not stat.S_ISSOCK(path.stat().st_mode):
        raise Refused('browser_socket_unavailable')
    return str(path)


def launch_args(root, site=False):
    from gi.repository import Gio

    if not ready():
        raise Refused('browser_isolation_unavailable')
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    display = mounted_socket(runtime / os.environ['WAYLAND_DISPLAY'])
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    result = bus.call_sync('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Bus',
                           'GetAddress', None, None, Gio.DBusCallFlags.NONE, 2000, None)
    address = result.unpack()[0]
    match = re.fullmatch(r'unix:path=([^,;]+)(?:,guid=[0-9a-f]+)?', address)
    if not match:
        raise Refused('browser_atspi_mount_unavailable')
    atspi = mounted_socket(Path(match[1]))
    home = Path(tempfile.mkdtemp(dir=root, prefix='firefox-'))
    uid, gid = os.getuid(), os.getgid()
    (home / 'passwd').write_text(f'browser:x:{uid}:{gid}:Browser:/home/browser:/bin/false\n')
    (home / 'group').write_text(f'browser:x:{gid}:\n')
    profile = home / 'profile'
    profile.mkdir(mode=0o700)
    (profile / 'user.js').write_text('''user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.newtabpage.enabled", false);
user_pref("network.trr.mode", 5);
user_pref("network.connectivity-service.enabled", false);
user_pref("accessibility.force_disabled", -1);
''')
    args = [BWRAP, '--unshare-all', '--die-with-parent', '--ro-bind', '/usr', '/usr',
            '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
            '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/run/browser', '--dir', '/etc',
            '--ro-bind', '/etc/fonts', '/etc/fonts',
            '--ro-bind', '/etc/machine-id', '/etc/machine-id',
            '--ro-bind', str(home / 'passwd'), '/etc/passwd',
            '--ro-bind', str(home / 'group'), '/etc/group',
            '--ro-bind', display, '/run/browser/wayland-0',
            '--ro-bind', atspi, '/run/browser/atspi',
            '--ro-bind', str(Path(__file__).parent / 'web_fixture'), '/fixture',
            '--ro-bind', str(Path(__file__).with_name('browser_boot.py')), '/browser_boot.py',
            '--ro-bind', str(Path(__file__).with_name('browser_native.py')), '/browser_native.py',
            '--ro-bind', str(Path(__file__).with_name('web_native.py')), '/web_native.py',
            '--bind', str(home), '/home/browser', '--chdir', '/home/browser',
            '--clearenv', '--cap-drop', 'ALL']
    env = dict(PATH='/usr/bin', HOME='/home/browser', XDG_RUNTIME_DIR='/run/browser',
               WAYLAND_DISPLAY='wayland-0', AT_SPI_BUS_ADDRESS='unix:path=/run/browser/atspi',
               MOZ_ENABLE_WAYLAND='1', GTK_A11Y='1', LANG='C.UTF-8', LIBGL_ALWAYS_SOFTWARE='1')
    if site:
        env['LOOPBRIDGE_SITE'] = '1'
    for key, value in env.items():
        args.extend(('--setenv', key, value))
    args.extend(('--', '/usr/bin/dbus-run-session', '--config-file=/fixture/session.conf', '--',
                 '/usr/bin/python3', '-B', '/browser_boot.py', EXEC, '--no-remote', '--new-instance', '--marionette', '--profile',
                 '/home/browser/profile', SITE_ROOT + SITE_PAGES['home'] if site else FORM))
    return args, home


def task_children(pid):
    root = Path(f'/proc/{pid}/task')
    children = set()
    try:
        threads = list(root.iterdir())
    except FileNotFoundError:
        return children
    for task in threads:
        try:
            children.update(int(child) for child in (task / 'children').read_text().split())
        except FileNotFoundError:
            continue
    return children


def process_tree(wrapper):
    """Snapshot descendants pinned by PID start time, UID and kernel namespaces."""
    pending = [wrapper]
    identities = {}
    while pending:
        pid = pending.pop()
        if pid in identities:
            continue
        if len(identities) >= 128:
            raise Refused('browser_process_limit')
        try:
            identity = process_identity(pid)
            identities[pid] = identity
            pending.extend(task_children(pid))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return identities


def lineage(wrapper, pid, expected=None):
    processes = process_tree(wrapper)
    identity = processes.get(pid)
    if (identity is None or identity[2] != os.getuid()
            or identity[3] != os.path.realpath(EXEC)
            or (expected is not None and identity != expected)):
        raise Refused('browser_process_identity_changed')
    host_network = os.readlink('/proc/self/ns/net')
    host_pid = os.readlink('/proc/self/ns/pid')
    executable = os.path.realpath(EXEC)
    allowed = {executable, str(Path(executable).with_name('crashhelper'))}
    descendants = process_tree(pid)
    for child, record in descendants.items():
        if (record[2] != os.getuid() or record[3] not in allowed
                or os.readlink(f'/proc/{child}/ns/net') == host_network
                or os.readlink(f'/proc/{child}/ns/pid') == host_pid):
            raise Refused('browser_subprocess_identity_changed')
    return identity, len(descendants) - 1


def active_document(frame):
    documents = [(node, node.queryDocument().getAttributeValue('DocURL')) for _, node in walk(frame)
                 if node and node.getRoleName() in ('document web', 'document frame')
                 and 'Document' in node.get_interfaces() and 'showing' in state_flags(node)]
    if len(documents) != 1:
        raise Refused('browser_document_ambiguous')
    return documents[0]


def known_document(frame):
    node, uri = active_document(frame)
    parsed = urlsplit(uri)
    if uri != FORM and (parsed.scheme, parsed.netloc, parsed.path, parsed.fragment) != (
            'file', '', '/fixture/receipt.html', ''):
        raise Refused('browser_document_outside_fixture')
    return node, uri


def identifier(node):
    native = next((item.removeprefix('id:') for item in node.getAttributes()
                   if item.startswith('id:')), '')
    if native:
        return native
    # Gecko can omit DOM attributes across IPC. The static fixture, role and
    # unique name locate the accessibility peer; the native endpoint still
    # independently addresses the allowlisted DOM ID.
    key = NAMES.get(node.name)
    return key if key and node.getRoleName() in CONTROLS[key] else ''


def control(frame, node, allowed):
    doc, uri = known_document(frame)
    if uri != FORM:
        raise Refused('browser_form_unavailable')
    key = identifier(node)
    if key not in allowed or node.getRoleName() not in CONTROLS[key]:
        raise Refused('browser_control_outside_fixture')
    matches = [child for _, child in walk(doc) if child and identifier(child) == key]
    if len(matches) != 1 or matches[0] != node:
        raise Refused('browser_control_ambiguous')
    return key


def allowed_text(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ]{0,39}', value):
        raise Refused('invalid_demo_text')
    return value


def form_values(frame):
    doc, uri = known_document(frame)
    if uri != FORM:
        raise Refused('browser_form_unavailable')
    found = {}
    for _, child in walk(doc):
        if not child:
            continue
        key = identifier(child)
        if key not in ('demo-name', 'alpha', 'beta'):
            continue
        if key in found:
            raise Refused('browser_control_ambiguous')
        found[key] = child
    if set(found) != {'demo-name', 'alpha', 'beta'}:
        raise Refused('browser_form_incomplete')
    checked = [item for item in ('alpha', 'beta') if 'checked' in state_flags(found[item])]
    if len(checked) != 1:
        raise Refused('browser_selection_ambiguous')
    value = found['demo-name'].queryText().getText(0, -1)
    return value, checked[0]


def receipt_fields(uri):
    fields = parse_qs(urlsplit(uri).query)
    if set(fields) != {'name', 'category'} or any(len(values) != 1 for values in fields.values()):
        raise Refused('browser_receipt_unconfirmed')
    name, category = fields['name'][0], fields['category'][0]
    allowed_text(name)
    if category not in ('alpha', 'beta'):
        raise Refused('browser_receipt_unconfirmed')
    return dict(name=name, category=category)


def receipt(frame, values):
    doc, uri = known_document(frame)
    parsed = urlsplit(uri)
    expected = dict(name=[values[0]], category=[values[1]])
    if (parsed.path != '/fixture/receipt.html' or parse_qs(parsed.query) != expected
            or not any(node and node.getRoleName() == 'heading' and node.name == 'LoopBridge local receipt'
                       for _, node in walk(doc))):
        raise Refused('browser_receipt_unconfirmed')
    return dict(submitted=True, category=values[1], name=values[0], execution='firefox_native', verifier='atspi_document_url_and_heading')


def prepare_action(desktop, target, action, fresh):
    if action not in ('click', 'select', 'press', 'activate'):
        raise Refused('browser_action_unsupported')
    key = control(target.frame, target.node, {'alpha', 'beta', 'submit'})
    before = form_values(target.frame)

    def frame():
        records, current, _, _ = desktop.match(target.app)
        if target.window not in records or current != target.frame:
            raise Refused('window_changed')
        return current

    def send():
        control(target.frame, fresh(), {key})
        browser_native.call(desktop.apps['browser'].profile,
                            'submit' if key == 'submit' else 'radio', '' if key == 'submit' else key)

    if key == 'submit':
        allowed_text(before[0])
        return Prepared(send, lambda: wait_for(lambda: receipt(frame(), before), timeout=6))
    if before[1] == key:
        raise Refused('no_change')

    def verify():
        if form_values(frame()) != (before[0], key):
            raise Refused('browser_selection_unconfirmed')
        return dict(selected=key, verifier='atspi_checked_state', execution='firefox_native')

    return Prepared(send, lambda: wait_for(verify, timeout=4))
