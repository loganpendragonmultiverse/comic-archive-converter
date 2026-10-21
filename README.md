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

## 1.2.0: Consistent conversion and verified publication

Conversion applies the same header checks as preflight before creating its private workspace. Links, encryption, unavailable sizes, file/directory conflicts and non-portable member paths are refused. Portable paths use forward slashes, have no redundant components, Windows device names, control characters or alternate-stream names, and cannot collide after Unicode normalization and case folding. This conservative policy keeps extraction behavior consistent across the supported operating systems.

ZIP copies are streamed with declared and actual byte limits. 7Z decoding uses py7zr 1.1.4 or newer with its actual expanded-byte limit enabled. Decoded files and directories are compared with the source headers; both member hashes and directory structure are checked after writing the new archive. Empty directories alongside files are retained. Receipt `member_count` counts files; `directory_count` and `directories` describe the retained structure. Filesystem Unicode normalization may change the spelling representation of a path without changing its canonical name.

Source, member and output hashes are streamed. A source change during conversion aborts publication. A completed output is published exclusively with a filesystem hard link, so a destination created after preflight is preserved. The output parent must already exist and support hard links. A pre-existing legacy `.NAME.tmp.cbz`/`.NAME.tmp.cb7` reservation is still refused and left untouched. Keep input files stable until conversion returns; this is accidental-change protection, not a hostile concurrent-filesystem guarantee. Archive metadata, decoder memory and CPU costs are not completely bounded; temporary disk space can exceed the expanded input size while the result is verified.

The release includes four authority documents and a standard-library example generator:

```bash
python examples/make_sample_archive.py sample.cbz
comic-archive-convert sample.cbz --format cb7 --output sample.cb7 --preflight
comic-archive-convert sample.cbz --format cb7 --output sample.cb7
comic-archive-convert --version
```

Installed documentation lives under the environment's `share/doc/comic-archive-converter/`. The sample contains valid synthetic PNG pages and owned metadata; no external comic content or RAR support is introduced.

Complete ZIP member spans are independently decoded with bounded output and checked
for actual size, CRC and codec completion, including directory streams. This avoids
`ZipExtFile`'s declared-size truncation. Stored, Deflate, BZIP2 and ZIP LZMA remain
supported; stdlib Zstandard is supported when available in the selected Python.
ZIP LZMA dictionaries above 64 MiB are refused; optional EOS follows the ZIP flag.
