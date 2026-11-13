<div align="center">

# OpenFlow

**Creative AI in node flows — images, videos, sounds and voices — in a simple, open, local-first app.**

Inspired by ElevenLabs Flow and much lighter than ComfyUI: connect a few nodes, see every result right on the node, and edit the final video without leaving the app. Runs on your computer, with models from companies (API) or fully local ones.

[Install](#install) · [The `flow` command](#the-flow-command) · [Projects](#projects--the-home-screen) · [Nodes](#the-nodes) · [Style Folder](#style-folder--folders-and-subfolders) · [Models](#models--support-files-install-themselves) · [Providers](#ai-providers) · [Rust core](#rust-core) · [Development](#development) · [Changelog](CHANGELOG.en.md) · [Português](README.pt-BR.md)

`MIT` · `Windows` · `macOS` · `Linux` · `Python 3.9+` · `Rust core` · `no required dependencies` · `v0.2.0`

</div>

---

## What it is

OpenFlow is the creative-flow side of [ASTA](https://github.com/KMC1525/ASTA) (its *Canvas* mode), turned into an app of its own that does **one thing**: creating with AI through a flow of connected nodes. It keeps ASTA's Python + Rust architecture and drops everything that is not about creating.

- 🗂️ **Starts on your projects.** The first screen lists **all your projects** with a **search bar** that looks into names, descriptions and the texts inside the nodes (accent- and case-insensitive).
- 🧩 **A simple node flow.** Every node has one output, typed inputs and a result you see on the node. Text, image, video, sound, voice, transcription, 30 utility nodes (they run on ffmpeg and Python — no model needed) and a built-in video **Editor** with MP4 export.
- 🎨 **Style for the whole project.** A *Style Prompt* and a *Style Folder* apply to every generator. The Style Folder now has **folders and subfolders, which you can rename**.
- 📦 **Models install with everything they need.** VAEs, text encoders and `mmproj` files are downloaded **automatically, together with the model**.
- 🦀 **Rust core** (std only, loaded through `ctypes`): audio synthesis, run order of the flow, local-model planning, memory release… with a pure-Python mirror of every function.
- ⌨️ **One command on every system: `flow`.** Install, update and run from the terminal on Linux, macOS and Windows.
- 🔒 **Local-first and private.** Your projects are plain folders (`project.json` + `assets/`); no telemetry; the server listens on `127.0.0.1`; API keys never reach the browser.

## Install

One command installs **and** updates (your data in `~/.openflow` is never touched):

**Linux and macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.ps1 | iex
```

Then open a **new terminal** and run:

```bash
flow
```

The installer creates an isolated environment (venv), installs Python 3.9+ if it is missing (apt, dnf, yum, pacman, zypper, apk, Homebrew or winget), installs OpenFlow, the optional libraries, offers the pre-installed models and sets up the Rust core (downloads the ready-made library from the Release and checks its SHA-256; compiles on your machine only if that fails). Anything already installed is **not** installed again.

| Variable | What it does |
|---|---|
| `OPENFLOW_EXTRAS=all\|none\|docs,media,local` | Optional libraries (default `all`; `none` installs only OpenFlow). One that fails never aborts the install. |
| `OPENFLOW_MODELS=ask\|all\|text\|image\|none` | Pre-installed models. Without the variable the installer **asks** (yes/no) before downloading several GB. |
| `OPENFLOW_RUST=yes\|ask\|no` | Rust core (default `yes`). |
| `OPENFLOW_PYTHON=auto\|keep` | `keep` never touches the system Python. |
| `OPENFLOW_SOURCE=<url\|folder>` | Install from another source (a fork, a local checkout). |
| `OPENFLOW_FORCE=1` | Reinstall even if the version is current. |
| `OPENFLOW_HOME`, `OPENFLOW_APP_DIR`, `OPENFLOW_BIN_DIR` | Where data, program and the `flow` command live. |
| `OPENFLOW_LANG=pt\|en` | Language of terminal messages (default: your computer's language). |

If you prefer pip: `pip install "openflow @ https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip"` gives you the same `flow` command (without the installer's extras).

## The `flow` command

| Command | What it does |
|---|---|
| `flow` · `flow run` | Opens OpenFlow in your browser (`--port`, `--host`, `--home`, `--no-browser`, `--no-update`). On start it checks for updates (once a day, only for installs made by the official installer; `--no-update` skips it). |
| `flow setup` (alias `flow install`) | Finishes an installation: optional libraries, pre-installed models and the Rust core. Safe to repeat. |
| `flow update` | Updates Python, OpenFlow, its libraries and the Rust core — only what is missing or has a newer version (`--core`, `--no-python`, `--extras`, `--force`, `--rust`). |
| `flow models list\|install\|support` | Pre-installed models; `support` checks every installed model and downloads the VAE, text encoder or `mmproj` it is missing. |
| `flow libs` | Installs/updates the optional libraries (`--sd-cli`, `--sd-latest` for new image models). |
| `flow native status\|build\|setup\|install\|update` | The Rust core and Rust itself. |
| `flow folder` | Opens the data folder (`--print` shows the path). |
| `flow doctor` · `flow version` | Diagnostics and version. |

## Projects — the home screen

OpenFlow opens on **Projects**: every project as a card (thumbnail, name, nodes, files, date).

- **Search bar** (press `/` anywhere on the screen): finds projects by **name, description and the texts inside nodes** (prompts, lines, titles, style-folder names). All words must appear; accents and case are ignored; the card says where it matched and highlights the match. No result? One click creates a project with the name you typed.
- **Sort** by most recent, name, oldest or most files (remembered).
- Menu on every card: open, rename, duplicate, download (`.zip`) and delete.
- `Ctrl/⌘ + K` opens the command palette (screens, projects and actions); `Alt + N` creates a project; `?` lists the shortcuts.
- Accessible by design: real links and buttons, labels for screen readers, visible focus, keyboard-only use, light/dark/automatic theme, interface size 90–150 %, reduced motion.

## The nodes

Every node has **one output**, **typed inputs** and a **result you can see on the node**. Results are cached by a hash of parameters, inputs, styles and model: only what changed runs again.

| Group | Nodes |
|---|---|
| **Text** | Text · AI text · Transcribe · Text template · Join texts · Edit text · Pick a piece · Refine with AI |
| **Image** | Image (generate or **edit**, with several references) · Resize · Filters and color · Text on image · Collage · Video frame |
| **Video** | Video (from text or a start image) · Cut · Join clips · Speed · Video look · Images to video |
| **Sound** | Sound (effects or music) · Voice (text to speech) · Cut · Mix · Effects · Audio from video · Repeat |
| **Input** | Media · Style Prompt · **Style Folder** · Color/gradient · Silence · Link (URL) · Random text · Date and project |
| **Output** | **Editor** (video editor: tracks, bin, preview, split/trim, fades, captions, MP4) · Final video · GIF · Final audio · Final image · Gallery |

Extras: `@` mentions of images, videos and sounds of the project inside prompts; a model picker on every media node (installed models, then each cloud provider you have a key for); **Generate flow with AI** (a planner + reviewer team builds nodes and connections from a sentence, with a template fallback when there is no AI); a Hugging Face **model search bar** in the editor; templates to start fast.

## Style Folder — folders and subfolders

The **Style Folder** node holds the images, videos and audio that define the look of the project. In v0.1+ it is organized like a file manager:

- **New folder** (at the node root) and **New subfolder** (inside any folder), up to **6 levels** and 60 folders per node.
- **Rename** a folder with the pencil button, by double-clicking its name, and confirm with `Enter` (`Esc` cancels). Names are unique among sibling folders (`Light`, `Light (2)`…).
- **Move files** between folders with the *Move to…* button on each thumbnail (keyboard-friendly) or by dragging them onto a folder. Drop files from your computer straight onto a folder to upload them there.
- **Turn a folder on/off** (the eye button): an off folder stays in the project but leaves the style, along with everything inside it.
- Folder names are part of the style: when OpenFlow describes your references (with your vision model, or from their dominant colors) it passes `Characters/Faces/ref1.png` and the folder structure, so *Characters*, *Lighting* or *Backgrounds* mean something to the model. Renaming a folder or moving a file refreshes the description and marks the nodes that use it as outdated.

Old projects open unchanged (a Style Folder without folders works as before).

## Models — support files install themselves

Open **Models** to install and manage local models (GGUF, via llama.cpp and stable-diffusion.cpp):

- **Recommended:** a small text model and an image model (Z-Image), with quantization already chosen. The image model comes with its VAE and text encoder.
- **Search on Hugging Face** by type (Text, Image, Video, Sound, Voice, Other); you see **every quantization** (bits, size, quality, whether it fits your RAM, the recommended one) and choose which to download.
- **Support files come along, automatically.** When you download a model, OpenFlow also downloads what it needs to run:

  | File | When |
  |---|---|
  | **VAE** | Image/video models of a known family (FLUX.2/3, Qwen-Image, Z-Image, Wan 2.1/2.2…) from the right repositories, or a VAE the model's own repository ships next to it. |
  | **Text encoders** (`clip_l`, `t5xxl`, `umt5`, Qwen3/Mistral/Qwen-VL as LLM encoders…) | Same rule as the VAE. |
  | **`mmproj`** (vision projector) | Text/vision models whose repository has `mmproj-*.gguf`; the best one is chosen (F16, BF16, Q8_0, F32) and saved as `<model>.mmproj.gguf` so two models never share the wrong projector. |

  Before downloading, the screen shows **what will come along** and its size. Downloads resume, never repeat what is already in the folder, and a support file that fails never undoes the model — the screen says what is missing and **Install what is missing** (or `flow models support`) fixes it. Deleting a model deletes its `mmproj`. You can switch this off (checkbox on the screen, or `hf.auto_support` in the settings).
- **Installed** shows each model with ✓ VAE · ✓ Text encoder · ⚠ missing …

With the optional `local` library, a model that has an `mmproj` next to it is loaded with image input (best effort: it depends on the installed `llama-cpp-python` knowing the model's family; otherwise it keeps working as text-only).

## AI providers

**Text** (AI text node, flow planner, style description): Claude (Anthropic), ChatGPT (OpenAI), Grok (xAI), Gemini, OpenRouter, Hugging Face Inference, LM Studio (detected automatically), Ollama / llama.cpp server / vLLM / any OpenAI-compatible endpoint, embedded Hugging Face GGUF, and **Demo** (offline).

**Media** (set per type in *Settings → Image, video, sound and voice*, and overridable on every node): OpenAI (gpt-image, TTS, Whisper), OpenAI-compatible servers (Kokoro, faster-whisper, LocalAI…), ElevenLabs, Google (Gemini/Veo), Stability AI, Replicate, Hugging Face Inference, Stable Diffusion WebUI (local), **Hugging Face local** (diffusers + transformers), **GGUF local** (stable-diffusion.cpp) and **Demo** (offline: procedural images, synthesized sound, Ken Burns video — needs `ffmpeg`).

## Rust core

OpenFlow keeps ASTA's architecture: orchestration and the HTTP server stay in Python (standard library only), on top of a small **Rust library** (`openflow/native`, std only, loaded with `ctypes`). It does the heavy lifting: audio synthesis for the Demo, the **run order** of the flow, **local-model planning** (reads GGUF/safetensors headers and the free RAM/VRAM to choose context size, GPU layers, threads and cache), a plan for several local agents, media analysis (loudness, silences, tempo) and memory release. **Every Rust function has an equivalent in Python** (`openflow/native/__init__.py`), so OpenFlow works without the library — just slower. `flow native setup` downloads the ready-made library (checked by SHA-256) and compiles locally only if needed; `flow doctor` shows its state.

## Your data

Everything lives in `~/.openflow` (or `OPENFLOW_HOME`), in open formats:

```
settings.json                     settings (API keys are never exported)
projects/<id>/project.json        nodes, connections, style folders
projects/<id>/assets/             generated and uploaded media
models/ (image/ video/ …)         GGUF models and their support files
native/                           the Rust library
```

No telemetry. The server listens on `127.0.0.1` and checks `Host`/`Origin`. Inputs (files, archives, URLs, AI output) are treated as untrusted; the AI only produces **data** (validated JSON), never code. Updates and uninstalling never delete your projects.

## Repository layout

```
openflow/
  cli.py · server.py · storage.py · routes_projects.py · routes_preinstalled.py
  canvas/        engine, node schema, media providers, store, support files (VAE/encoders/mmproj)
  providers/     text AI providers (cloud, local, Demo)
  native/        the Rust core + its Python mirror
  web/           the interface (plain HTML/CSS/JS, no build step)
install.sh · install.ps1     installers (Linux/macOS · Windows)
tests/                       Python, Node/Playwright and Rust tests
```

## Development

```bash
git clone https://github.com/KMC1525/OpenFlow && cd OpenFlow
python -m pip install -e .
python -m openflow --no-browser --no-update      # or: flow
python -m unittest discover -s tests -t .        # full suite
cargo test --release --manifest-path openflow/native/Cargo.toml
node tests/js/i18n_check.mjs                     # every UI phrase has an English translation
```

Browser tests need Node, Playwright and Chromium (`NODE_PATH` pointing at your `playwright` install). Python 3.9 compatible code (no `match`, no runtime `X | Y`). Every UI and terminal string is Portuguese-first with an English translation (`openflow/web/js/en.js`, `openflow/term_en.py`); tests enforce it.

## Honest limits (v0.2.0)

Verified here (Linux, Python 3.13): the full Python test suite (442 tests), the Chromium browser tests, the Rust tests, and `install.sh` end to end against a local checkout. **Not verified:** `install.ps1` on a real Windows machine and `install.sh` on macOS (CI jobs are written but were not run); Rust core builds for macOS/Windows/ARM; real downloads of VAEs, text encoders and `mmproj` from Hugging Face (tests simulate the downloads — file names of the curated and example repositories were checked against Hugging Face listings); inference with real GGUF models and GPUs; vision input through `mmproj` with a real model; cloud providers with real keys (tests use fake servers). Performance numbers are not benchmarked.

## License and credits

[MIT](LICENSE). OpenFlow derives from the Canvas mode of [ASTA](https://github.com/KMC1525/ASTA) (same author). Inspired by ElevenLabs Flow. Models, libraries and services keep their own licenses: llama.cpp, stable-diffusion.cpp, diffusers, transformers, ffmpeg and the model authors on Hugging Face.
