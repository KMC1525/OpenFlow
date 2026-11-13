# AGENTS.md — OpenFlow

Guide for people and AI agents working in this repository.

## What this is
OpenFlow is a local-first app for creative AI creation through node flows (images, videos, sounds, voices), derived from the Canvas mode of ASTA. Python (standard library only) + a Rust core + a plain HTML/CSS/JS interface. The terminal command is `flow`.

## Rules that must hold
- **Keep the Rust ↔ Python parity.** Every function of `openflow/native/src/*.rs` has an equivalent in `openflow/native/__init__.py`. Changing the interface means bumping `ABI` (Python) and `flow_abi_version` (Rust) and keeping old libraries working.
- **No required dependencies** in the Python core (extras only in `pyproject.toml`). Python ≥ 3.9 (no `match`, no runtime `X | Y`).
- **Strings are Portuguese-first with an English translation:** UI → `openflow/web/js/en.js` (`node tests/js/i18n_check.mjs`), terminal → `openflow/term_en.py`, installers → `L "pt" "en"`. Maps used with `t(variable)` live in DOM-free modules (`labels.js`, `model_labels.js`, `canvas_nodes.js`) so the check can read them.
- **Keep install surfaces in sync** when behavior, commands, install steps or limits change: `README.md` + `README.pt-BR.md`, `CHANGELOG.md` + `CHANGELOG.en.md`, `install.sh`, `install.ps1`, `.github/workflows`. The version lives in `openflow/__init__.py` (`__version__`); write the changelog before bumping it.
- **Treat inputs as untrusted** (files, archives, URLs, AI output): validate paths, sizes, types and JSON. The AI produces data the engine validates, never code to execute.
- **Local and private:** the server listens on `127.0.0.1` and checks `Host`/`Origin`; API keys never reach the browser; no telemetry; updates and uninstalls never delete user data.
- **Honesty:** say in the docs and changelog what was not verified (real devices, real models/GPUs, Windows/macOS runs, external services). Never claim what was not tested.
- Never remove existing functionality without authorization; never push, merge or publish releases without it.

## Map
- `openflow/cli.py` — the `flow` command · `server.py`, `routes_projects.py`, `routes_preinstalled.py` — HTTP API (`/api/projects`, `/api/hf/*`, `/api/models/support`, `/api/media/*`) · `storage.py` — settings and folders.
- `openflow/canvas/` — `schema.py` (node types, Style Folder tree), `engine.py` (execution, cache, styles), `store.py` (project files, search), `media.py` (providers), `support.py` (VAE / text encoders / mmproj plan + install), `nodes_ext.py` (30 utility nodes), `render.py` (video Editor).
- `openflow/hf.py` (Hugging Face search/download) · `preinstalled.py` (recommended models) · `providers/` (text AI) · `team.py` (agents and effort) · `native/` (Rust core).
- `openflow/web/` — `main.js` (router), `views/projects.js` (home + search), `views/canvas_edit.js` (editor), `views/models.js`, `views/settings.js`, `canvas_nodes.js` (nodes, Style Folder tree).
- `tests/` — `python -m unittest discover -s tests -t .` (browser tests need Node + Playwright + Chromium).
