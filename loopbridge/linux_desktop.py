# SPDX-License-Identifier: Apache-2.0
"""Shared Linux desktop and AT-SPI primitives for the trusted adapters."""
import json
import os
from pathlib import Path
import subprocess
import time


class Rejected(RuntimeError):
    pass

def unique(items, reason):
    if len(items) != 1:
        raise Rejected(reason)
    return items[0]

def sway(kind):
    return json.loads(subprocess.check_output(
        ['swaymsg', '-r', '-t', kind], timeout=3))

def windows(tree):
    result = []
    if tree.get('pid') and (tree.get('app_id') or tree.get('window')):
        result.append({k: tree.get(k) for k in ('id', 'pid', 'app_id', 'shell')})
    for child in tree.get('nodes', []) + tree.get('floating_nodes', []):
        result.extend(windows(child))
    return result

def process_identity(pid):
    # comm may contain spaces and parentheses; field 22 follows the last ')'.
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return (pid, stat[19], os.stat(f'/proc/{pid}').st_uid,
            os.readlink(f'/proc/{pid}/exe'))

def walk(root):
    pending = [((), root)]
    count = 0
    while pending:
        path, node = pending.pop()
        count += 1
        if count > 1500 or len(path) > 40:
            raise Rejected('tree_limit')
        yield path, node
        pending.extend((path + (i,), node[i]) for i in reversed(range(node.childCount)))

def texts(frame):
    # Exclude labels: a button label containing '7' cannot verify the display.
    return {'.'.join(map(str, p)): n.queryText().getText(0, -1)
            for p, n in walk(frame)
            if n.getRoleName() == 'text' and 'Text' in n.get_interfaces()}

def wait_for(read, timeout=10):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return read()
        except Exception as error:
            last = error
            time.sleep(.15)
    raise Rejected('readiness_timeout:' + type(last).__name__) from last
