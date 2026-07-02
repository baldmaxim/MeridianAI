# Audio / Channel → Speaker Identity wiring (Stage 6)

Делает так, чтобы hidden hints `speaker_identity_hints.audio_sources` / `channel_labels`
([speaker_identity_hints.md](speaker_identity_hints.md)) реально применялись — но ТОЛЬКО при
наличии явной structured-связи `speaker label → audio source id / channel label`.

## Зачем

`audio_sources`/`channel_labels` hints задают сторону «зоны записи» (канал/источник):
`primary = наша сторона`, `secondary = контрагент`, `left/right` и т.п. Но сам по себе
«primary» — это не сторона и не личность. Нужна связь, какой speaker label соответствует
какому источнику/каналу. Без этой связи hint inert (как на Stage 5).

## Stage 5 vs Stage 6

- **Stage 5:** `audio_sources`/`channel_labels` hints были inert — не применялись без metadata.
- **Stage 6:** добавлен слой `speaker_audio_links` (нормализация metadata разных форматов) и
  `apply_audio_channel_hints` — hint применяется к speaker через explicit link. confidence ≤ 0.85,
  source=`audio_channel`, evidence `audio_source_hint`/`channel_label_hint`.

## Форматы metadata (всё structured, без transcript text)

A. `{ "SM_0": "primary", "SM_1": "secondary" }` — label → source id.

B. `{ "SM_0": {"audio_source_id": "primary", "channel_label": "left", "confidence": 0.8} }`.

C. контейнеры:
```json
{
  "speaker_sources":  {"SM_0": "primary"},
  "speaker_channels": {"SM_0": "left"},
  "source_by_speaker":{"SM_0": "primary"},
  "channel_by_speaker":{"SM_0": "left"},
  "speaker_audio_links": [ {"speaker_label": "SM_0", "audio_source_id": "primary"} ]
}
```

D. список: `[ {"speaker_label": "SM_0", "audio_source_id": "primary", "channel_label": "left"} ]`.

E. объект с атрибутами `speaker_label/speaker/label`, `audio_source_id/source_id/source`,
   `channel_label/channel`, `device_role`, `route`, `confidence`.

## Hints + metadata вместе

Snapshot встречи:
```json
{ "speaker_identity_hints": { "audio_sources": {
    "primary":   {"side": "our_side",     "confidence": 0.75, "source": "audio_channel"},
    "secondary": {"side": "counterparty", "confidence": 0.75, "source": "audio_channel"} } } }
```
Runtime metadata (link): `{ "speaker_sources": { "SM_0": "primary", "SM_1": "secondary" } }`.

Результат графа: `SM_0 → our_side` (audio_channel, conf ≤0.85), `SM_1 → counterparty`.

## Конфликты audio_source vs channel_label

Если у спикера есть и source-hint, и channel-hint с РАЗНЫМИ сторонами:
- разница confidence ≥ 0.15 → берём более уверенный, confidence −0.1, evidence + `conflicting_audio_channel_hints`;
- разница близкая → `side=unknown`, confidence = max−0.2, evidence `conflicting_audio_channel_hints`.

## Ограничения

- `primary`/`secondary` сами по себе НЕ сторона; `desktop`/`phone` сами по себе НЕ сторона.
- source/channel hint — это зона записи, не доказанная личность.
- Без explicit link hint НЕ применяется (старое поведение сохраняется).
- `manual_correction` (подтверждённые роли) и `speaker_labels`/`stable_ids` hints сильнее audio/channel.
- Нет UI, нет БД-миграций, нет LLM role inference.
- Связь `speaker_label → source/channel` в live-сессии пока не заполняется автоматически
  (см. TODO в `SessionManager._collect_speaker_audio_metadata`); задаётся `set_speaker_audio_metadata()`.

## Что смотреть в trace

В `SIGNAL_ENGINE_TRACE` (только агрегаты):
`speaker_audio_linked_count`, `speaker_channel_linked_count`,
`speaker_audio_link_average_confidence`, `speaker_audio_link_sources`.

В `signal_trace_analysis` → `speaker_context`: `audio_linked_event_rate`, `audio_linked_count_p50`,
`channel_linked_count_p50`, `audio_link_confidence_p50`, `by_audio_link_source` — вместе с
`unknown_side_event_rate` и `hint_source_event_rate`. Notes подскажут, когда links есть, но hints
их не покрывают, или когда уверенность links низкая.
