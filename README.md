<div align="center">

# OpenFlow

**Creative AI in node flows — images, videos, sounds, voices and 3D — local, open and simple.**

Connect a few nodes, see each result on the node, edit the final video without leaving the app. Everything runs on your computer with local models from Hugging Face. No accounts, no API keys, no telemetry.

[Install](#install) · [Use](#use) · [Nodes](#nodes) · [Models](#models) · [Settings](#settings) · [Data](#your-data) · [Development](#development) · [Changelog](CHANGELOG.en.md) · [Português](README.pt-BR.md)

`MIT` · `Windows` · `macOS` · `Linux` · `Python 3.9+` · `Rust core` · `v0.85.0`

</div>

---

OpenFlow is the *Canvas* mode of [ASTA](https://github.com/KMC1525/ASTA) turned into an app of its own: Python (standard library only) + a small Rust core, plain HTML/CSS/JS interface, one `flow` command.

## Install

One command installs **and** updates (your data in `~/.openflow` is never touched):

```bash
curl -fsSL https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.sh | sh        # Linux / macOS
```

```powershell
irm https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.ps1 | iex             # Windows
```

Open a new terminal and run `flow`. The installer sets up an isolated environment, Python 3.9+ if missing, the optional libraries, the pre-installed models (it **asks** before several GB) and the Rust core (ready-made library checked by SHA-256). With pip: `pip install "openflow @ https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip"`.

Useful variables: `OPENFLOW_EXTRAS=all|none|docs,media,local` · `OPENFLOW_MODELS=ask|all|text|image|none` · `OPENFLOW_RUST=yes|ask|no` · `OPENFLOW_PYTHON=auto|keep` · `OPENFLOW_SOURCE=<url|folder>` · `OPENFLOW_FORCE=1` · `OPENFLOW_HOME` · `OPENFLOW_LANG=pt|en`.

## Use

| Command | What it does |
|---|---|
| `flow` | Opens OpenFlow in the browser (`--port`, `--host`, `--home`, `--no-browser`, `--no-update`). |
| `flow update` | Updates OpenFlow, its libraries (incl. stable-diffusion.cpp) and the Rust core. |
| `flow setup` | Finishes an installation: libraries, pre-installed models, Rust core. Safe to repeat. |
| `flow libs` · `flow models` · `flow native` | Optional libraries · pre-installed models and support files · the Rust core. |
| `flow doctor` · `flow version` · `flow folder` | Diagnostics · version · open the data folder. |

The first screen lists your **projects** with a search bar (names, descriptions and node texts; `/` focuses it). `Ctrl/⌘+K` opens the command palette, `Alt+N` creates a project, `?` lists the shortcuts. The **Library** keeps your models and generated files in virtual folders (drag and drop, search, downloads, storage usage, external drives).

## Nodes

Every node has one output, typed inputs and a result shown on the node. Results are cached by a hash of parameters, inputs, styles and model: only what changed runs again.

| Group | Nodes |
|---|---|
| **Text** | Text · AI text · Transcribe · Template · Join · Edit · Pick · Refine with AI · Extract · Count |
| **Image** | Image (generate or **edit**, several references) · Resize · Filters · Text · Collage · Frame · Crop · Watermark · **Character sheet** · **Comic page** |
| **Video** | Video (from text or image) · Cut · Join · Speed · Look · Slideshow · Reframe · Loop · Audio |
| **Sound** | **Music · Lyrics · SFX · Dubbing · Transcript · Subtitles** · Sound · Voice · Cut · Mix · Effects · Audio from video · Loop · Remove silence |
| **Input** | Media · Style Prompt · **Style Folder** · Color · Silence · URL · Random text · Date · Pattern |
| **3D** | **3D model** (text or image → GLB/OBJ; viewer on the node) · **3D texture** (image or procedural pattern, with projection) · **3D skeleton** (automatic rig and skin) · **3D animation** (spin, bounce, sway, walk, wave…; plays in the viewer) |
| **Output** | **Editor** (tracks, split/trim, fades, captions, MP4) · Final video · GIF · Audio · Image · Thumbnail · Gallery |

The Style Prompt and Style Folder (folders and subfolders, renameable) apply to every generator. `@` mentions bring the project's images, videos and sounds into prompts.

## Models

**All model search and download happens in the model search bar at the top of the Canvas editor**, with a downloads indicator next to it (progress, speed, time left, cancel). Click it to see a catalog of known models (it only lists them), search Hugging Face by type, or paste an `owner/name` address. For image and video choose **GGUF** (pick the quantization: bits, size, quality, fits your RAM?) or the **original** diffusers format; text is GGUF only; sound, voice, transcription and 3D use the original format. For **sound, voice and transcription** pick a **topic** (music, sound effects, voice, voice cloning, dubbing…): the list opens with the most downloaded, without the video/«omni» noise of the Hub, and each result says whether it **runs in OpenFlow**. **Q2, Q3, Q4, Q6 and Q8 for every model (v0.81):** the GGUF list shows the five tiers of each repository (the missing ones are dimmed, with a button to look for them in other repositories of the same model); a missing tier can be **created** from a downloaded file (Library → model menu → “Create tier”, or `flow models quant --name FILE.gguf --tier Q4`) or **used on the fly** in an image/video node (“Quantization on load”); original (diffusers) models get Q8…Q2 in the precision choice, compressing the weights on load (needs `flow libs --extras quant`). **PyTorch and TensorFlow (v0.82):** Settings → Performance (and `flow frameworks` / `flow torch`) shows whether each one uses your graphics card and the exact command to fix it; the **“PyTorch/TensorFlow model”** node runs your own image → image models (Keras, SavedModel, `torch.export`, TorchScript), and the search bar's **“Own models”** type downloads only the chosen framework's file.

- **Support files come along:** VAE, text encoders and `mmproj` are downloaded with the model (switch off in *Settings → Performance → Model downloads*).
- **Providers:** only local ones — *Hugging Face local* (diffusers, transformers), *GGUF local* (llama.cpp for text, stable-diffusion.cpp for image/video) and an offline *Demo*. 3D: Shap-E, TripoSR, Hunyuan3D-2.
- Known families: Qwen-Image 2.1 (incl. ChatR Labs Uncensored Omni), FLUX.1/2/3, Z-Image, Wan, MiniMax H3, LTX-2.x, MOSS-Image and more.

## Settings

**Text (AI)** model and context window · **Image, video, sound and voice** default model per type · **Projects** starting template · **Appearance** theme, color, size, font, language · **Performance** mode, CPU/GPU (several GPUs pooled, VRAM + RAM together, hybrid CPU+GPU), RAM-class planner for 16 GB machines (DDR4/DDR5), download connections, Hugging Face token (gated models).

## Your data

Everything is in `~/.openflow` (or `OPENFLOW_HOME`, or the folders you choose in the Library), in open formats: `settings.json` · `projects/<id>/project.json` + `assets/` · `models/` · `native/`. No telemetry; the server listens on `127.0.0.1` and checks `Host`/`Origin`; inputs (files, archives, URLs, model output) are untrusted; updating or uninstalling never deletes your projects.

## Development

```bash
git clone https://github.com/KMC1525/OpenFlow && cd OpenFlow
python -m pip install -e .
python -m openflow --no-browser --no-update
python -m unittest discover -s tests -t .                  # full suite (browser tests need Node + Playwright)
cargo test --release --manifest-path openflow/native/Cargo.toml
node tests/js/i18n_check.mjs                               # every UI phrase has an English translation
```

The Rust core (`openflow/native`) does audio synthesis, run order, local-model and RAM planning, CPU/GPU detection and memory release; **every function has a Python mirror**, so OpenFlow works without it, just slower. UI and terminal strings are Portuguese-first with English translations (`openflow/web/js/en.js`, `openflow/term_en.py`); Python 3.9-compatible code.

## Honest limits

Verified on Linux (Python 3.13): the Python suite, the Chromium tests, the Rust tests and `install.sh`. **Not verified:** `install.ps1` on real Windows, macOS, Rust builds for macOS/Windows/ARM, real model downloads from Hugging Face (tests simulate them), inference with real models and GPUs, and speed on real 16 GB machines. Each release's changelog lists what it did not verify.

## License

[MIT](LICENSE). Derived from [ASTA](https://github.com/KMC1525/ASTA) (same author), inspired by ElevenLabs Flow. Models, libraries and tools keep their own licenses (llama.cpp, stable-diffusion.cpp, diffusers, transformers, ffmpeg and the model authors).
