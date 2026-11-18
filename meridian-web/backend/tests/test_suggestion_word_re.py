# -*- coding: utf-8 -*-
"""Юникод-слова в проверке опоры цитат: турецкие буквы и ё не режут слово."""

from app.services.suggestion_parser import _WORD_RE, _fold, _stem_words


def test_word_re_keeps_turkish_and_yo_words():
    text = "Çalışma ğüzel ışık öğrenci şantiye ёлка İstanbul_x 5.1"
    words = _WORD_RE.findall(_fold(text))
    assert "çalışma" in words and "ğüzel" in words and "ışık" in words
    assert "öğrenci" in words and "şantiye" in words and "елка" in words  # ё → е
    assert "istanbul" in [w.replace("̇", "") for w in words]  # подчёркивание — граница слова
    assert "x" in words and "5" in words


def test_stem_words_turkish_dotted_capital_i():
    # İ → i без комбинирующей точки: заглавная и строчная формы дают одну основу
    assert _stem_words("İstanbul şantiyesi") == _stem_words("istanbul şantiyesi")
    assert _stem_words("Ёлка") == _stem_words("елка")
