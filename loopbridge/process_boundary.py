# SPDX-License-Identifier: Apache-2.0
"""Linux process-local protection for trusted credential and media holders."""
import ctypes
import os


def protect_process():
    # Apply in the process that handles the data, before reading it.
    # An exec can restore dumpability.
    libc = ctypes.CDLL(None, use_errno=True)
    zero = ctypes.c_ulong(0)
    if libc.prctl(4, zero, zero, zero, zero) != 0:  # PR_SET_DUMPABLE
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def close_bootstrap_stdin():
    # Python's sys.stdin wrapper does not own descriptor 0.
    with open(os.devnull, 'rb') as empty:
        os.dup2(empty.fileno(), 0)
