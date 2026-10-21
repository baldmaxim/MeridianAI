# Meridian Desktop

Десктоп-приложение «Meridian» для записи и офлайн-распознавания встреч.
Распознавание идёт локально на модели GigaAM v3 (transcribe.cpp, GGUF), без отправки аудио в облако.

Происхождение: форк [Handy](https://github.com/cjpais/Handy) / HandyRU (лицензия MIT, см. `LICENSE`).
Стек: Tauri 2 (Rust) + React 18 + TypeScript. Диктовка в другие приложения вырезана, запись управляется из UI.

## Команды

```bash
bun install                # зависимости
bun run tauri dev          # запуск в режиме разработки
bun run tauri build        # сборка установщика
bun run lint               # ESLint
cd src-tauri && cargo test --lib   # тесты Rust
```

Перед первым запуском нужна модель VAD: см. `AGENTS.md`. Подробности сборки по платформам: `BUILD.md`.

## Автообновление

Приложение при запуске молча проверяет `https://meridianai.ru/desktop/latest.json` и, если версия
новее, предлагает «Обновить сейчас / Позже»; ставит и перезапускается только по согласию.
Кнопка «Проверить обновления» — в «О программе». Релиз GitHub нужно **опубликовать** (не draft),
иначе `/releases/latest/download/latest.json` недоступен. Подробности: `BUILD.md`.

## Секреты

Токен устройства и API-ключи LLM хранятся в хранилище ОС (Windows Credential Manager,
macOS Keychain, Linux Secret Service), сервис `ru.meridianai.desktop`. Если хранилище недоступно,
секрет остаётся в файле настроек/`account.json` (0600 на unix) с предупреждением в логе.
