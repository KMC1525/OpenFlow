# Contributing to OpenFlow

Thanks for helping! A short guide (the [Portuguese version](CONTRIBUTING.pt-BR.md) says the same).

- **Run the tests** before opening a pull request: `python -m unittest discover -s tests -t .` (Python tests, plus the Chromium tests when Node + Playwright are available), `cargo test --release --manifest-path openflow/native/Cargo.toml` and `node tests/js/i18n_check.mjs`.
- **Python ≥ 3.9**, standard library only in the core (extras live in `pyproject.toml`). No `match`, no runtime `X | Y`.
- **Rust ↔ Python parity:** every function of the Rust core (`openflow/native/src`) needs an equivalent in `openflow/native/__init__.py` with the same behavior. Changing the interface means bumping `ABI` (Python) and `flow_abi_version` (Rust) while keeping old libraries working.
- **Strings:** the interface and the terminal are Portuguese-first with an English translation (`openflow/web/js/en.js`, `openflow/term_en.py`, installers use `L "pt" "en"`). A new phrase without a translation fails the tests.
- **Docs:** when behavior, install steps, commands or limits change, update `README.md` + `README.pt-BR.md` and `CHANGELOG.md` + `CHANGELOG.en.md` (per version: what changed and, honestly, what was not verified).
- **Safety:** treat files, archives, URLs and AI output as untrusted (validate paths, sizes, types, JSON). The AI produces data (JSON) that the engine validates, never code to run.
- Regression fixes come with a test that reproduces the bug. Never claim in the docs what was not tested.
