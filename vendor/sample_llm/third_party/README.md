# Bundled third-party component

This directory contains the pinned `cnki-metadata-exporter` component used by FYrepo's production collection workflow.

- Upstream: https://github.com/JYao-Chen/cnki-metadata-exporter
- Version: `0.2.0`
- Commit: `4bdf8e108c81c4d1a0590377aec1238f534e1a18`
- License: MIT

Files:

- `cnki-metadata-exporter-0.2.0-4bdf8e1.zip`: `git archive` of the original pinned upstream tree;
- `cnki_metadata_exporter-0.2.0-py3-none-any.whl`: wheel rebuilt from that same source tree using its original Hatchling configuration;
- `cnki-metadata-exporter.LICENSE.txt`: upstream MIT license.

## H1 repair (2026-10-07)

The two binaries originally copied from `Synex1213/sample-llm@2167aa39` were already invalid in upstream Git blobs: both lacked a ZIP central directory and EOCD; the wheel's second local entry also had a broken DEFLATE stream. Matching SHA256 values only proved byte identity, not ZIP validity. The first valid entry matched the original upstream `native_export.py`; partial salvage was not used.

Both files have been regenerated from the complete `JYao-Chen/cnki-metadata-exporter@4bdf8e1` Git tree, without changes to its six Python modules. `vendor/SAMPLE_LLM_SOURCE.json` now distinguishes the original sample-llm file hashes from the delivered file hashes and records the original component commit, tree and build tools. FYrepo's installer actively reads this manifest, decompresses every ZIP entry, verifies wheel RECORD hashes/sizes, and compares wheel modules with the source archive before invoking offline pip.

Rebuild instructions and actual offline installation checks: `docs/SAMPLING_CNKI_H1.md`. The rebuilt `py3-none-any` wheel has been installed and its real collector/merge entry points tested on Linux/Python 3.12. Institutional CNKI access and Windows browser login still require acceptance on the user's machine; the legacy claim of Windows-tested binaries does not apply to this rebuild.
