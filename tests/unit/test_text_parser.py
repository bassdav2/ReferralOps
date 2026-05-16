from __future__ import annotations

from pathlib import Path

from backend.app.documents.parser_pdf import parse_text


def test_parse_text_replaces_invalid_utf8(tmp_path: Path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"hello\xffworld")

    parsed = parse_text(path)

    assert "hello" in parsed.text
    assert "world" in parsed.text
