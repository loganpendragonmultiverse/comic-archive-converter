from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Any, cast

import py7zr

from . import __version__
from .zip_streams import verify_compressed_stream

MAX_ENTRIES = 10_000
MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
ZIP_INPUTS = {".zip", ".cbz"}
SEVEN_INPUTS = {".7z", ".cb7"}
_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{p}{n}" for p in ("com", "lpt") for n in (*range(1, 10), "¹", "²", "³")
}


def _key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _unsafe_name(name: str) -> bool:
    normalized = PurePosixPath(name.replace("\\", "/"))
    return (
        normalized.is_absolute()
        or ".." in normalized.parts
        or not normalized.parts
        or bool(PureWindowsPath(name).drive)
        or "\\" in name
        or name.rstrip("/") != normalized.as_posix()
        or any(
            any(ord(c) < 32 or c in '<>:"|?*' for c in part)
            or part.endswith((" ", "."))
            or part.split(".")[0].casefold() in _RESERVED
            for part in normalized.parts
        )
    )


def _safe_names(names: list[str]) -> list[str]:
    if len(names) > MAX_ENTRIES:
        raise ValueError("archive exceeds the entry limit")
    cleaned, seen = [], set()
    for name in names:
        if _unsafe_name(name):
            raise ValueError(f"unsafe archive member path: {name}")
        value = PurePosixPath(name).as_posix().rstrip("/")
        if _key(value) in seen:
            raise ValueError(f"duplicate archive member path: {name}")
        seen.add(_key(value))
        cleaned.append(value)
    return cleaned


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("source must be an existing regular archive")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _paths(source: Path, output: Path) -> tuple[Path, Path]:
    try:
        source = source.expanduser().resolve(strict=True)
        _signature(source)
        return source, output.expanduser().absolute()
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"source must be an existing archive and paths must resolve: {exc}"
        ) from exc


def _copy_member(source: IO[bytes], destination: IO[bytes], expected: int, remaining: int) -> int:
    count = 0
    while True:
        block = source.read(min(1024 * 1024, min(expected, remaining) - count + 1))
        if not block:
            break
        count += len(block)
        if count > expected or count > remaining:
            raise ValueError("actual expanded member exceeds its declared size or safety limit")
        destination.write(block)
    if count != expected:
        raise ValueError("actual expanded member size differs from its declared size")
    return count


def _checked_headers(source: Path) -> list[dict[str, Any]]:
    report = preflight(source, source.with_name(".header-check.cbz"), "cbz")
    issues = report["issues"] + [
        problem for item in report["members"] for problem in item["issues"]
    ]
    if issues:
        raise ValueError("archive headers are unsafe: " + "; ".join(dict.fromkeys(issues)))
    return cast(list[dict[str, Any]], report["members"])


def _extract_zip(source: Path, target: Path) -> None:
    total = 0
    with zipfile.ZipFile(source, "r") as archive:
        for info in archive.infolist():
            verify_compressed_stream(archive, info)
        for info in archive.infolist():
            destination = target.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as reader, destination.open("xb") as writer:
                total += _copy_member(reader, writer, info.file_size, MAX_UNCOMPRESSED - total)


def _extract_seven(source: Path, target: Path) -> None:
    # The decoder enforces the actual expanded-byte budget during decompression,
    # rather than waiting for the extracted tree's manifest.
    with py7zr.SevenZipFile(source, "r", max_extract_size=MAX_UNCOMPRESSED) as archive:
        archive.extractall(path=target)


def _manifest(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(
                f"symbolic links and non-regular files are unsupported: {path.relative_to(root)}"
            )
        total += info.st_size
        if len(items) >= MAX_ENTRIES:
            raise ValueError("archive exceeds the entry limit")
        if total > MAX_UNCOMPRESSED:
            raise ValueError("archive exceeds the uncompressed-size limit")
        items.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": info.st_size,
                "sha256": _digest(path),
            }
        )
    if not items:
        raise ValueError("archive contains no files")
    return items


def _directories(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if stat.S_ISDIR(path.lstat().st_mode)
    )


def _write(root: Path, output: Path, output_format: str) -> None:
    if output_format == "cbz":
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                archive.write(path, path.relative_to(root).as_posix())
    else:
        with py7zr.SevenZipFile(output, "w") as archive:
            for path in sorted(root.rglob("*")):
                archive.write(path, path.relative_to(root).as_posix())


def _extract(source: Path, target: Path) -> None:
    headers = _checked_headers(source)
    if source.suffix.casefold() in ZIP_INPUTS:
        _extract_zip(source, target)
    elif source.suffix.casefold() in SEVEN_INPUTS:
        _extract_seven(source, target)
    else:
        raise ValueError("source must be ZIP, CBZ, 7Z, or CB7")
    expected_files = {
        unicodedata.normalize("NFC", item["path"]): item["declared_expanded_bytes"]
        for item in headers
        if not item["directory"]
    }
    expected_directories = set()
    for item in headers:
        name = PurePosixPath(item["path"])
        if item["directory"]:
            expected_directories.add(unicodedata.normalize("NFC", name.as_posix()))
        expected_directories.update(
            unicodedata.normalize("NFC", parent.as_posix())
            for parent in name.parents
            if parent != PurePosixPath(".")
        )
    actual_files, actual_directories = {}, set()
    for path in target.rglob("*"):
        info = path.lstat()
        relative_name = unicodedata.normalize("NFC", path.relative_to(target).as_posix())
        if stat.S_ISDIR(info.st_mode):
            actual_directories.add(relative_name)
        elif stat.S_ISREG(info.st_mode):
            actual_files[relative_name] = info.st_size
        else:
            raise ValueError("decoder produced a symbolic link or non-regular member")
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ValueError("decoded tree does not match declared member paths and sizes")


def convert(source: Path, output: Path, output_format: str) -> dict[str, Any]:
    source, output = _paths(source, output)
    report = preflight(source, output, output_format)
    if not report["ready"]:
        issues = (
            report["output_conflicts"]
            + report["issues"]
            + [p for item in report["members"] for p in item["issues"]]
        )
        raise ValueError("conversion refused: " + "; ".join(dict.fromkeys(issues)))
    signature = _signature(source)
    source_hash = _digest(source)
    with tempfile.TemporaryDirectory(prefix=".comic-convert-", dir=output.parent) as workspace:
        root = Path(workspace)
        first = root / "source"
        second = root / "verification"
        first.mkdir()
        second.mkdir()
        _extract(source, first)
        before, directories = _manifest(first), _directories(first)
        temporary_output = root / ("validated." + output_format)
        _write(first, temporary_output, output_format)
        _extract(temporary_output, second)
        if before != _manifest(second) or directories != _directories(second):
            raise ValueError("output member manifest does not match source")
        if (
            _signature(source) != signature
            or _digest(source) != source_hash
            or _signature(source) != signature
        ):
            raise ValueError("source changed during conversion; output was not published")
        output_hash = _digest(temporary_output)
        # Hard-link publication is exclusive even if another writer creates the
        # destination after preflight. The validated bytes are on the same FS.
        os.link(temporary_output, output)
    return {
        "version": 1,
        "tool_version": __version__,
        "source": str(source),
        "output": str(output),
        "format": output_format,
        "member_count": len(before),
        "directory_count": len(directories),
        "directories": directories,
        "total_bytes": sum(item["size"] for item in before),
        "source_sha256": source_hash,
        "output_sha256": output_hash,
        "members": before,
        "source_stability_verified": True,
    }


def preflight(source: Path, output: Path, output_format: str) -> dict[str, Any]:
    """Inspect archive headers without reading member data or creating files."""
    source, output = _paths(source, output)
    if output_format not in {"cbz", "cb7"}:
        raise ValueError("format must be cbz or cb7")
    conflicts = []
    try:
        parent_directory = stat.S_ISDIR(output.parent.stat().st_mode)
    except OSError:
        parent_directory = False
    if not parent_directory:
        conflicts.append("output parent must be an existing directory")
    same_source = source == (output if output.is_symlink() else output.resolve())
    if same_source:
        conflicts.append("output must differ from source")
    if os.path.lexists(output):
        conflicts.append("output already exists")
    if output.suffix.casefold() != f".{output_format}":
        conflicts.append(f"output must use .{output_format}")
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix}")
    if os.path.lexists(temporary):
        conflicts.append("temporary output already exists")
    members: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()

    def member(
        name: str, size: Any, directory: bool, link: bool, encrypted: bool, regular: bool = True
    ) -> None:
        problems = []
        normalized = PurePosixPath(name.replace("\\", "/"))
        if _unsafe_name(name):
            problems.append("unsafe path")
        key = _key(normalized.as_posix().rstrip("/"))
        if key in seen:
            problems.append("duplicate path")
        seen.add(key)
        if directory and size not in (0, None):
            problems.append("directory contains unexpected member data")
        if link or not regular:
            problems.append("symbolic link or non-regular member")
        if encrypted:
            problems.append("encrypted member")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            size = None
            if not directory:
                problems.append("declared size unavailable")
        members.append(
            {
                "path": name,
                "directory": directory,
                "declared_expanded_bytes": size,
                "issues": problems,
            }
        )

    suffix = source.suffix.casefold()
    if suffix in ZIP_INPUTS:
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                member(
                    info.orig_filename,
                    info.file_size,
                    info.is_dir(),
                    stat.S_ISLNK(mode),
                    bool(info.flag_bits & 1),
                    kind == 0 or kind == (stat.S_IFDIR if info.is_dir() else stat.S_IFREG),
                )
    elif suffix in SEVEN_INPUTS:
        with py7zr.SevenZipFile(source, "r") as archive:
            encrypted = archive.needs_password()
            for info in archive.list():
                member(
                    info.filename,
                    info.uncompressed,
                    info.is_directory,
                    info.is_symlink,
                    encrypted,
                    info.is_file or info.is_directory,
                )
    else:
        raise ValueError("source must be ZIP, CBZ, 7Z, or CB7")
    file_paths = {
        _key(PurePosixPath(item["path"].replace("\\", "/")).as_posix().rstrip("/"))
        for item in members
        if not item["directory"]
    }
    for item in members:
        normalized = PurePosixPath(_key(item["path"].replace("\\", "/")))
        if any(parent.as_posix() in file_paths for parent in normalized.parents):
            item["issues"].append("file/directory ancestor conflict")
    if len(members) > MAX_ENTRIES:
        issues.append("archive exceeds the entry limit")
    if not any(not item["directory"] for item in members):
        issues.append("archive contains no files")
    known_total = sum(item["declared_expanded_bytes"] or 0 for item in members)
    complete = all(
        item["declared_expanded_bytes"] is not None for item in members if not item["directory"]
    )
    if known_total > MAX_UNCOMPRESSED:
        issues.append("archive exceeds the declared uncompressed-size limit")
    return {
        "schema_version": 1,
        "tool_version": __version__,
        "preflight": True,
        "source": str(source),
        "output": str(output),
        "format": output_format,
        "members": members,
        "member_count": len(members),
        "declared_expanded_bytes": known_total if complete else None,
        "known_declared_expanded_bytes": known_total,
        "declared_sizes_complete": complete,
        "size_note": "Declared estimates from archive headers; member data and actual expanded sizes are not verified.",
        "output_conflicts": conflicts,
        "issues": issues,
        "ready": not conflicts and not issues and not any(item["issues"] for item in members),
    }
