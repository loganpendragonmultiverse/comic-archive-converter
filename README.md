# Comic Archive Converter

[![CI](https://github.com/loganpendragonmultiverse/comic-archive-converter/actions/workflows/ci.yml/badge.svg)](https://github.com/loganpendragonmultiverse/comic-archive-converter/actions/workflows/ci.yml)

Comic Archive Converter converts ZIP/CBZ and 7Z/CB7 archives into a new CBZ or CB7 while preserving every member's bytes and relative path. It rejects unsafe paths and symbolic links, enforces entry and uncompressed-size limits, stages work in a temporary directory, validates the completed archive, and compares SHA-256 member manifests before publishing the output.

## Three-minute start

```bash
python -m pip install .
comic-archive-convert issue.cb7 --format cbz --output issue.cbz
comic-archive-convert issue.cbz --format cb7 --output issue.cb7
```

The JSON receipt records source and output hashes, member counts, total bytes, and the verified per-member manifest. The source is always retained and an existing output is refused.

RAR/CBR is deliberately unsupported because reliable decoding depends on separately installed backends and writing RAR is not an open portable path. Compression settings, timestamps, permissions, and archive comments may change; only member paths and bytes are promised. Password-protected archives are unsupported. Keep independent backups. Requires Python 3.10 or newer.

Part of the [Logan Pendragon Forge open-source collection](https://www.loganpendragonforge.com/open-source/). Licensed under the [MIT License](LICENSE).

## 1.1.0: Archive preflight

`--preflight` lists archive members, declared expanded byte estimates, unsafe or duplicate paths, links, encryption, missing size metadata, safety-limit findings and output conflicts. It reads headers only: no member decoding, extraction, temporary directories, output files or parent-directory creation. Declared estimates are not verified actual expanded sizes or an integrity guarantee. Missing sizes remain null and block readiness. Exit 0 means the headers pass preflight, 1 means findings need attention, and 2 means the archive could not be inspected. Conversion still performs its full validation independently.

```bash
comic-archive-convert issue.cb7 --format cbz --output issue.cbz --preflight
```

Preflight requires the output parent to exist as a directory. It also rejects
file/directory ancestor conflicts (including case-normalized member names) in either
archive order. These checks do not create directories or extract members.
