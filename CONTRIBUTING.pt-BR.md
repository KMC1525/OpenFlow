# Contribuindo com o OpenFlow

Obrigado por ajudar! Um guia curto (a [versão em inglês](CONTRIBUTING.md) diz o mesmo).

- **Rode os testes** antes de abrir um pull request: `python -m unittest discover -s tests -t .` (testes em Python, mais os do Chromium quando há Node + Playwright), `cargo test --release --manifest-path openflow/native/Cargo.toml` e `node tests/js/i18n_check.mjs`.
- **Python ≥ 3.9**, só biblioteca padrão no núcleo (os extras ficam no `pyproject.toml`). Sem `match`, sem `X | Y` em tempo de execução.
- **Paridade Rust ↔ Python:** toda função do núcleo Rust (`openflow/native/src`) precisa de um equivalente em `openflow/native/__init__.py` com o mesmo comportamento. Mudar a interface exige subir o `ABI` (Python) e o `flow_abi_version` (Rust), mantendo as bibliotecas antigas funcionando.
- **Textos:** a interface e o terminal são em português primeiro, com tradução para o inglês (`openflow/web/js/en.js`, `openflow/term_en.py`, os instaladores usam `L "pt" "en"`). Uma frase nova sem tradução faz os testes falharem.
- **Documentação:** quando comportamento, instalação, comandos ou limites mudarem, atualize `README.md` + `README.pt-BR.md` e `CHANGELOG.md` + `CHANGELOG.en.md` (por versão: o que mudou e, com honestidade, o que não foi verificado).
- **Segurança:** trate arquivos, pacotes, URLs e saída da IA como não confiáveis (valide caminhos, tamanhos, tipos, JSON). A IA produz dados (JSON) que o motor valida, nunca código para executar.
- Correções de bugs vêm com um teste que reproduz o bug. Nunca afirme na documentação o que não foi testado.
