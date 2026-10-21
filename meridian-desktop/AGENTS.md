# AGENTS.md

This file provides guidance to AI coding assistants working with code in this repository.

## Development Commands

**Prerequisites:**

- [Rust](https://rustup.rs/) (latest stable)
- [Bun](https://bun.sh/) package manager

**Core Development:**

```bash
# Install dependencies
bun install

# Run in development mode
bun run tauri dev
# If cmake error on macOS:
CMAKE_POLICY_VERSION_MINIMUM=3.5 bun run tauri dev

# Build for production
bun run tauri build

# Frontend only development
bun run dev        # Start Vite dev server
bun run build      # Build frontend (TypeScript + Vite)
bun run preview    # Preview built frontend
```

**Linting and Formatting (run before committing):**

```bash
bun run lint              # ESLint for frontend
bun run lint:fix          # ESLint with auto-fix
bun run format            # Prettier + cargo fmt
bun run format:check      # Check formatting without changes
bun run format:frontend   # Prettier only
bun run format:backend    # cargo fmt only
```

**Model Setup (Required for Development):**

```bash
mkdir -p src-tauri/resources/models
curl -L -o src-tauri/resources/models/silero-vad-v6.2-F32.gguf https://huggingface.co/handy-computer/silero-vad-v6.2-gguf/resolve/main/silero-vad-v6.2-F32.gguf
```

For detailed platform-specific build setup, see [BUILD.md](BUILD.md).

## Architecture Overview

Meridian Desktop is a cross-platform desktop application for recording and offline recognition of meetings, built with Tauri 2.x (Rust backend + React/TypeScript frontend). It is a fork of Handy/HandyRU (MIT) with the dictation features (global shortcuts, pasting into other apps, overlay, autostart, updater) removed. Recording is started and stopped from the UI.

### Backend Structure (src-tauri/src/)

- `lib.rs` - Main entry point, Tauri setup, manager initialization
- `managers/` - Core business logic:
  - `audio.rs` - Audio recording and device management
  - `model.rs` - Model downloading and management
  - `transcription.rs` - Speech-to-text processing pipeline
  - `history.rs` - Transcription history storage
- `audio_toolkit/` - Low-level audio processing:
  - `audio/` - Recording sink (VAD, levels, live streaming feed), output devices, WAV I/O
  - `vad/` - Voice Activity Detection (Silero VAD)
- `commands/` - Tauri command handlers for frontend communication
- `commands/recording.rs` - `start_recording` / `stop_recording` commands (stop returns the recognized text)
- `recording.rs` - Recording session state and the record → recognize → history pipeline
- `commands/settings.rs` - Commands that change individual settings
- `cli.rs` - CLI argument definitions (clap derive)
- `settings.rs` - Application settings management
- `tray.rs` - System tray icon and menu
- `utils.rs` - Cancellation, mic-level events, small helpers

### Frontend Structure (src/)

- `App.tsx` - Main component with onboarding flow
- `components/` - React UI components:
  - `settings/` - Settings UI
  - `model-selector/` - Model management interface
  - `onboarding/` - First-run experience
  - `shared/`, `ui/`, `icons/`, `footer/` - Shared components
- `hooks/useSettings.ts` - Settings state management hook
- `stores/settingsStore.ts` - Zustand store for settings
- `bindings.ts` - Auto-generated Tauri type bindings (via tauri-specta)
- `lib/types.ts` - Shared TypeScript type definitions

### Key Architecture Patterns

**Manager Pattern:** Core functionality organized into managers (Audio, Model, Transcription) initialized at startup and managed via Tauri state.

**Command-Event Architecture:** Frontend → Backend via Tauri commands; Backend → Frontend via events.

**Pipeline Processing:** Audio → VAD → GigaAM (transcribe.cpp) → Text (returned by `stop_recording`, saved to history)

**State Flow:** Zustand → Tauri Command → Rust State → Persistence (tauri-plugin-store)

### Technology Stack

**Core Libraries:**

- `transcribe-cpp` - Local speech recognition (Whisper, Parakeet, Moonshine, SenseVoice, etc.; GGML/GGUF) with GPU acceleration
- `handy-recorder` - Microphone capture: device selection, resampling to 16 kHz, failure detection
- `transcribe-cpp` (Silero VAD v6, CPU-only, in-process) / `earshot` - Voice Activity Detection
- `rodio` - Output device enumeration (audio_toolkit)

### Application Flow

1. **Initialization:** App loads settings, initializes managers, shows the main window (tray icon available)
2. **Model Setup:** First run offers the GigaAM v3 E2E models (CTC is the default)
3. **Recording:** UI calls `start_recording`; audio is captured with VAD filtering
4. **Processing:** UI calls `stop_recording`; audio is recognized by the model
5. **Output:** The text is returned to the UI and saved to history

### Settings System

Settings are stored using Tauri's store plugin with reactive updates:

- Audio devices (microphone selection)
- Model preferences (GigaAM v3 E2E CTC / RNN-T)
- Post-processing (LLM) and translation options

### Single Instance Architecture

The app enforces single instance behavior — launching when already running brings the main window to front rather than creating a new process (`tauri_plugin_single_instance`).

## Internationalization (i18n)

All user-facing strings must use i18next translations. ESLint enforces this (no hardcoded strings in JSX).

**Adding new text:**

1. Add key to `src/i18n/locales/en/translation.json`
2. Use in component: `const { t } = useTranslation(); t('key.path')`

**File structure:**

```
src/i18n/
├── index.ts           # i18n setup
├── languages.ts       # Language metadata
└── locales/
    ├── en/translation.json  # English (source)
    └── ru/translation.json  # Russian (default language)
```

Only `ru` (default) and `en` locales are kept; `bun run check:translations` checks `ru` against `en`.

## Code Style

**Rust:**

- Run `cargo fmt` and `cargo clippy` before committing
- Handle errors explicitly (avoid unwrap in production)
- Use descriptive names, add doc comments for public APIs

**TypeScript/React:**

- Strict TypeScript, avoid `any` types
- Functional components with hooks
- Tailwind CSS for styling
- Path aliases: `@/` → `./src/`

## CLI Parameters

**Implementation:** `cli.rs` (definitions), `main.rs` (parsing), `lib.rs` (applying)

| Flag             | Description                                                |
| ---------------- | ---------------------------------------------------------- |
| `--start-hidden` | Launch without showing the main window (tray icon visible) |
| `--no-tray`      | Launch without system tray (closing window quits the app)  |
| `--debug`        | Enable debug mode with verbose (Trace) logging             |

Headless flags (`--transcribe-file`, `--model`, `--list-models`, `--list-devices`, `--json`) transcribe a 16 kHz mono WAV or list models/devices without opening the UI. The `--transcribe-worker` flag is the internal engine worker process and must be kept.

CLI flags are runtime-only overrides — they do NOT modify persisted settings.

## Debug Mode

Access debug features: `Cmd+Shift+D` (macOS) or `Ctrl+Shift+D` (Windows/Linux)

## Platform Notes

- **macOS**: Metal acceleration, microphone permission required
- **Windows**: Vulkan acceleration, code signing. Implicit Vulkan layers (overlays, capture hooks) are disabled for the Meridian process via `VK_LOADER_LAYERS_DISABLE=~implicit~` set in `main.rs`; opt out with `HANDY_KEEP_VULKAN_IMPLICIT_LAYERS=1` or by setting `VK_LOADER_LAYERS_DISABLE` yourself
- **Linux**: OpenBLAS + Vulkan

## Troubleshooting

See `docs/troubleshooting/`.

## Commits

Use conventional commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`). Focus the message on _why_, not _what_.
