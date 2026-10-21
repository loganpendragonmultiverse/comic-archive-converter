# Changelog

## 1.2.0 - 2026-10-21

- Apply header preflight consistently before conversion and reject non-portable paths, links and unsafe metadata.
- Enforce ZIP copy and native 7Z expanded-byte limits during decoding, then verify the extracted tree.
- Preserve empty directories alongside byte-identical files and report their verified structure.
- Stream fingerprints, detect source changes and publish completed outputs exclusively without overwriting raced destinations.
- Make malformed codec/header errors actionable and ship installed authority documents plus an owned PNG example generator.

## 1.1.0 - 2026-10-16

- Added non-converting header preflight with declared size estimates, member findings and output conflicts.
- Reject missing or invalid output parents and file/directory ancestor conflicts without writes.
- Added synthetic regression fixtures for failure isolation and output preservation.


## 1.0.0 - 2026-07-26

- Added CBZ/ZIP and CB7/7Z input with CBZ or CB7 output.
- Added safe-path, symbolic-link, entry-count, and size controls.
- Added post-conversion integrity checks and SHA-256 member-manifest receipts.

The 1.2.0 release also validates full compressed ZIP streams, detecting forged
size/CRC prefixes, unfinished streams and trailing codec data before publication.
