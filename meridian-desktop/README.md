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
