# SPDX-License-Identifier: Apache-2.0
"""Logical-pixel limits and persisted preferences for the layout experiment."""
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

RAIL_SIDES = ('left', 'right')
CONSOLE_EDGES = ('top', 'bottom')
WIDTH_LIMITS = (200, 480)
HEIGHT_LIMITS = (120, 400)
MIN_WORKSPACE = (320, 200)
MAX_CONFIG_BYTES = 4096


def clamp(value, low, high):
    return max(low, min(value, high))


@dataclass(frozen=True)
class Layout:
    side: str = 'left'
    edge: str = 'bottom'
    width: int = 260
    height: int = 180

    @classmethod
    def from_config(cls, data):
        defaults = cls()
        if not isinstance(data, dict):
            return defaults
        side, edge = data.get('side'), data.get('edge')
        width, height = data.get('width'), data.get('height')
        return cls(
            side=side if side in RAIL_SIDES else defaults.side,
            edge=edge if edge in CONSOLE_EDGES else defaults.edge,
            width=clamp(width, *WIDTH_LIMITS) if type(width) is int else defaults.width,
            height=clamp(height, *HEIGHT_LIMITS) if type(height) is int else defaults.height,
        )

    def fit(self, width, height):
        """Fit the preferred layout or use a preview on a compact output."""
        max_width = min(width - MIN_WORKSPACE[0], WIDTH_LIMITS[1])
        max_height = min(height - MIN_WORKSPACE[1], HEIGHT_LIMITS[1])
        if max_width < WIDTH_LIMITS[0] or max_height < HEIGHT_LIMITS[0]:
            return None
        return replace(self, width=clamp(self.width, WIDTH_LIMITS[0], max_width),
                       height=clamp(self.height, HEIGHT_LIMITS[0], max_height))


def config_path():
    configured = Path(os.environ.get('XDG_CONFIG_HOME', ''))
    root = configured if configured.is_absolute() else Path.home() / '.config'
    return root / 'loopenvironment' / 'loopshell-layout.json'


def load_layout(path):
    try:
        with path.open('rb') as config:
            content = config.read(MAX_CONFIG_BYTES + 1)
        if len(content) <= MAX_CONFIG_BYTES:
            return Layout.from_config(json.loads(content))
    except (OSError, ValueError, RecursionError):
        pass
    return Layout()


def save_layout(path, layout):
    path.parent.mkdir(parents=True, exist_ok=True)
    output = NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False)
    staged = Path(output.name)
    try:
        with output:
            json.dump(asdict(layout), output, indent=2)
            output.write('\n')
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)
