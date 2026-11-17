# Сборка Meridian Desktop

## Требования

Для всех платформ: [Rust](https://rustup.rs/) (stable), [Bun](https://bun.sh/),
[зависимости Tauri](https://tauri.app/start/prerequisites/).

- **macOS:** Xcode Command Line Tools (`xcode-select --install`). Звук компьютера на встречах записывается
  через Core Audio tap и работает с macOS 14.6.
- **Windows:** Visual Studio Build Tools с C++, [CMake](https://cmake.org/download/) в `PATH`
  (`winget install Kitware.CMake`), [Vulkan SDK](https://vulkan.lunarg.com/sdk/home) для сборки GPU-бэкенда
  (`winget install KhronosGroup.VulkanSDK`; после установки откройте новый терминал, чтобы появился `VULKAN_SDK`).
- **Linux (Ubuntu/Debian):**

  ```bash
  sudo apt update
  sudo apt install build-essential clang libclang-dev libasound2-dev pkg-config libssl-dev libvulkan-dev vulkan-tools glslc spirv-headers glslang-tools libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev patchelf cmake
  ```

## Разработка и сборка

```bash
bun install
mkdir -p src-tauri/resources/models
curl -L -o src-tauri/resources/models/silero-vad-v6.2-F32.gguf https://huggingface.co/handy-computer/silero-vad-v6.2-gguf/resolve/main/silero-vad-v6.2-F32.gguf
bun run tauri dev      # запуск в режиме разработки
bun run tauri build    # установщики: deb/rpm/AppImage (Linux), dmg (macOS), nsis (Windows)
```

На macOS при ошибке cmake: `CMAKE_POLICY_VERSION_MINIMUM=3.5 bun run tauri dev`.

## Подпись артефактов обновления

`bundle.createUpdaterArtifacts: true` в `tauri.conf.json`: `tauri build` подписывает артефакты
minisign-ключом и без него падает. Для локальной сборки:

```bash
# либо задать ключ (приватный ключ хранится вне репозитория)
export TAURI_SIGNING_PRIVATE_KEY_PATH=~/.tauri/meridian-desktop.key
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=...
# либо отключить артефакты обновления
bun run tauri build --config '{"bundle":{"createUpdaterArtifacts":false}}'
```

Публичный ключ — `plugins.updater.pubkey`, endpoint — `https://meridianai.ru/desktop/latest.json`
(nginx перенаправляет на ассет последнего релиза GitHub).

## Выпуск версии

Поднять `version` в `tauri.conf.json`, `Cargo.toml` (и `Cargo.lock`), `package.json`, затем:

```bash
git tag desktop-vX.Y.Z && git push origin desktop-vX.Y.Z
```

Workflow `desktop-build.yml` соберёт установщики, подписанные `.sig` и `latest.json` и создаст **черновик** релиза.

> [!IMPORTANT]
> Релиз нужно **опубликовать** (убрать draft). Пока он черновик, ссылка
> `/releases/latest/download/latest.json` не отдаёт файл и автообновление не находит новую версию.

## Linux: запуск собранного бинарника

Голый бинарник `src-tauri/target/release/meridian-desktop` без ресурсов Tauri (иконки, модель VAD)
и библиотек распознавания не запустится. Ставьте из deb-пакета
(`src-tauri/target/release/bundle/deb/`): библиотеки лежат в `/usr/lib/Meridian/` и подключаются через rpath.

## Типичные проблемы

- **AppImage не собирается на Arch и других rolling-дистрибутивах:** `linuxdeploy` приносит старый `strip`.
  Остальные пакеты собираются, AppImage можно пропустить: `bun run tauri build -- --bundles deb`.
- **Windows, ошибки `MSB3491` / `FTK1011` / `MSB6003`:** превышен лимит пути 260 символов. Сборка
  `transcribe-cpp` обходит его через короткий junction в `%LOCALAPPDATA%\tcs`; если junction создать не
  удалось, задайте короткий каталог сборки: `$env:CARGO_TARGET_DIR = "C:\h"` и откройте новый терминал.
