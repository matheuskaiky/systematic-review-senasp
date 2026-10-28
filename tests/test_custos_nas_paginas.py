"""Custos operacionais (valores em dolar, saldos e consumo de creditos) so saem do servidor para quem tem `ver_custos`; o
visitante anonimo nunca os recebe. Paginas, a pagina da execucao e a metodologia. Os blocos da pagina de analises sao a outra
etapa e tem testes proprios."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dominio import autenticacao as A
from painel import metodologia_texto as MT
from test_autenticacao import _criar, _entrar, painel  # noqa: F401
from test_links_por_permissao import SEMENTES_REAL, _corpo, _percorrer
from test_metodologia_texto import _fatos
from test_painel import demo  # noqa: F401

DOLAR = re.compile(r"US\$ ?\d")
GRUPOS_EXTRAS = {
    "Consulta": {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao"},
    "TecnicoSemCustos": {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "ver_registros_revisao"},
    "TecnicoComCustos": {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "ver_registros_revisao", "ver_custos"},
}
SEM_CUSTOS = ("Visitante", "Consulta", "TecnicoSemCustos")


@pytest.fixture
def clis(painel):  # noqa: F811
    cli0, contas, _, _ = painel
    for nome, perms in GRUPOS_EXTRAS.items():
        contas.definir_permissoes(contas.criar_grupo(nome, "2026-10-28T00:00:00+00:00"), perms)
    saida = {"Visitante": cli0}
    for grupo in ("Administrador", *GRUPOS_EXTRAS):
        login = grupo.lower()[:20]
        _criar(painel, login, grupo, nome=grupo)
        c = TestClient(cli0.app)
        assert _entrar(c, login).status_code == 303
        saida[grupo] = c
    return saida


def _sem_analises(paginas):
    return {k: v for k, v in paginas.items() if not k.startswith("/analises")}       # blocos de analise: outra etapa


def _paginas_com_dolar(cli):
    vistas = _sem_analises(_percorrer(cli, SEMENTES_REAL, limite=120))
    return {k for k in vistas if DOLAR.search(cli.get(k if "{" not in k else _exemplo(cli, k)).text)}, vistas


def _exemplo(cli, chave):
    """Um endereco concreto para uma pagina com parametro (a primeira que aparece nos links da lista correspondente)."""
    lista = {"/execucoes/{run_id}": "/execucoes", "/chamadas/{chamada_id}": "/chamadas",
             "/literatura/artigos/{artigo_id}": "/literatura/artigos", "/achados/{achado_id}": "/achados",
             "/estados/{uf}": "/estados"}.get(chave)
    if lista is None:
        return "/"
    base = chave.split("{")[0]
    m = re.search(rf'href="({re.escape(base)}[^"/?#]+)"', cli.get(lista).text)
    return m.group(1) if m else "/"


# ---------------- percurso: nenhum valor em dolar para quem nao ve custos ----------------
@pytest.mark.parametrize("grupo", SEM_CUSTOS)
def test_nenhum_valor_em_dolar_sem_a_permissao(clis, grupo):
    com_dolar, vistas = _paginas_com_dolar(clis[grupo])
    assert len(vistas) >= 15 and com_dolar == set(), grupo


def test_quem_ve_custos_continua_vendo(clis):
    adm = clis["Administrador"]
    run = _run(adm)
    linhas = adm.get("/chamadas").text.split("<tr>")
    cid = next(re.search(r'href="/chamadas/(\d+)"', l).group(1) for l in linhas if 'href="/chamadas/' in l and DOLAR.search(l))
    for grupo in ("Administrador", "TecnicoComCustos"):
        for url in ("/", "/metodologia", "/execucoes", f"/execucoes/{run}", "/chamadas", f"/chamadas/{cid}"):
            assert DOLAR.search(clis[grupo].get(url).text), (grupo, url)


# ---------------- textos exatos sem custos ----------------
RUN = r'href="/execucoes/(\d{8}_\d{6}_[0-9a-f]+)"'


def _run(cli):
    return re.search(RUN, cli.get("/execucoes").text).group(1)


def test_visao_geral_sem_o_gasto_real(clis):
    for grupo, cli in clis.items():
        h = _corpo(cli.get("/").text)
        ve = grupo in ("Administrador", "TecnicoComCustos")
        assert ("Gasto registrado" in h) is ve, grupo
        assert ('<th class="num">Custo</th>' in h) is ve, grupo                    # ultimas execucoes (secao de operacao)


def test_pagina_da_execucao_sem_custos(clis):
    run = _run(clis["Administrador"])
    com, sem = (_corpo(clis[g].get(f"/execucoes/{run}").text) for g in ("TecnicoComCustos", "TecnicoSemCustos"))
    assert "Custo e latência por etapa</h2>" in com and "<dt>Custo registrado</dt>" in com
    assert '<h2 data-ic="timer" data-tom="ambar">Latência por etapa</h2>' in sem
    assert "Custo e latência" not in sem and "<dt>Custo registrado</dt>" not in sem and "Créditos antes e depois" not in sem
    assert '<th class="num">Custo</th>' not in sem and "custo_usd" not in sem
    assert '<th class="num">Latência</th>' in sem


def test_listas_de_execucoes_e_chamadas_sem_a_coluna(clis):
    for pagina in ("/execucoes", "/chamadas"):
        com, sem = (_corpo(clis[g].get(pagina).text) for g in ("TecnicoComCustos", "TecnicoSemCustos"))
        assert '<th class="num">Custo</th>' in com and '<th class="num">Custo</th>' not in sem, pagina
    sem = _corpo(clis["TecnicoSemCustos"].get("/chamadas").text)
    assert ("Cada chamada externa (busca, download, classificação): o que foi enviado, o que voltou e quanto demorou." in sem
            and "quanto custou" not in sem)


def test_uma_chamada_mostra_so_os_tokens(clis):
    cid = re.search(r'href="/chamadas/(\d+)"', clis["Administrador"].get("/chamadas").text).group(1)
    sem = _corpo(clis["TecnicoSemCustos"].get(f"/chamadas/{cid}").text)
    com = _corpo(clis["TecnicoComCustos"].get(f"/chamadas/{cid}").text)
    assert "<dt>Custo</dt>" in com and "<dt>Custo</dt>" not in sem
    tokens = re.search(r"<dd>[^<]*· ([\d.]+ tokens de entrada, [\d.]+ de saída)</dd>", com)
    if tokens:
        assert f"<dt>Tokens</dt><dd>{tokens.group(1)}</dd>" in sem
    else:
        assert "<dt>Tokens</dt>" not in sem


def test_comparar_execucoes_sem_o_custo(clis):
    runs = list(dict.fromkeys(re.findall(RUN, clis["Administrador"].get("/execucoes").text)))[:2]
    url = f"/execucoes/comparar?a={runs[0]}&b={runs[1]}"
    assert "<td>Custo registrado</td>" in clis["TecnicoComCustos"].get(url).text
    assert "<td>Custo registrado</td>" not in clis["TecnicoSemCustos"].get(url).text


def test_classificadores_sem_custo(clis):
    h = clis["Administrador"].get("/classificadores").text
    runs = re.findall(r'<option value="([^"]+)"', h[h.index('id="exec-a"'):h.index("</select>", h.index('id="exec-a"'))])
    url = f"/classificadores?a={runs[0]}&b={runs[-1]}"
    com, sem = (_corpo(clis[g].get(url).text) for g in ("TecnicoComCustos", "Consulta"))
    assert "Qualidade e custo de cada execução</h2>" in com and '<th scope="row">Custo total</th>' in com
    assert re.search(r'<h2 id="h-qual">\d\. Qualidade de cada execução</h2>', sem)
    for linha in ("Custo total", "Custo por página", "Custo por achado"):
        assert f'<th scope="row">{linha}</th>' not in sem
    assert ('<p class="explica">Estes números olham cada execução inteira, não só as páginas em comum. “Evidência confere” é a '
            'parcela de achados cujo trecho citado existe de fato no texto enviado ao modelo. “JSON válido” é a parcela de respostas '
            'que o programa conseguiu ler.</p>') in sem
    assert '<th scope="row">Tokens por página (entrada + saída)</th>' in sem


def test_triagem_de_escopo_sem_custo(clis):
    com, sem = (_corpo(clis[g].get("/triagem-escopo").text) for g in ("TecnicoComCustos", "Consulta"))
    assert "Custo das chamadas que produziram estas respostas" not in sem
    assert '<th scope="col" class="num">Custo</th>' not in sem
    if '<th scope="col" class="num">Custo</th>' in com:
        assert '<th scope="col" class="num">Conferência falhou</th><th scope="col">Quando</th>' in sem


# ---------------- metodologia ----------------
def test_metodologia_sem_custos_funcao_pura():
    com = MT.gerar_metodologia(_fatos())
    assert com == MT.gerar_metodologia(_fatos(), custos=True)
    sem = MT.gerar_metodologia(_fatos(), custos=False)
    assert "custos" in [s["id"] for s in com["secoes"]]
    assert [s["id"] for s in sem["secoes"]] == [s["id"] for s in com["secoes"] if s["id"] != "custos"]
    sem_aviso = sem["texto"].replace(AVISO_SEM_CUSTOS, "")            # o aviso fixo do fim nao traz valor nenhum
    assert not DOLAR.search(sem["texto"]) and "custo" not in sem_aviso.lower() and "gasto" not in sem_aviso.lower()
    textos = [MT.para_texto(r) for r in sem["ressalvas"] if MT.para_texto(r) != AVISO_SEM_CUSTOS]
    assert not any("custo" in t.lower() or "gasto" in t.lower() for t in textos)
    # o resto do texto e o mesmo: so saem a secao de custos e as ressalvas (ou o trecho delas) sobre custo
    assert [s for s in sem["secoes"]] == [s for s in com["secoes"] if s["id"] != "custos"]


@pytest.mark.parametrize("n,esperado", [
    (1, "1 execução está fora do relatório e não entra nos números. "),
    (2, "2 execuções estão fora do relatório e não entram nos números. "),
])
def test_ressalva_das_execucoes_fora_sem_o_custo(n, esperado):
    f = _fatos()
    dentro = [e for e in f["execucoes"] if e.get("no_relatorio")]
    f["execucoes"] = dentro + [{"run_id": f"F{i}", "no_relatorio": 0, "comando": "x", "status": "ok"} for i in range(n)]
    com = [MT.para_texto(r) for r in MT.gerar_metodologia(f)["ressalvas"]]
    sem = [MT.para_texto(r) for r in MT.gerar_metodologia(f, custos=False)["ressalvas"]]
    assert any("apenas no gasto real total" in t for t in com)
    assert any(t.startswith(esperado) for t in sem)


def test_rota_da_metodologia_respeita_a_permissao(clis):
    for grupo, cli in clis.items():
        h = cli.get("/metodologia").text
        ve = grupo in ("Administrador", "TecnicoComCustos")
        assert ('id="custos"' in h) is ve, grupo
        assert bool(DOLAR.search(h)) is ve, grupo


# ---------------- uma regra so nos modelos ----------------
PALAVRAS = re.compile(r"moeda_usd\(|custo|saldo|consumo")


def _blocos(texto):
    """(posicao, expressao) de cada {{ }} e {% %} do modelo (as tags montam a pilha; so os {{ }} sao conferidos)."""
    return [(m.start(), m.group(0)) for m in re.finditer(r"\{\{.*?\}\}|\{%.*?%\}", texto, re.S)]


def test_todo_custo_nos_modelos_esta_sob_ver_custos():
    """Cada expressao que imprime custo, saldo ou consumo (`{{ ... }}`) esta dentro de um `{% if ... ver_custos ... %}` aberto (e
    fora do seu `{% else %}`). As tags de controle (`{% if e.custos %}`, `{% for c in e.custos %}`) nao imprimem nada."""
    fora = []
    for arq in sorted(Path("painel/templates").glob("*.html")):
        s = arq.read_text(encoding="utf-8")
        pilha = []                                       # [tipo, condicao, no_else]
        for pos, bloco in _blocos(s):
            tag = re.match(r"\{%-?\s*(\w+)\s*(.*?)\s*-?%\}", bloco, re.S)
            if tag:
                nome, resto = tag.group(1), tag.group(2)
                if nome in ("if", "for", "macro", "call"):
                    pilha.append([nome, resto, False])
                elif nome in ("endif", "endfor", "endmacro", "endcall") and pilha:
                    pilha.pop()
                elif nome in ("else", "elif") and pilha:
                    pilha[-1][2] = True
                    if nome == "elif":
                        pilha[-1][1] = resto
                        pilha[-1][2] = False
                if nome in ("if", "elif") and "ver_custos" in resto:
                    continue
            if bloco.startswith("{{") and PALAVRAS.search(bloco):
                if not any(t in ("if",) and "ver_custos" in c and not no_else for t, c, no_else in pilha):
                    fora.append(f"{arq.name}:{s.count(chr(10), 0, pos) + 1}: {bloco[:60]}")
    assert fora == []


AVISO_SEM_CUSTOS = "Os custos das chamadas externas não aparecem neste nível de acesso ao painel."
PALAVRAS_DE_CUSTO = ("custo", "gasto", "US$", "preço")


def _sem_palavras_de_custo(t):
    return not any(p.lower() in t.lower() for p in PALAVRAS_DE_CUSTO)


def test_ressalvas_nao_financeiras_ficam_e_o_aviso_entra_no_fim():
    f = _fatos()
    com = [MT.para_texto(r) for r in MT.gerar_metodologia(f)["ressalvas"]]
    sem = [MT.para_texto(r) for r in MT.gerar_metodologia(f, custos=False)["ressalvas"]]
    esperadas = []
    for t in com:
        if _sem_palavras_de_custo(t):
            esperadas.append(t)                                       # nao financeira: identica e na mesma ordem
        elif "apenas no gasto real total. " in t:                     # execucoes fora do relatorio: perde so o trecho de custo
            esperadas.append(t.split(";")[0] + ". " + t.split("apenas no gasto real total. ", 1)[1])
        # as outras falam so de custo e saem
    assert sem == esperadas + [AVISO_SEM_CUSTOS] and AVISO_SEM_CUSTOS not in com
    assert any("gasto real total" in t for t in com)                  # o caso transformado existe nos fatos de exemplo


def test_texto_de_copia_vem_das_secoes_e_ressalvas_filtradas():
    sem = MT.gerar_metodologia(_fatos(), custos=False)
    assert sem["texto"] == MT._texto_puro(sem["secoes"], sem["ressalvas"])
    assert sem["texto"].rstrip().endswith(AVISO_SEM_CUSTOS)


def test_com_custos_nao_tem_o_aviso():
    assert AVISO_SEM_CUSTOS not in MT.gerar_metodologia(_fatos())["texto"]


def test_ressalvas_so_de_custo_saem():
    """Fatos que geram as duas ressalvas so de custo: preco nao informado numa etapa e chamadas sem custo gravado noutra."""
    f = _fatos()
    etapas = {e["etapa"]: e for e in f["custos"]["por_etapa"]}
    etapas["busca_web"].update(n_com_custo=0, custo_usd=0, n_ok_sem_custo=690)                 # preco nao informado
    etapas["busca_academica"].update(n_ok_sem_custo=3)                                        # parte sem custo gravado
    com = [MT.para_texto(r) for r in MT.gerar_metodologia(f)["ressalvas"]]
    sem = [MT.para_texto(r) for r in MT.gerar_metodologia(f, custos=False)["ressalvas"]]
    assert any(t.startswith("Custo não calculado: preços não informados para ") for t in com)
    assert any(t.startswith("Há chamadas bem-sucedidas sem custo gravado (") for t in com)
    assert not any(t.startswith(("Custo não calculado", "Há chamadas bem-sucedidas sem custo")) for t in sem)
    fora = "fora do relatório e não"                                     # a transformada tem teste proprio
    assert ([t for t in com if _sem_palavras_de_custo(t)]
            == [t for t in sem[:-1] if _sem_palavras_de_custo(t) and fora not in t])
    assert sem[-1] == AVISO_SEM_CUSTOS


def test_estado_vazio_da_triagem_de_escopo_sem_instrucao_de_custo(clis):
    sem, com = (_corpo(clis[g].get("/triagem-escopo").text) for g in ("Consulta", "TecnicoComCustos"))
    assert "Ainda não há triagem de escopo" in sem and "antes de ampliar para todos." in sem
    assert "Comece estimando o custo" in com and "--estimar" in com and "autorização do custo estimado" in com
    assert "Comece estimando o custo" not in sem and "--estimar" not in sem and "custo" not in sem.lower()
