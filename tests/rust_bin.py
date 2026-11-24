"""Localiza (e, se preciso, compila) o binário `flow` em Rust para os testes de paridade e de API (v0.91)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
_CACHED: Optional[Path] = None


def flow_bin(build: bool = True) -> Optional[Path]:
    """Caminho do `flow`: OPENFLOW_FLOW_BIN, rust/target/{release,debug}/flow ou (build=True e há cargo) compila o de depuração. None se não houver."""
    global _CACHED
    if _CACHED and _CACHED.is_file():
        return _CACHED
    env = os.environ.get("OPENFLOW_FLOW_BIN")
    if env and Path(env).is_file():
        _CACHED = Path(env)
        return _CACHED
    exe = "flow.exe" if os.name == "nt" else "flow"
    for kind in ("release", "debug"):
        p = ROOT / "rust" / "target" / kind / exe
        if p.is_file():
            _CACHED = p
            return p
    if build and shutil.which("cargo"):
        r = subprocess.run(["cargo", "build", "--manifest-path", str(ROOT / "rust" / "Cargo.toml")], capture_output=True, text=True)
        p = ROOT / "rust" / "target" / "debug" / exe
        if r.returncode == 0 and p.is_file():
            _CACHED = p
            return p
    return None
