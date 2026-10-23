"""Словарь терминов для правки распознанного текста.

GigaAM пишет «машины места» вместо «машино-места»: слова звучат правильно, а запись
другая. Здесь только данные и ключи сравнения; поиск похожих кусков — в term_matcher,
правка — в term_corrector.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

BASE_LEXICON_PATH = Path(__file__).with_name("asr_lexicon.txt")

# Форма короче этого (в буквах) ищется только точно: на коротких строках любая пара
# слов «похожа», нечёткий поиск даёт одни ложные кандидаты.
MIN_FUZZY_LEN = 5

_NOT_ALNUM = re.compile(r"[^а-яa-z0-9]")

# Фонетическая свёртка: безударные/звонкие пары сливаются, как их путает распознавание.
_PHON_MAP = str.maketrans({
    "о": "а",
    "е": "и", "э": "и", "я": "и", "ы": "и", "й": "и",
    "ю": "у",
    "б": "п", "в": "ф", "г": "к", "д": "т", "ж": "ш", "з": "с", "щ": "ш",
})
_PHON_DROP = str.maketrans("", "", "ьъ")


def plain(s: str) -> str:
    """Нижний регистр, ё→е, только буквы а-я/a-z и цифры."""
    return _NOT_ALNUM.sub("", (s or "").lower().replace("ё", "е"))


def phon(s: str) -> str:
    """Фонетический ключ от plain(s): о→а, е/э/я/ы/й→и, б→п, в→ф и т.д., повторы схлопнуты."""
    out: List[str] = []
    for ch in plain(s).translate(_PHON_MAP).translate(_PHON_DROP):
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


@dataclass(frozen=True)
class LexForm:
    term: str      # каноническое написание
    form: str      # написание варианта (может совпадать с term)
    plain: str
    key: str       # phon
    n_tokens: int  # слов (через пробел) в form
    fuzzy: bool    # искать нечётко; False — только как подсказка


def _is_fuzzy(form: str, form_plain: str) -> bool:
    if len(form_plain) < MIN_FUZZY_LEN:
        return False
    # Аббревиатура (ЛСР, КС-2): целиком из заглавных/цифр.
    return any(c.islower() for c in form)


class Lexicon:
    def __init__(self, forms: List[LexForm]):
        self.forms = forms

    @classmethod
    def from_entries(cls, entries: Iterable[Tuple[str, Iterable[str], str]]) -> "Lexicon":
        """entries: (термин, варианты, источник). Дубли форм отсекаются по plain."""
        seen: Dict[str, LexForm] = {}
        for term, aliases, _source in entries:
            term = (term or "").strip()
            if not term:
                continue
            for form in [term, *aliases]:
                form = (form or "").strip()
                p = plain(form)
                if not p or p in seen:
                    continue
                seen[p] = LexForm(
                    term=term, form=form, plain=p, key=phon(form),
                    n_tokens=len(form.split()), fuzzy=_is_fuzzy(form, p),
                )
        return cls(list(seen.values()))

    @property
    def version(self) -> str:
        """Короткий отпечаток словаря: по нему видно, каким словарём правили."""
        raw = "\n".join(sorted(f.plain for f in self.forms))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    @property
    def fuzzy_forms(self) -> List[LexForm]:
        return [f for f in self.forms if f.fuzzy]

    def terms(self) -> List[str]:
        return list(dict.fromkeys(f.term for f in self.forms))


def parse_lexicon_text(text: str) -> List[Tuple[str, List[str], str]]:
    """Разобрать текст словаря: «термин» или «термин = вариант1; вариант2»."""
    entries: List[Tuple[str, List[str], str]] = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        term, _, rest = line.partition("=")
        term = term.strip()
        if not term:
            continue
        aliases = [a.strip() for a in rest.split(";") if a.strip()]
        entries.append((term, aliases, "base"))
    return entries


def load_base_lexicon_entries() -> List[Tuple[str, List[str], str]]:
    return parse_lexicon_text(BASE_LEXICON_PATH.read_text(encoding="utf-8"))
