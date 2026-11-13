"""Processo de trabalho da stable-diffusion.cpp: `python -m openflow.canvas.sd_worker`. Carrega o modelo e gera as imagens FORA do processo do OpenFlow.
A biblioteca é código C++: quando recusa um modelo (ou falta memória) ela pode derrubar o processo (falha de segmentação), e o Python não consegue interceptar isso.
Aqui, se isso acontecer, cai só este processo — o OpenFlow vê o fim dele, lê o log que chegou até ali e mostra o erro no nó.

Protocolo: uma mensagem JSON por linha. Entrada (stdin): {"op": "load", "kw": {...}} | {"op": "gen", "kw": {...}, "out": "<pasta>"} | {"op": "quit"}.
Saída (um descritor próprio; o stdout comum vira stderr): {"log": [nível, texto]} a cada linha de log da biblioteca e uma resposta final {"ok": true, ...} ou {"ok": false, "error": "…"}."""
import ctypes
import inspect
import json
import os
import sys
import threading


def main() -> int:
    proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)   # qualquer print perdido da biblioteca vai para o terminal, não para o protocolo
    lock = threading.Lock()

    def send(obj) -> None:
        with lock:
            proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
            proto.flush()

    import stable_diffusion_cpp as sdc

    def cb(level, text, data):  # noqa: ANN001
        try:
            line = (text or b"").decode("utf-8", "replace").rstrip()
            send({"log": [int(level), line]})
            if level >= 1 and line:
                print(line, file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001 — um callback nunca pode derrubar a geração
            pass

    keep = sdc.sd_log_callback(cb)   # a referência precisa continuar viva
    sdc.sd_set_log_callback(keep, ctypes.c_void_p(0))
    sd = None
    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
            op = msg.get("op")
            if op == "quit":
                break
            if op == "load":
                sd = sdc.StableDiffusion(**msg["kw"])
                ctx = getattr(getattr(sd, "_model", None), "model", 1)   # a carga que falha devolve um ponteiro nulo (não None) e a biblioteca segue com ele
                if not ctx:
                    sd = None
                    send({"ok": False, "error": "refused"})
                    continue
                send({"ok": True, "params": list(inspect.signature(sd.generate_image).parameters) if hasattr(sd, "generate_image") else []})
            elif op == "gen":
                if sd is None:
                    send({"ok": False, "error": "modelo não carregado"})
                    continue
                images = sd.generate_image(**msg["kw"])
                files = []
                for i, img in enumerate(images if isinstance(images, (list, tuple)) else [images]):
                    f = os.path.join(msg["out"], f"out{i}.png")
                    img.save(f, format="PNG")
                    files.append(f)
                send({"ok": True, "files": files})
        except Exception as exc:  # noqa: BLE001 — o erro volta ao OpenFlow, que mostra no nó
            send({"ok": False, "error": str(exc) or exc.__class__.__name__})
    return 0


if __name__ == "__main__":
    sys.exit(main())
