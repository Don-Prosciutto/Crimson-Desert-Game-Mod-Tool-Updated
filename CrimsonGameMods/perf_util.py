"""Small helpers for loading big game tables quickly (new look 2.5).

paused_gc():   pauses Python's cyclic garbage collector while a large result
               (hundreds of thousands of dicts / lists) is built - otherwise
               the collector walks the growing result again and again. On
               exit the new objects go straight to the oldest generation.
vanilla_copy(): independent copy of parser output (dict / list / plain
               values). Same result as copy.deepcopy for such data, several
               times faster; anything else falls back to copy.deepcopy.
"""
from __future__ import annotations

import copy
import gc
import threading
from contextlib import contextmanager

_lock = threading.Lock()
_depth = 0
_was_on = False
_PLAIN = (str, int, float, bool, type(None), bytes)


@contextmanager
def paused_gc():
    global _depth, _was_on
    with _lock:
        if _depth == 0:
            _was_on = gc.isenabled()
            gc.disable()
        _depth += 1
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0 and _was_on:
                gc.freeze()
                gc.unfreeze()
                gc.enable()


def _plain_copy(x):
    t = type(x)
    if t is dict:
        return {k: (v if type(v) in _PLAIN else _plain_copy(v)) for k, v in x.items()}
    if t is list:
        return [(v if type(v) in _PLAIN else _plain_copy(v)) for v in x]
    if t is tuple:
        return tuple((v if type(v) in _PLAIN else _plain_copy(v)) for v in x)
    if t in _PLAIN:
        return x
    return copy.deepcopy(x)


def vanilla_copy(x):
    """Independent copy of a parsed table (list of dicts)."""
    with paused_gc():
        return _plain_copy(x)
