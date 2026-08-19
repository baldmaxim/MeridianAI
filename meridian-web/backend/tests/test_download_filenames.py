"""Скачивание результатов офлайн-распознавания: кириллица в Content-Disposition.

HTTP-заголовки кодируются latin-1 → сырое русское имя роняло ответ 500.
"""

from starlette.responses import Response

from app.core.http_files import ascii_fallback, content_disposition, safe_download_name


def test_cyrillic_header_encodes_to_latin1():
    value = content_disposition("Совещание по ВОР.txt")
    # не должно падать на UnicodeEncodeError при формировании ответа
    resp = Response(content=b"x", headers={"Content-Disposition": value})
    raw = dict(resp.raw_headers)[b"content-disposition"].decode("latin-1")
    assert "filename*=UTF-8''" in raw
    assert "%D0%A1" in raw  # «С» в utf-8 percent-encoding


def test_ascii_fallback_is_transliterated():
    assert ascii_fallback("Протокол.txt") == "Protokol.txt"
    assert ascii_fallback("報告.txt") == "__.txt"


def test_safe_download_name_strips_path_and_quotes():
    assert safe_download_name(r"C:\dir\запись.mp3") == "запись.mp3"
    assert safe_download_name('за"пись.mp3') == "запись.mp3"
    assert safe_download_name("") == "download"
    assert safe_download_name("a\r\nb.txt") == "ab.txt"
