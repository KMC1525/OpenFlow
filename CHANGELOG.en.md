# Changelog

Format: `## [version] — date`. Each version lists what changed for users and, honestly, what was **not** verified. [Português](CHANGELOG.md)

## [0.50.0] — 2026-11-16

### Design and customization
- **Graphite gray instead of pure black:** the dark theme now uses a soft gray (`#1e1f22`, slightly lighter panels, off-white text instead of pure white, lighter shadows) that is easier on the eyes in long sessions. It applies to the whole interface, the Canvas node area, the timeline and the browser/installed-app `theme-color`. Only the video stage stays black, since it is the media screen. The light theme did not change.
- **Interface size from 50% to 200%** (steps of 5): a slider in Settings → Appearance, with shortcuts 50 · 75 · 90 · 100 · 110 · 125 · 150 · 175 · 200%. It used to be five values (90–150%). The size applies when you release the slider (the whole interface resizes, the slider included). Old values stay valid.
- **More fonts:** System, Inter, Humanist, Rounded, Verdana, High legibility (Atkinson Hyperlegible/Lexend/OpenDyslexic), Book, Serif and Monospace — each card shows its own font — plus **“Other font”**, where you type the name of any font installed on your computer. The name is sanitized (letters, digits, space, dot and hyphen only) before it reaches the CSS.

### Tested
- `tests/test_design_v050.py` (8 tests): scale range and rounding, invalid values, font names without CSS injection, every font having CSS and a card, background color (neither black nor too light), API round trip. Browser test: background, 50%/200%/100% applied and saved, font cards, “Other font”.

### Not verified yet
- **I only checked the background by values and tests**, not by a person looking at it for hours: the exact tone (`#1e1f22`) is my choice; if it still bothers you, tell me whether you prefer lighter or warmer.
- Fonts use what exists on the computer; **nothing is downloaded**. Inter, Atkinson, Lexend and OpenDyslexic only show up if installed (otherwise a similar system font is used). I did not see them all rendered on Windows, macOS and Linux.
- At 50% and 200% the main screen and Settings stay usable in the test, but I did not walk through every screen and modal at those extremes; a browser without `zoom` support (old Firefox) ignores the size.

## [0.49.0] — 2026-11-16

### New — Computer protection
- **OpenFlow stops everything if your computer gets overloaded.** A watchdog (`openflow/guard.py`) samples **CPU**, **RAM** and **GPU** use every second. If any of them stays at **90% or more for 5 seconds** while OpenFlow is working, it **stops everything**: cancels running jobs, ends the processes it started (ffmpeg, sd-cli, llama…) and unloads the text and media models from memory.
- **No surprises:** a red banner at the top says what was stopped and why («RAM at 94%…»), and each cancelled job records the cause in its own log.
- **Settings → Performance → «Computer protection»:** on/off, limit (50–99%, default 90), seconds (1–60, default 5), what to watch (CPU, RAM, GPU), live readings and a **«Stop everything now»** button (the same stop, on demand). API: `GET /api/guard` and `POST /api/guard/stop`.
- **Rules so it does not get in the way for nothing:** a short spike does not trip it (only load sustained for the configured seconds); it acts only while **OpenFlow is working** (if another program overloads the machine there is nothing to stop here); after a stop there is a 20 s pause before it can trip again.

### Tested
- `tests/test_guard_v049.py` (15 tests): the decision machine with a fake sampler and clock (short spike, exact limit, disabled, idle, unticked metric), the full stop (job cancelled, child and grandchild processes ended, models unloaded, pause), reading `/proc/stat` and memory, and the API routes. Plus one browser test (card, saving, minimum limit, warning banner).
- In tests the watchdog is off (`OPENFLOW_NO_GUARD=1`) so it never trips by accident on a busy machine.

### Not verified yet
- **Not tested on a truly overloaded machine**: the decision was tested with simulated readings and the Linux CPU/RAM reading here; I did not see a real trip, nor on Windows or macOS (CPU there is an approximation from system load).
- **Generating on the CPU often uses ~100% of it and will trip the protection** with the default setting. If that gets in the way, untick «CPU» or raise the limit.
- **GPU:** only NVIDIA cards report utilization (via `nvidia-smi`) plus dedicated video memory; AMD/Intel/Apple are not measured, and without a reading the GPU never trips.
- A model running **inside** the OpenFlow process (embedded llama.cpp) is only cancelled between steps and unloaded afterwards; it is not interrupted mid-computation.
- The installer and `flow setup` still offer the pre-installed models (see 0.48).

## [0.48.0] — 2026-11-16

### Removed — “Ready to install” in the Canvas search bar
- The **“Ready to install”** section (with Z-Image and the text model, and an Install button) that showed up when clicking the model search bar is gone: the user chooses, searches and downloads the model. The bar no longer queries `/api/preinstalled`.
- **Stays** the **“Recommended catalog (GGUF)”** (Unsloth and ChatR Labs): it only **lists** known models and opens each one's search with “See quantizations”; nothing is installed until you pick the quantization and press Download.

### Not verified yet
- I did not touch anything outside the bar: the installer (`install.sh`/`install.ps1`) and `flow setup` still **ask** whether you want the pre-installed models (`OPENFLOW_MODELS=none` turns it off), and `flow models install` and the `/api/preinstalled` route still exist.

## [0.47.0] — 2026-11-16

### Fixed — general sweep 4
- **New node vanishes when saving at the limit:** a project accepts up to 200 nodes, but the editor let you create the 201st, which the server dropped on save (it disappeared when reopened). The editor now warns “Limit of 200 nodes per project…” and does not create it; deleting a node frees the room (the limit comes from the server).
- **Settings with the wrong type:** a provider's model or context window, and the media model names, with the wrong type (coming from settings import, the API or hand editing) were stored as they were and broke model loading; now only text (model) and an integer ≥ 0 (context, up to 4,194,304) count, the rest is discarded.
- **Invalid GLB:** a file that merely started with “glTF” entered the project as a 3D model; now the header and JSON are checked and the upload is refused with “That file is not a valid GLB 3D model”.
- **Leak when opening and closing the Canvas:** the model search bar and the downloads indicator left global listeners (`flow:hub`, `flow:downloads`, `pointerdown`, `Escape`) and a polling timer behind on every visit; they now release when leaving the Canvas, and outside it there is no downloads polling.

### Tested
- All 54 node types run with valid inputs (`tests/test_all_nodes_v038.py` and the sweep); the odd-input matrix (images, videos and audio) still has no unexpected failures; fuzz of 1,600 API requests, node parameters and odd texts in the sheet and comic nodes; huge bodies and nested JSON are refused; 400 chained nodes run in ~4 s and the second “Run all” uses the cache in ~10 ms.

### Not verified yet
- The 600-connections-per-project limit also drops the excess silently on save; the editor does not warn yet (hard to reach with 200 nodes).
- Real local models and the “Transcribe” node (the Whisper library is missing here) still did not run in this environment.

## [0.46.0] — 2026-11-16

### Changed — a shorter, more objective README
- Both READMEs (Portuguese and English) were rewritten: from 196 to 98 lines each. What stays: install, the `flow` command, the nodes, the models (search and download only through the Canvas bar, with the downloads indicator), settings, data, development, limits and license.
- Outdated parts are gone: “models from companies (API)”, “30 utility nodes”, the Library's “Download more models” catalogue, “cloud providers with real keys”, the agent planner, and the long Style Folder and support-files sections (one line each now).
- The installer variables table became one line; the commands table keeps only the main ones.

### Not verified yet
- The README's node list is a summary: the names in the interface may differ slightly.
- Nothing but the version (0.46.0) changed in the code.

## [0.45.0] — 2026-11-16

### New — 16 GB RAM computers (DDR4 and DDR5), with the Rust core
- **RAM-class memory planner** (`flow_plan_ram`, Rust core interface 7; a Python mirror with the same math, checked by the tests): it subtracts what the system, the browser and OpenFlow use (≈ 22% of RAM, between 2.5 and 6 GB) and, on what is left, decides:
  - **One model at a time in RAM:** if the text model and the image/video/sound one do not fit together, the loaded one **leaves first** before the other loads (before, both stayed in RAM and the computer started using the disk).
  - **Context** that fits the RAM left and an **8-bit attention cache** when the model takes more than 60% of it.
  - **Threads and batches by memory speed** (DDR4/DDR5 × MT/s × channels, read from SMBIOS when permitted): more threads than memory can feed only hurt CPU generation; DDR5 and dual channel take bigger batches; tight RAM uses smaller batches (compute buffers also take RAM).
  - **`mlock` only when there is plenty left**, prefetch only when the model fits comfortably and a smaller prompt cache when tight.
  - **Image, video and sound:** attention and VAE slicing on when the model takes a big share of RAM; idle models unload sooner (2 to 5 min) in this class.
- Only acts on the “small” (< 12 GB) and “16 GB” (12 to 24 GB) classes; at 32 GB or more nothing changes. Any planner failure goes back to the previous behavior, and a hand-set context is never shrunk.
- **Settings → Performance → Processor:** a new “Memory for the models” line (what is left after the system, GB/s and useful threads) with your RAM class.
- The core moved to **interface 7**: interface 6 libraries (v0.29–v0.44) still load and OpenFlow uses the planner's Python mirror until the new library is downloaded (`flow native setup`).

### Not verified yet
- **I did not measure a real speed gain on a 16 GB machine** (this environment is not one): the tests prove the math (Rust = Python on 400 random cases), the integration and the limits; the expected gains come from avoiding disk use when text and media compete for RAM and from not using more threads than memory feeds.
- DDR4/DDR5, MT/s and channels come from SMBIOS (Windows and `dmidecode` on Linux, with permission); without that the planner assumes DDR4-2400 in dual channel, which is conservative.
- The limits (22% reserve, 60% “tight”, ~12 GB/s per core) are heuristics; adjust them if you measure differently.

## [0.44.0] — 2026-11-16

### Removed — legacy or useless settings
- **Text (AI):** gone are the “Load models” button (it never showed for the remaining providers), the hidden address, API-key and “vision” fields (the card now saves only the **model** and the **context window**), the “local” and “generation” labels (now “in use”) and leftover code from the cloud era.
- **Image, video, sound and voice:** gone are the “no key” warning, the “configured” dot, the “local” badge (every provider is local) and the word “connection” in the test.
- **Appearance:** the “Appearance defaults” text no longer mentions keys and avatars; the Rust core text no longer mentions “agents”.
- **Settings file:** the `generation` section (temperature, tokens and “content” inherited from ASTA's Chat, which nobody read), the `voice` section, API keys, addresses and `vision` of providers and `media.urls` leave `settings.json` on the next save; old files still load. Settings export/import and “Restore defaults” no longer handle those sections.
- **API:** `GET /api/state` and `/api/media/providers` no longer carry `needs_key`, `has_key`, `base_url`, `docs`, `login`, `oauth` and the like; the `POST /api/providers/models` route is gone; media providers lost `key`, `base`, `need_key` and `need_url`.
- In the nodes' “Model” list: “Set up providers and keys…” became “Set up providers…” and “No cloud model” became “No model (Demo)”.

### Kept on purpose
- **Hugging Face token** (gated models), connections per download, “download the VAE… along”, Performance (CPU, GPU, Rust), Appearance (theme, color, scale, density, font, animations, language), Projects and the precision choice of downloads in Image, video, sound and voice: all of it is read by the app.

### Not verified yet
- I did not review the screens in every language combination (the translation check covers the new texts).
- Internal fields without a screen were left out of this cleanup (for example `server.max_upload_mb`, which the app reads).

## [0.43.0] — 2026-11-16

### New — follow model downloads inside the Canvas
- A **downloads** button sits right next to the model search bar at the top of the editor: it shows how many downloads are running (a counter and an overall progress bar) and, when clicked, opens a panel with **each download**: name, repository, percentage, bytes downloaded, speed and time left, the current step's note, a **Cancel** button, and the session's **recent** ones (finished, cancelled and failed, with the reason).
- It refreshes by itself (every 1 s with a download or the panel open; every 4 s when idle) and immediately when you press Download in the search bar. It closes with Esc or by clicking outside; on phones the panel takes the screen width.
- It uses the same data as the Library's Downloads tab (`/api/library/downloads`): model downloads, support files (VAE, text encoder), recommended models and the sd-cli library.

### Not verified yet
- Tested with simulated downloads API responses (the environment has no network to download real models); the list itself comes from an endpoint that already existed and is covered by the Library tests.
- The panel shows the downloads of **this server session**: restarting OpenFlow clears the recent list (as in the Library).

## [0.42.0] — 2026-11-16

### Changed — searching and downloading models is now only through the Canvas search bar
- **The Canvas model search bar** (top of the editor) gained everything the Library's models screen had: clicking it shows the **recommended models** ("ready to install" ones and the GGUF catalog of Unsloth and partners, such as ChatR Labs); you can **paste an `owner/name` address** (the repository opens directly, even if the search does not list it); the quantization list shows the incompatible-repository warning and what **comes along** (VAE, text encoder, mmproj).
- **Non-GGUF format:** image and video choose between **GGUF** (quantizations) and **Original** (diffusers, with fp32/fp16/bf16 precision); sound, voice, transcription and 3D use the original format; **text only runs GGUF** (llama.cpp), so its format is locked to GGUF.
- **Library:** the "Download more models" button, the model search/download screen (`views/models.js`) and the `GET /api/hf/search` route are gone. The Library only stores, organizes, uses and deletes models and files; the Downloads tab still shows progress.
- Warnings that used to send you to the Library/Models (node without the downloaded model, stable-diffusion.cpp-compatible repository, welcome, server messages) now open or point to the Canvas search bar.
- **Settings → Performance → Model downloads:** connections per download, "download the VAE/encoders/mmproj along" and the Hugging Face token (gated models) moved here from the removed models screen.
- Fixed: the Rust core text still said "Agents, storage and memory" (agents went away in v0.40).

### Not verified yet
- Real Hugging Face searches did not run here (no network in this environment): the browser tests use simulated API responses.
- Text models in the original (transformers) format do not run in OpenFlow, so text only searches GGUF.
- Model downloading is still also available in Settings → Image, video, sound and voice (each provider's precision choice) and in the `flow setup` recommended models: only the Library lost search and download.

## [0.41.0] — 2026-11-16

### New — ChatR Labs · Qwen-Image 2.1 Uncensored Omni Quantized
- The [`chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized`](https://huggingface.co/chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized) repository (Qwen-Image 2.1 with an “uncensored” Omni adapter merged and quantized, step 90000) shows up in **Models → Unsloth and partner models** as *Experimental*, with the list of GGUF quantizations (Q4_0 ≈ 4.2 GB … Q8_0 ≈ 7.7 GB and BF16 ≈ 14 GB; Q4_K_M is the recommended one) and the “See quantizations” button.
- The `qwen-image-2.1-step90000-*.gguf` files are recognized as **Qwen-Image 2.1** and use the **card's recipe: 35 steps and CFG 5.0** (the official Qwen-Image 2.1 and the Turbo keep theirs: 20 steps/CFG 6.0 and 8 steps/CFG 1.0). Multi-reference editing, as in Qwen-Image 2.1.
- Downloading the GGUF also downloads the **Qwen-Image 2.1 VAE** and the **Qwen3-VL-8B text encoder** (≈ 5.8 GB, not downloaded again if already there); the repository's `-comfy.safetensors` and diffusers folders are not mistaken for support files.
- The NF4/INT8/FP8 folders (transformer only, for diffusers) and the `-comfy` files (ComfyUI only) do **not** run in OpenFlow: the “Hugging Face local” provider refuses the repository with a message pointing to the `.gguf` files and the “GGUF local” provider.
- Fixed: the catalog's “Experimental” models (MiniMax H3, LTX-2.x…) had no “See quantizations” button; they do now.
- The model license is **Qwen Research** (research and non-commercial use only), noted in the catalog hint.

### Not verified yet
- **None of these GGUF files was run here** (no weights or GPU). I did not confirm that the installed stable-diffusion.cpp recognizes the tensor names of the ChatR Labs GGUF (“297” layout: the same style as Unsloth's GGUF); if it does not, the node's warning says so and the update-library button appears, as with other models.
- The card says `er_sde` + `simple` in ComfyUI; OpenFlow uses `euler` (the sampler the other Qwen-Image 2.1 recipes use in stable-diffusion.cpp). The single-space negative prompt only applies to diffusers/ComfyUI.

## [0.40.0] — 2026-11-16

### Removed — ASTA's agents, multi-agents and effort levels (Low … Omni)
- Gone: the **agent table** (1 to 32 parallel agents, private notes, peer review and a Synthesizer — `team.py`), the **effort levels** Low · Medium · High · Extra · Mega · Max · Ultra · Omni (`efforts.py`) and the model "thinking time" request (`providers/thinking.py`), along with the `GET /api/team` route, the team picker in the canvas bar, the "Agent team" card in Settings → Project, the `team` field in the run request and their texts, styles and tests.
- The AI text nodes ("AI text", "Refine with AI") and the style description now make **a single call** to the model, with the node's fixed answer size (no effort multiplier).
- Old settings with `agents`/`effort` still load (the keys are ignored).

### Not verified yet
- I kept the **Rust core planner** (`plan_agents`): it now only decides how many local text models can stay loaded in memory at once and the priority queue of the embedded model; the core ABI and the Rust code were not touched (nothing was recompiled). If you want, it can go in a release of its own.
- `Cancelled` and the priority queue (`scheduler.py`) stay: they belong to cancellation and the local model's queue, not to the agents.

## [0.39.0] — 2026-11-15

### Removed (for now) — "Generate flow with AI"
- Gone: the **canvas prompt box** ("Generate flow with AI"), the `POST /api/projects/{id}/flow` route, the Planner → Reviewer pipeline (`canvas/flow.py`) and the `agents/` package only it used, plus its texts, styles and tests. Projects, nodes, project templates and everything else stay as they were; building a flow is now through the palette, drag and drop, or project templates.
- **Stays:** the team (effort Low…Omni and 1–32 agents) for AI text nodes — its picker moved to the canvas top bar, next to "Run all" (it used to live inside the prompt box) — and the agent table (`team.py`) that the "AI text" and "Refine with AI" nodes use. The Demo no longer handles the planner's agent marker.
- `Cancelled`, which lived in the removed package, is now in `openflow/util.py`.

### Not verified yet
- I did not remove `team.ensemble_json`/`critique_json` (the agent table that returned JSON): they are unused by the app now but covered by tests, for when the feature returns.
- On medium screens the top bar wraps into two rows (team + Run all below); checked only by screenshots at 1500, 1100 and 390 px.

## [0.38.0] — 2026-11-15

### Fixed — general sweep (every node, screen and the API)
- **A GIF used as a still image in a video** (Editor, "Join clips", "Images to video" and "Final video") failed with ffmpeg's "Option not found"; the GIF now goes in through its first frame.
- **Editor with only audio** on the timeline failed with "Error opening output files"; it now makes a plain-background video with the sound.
- **"Extract from text" with a regex that never ends** (e.g. `(a|a)*b`) froze the run with no way to cancel; the pattern now runs in a separate process with a 4 s limit and says "took too long".
- Invalid API inputs (search kind, repository, a provider that no longer exists) answered 502 ("gateway"); they now answer 400.
- Lint: an f-string without fields.

### Tested
- **The 54 node types (49 runnable; the other 5 are Text, Media, Style Prompt, Style Folder and Link) really run** (engine + ffmpeg + Demo) with valid inputs wired — `tests/test_all_nodes_v038.py`; only "Transcribe" depends on the optional Whisper library.
- A matrix of odd inputs (RGBA/gray/palette/WebP/GIF/CMYK/16-bit/tiny/huge images; vertical/silent/odd-size/broken-fps/WebM/very short videos; mono WAV/OGG/FLAC/M4A/short audio) against every media node.
- Browser sweep (`sweep_ui.js`): every screen at 390, 1500 and 3440 px with no horizontal scroll, every Settings tab, and every canvas node with every option of every list and odd values in fields, then running everything — no page errors.
- Fuzz of 1,700 API requests and 8 thousand node parameters: no 500 errors; reads/writes outside the folder, zip-slip, secrets in exports and cross-origin requests remain blocked.

### Not verified yet
- Real local models (llama.cpp, diffusers, Shap-E…) still not run here, for lack of weights.
- "Transcribe" did not run (the Whisper library is missing in this environment).

## [0.37.0] — 2026-11-15

### New — local 3D models (text → 3D and image → 3D)
- **"3D model" node** (new **3D** palette group): prompt and/or image → **GLB** or **OBJ** file, with a viewer on the node (drag to rotate, wheel to zoom, auto-spin) and in the enlarged view; Download button; the Gallery accepts the model; the Library has a "3D models" type.
- **Local Hugging Face models:** **Shap-E** (`openai/shap-e` text → 3D; `openai/shap-e-img2img` image → 3D, picked automatically when an image is connected), **TripoSR** (`stabilityai/TripoSR`) and **Hunyuan3D-2** (`tencent/Hunyuan3D-2mini` / `-2`), image only. With a text, TripoSR and Hunyuan3D first generate an image of the object with the default image model (two steps, noted on the node).
- Download/use: "3D" in the Canvas model search bar (Hugging Face: text-to-3d / image-to-3d) and in Settings → Media; downloaded 3D models only appear in the 3D node's list. Nothing is downloaded silently.
- **Offline Demo:** procedural shapes (sphere, torus, cube, cone, vase) with colors — to test 3D flows without a model.
- Own GLB and OBJ writer (no dependencies); the mesh is centered and fitted into a cube of side 2.

### Not verified yet
- **No real 3D model was run here** (no weights, GPU, or the TripoSR/Hunyuan3D libraries): Shap-E, TripoSR and Hunyuan3D-2 were tested only with stand-ins. Shap-E's mesh orientation (rotated −90° on X) and the Hunyuan3D/TripoSR subfolder names and arguments follow their documentation and may need tuning.
- The viewer is a simple renderer (no textures; per-vertex colors) and draws at most ~40k faces at a time.
- Textured (UV) output of the big models is not written: only geometry and per-vertex color.

## [0.36.0] — 2026-11-15

### New — 2 nodes in the Image group to make hard prompts easy
- **Character sheet:** name, description, views (front, side, back, three-quarter, face, full body), extras (expressions, color palette, outfit, props, poses, height comparison), layout (row, turnaround or grid), pose, background, labels. Inputs: "Description" (texts) and "Style". Asks for character consistency across views.
- **Comic page:** format (page, strip, webtoon, yonkoma, splash), scenes as `scene | line` rows, linked characters, layout, style (American, manga, Franco-Belgian, webtoon, cartoon, indie), color/B&W/halftone, balloons (with lines, empty, none), reading direction (manga), title. Scenes beyond what the format holds produce a warning.
- Both deliver **text** (the prompt): connect it to an Image node. Prompt in English (recommended for models) or Portuguese; a linked Style Prompt/Folder is appended. The palette now has 53 nodes.

### Not verified yet
- The prompt is built deterministically; how well each local model draws sheets and panels (and the text inside balloons) depends on the model and was not measured here without weights.

## [0.35.0] — 2026-11-15

### Changed — no cloud (for now): only local Hugging Face models
- **Removed** every cloud/frontier provider (OpenAI, Claude, Grok, Gemini, OpenRouter, ElevenLabs, Stability, Qwen, Krea, Bria, Replicate, Hugging Face Inference…) **and the local-server providers too** (Ollama, LM Studio, llama.cpp server, A1111, OpenAI-compatible endpoints, server-mode voice): what remains is **Hugging Face local**, **GGUF local** and offline **Demo**.
- Old settings migrate by themselves: removed providers and keys are ignored (and leave `settings.json` on the next save); defaults go back to Demo/auto; nodes saved with a removed provider use the project default. The "Voice" tab and key/URL fields are gone from Settings.
- Clear message when something asks for a provider that no longer exists.

### Not verified yet
- Migration tested with synthetic settings, not real old installs.
- Real local models (llama.cpp, diffusers) still not exercised here without weights.

## [0.34.0] — 2026-11-15

### New — 10 new canvas nodes (the current ones stay; all tested by really running them)
- **Text:** **Extract from text** (links, e-mails, hashtags, numbers, quoted phrases, WORDS IN CAPITALS or a pattern/regex — protected against patterns that hang) · **Count text** (words, characters, lines).
- **Image:** **Crop image** (by ratio 1:1, 16:9, 9:16, 4:3, 3:2, 21:9 keeping the center/top/bottom/side, or by area in %) · **Watermark** (logo in a corner, with size, margin and opacity).
- **Video:** **Change aspect ratio** (9:16 vertical, 1:1, 4:5…: blurred background — the Reels/Shorts format —, fill and crop, or borders; keeps sound and frame rate) · **Loop video** (N times or to a duration) · **Audio in video** (replace, mix or remove the sound; end at the video or the audio).
- **Sound:** **Remove silences** (dB threshold, minimum silence and kept breathing room).
- **Input:** **Pattern and texture** (checkerboard, stripes, grid, dots and noise, in two colors).
- **Output:** **Thumbnail with title** (image cropped to 16:9 with the title on top, dark band and 3 positions; JPG or PNG).
- Each node has an icon, help, ports, form and translation; the palette (now with **search**, v0.31) lists them in the usual groups.

### Improved — Style Prompt and Style Folder understand characters, scenery and objects
- **Roles from folders:** the folder name says what it shows — “Characters”, “Scenery”, “Objects”, “Style”/“Light”… (Portuguese too). **A subfolder is an entity** (`Characters/Maria/front.png`, `side.png`); without subfolders, files starting with the same name become the same one (`maria_front.png` + `maria_side_v2.png` → Maria). A **`.txt`/`.md` with the entity's name is its description**.
- **Structured description, one line per item:** `ESTILO GERAL`, `TRAÇOS COMUNS DOS PERSONAGENS`, `PERSONAGEM — Maria: …` (apparent age, hair, eyes, skin, clothes, accessories, marks, posture), `CENÁRIO — Floresta: …`, `OBJETO — Espada: …`, `CONSISTÊNCIA: …` (what never changes between images). A vision AI receives **each image captioned with the name of who appears** (up to 10 for entities + style) and answers in that format; **every entity appears**, even if the AI forgets one (it enters with what is known: neighbouring text, colors, number of images), and without AI OpenFlow builds the same format from what it has.
- **General traits:** a new Style Folder field (“all characters wear a blue uniform; fine line…”) enters every description. The Style Prompt recognises `Personagem: Ana — ruiva` (and the other sections) and drops repeated lines.
- **Only what the prompt needs:** a Style Folder with 30 characters does not dump all 30 into each generation. The prompt “Maria walks through the forest” gets the general style, the sheet of **Maria** and of the **Forest** scenery, the common traits and the consistency; the others become one “Project cast” line. (Up to 3 entities all enter.) Applies to Image, Video, Sound, Voice, AI Text and Refine with AI.
- **The right reference images:** the images sent to the model are now those of the entities **cited** in the prompt (one each, then the second…, in the order they appear), then the general-style ones — before, they were always the node's first 3.
- The description shows in the node line by line, with the role highlighted.

### Not verified
- I tested AI description with a **simulated** model (the requested format, reading the answer, captioned images and the forgotten entity); **I did not test with a real vision model**, so the quality of character sheets depends on the model.
- Roles from folders depend on the names (common Portuguese and English words); folders with other names become general style. File names like “IMG_0034.png” create no entity.
- Relevance recognises the entity's name in the prompt (accent- and case-insensitive; the first name is enough). A nickname or pronoun (“she”) is not followed.
- The new nodes were tested with synthetic ffmpeg videos and images; “Watermark” and “Thumbnail” depend on ffmpeg having the text filter/font (like the text nodes that already existed).

## [0.33.0] — 2026-11-15

### New — Library in other folders (external HDD/SSD, pen drive, another disk)
- **Library → Storage → “Where to store”:** choose **where the AI models live** and **where the project files live** (generated or uploaded images, videos and sounds) — an external HDD or SSD, a pen drive or another folder on the computer itself. Each has its own folder (“default” or “custom”), with free space, the type (SSD/HDD) and a **Change…** button that lists the computer's **disks and devices** (with free space and an “external” tag), lets you browse folders or type the path, and offers **“Use the default”** to go back.
- **Moving what already exists, safely:** the “Move what already exists” option **copies first** (with a progress bar, cancellable and also shown in the Downloads tab), checks each file's size, **switches the folder in use only at the end** and only then empties the old folder; a failure or cancel **undoes the new copies** and the old folder stays intact, so a model is never missing. It resumes where it stopped if repeated. Without “move”, OpenFlow starts using the new folder and the old content stays where it is (warned in the dialog).
- **A disconnected external disk does not break OpenFlow:** if the configured folder is not accessible (device unplugged, folder deleted), it **uses the default and shows a warning** on the card; when the disk comes back, the chosen folder applies again.
- **Safeguards:** the new folder must exist (or its parent, so one can be created), accept writing and **have room** for the content; it cannot sit inside the current one (nor the current inside it); a **disk root** becomes an “OpenFlow-modelos”/“OpenFlow-projetos” subfolder (no scattering files over a pen drive's root); and nothing changes while a generation, download or other task is running. New routes: `GET /api/storage/locations`, `GET /api/storage/browse` and `POST /api/storage/location`; the setting lives in `storage.models_dir` and `storage.files_dir`.
- The models folder applies to everything: downloads, support files, the Library list, the terminal's `flow models …` and model loading. Settings and the folder map stay in OpenFlow's data folder.

### Not verified
- **I did not test with a real external disk:** tests use temporary folders (copy, undo, validation, folder switch and the inaccessible-folder warning run; the warning with a really unplugged device was simulated with a path that cannot be created). The **device list** follows each system's convention (Linux `/media`, `/run/media`, `/mnt`; macOS `/Volumes`; Windows drive letters) and **was not run on Windows or macOS**.
- Moving between slow disks (an external HDD over USB 2) can take a long time; performance was **not** measured. Running models from a slow external disk makes loading slower (OpenFlow preloads the model into RAM).
- **Not moved:** the Hugging Face cache (LTX-2 components), `sd-cli`, loose uploads (`uploads`), settings and the Library folder map — they stay in OpenFlow's data folder.
- Importing settings on another computer brings the paths: if they do not exist there, the warning and the default folder apply.

## [0.32.0] — 2026-11-15

### Fixed — bugs when editing generated videos (and images)
I looked by running every editing node (trim, speed, look, frame, GIF, export, join, slideshow; resize, filter, text, collage) with videos and images of different sizes, frame rates and tracks (odd width/height, portrait, very short, no audio, 12/16/24 fps, a 1×1 and a 3000×200 px image). The bugs found:
- **A video with odd width or height (e.g. 853×481) could not be trimmed, sped up or given a “Look”:** ffmpeg refused (“Nothing was written into output file”). The size is now rounded down to the nearest even number (852×480) before encoding.
- **Trim, speed and look converted everything to 30 fps:** a 16 or 24 fps video (what models usually produce) got repeated frames and stuttered, and a 12 fps one became 30. The **source frame rate is now kept**.
- **Speed: the duration came out wrong and the sound ended before the picture** (3 s at 2× gave 1.67 s of video for 1.51 s of sound instead of 1.5 s for both). The video now has the exact duration (1.50 s at 2×, 0.75 s at 4×), in sync with the audio.
- **Uploaded or generated videos had no width and height recorded** (only images did): they are now read with `ffprobe` when saved.
- Everything else passed without errors: 1×1 and 3000×200 images, text with `%`, quotes and backslash, a video without audio, a very short video, joining videos of different sizes and ratios, and image editing through the engine (one or several references, a video as reference, the model's reference limit).

### Not verified
- Tested with synthetic ffmpeg videos (`testsrc`), not with real video-model outputs nor phone videos (rotation metadata, real VFR).
- I found no bugs in the image “Edit” mode beyond what was already fixed; the quality of an edit depends on the model (not verifiable here). An “almost identical” result still only warns.
- `reverse` in speed loads the whole video into memory (an ffmpeg filter limit): long high-resolution videos may be heavy.

## [0.31.0] — 2026-11-15

### New — General improvements 2.0
- **Large and ultrawide screens:** above 1700 px the page, sidebar, node palette and the canvas file panel grow with the window (before, content sat in a 1180 px column in the middle of a 3440 px monitor); steps at 1700, 2200 and 3000 px and a tweak for 21:9 or wider screens. The Library gets more columns and larger cards. Nothing scrolls sideways at 1920, 3440 and on a phone (tested).
- **Node search in the canvas palette:** a field at the top of the nodes tab filters by name, description and group (accent- and case-insensitive); **Enter** adds the first result to the flow and **Esc** clears.
- **Dual/quad-channel RAM, DDR4/DDR5:** the v0.28 planner already used the measured bandwidth to pick generation threads (a 4-channel memory saturates with more threads than a 1-channel one); OpenFlow now also **reads the memory sticks** (Windows through SMBIOS/PowerShell; Linux through `dmidecode` when permitted): count, DDR4/DDR5, speed, **channels** and theoretical bandwidth, shown in Performance → Processor. And it **tells you what helps**: a single stick (single channel: model speed is halved), **XMP/EXPO off** (memory runs below what the stick supports) and measured speed well below theoretical. On **servers and Threadripper/EPYC with several NUMA nodes** llama.cpp now spreads threads and memory across the nodes.
- **Storage (HDD and SSD):** OpenFlow detects whether the models sit on an **HDD or SSD**. On an **HDD** it downloads over **a single connection** (sequential writing, no fragmentation) and preloads the model with **one thread** (parallel reads turn into random seeks and slow the disk); on an SSD it stays parallel. New **Library → Storage** section: free/total space, how much models (by type), projects and uploads take, and **cleanup** of incomplete downloads abandoned for over 1 hour, leftovers from interrupted generations and project files no project uses any more — it never deletes models or files in use (with a download running, partials stay). Routes `GET /api/storage` and `POST /api/storage/clean`.
- **Run local models on the CPU and GPU at the same time:** new **“Hybrid: CPU and GPU together”** option in Performance → Run on. **Text:** the card takes the layers that fit, the CPU the rest (with the right threads for its share) and also **proposes the next tokens** (prompt-lookup speculative decoding) that the card confirms — without changing the answer. **Image and video:** the text encoder and VAE run on the **CPU** and the card keeps only the diffusion model (bigger models and sizes fit); in diffusers each part occupies the card only while it works.

### Not verified
- **Hybrid does not make a token faster by itself:** text generation goes through the layers in sequence, so the gain is **capacity** (models that do not fit on the card alone) and, when text repeats, speculative decoding. Speculative decoding depends on the llama-cpp-python version (without it, only the layer split); I never timed it.
- **The memory sticks were only read in tests with simulated data:** I did not run on Windows (PowerShell) nor on a Linux with `dmidecode`; without permission (the norm on Linux) the reading is empty and only the measured speed shows. The channel count from the slot name (“ChannelA”, “BANK 1”) is an **estimate**.
- **HDD/SSD detection:** Linux (`/sys/block/.../rotational`) and macOS (`diskutil`) follow the documentation; Windows uses `Get-PhysicalDisk` and **was not run**. USB disks, RAID and cloud drives may show as “unknown” (treated as SSD). On this test machine the virtual disk shows as HDD.
- NUMA: `numa=1` (distribute) is the llama.cpp documentation value; I have no multi-node machine to test.
- Large screens: I only checked box sizes and the absence of horizontal scroll in a simulated 3440×1440 Chromium; I did not look at a real monitor.

## [0.30.0] — 2026-11-15

### New — MiniMax H3 Image (image and editing) and the full MiniMax H3
- **MiniMax H3 Image** (`unsloth/MiniMax-H3-Image-GGUF`, 33B): runs in OpenFlow through `sd-cli` with the card's recipe — **6 steps, CFG 1.0, `euler`, `--sigmas minimax-h3-image` and `--rng cpu`** (the last two are not optional), parameter offload to the CPU. It downloads with the model the **image VAE** (from `MiniMaxAI/MiniMax-H3-Image`, saved as `minimax-h3-image-vae.safetensors` so it does not collide with other “diffusion_pytorch_model” files) and the MiniMax H3 **Qwen3-VL-32B encoder** (Q2_K_M for Q2 denoisers, Q4_K_M for the rest). The card recommends `UD-Q4_K_XL` (13.6 GB).
- **Editing with up to 16 references:** the images linked to the node go as `-r` and OpenFlow uses the model's convention: **`<Picture 1>`, `<Picture 2>`…** in the prompt. If your prompt already cites the images it stays as is; otherwise OpenFlow adds ("Edit <Picture 1>. …" with one reference; "Reference images: <Picture 1>, … ." with several). References also count in Generate mode.
- **Sizes in multiples of 32** (each model token covers 32×32 pixels); when editing a single image, the size follows its aspect ratio (the card warns that a square size crops a wide reference).
- **Separate families:** H3 image, video (text + frames) and video-by-references no longer mix by file name (`minimax_h3_image…` used to match the video family).
- The PyPI Python library never recognises H3: it goes straight to `sd-cli` (like the v0.22 video H3). In the Unsloth list (Models → Download more models) **MiniMax H3 Image** shows as "Experimental".

### Not verified
- **I generated no images with H3 Image here** (no GPU, no network, no `sd-cli`; the model is 33B): tests cover family, recipe, companion files, `sd-cli` arguments, the `<Picture N>` convention and sizes. `sd-cli` must be recent (support landed in stable-diffusion.cpp via PR #2324).
- The `<Picture N>` prompt rule when you do not cite them is **my choice from the card**, untested; if results look odd, cite the images in the prompt.
- **The text encoder (≈ 18 GB) is downloaded once per model type:** using H3 image and H3 video takes two copies of it. OpenFlow does not yet share the file between folders.
- The original diffusers pipeline (68 GB, `MiniMaxAI/MiniMax-H3-Image`) and the `MiniMax-H3-Image-PE` prompt expander (a 27B text model) were **not** included; PE can be used as a separate text model.
- Nothing changed in the video H3 besides the family no longer catching image files.

## [0.29.0] — 2026-11-15

### New — GPU Upgrade: faster local models on NVIDIA, AMD and Intel cards (Rust core)
- **Card detection** (`gpu.rs`, core interface 6): NVIDIA through `nvidia-smi`; **AMD and Intel through `/sys/class/drm` (Linux)**, with total/free memory, the kind (**dedicated** or **integrated**), the name from the system's `pci.ids` and the right backend (CUDA, Vulkan, Metal). Before, only NVIDIA existed for OpenFlow: on an AMD/Intel text always fell to the CPU (or, with "GPU" forced, sent everything to the card without checking memory).
- **GPU planner** for text models: how many layers go to the card and **where the attention cache lives**. On **small cards (2–6 GB, laptops)** the cache stays in RAM and VRAM gets only layers — more layers fit, and the maths (card bandwidth × the RAM measured in v0.28) decides when it pays; a **bigger VRAM reserve** on small cards (the system uses some); **flash attention only on NVIDIA/Apple** (compatibility varies on Vulkan); **an integrated GPU is not used** by default (it shares RAM with the CPU, which performs the same) — unless you choose "GPU" in Run on.
- **Planning bug fixed:** the PyPI `llama-cpp-python` is **CPU-only**. With an NVIDIA card and that package, OpenFlow planned as if the card were used (context window from VRAM, only 4 threads, big batches) and the model ran on the CPU with the wrong settings. It now **asks llama.cpp whether GPU support exists** (`llama_supports_gpu_offload`) and, if not, treats the model as a CPU one (v0.28 tuning).
- **sd-cli (image and video):** with a **dedicated** AMD/Intel card, Automatic mode now downloads the **Vulkan** executable (before, only with "GPU" forced).
- **Settings → Performance → “Graphics card (acceleration)”:** lists the cards (memory, dedicated/integrated, backend), shows whether the installed llama.cpp **uses** the card and, if not, **the command to reinstall it with CUDA/Vulkan/Metal** (Copy button; PowerShell on Windows), the sd-cli executable in use and, per text model, how many layers go to the card, whether the cache stays in RAM and the expected speed. New route `GET /api/gpu`.
- Python equivalent without the Rust core; tests check Rust and Python give the **same plan** across 400 combinations.

### Not verified
- **There is no graphics card on this computer:** NVIDIA/AMD/Intel detection and the `/sys/class/drm` reading follow the kernel and `nvidia-smi` documentation but **never ran on a real card**; the planner was tested with simulated values. **Intel Arc:** reading dedicated memory (`lmem_total_bytes`) depends on the driver (i915) and may come empty. **Windows and macOS:** only NVIDIA (Windows) and Apple Silicon (already existed) are detected; AMD/Intel on Windows are not.
- The “≈ tok/s” speeds depend on a **bandwidth table of common cards** (manufacturer specs, not measured); a card outside the table gets no estimate. I timed no model.
- **OpenFlow does not install GPU-enabled llama.cpp by itself:** compiling takes minutes and needs the vendor kit (CUDA Toolkit, Vulkan SDK); it only shows the command. AMD ROCm was not handled — the recommended route is Vulkan.
- `offload_kqv` and flash attention depend on the installed llama-cpp-python accepting them; on an old version loading falls back to the basic options, as it already did.

## [0.28.0] — 2026-11-15

### New — CPU Upgrade: faster local models on AMD/Intel processors (Rust core)
- **OpenFlow now knows your processor** (`cpu.rs`, core interface 5): vendor, name, **performance (P) and efficiency (E) cores** on hybrid CPUs (Intel Alder Lake and newer; AMD Zen c and ARM big.LITTLE on Linux, by frequency), L2/L3 caches, best SIMD (AVX-512 › AVX2 › AVX › NEON) and extensions such as VNNI/AMX.
- **It measures memory speed** (once, about 0.5 s, saved in `cpu_bench.json`): on the CPU every token reads the whole model from RAM, so **tokens/s ≈ bandwidth ÷ model size**. The planner then picks:
  - **generation threads** only up to memory saturation (+1 spare, never beyond the performance cores; one core stays free for the system): more threads only hurt;
  - **prompt-reading threads** = all performance cores (that stage is compute-bound);
  - **smaller batches on weak CPUs** (≤ 4 cores, no AVX2, memory < 15 GB/s or < 6 GB free): batch 128 / micro-batch 64 (fit in the L2 cache), 8-bit attention cache and a context window of up to 4096 — before, a modest PC used batches of 256–512 and the full window.
- **Hybrid CPUs on Linux:** the process is **pinned to the performance cores** (`sched_setaffinity`) so threads do not land on efficiency cores and hold the others back. Turn it off in Settings → Performance or with `OPENFLOW_CPU_PIN=0`.
- **Settings → Performance → “Processor (CPU)”:** shows processor, cores, SIMD, L3, the **memory speed** (“Measure memory” button), **how many GB of model run at 5 and 10 tokens/s** and, for each downloaded text model, the expected speed (**Smooth / Usable / Slow**). New routes `GET /api/cpu` and `POST /api/cpu/bench`.
- Everything has a Python equivalent (without the Rust core it falls back to it, just without the memory measurement); tests check Rust and Python give **exactly** the same plan across 300 combinations.

### Not verified
- Tested **only on this computer** (Linux, Intel Xeon, 4 cores, no E cores): **pinning on a hybrid CPU and P/E core detection have never run on a real hybrid CPU** (the logic is tested with simulated data). **AMD:** vendor detection and caches (cpuid `0x8000001D`) follow the documentation but I did not run on an AMD. **Windows and macOS:** P/E separation is not detected (treated as a regular CPU) and pinning is not done; the memory measurement and the planner apply.
- The “≈ tok/s” speeds are **estimates** (bandwidth × 0.65 ÷ model size), not measured with a real model; the real gain on weak PCs was not timed. Not every MoE model follows the rule (only part of the weights is read per token).
- The prompt-reading estimate (`est_pp`) is rough and not shown in the UI.

## [0.27.0] — 2026-11-15

### New — Library 2.0 (Google-Drive style)
- **Redesigned screen:** a sidebar with the sections (**AI models**, **Generated files**, **Downloads**) and the folder tree; on top, a **search bar**, breadcrumb trail, type/source filters and a **grid/list** toggle. Everything the Library already did stays (use and delete models, download more models, download/delete files, open the source project, downloads with progress and speed).
- **Folders and subfolders** for AI models and for files (separate scopes): **New folder**, rename, move, delete. They are **virtual** (`library.json`): no file moves or is renamed on disk; models stay in `models/` and files inside their projects. Deleting a folder deletes nothing — its contents move up to the parent folder. Repeated names in the same folder are refused.
- **Drag and drop** to organise: items and folders onto a folder in the body, in the sidebar or in the breadcrumb; or the “⋮ → Move to…” menu.
- **Search** across all folders: finds folders and files/models by name (also by project and generating model) and shows **where they are** (“in Animals / Pets”).
- **“Download more models”** opens the former catalogue (recommended, Unsloth, Hugging Face search, download speed, token).
- **In the canvas, a “Library” tab** in the right panel (next to “Project”): browse folders, search and see files from **all projects** (images, videos and sounds only); **drag into the flow** (or use “+”) and OpenFlow copies the file into the project and creates a **Media** node with it, keeping the source model and prompt. New routes: `GET /api/library/items`, `GET/POST/PUT/DELETE /api/library/folders`, `POST /api/library/move`, `POST /api/projects/<id>/assets/import`.

### Not verified
- Tested in Chromium (create/enter/search/move by menu and by drag, delete folder, drag from the canvas tab) and the API; **not** with thousands of files (the list loads everything at once, up to 5000 files) nor on a phone beyond the basic responsive layout.
- Drag and drop depends on the browser: on touch screens use “Move to…”.
- A file lives only in its source project: deleting the project deletes the file, whatever folder it is in. A model deleted outside OpenFlow leaves only a harmless folder record.
- Model folders do not change where OpenFlow looks for the model; it is organisation only.

## [0.26.0] — 2026-11-15

### New — multiple graphics cards (multi-GPU)
- **Every NVIDIA card is listed** (before only the first was) in Settings → Performance → **Graphics cards (GPUs)**, where you check which ones OpenFlow may use (none checked = all).
- **Text (llama.cpp):** the model layers are **split across the checked cards** in proportion to each one's free memory (`tensor_split`), so models larger than a single card's VRAM can run. With a single card checked, the whole model stays on it (`main_gpu`).
- **Image, video and sound** (sd-cli, the out-of-process stable-diffusion.cpp and PyTorch) use **one card at a time — the checked one with the most free memory at that moment** (`CUDA_VISIBLE_DEVICES`/`cuda.set_device`; numbering follows `nvidia-smi`). A `CUDA_VISIBLE_DEVICES` you set yourself still wins.
- Applies from the next model loaded.

### Fixed
- **`flow libs --sd-cli` exited with code 1 even when it worked** (the function was defined twice and the second returned `True`): it now exits 0 on success and 1 on failure.
- The GPU name in System/Performance showed only the first card when there were several.
- An unused variable in the OpenRouter transcription was removed.

### Removed (ASTA legacy that does not apply to OpenFlow)
- **`websearch.py` (766 lines):** ASTA's Chat web search — OpenFlow has no Chat. Only the public-address check was still used, by the "Link" node; it moved to a small module (`safeurl.py`) with the same SSRF protection (localhost, private networks and redirects to them).
- Functions with no use at all: `lang_name`, `png_of`, `_as_list`, `transcriber` and the core's `scan_dir`/`dup_groups` shortcuts; **29 UI icons** for features that do not exist here (worlds, avatars, games, scriber…).

### Not verified
- **I have no multi-GPU machine here:** the split between cards was tested with simulated `nvidia-smi` output and memory; real loading with `tensor_split` on two GPUs, and the card choice in PyTorch and sd-cli, **were not run**. AMD/Intel (Vulkan) and Apple stay as before: no card choice.
- An image/video model is **not** split across cards (only text is); two simultaneous generations do not use different cards either.
- The node bug hunt consisted of running every node type empty and in chains with the Demo provider (all answer with clear messages, no exceptions) and a static sweep (pyflakes/vulture). I found no other node bugs; that does not prove there are none.

## [0.25.0] — 2026-11-15

### Improved — faster downloads that are never lost
- **Several connections per file:** a multi-GB model is now split into ranges (`Range`) downloaded **at the same time** (4 by default) into a pre-allocated file. A single connection is often far below your internet speed; with several, the download tends to use the whole bandwidth. Small files (< 64 MB) and servers without range support still use one connection, with no error.
- **Real resume:** each range's progress is kept in a `.seg` file next to the `.part`; if you close OpenFlow, cancel, or lose power, downloading again **continues where it stopped**. `.part` files from older versions still resume too.
- **A network drop no longer kills the download:** a dropped connection is retried by itself from the byte where it stopped (up to 6 attempts with growing waits). If the CDN's signed address expires mid-download, OpenFlow asks for a new one.
- **Speed and time left:** downloads show "12 MB/s ≈ 4 min" on the Models screen and in the Library's Downloads tab.
- **Setting:** Library → Models → "Download speed" → **connections per download** (1 to 8; default 4). Use 1 if downloads slow down the rest of your internet.
- Applies to everything downloaded from Hugging Face: models, VAEs, text encoders, `mmproj`, the recommended ones and the "Download the compatible version" button.

### Not verified
- Tested against a local HTTP server that honours `Range`: byte-identical file, a connection dropped mid-range, cancel and resume, a server without `Range`, an old `.part`. **I did not measure speed against the real Hugging Face** (no network here): the gain depends on the server limiting each connection and on your internet; if one connection already saturates yours, the gain will be small.
- The Hugging Face credential is sent only to the original server (the CDN carries its signature in the URL); I did not test a gated-repository token end to end.
- Support files and models split into shards still download one file at a time (each file in parallel inside).

## [0.24.0] — 2026-11-15

### Improved — FLUX.3 Image Klein
- **The "base" version has its own repository:** the "Download the compatible version" button (and the warning when opening a repository in search) now points FLUX.3 **base** users to `leejet/flux-3-image-klein-base-GGUF` instead of pushing them to the distilled repository. The button picks the equivalent file by itself (e.g. `flux3-image-klein-base-Q4_K.gguf`).
- **Recipe checked against stable-diffusion.cpp's `docs/models/flux3.md`:** distilled = 16 steps, CFG 1.0, `euler`; **base = 20 steps, CFG 3.5, `euler`** (OpenFlow used 50 steps for base through sd-cli, more than needed — the stable-diffusion.cpp recipe is 20) and `euler` is now passed explicitly for both. Up to 10 reference images (`-r`) still work.
- **Unsloth quantisations (`UD-Q4_K_XL`, `Q5_K_XL`…) now match `leejet`'s K family** (Q4_K, Q5_K…) when choosing the equivalent file; before they fell to "closest by bits", which could be Q4_0.
- The local Hugging Face provider suggestions include `black-forest-labs/flux-3-image-klein-base`; the Unsloth catalogue hint mentions the base repository.

### Not verified
- I generated no images with FLUX.3 here (no GPU/network/sd-cli): the recipe comes from the stable-diffusion.cpp docs and file names listed on Hugging Face; tests cover family, compatible repository, quantisation choice and `sd-cli` arguments.
- The diffusers path (`LocalHF`) still uses 50 steps/guidance 3.5 for base (Black Forest Labs card value); I did not compare with 20 steps.
- FLUX.3 Action (robotics) and the `pup` prompt upsampler are not image models and were not included.

## [0.23.0] — 2026-11-15

### New — Library
- **The "Models" screen became "Library"** (sidebar, Alt+2 shortcut; the old `#/models` address still opens it). Three tabs:
  - **Models:** everything the Models screen did (downloaded — now at the top —, recommended, Unsloth list, Hugging Face search, token).
  - **Generated files:** the images, videos and sounds your nodes produced, **across all projects**, newest first, with thumbnail, model used, size, project (link), **search** (name, project or model), **type** and **source** filters (generated by models / uploaded by you / all), **download** and **delete** (also removes it from the project, with confirmation). New `GET /api/library/files`.
  - **Downloads:** downloads **in progress** (models, support files, LTX-2 components, sd-cli…) with a progress bar, bytes and **cancel**; **recent** ones from this session (done, cancelled or failed with the reason); and the list of **all downloaded models**, newest first, with type, size and quantisation. It refreshes itself (every 1 s while something downloads, every 4 s when idle) and stops when you leave the tab. New `GET /api/library/downloads`.
- A download that fails with an error now shows as **"Failed"** (before, the task ended as "done").

### Not verified
- Tested in Chromium with mocked data (lists, filters, delete, progress and cancel) and the API with real projects and jobs; I did **not** watch a real multi-GB download in the Downloads tab. The "recent" list lives in server memory: it is gone when OpenFlow closes (downloaded models stay in the models list).
- "Generated" files are those not uploaded and not fetched from a link; videos assembled in the Editor and files from code nodes count as generated.

## [0.22.0] — 2026-11-15

### New — MiniMax H3 and LTX-2 / 2.3 / 2.5 (video with audio)
- **MiniMax H3** (`unsloth/MiniMax-H3-GGUF`, text + frames and references variants): OpenFlow now builds the model card recipe through `sd-cli` — **video VAE** and **audio VAE** (from `Comfy-Org/MiniMax-H3`, downloaded with the model), the **Qwen3-VL-32B** text encoder (Q2_K_M for Q2 denoisers, Q4_K_M for the rest), `--cfg-scale 1.0`, `--backend te=cpu`, flash attention and parameter offload. `sd-cli` writes the **WebM with stereo audio** (24 fps, up to 15 s, 960×544 or 544×960) and OpenFlow delivers it as is. New building blocks: `--audio-vae` and `te_on_cpu` in `sdcli`, `generate_video_file`, and `pick` for companion files (the file depends on the model's quantisation). The PyPI Python library never recognises it: it goes straight to `sd-cli`.
- **LTX-2, 2.3 and 2.5** (`unsloth/LTX-2*-GGUF`): run through **diffusers (≥ 0.43)** — the GGUF becomes the transformer (`LTX2VideoTransformer3DModel.from_single_file`) and the rest comes from Lightricks' diffusers repository. Text → video or start image → video, **MP4 with audio**, 24 fps, 8k+1 frames, sides multiple of 32; "distilled" uses 8 steps and CFG 1, "dev" 30 steps and CFG 3.
- **The components (≈ 25 GB) are never downloaded silently:** when missing, the node shows the error with a **"Download the LTX-2 components"** button (`POST /api/media/ltx2-components`).
- Unsloth catalogue: MiniMax H3 and LTX-2/2.3/2.5 move from "Not yet" to **"Experimental"**. `pip install "openflow[media]"` now includes `gguf` and `av`.

### Not verified / limits
- **I generated nothing with these models here** (no GPU, no network, no sd-cli): tests cover recognition, companion-file choice, `sd-cli` arguments, the button flow and error messages with diffusers/Hugging Face mocked. That is why they are labelled "Experimental".
- **LTX-2.3:** I found no diffusers repository of its own; I use the LTX-2.5 one as base (**unconfirmed guess**). `Lightricks/LTX-2.5-Diffusers` is gated: accept the licence and set your Hugging Face token.
- LTX-2 through diffusers is heavy (lots of VRAM/RAM) and the Unsloth GGUF layout may not match the base repository config; if so the node shows the diffusers error.
- MiniMax H3: no duration control beyond the 15 s cap, and the references variant runs as text → video.

## [0.21.0] — 2026-11-15

### New — Unsloth image and video models (Hugging Face)
- **Models screen → "Unsloth models":** the list of GGUF **image** and **video** models of the `unsloth` organization, for the chosen tab (Image/Video), each with its real state in OpenFlow — **"Works"** (OpenFlow downloads the VAE, text encoder and tokenizer with it), **"Use another repository"** or **"Not yet"** (with the reason). "See quantizations" opens the repository in the search.
- **Working:** Qwen-Image 2.1, 2.1 Turbo, 2512 and original; Qwen-Image-Edit 2511/2509; Z-Image and Z-Image Turbo; FLUX.2 klein 4B/9B (and base) and FLUX.2 dev; FLUX.1 schnell, dev and Kontext dev; Wan2.2 TI2V 5B (video) — and the **new MOSS-Image (SFT and Base, 5.1B)**.
- **MOSS-Image:** follows the Unsloth card recipe: `sd-cli` (master-975 or newer) with the **VAE and tokenizer** from `unsloth/MOSS-Image-SFT-FP8` and **Qwen3.5-9B Q8_0** (≈ 9.5 GB) as the text encoder, 50 steps and CFG 3. Everything is downloaded with the model; the VAE and tokenizer are saved under their own names (`moss-image-vae.safetensors`, `moss-image-tokenizer.json`) so they do not collide with other `diffusion_pytorch_model` files. The PyPI Python library does not know MOSS-Image: it goes straight to `sd-cli`.
- Unsloth's **FLUX.3 Image Klein** shows as "Use another repository" → `leejet/flux-3-image-klein-GGUF` (v0.18).
- The Qwen3.5-9B encoder and MOSS-Image's VAE/tokenizer do not show up as "models" in the installed list.

### Fixed
- **FLUX.1 (schnell, dev, Kontext, Krea) used the default CFG 7:** on distilled FLUX that ruins the image. Now the recipe is CFG 1 and 28 steps (schnell: 4 steps).

### Not verified yet / not included
- I did not download or generate with any of these models here (no network/GPU/sd-cli); the tests cover recognition, support files (names and repositories checked on Hugging Face), command building and the catalog. The FLUX.1 recipe (CFG 1, 28 steps) is what I recommend from the stable-diffusion.cpp docs and was not tested.
- **Still without a recipe (shown as "Not yet", with the reason):** MiniMax H3 (needs a video and an audio VAE, special sd-cli options and delivers stereo audio, which OpenFlow does not assemble yet), LTX-2, 2.3 and 2.5 (the cards only describe ComfyUI) and ERNIE-Image (I did not confirm stable-diffusion.cpp support).

## [0.20.0] — 2026-11-15

### Fixed
- **The FLUX.3 error (and its button) was hidden behind the "Generate a flow with AI" panel:** in your screenshot the message "stable-diffusion.cpp does not recognise the format of this file…" ends exactly where the panel covers the node — the v0.18 button was under it and you only saw the text. Now, after a run with an error, the canvas **moves the node above the panel** (if the node is taller than the screen it shows its end, which is where the error and buttons are), without touching nodes that are not covered.
- **The error now resolves with one click:** the button went from "Open … in Models" to **"Download and use flux3-image-klein-Q4_K.gguf (3.3 GB)"**. It picks the **equivalent** of the quantization you were using in the compatible repository (Q4_K_M → Q4_K; Q5_K_M → Q5_K; Q8_0 → Q8_0), shows the size before downloading, downloads with progress (and any missing VAE/encoder), **starts using the new file on this node** (and as the default image model) and says "Run the node again". If the file is already downloaded, the button becomes "Use …". "Open … in Models" stays beside it, for those who want another quantization.

### Not verified yet
- I did not really download the `leejet` file nor generate with it (no network/model/sd-cli here); the tests simulate Hugging Face and check the equivalent quantization choice, the download, the node's model switch and the panel. That the `leejet` file loads with your `sd-cli` and the VAE/encoder you already have is still untested by me.

## [0.19.0] — 2026-11-15

### Fixed (Text node linked to Image and Video nodes)
- **You could not see which text the Image/Video node would use:** with a Text node linked to the «Prompt» input, the node's field stayed empty (with the "Describe the image…" hint) and only the number "1" beside the port showed there was a link. Now the linked text appears under the field ("Linked text · Text: “A forest at dawn…”"), **follows what you type** in the Text node, and the node's field says "Optional: add details to the linked text (it comes first)" — which reflects what the engine does (linked text first, then the field's). It works for any node that delivers text (AI text, Transcribe…): if it has not run yet, the notice says "Waiting for node … to run".
- **"Needs a prompt: connect a text node" with the text node already connected:** when the linked node was empty, the error told you to connect a node that was already connected. Now it says which node is empty ("The text linked to the node is empty: Text (empty text)…") and, on Video, reminds you that you can connect a start image.
- **The error action button stuck out of the node:** the long label ("Open leejet/flux-3-image-klein-GGUF in Models") stayed on one line and went past the node's right edge. Now it wraps and fits inside the node.

### Not verified yet
- I checked the flow in the browser with the Demo provider (connect by dragging, run, edit the text, delete the node); I could not reproduce with the real models and cloud providers. If something still looks off with Text linked to Image/Video, describe what happened (or send the node's error).

## [0.18.0] — 2026-11-14

### Fixed
- **"sd-cli failed (code 1): … get sd version from file failed: '' … new_sd_ctx_t failed" with FLUX.3 Klein** (now with the `sd-cli` built and running): the file `flux-3-image-klein-Q4_K_M.gguf` from `unsloth/flux-3-image-klein-GGUF` is the **diffusers/ComfyUI** version — its tensors have the names of the original Black Forest Labs checkpoint, which stable-diffusion.cpp does not recognise (the VAE and text encoder loaded fine; the model is what failed). The repository stable-diffusion.cpp uses is **`leejet/flux-3-image-klein-GGUF`** (converted by it, e.g. `flux3-image-klein-Q4_K.gguf`).
  - The node error no longer dumps the raw `sd-cli` log: it now explains what happened, says which repository to download and has the button **"Open leejet/flux-3-image-klein-GGUF in Models"**, which opens the Models tab already on that repository. The VAE and text encoder you already have work; only the model file changes.
  - In the model search, opening a FLUX.3 repository that is not `leejet/…` shows a warning (with a button to open the right one) before you download several GB of a file that will not load.
- Other models that `sd-cli` rejects with "get sd version from file failed" also get a clear message (no log) saying the file is probably for ComfyUI/diffusers and that `leejet`'s GGUFs are the reference.

### Not verified yet
- I did not generate with the real FLUX.3 (no model and no `sd-cli` here). The `leejet/flux-3-image-klein-GGUF` repository is confirmed on Hugging Face as "converted with stable-diffusion.cpp", but I did not test whether its file loads with the `sd-cli` and the VAE/encoder OpenFlow downloads. The reference-repository list only has FLUX.3; other families get in when one is confirmed.

## [0.17.0] — 2026-11-14

### Fixed
- **"… missing: git. Run flow update … or install with: sudo apt install git build-essential…" on the Image node (FLUX.3):** the error repeated itself (the same sentence twice, with ".." in the middle) and only sent you to the terminal. Now it is **one message** that names what is missing and has the button **"Install what is missing and build sd-cli"**: it installs git/compiler with the system package manager (asks for the **administrator password**: in the terminal where OpenFlow is open with `sudo` or, if OpenFlow was opened without a terminal in a graphical session, in a **system password window** with `pkexec`), builds `sd-cli` (a few minutes) and the node works again — with nothing to run in the terminal. The button is your consent; `OPENFLOW_AUTO_TOOLS=0` only turns off `flow update`'s automatic install.
- **`flow update`/`flow libs`: the build tools now come BEFORE the «local» libraries.** Before, `llama-cpp-python` (which builds native code) was installed first, failed without a compiler and, once the compiler was in, was not redone.
- The tool installer chooses how to ask for the password: `sudo` with a terminal, `pkexec` (window) in a graphical session without a terminal, `sudo -n` otherwise; the two `apt` commands (`update` and `install`) ask for the password once with `pkexec`, and the step can be cancelled.

### Not verified yet
- I did not open the `pkexec` password window nor run `sudo apt-get install` for real here (no terminal/sudo/graphical environment): the tests cover the method choice, the commands, the button and the retry after installing.

## [0.16.0] — 2026-11-14

### New
- **`flow update` installs what is missing to build by itself and then installs/updates `sd-cli`.** Before, when git or a compiler was missing ("To build sd-cli here is missing: git. Install with: sudo apt install git build-essential"), you had to install it by hand and try again. Now `flow update`:
  1. checks **git** and a **C/C++ compiler**; if missing, installs them with the system package manager (`apt-get` → `git`/`build-essential`; `dnf`/`yum`, `zypper`, `pacman`, `apk` too) using `sudo` — **it asks for your password in the terminal** (as administrator it does not use sudo; without a terminal it uses `sudo -n` and only goes on if sudo does not ask for a password). It installs only what is missing;
  2. builds the GitHub stable-diffusion-cpp-python (v0.13) now with the tools;
  3. **installs `sd-cli`** if you have models that need it (FLUX.3, Qwen-Image…) and never downloaded it — ready-made, or built here when no prebuilt executable runs on your Linux (v0.15) — and **updates** it when there is a new version.
- On macOS and Windows there is no installation without windows: `flow update` shows the command (`xcode-select --install`…). With no recognised package manager or no `sudo`, it shows what to install. **`OPENFLOW_AUTO_TOOLS=0`** turns the automatic install off; `flow update --core` does not touch this.
- The node's "git is missing" error now tells you to run `flow update`, which installs what is missing by itself.

### Changed
- The "has a compiler" check is now the same in `flow update` and in the `sd-cli` build (it needs a **C++** compiler: `c++`, `g++` or `clang++`).

### Not verified yet
- I did not run `sudo apt-get install` for real here (no sudo/terminal in the environment): the tests simulate the package managers and check the commands, the use of sudo (with and without a terminal, as administrator), the failures and the whole `flow update` flow.

## [0.15.0] — 2026-11-14

### Fixed
- **"The prebuilt stable-diffusion.cpp executables (master-1104-5dcfa79) need glibc 2.43 or newer and this Linux has 2.39":** the Release only ships Linux packages built on Ubuntu 26.04, which your Linux (glibc 2.39) cannot run — before, OpenFlow gave up and told you to build by hand. Now, when no prebuilt executable runs on this Linux, OpenFlow **builds `sd-cli` by itself**: downloads the source (`git clone` of stable-diffusion.cpp), configures and builds with cmake (if there is no cmake it installs the pip one, with ninja) and tests the result **before** replacing what is installed. It shows progress in the node ("Building: [ 42%] …") and honours cancel. It builds for the GPU (CUDA or Vulkan) only if its tools exist (`nvcc`, `glslc`); otherwise it builds for CPU and says so. It takes a few minutes, once; later generations use the built executable.
- It needs **git** and a **C/C++ compiler**; if missing, the error names what is missing and the command to install it (e.g. `sudo apt install git build-essential`). Turn the automatic build off with `OPENFLOW_SD_CLI_BUILD=0` (back to the glibc message). It also applies when the tested packages fail to run for another reason.

### Not verified yet
- I did not actually build stable-diffusion.cpp here (the build takes minutes and needs network and a compiler): the tests simulate git and cmake and check the steps, the flags (CUDA only with `nvcc`), the copied libraries, the test before replacing and the removal of the source. If the build fails on your machine, the node error carries the compiler's last lines; send them to me.

## [0.14.0] — 2026-11-14

### Fixed
- **"The installed stable-diffusion.cpp does not recognise the model flux-3-image-klein… and closed (code -11)":** FLUX.3 Klein is newer than the PyPI library (0.4.7) and should go straight to the prebuilt `sd-cli`. When OpenFlow **could not** get that executable (no network, glibc too old…), it fell back to the library, which loaded the whole model, closed with "code -11" and showed a message telling you to use the very button that had just failed — hiding the real reason. Now, without an `sd-cli`, OpenFlow **does not even load the library** and the node error says **why the download failed** (e.g. "needs glibc 2.43 and this Linux has 2.39") and what to do: `flow update` (builds the newest stable-diffusion.cpp from GitHub), point `OPENFLOW_SD_CLI` to your own sd-cli, or use another model. The "Download the ready executable" button is only offered when trying again can help (network failure, not glibc).
- **With the GitHub library FLUX.3 tries the library again:** OpenFlow assumed the library never knows FLUX.3. After a `flow update` (which now builds the GitHub one, v0.13) or with a version above 0.4.7, it tries the library itself first instead of always using `sd-cli`.

### Not verified yet
- I did not reproduce "code -11" with the real model (no FLUX.3 and no library here); the tests cover the path choice, the reason shown and the detection of the GitHub library.

## [0.13.0] — 2026-11-14

### Changed
- **`flow update` now always updates all libraries to the newest versions.** Before, the GitHub stable-diffusion.cpp was only rebuilt if OpenFlow had flagged an unrecognised model or you had a diffusion GGUF downloaded, the downloaded `sd-cli` was never updated, and a library that failed to build made pip give up on the whole group. Now:
  - the optional libraries (`docs`, `media`, `local`) are updated with `pip --upgrade --upgrade-strategy eager` (their dependencies too);
  - if the group fails, **each library is tried on its own**: one that does not build (e.g. `llama-cpp-python`) does not stop the others from updating; the warning says which one failed;
  - the **GitHub stable-diffusion-cpp-python** is rebuilt whenever there is a new commit (`OPENFLOW_SD_LATEST=always` in `flow update`; `=never` still turns it off), without rebuilding if already at the newest commit;
  - the downloaded **`sd-cli`** follows the newest Release (only downloads if the version changed);
  - at the end you get a summary: "Updated: package before → after" or "All libraries were already at the newest versions".
- `flow update --core` still updates only OpenFlow and the Python tools. The app's automatic launch update (`flow`) stays in "auto" mode, without rebuilding stable-diffusion.cpp needlessly.

### Not verified yet
- I did not run `flow update` against real internet and pip here (tests simulate pip and GitHub); the GitHub stable-diffusion.cpp needs git and a C/C++ compiler to rebuild.

## [0.12.0] — 2026-11-14

### Fixed
- **The Image node failed with "sd-cli failed … version `GLIBC_2.43' not found":** the prebuilt stable-diffusion.cpp package OpenFlow downloaded was built on a newer glibc (Ubuntu 26.04 = 2.43) than your Linux has. Now, on Linux, OpenFlow **picks the package your glibc can run** (newest compatible Ubuntu to oldest), **tests the package before replacing** what is installed (before, it replaced first and, if the test failed, the broken executable stayed in place and was used for the next generations) and, if a package does not run, tries the next one.
- An sd-cli that OpenFlow downloaded and that cannot run because of glibc is **deleted** and, in the same generation, the compatible package is downloaded and the request is redone by itself. Unfinished installs (without the `VERSION` file) are no longer used: yours, already broken, is downloaded again on the next generation.
- When no package fits (glibc older than all of them), the error says which glibc they need, which one you have and what to do (build with `flow libs` or point `OPENFLOW_SD_CLI`).

### Not verified yet
- I did not test with the real stable-diffusion.cpp Release (no GitHub access here): the choice uses the Ubuntu version in the package name (20.04, 22.04, 24.04, 26.04 → glibc 2.31, 2.35, 2.39, 2.43). If the Release has no package your glibc can run, you need to build it.

## [0.11.0] — 2026-11-14

### Fixed
- **Searching for models was slow:** OpenFlow asked Hugging Face **one query at a time** (a search for "unsloth" in "Other" meant 12 queued queries, each waiting up to 20 s if the Hub was slow). Now the queries all run **at the same time**, each waits at most 12 s, and the same search (or a repository's file list) is served from memory for 90 s. Network errors are never cached: the next attempt asks again, and if only some queries fail the others' results still show.
- **An old result overwriting the new one:** with back-to-back searches, the slow answer of an old search could arrive later and replace the new list (in Models and in the Canvas model panel); the same applied to opening several repositories in a row. Now only the latest answer counts.
- **Feedback while loading:** the list shows "Searching Hugging Face for “term”…" and "Reading the quantizations of …", and the Models search also runs by itself ~0.5 s after you stop typing (3+ letters); Enter searches immediately.

### Not verified yet
- I did not measure the gain against the real Hugging Face (no access here); the tests prove the queries are parallel, the cache works and failures are not kept.

## [0.10.0] — 2026-11-14

### Fixed
- **Image edits barely changed anything:** with a loose request like "make the title bigger, keep the rest", local models that edit by reference (FLUX.3/FLUX.2 klein, Kontext, Qwen-Image-Edit…) returned almost the same image (in your example the title grew only ~6%). In **Edit** mode, when the request is not expanded by the text model, OpenFlow now sends it as a clear editing instruction ("Edit the provided reference image. Apply exactly this change: … make the change clearly visible and keep everything else the same"). When generating, the text goes as-is.
- **Warning when an edit had no effect:** if the result is almost identical to the input image, the node shows a warning saying what to do (describe the change in more detail, configure a text model to expand the request, or regenerate with another seed).

### Not verified yet
- I could not reproduce the edit with the real model (no FLUX.3 and no GPU here): the instruction framing follows the format edit models expect, but the gain only shows in your use. FLUX.3 Klein works best with the text model configured (Settings → Model), which expands the request into a full caption.

## [0.9.0] — 2026-11-14

### New
- **Local Wan (Alibaba) in GGUF:** **Wan2.2 T2V A14B** (text → video), **Wan2.2 I2V A14B** (image → video) and **Wan2.1 I2V 14B** (image → video), besides the Wan2.1 T2V and Wan2.2 TI2V 5B that already existed. Video at 480p (832×480 or 480×832), up to 81 frames (≈ 5 s at 16 fps).
- The A14B models use **two models** (low noise + high noise): pick the `…LowNoise…gguf` and OpenFlow downloads the `…HighNoise…gguf` **of the same quantization** by itself, together with the Wan2.1 VAE and the UMT5-XXL text encoder. Wan2.1 I2V also downloads the CLIP vision. These support files do not show up in the model list.
- Image → video models require the Video node's «Start image» (the message says what to do); the A14B text → video warns that it ignored a connected image.
- High-noise parameters (`high_noise_cfg_scale`, `high_noise_sample_steps`, `high_noise_sample_method`) and `clip_vision_path` also work through `sd-cli`.

### Not verified yet
- No Wan model was actually generated here (no model, no GPU); repositories and files were checked on Hugging Face and the tests cover recognition, support files and command building.
- Starting steps and CFG (20 steps low noise, 10 high noise, CFG 3.5) come from the stable-diffusion.cpp docs; adjust them in Extra parameters if the result is off. The A14B models need a lot of RAM/VRAM and time.

## [0.8.0] — 2026-11-14

### New
- **Qwen (Alibaba Cloud)** cloud provider: images (Qwen-Image, generation and **editing** with up to 3 references through Qwen-Image-Edit) and **Wan videos** (text → video and image → video). Model Studio key; international endpoint by default (switch to the China one in Settings → Media).
- **Krea** cloud provider: give the model as `provider/model` (`krea/krea-3`, `bfl/flux-1-dev`…).
- **Bria (FIBO)** cloud provider: generation with one reference image.
- **Local (GGUF) models** with their support files downloaded alongside: **Qwen-Image-Edit** (2509/2511; VAE, Qwen2.5-VL encoder and the `mmproj` vision projector), **Krea 2** (Raw and Turbo), **FLUX.1 Krea [dev]** and **Bria FIBO 2.0** (Dev and Edit Turbo), with each variant's steps and CFG.
- The new providers retry with only the essentials if the service rejects an optional parameter, and show the service's full message.

### Not verified yet
- The three cloud providers follow the public docs (submit + poll the task) but **were not tested with a real key**; tests use simulated responses.
- Local Krea 2 and FIBO 2.0 depend on the installed stable-diffusion.cpp recognising the architecture; if it does not, the node says so. Qwen-Image-Edit uses the library's `llm_vision_path`.
- Local Wan 2.2 A14B (two models, high/low noise) is not in this release; Wan 2.2 TI2V 5B and Wan 2.1 work as before, and cloud Wan comes through Qwen.
- Licences: Krea 2 (Krea 2 Community License) and FIBO 2.0 (CC BY-NC 4.0 on the GGUFs) restrict commercial use.

## [0.7.0] — 2026-11-14

### Fixed
- **Thumbnails (and any image) came out vertical** when a single portrait photo was wired as a reference (or came from the style folder) in **Generate** mode: the local model inherited the photo's aspect ratio and ignored the chosen resolution (16:9 became vertical). Now Generate always uses the node's resolution; only **Edit** mode with one image keeps its proportions (the long side follows the chosen resolution). Applies to the Python library and to `sd-cli`.

## [0.6.0] — 2026-11-14

### New
- **More resolutions to generate and edit images:** 25+ options grouped as Square, Landscape and Portrait — from 512×512 to 2048×2048, 1920×1080, 1080×1920, 2560×1080, 832×1216, 1344×768 and more (big ones are tagged «heavy»). They work in both Generate and Edit mode.
- Local (GGUF) models used to generate at most 1024 px on the long side; the limit is now **2048 px** (`OPENFLOW_MAX_SIDE`, 512 to 4096). Large resolutions need a lot of RAM/VRAM and time, especially on CPU. Cloud providers still adjust to the sizes their API accepts.
- Not verified: real generation at the large resolutions (no model here).

## [0.5.0] — 2026-11-14

### Fixed
- **«get sd version from file failed» still showed in the terminal with FLUX.3.** FLUX.3 models (which the PyPI library never recognized) now go **straight to `sd-cli`**, without even trying to load in the library; and that refusal message is no longer echoed to the terminal (OpenFlow already handles the refusal itself). `OPENFLOW_SD_INPROC=1` forces the library.
- Not verified: real generation with FLUX.3 Klein (no model or `sd-cli` here); if `sd-cli` refuses the model, the node shows its output.

## [0.4.0] — 2026-11-14

### New
- **Settings → Performance → Run on:** *Automatic* (uses the graphics card if there is one), *CPU only* or *GPU*. It applies to text models (llama.cpp), PyTorch media models and `sd-cli`: OpenFlow downloads the right executable by itself (cuda12 on NVIDIA, vulkan on AMD/Intel, cpu) and swaps it when you change the option. `OPENFLOW_SD_BACKEND` still wins.

### Limits
- The `stable-diffusion-cpp-python` library uses whatever it was compiled with; the option controls `sd-cli`, llama.cpp and PyTorch. Not verified with a real GPU (none here): tested with simulated detection.

## [0.3.0] — 2026-11-14

### Fixed
- **FLUX.3 Image Klein (and other models the library refuses) still showed «get sd version from file failed» in the terminal on every generation.** The message came from the library, which tried to load the whole model before OpenFlow fell back to `sd-cli`. After the first refusal the model is now remembered (`sd_unsupported.txt` in the data folder) and later generations go **straight to `sd-cli`**, without reloading or repeating the error. `flow libs --sd-latest` clears the record (a newer library may recognize the model).

### Not verified
- I did not have the node's error message or `sd-cli`'s result on your computer: if `sd-cli` also refuses FLUX.3 Klein (its version may not support that format yet), the node will show its output. Tested only with simulated logic; no model and no `sd-cli` download here.

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
