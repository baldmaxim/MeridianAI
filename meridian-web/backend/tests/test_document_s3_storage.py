"""Этап 22: document_storage — валидация, object key без raw filename, presigned+SSE, HEAD,
download_to_tempfile, safe_storage_ref. Без БД и без реальных AWS-вызовов (s3 замокан)."""

import os

import pytest

from app.config import get_settings
from app.services import document_storage as ds
from app.services import s3 as s3mod


# --- object key: без raw filename ---

def test_build_object_key_has_no_raw_filename():
    key = ds.build_object_key(7, "Секретный Договор №5 (final).pdf")
    assert key.endswith(".pdf")
    assert "documents" in key
    for token in ("Секретный", "Договор", "final", " "):
        assert token not in key
    # uuid-хвост: 32 hex перед расширением
    stem = os.path.splitext(os.path.basename(key))[0]
    assert len(stem) == 32 and all(c in "0123456789abcdef" for c in stem)


# --- validate_upload ---

def test_validate_upload_rejects_unsupported_ext():
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_upload("virus.exe", None, 10)


def test_validate_upload_accepts_supported_exts():
    for fn in ("a.pdf", "b.docx", "c.xlsx", "d.txt", "e.md", "f.csv"):
        assert ds.validate_upload(fn, None, 10) == os.path.splitext(fn)[1]


def test_validate_upload_rejects_too_large(monkeypatch):
    monkeypatch.setattr(get_settings(), "document_s3_max_upload_bytes", 1000)
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_upload("a.pdf", "application/pdf", 2000)
    assert ds.validate_upload("a.pdf", "application/pdf", 500) == ".pdf"


def test_validate_upload_content_type_allowlist():
    # чужой content-type отклоняется; допустимый и «generic» проходят (расширение авторитетно)
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_upload("a.pdf", "image/png", 10)
    assert ds.validate_upload("a.pdf", "application/pdf", 10) == ".pdf"
    assert ds.validate_upload("a.pdf", "application/octet-stream", 10) == ".pdf"
    assert ds.validate_upload("a.pdf", None, 10) == ".pdf"


def test_validate_upload_rejects_path_traversal():
    for bad in ("../../etc/passwd.pdf", "a/b.pdf", "a\\b.pdf", "x\x00.pdf", ""):
        with pytest.raises(ds.DocumentStorageError):
            ds.validate_upload(bad, None, 10)


# --- presigned PUT (+SSE) ---

def test_create_presigned_put_default_no_sse(monkeypatch):
    seen = {}

    def _fake(key, ttl=None, sse=None, kms_key_id=None):
        seen["sse"] = sse
        seen["kms"] = kms_key_id
        return "http://fake-s3/put"

    monkeypatch.setattr(s3mod, "presign_put", _fake)
    monkeypatch.setattr(get_settings(), "document_s3_sse", "")
    url, headers = ds.create_presigned_put("documents/abc.pdf", "application/pdf")
    assert url == "http://fake-s3/put"
    assert seen["sse"] is None
    assert not any(h.lower().startswith("x-amz-server-side-encryption") for h in headers)
    assert headers.get("Content-Type") == "application/pdf"


def test_create_presigned_put_with_sse(monkeypatch):
    seen = {}

    def _fake(key, ttl=None, sse=None, kms_key_id=None):
        seen["sse"] = sse
        seen["kms"] = kms_key_id
        return "http://fake-s3/put"

    monkeypatch.setattr(s3mod, "presign_put", _fake)
    monkeypatch.setattr(get_settings(), "document_s3_sse", "aws:kms")
    monkeypatch.setattr(get_settings(), "document_s3_kms_key_id", "key-123")
    url, headers = ds.create_presigned_put("documents/abc.pdf", "application/pdf")
    assert seen["sse"] == "aws:kms" and seen["kms"] == "key-123"
    assert headers["x-amz-server-side-encryption"] == "aws:kms"
    assert headers["x-amz-server-side-encryption-aws-kms-key-id"] == "key-123"


# --- HEAD валидация ---

def test_validate_head_missing_object():
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_head(None)


def test_validate_head_too_large(monkeypatch):
    monkeypatch.setattr(get_settings(), "document_s3_max_upload_bytes", 1000)
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_head({"size": 5000, "content_type": "application/pdf"})


def test_validate_head_bad_content_type():
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_head({"size": 10, "content_type": "image/png"})
    assert ds.validate_head({"size": 10, "content_type": "application/pdf"})["size"] == 10
    # generic/пустой content-type пропускаем
    assert ds.validate_head({"size": 10, "content_type": None})["size"] == 10


def test_validate_head_rejects_negative_size():
    with pytest.raises(ds.DocumentStorageError):
        ds.validate_head({"size": -1, "content_type": "application/pdf"})


# --- download_to_tempfile + cleanup ---

async def test_download_to_tempfile_and_cleanup(monkeypatch):
    async def _dl(key, dest):
        with open(dest, "wb") as f:
            f.write(b"hello")

    monkeypatch.setattr(s3mod, "download_to", _dl)
    path = await ds.download_to_tempfile("documents/abc.pdf", ".pdf")
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"hello"
    tmpdir = os.path.dirname(path)
    ds.cleanup_tempfile(path)
    assert not os.path.exists(tmpdir)
    ds.cleanup_tempfile(None)  # идемпотентно / no-op


async def test_download_to_tempfile_cleans_up_on_failure(monkeypatch):
    import glob
    import tempfile as _tf

    async def _fail(key, dest):
        raise RuntimeError("network down")

    monkeypatch.setattr(s3mod, "download_to", _fail)
    pattern = os.path.join(_tf.gettempdir(), "meridian_docstore_*")
    before = set(glob.glob(pattern))
    with pytest.raises(RuntimeError):
        await ds.download_to_tempfile("documents/x.pdf", ".pdf")
    assert set(glob.glob(pattern)) == before  # tmpdir не утёк при ошибке скачивания


# --- safe_storage_ref: без bucket/key/filename ---

def test_safe_storage_ref_redacts():
    ref = ds.safe_storage_ref("meridian/7/documents/abcdef0123456789.pdf")
    assert ref.startswith("s3:") and ref.endswith(".pdf")
    for token in ("meridian", "documents", "abcdef0123456789", "/7/"):
        assert token not in ref
    assert ds.safe_storage_ref(None) == "none"


# --- is_enabled kill-switch ---

def test_is_enabled_false_when_killswitch_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "document_s3_upload_enabled", False)
    assert ds.is_enabled() is False
    assert ds.storage_backend() == "local"
