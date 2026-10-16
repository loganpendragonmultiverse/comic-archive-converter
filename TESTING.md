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
