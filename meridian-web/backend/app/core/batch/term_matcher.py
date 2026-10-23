"""Поиск в распознанном тексте кусков, похожих на словарные термины.

Код только предлагает кандидатов; решает, правда ли тут сказан термин, LLM
(term_corrector). Сравнение идёт по фонетическим ключам (term_lexicon.phon).
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .term_lexicon import LexForm, Lexicon, phon, plain

# Окно короче формы не больше чем на столько знаков ключа (слово оборвано) и длиннее
# не больше чем на столько (окончание, «лишние» слова).
KEY_SHORTER_BY = 2
KEY_LONGER_BY = 4
# «Уже верное»: после стема формы в окне допустимо не больше букв (окончание).
MAX_ENDING = 3
# Окно из нескольких слов: в каждом слове не меньше стольких букв.
MIN_GLUED_LETTERS = 3
# Порог похожести окна на форму; 0.7 подобран на стенде (23.10.2026, 6×10 мин).
DEFAULT_THRESHOLD = 0.7

_VOWELS = set("аеёиоуыэюяйь")
_TAIL_PUNCT = re.compile(r"[^\w]+$")
_EPS = 1e-9


def levenshtein(a: str, b: str, max_dist: Optional[int] = None) -> int:
    """Расстояние Левенштейна; при превышении max_dist возвращает max_dist + 1."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    la, lb = len(a), len(b)
    if max_dist is not None and la - lb > max_dist:
        return max_dist + 1
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        ca = a[i - 1]
        cur = [i] + [0] * lb
        row_min = i
        for j in range(1, lb + 1):
            v = prev[j - 1] + (ca != b[j - 1])
            w = prev[j] + 1
            if w < v:
                v = w
            w = cur[j - 1] + 1
            if w < v:
                v = w
            cur[j] = v
            if v < row_min:
                row_min = v
        if max_dist is not None and row_min > max_dist:
            return max_dist + 1
        prev = cur
    d = prev[lb]
    if max_dist is not None and d > max_dist:
        return max_dist + 1
    return d


@dataclass
class Candidate:
    id: int
    seg: int    # индекс реплики
    w0: int     # слова transcription["words"][w0:w1]
    w1: int
    text: str   # исходные слова через пробел, без хвостовой пунктуации последнего
    term: str
    form: str
    score: float


def split_tail_punct(word: str) -> Tuple[str, str]:
    """«сайт,» → («сайт», «,»)."""
    m = _TAIL_PUNCT.search(word)
    if not m:
        return word, ""
    return word[:m.start()], m.group(0)


def reply_ranges(words: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    """Реплики как диапазоны слов [s, e): подряд идущие слова одного говорящего."""
    ranges: List[Tuple[int, int]] = []
    start = 0
    prev: Any = None
    for i, w in enumerate(words):
        speaker = w.get("speaker_id", w.get("speaker"))
        if i > 0 and speaker != prev:
            ranges.append((start, i))
            start = i
        prev = speaker
    if words:
        ranges.append((start, len(words)))
    return ranges


def _stem(form_plain: str) -> str:
    return form_plain[:-1] if form_plain[-1] in _VOWELS else form_plain


def _already_right(window_plain: str, form: LexForm, anchored: bool = False) -> bool:
    """Окно уже содержит словарную форму (с любым окончанием), возможно после лишнего слова.

    anchored — форма должна стоять в начале окна (окно само и есть этот термин).
    """
    stem = _stem(form.plain)
    variants = [stem]
    if len(stem) >= 4 and stem[-1] not in _VOWELS:
        # Беглая гласная: кладовка → кладовок, перегородка → перегородок.
        variants += [stem[:-1] + v + stem[-1] for v in "ое"]
    for v in variants:
        if anchored:
            at = 0 if window_plain.startswith(v) else -1
        else:
            at = window_plain.find(v)
        if at >= 0 and len(window_plain) - at - len(v) <= MAX_ENDING:
            return True
    return False


def _max_dist(length: int, threshold: float) -> int:
    return int(length * (1 - threshold) + _EPS)


class _FormIndex:
    """Индекс нечётких форм по биграммам ключа, чтобы не сравнивать окно со всеми формами.

    k правок портят не больше 2k биграмм формы, поэтому подходящее окно содержит почти все
    биграммы начала ключа формы (первые L-2 знака — они сравниваются всегда).
    """

    def __init__(self, forms: List[LexForm], threshold: float):
        self.threshold = threshold
        self.forms = forms
        self.maxd = [_max_dist(len(f.key), threshold) for f in forms]
        self.postings: Dict[str, List[int]] = {}
        self.required: List[int] = []
        self.always: List[int] = []   # формы, для которых биграммный фильтр бесполезен
        for n, f in enumerate(forms):
            head = f.key[:len(f.key) - KEY_SHORTER_BY]
            grams = {head[i:i + 2] for i in range(len(head) - 1)}
            need = len(grams) - 2 * self.maxd[n]
            self.required.append(need)
            if need <= 0:
                self.always.append(n)
                continue
            for g in grams:
                self.postings.setdefault(g, []).append(n)
        lengths = [len(f.key) for f in forms]
        self.min_len = min(lengths) - KEY_SHORTER_BY
        self.max_len = max(lengths) + KEY_LONGER_BY

    def possible(self, wkey: str) -> List[int]:
        counts: Dict[int, int] = {}
        for g in {wkey[i:i + 2] for i in range(len(wkey) - 1)}:
            for n in self.postings.get(g, ()):
                counts[n] = counts.get(n, 0) + 1
        found = [n for n, c in counts.items() if c >= self.required[n]]
        found.extend(self.always)
        return found


def _best_form(wplain: str, prev_len: int, index: _FormIndex) -> Optional[Tuple[LexForm, float]]:
    """prev_len — длина ключа окна без последнего слова (0 для одного слова)."""
    wkey = phon(wplain)
    m = len(wkey)
    if m < index.min_len or m > index.max_len:
        return None
    possible = index.possible(wkey)
    # Окно уже само словарное («чистовая отделка») — не выдаём его за искажение соседнего термина
    # («черновая отделка»). Точная форма всегда среди possible: у неё есть все биграммы.
    if any(_already_right(wplain, index.forms[n], anchored=True) for n in possible):
        return None
    best: Optional[Tuple[LexForm, float, int]] = None
    for n in possible:
        form = index.forms[n]
        length = len(form.key)
        if m < length - KEY_SHORTER_BY or m > length + KEY_LONGER_BY:
            continue
        if prev_len >= length - KEY_SHORTER_BY:
            continue  # без последнего слова окно уже годилось — слово лишнее
        maxd = index.maxd[n]
        if m >= length:
            d = levenshtein(wkey[:length], form.key, maxd)
        else:
            # Слово оборвано («кладов»): сравниваем с началом ключа, обрыв стоит штрафной 1.
            d = levenshtein(wkey, form.key[:m], maxd - 1) + 1 if maxd >= 1 else maxd + 1
        if d > maxd:
            continue
        score = 1 - d / length
        if score + _EPS < index.threshold or _already_right(wplain, form):
            continue
        # Порядок в словаре решает при равных оценках.
        if best is None or score > best[1] + _EPS or (abs(score - best[1]) <= _EPS and n < best[2]):
            best = (form, score, n)
    return (best[0], best[1]) if best else None


def find_candidates(words: List[Dict[str, Any]], lexicon: Lexicon,
                    threshold: float = DEFAULT_THRESHOLD, max_window: int = 3) -> List[Candidate]:
    """Окна из 1..max_window слов внутри одной реплики, похожие на нечёткие формы словаря."""
    forms = [f for f in lexicon.fuzzy_forms if f.key]
    if not forms or not words:
        return []
    index = _FormIndex(forms, threshold)

    plains = [plain(split_tail_punct(w.get("text", ""))[0]) for w in words]
    cache: Dict[Tuple[str, int], Optional[Tuple[LexForm, float]]] = {}
    found: List[Candidate] = []

    for seg, (s, e) in enumerate(reply_ranges(words)):
        for i in range(s, e):
            wplain = ""
            prev_len = 0
            for j in range(i, min(i + max_window, e)):
                p = plains[j]
                if not p or any(c.isdigit() for c in p):
                    break  # пустое слово (тире) или число окно не продолжают
                if j > i and min(len(p), len(plains[i])) < MIN_GLUED_LETTERS:
                    break  # «три на» → «дренаж», «вот он» → «воронка»: короткие слова не склеиваем
                prev_len = len(phon(wplain)) if wplain else 0
                wplain += p
                ckey = (wplain, prev_len)
                if ckey not in cache:
                    cache[ckey] = _best_form(wplain, prev_len, index)
                hit = cache[ckey]
                if hit is None:
                    continue
                form, score = hit
                texts = [w.get("text", "") for w in words[i:j + 1]]
                texts[-1] = split_tail_punct(texts[-1])[0]
                found.append(Candidate(
                    id=0, seg=seg, w0=i, w1=j + 1, text=" ".join(texts),
                    term=form.term, form=form.form, score=score,
                ))

    # Перекрытия: из пересекающихся окон остаётся лучшее (при равенстве — длиннее).
    found.sort(key=lambda c: (-c.score, -(c.w1 - c.w0), c.w0))
    taken = [False] * len(words)
    kept: List[Candidate] = []
    for c in found:
        if any(taken[c.w0:c.w1]):
            continue
        for k in range(c.w0, c.w1):
            taken[k] = True
        kept.append(c)
    kept.sort(key=lambda c: c.w0)
    for n, c in enumerate(kept):
        c.id = n
    return kept
