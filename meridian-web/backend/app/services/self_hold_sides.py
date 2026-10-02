"""Калибровка сторон кнопкой «держу — говорим мы» (очная встреча, один микрофон).

Пока говорит наша сторона, человек держит кнопку; отпускает — говорят они. Интервалы
удержания сопоставляются с интервалом речи committed-сегмента, и голос «мы»/«не мы» по
метке спикера уходит в общий OnlineCaptureSideVoter. Когда по метке набралось достаточно
согласных голосов, сторона закрепляется за меткой — дальше кнопку держать не нужно.

«Отпущено = не мы» действует только в окне калибровки (пока человек пользуется кнопкой):
через минуту после последнего нажатия/отпускания реплики без удержания ни о чём не говорят.

Чистый модуль: без БД, без IO, без часов — всё время приходит аргументами (epoch ms сервера).
"""

from dataclasses import dataclass, field

# Человек нажимает с опозданием и отпускает чуть раньше/позже конца фразы.
HOLD_LEAD_MS = 500
HOLD_TAIL_MS = 500
# Доля речи под удержанием: от SELF_MIN — «мы», до OPPONENT_MAX — «не мы», между — смешанная.
SELF_MIN_OVERLAP = 0.5
OPPONENT_MAX_OVERLAP = 0.1
# Голос «не мы» слабее: прощает реплику коллеги, сказанную без кнопки.
OPPONENT_WEIGHT = 0.6
# Сколько после последнего события кнопки отпущенная кнопка ещё значит «не мы».
CALIBRATION_TAIL_MS = 60_000
# Потерянное «отпустил» (сокет был закрыт) не должно делать «нашей» всю встречу.
MAX_HOLD_MS = 120_000
# Интервалы старше этого не нужны: сегменты приходят с задержкой в секунды, не минуты.
KEEP_INTERVALS_MS = 15 * 60_000


@dataclass
class SelfHoldTracker:
    """Интервалы удержания кнопки по всем соединениям встречи (объединение)."""

    open_presses: dict[str, int] = field(default_factory=dict)
    intervals: list[tuple[int, int]] = field(default_factory=list)
    first_press_ms: int | None = None
    last_event_ms: int | None = None

    def press(self, conn_id: str, server_ms: int) -> None:
        # Повторное нажатие без отпускания — прошлое «отпустил» потерялось: закрываем его.
        self.release(conn_id, server_ms)
        self.open_presses[conn_id] = server_ms
        if self.first_press_ms is None:
            self.first_press_ms = server_ms
        self.last_event_ms = server_ms

    def release(self, conn_id: str, server_ms: int) -> None:
        start = self.open_presses.pop(conn_id, None)
        if start is None:
            return
        self.intervals.append((start, min(max(start, server_ms), start + MAX_HOLD_MS)))
        self.last_event_ms = server_ms
        cutoff = server_ms - KEEP_INTERVALS_MS
        self.intervals = [iv for iv in self.intervals if iv[1] >= cutoff]

    def release_all(self, conn_id: str, server_ms: int) -> None:
        """Соединение ушло — зажатая кнопка не должна висеть вечно."""
        self.release(conn_id, server_ms)

    def reset(self) -> None:
        self.open_presses.clear()
        self.intervals.clear()
        self.first_press_ms = None
        self.last_event_ms = None

    def _held_ms(self, start_ms: int, end_ms: int) -> int:
        """Сколько мс из [start, end] покрыто удержанием (с поправками), без двойного счёта."""
        spans = [(s - HOLD_LEAD_MS, e + HOLD_TAIL_MS) for s, e in self.intervals]
        # Ещё зажатая кнопка — до конца реплики (сегмент мог закрыться раньше отпускания).
        spans += [(s - HOLD_LEAD_MS, min(end_ms, s + MAX_HOLD_MS)) for s in self.open_presses.values()]
        spans = sorted((max(s, start_ms), min(e, end_ms)) for s, e in spans)
        held, cur_s, cur_e = 0, None, None
        for s, e in spans:
            if e <= s:
                continue
            if cur_e is None or s > cur_e:
                if cur_e is not None:
                    held += cur_e - cur_s
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        if cur_e is not None:
            held += cur_e - cur_s
        return held

    def classify(self, speech_start_ms: int, speech_end_ms: int) -> tuple[str, float] | None:
        """(сторона, вес голоса) реплики или None — если кнопкой не пользовались/непонятно."""
        if self.first_press_ms is None or speech_end_ms <= speech_start_ms:
            return None
        overlap = self._held_ms(speech_start_ms, speech_end_ms) / (speech_end_ms - speech_start_ms)
        if overlap >= SELF_MIN_OVERLAP:
            return "self", overlap
        if overlap > OPPONENT_MAX_OVERLAP:
            return None  # смешанная реплика — не голосуем
        in_window = (speech_end_ms >= self.first_press_ms - HOLD_LEAD_MS
                     and (bool(self.open_presses)
                          or speech_start_ms <= (self.last_event_ms or 0) + CALIBRATION_TAIL_MS))
        return ("opponent", OPPONENT_WEIGHT) if in_window else None
