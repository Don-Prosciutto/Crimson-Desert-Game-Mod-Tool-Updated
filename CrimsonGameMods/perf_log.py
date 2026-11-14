"""Timing of slow list/table fills, written to logs.txt.

    @perf_log.timed
    def _populate_something(self): ...

A call that takes longer than THRESHOLD seconds prints one line like
    [perf] field_edit._mount_populate: 1.84 s
so the log shows which table to speed up first. Faster calls print nothing.

Many of these functions are Qt slots. Qt hands a slot as many signal
arguments as the function can take, so the wrapper drops the extra ones the
original function would not accept - it behaves exactly like before.
"""

from __future__ import annotations

import functools
import inspect
import time

THRESHOLD = 0.2


def timed(fn):
    name = f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__qualname__.rsplit('.', 1)[-1]}"
    code = fn.__code__
    takes_varargs = bool(code.co_flags & inspect.CO_VARARGS)
    max_pos = code.co_argcount

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not takes_varargs and len(args) > max_pos:
            args = args[:max_pos]
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            if dt >= THRESHOLD:
                try:
                    print(f"[perf] {name}: {dt:.2f} s")
                except Exception:  # noqa: BLE001
                    pass
    return wrapper
