# SPDX-License-Identifier: Apache-2.0
"""Trusted launch targets and profiles. Clients choose keys, never argv."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationSpec:
    executable: str
    window_id: str
    arguments: tuple = ()
    profile: str = 'desktop'
    semantic_required: bool = False
    standalone: bool = False


CATALOG = {
    'calculator': ApplicationSpec('/usr/bin/gnome-calculator', 'org.gnome.Calculator',
                                  ('--mode=basic',), semantic_required=True),
    'editor': ApplicationSpec('/usr/bin/gnome-text-editor', 'org.gnome.TextEditor',
                              ('--standalone',), 'document', semantic_required=True,
                              standalone=True),
    'files': ApplicationSpec('/usr/bin/nautilus', 'org.gnome.Nautilus',
                             ('--new-window',), 'directory'),
    'clocks': ApplicationSpec('/usr/bin/gnome-clocks', 'org.gnome.clocks'),
    'browser': ApplicationSpec('/usr/bin/firefox-esr', 'firefox-esr', profile='offline_fixture',
                               semantic_required=True, standalone=True),
}
