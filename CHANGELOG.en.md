# Changelog

Format: `## [version] — date`. Each version lists what changed for users and, honestly, what was **not** verified. [Português](CHANGELOG.md)

## [0.91.0] — 2026-11-24

### New — `flow` is now a Rust program (first stage of the Rust backend)
- **A single binary** (`rust/`, ~1 MB, standard library + `serde_json` and `include_dir`): HTTP/1.1 server with SSE, **the web interface embedded** (no folder of files), the same `Host`/`Origin` check as the Python server (anti DNS-rebinding/CSRF), `Range`, streamed uploads and the basic terminal (`flow`, `--host/--port/--home/--no-browser`, `version`). A busy port moves to the next one, as before.
- **Already answered by Rust itself**, with the same files on disk and the same answers as Python: settings (`GET/PUT /api/settings`, export, import, reset a section) with the defaults, the forced «shape», local-only mode, the computer-protection limit, memory and UI normalized and the Hugging Face token kept out of what reaches the browser; and attachments (`POST/DELETE /api/uploads`). `tests/test_rust_parity_v091.py` runs **the same inputs through Python and `flow dev …` and compares the JSON** (hundreds of saved-file × change combinations) — that is how a rounding difference (`round(5.55, 1)`) showed up and was fixed.
- **Every other route is still Python** and is **forwarded byte by byte** (large uploads and SSE included) to the **Python worker**: `flow` starts it on demand on a private `127.0.0.1` port, it accepts nothing from outside (Rust checks `Host`/`Origin` first) and it **exits with `flow`, even if `flow` is killed**. Python no longer listens on the port you open.
- **Installation:** `install.sh` and `install.ps1` download `flow` from the Release (one file per platform, **checked by SHA-256**; static on Linux, runs on any distribution) and put it where the shim was; the Python environment is still created, as the worker. **Without the binary** (no network, a platform with no build, `OPENFLOW_FLOW_RUST=no`, a version different from Python's) `flow` **stays the Python one of before** — nothing stops working. On Windows a `flow.exe` in use is renamed (not deleted) on update.
- **Auto-update as before** (every 24 h, `--no-update` skips): Rust asks the installer's Python, which runs the official installer, and `flow` reopens already updated.
- The Release now publishes `flow-linux-x86_64`, `flow-linux-aarch64`, `flow-macos-aarch64`, `flow-macos-x86_64` and `flow-windows-x86_64.exe` (besides the core and the installers). CI gained the «flow in Rust» job (cargo test, parity and end-to-end server on the 3 systems) and the real installers now exercise the binary.

### What is NOT Rust yet (next versions)
Projects and canvas (`store`, `schema`, routes), the execution engine and the nodes, the providers (sd-cli, llama.cpp, HTTP, Python-local), the library and Hugging Face (search, downloads, Q2–Q8 tiers, support files), background jobs and SSE, hardware/GPU/guard and the terminal beyond the basics (`libs`, `models`, `update`, `doctor`… go to Python). **The request «replace the whole Python backend with Rust» is not finished**: about 22 thousand lines of Python (and 22 thousand of tests) against 3 thousand of Rust. Features that only exist as Python libraries (diffusers/LTX-2, VoxCPM2, Whisper, PyTorch/TensorFlow) will stay in an optional Python worker even after the port.

### Not verified
- **No real Windows, macOS or ARM machine**: the binary was built and tested on Linux; Windows, macOS and the per-platform releases depend on GitHub's CI (result in the PR).
- Performance (the server uses one thread per connection) and Rust's memory use under many simultaneous SSE streams.
- Updating an old (Python) install to the new (Rust) one on a real machine.

## [0.90.0] — 2026-11-19

### Bugs when installing on Windows and macOS — what was searched
- **The installers** (`install.ps1` and `install.sh`) read line by line and **actually run**: `install.ps1` in PowerShell 7 (the parts that can be proven outside Windows) and, on GitHub, **on real Windows and macOS**, installing from this folder and reinstalling.
- **The whole test suite on Windows and macOS** (Python 3.9 and 3.13): the first time in a long while — see the first «Fixed» item.

### Fixed
- **GitHub CI had not been running since v0.10:** `.github/workflows/ci.yml` was invalid YAML (a step name with «numpy: os» without quotes), so GitHub created no job at all: the Windows, macOS and Linux tests and the installer tests **never ran** in the last ~80 versions (only a zero-second «failed» showed up). Fixed, and a test now reads the workflows as YAML.
- **Windows — the installer did not find Python on many machines:** when the only Python was `python` (the Microsoft Store one, conda, Chocolatey/Scoop, or one installed without the `py` launcher), PowerShell returned the string «python» instead of a one-element list and the installer ran the command «p» («not recognized»). People with `py` never saw the error.
- **Windows — the `flow` command broke with an accent in the user name** (`C:\Users\João\…`): the `flow.cmd` shim was written in ASCII with the full path, and «ã» became «?». It now points to the program by a path relative to the file itself (no user name inside).
- **Windows — the installer rewrote the user PATH already «expanded»:** entries like `%USERPROFILE%\bin` became the literal path (and the value type, REG_EXPAND_SZ, became REG_SZ). It now reads the raw value from the registry and only appends the `flow` folder.
- **Windows — the Rust core (.dll) was never updated on an update:** `flow native setup` already loaded the old .dll when checking the version and, on Windows, a loaded .dll cannot be overwritten (access denied), so OpenFlow kept the old core. The old one is now renamed (Windows allows that) and the new one goes in; the leftover is deleted at the next launch.
- **Windows — clear error when recreating the environment:** if the old environment is in use (OpenFlow open), the installer now says so instead of a technical error.
- **Tests that only failed outside Linux** (so they never showed up): the voxcpm Python 3.10 check knocked down 21 tests on Python 3.9; macOS paths (`/var` → `/private/var`) and Windows paths (short names «RUNNER~1», backslashes, `/proc`); a missing ffmpeg in the project templates; a test that really downloaded FLUX.3's support files; the 3D viewer reading backslash paths; tests that swapped `os.name` (Windows' `pathlib` rejects that).

### Not verified yet
- **I used no real computer:** what is known about Windows and macOS comes from GitHub's CI (installing from the folder and reinstalling passed; the test results are in the PR) and from PowerShell 7 on Linux. Windows with a Python **without** `py` and a user name with an accent were proven only by PowerShell tests, not by such a machine.
- The core update (loaded .dll) was simulated (overwrite refused + rename), not run with a loaded .dll on Windows.
- Installing Python through `winget`, Homebrew and the macOS Command Line Tools are not exercised by the CI (the runner's Python is kept).

## [0.89.0] — 2026-11-18

### New — Q2, Q3, Q4, Q6 and Q8 tiers of text encoders and VAEs
- **Library → «Text encoders and VAEs»:** lists the support files of the downloaded image and video models (VAE, Qwen/Mistral LLM, T5/UMT5, CLIP) with each one's tier, the tiers already in the folder and the ones you can still get. Pick the tier and the mode — **download the ready one** (when the file's repository has GGUF in that tier: the unsloth LLM encoders and the GGUF T5/UMT5), **create** it from the downloaded file, or **automatic** (downloads the ready one; without it, creates).
- **Creating a tier:** GGUF LLM encoder → `llama_model_quantize` (llama.cpp); T5/UMT5/CLIP and VAE (safetensors or GGUF) → `sd-cli -M convert`. The created tier is named after the source file + the tier (`t5xxl_fp8_e4m3fn-Q4_K.gguf`) and only appears complete. OpenFlow reports the resulting size.
- **Using it:** in an image or video node (GGUF models), the new **«Support files tier»** field loads the text encoder and the VAE in the chosen tier if it is already in the folder (otherwise it uses the file as it is and says how to install). The node's «Download the support files» button then downloads the encoder already in the chosen tier (instead of downloading the default and compressing later).
- **Terminal:** `flow models support --tier Q4` and `flow models install --tier Q4` (with `--how auto|download|create`) get the tier of every downloaded encoder and VAE; `flow models quant` now lists those files too and `--name FILE --tier Q4` creates their tier.
- API: `GET /api/models/support/files` and `POST /api/models/support/tier` («Support file (tier)» task in the Downloads tab).

### Fixed
- **«Automatic» picked the support file by alphabetical order:** with more than one file of the same encoder in the folder (say, the default Q4_K_M and a created Q2), the first one alphabetically won — and «Q2» sorts before «Q4». «Automatic» now uses the family's default file, then the original, and only then Q8 → Q2.
- **Creating a tier of a GGUF text encoder that lives in the image folder used the wrong program** (sd-cli, which cannot read an LLM): it now goes to llama.cpp.

### Honest limits (please read)
- **Almost nothing in a VAE is quantizable:** ggml only quantizes tensors whose first dimension is a multiple of the block size (32; 256 for the «K» tiers), and a VAE's 3×3 convolutions are not. The «quantized» file barely shrinks (OpenFlow reports the size) and VAE quality is sensitive; there is no ready VAE tier to download.
- The sd-cli and llama.cpp commands follow their documentation and code, but **were not run against the real programs and files** (Hugging Face blocked, no GPU): the tests simulate the programs and prove what OpenFlow asks for and how it picks files. Whether sd.cpp loads a T5/CLIP/VAE GGUF created by it, and whether llama.cpp quantizes a newer-architecture encoder (e.g. Qwen3-VL), depends on the installed version.
- The vision projector (mmproj), CLIP vision, the audio VAE and the tokenizer are not quantized (vision is precision-sensitive and they are small). LTX-2 (diffusers) does not use the field.

## [0.88.0] — 2026-11-18

### Bug hunt 7 — what was searched
- **Colour contrast (WCAG AA, 4.5:1)** with axe-core — the rule earlier hunts left out — in both themes (dark and light), in every accent colour of Appearance, on the projects, canvas (empty, executed, with a node in error, node menu), model search, Library (3 tabs) and Settings (all tabs) screens, plus notices (normal, error, ok).
- **Keyboard focus:** tabbing through the whole screen (projects, canvas, Library, Settings) and checking that each element shows where the focus went.
- **Concurrency during a run:** deleting the project, saving an empty layout, cancelling, two runs and renaming **while** a run is in progress (the server survived them all).
- The file names of 40 quantization variants, tier conversion (`with_weight_type`) over 14 file types × 8 requests, the `flow` commands, the `sh` (dash) installer and compatibility with Python 3.9–3.13.

### Fixed
- **The «dimmed» text of the interface had too little contrast:** the colour used in hints, small labels, the version, «Saved», palette group titles and Settings descriptions had a contrast ratio of 3.0 to 3.9 (the minimum is 4.5) — hard to read, especially in the light theme. It is now above 4.5 on every background, in both themes; axe-core finds no case left on the scanned screens.
- **Text on the accent colour unreadable in four of the six colours:** OpenFlow picked black or white text with a threshold that left white on blue, pink, red and violet at a contrast of 3.2 to 4.2. It now picks whichever of black or white has MORE contrast (buttons, tabs and notices in the accent colour).
- **The palette's «Search nodes» field showed no keyboard focus** (no outline or other sign): a line now marks the field when active; the project name at the top also got a clearer outline while being edited.
- **The Video node sent «(reference image N)» in the prompt:** citing `@photo` in a video prompt sent the model «photo (reference image 1)» (and, with two mentions, «(reference image 2)» — an image that never arrives, since video uses a single one). The text now carries only the nickname; the first one cited is still the start image.

### Not verified yet
- No real model was downloaded or run (Hugging Face blocked, no GPU here). Contrast was measured by axe-core (automatic) on the screens and states listed; screens and states that were not scanned may have cases.
- There is no real screen reader in the verification.

## [0.87.0] — 2026-11-18

### Removed
- **The «Editor» node (video timeline) is gone.** To gather video, voice and sound in one final file use **Final video**; to join clips, **Join clips**; for images, **Images to video** — all of them already existed. The «Full scene» project template now ends in a **Final video** (it used to end in the Editor).
- **The «PyTorch/TensorFlow model» node is gone**, together with the «Own models» tab of the model search, the `/api/tool/*` endpoints and the Keras/TorchScript model loader (`modelrun`). What stays of PyTorch/TensorFlow is the card in Settings, `flow frameworks` and `flow torch` (local models keep using PyTorch).
- **Old projects open normally:** nodes that no longer exist leave the canvas and the screen tells how many; the files they generated (including the Editor's videos) **stay in the project and the Library**. Only the node drawing is lost (the timeline built inside the Editor and the other node's model path).

### Bug hunt 6 — what was searched
- The image, video, sound and voice nodes run one by one, the command line (`doctor`, `models`, `frameworks`, `torch`, `native`, `folder`, `libs`, `update`), the interface at every screen size and the file names of every quantization tier (Q2, Q3, Q4, Q6, Q8 and the IQ, UD, MXFP4, TQ variants).

### Fixed
- **Utility nodes could not be run one by one:** Filters and colour, Resize, Final video, Join clips etc. showed no status dot («out of date»/«up to date»), no «Run this node» button and no «Generate again» in the menu — only the AI nodes had them. Every node the server runs now shows all three.
- **Ternary quants (TQ1_0, TQ2_0) were not recognised** from the file name: they showed up with no tier. They now count as Q2 (and the «edit only copied the image» warning catches them too).
- **Long notices vanished after 3 seconds:** the on-screen notice now stays 6 seconds when the message is over 90 characters.
- **The PyTorch/TensorFlow card text** said TensorFlow is «only needed for the PyTorch/TensorFlow model node»; it now says OpenFlow does not need it.

### Not verified yet
- No real model was downloaded or run (Hugging Face blocked, no GPU here); ffmpeg for the «Final video» was tested with Demo-mode files.
- The hunt does not exhaust the program: it covered the paths described above.

## [0.86.0] — 2026-11-18

### Editing bugs — what was searched
- The **editing path of generated images and videos** in each family: FLUX.3 Image Klein, Qwen-Image 2.1 and Qwen-Image-Edit (2509/2511), FLUX.2/Kontext, MiniMax H3 (image and video), LTX-2/2.3/2.5 and Wan. For each one: what OpenFlow sends (prompt, references, size, load and run parameters) compared with the documentation and code of stable-diffusion.cpp and diffusers.
- The screenshot case (FLUX.3 Klein Q2 GGUF, node on «Edit» with the previous node's image, result identical to the input): the arguments sent to sd-cli are right (`-r` with the image, no `--strength`, 16 steps and CFG 1 recipe); what OpenFlow **cannot** fix is a Q2 model, which tends to just copy the reference. The warning now says so.

### Fixed
- **Qwen-Image-Edit-2511 edited badly:** stable-diffusion.cpp requires `--qwen-image-zero-cond-t` for this model («without it editing quality drops a lot») and OpenFlow never sent it. Every «Qwen-Image-Edit-2511» file now loads with it, through the library (`qwen_image_zero_cond_t`) and through sd-cli. If the installed library is too old for the option, OpenFlow uses sd-cli (or explains how to update) instead of silently editing wrong. It can be turned off in the node's «extra» field: `{"load": {"qwen_image_zero_cond_t": false}}`.
- **LTX-2 «distilled» (2.5 included) ran with the wrong noise schedule:** the model was trained with 8 fixed noise levels (`DISTILLED_SIGMA_VALUES`) and OpenFlow only asked for «8 steps», which diffusers turns into a linear schedule — blurry video that followed the start image poorly. The «distilled» file now gets its own schedule (if you set another step count in «extra», yours wins). «dev» is unchanged.
- **Stretched start image:** when animating a generated image (square, say) into a 16:9 video, the image was **distorted** to fit the frame (LTX-2, MiniMax H3, Wan, and video and image → image on local Hugging Face). It is now scaled to cover the frame and the excess is cropped from the center; in multi-reference edits on local Hugging Face each reference keeps its own proportion.
- **A video wired into a Video node's «Start image» began in the MIDDLE of it:** a new video from another one continued nothing. The Video node now uses the **last frame** of the wired (or `@`-mentioned) video — what continues it. Image nodes keep using the middle frame.
- **MiniMax H3 Image got the edit request duplicated, with markers it does not understand:** OpenFlow wrote «Edit <Picture 1>. Edit the provided reference image… @name (reference image 1)». The markers now become `<Picture N>` and the prompt opens once with «Edit <Picture 1>.».
- **The «result almost identical to the input» warning now names the likeliest cause:** when the model file is Q2 or Q3 it says those tiers tend to just copy the image, suggests Q4 or higher, and advises avoiding «slightly» and «a bit» in the request.

### Not verified yet
- No real model was downloaded or run (Hugging Face blocked) and there is no GPU here: tests use **simulated** stable-diffusion.cpp and diffusers and prove what OpenFlow sends, not image or video quality. That Qwen-Image-Edit-2511 and LTX-2.5 distilled get better with the fixes comes from their documentation, not from a real generation.
- A video's last frame is read with ffmpeg (tested here with a short synthetic video).
- The screenshot case was not reproduced with the real model: the likely cause (Q2) is a hypothesis, not a confirmation.

## [0.85.0] — 2026-11-18

### Bug hunt 5 — what was searched
- **The model downloader**, with a local server that breaks on purpose: no `Range` support, `chunked` response without a size, a connection dropping mid-way (with and without a size), `429` at the start, redirects, a half, a complete, an other-version and a legacy `.part` — with 1 and 4 connections.
- **Accessibility** of the main screens with axe-core (rules about names, labels and headings; colour contrast was not evaluated): projects, editor, Library (3 tabs), the 5 Settings tabs, the welcome, the open model search and a selected node, in Portuguese and English.
- Background jobs and what lists them; the full path of the Q2–Q8 tiers (no new problems beyond the ones below).

### Fixed
- **A download whose chunked response was cut mid-way crashed:** when the server (or a proxy) sends the file as `Transfer-Encoding: chunked` and the connection drops, Python raises `IncompleteRead`, which the downloader did not treat as a network drop: the download failed instead of resuming. It now resumes (with one and with several connections).
- **A leftover of ANOTHER version of the file was returned as "complete":** if the `.part` ended up bigger than the new file, the server answered `416` and the downloader accepted the `.part` as done — a corrupt model, bigger than the original. It now checks the size the server reports and, if it does not match, discards the leftover and downloads again.
- **An error, login or network-portal page (hotel Wi-Fi) became a "model":** downloaded with status 200, it was saved as `.gguf` and only failed on load, with an error unrelated to the download. Every downloaded `.gguf` is now checked ("GGUF" at the start) before getting its final name; if it is not, the file is deleted and the error says what probably happened. The good parts of a split model stay for the next download to continue.
- **"Create tier" and the "Own model" download did not show in the Downloads tab** (nor in the counter next to the search) and **did not stop** disk cleaning or moving the Library folder while they were writing to disk. They now show up, with title and messages, and count as a download in progress.
- **Accessibility (axe-core):** the logo link had a name that did not start with the visible text (now "OpenFlow — home" from its content, with the "F" hidden from screen readers); the project editor had no page heading (now there is a screen-reader-only `h1`); the headings of the Settings cards, the Library, the empty project list and the palette groups skipped a level (now level 2); the "custom colour" field only had a `title` (it got a name); each project card's link had a label that did not contain the visible text (the name now comes from the content).

### Not verified yet
- No real model was downloaded or run (Hugging Face blocked); the downloader was tested with a local server, not Hugging Face's CDN. There is no real screen reader in the check: axe-core is automatic and only finds part of the problems.
- The hunt does not exhaust the program: it covered the paths above.

## [0.84.0] — 2026-11-18

### Bug hunt 4 — what was searched
- **The full path of the Q2, Q3, Q4, Q6 and Q8 tiers:** choosing and downloading (GGUF and original format), creating (text, image, video), using on load (image, video, editing) and the screens of each step; plus hostile Dubbing-with-cloned-voice scenarios (lines with the same start, zero duration, outside the audio, 300 lines, huge text, Unicode, silence), the options of **every list and range field** of **every node** (what the screen offers against what the server accepts), the command line, corrupt media, 1018 malformed API calls and 160 random graphs.
- The API, the engine, Dubbing and the nodes' options held up to everything; what turned up is below.

### Fixed
- **`flow update` took the graphics card away from PyTorch:** whoever installed the graphics-card PyTorch with `flow torch --install` ("2.15.0+cu130", "+rocm…", "+xpu") had it replaced, on the next update, by the PyPI build — which on Windows is the **CPU-only** one. `flow libs`/`flow update` now keep a graphics-card-index PyTorch and torchvision (and say how to update them: `flow torch --install`). Also, at the end of an install/update on Windows with an NVIDIA card and the "default" PyTorch, OpenFlow warns and shows the command.
- **The original format's Q… tiers had no explanation in the model search** (the panel had an old copy of the texts, with only fp32/fp16/bf16): it now uses the full texts.
- **"Quantization on load" on LTX-2 was silently ignored** (it runs through diffusers, not stable-diffusion.cpp), and so was the tier chosen on the modular pipeline (FLUX.3): the node now says so and how to get another tier (its GGUF file).
- **The "Model" field of the "PyTorch/TensorFlow model" node got "internal error"** with a too-long name or a folder without permission (like `/proc`): the node's status now always answers, and the node's file checks never raise.
- **`flow torch --index 'a b;rm -rf /'` showed a command to copy with that text loose inside:** the index is now validated (letters, digits, `.`, `-`, `/`, no `..`) on every path, including `OPENFLOW_TORCH_INDEX`.
- **`flow models quant --name x`**, with a file that is not downloaded, said "only text, image and video models": it now says it could not find the file and how to see the list.

### Not verified yet
- No real model was downloaded or run (Hugging Face blocked), nothing ran on a graphics card, and `flow torch --install`/`flow update` were tested with a simulated pip.
- The hunt does not exhaust the program: it covered the paths above.

## [0.83.0] — 2026-11-17

### Bug hunt 3 — what was searched
- **The 0.80–0.82 code** (cloned-voice dubbing, Q2–Q8 tiers, PyTorch/TensorFlow, the own-model node), read with an eye to breaking it, plus: 1018 malformed API calls (every route, the new ones included), 160 random graphs in the engine, 4000 random inputs to the new pure functions and a layout audit of the new screens at 3 screen sizes × 2 languages.
- The API, the engine and the pure functions held up to everything; the bugs are below, all in the new features.

### Fixed
- **Creating a tier of a TEXT model could hang forever.** llama.cpp's output (one line per tensor, hundreds of KB) went to a pipe nobody read: the buffer filled up and the process stopped. It now goes to a temporary file (and the error shows the end of the log). The test hangs on the old code.
- **"Quantization on load" recompressed upwards:** asking for Q8 on a Q5 file (or Q1, IQ…) said "Compressing to Q8" and sent the request to stable-diffusion.cpp. It now only applies to a tier SMALLER than the file's, also for types that are not one of the five tiers.
- **"Look in other repositories" offered another model:** whoever searched for "Z-Image" got "Z-Image-Turbo". The repository's base name must now be equal.
- **The "PyTorch/TensorFlow model" node scanned whole folders:** pointing to the home folder by mistake walked the whole disk; and the "is the node stale?" check (several times a second) repeated the scan. The search now stops at 4000 files and 6 levels (no hidden, cache or linked folders) and the model's stamp is valid for 3 s.
- **A huge or broken image in the own-model node** gave "Unexpected error" (decompression bomb) or an error without a reason: it now says the image is too big, or corrupt/incomplete.
- **Downloading a model for the "PyTorch/TensorFlow model" node broke the repository as an image model:** it wrote the "fp32" mark (looked like a complete model) and, after downloading the repository normally, the old marker still refused it. The framework download now only writes its own marker, and both ways coexist.
- **The PyTorch/TensorFlow card loaded TensorFlow just because someone opened Settings** (≈ 400 MB of RAM and several seconds, on computers that already struggle): it now only loads through the "Check TensorFlow" button (or if it was already loaded).
- **UI — the model search panel went past the screen edge on tablets** (the open sidebar pushed the `92vw` out: "Download" buttons cut off); the panel now fits the width left. **The long command in the PyTorch card** pushed the "Copy" button off the card on phones: it now wraps (also the graphics-card one).
- **UI — "Create tier"/download with another one running** showed the server's JSON in the notice; it now says "A download is already running" (in the three places: model search, Library and Settings).
- **Dubbing without audio:** the warning that the voice could not be cloned now reminds that a silent video will not do. The "Own models" search has its own help text (it used to talk about sound and voice).

### Not verified yet
- No real model was downloaded or run (Hugging Face blocked), and nothing ran on a graphics card. The layout audit is scripted (Chromium), not a person with a screen reader; contrast and colours were not evaluated.
- The hunt does not exhaust the program: it covered the paths above.

## [0.82.0] — 2026-11-17

### Full PyTorch and TensorFlow support
- **PyTorch — knowing whether it uses your graphics card, and installing the right one.** pip installs the system's "default" PyTorch: on Windows that is the **CPU-only** build (people with an NVIDIA card end up without GPU unknowingly), and AMD and Intel need their own index. OpenFlow now reads what is installed (version, CUDA/ROCm/CPU, cards seen through `cuda`, `mps` and `xpu`), compares it with the computer's cards and says, in Portuguese and English, whether the GPU is in use — and if not, why and the right command (`--index-url …/cu130`, `rocm7.1`, `xpu`, `cpu`). In **Settings → Performance** ("PyTorch and TensorFlow" card, with a copy-command button) and in the terminal: `flow frameworks`, `flow torch` (shows the command) and `flow torch --install` (installs, trying the indexes from newest to oldest; `OPENFLOW_TORCH_INDEX` forces one). `flow doctor` shows the versions.
- **PyTorch — Intel cards (XPU).** The "xpu" device (Arc and integrated, with the XPU index package) joins the device choice after CUDA/ROCm and MPS, and the card's cache is cleared when a model is unloaded (MPS too).
- **TensorFlow — install and diagnostics.** `flow libs --extras tensorflow` (**not** part of "all": it is heavy), version, Keras, backend and cards; warns that on native Windows TensorFlow does not use the GPU (WSL2 only), about `[and-cuda]` on Linux, and that TensorFlow does not exist for Python 3.14 yet.
- **New "PyTorch/TensorFlow model" node (Image group):** applies to an image your own **image → image** model — upscale, denoise, colorize, change the style. Runs **Keras** (`.keras`, full `.h5`), **SavedModel** (folder), **torch.export** (`.pt2`) and **TorchScript** (`.pt`, `.pth`). Settings: framework, input and output value range (0–1, 0–255, −1–1, output auto-detected), dimension order, channels, **maximum longest side** and **tiles** (`tile`, with 16 px of margin that hides the seam) for low-memory computers, size multiple of N. A fixed size in the model → the image is resized (with a warning). The model stays loaded between runs and reloads if the file changes; replacing the file makes the node stale. The "Model" field takes a path, a folder, `owner/name` (already downloaded) or `owner/name::file`, and below it the node says what it found (format, framework, missing library).
- **Safety:** Keras `Lambda` layers are refused (`safe_mode`), and a `.pt` that is a model "pickle" is **not** loaded (it would run code from the file): the error says how to export to `torch.export`/TorchScript.
- **Finding and downloading:** the model search bar gained the **"Own models"** type (image → image); **every search result shows its framework** (PyTorch, TensorFlow, JAX, ONNX, GGUF); opening a repository you choose the framework and **only that framework's file is downloaded** (without the other formats' weights); once downloaded, "Use" puts the model in the selected node. Models downloaded this way do not show up as image/sound/voice models (and if picked by mistake, the error explains).
- **A bug that only appears with both together (and would take OpenFlow down):** with PyTorch and TensorFlow installed, importing TensorFlow BEFORE `torch.export` kills the whole process ("LLVM ERROR: inconsistency in registered CommandLine options"). Every TensorFlow import goes through `frameworks.import_tensorflow()`, which loads PyTorch (and `torch.export`/`torch._dynamo`) first; a test runs this in a separate process.

### Not verified yet
- **With real libraries, CPU only:** the tests also ran with the **real PyTorch 2.15 and TensorFlow 2.21** (in a separate environment, no graphics card): a 2× upscaler in TorchScript, `torch.export` (fixed and dynamic size), Keras (`.keras`, fixed and free size) and SavedModel, tiles identical to the whole image, refusal of Lambda, of pickles and of two-input models. **It never ran on a graphics card** (CUDA, ROCm, XPU, MPS): the diagnostics and `flow torch --install` were tested with simulations. The PyTorch index names (`cu130`, `cu128`, `cu126`, `rocm7.1`, `rocm7.0`, `rocm6.4`, `xpu`, `cpu`) are from my own knowledge — PyTorch's site could not be reached from here; that is why `--install` tries several and `--index`/`OPENFLOW_TORCH_INDEX` let you pick another.
- No third-party model (ESRGAN etc.) was downloaded or run: Hugging Face is blocked where this was developed. The node only serves ONE image → ONE image models; classification, text models and multi-input models do not run in it. TorchScript is marked deprecated by PyTorch (it still runs): prefer `.pt2`.
- What already used PyTorch (image, video, sound, voice, transcription) stays the same: TensorFlow is not the engine of those models (transformers 5 removed TensorFlow).

## [0.81.0] — 2026-11-17

### Q2, Q3, Q4, Q6 and Q8 for every model
The five quantization tiers (≈ 2, 3, 4, 6 and 8 bits per weight: fewer bits = smaller file and memory, lower quality) now exist for **every** OpenFlow model, in three ways — choose, create and use:
- **Choose (GGUF — text, image, video):** a repository's list shows the five tiers at a glance, each with the recommended file (Q4_K_M before Q4_0…), its size, a "Recommended" mark (the largest tier that fits 60 % of your RAM) and, dimmed, the ones the repository does NOT have. For the missing ones, the **"Look in other repositories"** button finds other repositories of the same model that have those tiers (it only searches when you ask).
- **Choose (original format — diffusers/transformers):** the precision choice gained Q8, Q6, Q4, Q3 and Q2 next to fp32/fp16/bf16. They download the same files as fp16 and **compress the weights on load** (bitsandbytes on an NVIDIA GPU; otherwise optimum-quanto, which runs on any device, even the CPU): the download is fp16-sized, but memory drops (the list says how much: Q4 ≈ 29 % of fp16). If even fp16 does not fit your RAM, the recommended one becomes the largest tier that fits. The original format only has 8, 4 and 2 bits: **Q6 uses 8 bits and Q3 uses 4** (the node says so). Applies to image and video models; voice, sound, transcription and 3D run uncompressed (and say so). Install the library with `flow libs --extras quant`.
- **Create the missing tier:** from an already downloaded GGUF, OpenFlow generates the Q2, Q3, Q4, Q6 or Q8 (Library → model menu → "Create tier Q…", or `flow models quant --name FILE.gguf --tier Q4`): image and video through `sd-cli -M convert --type …`, text through llama.cpp's `llama_model_quantize` (in a separate process, cancellable). The source is the file with the MOST bits you have; it refuses files that are already that small, files split into parts and a disk without space; the file only gets its final name when complete.
- **Use on the fly (image and video GGUF):** the new node field **"Quantization on load"** (writes `extra.quant`: Q8, Q6, Q4, Q3 or Q2) uses any file at a tier smaller than its own — stable-diffusion.cpp recompresses the weights on load (`wtype` / `--type`). Asking for a tier larger than the file's does nothing (and says so).
- The downloaded models list (Library and API) now carries each file's `bits` and `tier`; nothing that existed changes.

### Not verified yet
- **None of this ran with the real programs and models** (Hugging Face is blocked where this was developed and there is no sd-cli, llama.cpp, optimum-quanto or bitsandbytes here): the tests use simulations with the libraries' real signatures (sd-cli's `--type`/`convert` and the library's `wtype` were checked against the stable-diffusion.cpp 0.4.7 source; `PipelineQuantizationConfig` against diffusers 0.43). I do not know each tier's quality on each model, nor whether a specific model survives Q2/Q3 without ruining the image.
- Recompressing a file that is already compressed (Q8 → Q4) loses more than compressing the F16: that is why the source is always the one with the most bits. `convert` of a GGUF that holds only the diffusion model (no VAE/text) uses the file as `-m`; if an sd-cli version requires `--diffusion-model`, creation fails with its message.
- diffusers' `QuantoConfig` is marked deprecated (removed in 1.0) and transformers' changes signature between versions: if compression on load fails on a new version, the error shows the cause and the model is not loaded uncompressed (it would blow the memory of exactly whoever chose the tier).

## [0.80.0] — 2026-11-17

### Dubbing with openbmb/VoxCPM2 — each person's voice, automatically
- **Dubbing clones the voice of whoever speaks in the original, without you connecting anything.** Before, dubbing with VoxCPM2 used the same voice (or the node's description) for every line; cloning a voice needed a Voice node with a reference audio for each character. Now, when the voice model clones (VoxCPM2) and no Voice nodes are connected, the node: (1) tells who speaks each stretch of the original audio/video (the same voice separation as Transcript); (2) takes a sample of each person's voice from the original (their longest lines, up to ≈ 12 s); (3) dubs each line with the cloned voice of whoever said it — several speakers, several voices, on one model loaded once.
- **Same language, faithful cloning:** with no translation ("Keep the language") and a transcribed speech, the sample's transcript goes along and VoxCPM2 continues the sample's speech (the model's most faithful mode). Translating into another language uses the timbre (controllable cloning); if you wrote "What the voice is like", that description guides the style while keeping the timbre.
- **Two new settings on the node:** "Clone the voice of whoever speaks in the original" (on by default; turn it off for the old dubbing) and "How many voices in the original" (0 = detect; giving the number is more reliable). Connected Voice nodes still win over the automatic cloning; a model that does not clone (the other voice models) behaves as before, with no new warning.
- **Clear warnings:** which voices were cloned and each sample's length, who speaks too little in the original (under 1.5 s: keeps the node's voice), and when cloning was not possible (no ffmpeg/numpy, not enough speech, silence). Telling several speakers apart only works when the speech has real timing (a timed transcription or SRT/VTT subtitles); with an untimed script the dub uses one voice, sampled from the stretches with sound.

### Not verified yet
- **The real VoxCPM2 was never run** (Hugging Face is blocked where this was developed): the tests use a simulated `voxcpm` library and synthetic voices (deep and high). I do not know whether the cloned voice sounds like the original, nor whether speaker separation works on real people (similar voices, overlapping speech and background music confuse it; the cloned sample carries the original's noise along).
- Faithful cloning (sample + transcript) across different languages is deliberately not used: same language only.

## [0.79.0] — 2026-11-17

### Bug hunt 2 — what was searched
- **Broken media:** truncated, empty, wrongly-named and binary-garbage images and videos fed to every video/audio/image node and to export; odd image sizes (1×1, odd dimensions, 4000×50, RGBA, palette, grey+alpha) in export and "Images to video".
- The engine held up to almost everything; what turned up is below.

### Fixed
- **Export / "Images to video" hung forever on a truncated or corrupt image:** ffmpeg, looping the still (`-loop 1`), never gives up on a frame that will not decode and spun until the user killed the program. The image is now checked first and the node stops at once with "Image «…» is corrupt or incomplete (ffmpeg could not read it). Upload the file again." (the message is in Portuguese in the app, English in the terminal's translated layer where applicable). Valid images and GIFs are unchanged (a GIF still uses its first frame).

### Not verified yet
- No real model was downloaded or run (Hugging Face is blocked where this was developed).
- The hunt does not exhaust the program: it covered the paths above. Without ffmpeg installed the image check is skipped (the node already needs ffmpeg to export).

## [0.78.0] — 2026-11-17

### Bug hunt — what was searched
- **API:** 974 calls with malformed bodies and queries (broken JSON, wrong types, 200 KB of text, ids with `..` and with 300 characters) on every route that touches neither the network nor the user's disk; **160 random node graphs** (cycles, self-links, ports that do not exist) in the engine; the upload and static-file routes with odd headers; every `flow` command; the interface at 3 screen sizes (phone, tablet, desktop) and 2 languages, with all screens, the 5 Settings tabs and **all 63 node types** on the canvas (console errors, sideways scrolling, unnamed fields, clipped text, content overflowing the node border); and the model install flow.
- The engine and the API withstood almost everything (no hang, no exception in the 160 graphs); what showed up is below.

### Fixed
- **Installing models — a full disk only showed up in the middle of the download:** the local Hugging Face download did not check free space; a full disk only gave «No space left on device» after minutes of wasted network. It now checks **beforehand**, discounting what is already in the cache, and says how much is missing («Not enough disk space for «…»: 4.0 GB left to download and 2.0 GB free in …; free space, choose a smaller precision or change the models folder»).
- **Installing models — «Cancel» waited for the file to finish:** cancellation was only read between one file and the next, so cancelling a 5 GB `.safetensors` waited for it to end. It now takes effect **in the middle** of the file (the partial is kept and the next download continues from it; the cancelled model is not marked as downloaded).
- **Interface — fields without a name (accessibility):** the label of almost every field sat next to the field with no link to it: screen readers read «combo box» without saying which, and clicking the label did not go to the field. There were 13 fields in Settings (providers, performance, computer protection, memory, language…) and the canvas node fields. The label is now linked to the field (`for`/`id`) and, for button groups, names the group; the copy button for the GPU command got a name.
- **Interface — phone:** small buttons and the segmented-selector buttons were under 28 px; they are now at least 34 px on narrow screens.
- **API — a huge project id gave a 500 error** («File name too long»); it is now «does not exist». **Invalid or negative Content-Length and chunked bodies (`Transfer-Encoding: chunked`)** were read as «empty body» and the request passed as valid (creating a blank project, for instance); they now give 400 and 411.
- **English terminal with a Portuguese snippet:** the reason the Rust core is inactive («library not built…», «turned off by OPENFLOW_NO_NATIVE», «interface version differs…») came out in Portuguese; it now follows the terminal language.

### Not yet verified
- No real model was downloaded or run (Hugging Face is blocked where this was developed): the space check and cancelling in the middle of a file were tested with a simulated `huggingface_hub`. Cancelling mid-file depends on the installed hub version using the `file_download.tqdm` progress bar; if it does not, cancellation still takes effect only between files, as before.
- The accessibility and layout audit was done by script (Chromium), not with a real screen reader; colors and contrast were not evaluated.
- The hunt does not exhaust the program: it covered the paths described above.

## [0.77.0] — 2026-11-17

### Fixed — freezes while generating and editing on weak machines
Four causes made the node (or the whole computer) look frozen; all were handled.
- **The «Stop» button was mute for minutes:** cancellation was only read between one image and the next, and on a weak machine one image takes many minutes. Cancellation is now read **at every diffusion step** (local Hugging Face image and video), and the node shows progress: «Generating image: step 12 of 28 — about 3min10s left» (in image → image, it counts only the steps that actually run). With several images, «Generating image 2 of 3».
- **The whole computer stuttered:** torch used every CPU core. It now leaves **at least one core free** for the interface and the system (balanced mode: all but one; light: half; max: all, as before). Applies to local image, video, voice, sound and transcription.
- **Silence during long steps:** loading a big model takes minutes with no event at all, and so does the end of generation (decoding the image on the CPU, stable-diffusion.cpp). Every few seconds the node now says «Loading «model» into memory… 1min20s» and «Still generating… 45s», with the elapsed time; the notice stops when the step ends. If you cancel during loading, the cancellation takes effect right after it.
- **A model bigger than the RAM froze the whole machine:** a model that does not fit in free RAM goes to the disk's virtual memory and the whole computer stops responding for minutes. Now: above 1× the free RAM, the node **warns** («This model takes 20.0 GB and there is only 16.0 GB of free RAM… use a smaller precision or a GGUF»); above 2×, it **refuses before loading**, with the same explanation. To try anyway (slowly, using the disk), set `OPENFLOW_ALLOW_SWAP=1`. A model entirely on the graphics card does not count RAM.

### Not yet verified
- **No real model was run** (Hugging Face is blocked where this was developed): fake pipelines with the real diffusers signature call the callback at every step, and torch is simulated. Whether the computer really feels smoother, and how much slower generation gets with one core less, depends on your machine.
- Per-step cancellation and progress apply to diffusers pipelines that have `callback_on_step_end` in their signature (most: FLUX, Qwen-Image, SD3, SDXL, Z-Image, LTX, Wan). FLUX.3 (modular pipeline), Python stable-diffusion.cpp and sd-cli show only the periodic notice: Python stable-diffusion.cpp still cannot be interrupted in the middle of an image.
- The 1× and 2× RAM limits are simple rules on the size of the model files; a model that fits in RAM but changes type on loading (e.g. fp16 → bf16) may take more than its file size.

## [0.76.0] — 2026-11-17

### Fixed — «AudioVAE checkpoint not found» in Dubbing (and Voice) with openbmb/VoxCPM2
- **The cause, in the image:** *«Unexpected error: AudioVAE checkpoint not found. Expected either …/audiovae.safetensors or …/audiovae.pth»*. VoxCPM2 needs its **audio codec** (`audiovae.pth`, ≈ 377 MB), and the download's file selector **dropped** it when the repository has `.safetensors`. v0.71 fixed the download, but whoever downloaded the model earlier (the selector shows «openbmb/VoxCPM2 · fp16») was left with an incomplete folder, and the library failed with the raw error.
- **OpenFlow now notices the gap and completes it by itself:** before loading VoxCPM, if the model folder has neither `audiovae.pth` nor `audiovae.safetensors`, it downloads **only that file** from the same repository you already chose, with a notice on the node («Model … was downloaded without the audio codec…: downloading just that file now»), once. Without a network, the error says what to do («Download the model again in Settings → Media (only that file is missing) or put audiovae.pth in the folder …») instead of «Unexpected error».
- **VoxCPM load errors with a useful message:** any library failure while loading the model now becomes «VoxCPM could not load «…»: <the error>. If the model was downloaded incomplete, download it again in Settings → Media.»
- This applies to the Voice node and to Dubbing (same path), with the model on the node itself or on the connected voices.

### Not yet verified
- **No real download was made** (Hugging Face is blocked where this was developed): the fix was tested with the network and the library simulated (the Dubbing from the image, with «Alternate between voices», «Replace with the dub» and «Speed up speech», completes the download and generates the dub). Whether `audiovae.pth` really downloads, and whether VoxCPM2 then loads, depends on the network and the library on your machine.
- Only VoxCPM had an essential file dropped by the selector; if another local model shows up with an incomplete folder, the error is still the one from its library.

## [0.75.0] — 2026-11-17

### Tested — Voice and Dubbing with openbmb/VoxCPM2, node chains, GGUF models and audio models
- **Voice and Dubbing with VoxCPM2, end to end** (`tests/test_voxcpm_nodes_v075.py`, 20 tests): the node, the engine and the local provider are the real ones; only the `voxcpm` library (and torch/download) is simulated, with a 48 kHz voice whose length follows the text. Voice: plain speech, voice designed from a description (with and without the project's Style Prompt, and the hand-written «(…)»), controllable cloning and faithful cloning with an audio **and a video** reference, long text in pieces, speed, cache (only what changed is redone, without reloading the model) and the error messages (model not downloaded, library missing, out of memory). Dubbing: the node's own voice, **one character with a designed voice and another cloned from a reference**, audio and video sources, the «replace» and «keep quiet underneath» mixes, «speed up to fit», alternate assignment, long lines and per-character cache. No defect in OpenFlow showed up on that path.
- **Node chains** (`tests/test_chains_v075.py`): generate → filter → write on the image → **edit** → resize → animate → look → reframe → export, and the text and audio chain (refine → voice → effect → sound effect → mix). Checked: the order, the cache (nothing runs again; change one link and it and its dependents run, and only them), the «out of date» marks, running just one target, and a failure in the middle (only what depends on it stops running). The 5 project templates run from start to finish and stay up to date.
- **GGUF models** (`tests/test_gguf_matrix_v075.py`): 15 typical file names (FLUX.1 dev/schnell/Kontext/Krea, FLUX.2 dev/klein 4B/9B, Qwen-Image, Edit, Lightning and 2.1, Z-Image Turbo and base) are recognised, load with the right companion files, generate with the family's steps and CFG and edit the way each one does (several references × image → image), with the library simulated.
- **Audio models** (`tests/test_audio_models_matrix_v075.py`): each suggested voice (Bark, MMS-TTS, VoxCPM2, Orpheus, CSM), each suggested sound (MusicGen, AudioLDM, Stable Audio) and each suggested transcription (Whisper) takes the right path; 46 real model names are classified as voice, sound, transcription or image/video.

### Fixed — what the tests found
- **MusicLDM was not recognised as a sound model:** v0.68 made it run, but the type filter did not know it; it showed up in the image and video lists and the wrong-type protection did not apply to it.
- **Image models vanished from the lists because of the organisation name:** `yuewen/…` or `tango-labs/…` were taken for music models (YuE, Tango). Now only the model name counts («m-a-p/YuE-…», «declare-lab/tango-2» are still music).
- **Qwen-Image and Qwen-Image-Edit (GGUF) could pick Qwen-Image 2.1's VAE** when both are in the same folder (the pattern found «qwen…image…vae»): 2.1 has a different latent space and the images came out ruined. The pattern now excludes 2.1's VAE.
- **Qwen-Image Lightning (GGUF)** ran with CFG 2.5 and the usual steps; it now uses 8 steps (or 4 when the name says «4steps») and CFG 1.

### Not yet verified
- **No real model was run** (Hugging Face is blocked where this was developed): VoxCPM2, GGUF and the audio models were exercised with simulated libraries, which proves that the right request reaches the right place, not the quality of the voice, image or sound.
- The new suite runs in about 1 minute; the Hugging Face local image and video nodes (diffusers) remain covered by the v0.74 tests.

## [0.74.0] — 2026-11-17

### Tested — every node and model compatibility
- **Every node, with every option and hard inputs:** a sweep of **1,233 runs** ran the 58 nodes that execute (engine + ffmpeg + Demo provider) with every option of every field, extreme values in numeric fields and three input sets: ordinary (640×360), hard (a 333×517 portrait JPEG; a **321×241 video, odd dimensions, no audio**) and tiny (a 17×9 image). Result: **no ffmpeg error, exception, empty file or unreadable video**; every failure was a validation message that says what to do («Type the text to search», «connect a 3D Skeleton node», «the video has no audio»). This became a permanent test (`tests/test_every_node_v074.py`: defaults on 3 input sets, every option on the hard input, numeric extremes on the nodes that edit media, and the fields are read straight from the code, so a new field enters the test by itself).
- **Image and video, generate and edit:** the Image node was exercised in both modes, with 0 to 5 references (PNG, JPEG, WebP, GIF, with transparency, 17×9, 2600×1500, and a video as a reference), 4 sizes and 1–2 images, on 4 providers (Demo and three fakes: accepts references, only edits with a reference, accepts 1 reference); the Video node, with and without a start image, 3 aspect ratios and 1–30 s. Checked: how many references reach the provider (and the warning when they are cut), the style in the prompt, the Edit-mode-without-image errors.
- **Model compatibility:** each local image family (SD/SDXL turbo, SD3, FLUX.1 schnell/dev, FLUX Kontext, FLUX.2 dev and klein, Z-Image, Qwen-Image, Qwen-Image-Edit/Plus) and video family (LTX text→video and image→video) runs in both modes with a fake pipeline that has the **real diffusers 0.43 signature**; odd reference images (1×1, 4000×12, CMYK, with transparency) keep valid sizes; the suggested catalog is checked (model type, steps and guidance, reference limit), and the GGUF family table is checked (regexes, sd-cli options, companion files).

### Fixed — what the tests found
- **Z-Image-Turbo came out blurry:** the generic «turbo» rule gave 2 steps; the model asks for 9 (8 evaluations) and guidance 0 (the GGUF path already used 8). «Base» Z-Image now uses 28 steps and guidance 4.
- **Oversaturated SD3/SD3.5:** guidance 7 (the old default) is too high; now 28 steps and guidance 4.5, and «turbo» 4 steps with no guidance. **SDXL-Lightning** reads 2, 4 or 8 steps from the model name (before: always 2).
- **LTX-Video image → video failed:** the repository ships the text → video pipeline and a start image raised an error; OpenFlow now builds LTX's image → video pipeline from the same weights (no reload). LTX also receives the real frame rate (24; it assumed 25 and motion came out ~4% slower).
- **Subtitles with a very negative «Advance/delay»** said «No speech found to subtitle» when speech existed; the message now says every cue would fall before the start and when the speech ends.

### Not yet verified
- **No real model was run** (Hugging Face is blocked where this was developed): compatibility proves that the right arguments reach the right pipeline, not that the image looks good. The new steps and guidance defaults come from the models' documentation and the GGUF path, not from quality tests.
- Only local providers and Demo are in the new matrix; the cloud adapters (OpenAI, Google, Replicate…) remain covered by the tests that already existed, with simulated servers.
- The 1,233-run sweep was done separately (it takes ~10 min); the permanent test runs a smaller version (~2 min).

## [0.73.0] — 2026-11-17

### Improved — internal system prompts of Style Folder and Style Prompt
OpenFlow now instructs the AI on its own (the user neither sees nor edits these texts, which live in `canvas/styles.py`) so the project's general style is described and applied more precisely.
- **Style Folder — describing the folders:** the system prompt that describes the reference images and folders was rewritten with precision rules. The general style talks only about what holds for every image (technique, palette with concrete colors, light, composition), character/scenery/object sheets carry only **fixed, visual** traits, with no action, momentary emotion or plot, and do not repeat the general style; when in doubt it omits (does not invent); if the images diverge, what repeats wins; if a note of yours contradicts the images, the note wins. The AI's answer is now read **from the first line of the format**, so a «Sure! Here is…» before the guide does not become style.
- **Style Prompt — new:** a long running text (140 characters or more, without the «GENERAL STYLE / CHARACTER…» headings) is rewritten by the AI, internally, in the fixed format: what holds for everything goes to general style, each character/scenery/object becomes a sheet, prohibitions («never…») go to consistency. Rules: it does not invent, keeps names, @mentions and terms exactly, does not create entities. Per-prompt relevance therefore also works on running text: a style with four characters only sends the prompt the sheet of whoever it mentions. The result is stored in the node (redone only if the text or the text model changes). Short texts («watercolor, soft colors»), texts already in the format and projects without a text model (Demo) stay exactly as before; the «Organize the text with AI» box turns it off. If the AI fails or answers something without the format, the original text is used (with a notice).
- **Using the style in text steps** (AI Text, Refine text, Lyrics): they gained usage rules — the style guides tone and visual language but **never changes the subject or the instruction** (in a conflict, the request wins), the sheets apply only to whoever the text mentions, «Consistency» is a fixed rule, and the guide is neither copied nor mentioned in the answer.
- **Using the style in image, video and music:** the style snippet at the end of the prompt now comes with a short frame («Style guide (the look of the whole result, not its subject or action): …»), so the model treats it as look and not as subject. Before it was just «Style: …».

### Not yet verified
- No real text model was used: in the tests the AI is fake. Whether the new system prompts make a real model describe and organize better, and whether the frame improves images from real models, **was not measured**. The frame is a bit longer than the old «Style:», which on models that read few tokens (CLIP's 77) may push part of the style past the limit.
- Organizing the Style Prompt is one more call to the text model, once per text (stored afterwards).

## [0.72.0] — 2026-11-17

### Fixed — local image and video models on weak computers (FLUX, Qwen-Image and the rest)
I looked for the problems **by reading the diffusers 0.43 code** (the real signature of each pipeline) and OpenFlow's generation path; none of it was reproduced with a real model.
- **Editing with Qwen-Image-Edit, FLUX Kontext and FLUX.2 broke:** OpenFlow sent `strength` (which these pipelines do not have) and went through an «image → image» that diffusers does not link to them. The requested arguments are now checked against the pipeline's real signature: these models edit with `image` directly, without `strength`. A model that does not accept an image says so, instead of a raw error in the middle of generation.
- **Qwen-Image generated weaker than it should:** OpenFlow sent `guidance_scale` 7 (which it ignores) and no negative prompt, and without a negative prompt diffusers **turns CFG off**. It now uses `true_cfg_scale` 4.0 with a negative prompt, 30 steps (50 is the library default; 30 saves time on a weak machine) and, for the «Lightning» versions, 4 or 8 steps without CFG (before: 2 steps).
- **Several reference images:** FLUX.2 dev (up to 10) and Qwen-Image-Edit-Plus/2509/2511 (up to 3) only used the first one; they now use all of them, within each model's limit.
- **Black images on FLUX and Qwen-Image with a GPU:** these models are trained in bf16 and overflow in fp16. A model downloaded in fp16 is now loaded as bfloat16 (the fp16 weights are read in that type).
- **Computers without a GPU:** a model downloaded in fp16 ran in fp16 on the CPU and failed («not implemented for 'Half'») on Whisper, Bark, MMS, SDXL and others. The CPU now uses float32 for small models and bfloat16 for big ones (FLUX, Qwen, SD3, Wan, LTX…, where float32 would double the RAM). Applies to image, video, voice, sound and transcription.
- **Size on the CPU:** the longer side went to 768 but **each side was clipped on its own** (1024×576 became 768×576, stretched); the aspect ratio is now kept (768×432). Sizes are multiples of 16, as FLUX, Qwen-Image, SD3 and Z-Image expect.
- **Out of memory while generating:** instead of torch's raw error, OpenFlow tries again, lighter. On the graphics card: VAE slicing and offloading the model to RAM; then an image 25% smaller (up to 2 times; the next images already come out at the size that fit). On RAM, only the reduction. For video: fewer frames first, then smaller. If nothing fits, the message says what to do (smaller image, smaller precision, quantized GGUF, virtual memory on Windows).
- **Out of memory while loading:** the message explains (RAM or card) instead of a traceback; and if the model does not fit on the card even with the plan, loading falls back to offloading to RAM.
- **Text-only video model with an image connected:** raised a `TypeError` mid-generation; the message now says the model only generates from text.

### New — voxcpm library in OpenFlow's libraries
- `flow libs` (and the installer/updater, which use «all») now install the **voxcpm** library (the VoxCPM2 voice) when Python is 3.10 or newer; on 3.9 it is skipped. Also `pip install "openflow[voxcpm]"`, and the «all» extra includes it (`python_version >= "3.10"`). If the installation fails, OpenFlow carries on without it and warns.
- `flow doctor` shows whether voxcpm is installed. If the library exists but one of its dependencies is missing (funasr, modelscope…), the node says which; on Python 3.9 it says 3.10 is needed.

### Not yet verified
- **No real model was run** (Hugging Face is blocked where this was developed): FLUX, Qwen-Image and the rest were exercised with fake pipelines that have the real diffusers signature. Whether OpenFlow now generates/edits on those machines, and how much memory each model really uses, was not measured.
- The lighter retry after running out of memory (sequential offload after model offload) depends on the diffusers/accelerate version and is done «as far as it goes»; if a step does not exist, it moves to the next (shrinking the size).
- FLUX.1 in bf16 on a GPU without native bf16 (Pascal/Turing, such as the GTX 16xx) runs by emulation, slower; an FP8/GGUF model is better in those cases.
- Installing voxcpm along with everything may bring heavy dependencies (gradio, funasr, modelscope…) and conflict with versions already installed; failures only produce a warning.

## [0.71.0] — 2026-11-17

### New — openbmb/VoxCPM2 support (local voice)
- **The model:** VoxCPM2 is a 2 B-parameter voice model, 30 languages (including Portuguese), **48 kHz** output, Apache-2.0 license. Pick `openbmb/VoxCPM2` in the «Model» field of the Voice (or Dubbing) node: it shows up in the local Hugging Face voice suggestions, is recognized as a voice model, and the sound search bar shows the «ok» badge for it under the «Voice», «Clone» and «Created from a description» topics.
- **Plain speech:** just the text, no language tag. Long texts are split into pieces (≈ 420 characters, cut at sentence ends) with a short pause between them, because the model gets unstable on very long inputs.
- **Voice design:** the «What the voice is like» field (plus the project style) becomes «(description)text», as the model expects: «young woman, sweet and cheerful voice». Parentheses in the description become commas, and a text that already starts with «(…)» is left as you wrote it.
- **Controllable cloning:** connect an audio (or video) to the new **«Reference voice»** input of the Voice node. The voice in the audio is cloned, and the description, if any, steers the style («a bit faster, cheerful») while keeping the timbre. The audio is converted to 16 kHz mono WAV (and cut to the first 30 seconds).
- **Faithful cloning:** also fill «What is said in the reference voice» with the exact text of the audio: the model continues its speech (the whole audio counts). In this mode the voice description is not read, and the node says so.
- **Dubbing:** each Voice node connected to «Voices» can have its own reference, so each character is cloned from a different audio. Changing the reference or its text redoes the dubbing.
- **Advanced settings** in the node's «Extra» field: `cfg_value` (default 2.0), `inference_timesteps` (default 10), `normalize`, `denoise` and `retry_badcase`. The Voice node's speed also works (ffmpeg, pitch unchanged). The model is read only from downloaded files (nothing is downloaded silently), on GPU when available.
- **Download:** the model's audio codec is the `audiovae.pth` file, which the downloader used to drop when the repository has `safetensors`; it now comes with the weights (without it the model cannot speak).
- **Installation:** the library is optional and left out of «all», because it brings many dependencies of its own (Python 3.10+): `flow libs --extras voxcpm` (or `pip install voxcpm`). Without it, the node tells you how to install it.
- Other providers/models that do not clone voices ignore the «Reference voice» **with a warning** (VoxCPM 0.5B/1.5 do not either: only VoxCPM2 accepts a reference).

### Not yet verified
- **No model was downloaded or run:** Hugging Face is blocked where this was developed. The arguments of `VoxCPM.from_pretrained` and `generate` were checked by reading the `voxcpm` 2.0.3 package code and the README and `config.json` of `openbmb/VoxCPM2` through the Hub; in the tests, the library and torch are simulated (ffmpeg and numpy are real).
- I do not know whether the library installs without conflicts with your torch/transformers versions, nor how much memory the model uses on your computer (the README mentions ≈ 8 GB of VRAM). I ran with `optimize=False` (no `torch.compile`) to be stable: it may be slower than the speed the README mentions.
- The quality of cloning and voice design **in Portuguese**, and whether Portuguese descriptions work as well as English/Chinese ones, was not evaluated. The README warns that voice design and style control vary between runs (generate 1 to 3 times).
- The model has no seed: two generations of the same text may sound different.
- Use forbidden by the model's author: impersonation, fraud and disinformation. Label generated audio and clone only voices you have the right to use.

## [0.70.0] — 2026-11-17

### New — Remove watermarks from images and videos
- **The Watermark node now also removes:** under «What to do», choose «Remove a watermark». It works on **images and videos** (the video keeps its resolution, frame rate and sound). The node's output can now be a video and connects to any media input; the «Add a mark» mode is unchanged (and is the default).
- **Where the mark is:** in a **corner** (size as % of the frame and margin), in an **area** in % (left, top, width, height), **found automatically** (video only) or given by a **mask** connected to the new «Mask» input (white = what to erase), which replaces the area.
- **How it erases:** ffmpeg rebuilds the area from the surrounding pixels (`delogo`; with a mask, `removelogo`). A small mark over a smooth background disappears well; over a detailed background a **blurry smear** is left: it is not an inpainting model and does not «guess» what was underneath.
- **Automatic detection in video:** it analyzes 14 frames spread across the video and looks, in the four corners, for what does not change and has edges (letters and outlines). The node says where it found it («Mark found at x…%»). Needs numpy. In an almost still video (slides, fixed camera) the mark cannot be told apart from the background and the node warns instead of guessing; if nothing is found, it also warns.

### Not yet verified
- Tested with synthetic images and videos (white mark over a smooth background or moving noise), real ffmpeg and numpy. **Real photos and videos were not tested:** semi-transparent, moving, large marks or marks over detailed backgrounds may stay visible or leave a smear, and automatic detection was tuned only on those test videos.
- Marks that fill the frame, appear in several places or move around are not handled (the area is fixed throughout the video).
- Removing watermarks from other people's content may infringe copyright; use it on your own material or with permission.

## [0.69.0] — 2026-11-17

### New — Transcript with several voices
- **Who speaks each part:** the Transcript node gained «Separate the voices». Each line comes with the name of who spoke it («Locutor 1: …», «Locutor 2: …»), in running text (one line per change of voice), in timestamps (the name on every line) and in paragraphs. When the voice changes in the middle of a segment, the segment is split at the change (the text is divided by time, so that cut is approximate).
- **How many voices and names:** leave 0 for OpenFlow to find out, or say how many people speak (more reliable). «Voice names» («Ana, Bruno») replaces «Locutor N» with names, in the order the voices appear. Named output is read by Dubbing («Name: line» marks).
- **How it works:** no model download, only numpy and ffmpeg: the audio becomes 1 s windows of speech, each with the timbre (mel cepstrum) and pitch of the voice, and the windows are grouped by similarity. A single voice stays a single voice. Off by default, so old projects come out the same. Without ffmpeg/numpy, or with a model that returns no timings, the transcript comes out as before and the node warns when you asked for more than one voice.

### Not yet verified
- Tested only with the demo's synthetic voices (deep and high), real ffmpeg and numpy. **Recordings of real people were not tested:** similar human voices, noise, background music and overlapping speech may be confused, and the thresholds of automatic mode were calibrated on the synthetic voice. When in doubt, say how many voices there are.
- It does not use a dedicated model (pyannote, ECAPA): it is much simpler and less accurate than those.

## [0.68.0] — 2026-11-17

### Improved — local Hugging Face sound and voice models
- **Sounds, music and effects from more families:** besides MusicGen, the Music/Effect node now runs **AudioLDM, AudioLDM 2, MusicLDM, Stable Audio Open and Stable Audio 3** (through the `diffusers` audio pipelines; install with `pip install diffusers`). Each family gets its own arguments (duration as `audio_length_in_s`, `audio_end_in_s` or `duration`), the sampling rate is read from the model, and the result is WAV (stereo when the model is stereo). Requests above a model's limit (AudioLDM 30 s, Stable Audio Open 47 s, Stable Audio 3 190 s) are capped and the node says so.
- **Voice speed on local models:** the «Speed» field only worked on the demo voice. It now also applies to Bark, MMS-TTS, Orpheus and CSM, changing the pace **without changing the pitch** (ffmpeg `atempo`, 0.5×–2×). Without ffmpeg the voice keeps its original speed and the node says so.
- **Sound search bar:** AudioLDM/MusicLDM and Stable Audio now show as compatible («ok») for sounds and music; GGUF, ONNX and TFLite models stay marked incompatible. The local Hugging Face suggestions gained AudioLDM 2, Stable Audio Open/3 and the MMS-TTS voices (pt/en/es).

### Not yet verified
- No model was run: Hugging Face is blocked in the development environment. Each pipeline's arguments were checked by reading the `diffusers` 0.43 and `transformers` 5.23 sources, and the tests use simulated `diffusers`/`torch` (ffmpeg and numpy are real). Whether AudioLDM 2 or Stable Audio really generate the sound, and how well, was not tested.
- The Stable Audio 3 repository layout for `diffusers` was assumed from the `diffusers` documentation.
- Out of scope: SpeechT5 (needs a speaker vector), non-Whisper transcription, Parler-TTS, Dia and Kokoro.

## [0.67.0] — 2026-11-16

### Fixed — «could not convert string to float: 'E aí e aí e aí…'» in Dubbing
- **The cause, in the screenshot:** the «Model» selector of the **Dubbing** node itself (the **voice** model) was set to `openai/whisper-small`, which is a **transcription** model. The speech text was handed to a model that expects audio, and the conversion failed with the whole text inside the message. Whisper was on the list because local Hugging Face showed **every downloaded model in every list** (sound, voice, transcription, image…), except the 3D ones.
- **The lists now separate by type:** the voice selector no longer shows Whisper or MusicGen; the transcription one only shows transcription models (or of unknown type); the sound one, sound and music models; and the image and video lists show no audio models. The type comes from the model's **name** (Whisper, wav2vec, Bark, MMS-TTS, Orpheus, CSM, MusicGen, AudioLDM, Stable Audio…); a name OpenFlow does not recognize **keeps showing up and working as before**.
- **A clear message instead of the cryptic error:** if a model of the wrong type reaches the loader (a project already saved that way, for example), the node says *«'openai/whisper-small' is a transcription model (speech → text), not a voice one (text → speech). In the node's «Model» field… choose a voice model (Bark, MMS-TTS, Orpheus or CSM)…»*. The same holds for sounds and for transcription. And «Use» in the search bar refuses the model of the wrong type.
- **Whisper repetition loops:** the text «E aí e aí e aí…» repeated dozens of times is Whisper's typical hallucination on stretches with no speech. A word repeated 12 times or more in a row, or a phrase of up to 6 words repeated 6 times or more, keeps two repetitions in the transcript, the subtitles and the dub. Normal repetitions (song lyrics, «la la la la», «Eu te amo» ×4) stay as they are.

### Not verified yet
- **I did not run Whisper or the real transformers** (Hugging Face is not reachable from here): the case in the screenshot was reproduced by sending the wrong model to the local loader, which refuses it before any library. That the original transformers error (`float(...)` with the text) really came from Whisper receiving the text is the most likely conclusion (the model in the screenshot was Whisper, and the text in the message is the text that was going to be spoken), **not a run of the error**.
- The model type comes from the **name**: a voice model whose name contains «whisper» would be treated as a transcription one, and a repository with no recognizable name is neither filtered nor blocked.
- The repetition cleanup uses fixed limits (12 equal words; 6 repetitions of a short phrase): a shorter loop, or a hallucination that does not repeat, **is not detected**; Whisper can still invent text on stretches with no speech.

## [0.66.0] — 2026-11-16

### Fixed — «got multiple values for keyword argument 'local_files_only'» in transcription
- **The error in the screenshot:** when dubbing or transcribing with **local Whisper**, the node failed with *«Unexpected error: transformers.models.auto.configuration_auto.AutoConfig.from_pretrained() got multiple values for keyword argument 'local_files_only'»*. The new transformers already passes `local_files_only` by itself when loading the model configuration, and OpenFlow passed it again in `model_kwargs`. Now loading tries as before and, if transformers rejects the repeated argument, **repeats the load with offline mode through the `HF_HUB_OFFLINE` variable** (valid only during the load and restored as it was), which works on every version. Nothing is downloaded silently, as before.
- **Where it applies:** transcription (Whisper — the Transcript, Subtitles and Dubbing nodes, and the Transcribe node), **voice** (Bark, MMS-TTS) and **sounds/music** (MusicGen): the three loaded the model the same way and had the same risk with the new transformers.

### Not verified yet
- **I did not run Whisper or the real transformers:** the tests use a fake `transformers` that rejects the repeated argument exactly as in the message. That Whisper loads, transcribes and gives the timings with the new transformers (and whether another error shows up after this one) **was not measured**.
- The message still shows as «Unexpected error» when loading fails for another reason (for example, a model not downloaded or a missing library have their own message; other transformers errors do not).

## [0.65.0] — 2026-11-16

### New — Search bar for sound, music and SFX models (Hugging Face)
The Canvas model search bar got much better for **sound**, **voice** and **transcription**. Hugging Face's `text-to-audio` filter mixes everything — **video** models that also generate audio (LTX), «omni» assistants, codecs and text-to-speech voices next to the songs —, so the search now **classifies every result**:
- **Topics:** a new «Topic» selector appears when you pick the type. **Sound:** Music · Sound effects (SFX) · Separate and enhance audio. **Voice:** Voice (text → speech) · Clone or swap the voice · Voice created from a description · **Dubbing** (speech → speech in another language). **Transcription:** Transcription and subtitles. Each topic queries the Hub by **its own tags** (`music`, `sound-effects`, `voice-conversion`, `voice-cloning`, `voice-design`, `speech-to-speech`, `source-separation`…), not only by name.
- **No noise:** video models, «omni» assistants and codecs/vocoders are gone from the sound results; music and effects are told apart (Stable Audio, which does both, shows up in both); voices no longer show up among the songs.
- **«Runs in OpenFlow» / «Does not run in OpenFlow yet» badge** on every result, with the reason on hover and when you open the model (e.g. «needs the repository's own code», «uses the diffusers library», «is in GGUF»). Today OpenFlow runs **MusicGen** (sounds and music), **Bark, MMS-TTS (VITS), Orpheus and CSM** (voice) and **Whisper** (transcription); the ones that run come **first**, then the most downloaded. A model OpenFlow does not run can still be opened, but the **«Use» button is blocked**, with the reason.
- **Opens with the most downloaded:** when you pick sound, voice or transcription, the list appears **without typing anything**, for the chosen topic. Typing filters: the name of a family (`musicgen`, `whisper large`), an author (`stabilityai`) or **a language in Portuguese** — «voz em português» filters by the Hub's language tag; words that only name the topic («música», «efeitos sonoros», «dublagem») do not get in the way of the text search.
- **Server:** `GET /api/media/hub/search?cap=sound|voice|stt&topic=…` (results with `topics`, `library` and `compat`) and `GET /api/media/hub/topics`. The other capabilities (image, video, 3D, text) work as before.

### Not verified yet
- The Hub query was **simulated** in the tests (and the real Hugging Face tags and results were checked separately, through the Hub tool, not through OpenFlow's HTTP client): the real network search, with OpenFlow's token and cache, was not exercised here. The classification by topic and the badge come from the **tags, library and name** the Hub reports: a repository with incomplete tags may land in the wrong topic or be left out.
- **«Runs in OpenFlow» means «supported family»:** it does not mean that exact repository was downloaded and tested. The reverse also holds: a model marked «Does not run yet» may work if it is compatible with one of those families without saying so in its tags.
- Sung music (ACE-Step, YuE), effects (Stable Audio, MOSS-SoundEffect), new voices (Kokoro, XTTS, OmniVoice…), voice conversion and speech-to-speech dubbing **show up in the search, but OpenFlow does not run those models yet**: the badge says so. Searching by language («voz em português» + «voz em inglês») asks for models that declare both.
- It does not rank by relevance or quality: after the badge, the Hub's download order applies.

## [0.64.0] — 2026-11-16

### New — Voice style: «What the voice is like» on the Voice node
On the **Voice** node, right **below the text that will be spoken**, there is a new box: **«What the voice is like (optional)»** — describe the voice in free words (*«deep and calm, like a narrator»*, *«female, young and upbeat»*, *«whispering»*). The same box exists on **Dubbing**, for the node's own voice. For voices connected to Dubbing (v0.63), each Voice node carries its character's description.
- **How it reaches the model:** the description goes in the voice's style request (`instructions` of the provider API) **before** the project's Style Prompt, if any. It takes part in the **cache**: changing the description redoes the Voice node, and, in a Dubbing, the description of each connected voice redoes the dub.
- **Demo voice (offline):** the description changes the **pitch** (deep, male, old → lower; high, female, child → higher), the **pace** (fast, upbeat → faster; slow, calm → slower) and the **volume** (whispering, soft → quieter), in Portuguese and English, ignoring accents and case. With no words it recognizes, the voice comes out **identical** to the previous version (checked byte by byte).
- **Orpheus (local):** the description only counts for the **gender** (female/male): with the «Voice» field **empty**, OpenFlow picks one of the model's voices that fits (female → `tara`, male → `leo`); a voice typed in the «Voice» field always wins.
- **Warnings, instead of silently ignoring:** a model that **does not read** the description (today, all the other local voice models) says so in the node's result — «… does not read the voice description: it was ignored (the voice comes from the node's «Voice» field)». In Dubbing, the same warning shows once per model, only for voices that have a description.

### Not verified yet
- **No real voice model read the description.** The voice models OpenFlow offers today (Bark, MMS-TTS, Orpheus, CSM) **have no** voice-description field: only the demo voice and the Orpheus gender-based voice pick do anything with it; the others warn that they ignored it. Models built for this (that accept «describe the voice») and providers with `instructions` **are not integrated**; the box and the path to the provider are ready for them.
- Which Orpheus voices are female (`tara`, `leah`, `jess`, `mia`, `zoe`) and male (`leo`, `dan`, `zac`) comes from the model's documentation and **was not checked by listening to the model**; the automatic pick did not read the result.
- In the demo the description is just a list of words (pitch, pace, volume): it **does not imitate accent, age or emotion**, and «louder/shouting» does not exist (the demo's volume already comes out at maximum).
- The «Speed» field still has no effect on local voice models (only the demo voice uses it) — this was already so and did not change in this version.

## [0.63.0] — 2026-11-16

### New — Custom voices in Dubbing: a Voice node for each character
The **Dubbing** node got a **«Voices»** input: connect **one or several Voice nodes** to it and each character speaks with their own voice.
- **Each Voice node is a voice profile:** its **model**, **voice**, **speed**, extra settings and the **Style Prompt** connected to it all count. The **node's title is the character's name** (with no title, the voice name is used; and always «Voz 1», «Voz 2»… by connection order). Each node can use a **different model/provider**. With voices connected, they replace the voice of the Dubbing node itself; with none, everything works as before.
- **Who speaks each piece — «How to pick the voice of each line»:**
  - **By the marks** (default): in the script (plain text or SRT/VTT connected to «Script»), mark the line with `Maria: line`, `[Maria] line` or `(Maria) line`. Case and accents do not matter («joão» = «João»). The mark holds **until the next one** (a script with the mark only on the first sentence of each speech keeps the same character); before the first mark, the first Voice node speaks. The mark is removed from the text: it is not read aloud.
  - **Alternate between the voices:** lines alternate, one at a time (a two-person dialogue with no marks).
- **Only names of connected Voice nodes become marks:** «(laughing)», «[Music]» or «Attention: the train arrives» stay as spoken text. A «Name:» that has **no** voice connected but **repeats** in two or more lines is treated as a character with no voice: the mark is removed from the text, the line keeps the previous voice and the node **warns** which characters have no voice.
- **Warnings:** voices connected but no marks in the script (it used only the first voice and says how to fix it); the list of **voices used** with each one's line count; a node connected to «Voices» that is not a Voice node (ignored, with its name). The node's result shows «Maria: …», «João: …» with timestamps.
- **A Voice node connected to Dubbing needs no text and does not have to run:** with no text it only defines the voice (it is no longer a «needs a text» error — that message stays for a loose Voice node); Dubbing **does not wait** for it nor stops running if it fails (if it has text and generates a sample audio, that is separate). The Dubbing **cache** follows the voices' **settings** (voice, speed, model, style and character name) and not the sample audio: changing a character's voice redoes the dub; regenerating the sample audio does not.

### Not verified yet
- **No real voice model was used**: the tests use fake providers that record what each voice was asked, and the real ffmpeg. That a real voice model sounds like the character you imagine was not measured. The voice models OpenFlow offers have fixed or few voices (the node's «Voice» field is the name the model understands); **cloning a person's voice from a sample is not in this version**.
- Voice choice depends on **marks in the script**: when the speech comes from transcribing a video (no marks), OpenFlow **does not tell who is speaking** (there is no speaker separation), so everything comes out in the first voice — use «Alternate between the voices» in a two-person dialogue, or pass the transcript through a text node, mark the characters and connect it to «Script».
- The «Name:» mark is only recognized at the **start** of the line/cue; a line OpenFlow splits (too long) keeps the same character.

## [0.62.0] — 2026-11-16

### New — Dubbing, Subtitles and Transcript: three nodes in the Sound group
Three new nodes, right after the **Voice** node in the palette. They take a video or audio (from the **Media** node or any node that generates audio/video) and chain with each other.
- **Transcript (`transcript`):** transcribes the speech of the video or audio with the project's default transcription model (local Whisper) and delivers **text**: running, **with timestamps** (`[1:05] sentence`) or in **paragraphs** (a long pause opens a new one). Speech language automatic or of your choice; a **Download (.txt)** button on the node. Long audio is read in 30 s windows without losing each piece's timing.
- **Subtitles (`sub`):** generates **SRT or VTT** for any player, from the speech of the video/audio **or from a text**: a text that already is a subtitle (SRT/VTT) is reformatted (format change, advance/delay); plain text is **spread across the file** in proportion to the size of each sentence (using the connected file's duration, or the one you type in the node). Controls: characters per line (20 to 80), lines per subtitle (1 to 3), maximum duration of each subtitle (long ones are split so every part fits both limits), advance/delay in seconds and optional **translation** to another language with the text model (10 languages). A **Download (.srt / .vtt)** button on the node (the file is built in the browser).
- **Dubbing (`dub`):** dubs a video or audio: **transcribes** the speech (or uses the **script/subtitles connected** to the «Script» input, which are dubbed as they are), **translates** with the text model, **speaks** each piece with the node's voice model (adjustable voice and speed), **fits** each line into the time of the original piece (speeds up to 1.6× what does not fit; speech never overlaps: a piece that did not fit pushes the next one back and the node warns) and **mixes**: replaces the original audio with the dub or keeps it low underneath. With video, the picture is kept (copied without re-encoding when possible) and the audio is swapped; with audio, an MP3 comes out. What was dubbed, with timestamps, stays in the node's result. Up to 300 pieces per dub.
- **A flow with no transcription model:** since the Demo voice works offline, a **script (or SRT subtitles) connected to «Script»** gives a complete dub (the demo babble) without Whisper; the node warns that it is a demo voice.
- All three take part in the **cache** (changing the script, the transcription model or the text model regenerates only what depends on it), have English translations and clear warnings: a transcription model that returns no timings, plain text spread over the file, lines the translation did not return (they stay in the original language, with the count), no text model (does not translate, and says so), demo voice, pieces sped up or delayed.
- **New in the media-provider API:** `transcribe_segments` (the speech with the timing of each piece) and `timed_segments`; local Whisper returns the timings, other providers fall back to a single block.

### Not verified yet
- **No real transcription or voice model was used.** The tests use a fake provider with known timings and the demo babble; ffmpeg is real. That local Whisper gets the words and the **timings** right (and how it behaves on long audio, with music or several voices) **was not measured**; `chunk_length_s=30` was chosen from the transformers documentation, without running the model.
- The **quality of the dub** depends on the configured voice and text models: the mixing, the fitting in time and the audio swap are verified; the naturalness of the voice, the accent and the rhythm of the translated speech are not. The dub does not separate the voices from the effects and music of the original: with «Keep it low underneath» they stay underneath; with «Replace with the dub» they go away.
- Translation depends on the text model (and on it following the numbered format); lines it does not return stay in the original language.
- **Subtitles are not «burned» into the video** (that stays in the Editor/Final video); here the result is the subtitle file. There is no speaker change (diarization) or styles (ASS) — only SRT and VTT.
- The formats were checked by round-trip reading inside OpenFlow itself (SRT and VTT), **not** loaded into real players (VLC, browsers, YouTube).

## [0.61.0] — 2026-11-16

### New — Music and SFX: three nodes in the Sound group
Three new nodes at the start of the palette's **Sound** group (the old **Sound** node stays, for whoever already uses it):
- **Music:** generates a song from the style you describe (genre, mood, instruments) — in the node's field and/or in a text connected to «Description». Controls: **lyrics** (optional; write them in the node or connect a Lyrics node to the «Lyrics» input), **instrumental** (no vocals), **duration** (5 to 240 s), **tempo in BPM** (0 = automatic), seed and the model picker (as in the other media nodes). The generated song keeps the lyrics it used next to the file.
- **Lyrics:** writes the lyrics of a song with the active **text model** (Settings → Providers) from a theme (the node's field and/or a connected text). It picks the **language** (Portuguese, English, Spanish, French, Italian, German), **genre**, **mood**, **structure** (full song with verses, chorus and bridge; short; chorus only; rap), **rhymes** (in pairs, alternating, free) and whether the parts come marked with `[Verse 1]`, `[Chorus]`… (the format music models read). In **Tidy my lyrics** mode it uses no AI: it cleans your lyrics and standardizes the marks («Refrão:», «(verso 2)» → `[Chorus]`, `[Verse 2]`). With no text model configured (Demo provider), it builds an **example** lyric from the words of the theme, and says so.
- **SFX:** generates short sound effects (footsteps, door, rain, laser…) from a description, with 1 to 4 **variations** at once (each with a different seed), 1 to 30 s long.
- All three take part in the flow **cache** (changing the lyrics or the theme regenerates only what depends on it), show up in the **Editor** and the **Library** like any audio, and have English translations.
- **Honest warnings when running:** if the model does not sing lyrics, the song comes out with the style only and the node **warns** (the lyrics are not sent to the model as if they were style); if the model returns less than the requested duration (local models generate a short piece at a time), the node says how many seconds came out; with **Instrumental** on, the lyrics are ignored and that is said too.
- **Demo (offline):** the demo music gains tempo by BPM and, with lyrics, a **rhythmic babble** on top (not real singing) — it serves to test the whole Text → Lyrics → Music flow with no model at all.

### Not verified yet
- **No real music model was used.** The tests use the Demo provider and fake providers. The local sound model OpenFlow offers (MusicGen) **does not sing lyrics**: with it, the song comes out with the style only and the node warns. Real sung music (for example ACE-Step or YuE) is **not integrated in this version**: the «Lyrics» port, the warning and the interface are ready for a provider that sings, but none has been plugged in yet.
- Local models generate up to 30 s at a time; longer durations get the warning above (join pieces with «Loop audio» or in the Editor).
- MusicGen is a **music** model: used for SFX it only works approximately (there is no dedicated sound-effects model yet).
- The lyrics written by the text model depend on the configured model (quality, language, respect for the structure): the cleaning and the format are verified, the quality of the lyrics is not.

## [0.60.0] — 2026-11-16

### Fixed — `flow` in the Windows and macOS terminals
An audit of what the terminal does differently on each system, with these fixes (the ones marked «tested» have automatic tests using simulated command output and sockets; there is no real Windows or macOS in the tests):
- **Windows — `flow update` did not run the installer properly:** the downloaded `install.ps1` was saved as UTF-8 **without a BOM**, and Windows PowerShell 5.1 reads that as ANSI: the installer's «✓» (bytes E2 9C 93) becomes «â œ “», and the «“» quote closes the string halfway — a syntax error before it starts, besides the swapped accents. `flow update` now saves the installer with a BOM (tested). The published file stays **without** a BOM on purpose, because `irm … | iex` does not accept a BOM at the start.
- **Windows — installer on old Windows 10 / Server 2016:** `install.ps1` turns TLS 1.2 on (PowerShell 5.1 does not always do it by itself and the GitHub download failed with «Could not create SSL/TLS secure channel»).
- **Windows — terminal output crashed on ✓ ⚠ → …:** with redirected output (`flow models list | clip`, `> file`, task scheduler) Windows uses the system code page (cp1252/cp850), which lacks those characters, and `print` died with `UnicodeEncodeError`. Now whatever the encoding cannot represent becomes «?» (stdout and stderr) instead of crashing the command (tested).
- **Windows — opening `flow` twice fought over the same port:** Windows' `SO_REUSEADDR` lets two programs open the same port without error, so the second instance did not move to the next port (8788…) and the browser landed on one or the other. The server now uses `SO_EXCLUSIVEADDRUSE` on Windows (the second attempt fails and `flow` moves on to the next port). Linux and macOS stay as they were (tested what can be tested on Linux: the second instance cannot open the same port; the Windows branch is tested with a simulated socket).
- **macOS — without the Rust core, RAM showed as 0:** the Python path only read Linux's `/proc`. It now reads the total (`sysctl hw.memsize`), the really available memory (`vm_stat`: free + inactive + speculative + purgeable, in Apple Silicon's 16 KB page or Intel's 4 KB), the **physical cores** (`hw.physicalcpu`; the «half of the logical ones» guess was wrong on Apple Silicon, which has no hyper-threading) and the **CPU extensions** (NEON on Apple Silicon; SSE4.2/AVX/AVX2/FMA/AVX-512 through `sysctl` on Intel) (tested with simulated output).
- **macOS — available RAM was only an estimate:** the Rust core estimates 60 % of the total on macOS. OpenFlow now uses the `vm_stat` reading when the core only estimates, so the model planner and the computer guard see the real memory (cached for 2 s so `vm_stat` is not called all the time).

### Not verified yet
- **None of this ran on a real Windows or macOS.** The tests use simulated `sysctl`/`vm_stat` output, sockets and downloads; `install.ps1` was not executed (there is no PowerShell here, only a byte-level analysis). That PowerShell 5.1 accepts the installer with a BOM and that TLS 1.2 fixes the download on an old Windows 10 is reasoning about known behavior, not a run.
- **The Rust core was not changed:** on macOS it still estimates 60 % free RAM and counts physical = logical cores; the fix is on the Python side, which overrides the estimate. Fixing it in Rust requires building and testing on macOS.
- The audit was a code read: other system-specific problems may exist (for example, the URL shown is `localhost` and Windows tries `::1` before `127.0.0.1`, which only delays opening).

## [0.59.0] — 2026-11-16

### New — Multi GPU: the VRAM of several cards together, and VRAM + RAM at the same time
To run models bigger than one card holds. Everything is in **Settings → Performance → Memory** (new card), with defaults that already work: **split across cards** (on), **use RAM together** (on), per-card VRAM reserve (512 MB) and RAM reserve (2 GB).
- **Text models (llama.cpp):** with two or more NVIDIA cards chosen, the planner now counts the **usable memory of all of them together** — a 30 GB model that used to leave layers in RAM on a 24 GB card now fits entirely on two. Layers are split in proportion to each card's free memory (`tensor_split`; the card with the most free memory is the main one). Whatever still does not fit on the cards goes to **RAM** (CPU layers) — both at the same time.
- **Image and video (diffusers):** when the model does not fit one card it loads with `device_map="balanced"` and `max_memory` (usable VRAM of each card and, with «use RAM together», the free RAM). If your diffusers/accelerate version rejects it, OpenFlow repeats the load the old way.
- **Image and video (sd-cli):** with a CUDA sd-cli installed by OpenFlow that accepts `--backend`, the **text encoder and the VAE go to another card** when they do not fit next to the diffusion model on the main one (the diffusion model itself does not split: it stays on one card, offloading to RAM if needed). In every other case (Vulkan, an sd-cli without `--backend`, a single card) the previous behavior applies.
- **«Use RAM together» off:** a text model that does not fit entirely on the chosen cards **stops with a clear message** (instead of silently running slowly on the CPU).
- **New route** `GET /api/perf/memory` and the card show the cards, usable VRAM and RAM and, for every downloaded model, **where it would fit**: one card, split across cards, cards + RAM, RAM only, or does not fit.
- The settings are validated (reserves 0–8192 MB and 0–64 GB; an invalid value goes back to the default) and included in export/import.

### Not verified yet
- **No real graphics card was used**: the tests use simulated cards and a fake `torch` and `sd-cli`. That a model actually **runs faster or fits** with two real cards was not measured; speed between cards depends on PCIe/NVLink.
- The `--backend te=CUDA1,vae=CUDA1` syntax and the CUDA0/CUDA1 numbering (in `CUDA_VISIBLE_DEVICES` order) come from the ggml/stable-diffusion.cpp documentation and were **not tested with a real sd-cli**; OpenFlow only uses it when the executable's `--help` shows `--backend`.
- diffusers' `max_memory` with a `"cpu"` key may be rejected by some versions (there is a fallback); diffusers' automatic split applies to models loaded from Hugging Face folders, not GGUF.
- **AMD/Intel (Vulkan) do not split across cards**: NVIDIA only. The sd-cli `_SPLIT_ACTIVE` state is global: two simultaneous generations with different plans could mix it up (OpenFlow runs one at a time).

## [0.58.0] — 2026-11-16

### New — 3D 2: texture, skeleton and animation for 3D models
Three new nodes in the palette's **3D** group. They chain (**3D model → 3D texture → 3D skeleton → 3D animation**) and each one **keeps what the previous one did**: the texture goes all the way, so does the skeleton, and the final file is a GLB with everything. Any GLB or OBJ uploaded through the **Media** node can also come in (before, the Media node could not connect to 3D model ports).
- **3D texture:** puts a texture on the model, with a **connected image** (e.g. generated by an Image node) or, with no image, a **procedural pattern** (checker, stripes, bricks, noise, gradient, wood) between two colors. Projections: box (each face from one side), planar, cylindrical and spherical — for cylindrical/spherical, triangles crossing the seam are rebuilt so the texture does not “wrap back”. Controls: repeats, rotation, pattern size, tint, metallic, roughness and whether the model's colors stay with the texture.
- **3D skeleton:** creates an automatic skeleton and binds the mesh to it (skin with up to 4 joints per vertex, soft blending): **Humanoid** (21 joints from the model's proportions, standing and facing forward), **Spine** (vertical chain) and **Chain** (along the longest axis: snakes, tails). The blending smoothness is adjustable.
- **3D animation:** creates a **looping** animation and writes it into the GLB (playable in other programs): for the whole model — spin, bounce, float, pulse, wobble — and, with a skeleton, **sway** (every joint, in shifted phase), **walk** and **wave** (humanoid skeleton) and **breathe**. Duration and intensity are adjustable; one animation per model (the new one replaces the old one).
- **3D viewer:** now shows the **texture** (each face's color from the map, at the face's center), draws the **skeleton** on top (on/off) and **plays the file's animation** (skinning computed in the browser; Pause/Play button). It also reads GLBs with a skeleton and animation made outside OpenFlow.
- **Core (`model3d_ops.py`):** reads GLB/OBJ completely (geometry, colors, UV, texture, skeleton, animation) and writes a full GLB 2.0; it includes the Python reference of the pose, used to check the viewer.

### Tested
- `tests/test_3d_nodes_v058.py` (28 tests): reading and writing (GLB, OBJ with UV, foreign GLB with transforms), skeletons (joint counts, valid weights, each limb bound to its own joints on a box figure, limits), animations (closed loops, friendly errors without a skeleton, the right joints for walk/wave/breathe, valid GLB), textures (UVs, seams, patterns, embedded image, skin copied to duplicated vertices), the nodes in the engine chained with a texture image (and the error messages) and the viewer **running in Node**: it must give the same pose as the Python reference for every animation, at several instants.
- Browser test (`model3d_v058_ui.js`): palette, forms, the whole chain in a project, joints/animation/texture text in the viewer, Pause/Play (paused frame × moving animation) and the skeleton on/off.
- The test that runs every node type now includes a 3D model as input.

### Fixed along the way
- The **Media** node could not be connected to 3D model ports: now it can (Python and interface).

### Not verified yet
- **Real models:** I tested with the demo mesh, a box figure and hand-built GLBs; not with models generated by Shap-E, TripoSR or Hunyuan3D, nor with characters downloaded from the internet. The skeleton is **procedural and approximate** (from the model's bounding box; “Humanoid” assumes a standing body facing +z with arms at the sides, and warns when the model is wider than tall): on real characters the weights may need manual adjustment, which OpenFlow does not have.
- **Other programs:** the written GLB follows the specification (checked through counts, types and references), but I did not open it in Blender, Three.js or any other viewer.
- **Limits:** a single skin; joints without rest rotation; all meshes in the file become one when passing through one of the nodes; animations from outside files come in as joint tracks (cubic interpolation becomes linear); the automatic skeleton takes up to 400 thousand vertices (with the weights, it can take minutes on big meshes); the viewer only plays the animation of meshes up to 60 thousand vertices.
- **Texture in the viewer** is a preview (one color per face); the file carries the full texture. OBJ carries no texture (only the resulting GLB).
- There is no rendering of the animation to video (only in the viewer and the GLB) nor manual weight painting; I also did not test on Windows or macOS.

## [0.57.0] — 2026-11-16

### Fixed — “out of memory” when generating with Qwen-Image 2.1 (and other models through sd-cli)
The error in the screenshot (`sd-cli failed (code -9): the system ended it for lack of memory (RAM)…`, in a project with Qwen-Image 2.1 Q4_0, one reference image and a Style Folder) showed generic advice and a leftover progress bar. Code -9 is the operating system killing the program for lack of RAM; in the screenshot's log that happened **while loading the model weights** (`6/297 – 0.00MB/s`), after the Qwen3-VL text encoder (≈ 5 GB) and the vision projector were already in memory.
- **The message now says what happened and what to do:** at which stage memory ran out (loading the weights, or during the generation steps), how much the loaded files add up to (e.g. “model 4.2 GB, text encoder 5.1, vision projector 1.2, VAE 0.3”), how much RAM the computer has and how much is free, and the ways out: remove the reference image (the ≈ 1.2 GB vision projector is only loaded with it), use a smaller text encoder (Qwen3-VL-8B Q3_K_XL or Q2_K_XL, given in the node's “extra”) or a smaller quantization of the model, and close other programs. When it ran out during the weights, the message says that **lowering the resolution does not help** (before, that was exactly the advice).
- **Automatic second attempt only when it makes sense:** if memory runs out **during the generation steps** (where resolution matters), OpenFlow retries once at 0.7× the size (multiples of 16) and says so in the node log. During the weights or at an unknown stage it does not repeat (each attempt reloads ≈ 11 GB and would waste minutes).
- **Cut progress bar in the message:** lines like `| ## 6/297 - 0.00MB/s` (without enough `###` for v0.56 to recognize) still got into the error text. Now any progress line (bytes/s, s/it, it/s) is removed.

### Tested
- `tests/test_qwen21_memory_v057.py` (10 tests): the stage from the bar's unit (bytes/s → weights, s/it → steps), the cut bar, a program that kills itself with SIGKILL like the OOM killer (`OutOfMemory` with the stage, still a `ProviderError`), the message with file sum, RAM and tips (with and without references, without hardware info), the second attempt at 704×400 from 1024×576 and no attempt during the weights, at an unknown stage and on other errors. Without the fix, they fail.

### Not verified yet
- **I did not reproduce the out-of-memory for real** (nor do I have your machine): the diagnosis comes from the screenshot's log; the file sum and the tips are estimates from on-disk sizes, not from the memory sd-cli really asks for.
- **I did not reduce memory use itself:** OpenFlow still loads the text encoder (≈ 5 GB), the projector (≈ 1.2 GB) and the model together when there is a reference image. If your RAM cannot hold that, the way out is one of those in the message (smaller encoder/quantization, or no reference). In a later version I can look into unloading the encoder before loading the model, if your sd-cli allows it.
- Choosing the smaller encoder is still manual (the node's “extra” field); OpenFlow still uses the first file it finds in the folder.
- The 7-image Style Folder was not the cause here: with a reference connected, style images do not become references (only the style text goes into the prompt).

## [0.56.0] — 2026-11-16

### Fixed — generating and editing with Qwen-Image 2.1 (ChatR Labs “Uncensored Omni Quantized”)
I read the model card (the ChatR Labs recipe) and OpenFlow's generate/edit path (sd-cli and library) and tested each point with a simulated sd-cli:
- **Unreadable error message:** when sd-cli failed, the screen showed the last 500 characters of the log with the progress bars (`| | ######## 98/98 - 739MB/s`) mixed in, hiding the cause (this was the case in the screenshot). Now the message drops the bars and the leading `---`/`|` of the lines, shows the error lines (`[E] …`) first and only then the log's final context.
- **Vision-projector error with an explanation:** if sd-cli still answers “requires Qwen3-VL vision weights / --llm_vision”, the node now says what is missing (the Qwen3-VL mmproj, ≈ 1.2 GB), where the “Download the support files” button is and the file's name in the folder.
- **Reference limit taken from the wrong model:** when generating through sd-cli, the maximum number of references came from the **default model in settings**, not the model chosen in the node. With a default model that takes 1 image (e.g. Z-Image) and Qwen-Image 2.1 (4 images) in the node, only the first reference was used, silently. Now the node's model rules.
- **Negative prompt:** the card says an omitted or empty negative turns true CFG off and tells you to use a single space. If the node's negative is empty, OpenFlow now sends a space (this family only; other models do not change), both to sd-cli (`-n`) and to the library.

### Tested
- `tests/test_qwen21_bugs_v056.py` (8 tests): the message built from the screenshot's log (no bars, error first, size cap), a real failing program run, the reference limit with a default model different from the node's, the negative (empty, spaces only, filled, other family), sd-cli's arguments and the projector message. Without the fix, 7 fail.

### Not verified yet
- **I did not run Qwen-Image 2.1 for real** (nor sd-cli): everything was tested up to the command line and with simulated answers. I do not know whether, in sd-cli, a one-space negative changes the result compared with an empty one (the card talks about the diffusers pipeline); it is the author's recipe and harmless.
- **Sampler:** the card recommends `er_sde` with the `simple` scheduler (ComfyUI); OpenFlow stays on `euler`, because I did not confirm your sd-cli version has `er_sde`. If it does, you can switch in “extra” (`sample_method`).
- **Resolution:** the card recommends 768×1152 or 1024×1024; the node's proportions are as usual.
- Extremely thin reference images (80:1) still have their aspect limited to 256 px on the short side (as in v0.51).

## [0.55.0] — 2026-11-16

### Fixed — Qwen-Image 2.1 (Uncensored Omni Quantized) when editing images
- **The error in the screenshot:** editing an image with `qwen-image-2.1-step90000-Q4_0.gguf` (ChatR Labs), sd-cli failed with “Qwen Image 2.1 editing requires Qwen3-VL vision weights; provide --llm_vision or a combined encoder … failed to encode prompt”. Qwen-Image 2.1 reads the reference image through the **Qwen3-VL-8B vision projector (mmproj)**, and OpenFlow only downloaded and passed the VAE and the text encoder.
- **Now:** OpenFlow knows that file (`mmproj-F16.gguf` from `unsloth/Qwen3-VL-8B-Instruct-GGUF`, ≈ 1.2 GB). It is **downloaded along with the model** (and shows up in “Download the support files” for people who already have the model), is stored as `Qwen3-VL-8B-Instruct-mmproj-F16.gguf` (Qwen2.5-VL's is also called `mmproj-F16.gguf`, and the two must not overwrite each other) and is passed to sd-cli as `--llm_vision` when you edit.
- **Only required for editing:** generating from text alone keeps working without it (nobody who already had the model loses anything), and in that case OpenFlow does not even load it (≈ 1.2 GB less memory). If you edit without the file, the node explains what is missing and offers the download button, instead of sd-cli's technical error. Anyone who gave their own mmproj in the node's “extra” field is not blocked.

### Tested
- `tests/test_qwen21_vision_v055.py` (10 tests): the family knows the file and where to download it; it is found next to the model and is not mistaken for the text encoder or for Qwen2.5-VL's mmproj; download plan and status; old installs without the file still load for generation; editing without the file gives the clear message (without reaching sd-cli); generating does not load it; editing with it passes it to the loader; sd-cli gets `--llm_vision`. Without the fix, 8 fail.

### Not verified yet
- **I did not run the real model** (nor sd-cli with Qwen-Image 2.1): the cause comes from sd-cli's own message in the screenshot and the fix was tested up to the command line it receives. If editing still fails after downloading the mmproj, the new error (or sd-cli's log) shows what is left.
- I chose the **F16** mmproj; if your sd-cli version requires another precision or a “combined” encoder (the message mentions that option), tell me and I'll adjust.
- Qwen-Image 2.1 models that are already downloaded get the file through the “Download the support files” button; I do not download anything on my own.
- The numbering skipped v0.54: no version with that number was requested.

## [0.53.0] — 2026-11-16

### Fixed — general improvements 6 (sounds, voices and 3D models)
I generated sounds (effects and music, 1 to 120 s, 16 descriptions, odd characters), voices (0.5×–2×, letterless, long and emoji texts) and 3D models (GLB and OBJ, 11 prompts, 2 seeds) with the demo provider, checked the output files, and read the code of the local providers and the 3D viewer. The defects found:
- **Demo voice silent on numbers and symbols:** a text like “123” or “50% of $20” came out in total silence. Each digit now becomes a syllable, and symbols become a short hiss. Long texts were silently cut at the first 1,200 characters; now up to 3,000.
- **A 1 s music clip came out at 2 s** on the demo provider; it now honors the duration.
- **Local-model audio with NaN/infinity** became blown-out noise (and a NaN peak went unnoticed), and an empty output crashed with a technical error. Now invalid values become silence and an empty output gives a clear message. Asking a local model (which generates up to 30 s) for more than 30 s of sound now says so in the node log instead of silently shortening it.
- **A valid GLB refused on upload:** a file without indices (common in exporters), with several meshes or with trailing bytes was rejected as “not a valid GLB 3D model”. Validation now counts every mesh, accepts primitives without indices and ignores points and lines.
- **OBJ could not be uploaded:** only GLB was accepted. Now a text OBJ with a mesh (numeric vertices and faces pointing at existing vertices, including quads and negative indices) enters as a 3D model; a broken OBJ gets a clear message.
- **The 3D viewer showed only the first mesh, without the nodes' placement:** a multi-part GLB (as exported by Blender and trimesh) looked incomplete or misaligned. Now it reads every mesh in the scene with each node's transform (matrix or translation/rotation/scale), 8/16/32-bit indices, triangle strips and fans, normalized byte/short colors (they used to blow out to white), the material color when there is no per-vertex color, and finds the data chunk without assuming it follows the JSON. OBJ with negative indices, CRLF and invalid faces is also read.
- **Transparent image into 3D:** TripoSR and Hunyuan3D separate the object from the background by transparency, but the connected image arrived already flattened over white (since v0.51). They now receive the cut-out with transparency when it exists; Shap-E stays on RGB.

### Tested
- `tests/test_3d_audio_v053.py` (18 tests): GLB/OBJ validation, upload through the API, the viewer's reader (really run with Node on GLBs without indices, strip/fan, uint16, two instances/parent with scale, normalized colors and material color, negative/CRLF OBJ), voice with numbers, a 1 s music clip, NaN audio and transparency. Without the fix, 15 fail.
- The demo-provider sound/voice/3D battery (about 120 sound cases, 30 voice and 44 3D) ended with no defects other than the ones below.

### Not verified yet
- **No real local model was run** (MusicGen, Kokoro/Orpheus, Shap-E, TripoSR, Hunyuan3D): the fixes in them (alpha, NaN, 30 s notice) come from reading the code and testing the functions, not from a real generation.
- On the demo provider, a short sound effect (laser, explosion) has the effect's own duration rather than the node's; that is how it was designed and I did not change it.
- The viewer draws a textured mesh with the material color only (no textures); a GLB with animations, skeletons or KHR_draco_mesh_compression is not supported and shows the error.
- An OBJ inside an uploaded ZIP/RAR is still not recognized (direct upload only).
- There is no 3D model editing in the Canvas (the node generates, the viewer shows): I did not create one.

## [0.52.0] — 2026-11-16

### Fixed — general improvements 5 (images and videos)
I ran the video and audio nodes and the Editor through a battery of difficult inputs: 1-frame and 0.1 s clips, 16×16, 333×221 (odd), vertical and ultrawide videos, at 5 and 59.94 fps, without audio, WebM, GIF, rotated; trims, speeds (0.25×–4×), looks, aspect changes, loops, audio swaps, joining clips, GIF, final video; and the Editor with clips past the end of the file, fades longer than the clip, 4× scale, canvases from 160×160 to 3840×160, text with quotes, `%`, `:`, emoji and 300 characters, overlapping clips, a missing file and 40 clips. Nearly everything was already right; the defects found:
- **Audio inside a video container was treated as video.** A voice note saved as `.mp4`/`.mov`/`.3gp`, or a `.webm`/`.mka` recording with sound only, came in as “video” and broke the video nodes with a technical ffmpeg error; an Ogg video (`.ogv`) came in as “audio” and vanished from the video ports. Now the type comes from the tracks inside the file (direct upload, files inside ZIP/RAR and attachments).
- **“Trim audio” past the end saved an empty file** without a warning (and the output showed as a broken audio). Now the node says “The cut start is past the end of the audio”, the “Remove silences” node with a threshold that was too high saved a 0 s audio instead of saying “The audio is empty”; and any audio node that ended up silent (e.g. speeding a 0.05 s clip up 5×) says “The result has no audio…” instead of saving the empty file.

### Tested
- `tests/test_general_v052.py` (8 tests): type from tracks (audio in .mp4/.mov/.3gp/.webm/.mka, video with and without sound, `.ogv`), upload through the API, trim past the end, an effect that empties the audio and a valid trim. Without the fix, 7 fail.
- The full video battery (13 videos × hundreds of parameters) and the Editor one (about 170 cases) ended with no other defects (only expected errors with clear messages, like “connect a video” for a GIF on a video port).

### Not verified yet
- Files uploaded before the fix keep their old classification (just upload them again).
- Formats OpenFlow does not recognize (`.mpg`, `.flv`, `.ts`) are still refused on upload with the invalid-format message; I did not add them because the browser cannot play them in the preview.
- A video file with no video track that gets through as video by another path (e.g. generated by a provider) would still give the technical ffmpeg error.
- I did not test large videos (minutes/GB) or rare codecs; real local video models do not run in this environment.

## [0.51.0] — 2026-11-16

### Fixed — bugs when editing images in Canvas nodes
I looked for errors by running the image-editing nodes (Resize, Filters and color, Text on image, Crop, Watermark, Collage, Thumbnail, Final image and the “Edit” mode of the Image node) with difficult inputs: 1 px, very thin, transparent, grayscale, palette, 16-bit, JPEG, WebP, GIF and BMP images. That turned up 14 failures and 3 silent defects:
- **Resize with width or height at 0 (automatic)** failed on very thin images (e.g. 50×4000 with height 50 gave width 0 and ffmpeg gave up). Now the other side follows the aspect ratio, never below 1 px. As a bonus, “automatic” no longer rounds to an even number.
- **Crop** could ask for 0 px (a 1% manual crop on a thin image, a 21:9 ratio on a 1 px image) and failed. Now a crop is always at least 1 px and, if it goes past the image edge, it snaps to the edge and warns (“The crop went past the image edge”).
- **Filters (blur, sharpen, VHS) on a 1 px image** made ffmpeg corrupt memory and exit. Now the effect is skipped with a warning.
- **Phone photos (EXIF orientation) came out sideways:** in the Image node's “Edit” mode the reference was read without its orientation, and the image nodes depended on the ffmpeg version (new ones rotate by themselves, old ones don't). Now the photo is rotated on input and the result is the same with any ffmpeg.
- **Transparency turned black (or the hidden color):** an edit reference with a transparent background was converted straight to RGB. Now it is composited over white.
- **16-bit PNGs came out all white** as an edit reference. Now they keep their brightness.
- The “result is almost identical to the input” check and sd-cli (GGUF models) use the same corrected reading.

### Tested
- `tests/test_edit_images_v051.py` (12 tests): reading transparency, EXIF, 16-bit and formats; automatic sizes, Resize modes, 0 px and edge crops, 1 px blur, EXIF photo and BMP. With the old code, 10 of them fail.
- The sweep (14 images × hundreds of parameters, plus collage, thumbnail, final image and the Edit mode with the demo provider) ended with 0 problems.

### Not verified yet
- **Real local models** (FLUX, Qwen-Image-Edit, etc.) were not run here: “Edit” mode was tested with the demo provider and the reference reading itself, not with a real model.
- The output size of “Edit” on a local model keeps a 256 px minimum per side: an extremely thin image (e.g. 80:1) comes out with a limited aspect ratio.
- Transparency: the reference is composited over **white**; no model receives the transparency channel. Watermark and Text on image keep preserving the input image's alpha.
- I did not review the Canvas interface (dragging, zoom, viewer) for editing bugs: the sweep covered the node engine.

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
