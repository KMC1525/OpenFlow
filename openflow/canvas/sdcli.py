"""O `sd-cli` pré-compilado da stable-diffusion.cpp: a saída quando a biblioteca Python (PyPI 0.4.7) não reconhece um modelo novo e a pessoa não tem (ou não quer instalar) git, cmake e um compilador.

A stable-diffusion.cpp publica a cada commit um executável pronto para Linux, macOS e Windows (ver as Releases de leejet/stable-diffusion.cpp). O OpenFlow o baixa **só quando a pessoa pede** (botão no nó,
`flow libs --sd-cli`) para `<dados>/bin/sd-cpp/` e passa a rodá-lo como processo à parte quando a biblioteca falha com «get sd version from file failed» — com os MESMOS arquivos de apoio e parâmetros
(`support.FAMILIES`). O executável vem por HTTPS do repositório oficial; nada é baixado sem pedido e nada é instalado fora da pasta de dados do OpenFlow.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..providers import ProviderError
from ..util import flow_home, ssl_context

REPO = "leejet/stable-diffusion.cpp"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE = "sd-cli.exe" if os.name == "nt" else "sd-cli"


def bin_dir() -> Path:
    return flow_home() / "bin" / "sd-cpp"


def find() -> Optional[Path]:
    """O `sd-cli` em uso: `OPENFLOW_SD_CLI`, o baixado pelo OpenFlow ou um que já esteja no PATH (`sd-cli`)."""
    env = os.environ.get("OPENFLOW_SD_CLI")
    if env and Path(env).is_file():
        return Path(env)
    try:
        hit = next(iter(sorted(bin_dir().rglob(EXE))), None)
    except OSError:
        hit = None
    if hit and hit.is_file():
        return hit
    which = shutil.which("sd-cli")
    return Path(which) if which else None


def backend() -> str:
    """cpu (padrão, funciona em qualquer máquina), vulkan ou cuda12 (`OPENFLOW_SD_BACKEND`)."""
    v = (os.environ.get("OPENFLOW_SD_BACKEND") or "cpu").strip().lower()
    return v if v in ("cpu", "vulkan", "cuda", "cuda12") else "cpu"


def pick_asset(assets: Sequence[Dict[str, Any]], system: str, machine: str, want: str = "cpu") -> Optional[Dict[str, Any]]:
    """O arquivo `.zip` da Release que serve a este sistema. Os nomes seguem `sd-<branch>-<commit>-bin-<SO>-<distro>-<versão>-<arq>[-vulkan|-rocm-…].zip` (Linux/macOS) e
    `sd-<branch>-<commit>-bin-win-<cpu|cuda12|vulkan>-x64.zip` (Windows)."""
    m = (machine or "").lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "x86_64" if m in ("x86_64", "amd64", "x64") else m
    want = "cuda12" if want == "cuda" else want
    zips = [a for a in assets if isinstance(a, dict) and str(a.get("name", "")).startswith("sd-") and str(a.get("name", "")).endswith(".zip") and "-bin-" in str(a.get("name", ""))]
    sysname = (system or "").lower()
    if sysname == "windows":
        if arch != "x86_64":
            return None
        for key in (want, "cpu", "avx2"):
            hit = next((a for a in zips if re.search(rf"-bin-win-{key}-x64\.zip$", a["name"])), None)
            if hit:
                return hit
        return None
    if sysname == "darwin":
        return next((a for a in zips if re.search(rf"-bin-Darwin-.*-{arch}\.zip$", a["name"]) and "vulkan" not in a["name"]), None)
    if sysname == "linux":
        cands = [a for a in zips if re.search(rf"-bin-Linux-.*-{arch}(-[\w.]+)?\.zip$", a["name"])]
        if want == "vulkan":
            hit = next((a for a in cands if a["name"].endswith("-vulkan.zip")), None)
            if hit:
                return hit
        return next((a for a in cands if not re.search(r"-(vulkan|rocm[\w.-]*)\.zip$", a["name"])), None)
    return None


def latest_release() -> Dict[str, Any]:
    from ..providers import http

    return http.get_json(RELEASES_API, {"Accept": "application/vnd.github+json"}, timeout=30)


def _download(url: str, dest: Path, progress: Optional[Callable[[int, int], None]], cancelled: Callable[[], bool]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenFlow"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if cancelled():
                    raise ProviderError("cancelado")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    except OSError as exc:
        raise ProviderError(f"Não consegui baixar o sd-cli ({exc}). Confira a internet e tente de novo.") from None


def install(progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Path:
    """Baixa o executável da Release mais nova para `<dados>/bin/sd-cpp/` e confere que ele roda. Devolve o caminho do `sd-cli`."""
    from .. import archives

    note("Procurando a versão mais nova da stable-diffusion.cpp…")
    try:
        rel = latest_release()
    except ProviderError as exc:
        raise ProviderError(f"Não consegui consultar as versões da stable-diffusion.cpp ({exc}).") from None
    asset = pick_asset(rel.get("assets") or [], platform.system(), platform.machine(), backend())
    if not asset:
        raise ProviderError(f"Não há executável pronto da stable-diffusion.cpp para {platform.system()} {platform.machine()} nesta versão ({rel.get('tag_name', '?')}). "
                            "Use a compilação (git + compilador C/C++) ou aponte OPENFLOW_SD_CLI para um sd-cli seu.")
    dest = bin_dir()
    tmp_zip = dest.parent / (asset["name"] + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    note(f"Baixando {asset['name']} (≈ {int(asset.get('size') or 0) / 1e6:.0f} MB)…")
    _download(asset["browser_download_url"], tmp_zip, progress, cancelled)
    new = dest.parent / (dest.name + ".new")
    shutil.rmtree(new, ignore_errors=True)
    try:
        archives.extract(tmp_zip, new, asset["name"])
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"O pacote baixado não abriu ({exc}).") from None
    finally:
        tmp_zip.unlink(missing_ok=True)
    exe = next(iter(sorted(new.rglob(EXE))), None)
    if not exe:
        shutil.rmtree(new, ignore_errors=True)
        raise ProviderError("O pacote baixado não traz o sd-cli.")
    for f in new.rglob("*"):
        if f.is_file() and (f.suffix == "" or f.name == EXE):
            try:
                f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                pass
    shutil.rmtree(dest, ignore_errors=True)
    new.rename(dest)
    exe = next(iter(sorted(dest.rglob(EXE))), exe)
    ok, out = _probe(exe)
    if not ok:
        raise ProviderError("O sd-cli baixado não roda neste computador" + (f": {out[-200:]}" if out else "") + ". Tente OPENFLOW_SD_BACKEND=cpu ou compile a biblioteca.")
    (dest / "VERSION").write_text(str(rel.get("tag_name") or asset["name"]), encoding="utf-8")
    note("sd-cli pronto.")
    return exe


def _probe(exe: Path) -> Tuple[bool, str]:
    try:
        r = subprocess.run([str(exe), "-h"], capture_output=True, text=True, timeout=30, cwd=str(exe.parent), env=_env(exe))
        return r.returncode == 0 and "usage" in (r.stdout + r.stderr).lower() or "--diffusion-model" in (r.stdout + r.stderr), (r.stderr or r.stdout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def _env(exe: Path) -> Dict[str, str]:
    env = dict(os.environ)
    d = str(exe.parent)
    if sys_platform() == "linux":
        env["LD_LIBRARY_PATH"] = d + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    elif sys_platform() == "darwin":
        env["DYLD_LIBRARY_PATH"] = d + (os.pathsep + env["DYLD_LIBRARY_PATH"] if env.get("DYLD_LIBRARY_PATH") else "")
    return env


def sys_platform() -> str:
    return platform.system().lower()


# ----------------------------------------------------------------------------- linha de comando

#: parâmetro de carga da biblioteca Python → opção do sd-cli (caminhos de arquivo)
LOAD_FLAGS = {"diffusion_model_path": "--diffusion-model", "model_path": "-m", "vae_path": "--vae", "llm_path": "--llm", "t5xxl_path": "--t5xxl", "clip_l_path": "--clip_l", "clip_g_path": "--clip_g",
              "tokenizer_path": "--tokenizer", "llm_vision_path": "--llm_vision"}
#: parâmetro de carga booleano → opção
LOAD_SWITCHES = {"offload_params_to_cpu": ["--offload-to-cpu"], "diffusion_flash_attn": ["--flash-attn", "off,diffusion=on"], "keep_clip_on_cpu": ["--clip-on-cpu"], "vae_tiling": ["--vae-tiling"]}
#: parâmetro de geração → opção
RUN_FLAGS = {"cfg_scale": "--cfg-scale", "sample_steps": "--steps", "sample_method": "--sampling-method", "flow_shift": "--flow-shift", "strength": "--strength", "guidance": "--guidance",
             "video_frames": "--video-frames", "fps": "--fps"}


def build_args(exe: Path, load: Dict[str, Any], run: Dict[str, Any], *, prompt: str, width: int, height: int, seed: int, negative: str = "", refs: Sequence[Path] = (), init: Optional[Path] = None,
               out: Path, video: bool = False) -> Tuple[List[str], List[str]]:
    """(argumentos, avisos) do `sd-cli`: arquivos do modelo e de apoio, parâmetros da geração, imagens de referência (`-r`) ou inicial (`-i`)."""
    args = [str(exe), "-M", "vid_gen" if video else "img_gen"]
    warns: List[str] = []
    for k, v in load.items():
        if k in LOAD_FLAGS and isinstance(v, str) and v:
            args += [LOAD_FLAGS[k], v]
        elif k in LOAD_SWITCHES:
            if v:
                args += LOAD_SWITCHES[k]
        else:
            warns.append(k)
    for k, v in run.items():
        if k in RUN_FLAGS and v is not None:
            args += [RUN_FLAGS[k], str(v)]
        elif k not in ("prompt", "width", "height", "seed", "negative_prompt", "ref_images", "init_image"):
            warns.append(k)
    args += ["-p", prompt, "-W", str(int(width)), "-H", str(int(height)), "-s", str(int(seed)), "-o", str(out)]
    if negative:
        args += ["-n", negative]
    for r in refs:
        args += ["-r", str(r)]
    if init:
        args += ["-i", str(init)]
    return args, warns


def run(args: Sequence[str], exe: Path, cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None, timeout: float = 7200) -> str:
    """Roda o sd-cli (com cancelamento) e devolve as últimas linhas do log; levanta ProviderError com o motivo se falhar."""
    tail: List[str] = []
    p = subprocess.Popen(list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", cwd=str(exe.parent), env=_env(exe), bufsize=1)
    start = time.time()
    try:
        assert p.stdout is not None
        for line in p.stdout:
            line = line.rstrip()
            if line:
                tail = (tail + [line])[-12:]
                if "|" in line and "/" in line:   # barra de progresso das etapas
                    note(line[-90:])
            if cancelled():
                p.terminate()
                raise ProviderError("cancelado")
            if time.time() - start > timeout:
                p.terminate()
                raise ProviderError("O sd-cli demorou demais e foi interrompido.")
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
        if p.stdout:
            p.stdout.close()
    if p.returncode != 0:
        oom = " O sistema o encerrou por falta de memória (RAM): use uma resolução ou quantização menores, ou feche outros programas." if p.returncode in (-9, 137) else ""
        raise ProviderError(f"O sd-cli falhou (código {p.returncode}):{oom} " + " | ".join(tail)[-500:])
    return "\n".join(tail)


def generate_image(exe: Path, load: Dict[str, Any], run_params: Dict[str, Any], *, prompt: str, width: int, height: int, seed: int, negative: str = "", refs: Sequence[bytes] = (),
                   init: Optional[bytes] = None, cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Tuple[bytes, List[str]]:
    """Uma imagem pelo sd-cli: grava as referências em arquivos temporários, roda e devolve (PNG, avisos)."""
    with tempfile.TemporaryDirectory(prefix="flow-sdcli-") as tmp:
        d = Path(tmp)
        ref_files = []
        for i, data in enumerate(refs):
            f = d / f"ref{i}.png"
            f.write_bytes(data)
            ref_files.append(f)
        init_file = None
        if init:
            init_file = d / "init.png"
            init_file.write_bytes(init)
        out = d / "out.png"
        args, warns = build_args(exe, load, run_params, prompt=prompt, width=width, height=height, seed=seed, negative=negative, refs=ref_files, init=init_file, out=out)
        run(args, exe, cancelled, note)
        if not out.is_file():
            raise ProviderError("O sd-cli terminou sem gerar a imagem.")
        return out.read_bytes(), warns


def generate_video(exe: Path, load: Dict[str, Any], run_params: Dict[str, Any], *, prompt: str, width: int, height: int, seed: int, fps: int, init: Optional[bytes] = None,
                   cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Tuple[List[bytes], List[str]]:
    """Um vídeo pelo sd-cli: os quadros saem como PNG numerados (o OpenFlow monta o MP4 com o ffmpeg) → (quadros, avisos)."""
    with tempfile.TemporaryDirectory(prefix="flow-sdcli-") as tmp:
        d = Path(tmp)
        init_file = None
        if init:
            init_file = d / "init.png"
            init_file.write_bytes(init)
        args, warns = build_args(exe, load, {**run_params, "fps": fps}, prompt=prompt, width=width, height=height, seed=seed, init=init_file, out=d / "frame_%05d.png", video=True)
        run(args, exe, cancelled, note)
        frames = sorted(d.glob("frame_*.png"))
        if not frames:
            raise ProviderError("O sd-cli terminou sem gerar os quadros do vídeo.")
        return [f.read_bytes() for f in frames], warns
