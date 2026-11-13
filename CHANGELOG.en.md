# Changelog

Format: `## [version] — date`. Each version lists what changed for users and, honestly, what was **not** verified. [Português](CHANGELOG.md)

## [0.2.0] — 2026-11-14

### Fixed
- **Models the library's stable-diffusion.cpp does not recognize** (e.g. FLUX.3 Image Klein: «get sd version from file failed» in the terminal and generation stuck). OpenFlow now **downloads the ready-made `sd-cli` by itself** (the newest stable-diffusion.cpp, no compiling) and generates through it with the same support files; before, you had to click a button on the node. Turn it off with `OPENFLOW_SD_CLI_AUTO=0`; if the download fails the node button still works.
- **Progress bar with junk on screen** (`########… 359/359 - 2.08GB/s[K`): sd-cli's terminal codes (like «erase line») were shown on the node. They are now stripped from every progress message, which reads «Step 359/359 · 2.08GB/s».
- In CI, the Python 3.9 tests on Linux run on `ubuntu-22.04` (current `ubuntu-latest` has no Python 3.9 in `setup-python`).

### New
- **Import project (.zip)** on the home screen: creates a new project from a `.zip` downloaded from OpenFlow (`POST /api/projects/import`). The file is treated as untrusted (only files listed by the project, with safe names and a size limit).

### Verified / not verified
- New automated tests for the automatic sd-cli download, the progress cleanup and the import (including a hostile `.zip`). **Not verified:** generation with the real FLUX.3 Klein (needs the model, hardware and the GitHub download of `sd-cli`, blocked here): the fix was validated with simulated sd-cli output.

## [0.1.0] — 2026-11-13

First release of **OpenFlow**: the Canvas mode of [ASTA](https://github.com/KMC1525/ASTA) became an app of its own, focused only on creative AI creation through node flows (ElevenLabs Flow style), with a simple, accessible interface.

### New
- **Home screen with all projects and a search bar.** OpenFlow opens on the list of every project (cards with thumbnail, nodes, files and date). The search (`/` focuses the field) looks into the **name, the description and the texts inside nodes** (prompts, lines, titles and style-folder names), ignoring accents and case; every word must appear; the card shows where it matched and highlights it. With no result, a button creates a project with the typed name. Sort by most recent, name, oldest or most files (remembered). Menu per card: open, rename, duplicate, download `.zip`, delete. API: `GET /api/projects?q=…&sort=…`.
- **Style Folder with folders and subfolders.** On the Style Folder node: **New folder**, **New subfolder** (up to 6 levels and 60 folders per node), **rename** (pencil button, double-click, `Enter`/`Esc`), names unique among sibling folders, **move files** between folders (*Move to…* button, drag and drop), upload straight into a folder, **turn a folder on/off** and delete. Folder names enter the style description; renaming or moving marks the nodes as outdated. Old projects open unchanged. API: `POST /api/projects/<id>/assets?node=…&folder=…`.
- **VAEs, text encoders and mmproj installed along with the model, automatically.** When you download a model (Models screen), OpenFlow also downloads: the **VAE** and **text encoders** (known families — FLUX.2/3, Qwen-Image, Z-Image, Wan 2.1/2.2 — or whatever the repository ships next to the model) and the **mmproj** of vision models (picks F16/BF16/Q8_0/F32 and saves it as `<model>.mmproj.gguf`). The screen shows **what will come along** and its size first; downloads resume and never repeat what exists; a failed support file never undoes the model. **Install what is missing** on the screen (or `flow models support`) repairs models you already had; deleting a model deletes its `mmproj`. Can be switched off (`hf.auto_support`). With the `local` library, a model with an `mmproj` is loaded with image input (best effort).
- **The `flow` command** on Linux, macOS and Windows: `flow` (opens), `flow setup`/`flow install`, `flow update`, `flow models list|install|support`, `flow libs`, `flow native`, `flow folder`, `flow doctor`, `flow version`.
- **Terminal installers**: `install.sh` (Linux and macOS) and `install.ps1` (Windows) install and update with the same command — Python (if missing), isolated environment, OpenFlow, optional libraries, pre-installed models (asking first) and the Rust core.
- **New, simple screens:** *Projects*, *Models* (recommended, Hugging Face search with every quantization, installed models with the state of their support files) and *Settings* (text AI, media, voice, projects, appearance, performance).
- **Accessibility:** real links and buttons, screen-reader labels, visible focus, keyboard-only use, light/dark/automatic theme, 90–150 % size, reduced motion; `Ctrl/⌘+K` palette, `Alt+N` (new project), `/` (search), `?` (shortcuts).

### Kept from ASTA's Canvas
- All the nodes (text, image, video, sound, voice, transcription, 30 utility nodes and the video Editor with MP4), `@` mentions, a model picker per node, **Generate flow with AI**, global styles, hash-based cache, model search in the editor, media providers (OpenAI, ElevenLabs, Google, Stability, Replicate, Hugging Face, Stable Diffusion WebUI, Hugging Face local, GGUF local, Demo).
- **Rust backend kept:** the `openflow_core` core (`openflow/native`) with a Python mirror of every function (`flow native setup` downloads the ready-made library and checks its SHA-256).

### Changed compared to ASTA
- Left out of OpenFlow (they stay in ASTA): chat, Game Engine, Scriber, Data, Avatars, Studio, Computer Use, Code, Work, Rebuild, the mobile app and graphical installers (`.exe`, `.pkg`, AppImage, APK). **Send to Studio** left together with the Studio.
- Data in `~/.openflow` (`OPENFLOW_HOME`); projects in `projects/<id>/project.json`; API under `/api/projects`; `OPENFLOW_*` variables.
- The Hugging Face model search now **reports the error** when no query reaches it (before it showed «nothing found»).
- **Fixed in the Rust core:** the triangle wave of the audio synthesis came out with the opposite sign compared with the Python mirror (`1−2·|2c−1|` instead of `2·|2c−1|−1`); ASTA's Rust ↔ Python equivalence test already failed with the core compiled. Both now match, with a new Rust test.

### Verified
- Linux, Python 3.13: the full Python suite (442 tests; with the Rust core compiled none is skipped, including the Rust ↔ Python equivalence tests), Chromium browser tests (projects and search, folders and subfolders, models and support files, editor, nodes, mentions, model picker, video), 14 Rust tests, the translation check, `install.sh` end to end against a local checkout and `flow doctor`/`flow version` of the result.

### Not verified (honesty)
- `install.ps1` on a real Windows machine and `install.sh` on macOS; the CI jobs for Linux/macOS/Windows are written but did not run. Rust core builds for macOS, Windows and ARM.
- Real downloads of VAEs, text encoders and `mmproj` from Hugging Face: tests simulate the downloads (file names of the curated and example repositories were checked against Hugging Face listings, but no large file was downloaded).
- Inference with real GGUF models and GPUs; image input through `mmproj` with a real model (it depends on the installed `llama-cpp-python` knowing the model's family); cloud providers with real keys.
- No performance measurements.
