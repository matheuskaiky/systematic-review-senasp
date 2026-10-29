"""Pagina da Visao Geral: a rota le os dados uma vez, monta com o montador e o modelo unico desenha as secoes nos dois bancos.
Matriz de aceitacao: leitores (anonimo, anonimo com permissao tecnica gravada, leitura, revisao, tecnico com e sem custos,
administrador, painel sem login, somente leitura) x bancos (real e vies) x estados (fila vazia, sem coleta concluida)."""
import dataclasses
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dominio import autenticacao as A
from painel import visao_geral as VG
from test_autenticacao import painel  # noqa: F401
from test_custos_nas_paginas import clis  # noqa: F401
from test_menu_e_acoes_por_permissao import clientes, somente_leitura, vies  # noqa: F401
from test_painel import cliente_demo, demo  # noqa: F401
from test_validacao_vies import banco  # noqa: F401

PRELIMINAR = ("Resultado preliminar: produzido por processamento automatizado e ainda não validado por pesquisadores. "
              "Interprete como exploratório.")
NAO_DIVULGADO = "Resultados automatizados ainda não divulgados."
ICONES = {"identificacao": ("binoculars", "petroleo"), "cobertura": ("magnifying-glass", "cobalto"), "fila": ("list-checks", "cobalto"),
          "fila_artigos": ("list-checks", "cobalto"), "andamento": ("users", "cobalto"),
          "administracao": ("user-check", "cobalto"),
          "decisoes_humanas": ("check-circle", "cobalto"), "segundo_o_modelo": ("robot", "violeta"),
          "conferencia": ("seal-check", "violeta"), "prontidao": ("gauge", "violeta"), "ocultos": ("prohibit", "rosa"),
          "execucoes": ("play-circle", "ambar"), "links": ("link", "petroleo")}
MODELOS = Path(__file__).resolve().parents[1] / "painel" / "templates"
CSS = (MODELOS.parent / "static" / "painel.css").read_text(encoding="utf-8")
IDS_REAL = ["consultas_web", "urls_unicas", "paginas_com_texto", "pendentes", "artigos_pendentes", "verificados", "confirmados",
            "descartados", "ufs_confirmadas", "classificacoes", "achados", "evidencia", "sem_evidencia", "decisoes", "decisoes_achados",
            "decisoes_artigos", "decisoes_recentes", "nao_concluidas", "falhas", "gasto", "contas_ativas", "contas_inativas"]
IDS_VIES = ["n_obras", "n_web", "n_scholar", "n_em_ambas_fontes", "pendentes", "com_triagem_humana", "incluidos", "excluidos",
            "n_triados", "n_alta", "n_fora", "ocultos_llm", "decisoes", "decisoes_achados", "decisoes_artigos", "decisoes_recentes",
            "nao_concluidas", "falhas", "gasto", "contas_ativas", "contas_inativas"]


@pytest.fixture
def vies_grupos(banco, tmp_path):  # noqa: F811
    """Banco vies com login: Visitante, Leitor, Revisor, Administrador e dois grupos tecnicos (com e sem custos)."""
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.contas_sqlite import ContasSQLite
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from painel.app import criar_app
    from test_menu_e_acoes_por_permissao import _usuario
    from test_autenticacao import _entrar
    from test_validacao_vies import _contexto
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    contas_db = tmp_path / "contas_vies.db"
    contas = ContasSQLite(contas_db)
    app = criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas)
    saida = {"Visitante": TestClient(app)}
    for nome, perms in (("TecnicoSemCustos", {"ver_painel", "ver_chamadas"}), ("TecnicoComCustos", {"ver_painel", "ver_chamadas", "ver_custos"})):
        contas.definir_permissoes(contas.criar_grupo(nome, "2026-10-28T00:00:00+00:00"), perms)
    for grupo in ("Leitor", "Revisor", "Administrador", "TecnicoSemCustos", "TecnicoComCustos"):
        _usuario(contas, contas_db, grupo.lower()[:20], grupo)
        c = TestClient(app)
        assert _entrar(c, grupo.lower()[:20]).status_code == 303
        saida[grupo] = c
    saida["_contas"] = contas
    return saida


def _secoes(h):
    return re.findall(r'<section class="vg-secao" id="vg-([a-z]+)" aria-labelledby="t-vg-\1">\n<h2 id="t-vg-\1">([^<]+)</h2>', h)


def _blocos(h):
    return re.findall(r'<section class="cartao vg-bloco" id="vg-bloco-([a-z_]+)"', h)


def _bloco(h, bid):
    i = h.index(f'id="vg-bloco-{bid}"')
    return h[i:h.index("</section>", i)]


# ======================== estrutura por leitor (banco real, com login) ========================
@pytest.mark.parametrize("grupo,secoes", [
    ("Visitante", ["pesquisa", "resultados", "qualidade", "aprofundar"]),
    ("Leitor", ["pesquisa", "resultados", "qualidade", "aprofundar"]),
    ("Revisor", ["pesquisa", "revisao", "resultados", "qualidade", "operacao", "aprofundar"]),
    ("Administrador", ["pesquisa", "revisao", "resultados", "qualidade", "andamento", "operacao", "administracao", "aprofundar"]),
])
def test_secoes_por_leitor(clientes, grupo, secoes):  # noqa: F811
    h = clientes[grupo].get("/").text
    assert [s for s, _ in _secoes(h)] == secoes
    titulos = {"pesquisa": "A pesquisa", "revisao": "Sua revisão", "resultados": "Resultados", "qualidade": "Qualidade dos dados",
               "andamento": "Andamento da equipe", "operacao": "Operação técnica", "administracao": "Administração", "aprofundar": "Para aprofundar"}
    assert _secoes(h) == [(s, titulos[s]) for s in secoes]
    assert h.count("<h1>") == 1 and "<h1>Visão geral</h1>" in h


def test_cada_bloco_com_titulo_e_icone(clientes):  # noqa: F811
    h = clientes["Administrador"].get("/").text
    assert _blocos(h) == ["identificacao", "cobertura", "fila", "fila_artigos", "decisoes_humanas", "segundo_o_modelo", "conferencia",
                          "prontidao", "andamento", "execucoes", "administracao", "links"]
    for bid in _blocos(h):
        ic, tom = ICONES[bid]
        assert re.search(rf'<h3 id="t-vg-bloco-{bid}" data-ic="{ic}" data-tom="{tom}">[^<]+</h3>', h), bid


# ======================== quem nao entrou (D135, D141) ========================
def test_anonimo_sem_resultado_automatizado_nem_operacao(clientes):  # noqa: F811
    h = clientes["Visitante"].get("/").text
    assert h.count(f'<p class="aviso" role="note">{NAO_DIVULGADO}</p>') == 2              # modelo e conferencia
    assert PRELIMINAR not in h and "Achados apontados pelo modelo" not in h and "Funil do levantamento" not in h
    assert "python main.py" not in h and "Gasto registrado" not in h and "Execuções e chamadas" not in h
    assert "Comando:" not in h and not re.search(r"<code>\d{8}_\d{6}_", h)
    assert "Achados verificados" in h and "UFs com achado confirmado" in h                   # decisoes humanas continuam


def test_visitante_com_permissao_tecnica_gravada_continua_sem_operacao(clientes, painel):  # noqa: F811
    _, contas, _, _ = painel
    v = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Visitante")
    contas.definir_permissoes(v, {"ver_painel", "ver_chamadas", "ver_nomes_revisores"})
    with sqlite3.connect(contas.caminho) as conn:                  # estado antigo gravado direto (o adaptador recusaria)
        conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, 'ver_custos')", (v,))
    h = clientes["Visitante"].get("/").text
    assert "operacao" not in [s for s, _ in _secoes(h)] and "python main.py" not in h and NAO_DIVULGADO in h
    assert "Gasto registrado" not in h and "US$" not in h


# ======================== quem entrou ========================
def test_leitor_ve_o_preliminar_com_aviso_e_sem_comandos(clientes):  # noqa: F811
    h = clientes["Leitor"].get("/").text
    assert h.count(f'<p class="aviso" role="note">{PRELIMINAR}</p>') == 2 and NAO_DIVULGADO not in h
    assert "Achados apontados pelo modelo" in h and "Funil do levantamento" in h
    assert "Comando:" not in h and "python main.py" not in h and "Execuções e chamadas" not in h


@pytest.mark.parametrize("grupo,ve_gasto", [("TecnicoSemCustos", False), ("TecnicoComCustos", True), ("Administrador", True),
                                            ("Consulta", None)])
def test_operacao_e_gasto(clis, grupo, ve_gasto):  # noqa: F811
    h = clis[grupo].get("/").text
    if ve_gasto is None:
        assert "Execuções e chamadas" not in h
        return
    b = _bloco(h, "execucoes")
    assert ("Gasto registrado" in b) is ve_gasto and ('<th class="num">Custo</th>' in b) is ve_gasto
    assert re.search(r'<a href="/execucoes/[^"]+"><code>', b)


def test_fila_de_revisao_para_quem_decide(clientes):  # noqa: F811
    h = clientes["Revisor"].get("/").text
    b = _bloco(h, "fila")
    m = re.search(r'<a class="botao" href="/revisao/achados">Continuar a revisão \((\d+)\)</a>', b)
    assert m and int(m.group(1)) > 0
    assert "fila" not in _blocos(clientes["Leitor"].get("/").text)


def test_somente_leitura_sem_botao_da_fila(somente_leitura):  # noqa: F811
    h = somente_leitura.get("/").text
    assert "Continuar a revisão" not in h and "/revisao/achados" not in _bloco(h, "fila")


# ======================== indicadores: origem, denominador e definicoes ========================
def test_indicador_com_denominador_origem_e_definicao(cliente_demo):  # noqa: F811
    cli, _, copia = cliente_demo
    c = sqlite3.connect(copia)
    total, verif = c.execute("SELECT COUNT(*), COALESCE(SUM(verificado), 0) FROM v_achados_revisao").fetchone()
    achados = c.execute("SELECT COUNT(*) FROM r_achados").fetchone()[0]
    h = cli.get("/").text
    assert (f'<div class="kpi" id="vg-ind-verificados"><span class="kpi-valor">{verif} <small>de {total}</small></span>'
            '<span class="kpi-rotulo">Achados verificados</span><span class="selo neutro">◆ Decisão humana</span></div>') in h
    assert (f'<div class="kpi" id="vg-ind-achados"><span class="kpi-valor">{achados}</span>'
            '<span class="kpi-rotulo">Achados apontados pelo modelo</span><span class="selo neutro">◆ Segundo o modelo</span></div>') in h
    assert ("<dt>Achados verificados</dt><dd>Achados que uma pessoa leu e classificou. Decisão humana: Decisão registrada por uma "
            "pessoa. Universo: Execuções marcadas para o relatório.</dd>") in h


def test_todo_indicador_da_pagina_tem_definicao(cliente_demo):  # noqa: F811
    cli, _, _ = cliente_demo
    h = cli.get("/").text
    rotulos = re.findall(r'<span class="kpi-rotulo">([^<]+)</span>', h)
    assert rotulos
    for r in rotulos:
        assert re.search(rf"<dt>{re.escape(r)}</dt><dd>[^<]+ Universo: [^<]+</dd>", h), r


def test_prontidao_com_origem_calculada(cliente_demo):  # noqa: F811
    b = _bloco(cliente_demo[0].get("/").text, "prontidao")
    assert ('<p class="vg-origem"><span class="selo neutro">◆ Calculado</span> Calculado por regra a partir de decisões humanas. '
            'Universo: Execuções marcadas para o relatório. Cada cartão compara as decisões humanas já registradas com o mínimo que '
            'a análise estatística exige.</p>') in b


# ======================== identificacao ========================
def test_identificacao_real_com_ultima_coleta(cliente_demo):  # noqa: F811
    cli, _, copia = cliente_demo
    fim = sqlite3.connect(copia).execute(
        "SELECT MAX(finalizado_em) FROM execucoes WHERE status = 'concluida' AND no_relatorio = 1").fetchone()[0]
    from painel import formatacao as fmt
    b = _bloco(cli.get("/").text, "identificacao")
    assert '<h3 id="t-vg-bloco-identificacao" data-ic="binoculars" data-tom="petroleo">Secretarias Estaduais de Segurança Pública</h3>' in b
    esperado = (f"Última coleta concluída em {fmt.data_hora(fim)}." if fim else "Ainda não há coleta concluída no relatório.")
    assert f'<p class="sub">{esperado}</p>' in b


def test_identificacao_sem_coleta(cliente_demo, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    monkeypatch.setattr(LeituraPainelSQLite, "ultima_coleta_concluida", lambda self: None)
    assert '<p class="sub">Ainda não há coleta concluída no relatório.</p>' in cliente_demo[0].get("/").text


# ======================== banco vies ========================
def test_vies_por_leitor(vies, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    monkeypatch.setattr(LeituraPainelSQLite, "contagem_triagem",
                        lambda self: {"total": 5, "incluidos": 1, "excluidos": 1, "pendentes": 3, "ocultos_llm": 0})
    anon = vies["Visitante"].get("/").text
    assert [s for s, _ in _secoes(anon)] == ["pesquisa", "resultados", "qualidade", "aprofundar"]
    assert anon.count(NAO_DIVULGADO) == 2 and "Relevância alta segundo o modelo" not in anon
    rev = vies["Revisor"].get("/").text
    assert [s for s, _ in _secoes(rev)] == ["pesquisa", "revisao", "resultados", "qualidade", "operacao", "aprofundar"]
    assert '<a class="botao" href="/literatura/triagem">Continuar a triagem (3)</a>' in rev
    assert "Viés Algorítmico e Inteligência Artificial na Segurança Pública</h3>" in rev
    assert '<link rel="stylesheet" href="/static/analises.css">' in rev and "Funil do levantamento" not in rev


def test_vies_fila_vazia(vies, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    monkeypatch.setattr(LeituraPainelSQLite, "contagem_triagem",
                        lambda self: {"total": 5, "incluidos": 3, "excluidos": 2, "pendentes": 0, "ocultos_llm": 0})
    b = _bloco(vies["Revisor"].get("/").text, "fila")
    assert '<p class="aviso" role="note">Nada pendente.</p>' in b and "Continuar a triagem" not in b


# ======================== a rota: uma leitura, o montador, a regra das rotas ========================
def test_rota_usa_ler_dados_e_montar_com_a_regra_das_rotas(clientes, monkeypatch):  # noqa: F811
    vistos = {}
    original_ler, original_montar = VG.ler_dados, VG.montar

    def ler(leitura, contexto, quem=None):
        vistos["ler"] = vistos.get("ler", 0) + 1
        vistos["quem_ler"] = quem
        return original_ler(leitura, contexto, quem)

    def montar(dados, quem):
        vistos["quem"] = quem
        return original_montar(dados, quem)
    monkeypatch.setattr(VG, "ler_dados", ler)
    monkeypatch.setattr(VG, "montar", montar)
    clientes["Revisor"].get("/")
    q = vistos["quem"]
    assert vistos["ler"] == 1 and q["logado"] is True and q["grupo"] == "Revisor" and vistos["quem_ler"] is q
    assert q["pode_rota"]("GET", "/execucoes") is True and q["pode_rota"]("POST", "/achados/1/verificar") is True
    clientes["Visitante"].get("/")
    assert vistos["quem"]["logado"] is False and vistos["quem"]["grupo"] == "Visitante"


def test_painel_sem_login_ve_tudo(cliente_demo, monkeypatch):  # noqa: F811
    vistos = {}
    original = VG.montar
    monkeypatch.setattr(VG, "montar", lambda dados, quem: (vistos.update(quem=quem), original(dados, quem))[1])
    cliente_demo[0].get("/")
    q = vistos["quem"]
    assert q["logado"] is True and q["grupo"] == A.GRUPO_ADMIN and q["permissoes"] == frozenset(A.PERMISSOES)


def test_pagina_com_um_comando_select_por_leitura_no_maximo_da_linha_de_base(cliente_demo, monkeypatch):  # noqa: F811
    """Linha de base medida antes da P7: 11 SELECTs por visita no banco real (a repeticao de funil sai, a ultima coleta entra).
    O painel sem login ve tudo: mais 4 da fila de artigos (contagem_triagem) e 1 do andamento (atividade_por_revisor)."""
    from adaptadores import leitura_sqlite
    cli = cliente_demo[0]
    cli.get("/")
    cmds = []
    original = leitura_sqlite.sqlite3.connect

    def conectar(*a, **k):
        c = original(*a, **k)
        c.set_trace_callback(lambda s: cmds.append(s.strip().split()[0].upper()))
        return c
    monkeypatch.setattr(leitura_sqlite.sqlite3, "connect", conectar)
    cli.get("/")
    assert sum(1 for c in cmds if c in ("SELECT", "WITH")) <= 16


# ======================== limpeza: o que saiu ========================
def test_modelos_antigos_sairam():
    for nome in ("geral_vies.html", "_alertas.html", "_execucoes_recentes.html"):
        assert not (MODELOS / nome).exists(), nome
    from painel import visao_geral_vies
    assert not hasattr(visao_geral_vies, "dados") and hasattr(visao_geral_vies, "itens")


def test_guia_de_leitura_continua(cliente_demo):  # noqa: F811
    assert 'id="guia-geral"' in cliente_demo[0].get("/").text


# ======================== pre-revisao: completude, estrutura, execucoes, vies ========================
def _ids(h):
    return re.findall(r'<div class="kpi" id="vg-ind-([a-z_]+)">', h)


def test_todos_os_indicadores_em_ordem_nos_dois_bancos(clientes, vies_grupos):  # noqa: F811
    assert _ids(clientes["Administrador"].get("/").text) == IDS_REAL
    assert _ids(vies_grupos["Administrador"].get("/").text) == IDS_VIES
    assert _ids(vies_grupos["Visitante"].get("/").text) == ["n_obras", "n_web", "n_scholar", "n_em_ambas_fontes",
                                                             "com_triagem_humana", "incluidos", "excluidos"]


def test_indicador_do_vies_com_denominador_e_definicao(vies_grupos):  # noqa: F811
    h = vies_grupos["Leitor"].get("/").text
    m = re.search(r'<div class="kpi" id="vg-ind-n_fora"><span class="kpi-valor">1 <small>de (\d+)</small></span>'
                  r'<span class="kpi-rotulo">Fora do escopo segundo o modelo</span><span class="selo neutro">◆ Segundo o modelo</span></div>', h)
    assert m and int(m.group(1)) >= 1
    assert ("<dt>Fora do escopo segundo o modelo</dt><dd>Itens que o modelo julgou fora do escopo da pesquisa. Segundo o modelo: Saída "
            "de um modelo de linguagem; ainda não validada por pesquisadores. Universo: Referências da web e artigos do Google Scholar "
            "das consultas configuradas.</dd>") in h


def test_icones_dos_blocos_existem_no_css_nos_dois_bancos(clientes, vies_grupos):  # noqa: F811
    for h in (clientes["Administrador"].get("/").text, vies_grupos["Administrador"].get("/").text):
        for bid in _blocos(h):
            ic, tom = ICONES[bid]
            assert re.search(rf'<h3 id="t-vg-bloco-{bid}" data-ic="{ic}" data-tom="{tom}">', h), bid
            assert f'[data-ic="{ic}"]' in CSS and f'data-tom="{tom}"' in CSS, bid
    assert "ocultos" in _blocos(vies_grupos["Administrador"].get("/").text)


def test_estrutura_e_ordem_do_conteudo(cliente_demo):  # noqa: F811
    h = cliente_demo[0].get("/").text
    assert "<title>Visão geral · " in h and '<link rel="stylesheet" href="/static/analises.css">' not in h
    for bid in _blocos(h):
        assert f'<section class="cartao vg-bloco" id="vg-bloco-{bid}" aria-labelledby="t-vg-bloco-{bid}">' in h, bid
    ident = _bloco(h, "identificacao")
    assert ident.index("<h3") < ident.index('<p class="sub">Levantamento') < ident.index("coleta")
    pront = _bloco(h, "prontidao")
    assert pront.index('<p class="sub">O que falta') < pront.index('class="vg-origem"') < pront.index('class="prontidao')
    dh = _bloco(h, "decisoes_humanas")
    assert dh.index('<p class="sub">Achado ainda') < dh.index('<div class="kpis">') < dh.index(
        '<details class="vg-definicoes"><summary>Definições e origem dos números</summary><dl>') < dh.index("<svg")
    mod = _bloco(h, "segundo_o_modelo")
    assert mod.index('<p class="aviso" role="note">') < mod.index('<div class="kpis">') < mod.index("<svg")
    conf = _bloco(h, "conferencia")
    assert conf.index('<p class="aviso" role="note">') < conf.index('<div class="kpis">') < conf.index('<a class="botao"')
    cob = _bloco(h, "cobertura")
    assert cob.index("<h3") < cob.index('<div class="kpis">') < cob.index('<details class="vg-definicoes">')
    fila = _bloco(h, "fila")
    assert fila.index("<h3") < fila.index('<div class="kpis">') < fila.index('<details class="vg-definicoes">') < fila.index('<a class="botao"')
    links = _bloco(h, "links")
    assert links.index("<h3") < links.index('<a class="botao"') and '<div class="kpis">' not in links


def test_tabela_das_execucoes(clis, painel):  # noqa: F811
    from urllib.parse import quote
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from painel import formatacao as fmt
    b = _bloco(clis["TecnicoComCustos"].get("/").text, "execucoes")
    e = LeituraPainelSQLite(painel[2]).execucoes_recentes(1)[0]
    assert (f'<tr><td><a href="/execucoes/{quote(e["run_id"], safe="")}"><code>{e["run_id"]}</code></a></td><td>{e["comando"]}</td>'
            f'<td>{e["status"]}</td><td>{fmt.data_hora(e["iniciado_em"])}</td><td class="num">{fmt.moeda_usd(e["custo_usd"])}</td>'
            f'<td>{"dentro" if e["no_relatorio"] else "fora"}</td></tr>') in b
    assert ('<thead><tr><th>Execução</th><th>Comando</th><th>Situação</th><th>Início</th><th class="num">Custo</th>'
            '<th>Relatório</th></tr></thead>') in b
    sem = _bloco(clis["TecnicoSemCustos"].get("/").text, "execucoes")
    assert '<thead><tr><th>Execução</th><th>Comando</th><th>Situação</th><th>Início</th><th>Relatório</th></tr></thead>' in sem
    assert re.search(r"<td>(dentro|fora)</td></tr>", sem)


def test_execucoes_vazias_mostram_o_comando_so_ao_tecnico(clis, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    monkeypatch.setattr(LeituraPainelSQLite, "execucoes_recentes", lambda self, n=5: [])
    h = clis["TecnicoSemCustos"].get("/").text
    assert ('<p class="vazio">Nenhuma execução registrada ainda. Rode <code>python main.py pipeline-uf --ufs PI --limite 5</code>.</p>'
            in _bloco(h, "execucoes"))
    assert "python main.py" not in clis["Consulta"].get("/").text


@pytest.mark.parametrize("trecho", [
    "Enquanto o percentual de verificados for baixo, trate os totais por estado como <strong>provisórios</strong>: o modelo pode ter errado.",
    "O número de achados <strong>não</strong> é o número de ferramentas: a mesma ferramenta pode aparecer em várias notícias.",
    "Quer ajudar a aumentar o percentual de verificados? Entre como revisor e abra a sua fila de trabalho.",
])
def test_guia_do_banco_real_sem_mudanca(cliente_demo, trecho):  # noqa: F811
    assert trecho in cliente_demo[0].get("/").text


@pytest.mark.parametrize("trecho", [
    "Os números descrevem o que estas buscas recuperaram (em português, nestas fontes), não a literatura em geral.",
    "As análises por fonte, tipo, eixo, ano, país, consulta e site ficam na página Análises.",
    "Relevância, tipo de fonte, país, tópicos e eixo atribuídos pelo modelo de linguagem a cada item. É a opinião do modelo, não uma decisão.",
])
def test_guia_do_vies_sem_mudanca(vies_grupos, trecho):  # noqa: F811
    assert trecho in vies_grupos["Leitor"].get("/").text


def test_vies_le_os_itens_uma_vez(vies_grupos, monkeypatch):  # noqa: F811
    from painel import visao_geral_vies
    chamadas = []
    original = visao_geral_vies.itens
    monkeypatch.setattr(visao_geral_vies, "itens", lambda l, c: (chamadas.append(1), original(l, c))[1])
    vies_grupos["Administrador"].get("/")
    assert chamadas == [1]


@pytest.mark.parametrize("grupo,operacao,gasto", [("Visitante", False, False), ("Leitor", False, False),
                                                  ("TecnicoSemCustos", True, False), ("TecnicoComCustos", True, True),
                                                  ("Administrador", True, True)])
def test_vies_operacao_e_custos(vies_grupos, grupo, operacao, gasto):  # noqa: F811
    h = vies_grupos[grupo].get("/").text
    assert ("Execuções e chamadas" in h) is operacao and ("Gasto registrado" in h) is gasto, grupo
    assert ('<th class="num">Custo</th>' in h) is gasto, grupo


def test_vies_visitante_com_permissoes_gravadas(vies_grupos):  # noqa: F811
    contas = vies_grupos["_contas"]
    v = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Visitante")
    contas.definir_permissoes(v, {"ver_painel", "ver_chamadas"})
    with sqlite3.connect(contas.caminho) as conn:                  # estado antigo gravado direto (o adaptador recusaria)
        conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, 'ver_custos')", (v,))
    h = vies_grupos["Visitante"].get("/").text
    assert "Execuções e chamadas" not in h and "Gasto registrado" not in h and h.count(NAO_DIVULGADO) == 2


def test_vies_sem_coleta(vies_grupos, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    monkeypatch.setattr(LeituraPainelSQLite, "ultima_coleta_concluida", lambda self: None)
    assert '<p class="sub">Ainda não há coleta concluída no relatório.</p>' in vies_grupos["Leitor"].get("/").text



# ======================== retrabalho: largura do celular ========================
def test_tabela_das_execucoes_dentro_do_conteiner_rolavel(clis):  # noqa: F811
    b = _bloco(clis["TecnicoComCustos"].get("/").text, "execucoes")
    assert '<div class="tabela-rolavel"><table>' in b and "tabela-container" not in b


def test_selo_de_origem_quebra_linha_dentro_do_indicador():
    """O selo de origem fica dentro de um indicador estreito: no celular ele quebra linha em vez de passar da borda."""
    assert ".kpi .selo { align-self: flex-start; margin-top: .25rem; white-space: normal; }" in CSS
    fonte = (MODELOS.parents[1] / "design" / "src" / "painel" / "30_componentes.css").read_text(encoding="utf-8")
    assert ".kpi .selo { align-self: flex-start; margin-top: .25rem; white-space: normal; }" in fonte
