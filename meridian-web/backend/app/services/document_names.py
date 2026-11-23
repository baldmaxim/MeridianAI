"""Читаемые имена документов для интерфейса, подсказок LLM и ссылок на источники."""

_SEPARATOR = " · "
# Хвосты OCR-результатов; порядок — от длинного к короткому (расширение исходника .pdf/.docx/... не трогаем)
_OCR_SUFFIXES = ("_results.md", "_results", ".md")


def document_display_name(original_name: str) -> str:
    """Имя без служебного префикса («КП 343 · 2026-11-09 · папка · ») и OCR-хвоста.

    Берётся последний сегмент после « · ». Пустой результат — исходное имя.
    """
    name = original_name or ""
    segment = name.rsplit(_SEPARATOR, 1)[-1].strip()
    lowered = segment.lower()
    for suffix in _OCR_SUFFIXES:
        if lowered.endswith(suffix):
            segment = segment[: -len(suffix)].rstrip()
            break
    return segment or name
