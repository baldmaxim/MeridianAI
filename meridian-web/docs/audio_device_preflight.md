# Audio Device Preflight + Capture Route Metadata (Stage 15)

Практический audio-слой: выбор input-устройства в браузере, sound-check (уровень/тишина/клиппинг/
sample rate/каналы), route-пресеты (speakerphone / USB-рекордер / room mic) и безопасная
`audio_capture_metadata` в backend. **Не** реализует full multichannel PCM-протокол и **не** выводит
сторону переговоров из устройства.

## Что добавляет Stage 15

- **Frontend:** `AudioPreflightPanel` рядом с кнопкой записи (не блокирует старт), хуки
  `useAudioInputDevices` (список/выбор/persist), `useAudioSoundCheck` (локальная проверка),
  расширенный `useAudioRecorder` (опциональный device/route), отправка safe metadata по WS.
- **Backend:** модель `AudioCaptureMetadata` (`app/core/context/audio_capture_metadata.py`),
  `SessionManager.set_audio_capture_metadata` / `get_audio_capture_metadata`, WS-сообщение
  `audio_capture_metadata`, safe-поля в `SIGNAL_ENGINE_TRACE` + сводка `audio_capture` в анализаторе.

## Рекомендуемые маршруты (route)

| route | когда |
|---|---|
| `speakerphone_usb` | портативный конференц-спикерфон (Jabra/Poly/Anker) |
| `usb_recorder` / `usb_room_mic` | USB-рекордер типа Zoom H2n, поставить по центру стола |
| `external_audio_interface` | внешняя аудиокарта/микшер |
| `laptop_mic` / `browser_default` | fallback (встроенный/дефолтный микрофон) |
| `phone_secondary` | запасной/secondary сценарий, **не** основной микрофон |

> route — это **техническая зона записи**, не сторона и не AI-профиль. Панель не выбирает триггеры/
> профили. USB-рекордер/спикерфон — маршруты записи, не идентичность говорящего.

## Интерпретация sound-check

- **Слишком тихо** (`too_quiet`): RMS ниже порога дольше ~1.5 с — поднять усиление/придвинуть микрофон.
- **Перегруз / клиппинг** (`clipping`): пик ≥ 0.98 — отодвинуть микрофон/снизить gain.
- **ОК** (`ok`): уровень в норме.
- **mono vs stereo**: «Каналов: 1/2» — что отдаёт браузер. Даже при стерео-устройстве стрим в
  обработку остаётся mono (см. ограничение ниже).

## Важное ограничение

Stage 15 **не** реализует multichannel streaming. Бинарный аудио-протокол не меняется: стрим в
backend остаётся **mono 16 кГц** (AudioContext ресемплит). Если Zoom H2n рапортует stereo, но
`capture_pipeline = stereo_requested_mono_stream`/`mono_stream` — backend всё равно получает текущий
mono STT-стрим. Channel-aware capture/протокол — задача **Stage 16**.

## Что отправляется в backend (и что нет)

Frontend шлёт JSON-control `{"type":"audio_capture_metadata","payload":{…}}` **один раз на старт**:
- `route`, `capturePipeline`, requested/actual `channelCount`/`sampleRate`,
  `echoCancellation`/`noiseSuppression`/`autoGainControl`, `deviceLabelHash`, `deviceIdHash`,
  короткое `browser` (не полный UA).

**Не отправляется:** raw device label, raw device id, transcript text, speaker labels. Label/id
хэшируются на клиенте (sha256[:16]); raw остаётся локально (показывается только в UI). Если бы сырьё
всё же пришло — backend хэширует и отбрасывает raw (`parse_audio_capture_metadata`).

## Privacy / Safety

- raw device labels/ids остаются на клиенте; backend хранит только route/counts/hashes;
- `route`/`source_kind` **никогда** не задают `speaker_side`; сторона — только через
  `speaker_identity_hints` поверх stable link;
- `set_audio_capture_metadata` — диагностика: **не** создаёт source attribution, **не** трогает
  `speaker_identity_hints`, **не** влияет на reconciliation, **не** вызывает `set_speaker_audio_metadata`;
- логи — только агрегаты (`[AudioCapture] route=… pipeline=… actual_channels=…`), без raw label/id;
- старое поведение без выбора устройства остаётся рабочим (legacy mono 16k constraints).

## Stage 16: channel-aware v2 shadow

Stage 15 честно оставил pipeline mono. Stage 16 добавляет **opt-in** multichannel v2 shadow-стрим
(MAUD2) — отдельную диагностическую ветку; legacy mono 16k остаётся единственным live STT input. См.
[channel_aware_capture_v2.md](channel_aware_capture_v2.md).

- Если `capture_pipeline = mono_stream` / `stereo_requested_mono_stream` → v2 **не активен**, в trace
  `audio_multichannel_frame_count` пуст.
- Если включён experimental shadow и трек отдаёт ≥2 каналов → frontend шлёт MAUD2 frames, и trace
  показывает `audio_multichannel_*` (`max_channels_seen`, `frame_count`, parse/gap счётчики).

## Как это помогает canary

`SIGNAL_ENGINE_TRACE` получает safe-поля: `audio_capture_route`, `audio_capture_pipeline`,
`audio_capture_actual_channel_count`, `audio_capture_actual_sample_rate`, `audio_capture_source_kind`,
`audio_capture_source_is_isolated`. Анализатор (`signal_trace_analysis`) даёт сводку `audio_capture`
(`by_route`/`by_pipeline`/`by_source_kind`/перцентили) и заметки:
- «audio route в основном laptop/default mic — рассмотреть USB speakerphone/recorder»;
- «USB recorder/room mic выбран, но pipeline mono_stream — multichannel не активен (Этап 16)».

Это позволяет коррелировать плохой `unknown_side_event_rate` с плохим audio-маршрутом перед active
source-reconcile canary.

## Команды проверки

```bash
# backend
cd meridian-web/backend
../.venv/Scripts/python.exe -m pytest tests/test_audio_capture_metadata.py tests/test_session_manager_audio_metadata.py tests/test_signal_trace.py tests/test_signal_trace_analysis.py -q
# frontend
cd meridian-web/frontend
npm run build   # tsc -b && vite build
```
