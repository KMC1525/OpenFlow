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
    if hit and hit.is_file() and (bin_dir() / "VERSION").is_file():   # sem VERSION a instalação não terminou ou o pacote não passou no teste (ex.: glibc antiga): não serve
        return hit
    which = shutil.which("sd-cli")
    return Path(which) if which else None


def _nvidia() -> bool:
    return shutil.which("nvidia-smi") is not None


def backend() -> str:
    """Tipo do `sd-cli`: cpu, vulkan ou cuda12. `OPENFLOW_SD_BACKEND` manda; senão vale Configurações → Desempenho → Rodar em:
    «CPU» = cpu; «GPU» = cuda12 (NVIDIA) ou vulkan (AMD/Intel; no macOS o executável padrão já usa a placa); «Automático» = cuda12 se há NVIDIA, senão cpu."""
    v = (os.environ.get("OPENFLOW_SD_BACKEND") or "").strip().lower()
    if v in ("cpu", "vulkan", "cuda", "cuda12"):
        return "cuda12" if v == "cuda" else v
    from .. import perf

    dev = perf.device()
    if dev == "cpu" or platform.system() == "Darwin":
        return "cpu"
    if _nvidia():
        return "cuda12"
    return "vulkan" if dev == "gpu" else "cpu"


def installed_backend() -> str:
    """O tipo do `sd-cli` que o OpenFlow baixou (vazio se não foi ele ou se não se sabe)."""
    try:
        return (bin_dir() / "BACKEND").read_text(encoding="utf-8").strip()
    except OSError:
        return ""



# glibc que cada versão do Ubuntu traz: os pacotes `Linux-Ubuntu-X` da Release foram compilados nela e só rodam em sistemas com glibc igual ou mais nova
UBUNTU_GLIBC = {"18.04": (2, 27), "20.04": (2, 31), "22.04": (2, 35), "24.04": (2, 39), "26.04": (2, 43)}
_GLIBC_MISSING = re.compile(r"GLIBC(?:XX)?_(\d+)\.(\d+)(?:\.\d+)?['`\"]? not found")


def glibc_version() -> Optional[Tuple[int, int]]:
    """A versão da glibc deste Linux (None fora do Linux ou em musl/Alpine, onde o pacote `Linux-Ubuntu` não serve)."""
    if sys_platform() != "linux":
        return None
    try:
        raw = os.confstr("CS_GNU_LIBC_VERSION") or ""
    except (ValueError, OSError, AttributeError):
        raw = ""
    m = re.search(r"glibc\s+(\d+)\.(\d+)", raw)
    if not m:
        lib, ver = platform.libc_ver()
        m = re.match(r"(\d+)\.(\d+)", ver) if lib == "glibc" else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def asset_glibc(name: str) -> Optional[Tuple[int, int]]:
    """A glibc mínima que o pacote exige (pela versão do Ubuntu no nome); None se o nome não diz."""
    m = re.search(r"-Linux-Ubuntu-(\d+\.\d+)-", name)
    if not m:
        return None
    if m.group(1) in UBUNTU_GLIBC:
        return UBUNTU_GLIBC[m.group(1)]
    yy = int(m.group(1).split(".")[0])
    return (2, 43 + 2 * max(0, (yy - 26) // 2))   # Ubuntu mais novo que a tabela: assume que exige pelo menos a glibc do último conhecido


class GlibcError(ProviderError):
    """O sd-cli não roda neste Linux por causa da glibc (o OpenFlow já apagou o executável baixado: o próximo pedido baixa o pacote compatível)."""


def glibc_error(text: str) -> str:
    """Se a saída do sd-cli é «GLIBC_x.y not found», a explicação em português (senão vazio)."""
    m = _GLIBC_MISSING.search(text or "")
    if not m:
        return ""
    have = glibc_version()
    return (f"O sd-cli baixado exige a glibc {m.group(1)}.{m.group(2)} e este Linux tem {'%d.%d' % have if have else 'uma mais antiga'}. "
            "O OpenFlow o apagou: ao gerar de novo ele baixa o pacote compatível com a sua glibc (Ubuntu 22.04/24.04). "
            "Se a Release só trouxer pacotes mais novos, compile a stable-diffusion.cpp (flow libs) ou aponte OPENFLOW_SD_CLI para um sd-cli seu.")


def pick_assets(assets: Sequence[Dict[str, Any]], system: str, machine: str, want: str = "cpu", glibc: Optional[Tuple[int, int]] = None) -> List[Dict[str, Any]]:
    """Os pacotes que servem a este sistema, do melhor para o pior. No Linux, com `glibc` conhecida, só entram os que ela consegue rodar, do mais novo para o mais antigo."""
    m = (machine or "").lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "x86_64" if m in ("x86_64", "amd64", "x64") else m
    want = "cuda12" if want == "cuda" else want
    zips = [a for a in assets if isinstance(a, dict) and str(a.get("name", "")).startswith("sd-") and str(a.get("name", "")).endswith(".zip") and "-bin-" in str(a.get("name", ""))]
    sysname = (system or "").lower()
    if sysname == "windows":
        if arch != "x86_64":
            return []
        out: List[Dict[str, Any]] = []
        for key in (want, "cpu", "avx2"):
            out += [a for a in zips if re.search(rf"-bin-win-{key}-x64\.zip$", a["name"]) and a not in out]
        return out
    if sysname == "darwin":
        return [a for a in zips if re.search(rf"-bin-Darwin-.*-{arch}\.zip$", a["name"]) and "vulkan" not in a["name"]]
    if sysname != "linux":
        return []
    cands = [a for a in zips if re.search(rf"-bin-Linux-.*-{arch}(-[\w.]+)?\.zip$", a["name"])]
    if glibc:
        cands = [a for a in cands if (asset_glibc(a["name"]) or (0, 0)) <= glibc]
    cands.sort(key=lambda a: asset_glibc(a["name"]) or (0, 0), reverse=True)   # estável: a ordem da Release vale dentro da mesma versão
    plain = [a for a in cands if not re.search(r"-(vulkan|rocm[\w.-]*)\.zip$", a["name"])]
    vulkan = [a for a in cands if a["name"].endswith("-vulkan.zip")]
    return (vulkan + plain) if want == "vulkan" else plain


def pick_asset(assets: Sequence[Dict[str, Any]], system: str, machine: str, want: str = "cpu", glibc: Optional[Tuple[int, int]] = None) -> Optional[Dict[str, Any]]:
    """O arquivo `.zip` da Release que serve a este sistema. Os nomes seguem `sd-<branch>-<commit>-bin-<SO>-<distro>-<versão>-<arq>[-vulkan|-rocm-…].zip` (Linux/macOS) e
    `sd-<branch>-<commit>-bin-win-<cpu|cuda12|vulkan>-x64.zip` (Windows)."""
    return next(iter(pick_assets(assets, system, machine, want, glibc)), None)


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
    """Baixa o executável da Release mais nova para `<dados>/bin/sd-cpp/` e confere que ele roda **antes** de trocar o que já existe. No Linux só tenta os pacotes que a glibc daqui roda
    (do mais novo para o mais antigo). Devolve o caminho do `sd-cli`."""
    from .. import archives

    note("Procurando a versão mais nova da stable-diffusion.cpp…")
    try:
        rel = latest_release()
    except ProviderError as exc:
        raise ProviderError(f"Não consegui consultar as versões da stable-diffusion.cpp ({exc}).") from None
    glibc = glibc_version()
    assets = rel.get("assets") or []
    cands = pick_assets(assets, platform.system(), platform.machine(), backend(), glibc)
    if not cands:
        if glibc and pick_assets(assets, platform.system(), platform.machine(), backend()):   # há pacotes, mas todos pedem uma glibc mais nova que a daqui
            need = min((asset_glibc(a["name"]) or (0, 0)) for a in pick_assets(assets, platform.system(), platform.machine(), backend()))
            raise ProviderError(f"Os executáveis prontos da stable-diffusion.cpp ({rel.get('tag_name', '?')}) exigem a glibc {need[0]}.{need[1]} ou mais nova e este Linux tem {glibc[0]}.{glibc[1]}. "
                                "Compile a stable-diffusion.cpp (flow libs; git + compilador C/C++) ou aponte OPENFLOW_SD_CLI para um sd-cli seu.")
        raise ProviderError(f"Não há executável pronto da stable-diffusion.cpp para {platform.system()} {platform.machine()} nesta versão ({rel.get('tag_name', '?')}). "
                            "Use a compilação (git + compilador C/C++) ou aponte OPENFLOW_SD_CLI para um sd-cli seu.")
    dest = bin_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = ""
    for asset in cands[:3]:
        tmp_zip = dest.parent / (asset["name"] + ".part")
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
        ok, out = _probe(exe)   # testa o pacote novo ANTES de trocar o que já está instalado: um pacote que não roda nunca fica no lugar
        if ok:
            shutil.rmtree(dest, ignore_errors=True)
            new.rename(dest)
            exe = next(iter(sorted(dest.rglob(EXE))), exe)
            (dest / "VERSION").write_text(str(rel.get("tag_name") or asset["name"]), encoding="utf-8")
            (dest / "BACKEND").write_text(backend(), encoding="utf-8")
            note("sd-cli pronto.")
            return exe
        shutil.rmtree(new, ignore_errors=True)
        last = glibc_error(out) or out[-200:]
        note(f"O pacote {asset['name']} não roda aqui" + ("; tentando outro…" if asset is not cands[:3][-1] and len(cands) > 1 else "."))
    raise ProviderError("O sd-cli baixado não roda neste computador" + (f": {last}" if last else "") + ". Tente OPENFLOW_SD_BACKEND=cpu ou compile a biblioteca.")


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
              "tokenizer_path": "--tokenizer", "llm_vision_path": "--llm_vision", "clip_vision_path": "--clip_vision", "high_noise_diffusion_model_path": "--high-noise-diffusion-model"}
#: parâmetro de carga booleano → opção
LOAD_SWITCHES = {"offload_params_to_cpu": ["--offload-to-cpu"], "diffusion_flash_attn": ["--flash-attn", "off,diffusion=on"], "keep_clip_on_cpu": ["--clip-on-cpu"], "vae_tiling": ["--vae-tiling"]}
#: parâmetro de geração → opção
RUN_FLAGS = {"cfg_scale": "--cfg-scale", "sample_steps": "--steps", "sample_method": "--sampling-method", "flow_shift": "--flow-shift", "strength": "--strength", "guidance": "--guidance",
             "video_frames": "--video-frames", "fps": "--fps", "high_noise_cfg_scale": "--high-noise-cfg-scale", "high_noise_sample_method": "--high-noise-sampling-method",
             "high_noise_sample_steps": "--high-noise-steps"}


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


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_STEPS = re.compile(r"(\d+)/(\d+)(?:\s*-\s*([\d.]+\s*\S*?(?:/s|s/it|it/s)))?\s*$")


def progress_text(line: str) -> str:
    """Uma linha do sd-cli sem códigos de terminal (o “[K” que apagava a linha aparecia na tela) e só com o último estado da barra."""
    line = _ANSI.sub("", line).replace("\x1b", "")
    return (line.split("\r")[-1] if "\r" in line else line).strip()


def run(args: Sequence[str], exe: Path, cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None, timeout: float = 7200) -> str:
    """Roda o sd-cli (com cancelamento) e devolve as últimas linhas do log; levanta ProviderError com o motivo se falhar."""
    tail: List[str] = []
    p = subprocess.Popen(list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", cwd=str(exe.parent), env=_env(exe), bufsize=1)
    start = time.time()
    try:
        assert p.stdout is not None
        for line in p.stdout:
            line = progress_text(line)
            if line:
                tail = (tail + [line])[-12:]
                m = _STEPS.search(line)
                if m:   # barra de progresso das etapas: «|####| 359/359 - 2.08GB/s» vira «Etapa 359/359 · 2.08GB/s»
                    note(f"Etapa {m.group(1)}/{m.group(2)}" + (f" · {m.group(3)}" if m.group(3) else ""))
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
        why = glibc_error("\n".join(tail))
        if why:   # o executável não roda neste Linux (glibc antiga): se foi o OpenFlow que o baixou, apaga para a próxima geração baixar o pacote certo
            try:
                if bin_dir() in Path(exe).resolve().parents or bin_dir().resolve() in Path(exe).resolve().parents:
                    shutil.rmtree(bin_dir(), ignore_errors=True)
            except OSError:
                pass
            raise GlibcError(why)
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
