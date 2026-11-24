# SPDX-License-Identifier: Apache-2.0
"""Bounded numeric probes for the disposable offline presentation fixture."""
from collections import deque
from statistics import median
from threading import Lock
from time import monotonic_ns, time_ns

NS_PER_MS = 1_000_000
LIMIT = 8192


def clock_pair():
    """Bracket a realtime read with reads of the common guest monotonic clock."""
    first = monotonic_ns()
    realtime = time_ns()
    last = monotonic_ns()
    return realtime - (first + last) // 2, (last - first) // 2


def compatible_offset(first, last):
    offset, uncertainty = first
    final, final_uncertainty = last
    if max(uncertainty, final_uncertainty) > NS_PER_MS or abs(offset - final) > 2 * NS_PER_MS:
        return None
    return (offset + final) // 2


def stats_ms(values):
    values = sorted(value / NS_PER_MS for value in values if value >= 0)
    if not values:
        return None
    return dict(n=len(values), median=round(median(values), 3),
                p95=round(values[(95 * len(values) + 99) // 100 - 1], 3))


def intervals(values):
    ordered = sorted(values)
    return stats_ms(b - a for a, b in zip(ordered, ordered[1:]))


class PipelineProbe:
    def __init__(self):
        self.rows = {}
        self.status = deque(maxlen=LIMIT)
        self.lock = Lock()

    def __call__(self, stage, sequence, *values):
        with self.lock:
            if stage == 'status':
                self.status.append(values)
                return
            if stage == 'wire':
                if len(self.rows) >= LIMIT:
                    del self.rows[next(iter(self.rows))]
                self.rows[sequence] = {}
            if sequence in self.rows:
                self.rows[sequence][stage] = values

    def report(self, start, end, clocks):
        with self.lock:
            rows = [row.copy() for row in self.rows.values()]
            status = [b - a for a, b in self.status if start <= a < end]

        def select(stage, index=0):
            return [row for row in rows if stage in row and start <= row[stage][index] < end]

        received = select('wire', 2)
        painted = select('paint')
        submitted = select('draw')
        unique = select('mailbox')
        overwritten = select('overwrite')
        feedback = [row for row in painted if 'feedback' in row]
        decoded = [row['decode'][2] for row in received
                   if 'decode' in row and row['decode'][2] is not None]
        marks_painted = [row['decode'][2] for row in painted
                         if 'decode' in row and row['decode'][2] is not None]
        duration = (end - start) / 1e9
        spans = {}
        if len(decoded) >= 2 and decoded[-1][0] > decoded[0][0] and decoded[-1][1] > decoded[0][1]:
            count = decoded[-1][0] - decoded[0][0] + 1
            spans = dict(source_deltas=count - 1,
                         source_fps=round((count - 1) * 1000 / (decoded[-1][1] - decoded[0][1]), 2),
                         absent_at_client_between_markers=max(0, count - len(set(decoded))))

        def segment(group, before, after):
            source, src_index = before
            dest, dst_index = after
            return stats_ms(row[dest][dst_index] - row[source][src_index]
                            for row in group if source in row and dest in row)

        offset = compatible_offset(*clocks)

        def source_to(group, stage, index):
            if offset is None:
                return None
            values = []
            for row in group:
                marker = row.get('decode', (None, None, None))[2]
                if marker is not None:
                    age = row[stage][index] + offset - marker[1] * NS_PER_MS
                    if 0 <= age <= 2_000 * NS_PER_MS:
                        values.append(age)
            return stats_ms(values)

        return dict(
            seconds=round(duration, 3),
            frames=dict(received=len(received), unique=len(unique), overwritten=len(overwritten),
                        submitted=len(submitted), painted=len(painted), feedback=len(feedback),
                        decoded=len(decoded), markers_painted=len(marks_painted)),
            fps=dict(received=round(len(received) / duration, 2), painted=round(len(painted) / duration, 2)),
            source=spans,
            clock=dict(realtime_to_monotonic_usable=offset is not None,
                       offset_drift_ms=round(abs(clocks[0][0] - clocks[1][0]) / NS_PER_MS, 4)),
            overhead_ms=dict(
                origin_to_capture=source_to(received, 'wire', 0),
                capture_to_header=segment(received, ('wire', 0), ('wire', 1)),
                header_to_payload=segment(received, ('wire', 1), ('wire', 2)),
                capture_to_payload=segment(received, ('wire', 0), ('wire', 2)),
                decode=segment(received, ('decode', 0), ('decode', 1)),
                payload_to_mailbox=segment(unique, ('wire', 2), ('mailbox', 0)),
                mailbox_to_idle=segment(submitted, ('mailbox', 0), ('idle', 0)),
                idle_to_tick=segment(submitted, ('idle', 0), ('draw', 0)),
                mailbox_to_tick=segment(submitted, ('mailbox', 0), ('draw', 0)),
                texture=segment(submitted, ('draw', 0), ('draw', 1)),
                assign_picture=segment(submitted, ('draw', 1), ('draw', 2)),
                assign_to_paint=segment(painted, ('draw', 2), ('paint', 0)),
                paint_to_feedback=segment(feedback, ('paint', 0), ('feedback', 0)),
                origin_to_paint=source_to(painted, 'paint', 0),
                origin_to_feedback=source_to(feedback, 'feedback', 0),
                status_callback=stats_ms(status),
                tick_interval=intervals(row['draw'][0] for row in submitted),
                paint_interval=intervals(row['paint'][0] for row in painted),
            ),
            mailbox_overwrite_pct=round(100 * len(overwritten) / len(unique), 2) if unique else None,
        )
