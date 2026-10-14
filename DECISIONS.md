# DECISIONS

Registro de desvios e decisões de julgamento em relação à especificação (`docs/SPEC_v2.md`).

### D1 — Idioma das mensagens e do prompt (marco M0)
- Contexto: a especificação disponível é a tradução para o inglês; os blocos de código trazem comentários, mensagens de log/erro, textos de ajuda da CLI e o prompt em inglês. Os identificadores, tabelas, comandos e valores de enum continuam em português.
- Decisão: os blocos de código foram implementados literalmente, mantendo as mensagens e o prompt como estão na especificação. Comentários e docstrings novos (os que não vêm da especificação) são escritos em português. `PROMPT_VERSAO` ficou em `"v1"`, como no bloco de código.
- Motivo: o bloco de código literal tem precedência sobre a prosa, e o prompt é escolha de pesquisa que não cabe a quem implementa. Não existe execução anterior com prompt em português, então não há resultados a comparar.
- Impacto: `config/prompts.py` e as mensagens dos próximos marcos. Se o pesquisador preferir mensagens ou prompt em português, a troca é local; mudar o prompt exige subir `PROMPT_VERSAO`.

### D2 — Marcadores de preenchimento em português (marco M0)
- Contexto: a especificação traduzida usa `YOUR_EMAIL` e `FILL_IN`; as regras do projeto citam `SEU_EMAIL` e `PREENCHA`.
- Decisão: `config/settings.py` usa `SEU_EMAIL` (no `user_agent`) e `PREENCHA` (no modelo de `openai_compat`). Preços continuam `None`.
- Motivo: manter os nomes em português e deixar claro o que o pesquisador precisa preencher.
- Impacto: `config/settings.py`; entra na configuração e no hash da execução.

### D3 — `.gitignore` reescrito conforme a especificação (marco M0)
- Contexto: havia um `.gitignore` não versionado que listava a pasta `docs/` inteira e um arquivo de instruções locais. As regras proíbem listar esses arquivos no `.gitignore`, que é versionado; a exclusão deles é feita por `.git/info/exclude`.
- Decisão: `.gitignore` com o conteúdo da seção 4 da especificação mais `.venv/` e `.pytest_cache/`.
- Motivo: cumprir a regra de exclusão por `.git/info/exclude` e ignorar o ambiente virtual e o cache do pytest.
- Impacto: `.gitignore`. Com isso `docs/SPEC_v2.md` deixa de estar ignorado; a decisão de versioná-lo ou não fica com o pesquisador (ver relatório).

### D4 — Fixtures sintéticas criadas junto com cada adaptador (marco M0)
- Contexto: C2 pede marcadores `skipif` e fixtures sintéticas por adaptador, mas os adaptadores só existem a partir do M1 a M7.
- Decisão: no M0 ficou o marcador `skipif` no teste real do Perplexity (importação dentro do teste). As fixtures sintéticas em `tests/fixtures/sintetico/` serão criadas, com seus testes, no marco de cada adaptador.
- Motivo: uma fixture sem o adaptador correspondente não teria teste que a validasse.
- Impacto: `tests/test_contratos.py` cresce a cada marco.

### D5 — Ambiente virtual e lock criados com `uv` (marco M0)
- Contexto: o sistema não tem `python` nem `python3-venv`/`pip`; só `python3` e o `uv`.
- Decisão: `uv venv .venv`, `uv pip install -r requirements.txt` e `uv pip freeze > requirements.lock.txt`.
- Motivo: é a ferramenta disponível sem `sudo`; o formato do lock é o mesmo do `pip freeze` (C16).
- Impacto: `requirements.lock.txt` (a regenerar antes do M9). Os comandos dos relatórios usam `.venv/bin/python`.

### D6 — Caminhos relativos no snapshot (C12) (marco M0)
- Contexto: C12 manda serializar caminhos relativos a `RAIZ`.
- Decisão: `_plano` em `config/settings.py` trata também `Path` e passou a ser o `default` único do `json.dumps`, no lugar do lambda da especificação.
- Motivo: o lambda só chamava `_plano` para dataclasses; os `Path` caíam em `str()` com caminho absoluto.
- Impacto: `config/settings.py`, `tests/test_config.py`.

### D7 — Leitura e validação do `run_origem` no repositório (marco M1)
- Contexto: C5 manda guardar `--de` em `execucoes.run_origem`, reaproveitá-lo em `--retomar` e validar que a execução existe, mas só cita `iniciar_execucao(run_origem=None)` na porta.
- Decisão: a validação de `--de` (mensagem em português) fica dentro de `iniciar_execucao`; foi acrescentado o método `obter_run_origem(run_id)` à porta `Repositorio` e ao adaptador SQLite, para que o `main.py` leia o valor guardado ao retomar. Na retomada com `--de` novo o valor guardado é atualizado; sem `--de` é preservado.
- Motivo: menor mudança que dá ao `main.py` o dado de que ele precisa sem consultar o banco diretamente.
- Impacto: `dominio/portas.py`, `adaptadores/repositorio_sqlite.py`, `tests/test_repositorio.py`.

### D8 — Nome do arquivo bruto com sufixo único (C11) (marco M1)
- Contexto: C11 pede um sufixo curto e único no nome do arquivo bruto.
- Decisão: `BrutoLocal.salvar` grava `<16 primeiros caracteres da chave>_<6 hex de uuid4>.<ext>`.
- Motivo: uma nova tentativa não sobrescreve o arquivo da tentativa anterior e o `raw_path` antigo continua válido.
- Impacto: `adaptadores/bruto_local.py`, `tests/test_repositorio.py`.
