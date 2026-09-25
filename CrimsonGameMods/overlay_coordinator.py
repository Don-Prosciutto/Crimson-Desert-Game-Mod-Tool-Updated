"""Overlay Coordinator — the single authority for game directory safety.

EVERY overlay operation goes through this module. No tab writes a PAZ
overlay, rebuilds PAPGT, or deletes an overlay directory without calling
the coordinator first. This ensures:

 1. Tools never overwrite each other's overlays
 2. PAPGT always preserves foreign entries
 3. The shared state file is always current
 4. The game directory is always in a loadable state
 5. Stale state is cleaned up on restore

RULES (the workflow bible):
 - Before writing overlay group N: call pre_write(game_path, group, owner)
   → returns True if safe, False if another tool owns it
 - After writing overlay group N: call post_write(game_path, group, ...)
   → updates shared state + verifies PAPGT
 - Before restoring/deleting group N: call pre_restore(game_path, group)
   → returns True if we own it
 - After restoring group N: call post_restore(game_path, group)
   → cleans shared state
 - Before rebuilding PAPGT: call get_foreign_groups(game_path)
   → returns list of groups owned by other tools that MUST be preserved
 - Any time: call audit(game_path) to verify state consistency
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from shared_state import (
    load_state, save_state, record_overlay, remove_overlay,
    scan_dmm_into_state, OverlayEntry, ModdingState,
)

log = logging.getLogger(__name__)

# Groups we own — hardcoded because they're part of the protocol
OUR_GROUPS = {
    "0058": "ItemBuffs (iteminfo)",
    "0059": "ItemBuffs (equipslot)",
    "0060": "Stores",
    "0061": "MercPets",
    "0062": "Stacker (merged items)",
    "0063": "Stacker (equipslot) / SkillTree",
    "0064": "ItemBuffs (localization)",
}

# Prefixes that identify DMM-owned groups
DMM_PREFIXES = ("dmmsa", "dmmgen", "dmmequ", "dmmlang")

# Groups that are vanilla game data — never touch. Since game 2.03 the game
# ships groups up to 0040 (0036-0040 are optional language groups whose
# folders only exist when that language is installed), so 0036-0040 are NOT
# free for overlays any more. is_game_data_group() also checks the pack list.
VANILLA_RANGE = range(0, 41)
OVERLAY_LANGUAGE = 0x3FFF      # every overlay (ours, DMM) is registered with this


def is_game_data_group(game_path: str, group: str) -> bool:
    """True when this numbered group belongs to the game itself: 0000-0040,
    or listed in meta/0.papgt with a language value overlays never use."""
    if not group.isdigit():
        return False
    if int(group) in VANILLA_RANGE:
        return True
    try:
        import crimson_rs
        papgt = crimson_rs.parse_papgt_file(os.path.join(game_path, "meta", "0.papgt"))
        for e in papgt.get("entries", []):
            if e.get("group_name") == group:
                return e.get("language") != OVERLAY_LANGUAGE
    except Exception:  # noqa: BLE001 - unreadable pack list: numbers alone decide
        pass
    return False


def _safe_overlay_default(value, fallback: int, taken=()) -> int:
    """Saved overlay numbers from before game 2.03 may point into the game's
    own range (0036-0040) or at another tool's group; use the new default then."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if v in VANILLA_RANGE or v in taken else v


def safe_rmtree(path) -> None:
    """shutil.rmtree for overlay folders that refuses to delete game data
    (0000-0040 and other groups the game itself lists) or the meta/bin64
    folders. Raises RuntimeError instead - callers show the message."""
    import shutil
    path = os.path.normpath(str(path))
    group = os.path.basename(path)
    parent = os.path.dirname(path)
    if group.lower() in ("meta", "bin64", "bin", "") or (
            group.isdigit() and is_game_data_group(parent, group)):
        raise RuntimeError(f"{group}/ belongs to the game itself and was not deleted. "
                           f"If a tool wrote into it, use Steam > Verify integrity of game files.")
    shutil.rmtree(path)


def free_overlay_number(game_path: str, start: int = 100) -> int:
    """First 4-digit group number with no folder and no pack-list entry."""
    used = set()
    try:
        for name in os.listdir(game_path):
            if name.isdigit() and len(name) == 4:
                used.add(int(name))
        import crimson_rs
        papgt = crimson_rs.parse_papgt_file(os.path.join(game_path, "meta", "0.papgt"))
        used |= {int(e["group_name"]) for e in papgt.get("entries", [])
                 if str(e.get("group_name", "")).isdigit()}
    except Exception:  # noqa: BLE001
        pass
    for n in range(max(start, 41), 9999):
        if n not in used:
            return n
    return start


def remove_papgt_groups(game_path: str, groups) -> str:
    """Remove only these entries from meta/0.papgt. Every other entry (game,
    DMM, other tools) stays. Never falls back to an old backup copy: those
    are from earlier game versions and would drop other mods' entries."""
    import crimson_rs
    groups = set(groups)
    papgt_path = os.path.join(game_path, "meta", "0.papgt")
    if not os.path.isfile(papgt_path):
        return "PAPGT not found"
    papgt = crimson_rs.parse_papgt_file(papgt_path)
    before = len(papgt["entries"])
    papgt["entries"] = [e for e in papgt["entries"] if e.get("group_name") not in groups]
    removed = before - len(papgt["entries"])
    if not removed:
        return f"PAPGT: {', '.join(sorted(groups))} was not registered"
    crimson_rs.write_papgt_file(papgt, papgt_path)
    others = [e["group_name"] for e in papgt["entries"]
              if not (str(e["group_name"]).isdigit() and int(e["group_name"]) in VANILLA_RANGE)]
    extra = f" (other overlays still active: {', '.join(others)})" if others else ""
    return f"PAPGT: removed {', '.join(sorted(groups))}{extra}"


def _is_ours(group: str) -> bool:
    return group in OUR_GROUPS


def _is_dmm(group: str) -> bool:
    return group.startswith(DMM_PREFIXES)


def _is_vanilla(group: str) -> bool:
    try:
        return int(group) in VANILLA_RANGE
    except ValueError:
        return False


def _group_exists(game_path: str, group: str) -> bool:
    gdir = os.path.join(game_path, group)
    if not os.path.isdir(gdir):
        return False
    return (os.path.isfile(os.path.join(gdir, "0.paz")) or
            os.path.isfile(os.path.join(gdir, "0.pamt")))


# ── Pre-write check ─────────────────────────────────────────────

def pre_write(game_path: str, group: str, owner: str = "CrimsonGameMods"
              ) -> tuple[bool, str]:
    """Check if it's safe to write to this overlay group.

    Returns (safe, reason). If safe=False, the caller should abort.
    """
    if not game_path or not os.path.isdir(game_path):
        return False, "Game path not set or doesn't exist"

    if _is_vanilla(group):
        return False, f"Group {group} is vanilla game data — never overwrite"

    state = load_state(game_path)

    if group in state.overlays:
        existing = state.overlays[group]
        if existing.owner != owner and existing.owner != "Unknown":
            return False, (
                f"Group {group} is owned by {existing.owner} "
                f"({existing.content}). Writing would overwrite their data."
            )

    return True, "OK"


# ── Post-write ───────────────────────────────────────────────────

def post_write(game_path: str, group: str, content: str,
               files: list[str] | None = None,
               owner: str = "CrimsonGameMods") -> None:
    """Record that we just wrote an overlay. Call after every successful write."""
    record_overlay(game_path, group, content, files)
    log.info("Overlay %s written by %s: %s", group, owner, content)


# ── Pre-restore check ────────────────────────────────────────────

def pre_restore(game_path: str, group: str,
                owner: str = "CrimsonGameMods") -> tuple[bool, str]:
    """Check if it's safe to delete/restore this overlay group."""
    if not game_path or not os.path.isdir(game_path):
        return False, "Game path not set"

    if _is_vanilla(group):
        return False, f"Group {group} is vanilla — don't delete"

    state = load_state(game_path)
    if group in state.overlays:
        existing = state.overlays[group]
        if existing.owner != owner and existing.owner != "Unknown":
            return False, (
                f"Group {group} is owned by {existing.owner}. "
                f"Only {existing.owner} should remove it."
            )

    return True, "OK"


# ── Post-restore ─────────────────────────────────────────────────

def post_restore(game_path: str, group: str) -> None:
    """Clean up shared state after removing an overlay group."""
    remove_overlay(game_path, group)
    log.info("Overlay %s removed and state cleaned", group)


# ── Foreign group preservation ───────────────────────────────────

def get_foreign_groups(game_path: str,
                       our_owner: str = "CrimsonGameMods") -> list[str]:
    """Return overlay groups owned by OTHER tools that must be preserved
    in PAPGT rebuilds.

    Call this before rebuilding PAPGT. Pass the returned groups to
    crimson_rs.add_papgt_entry() so they survive the rebuild.
    """
    if not game_path or not os.path.isdir(game_path):
        return []

    foreign = []
    state = load_state(game_path)

    # From shared state
    for group, entry in state.overlays.items():
        if entry.owner != our_owner and _group_exists(game_path, group):
            foreign.append(group)

    # Also scan for DMM groups not in state (DMM might not write state yet)
    try:
        for entry in os.listdir(game_path):
            if not _group_exists(game_path, entry):
                continue
            if _is_vanilla(entry):
                continue
            if _is_dmm(entry) and entry not in foreign:
                foreign.append(entry)
            # Also catch numeric groups > 35 that aren't ours and aren't in state
            try:
                num = int(entry)
                if num >= 36 and entry not in OUR_GROUPS and entry not in foreign:
                    # Unknown overlay — preserve it to be safe
                    if entry not in state.overlays:
                        foreign.append(entry)
            except ValueError:
                if entry not in foreign and not _is_ours(entry):
                    foreign.append(entry)
    except OSError:
        pass

    return sorted(set(foreign))


# ── Check if DMM has an iteminfo overlay active ──────────────────

def get_active_iteminfo_overlay(game_path: str) -> Optional[str]:
    """Return the path to the most recently written iteminfo overlay
    from ANY tool, or None if only vanilla exists.

    Used by the Stacker to decide whether to merge from vanilla or
    from the current modified state.
    """
    if not game_path:
        return None

    state = load_state(game_path)
    candidates = []

    for group, entry in state.overlays.items():
        if not _group_exists(game_path, group):
            continue
        if any("iteminfo" in f.lower() for f in entry.files):
            paz_path = os.path.join(game_path, group, "0.paz")
            if os.path.isfile(paz_path):
                mtime = os.path.getmtime(paz_path)
                candidates.append((mtime, group, entry.owner, paz_path))

    if not candidates:
        return None

    # Return the most recent one
    candidates.sort(reverse=True)
    _, group, owner, paz_path = candidates[0]
    log.info("Active iteminfo overlay: %s (owner: %s)", group, owner)
    return paz_path


def get_dmm_overlay_files(game_path: str, filename: str) -> Optional[bytes]:
    """Extract a specific file from DMM's active overlays.

    Used to check if DMM has modified a file that we also want to modify,
    so we can merge from the modified state instead of vanilla.
    """
    if not game_path:
        return None

    state = load_state(game_path)
    for group, entry in state.overlays.items():
        if entry.owner == "CrimsonGameMods":
            continue
        if not _group_exists(game_path, group):
            continue
        if filename.lower() in [f.lower() for f in entry.files]:
            paz_path = os.path.join(game_path, group, "0.paz")
            if os.path.isfile(paz_path):
                try:
                    import crimson_rs
                    data = crimson_rs.extract_file_from_paz(
                        paz_path,
                        f"gamedata/binary__/client/bin/{filename}"
                    )
                    if data:
                        return bytes(data)
                except Exception as e:
                    log.warning("Could not extract %s from %s: %s",
                                filename, group, e)
    return None


# ── Audit ────────────────────────────────────────────────────────

def audit(game_path: str) -> list[str]:
    """Check consistency between shared state and actual game directory.

    Returns list of issues found. Empty list = everything is consistent.
    """
    if not game_path or not os.path.isdir(game_path):
        return ["Game path not set or doesn't exist"]

    issues = []
    state = load_state(game_path)

    # Check for overlays in state that don't exist on disk
    for group, entry in list(state.overlays.items()):
        if not _group_exists(game_path, group):
            issues.append(
                f"State says {group} ({entry.owner}: {entry.content}) "
                f"exists but directory is missing — removing stale entry"
            )
            state.overlays.pop(group)

    # Check for overlay directories on disk not in state
    try:
        for entry in sorted(os.listdir(game_path)):
            if not _group_exists(game_path, entry):
                continue
            if _is_vanilla(entry):
                continue
            if entry not in state.overlays:
                issues.append(
                    f"Directory {entry}/ exists but not in shared state — "
                    f"unknown owner"
                )
    except OSError:
        pass

    # Check PAPGT consistency
    papgt_path = os.path.join(game_path, "meta", "0.papgt")
    if os.path.isfile(papgt_path):
        try:
            import crimson_rs
            papgt = crimson_rs.parse_papgt_file(papgt_path)
            registered = {e["group_name"] for e in papgt.get("entries", [])
                          if not (str(e.get("group_name", "0")).isdigit() and int(e.get("group_name", "0")) <= 40)}

            # Overlay exists on disk but not in PAPGT
            for group in state.overlays:
                if _group_exists(game_path, group) and group not in registered:
                    try:
                        int(group)
                        issues.append(
                            f"Overlay {group} exists on disk + in state "
                            f"but NOT registered in PAPGT — game won't load it"
                        )
                    except ValueError:
                        pass  # Non-numeric groups (DMM) use different registration

            # In PAPGT but no directory
            for group in registered:
                if not _group_exists(game_path, group):
                    issues.append(
                        f"PAPGT references {group} but directory doesn't exist — "
                        f"game may error on load"
                    )
        except Exception as e:
            issues.append(f"PAPGT parse failed: {e}")

    # Save cleaned state if we removed stale entries
    if issues:
        save_state(game_path, state)

    return issues


# ── Convenience: safe PAPGT rebuild ──────────────────────────────

def safe_papgt_add(game_path: str, our_group: str,
                   pamt_checksum: int) -> str:
    """Add our overlay to PAPGT while preserving ALL foreign entries.

    Returns status message. This is the ONLY way tabs should update PAPGT.
    """
    try:
        import crimson_rs
    except ImportError:
        return "crimson_rs not available"

    papgt_path = os.path.join(game_path, "meta", "0.papgt")
    if not os.path.isfile(papgt_path):
        return "PAPGT not found"

    try:
        papgt = crimson_rs.parse_papgt_file(papgt_path)
        original_entries = papgt.get("entries", [])

        # Remove ONLY our group, preserve everything else
        papgt["entries"] = [
            e for e in original_entries
            if e.get("group_name") != our_group
        ]
        preserved_count = len(papgt["entries"])

        # Add our group
        papgt = crimson_rs.add_papgt_entry(
            papgt, our_group, pamt_checksum,
            is_optional=0, language=0x3FFF
        )

        crimson_rs.write_papgt_file(papgt, papgt_path)

        foreign = [e["group_name"] for e in papgt["entries"]
                   if e["group_name"] != our_group]
        foreign_str = f" (preserved: {', '.join(foreign)})" if foreign else ""
        return f"PAPGT updated: added {our_group}{foreign_str}"

    except Exception as e:
        return f"PAPGT update failed: {e}"


def safe_papgt_remove(game_path: str, our_group: str) -> str:
    """Remove our overlay from PAPGT while preserving ALL foreign entries."""
    try:
        import crimson_rs
    except ImportError:
        return "crimson_rs not available"

    papgt_path = os.path.join(game_path, "meta", "0.papgt")
    if not os.path.isfile(papgt_path):
        return "PAPGT not found"

    try:
        papgt = crimson_rs.parse_papgt_file(papgt_path)
        before = len(papgt["entries"])

        papgt["entries"] = [
            e for e in papgt["entries"]
            if e.get("group_name") != our_group
        ]

        if len(papgt["entries"]) == before:
            return f"PAPGT: {our_group} was not registered"

        crimson_rs.write_papgt_file(papgt, papgt_path)

        remaining = [e["group_name"] for e in papgt["entries"]
                     if not (str(e.get("group_name", "0")).isdigit() and int(e.get("group_name", "0")) <= 40)]
        extra = f" (remaining: {', '.join(remaining)})" if remaining else ""
        return f"PAPGT: removed {our_group}{extra}"

    except Exception as e:
        # Fallback to .sebak restore
        sebak = papgt_path + ".sebak"
        if os.path.isfile(sebak):
            import shutil
            shutil.copy2(sebak, papgt_path)
            return f"PAPGT: fell back to .sebak restore ({e})"
        return f"PAPGT removal failed: {e}"


# ── Universal Conflict Scanner ───────────────────────────────────

@dataclass
class ConflictSource:
    """A single source that contains iteminfo.pabgb."""
    location: str          # file/directory path
    owner: str             # "CrimsonGameMods" | "DMM" | "JMM" | "Unknown" | "mod folder"
    format: str            # "overlay_paz" | "loose_pabgb" | "json_patch" | "browser_mod" | "archive"
    group: str = ""        # overlay group name if applicable
    mod_name: str = ""     # human-readable mod name if known
    files_found: list = None

    def __post_init__(self):
        if self.files_found is None:
            self.files_found = []


def _pamt_contains_file(pamt_path: str, target: str) -> list[str]:
    """Read a PAMT index and return matching file names."""
    try:
        import crimson_rs
        data = open(pamt_path, "rb").read()
        parsed = crimson_rs.parse_pamt_bytes(data)
        found = []
        for d in parsed.get("directories", []):
            for f in d.get("files", []):
                fname = f.get("name", "")
                if target.lower() in fname.lower():
                    full = d.get("path", "") + "/" + fname
                    found.append(full)
        return found
    except Exception:
        return []


def scan_for_iteminfo_conflicts(game_path: str,
                                 our_group: str = "",
                                 dmm_exe_path: str = "",
                                 extra_scan_dirs: list[str] | None = None,
                                 ) -> list[ConflictSource]:
    """Scan EVERYTHING for iteminfo.pabgb — overlays, mod folders, archives.

    Checks:
     1. Every overlay group's PAMT index (catches pre-built PAZ overlays)
     2. DMM's mods folder for JSON byte-patch mods targeting iteminfo
     3. DMM's browser mods folder for loose file replacements
     4. Any extra directories (user's mod downloads, etc.)

    Excludes `our_group` from results (we know about our own overlay).
    Returns a list of ConflictSource describing each conflict found.
    """
    if not game_path or not os.path.isdir(game_path):
        return []

    conflicts: list[ConflictSource] = []
    target = "iteminfo"

    # 1. Scan every overlay group's PAMT for iteminfo files
    try:
        for entry in sorted(os.listdir(game_path)):
            entry_path = os.path.join(game_path, entry)
            if not os.path.isdir(entry_path):
                continue
            pamt = os.path.join(entry_path, "0.pamt")
            if not os.path.isfile(pamt):
                continue

            # Skip vanilla
            if _is_vanilla(entry):
                continue
            # Skip our own group
            if entry == our_group:
                continue

            found = _pamt_contains_file(pamt, target)
            if found:
                owner = "CrimsonGameMods" if _is_ours(entry) else (
                    "DMM" if _is_dmm(entry) else "Unknown"
                )
                # Check shared state for richer info
                state = load_state(game_path)
                if entry in state.overlays:
                    owner = state.overlays[entry].owner
                    mod_name = state.overlays[entry].content
                else:
                    mod_name = f"overlay {entry}"

                conflicts.append(ConflictSource(
                    location=entry_path,
                    owner=owner,
                    format="overlay_paz",
                    group=entry,
                    mod_name=mod_name,
                    files_found=found,
                ))
    except OSError:
        pass

    # 2. Scan DMM's mods folder for JSON mods targeting iteminfo
    if dmm_exe_path and os.path.isfile(dmm_exe_path):
        dmm_config = Path(dmm_exe_path).parent / "config.json"
        if dmm_config.is_file():
            try:
                import json
                with open(dmm_config, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                mods_path = cfg.get("modsPath", "")
                if mods_path and os.path.isdir(mods_path):
                    _scan_mod_folder(mods_path, target, "DMM mods folder", conflicts)
            except Exception:
                pass

    # 3. Scan extra directories
    for scan_dir in (extra_scan_dirs or []):
        if os.path.isdir(scan_dir):
            _scan_mod_folder(scan_dir, target, os.path.basename(scan_dir), conflicts)

    return conflicts


def _scan_mod_folder(folder: str, target: str, source_label: str,
                     conflicts: list[ConflictSource]) -> None:
    """Scan a folder for mods containing iteminfo — JSON, loose files, sub-overlays."""
    import json as _json

    for item in os.listdir(folder):
        item_path = os.path.join(folder, item)

        # JSON mod files
        if item.lower().endswith(".json") and os.path.isfile(item_path):
            try:
                with open(item_path, "r", encoding="utf-8", errors="replace") as f:
                    doc = _json.load(f)
                patches = doc.get("patches", [])
                for patch in patches:
                    gf = (patch.get("game_file") or "").lower()
                    if target in gf:
                        info = doc.get("modinfo") or doc
                        title = info.get("title") or info.get("name") or item
                        n = sum(len(p.get("changes", [])) for p in patches
                                if target in (p.get("game_file") or "").lower())
                        conflicts.append(ConflictSource(
                            location=item_path,
                            owner=source_label,
                            format="json_patch",
                            mod_name=f"{title} ({n} patches)",
                            files_found=[gf],
                        ))
                        break
            except Exception:
                pass

        # Mod folders — check for loose pabgb or sub-overlay PAZ
        elif os.path.isdir(item_path):
            # Loose iteminfo.pabgb in files/ subfolder (browser mod)
            for root, dirs, files in os.walk(item_path):
                for fname in files:
                    if target in fname.lower() and fname.lower().endswith(".pabgb"):
                        conflicts.append(ConflictSource(
                            location=os.path.join(root, fname),
                            owner=source_label,
                            format="loose_pabgb",
                            mod_name=item,
                            files_found=[os.path.join(root, fname)],
                        ))
                        break
                else:
                    continue
                break

            # Sub-overlay (0036/0.paz + 0.pamt inside mod folder)
            for sub in os.listdir(item_path):
                sub_pamt = os.path.join(item_path, sub, "0.pamt")
                if os.path.isfile(sub_pamt):
                    found = _pamt_contains_file(sub_pamt, target)
                    if found:
                        conflicts.append(ConflictSource(
                            location=os.path.join(item_path, sub),
                            owner=source_label,
                            format="overlay_paz",
                            group=sub,
                            mod_name=f"{item}/{sub}",
                            files_found=found,
                        ))


def check_iteminfo_conflicts_before_apply(
    game_path: str, our_group: str,
    config: dict | None = None,
) -> str | None:
    """Quick pre-apply check. Returns a warning message if conflicts exist,
    or None if safe to proceed.

    Call this from any Apply button before writing an iteminfo overlay.
    """
    dmm_exe = (config or {}).get("dmm_exe_path", "")
    conflicts = scan_for_iteminfo_conflicts(
        game_path, our_group=our_group, dmm_exe_path=dmm_exe)

    if not conflicts:
        return None

    lines = []
    for c in conflicts:
        if c.format == "overlay_paz":
            lines.append(f"  {c.group}/ ({c.owner}: {c.mod_name})")
        elif c.format == "json_patch":
            lines.append(f"  {c.mod_name} ({c.owner})")
        else:
            lines.append(f"  {c.mod_name} [{c.format}]")

    return (
        f"Found {len(conflicts)} other source(s) with iteminfo.pabgb:\n"
        + "\n".join(lines) + "\n\n"
        "Your overlay will take priority — their iteminfo changes "
        "won't load alongside yours.\n\n"
        "To include their changes: use Stacker Tool → Pull DMM, "
        "then Install Stack to merge everything into one overlay.\n\n"
        "Continue anyway?"
    )
