
import os as _os

_os.environ.setdefault("OPENFLOW_LANG", "pt")   # os testes de terminal conferem os textos em português; o inglês é testado à parte


def _voxcpm_gate_open():
    """O voxcpm exige o Python 3.10+; nos Pythons 3.9 do CI (e de quem testa) os testes que simulam a biblioteca ficariam presos nessa exigência. Os que testam a mensagem do 3.9 trocam isto por False."""
    return True


try:
    from openflow.canvas import media as _media

    _media._voxcpm_python_ok = _voxcpm_gate_open
except Exception:   # sem o pacote (testes soltos): nada a ajustar
    pass
