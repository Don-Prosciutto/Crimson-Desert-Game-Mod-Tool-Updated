"""Several variants of one mod in one zip that DMM offers as a choice.

A zip with dmm_pack.json (title, author, description) and one mod JSON per
variant, all at the top level. DMM shows the pack once and lets the user
pick the variant to mount (the same layout as e.g. the Custom Artifact
Challenges presets). No Qt in here.
"""

from __future__ import annotations

import json
import re
import zipfile
from typing import List, Tuple


def safe_name(text: str) -> str:
    """A file name from a title: letters, digits, space, - and _ only."""
    s = re.sub(r"[^\w\- ]+", "_", text, flags=re.UNICODE).strip(" _")
    return s or "variant"


def write_pack(path: str, title: str, author: str, description: str,
               variants: List[Tuple[str, dict]]) -> List[str]:
    """Write `variants` ((name, mod dict), ...) as a DMM pack zip at `path`.
    Returns the file names inside the zip."""
    if not variants:
        raise ValueError("No variant to write.")
    names, used = [], set()
    for name, _mod in variants:
        base = safe_name(name)
        fn, i = base + ".json", 2
        while fn.lower() in used:
            fn, i = f"{base} ({i}).json", i + 1
        used.add(fn.lower())
        names.append(fn)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dmm_pack.json", json.dumps(
            {"title": title, "author": author, "description": description},
            indent=2, ensure_ascii=False))
        for fn, (_name, mod) in zip(names, variants):
            z.writestr(fn, json.dumps(mod, indent=2, ensure_ascii=False))
    return names
