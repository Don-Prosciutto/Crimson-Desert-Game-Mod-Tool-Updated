#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECTS = {
    "gamemods": {
        "root": ROOT / "CrimsonGameMods",
        "targets": {
            "cli": {"entry": "cli.py", "name": "CrimsonCLI", "out": "build-nuitka-cli", "spec": "CrimsonCLI.spec"},
            "full": {"entry": "main.py", "name": "CrimsonGameMods", "out": "build-nuitka-full", "spec": "CrimsonGameMods.spec"},
            "lite": {"entry": "simple_launcher.py", "name": "CrimsonGameModsSimple", "out": "build-nuitka-lite", "spec": "CrimsonGameModsSimple.spec"},
        },
    },
    "saveeditor": {
        "root": ROOT / "CrimsonSaveEditor",
        "targets": {
            "full": {"entry": "main.py", "name": "CrimsonSaveEditor", "out": "build-output", "spec": "CrimsonSaveEditor.spec"},
        },
    },
}


def find_qt_libs() -> tuple[str, str]:
    paths = []
    try:
        paths.extend(site.getsitepackages())
    except AttributeError:
        pass
    try:
        paths.append(site.getusersitepackages())
    except AttributeError:
        pass
    for base in paths:
        if not base:
            continue
        pyside = sorted(glob.glob(os.path.join(base, "PySide6", "libpyside6*.so*"))
                        + glob.glob(os.path.join(base, "PySide6", "pyside6*.dll")))
        shiboken = sorted(glob.glob(os.path.join(base, "shiboken6", "libshiboken6*.so*"))
                          + glob.glob(os.path.join(base, "shiboken6", "shiboken6*.dll")))
        if pyside and shiboken:
            return pyside[0], shiboken[0]
    raise SystemExit("Unable to locate PySide6/shiboken6 shared libraries")


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=PROJECTS.keys(), required=True)
    parser.add_argument("--target", default="full")
    parser.add_argument("--backend", choices=["nuitka", "pyinstaller"], default="pyinstaller")
    args = parser.parse_args()

    project = PROJECTS[args.project]
    if args.target not in project["targets"]:
        raise SystemExit(f"Invalid target {args.target!r} for project {args.project}")

    target = project["targets"][args.target]
    root = project["root"]
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    if args.backend == "pyinstaller":
        spec = root / target["spec"]
        # Only replace this target's exe: wiping the whole dist folder deleted
        # the other exes (building Simple removed CrimsonGameMods.exe).
        dist = root / "dist"
        for old in dist.glob(target["name"] + ".exe"):
            old.unlink()
        shutil.rmtree(dist / target["name"], ignore_errors=True)
        run([sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm"], cwd=root)
        return 0

    # Only the Nuitka build needs the Qt library paths. Looking them up
    # first made the default PyInstaller build fail on Windows, where the
    # files end in .dll, not .so ("Unable to locate PySide6/shiboken6").
    pyside_lib, shiboken_lib = find_qt_libs()

    build_dir = root / target["out"]
    shutil.rmtree(build_dir, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyside6",
        "--output-dir",
        str(build_dir),
        "--output-filename",
        target["name"],
    ]

    if args.project == "gamemods":
        cmd += ["--include-package=crimson_rs"]

    common_datas = [
        ("data", "data"),
        ("locale", "locale"),
        ("knowledge_packs", "knowledge_packs"),
        ("dropset_packs", "dropset_packs"),
    ]
    for src, dst in common_datas:
        candidate = root / src
        if candidate.exists():
            cmd += ["--include-data-dir", f"{candidate}={dst}"]

    if args.project == "gamemods":
        quest_packs = ROOT / "quest_packs"
        if quest_packs.exists():
            cmd += ["--include-data-dir", f"{quest_packs}=quest_packs"]
        for file_name in ["crimson_data.db.gz", "vfx_equip_attachments.json", "localizationstring_eng_items.tsv"]:
            candidate = root / file_name
            if candidate.exists():
                cmd += ["--include-data-file", f"{candidate}={file_name}"]
        backend_files = {
            "Linux": [root / "dmm_parser" / "dmm_parser.abi3.so"],
            "Windows": [root / "dmm_parser" / "dmm_parser.pyd"],
        }
        platform_files = backend_files.get(os.name == "nt" and "Windows" or "Linux", [])
        for candidate in platform_files:
            if candidate.exists():
                cmd += ["--include-data-file", f"{candidate}=dmm_parser/{candidate.name}"]
    else:
        for file_name in [
            "parc_parser.dll",
            "item_names.json",
            "store_names.json",
            "item_templates.json",
            "master_templates.json",
            "item_limits.json",
            "item_category_map.json",
            "max_enchant_map.json",
            "waypoint_templates_community.json",
            "abyss_gimmick_templates.json",
            "knowledge_keys_all.json",
            "community_knowledge_keys.json",
            "quest_names.json",
            "quest_database.json",
            "quest_groups.json",
            "mission_names.json",
            "quest_stage_map.json",
            "stage_names.json",
            "gimmick_respawn_timers.json",
            "quest_chains.json",
            "dye_slot_counts.json",
            "buff_skill_descriptions.json",
            "game_map.json",
            "localizationstring_eng_items.tsv",
            "editor_version_standalone.json",
        ]:
            candidate = root / file_name
            if candidate.exists():
                cmd += ["--include-data-file", f"{candidate}={file_name}"]

    cmd += ["--include-data-file", f"{pyside_lib}=PySide6/{Path(pyside_lib).name}"]
    cmd += ["--include-data-file", f"{shiboken_lib}=shiboken6/{Path(shiboken_lib).name}"]

    entry = root / target["entry"]
    if not entry.exists():
        raise SystemExit(f"Missing entry point: {entry}")
    cmd.append(str(entry))

    run(cmd, cwd=root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
