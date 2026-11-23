# dmm-parser: local changes

**Since tool version 2.6.3 there are none.** The parser bundled in CrimsonGameMods/dmm_parser and
CrimsonSaveEditor/dmm_parser is the official upstream build of dmm-parser
(https://github.com/exodiaprivate-eng/dmm-parser), commit 9d9747c (game 2.05.01): `dmm_parser.pyd` is the
file shipped in that repository, unchanged. See `UPSTREAM_COMMIT.txt` next to the binaries.

History (CDMTL v1.0: modified files stay open source):

- game-2.05.01.patch - used in tool versions 2.5.0 to 2.6.2 on top of upstream 9778425, before upstream
  supported game 2.05.01. Two new one-byte fields in iteminfo (ItemInfo._discardSingleCount after
  _discardable, PageData._uiTextureRotationType after the knowledge keys). Upstream 9d9747c has the same
  two fields at the same place, plus MissionResultData.level_gimmick_scene_object_info, which the patch
  lacked (1,795 of 6,872 missioninfo records were only kept as raw bytes).
