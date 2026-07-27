import json
import zipfile
from pathlib import Path

import pytest

from comic_archive_converter.cli import main
from comic_archive_converter.core import _safe_names, convert


def cbz(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pages/001.jpg", b"page-one")
        archive.writestr("pages/002.jpg", b"page-two")


def test_round_trip_formats(tmp_path: Path) -> None:
    source = tmp_path / "source.cbz"
    cbz(source)
    seven = tmp_path / "converted.cb7"
    first = convert(source, seven, "cb7")
    assert first["member_count"] == 2
    output = tmp_path / "roundtrip.cbz"
    second = convert(seven, output, "cbz")
    assert first["members"] == second["members"]
    with zipfile.ZipFile(output) as archive:
        assert archive.read("pages/001.jpg") == b"page-one"


def test_safety_and_validation(tmp_path: Path) -> None:
    source = tmp_path / "source.cbz"
    cbz(source)
    with pytest.raises(ValueError, match="format"):
        convert(source, tmp_path / "x.rar", "rar")
    with pytest.raises(ValueError, match="existing"):
        convert(tmp_path / "missing.cbz", tmp_path / "x.cbz", "cbz")
    with pytest.raises(ValueError, match="differ"):
        convert(source, source, "cbz")
    with pytest.raises(ValueError, match="use .cbz"):
        convert(source, tmp_path / "wrong.zip", "cbz")
    output = tmp_path / "output.cbz"
    convert(source, output, "cbz")
    with pytest.raises(ValueError, match="already exists"):
        convert(source, output, "cbz")


def test_unsafe_and_empty_archives(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe.cbz"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../page.jpg", b"bad")
    with pytest.raises(ValueError, match="unsafe"):
        convert(unsafe, tmp_path / "unsafe-out.cbz", "cbz")
    empty = tmp_path / "empty.cbz"
    with zipfile.ZipFile(empty, "w"):
        pass
    with pytest.raises(ValueError, match="no files"):
        convert(empty, tmp_path / "empty-out.cbz", "cbz")


def test_duplicate_members_format_and_temporary_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _safe_names(["Page.jpg", "page.jpg"])
    source = tmp_path / "source.txt"
    source.write_text("not an archive", encoding="utf-8")
    with pytest.raises(ValueError, match="ZIP, CBZ"):
        convert(source, tmp_path / "output.cbz", "cbz")
    archive_source = tmp_path / "source.cbz"
    cbz(archive_source)
    temporary = tmp_path / ".output.tmp.cbz"
    temporary.write_bytes(b"occupied")
    with pytest.raises(ValueError, match="temporary"):
        convert(archive_source, tmp_path / "output.cbz", "cbz")


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "source.cbz"
    cbz(source)
    output = tmp_path / "output.cb7"
    assert main([str(source), "--format", "cb7", "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["format"] == "cb7"
    assert main([str(source), "--format", "cb7", "--output", str(output)]) == 2
