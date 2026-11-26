# SPDX-License-Identifier: Apache-2.0
"""Explicit cross-UID supervision with pinned private state and Registry policy."""
from contextlib import contextmanager
from time import monotonic, time

from experiments.registry_operational import _serve_profile
from experiments.registry_storage import _initialize_database
from experiments.supervision_lab import SupervisionLabBroker
from experiments.supervision_storage import SupervisionRegistry

DATABASE = 'supervised.sqlite3'
ENDPOINT = 'supervised.sock'


def initialize_supervision_database(path, *, wall_clock=time):
    return _initialize_database(path, DATABASE, SupervisionRegistry, wall_clock)


@contextmanager
def serve_operational_supervision(ingress, *, database_pin, policy_pin, wall_clock=time, clock=monotonic):
    """Use an explicitly provisioned ingress. Trusted execution grants are volatile."""
    with _serve_supervision(ingress, database_pin, policy_pin, wall_clock=wall_clock,
                            clock=clock) as (endpoint, broker, control):
        yield endpoint, broker.execution, control


@contextmanager
def _serve_supervision(ingress, database_pin, policy_pin, *, wall_clock, clock,
                       broker_type=SupervisionLabBroker, prepare=None):
    # The qualification harness binds its deterministic barriers in-process.
    with _serve_profile(ingress, database_pin, policy_pin, endpoint_name=ENDPOINT,
                        database_name=DATABASE, broker_type=broker_type, prepare=prepare,
                        wall_clock=wall_clock, clock=clock) as profile:
        yield profile
