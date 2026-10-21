# Testing

Run `python -m pip install -e ".[dev]"`, `ruff format --check .`, `ruff check .`, `mypy src`, `pytest`, `python -m pip_audit`, and `python -m build`.

## 1.1.0: Archive preflight

`--preflight` lists archive members, declared expanded byte estimates, unsafe or duplicate paths, links, encryption, missing size metadata, safety-limit findings and output conflicts. It reads headers only: no member decoding, extraction, temporary directories, output files or parent-directory creation. Declared estimates are not verified actual expanded sizes or an integrity guarantee. Missing sizes remain null and block readiness. Exit 0 means the headers pass preflight, 1 means findings need attention, and 2 means the archive could not be inspected. Conversion still performs its full validation independently.

```bash
comic-archive-convert issue.cb7 --format cbz --output issue.cbz --preflight
```

Preflight requires the output parent to exist as a directory. It also rejects
file/directory ancestor conflicts (including case-normalized member names) in either
archive order. These checks do not create directories or extract members.

## 1.2.1 completion validation

Keep all existing tests and the 90% branch-aware coverage requirement. Run the full commands above, then exercise the installed wheel and source distribution from outside this checkout. Use the installed example generator, convert ZIP to 7Z and back, compare every file's bytes and the empty directory, and independently run a real 7-Zip integrity check. No RAR conversion is promised.

Regressions cover preflight/conversion agreement, unsafe and non-regular members, real ZIP/7Z round trips, bounded actual expansion despite misleading metadata, streamed hashing, changed sources, dangling/looping output links, destination races, and unsupported ZIP headers. Confirm all rejected operations leave existing destinations untouched. Metadata-only preflight must not create a directory, decode a member or write any file.

The Python 3.10/3.14 matrix and all checks remain intact. The py7zr minimum is 1.1.4 to enable the decoder's expanded-byte guard. Output publication requires hard links in the existing destination directory; no filesystem-wide locking, RAR decoder installation or metadata-preservation claim is added.

Complete ZIP member spans are independently decoded with bounded output and checked
for actual size, CRC and codec completion, including directory streams. This avoids
`ZipExtFile`'s declared-size truncation. Stored, Deflate, BZIP2 and ZIP LZMA remain
supported; stdlib Zstandard is supported when available in the selected Python.
ZIP LZMA dictionaries above 64 MiB are refused; optional EOS follows the ZIP flag.

## Release artifact closure

The tag workflow pins maintained action commits, checks the stable tag against
the package version before building, runs the full quality and dependency-audit
checks, validates wheel/sdist metadata and writes SHA256SUMS over those exact
two payloads. Normal PR/main native matrix and independent installed-artifact
review remain required before a public release. It does not publish a GitHub
release automatically.
