from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import py7zr

MAX_ENTRIES = 10_000
MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
ZIP_INPUTS = {".zip", ".cbz"}
SEVEN_INPUTS = {".7z", ".cb7"}


def _safe_names(names: list[str]) -> list[str]:
    if len(names) > MAX_ENTRIES:
        raise ValueError("archive exceeds the entry limit")
    cleaned = []
    seen: set[str] = set()
    for name in names:
        normalized = PurePosixPath(name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
            raise ValueError(f"unsafe archive member path: {name}")
        value = normalized.as_posix().rstrip("/")
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            raise ValueError(f"duplicate archive member path: {name}")
        seen.add(key)
        cleaned.append(value)
    return cleaned


def _extract_zip(source: Path, target: Path) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        _safe_names([info.filename for info in infos])
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED:
            raise ValueError("archive exceeds the uncompressed-size limit")
        for info in infos:
            if info.is_dir():
                continue
            relative = PurePosixPath(info.filename.replace("\\", "/"))
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source_handle, destination.open("wb") as output_handle:
                shutil.copyfileobj(source_handle, output_handle)


def _extract_seven(source: Path, target: Path) -> None:
    with py7zr.SevenZipFile(source, "r") as archive:
        _safe_names(archive.getnames())
        archive.extractall(path=target)


def _manifest(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symbolic links are unsupported: {path.relative_to(root)}")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if len(items) >= MAX_ENTRIES:
            raise ValueError("archive exceeds the entry limit")
        if total > MAX_UNCOMPRESSED:
            raise ValueError("archive exceeds the uncompressed-size limit")
        items.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not items:
        raise ValueError("archive contains no files")
    return items


def _write(root: Path, output: Path, output_format: str) -> None:
    if output_format == "cbz":
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
    else:
        with py7zr.SevenZipFile(output, "w") as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())


def _extract(source: Path, target: Path) -> None:
    suffix = source.suffix.casefold()
    if suffix in ZIP_INPUTS:
        _extract_zip(source, target)
    elif suffix in SEVEN_INPUTS:
        _extract_seven(source, target)
    else:
        raise ValueError("source must be ZIP, CBZ, 7Z, or CB7")


def convert(source: Path, output: Path, output_format: str) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    if output_format not in {"cbz", "cb7"}:
        raise ValueError("format must be cbz or cb7")
    if not source.is_file():
        raise ValueError("source must be an existing archive")
    if source == output:
        raise ValueError("output must differ from source")
    if output.exists():
        raise ValueError("output already exists")
    if output.suffix.casefold() != f".{output_format}":
        raise ValueError(f"output must use .{output_format}")
    temporary_output = output.with_name(f".{output.stem}.tmp{output.suffix}")
    if temporary_output.exists():
        raise ValueError("temporary output already exists")
    try:
        with tempfile.TemporaryDirectory(prefix="comic-convert-") as first_name:
            first = Path(first_name)
            _extract(source, first)
            before = _manifest(first)
            _write(first, temporary_output, output_format)
            with tempfile.TemporaryDirectory(prefix="comic-verify-") as second_name:
                second = Path(second_name)
                _extract(temporary_output, second)
                after = _manifest(second)
            if before != after:
                raise ValueError("output member manifest does not match source")
        os.replace(temporary_output, output)
    except Exception:
        if temporary_output.exists():
            temporary_output.unlink()
        raise
    return {
        "version": 1,
        "source": str(source),
        "output": str(output),
        "format": output_format,
        "member_count": len(before),
        "total_bytes": sum(item["size"] for item in before),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "members": before,
    }


def preflight(source: Path, output: Path, output_format: str) -> dict[str, Any]:
    """Inspect archive headers without reading member data or creating files."""
    source, output = source.resolve(), output.resolve()
    if output_format not in {"cbz", "cb7"}:
        raise ValueError("format must be cbz or cb7")
    if not source.is_file():
        raise ValueError("source must be an existing archive")
    conflicts = []
    if not output.parent.is_dir():
        conflicts.append("output parent must be an existing directory")
    if source == output:
        conflicts.append("output must differ from source")
    if output.exists():
        conflicts.append("output already exists")
    if output.suffix.casefold() != f".{output_format}":
        conflicts.append(f"output must use .{output_format}")
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix}")
    if temporary.exists():
        conflicts.append("temporary output already exists")
    members: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()

    def member(
        name: str, size: Any, directory: bool, link: bool, encrypted: bool, regular: bool = True
    ) -> None:
        problems = []
        normalized = PurePosixPath(name.replace("\\", "/"))
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or not normalized.parts
            or PureWindowsPath(name).drive
            or "\x00" in name
        ):
            problems.append("unsafe path")
        key = normalized.as_posix().rstrip("/").casefold()
        if key in seen:
            problems.append("duplicate path")
        seen.add(key)
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
                    info.filename,
                    info.file_size,
                    info.is_dir(),
                    stat.S_ISLNK(mode),
                    bool(info.flag_bits & 1),
                    kind in {0, stat.S_IFREG, stat.S_IFDIR},
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
        PurePosixPath(item["path"].replace("\\", "/")).as_posix().rstrip("/").casefold()
        for item in members
        if not item["directory"]
    }
    for item in members:
        normalized = PurePosixPath(item["path"].replace("\\", "/").casefold())
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
