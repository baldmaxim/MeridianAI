# -*- coding: utf-8 -*-
"""Сверка карточек с текстом договора, который видела модель.

Фрагменты взяты из реального договора генподряда и реальных ответов модели на нём.
"""

from app.schemas.suggestion import SuggestionCard, SuggestionEvidence
from app.services.suggestion_parser import apply_safety_checks, ungrounded_reasons

DOC = """Релевантные фрагменты документов:

[Документ: Договор_ГП.pdf | Страница 23]
3.7.10. В случае, если Генеральный подрядчик выполнил Дополнительные работы без должного согласования, предусмотренного настоящим Договором, такие дополнительные работы не подлежат оплате Застроителем и выполняются за счет средств Генерального подрядчика.

[Документ: Договор_ГП.pdf | Страница 54]
13.1.4 Оплата выполненных по Договору Работ производится Застроительщиком не позднее 15 (пятнадцати) рабочих дней с момента подписания Сторонами Актов о приемке выполненных работ по форме КС-2.

[Документ: Договор_ГП.pdf | Страница 57]
13.2.1 Стороны соглашаются, что Гарантийное удержание в соответствии с настоящим Договором будет составлять 3% (три процента) от стоимости выполненных Генеральным подрядчиком Работ. Договор подписан 01.09.2025.

[Документ: Договор_ГП.pdf | Страница 73]
При этом: - если срок получения ЗОС был соблюден, все ранее взысканные Застройщиком с"""


def _card(text, quote, confidence=0.9):
    return SuggestionCard(type="counter", title="t", text=text, confidence=confidence,
                          needs_user_check=False,
                          evidence=[SuggestionEvidence(source="document", ref="Договор_ГП.pdf, стр. 57",
                                                       text=quote)])


def test_faithful_quote_passes():
    card = _card("По пункту 13.2.1 гарантийное удержание 3%, а не 10%.",
                 "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3% (три процента)")
    [out] = apply_safety_checks([card], DOC)
    assert out.needs_user_check is False and out.confidence == 0.9


def test_paraphrase_with_abbreviations_passes():
    """Модель сокращает: «ГП», «доп.» — это пересказ пункта, а не выдумка."""
    card = _card("Согласно п. 3.7.10 работы без допсоглашения не оплачиваются.",
                 "Если ГП выполнил доп. работы без согласования, они не подлежат оплате и выполняются за счет ГП.")
    assert ungrounded_reasons(card, DOC) == []


def test_clause_absent_from_documents_flagged():
    card = _card("Будем оспаривать согласно п. 20.8 договора.",
                 "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3%")
    [out] = apply_safety_checks([card], DOC)
    assert out.needs_user_check is True and out.confidence <= 0.6
    assert "20.8" in ungrounded_reasons(card, DOC)[0]


def test_guessed_ending_in_brackets_flagged():
    """Реальный случай: страница обрывается, модель дописала концовку в квадратных скобках."""
    card = _card("Если мы соблюдём срок ЗОС, неустойки вернут.",
                 "если срок получения ЗОС был соблюден, все ранее взысканные Застройщиком... "
                 "[подлежат возврату/не учитываются]")
    reasons = ungrounded_reasons(card, DOC)
    assert any("дописана" in r for r in reasons)


def test_invented_quote_flagged():
    card = _card("В разделе 13 удержания нет.",
                 "В разделе 13.1 отсутствует упоминание о гарантийном удержании в размере 10% от текущих платежей.")
    reasons = ungrounded_reasons(card, DOC)
    assert any("не совпадает" in r for r in reasons)


def test_quote_attributed_to_wrong_clause_flagged():
    """Реальный случай: удержание 3% из п. 13.2.1 модель приписала п. 13.1.4 (срок оплаты)."""
    card = _card("По пунктам 13.1.4 и 13.2.1 удержание ограничено 3%.",
                 "п. 13.1.4: Застроитель производит гарантийное удержание в размере 3% от стоимости работ. "
                 "п. 13.2.1: Гарантийное удержание будет составлять 3% (три процента)")
    assert ungrounded_reasons(card, DOC) == ["текст цитаты не из пункта: 13.1.4"]


def test_short_or_shared_clause_segments_not_flagged():
    """Реальные ложные срабатывания: сжатый пересказ и текст, общий на два номера подряд."""
    short = _card("Оплата через 15 рабочих дней.",
                  "п. 13.1.4: Оплата 15 раб. дней; п. 13.2.1: Гарантийное удержание будет составлять 3% (три процента)")
    assert ungrounded_reasons(short, DOC) == []
    shared = _card("Удержание 3%.", "п. 13.1.4 и 13.2.1: Гарантийное удержание в соответствии с настоящим "
                                     "Договором будет составлять 3% (три процента)")
    assert ungrounded_reasons(shared, DOC) == []


def test_quote_with_correct_clauses_passes():
    card = _card("Оплата через 15 рабочих дней, удержание 3%.",
                 "13.1.4 Оплата выполненных Работ производится не позднее 15 (пятнадцати) рабочих дней. "
                 "13.2.1 Гарантийное удержание будет составлять 3% (три процента)")
    assert ungrounded_reasons(card, DOC) == []


def test_dates_and_money_are_not_clauses():
    card = _card("Договор от 01.09.2025, удержание 3% по п. 13.2.1, аванс 1,2 млрд.",
                 "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3% (три процента)")
    assert ungrounded_reasons(card, DOC) == []


def test_no_documents_no_quote_check():
    """Без документов цитату сверять не с чем; ссылка на пункт всё равно подозрительна."""
    card = SuggestionCard(type="ask", title="t", text="Какой у нас срок оплаты?", confidence=0.7,
                          evidence=[SuggestionEvidence(source="transcript", text="срок оплаты")])
    assert ungrounded_reasons(card, "") == []
    card.text = "По п. 7.3 срок оплаты 45 дней."
    assert ungrounded_reasons(card, "") == ["пункт не найден в документах: 7.3"]


def test_check_reasons_explain_the_flag():
    card = _card("Будем оспаривать согласно п. 20.8 договора.",
                 "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3%")
    [out] = apply_safety_checks([card], DOC)
    assert out.check_reasons == ["пункт не найден в документах: 20.8"]


def test_clean_card_has_no_reasons_and_model_doubt_is_explained():
    ok = _card("По пункту 13.2.1 гарантийное удержание 3%, а не 10%.",
               "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3% (три процента)")
    [out] = apply_safety_checks([ok], DOC)
    assert out.needs_user_check is False and out.check_reasons == []
    doubt = _card("По пункту 13.2.1 гарантийное удержание 3%.",
                  "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3% (три процента)")
    doubt.needs_user_check = True
    [out] = apply_safety_checks([doubt], DOC)
    assert out.needs_user_check is True and out.check_reasons == ["модель не уверена в опоре"]


def test_model_cannot_fill_reasons_itself():
    card = _card("По пункту 13.2.1 гарантийное удержание 3%.",
                 "Гарантийное удержание в соответствии с настоящим Договором будет составлять 3% (три процента)")
    card.check_reasons = ["всё проверено"]
    [out] = apply_safety_checks([card], DOC)
    assert out.check_reasons == []
