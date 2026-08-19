"""Publicизация presigned-ссылок: браузер ходит на свой домен, а не в S3 напрямую."""

import pytest

from app.services import s3


@pytest.fixture
def public_base(monkeypatch):
    settings = s3.get_settings()
    monkeypatch.setattr(settings, "s3_public_base_url", "https://meridianai.ru/s3", raising=False)
    return settings


def test_url_rewritten_to_public_base(public_base):
    src = "https://s3.cloud.ru/meridian/meridian/1/batch/a.ogg?X-Amz-Signature=abc&X-Amz-Expires=900"
    out = s3._public(src)
    assert out.startswith("https://meridianai.ru/s3/meridian/meridian/1/batch/a.ogg?")
    assert "X-Amz-Signature=abc" in out  # подпись и параметры сохранены


def test_empty_base_keeps_direct_url(monkeypatch):
    settings = s3.get_settings()
    monkeypatch.setattr(settings, "s3_public_base_url", "", raising=False)
    src = "https://s3.cloud.ru/meridian/key?X-Amz-Signature=abc"
    assert s3._public(src) == src


def test_trailing_slash_in_base_not_duplicated(monkeypatch):
    settings = s3.get_settings()
    monkeypatch.setattr(settings, "s3_public_base_url", "https://meridianai.ru/s3/", raising=False)
    assert s3._public("https://s3.cloud.ru/bucket/k") == "https://meridianai.ru/s3/bucket/k"
