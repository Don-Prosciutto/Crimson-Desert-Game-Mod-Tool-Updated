# dmm-parser: local changes

The parser binaries bundled in CrimsonGameMods/dmm_parser and CrimsonSaveEditor/dmm_parser are built from
upstream dmm-parser (https://github.com/exodiaprivate-eng/dmm-parser), commit 9778425, plus the patches in this
folder (CDMTL v1.0: modified files stay open source).

- game-2.05.01.patch: two new one-byte fields in iteminfo for game 2.05.01
  (ItemInfo._discardSingleCount after _discardable, PageData._uiTextureRotationType after the knowledge keys).
  Older mod JSON without these keys still writes (missing fields are written as 0).
