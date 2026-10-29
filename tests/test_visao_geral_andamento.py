"""Visao Geral, "Sua revisao" e "Andamento da equipe": a fila de artigos tambem no banco real, para quem pode triar; o
andamento da equipe so com totais (nenhuma pessoa identificada), so com sessao e ver_estatisticas_usuarios. Cada leitura so
acontece para quem ve o bloco que a usa."""
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from dominio import autenticacao as A
from painel import visao_geral as VG
from test_admin import _criar, _entrar, _historico, _sair, adm  # noqa: F401
from test_autenticacao import painel  # noqa: F401
from test_menu_e_acoes_por_permissao import clientes, somente_leitura  # noqa: F401
from test_painel import cliente_demo, demo  # noqa: F401
from test_validacao_vies import banco  # noqa: F401
from test_visao_geral_montador import ADMIN, ANONIMO, ANONIMO_COM_CHAMADAS, LEITOR, TECNICO, TRIADOR, VERIFICADOR, _quem, _real, _vies
from test_visao_geral_pagina import _blocos, _secoes, vies_grupos  # noqa: F401

HOJE = "2026-10-29"
TEXTO = "Totais da equipe, sem identificar quem decidiu."
DEC = "Decisões de revisores registradas no painel, em achados (sem as desfeitas) e em artigos."
VAZIO = "Ainda não há decisões de revisores."
ESTAT = _quem("Estat", {"ver_painel", "ver_estatisticas_usuarios"})
ESTAT_NOMES = _quem("Estat", {"ver_painel", "ver_estatisticas_usuarios", "ver_nomes_revisores"})
ANONIMO_COM_ESTAT = _quem("Visitante", {"ver_painel", "ver_estatisticas_usuarios", "ver_nomes_revisores"}, logado=False)
REVISOR = _quem("Revisor", set(A.GRUPOS_PADRAO["Revisor"]))

# linhas no formato de atividade_por_revisor (revisor, dia, achados, artigos)
ATIVIDADE = [
    {"revisor": "Bia", "dia": "2026-10-30", "achados": 0, "artigos": 1},       # dia futuro: conta no total, fora da janela
    {"revisor": "Ana", "dia": HOJE, "achados": 2, "artigos": 0},              # hoje
    {"revisor": "Ana", "dia": "2026-09-30", "achados": 0, "artigos": 1},      # ha 29 dias: dentro da janela
    {"revisor": "Ana", "dia": "2026-09-29", "achados": 4, "artigos": 0},      # ha 30 dias: fora da janela
    {"revisor": "Caio", "dia": None, "achados": 1, "artigos": 0},             # sem dia: so no total
]
TRIAGEM_REAL = {"total": 12, "incluidos": 3, "excluidos": 2, "pendentes": 7, "ocultos_llm": 4}


def _com_atividade(d, atividade=ATIVIDADE):
    return {**d, "atividade": [dict(x) for x in atividade], "hoje": HOJE}


def _ids_secoes(s):
    return [x["id"] for x in s]


def _tem(s, bid):
    return any(b["id"] == bid for x in s for b in x["blocos"])


def _bloco(s, bid):
    achados = [b for x in s for b in x["blocos"] if b["id"] == bid]
    assert len(achados) == 1, f"bloco {bid}: {len(achados)}"
    return achados[0]


def _ind(b):
    return [(i["id"], i["rotulo"], i["valor"], i["denominador"], i["origem"], i["classe"], i["universo"], i["definicao"])
            for i in b["indicadores"]]


# ======================== quem ve (uma regra para a leitura e para o bloco) ========================
@pytest.mark.parametrize("quem,fila,andamento", [
    (ADMIN, True, True),
    (REVISOR, True, False),
    (LEITOR, False, False),
    (TRIADOR, True, False),
    (VERIFICADOR, False, False),
    (TECNICO, False, False),
    (ESTAT, False, True),
    (ANONIMO, False, False),
    (_quem("Visitante", {"ver_painel", "triar_artigos"}, logado=False), False, False),
    (ANONIMO_COM_ESTAT, False, False),                     # sem sessao nunca, qualquer que seja a permissao gravada
    (_quem("Administrador", set(), logado=False), False, False),
    (None, False, False),
    ({}, False, False),
    ({"logado": True}, False, False),                      # chaves faltando valem como quem nao entrou
    ({"logado": True, "grupo": "Administrador"}, False, False),
    ({"logado": True, "permissoes": frozenset(A.PERMISSOES)}, False, False),
    ({"grupo": "Administrador", "permissoes": frozenset()}, False, False),
])
def test_quem_ve_a_fila_de_artigos_e_o_andamento(quem, fila, andamento):
    assert VG.ve_fila_artigos(quem) is fila
    assert VG.ve_andamento(quem) is andamento


def test_as_regras_usam_pode(monkeypatch):
    vistos = []
    monkeypatch.setattr(A, "pode", lambda g, p, exigida: vistos.append(exigida) or False)
    assert VG.ve_fila_artigos(ADMIN) is False and VG.ve_andamento(ADMIN) is False
    assert vistos == ["triar_artigos", "ver_estatisticas_usuarios"]


# ======================== ler_dados: cada leitura so para quem ve o bloco ========================
class _Leitura:
    def __init__(self):
        self.chamadas = []

    def _r(self, nome, valor):
        self.chamadas.append(nome)
        return valor

    def resumo_geral(self):
        return self._r("resumo_geral", {})

    def contagem_revisao(self):
        return self._r("contagem_revisao", {})

    def analise_prontidao(self):
        return self._r("analise_prontidao", {})

    def execucoes_recentes(self, n):
        return self._r("execucoes_recentes", [])

    def ultima_coleta_concluida(self):
        return self._r("ultima_coleta_concluida", None)

    def contagem_triagem(self):
        return self._r("contagem_triagem", dict(TRIAGEM_REAL))

    def atividade_por_revisor(self):
        return self._r("atividade_por_revisor", [dict(x) for x in ATIVIDADE])


class _Ctx:
    banco = "real"
    ufs = {"PI": "Piauí"}


class _CtxVies:
    banco = "vies"


@pytest.fixture
def leitura_real(monkeypatch):
    from painel import analises_blocos
    monkeypatch.setattr(analises_blocos, "bloco_prontidao", lambda a: {"cartoes": []})
    return _Leitura()


@pytest.fixture
def vies_sem_itens(monkeypatch):
    from painel import analises_blocos_vies, visao_geral_vies
    monkeypatch.setattr(visao_geral_vies, "itens", lambda leitura, contexto: [])
    monkeypatch.setattr(analises_blocos_vies, "bloco_relevancia", lambda lista: {})


@pytest.mark.parametrize("quem,triagem,atividade", [
    (None, False, False),
    (ANONIMO, False, False),
    (ANONIMO_COM_ESTAT, False, False),
    (LEITOR, False, False),
    (REVISOR, True, False),
    (ESTAT, False, True),
    (ADMIN, True, True),
])
def test_ler_dados_real_le_so_o_que_o_leitor_ve(leitura_real, quem, triagem, atividade):
    antes = datetime.now(timezone.utc).date()
    d = VG.ler_dados(leitura_real, _Ctx(), quem)
    depois = datetime.now(timezone.utc).date()
    assert leitura_real.chamadas.count("contagem_triagem") == int(triagem)
    assert leitura_real.chamadas.count("atividade_por_revisor") == int(atividade)
    assert ("triagem" in d) is triagem and ("atividade" in d) is atividade and ("hoje" in d) is atividade
    if triagem:
        assert d["triagem"] == TRIAGEM_REAL
    if atividade:
        assert d["atividade"] == ATIVIDADE and d["hoje"] in {antes.isoformat(), depois.isoformat()}   # virada de dia em UTC


def test_ler_dados_sem_quem_nao_faz_as_leituras_novas(leitura_real):
    VG.ler_dados(leitura_real, _Ctx())
    assert "contagem_triagem" not in leitura_real.chamadas and "atividade_por_revisor" not in leitura_real.chamadas


def test_ler_dados_segue_as_regras_de_quem_ve(leitura_real, monkeypatch):
    monkeypatch.setattr(VG, "ve_fila_artigos", lambda quem: True)
    monkeypatch.setattr(VG, "ve_andamento", lambda quem: True)
    VG.ler_dados(leitura_real, _Ctx(), ANONIMO)
    assert leitura_real.chamadas.count("contagem_triagem") == 1 and leitura_real.chamadas.count("atividade_por_revisor") == 1


@pytest.mark.parametrize("quem,atividade", [(None, False), (LEITOR, False), (ANONIMO_COM_ESTAT, False), (ESTAT, True), (ADMIN, True)])
def test_ler_dados_vies_le_a_triagem_para_todos_e_a_atividade_so_para_quem_ve(vies_sem_itens, quem, atividade):
    lt = _Leitura()
    d = VG.ler_dados(lt, _CtxVies(), quem)
    assert lt.chamadas.count("contagem_triagem") == 1 and d["triagem"] == TRIAGEM_REAL      # como hoje, para todos
    assert lt.chamadas.count("atividade_por_revisor") == int(atividade) and ("atividade" in d) is atividade


# ======================== fila de artigos no banco real ========================
def test_fila_de_artigos_no_banco_real():
    s = VG.montar({**_real(), "triagem": dict(TRIAGEM_REAL)}, ADMIN)
    assert [b["id"] for b in next(x for x in s if x["id"] == "revisao")["blocos"]] == ["fila", "fila_artigos"]
    b = _bloco(s, "fila_artigos")
    assert (b["titulo"], b["classe"], b["aviso"]) == ("Artigos para triar", "C1", None)
    assert _ind(b) == [("artigos_pendentes", "Artigos aguardando triagem humana", 7, 12, "humana", "C1",
                        "Artigos exibidos na triagem humana.",
                        "Artigos exibidos na triagem que ainda não têm decisão de uma pessoa.")]
    assert b["acoes"] == [{"texto": "Continuar a triagem (7)", "href": "/literatura/triagem"}]


@pytest.mark.parametrize("quem,blocos", [
    (ADMIN, ["fila", "fila_artigos"]),
    (TRIADOR, ["fila_artigos"]),
    (VERIFICADOR, ["fila"]),
    (LEITOR, []),
    (_quem("Visitante", {"ver_painel", "triar_artigos"}, logado=False), []),
])
def test_fila_de_artigos_por_leitor(quem, blocos):
    s = VG.montar({**_real(), "triagem": dict(TRIAGEM_REAL)}, quem)
    revisao = next((x for x in s if x["id"] == "revisao"), {"blocos": []})
    assert [b["id"] for b in revisao["blocos"]] == blocos


def test_fila_de_artigos_sem_a_leitura_nao_aparece():
    assert not _tem(VG.montar(_real(), ADMIN), "fila_artigos")


def test_fila_de_artigos_vazia():
    b = _bloco(VG.montar({**_real(), "triagem": {**TRIAGEM_REAL, "pendentes": 0}}, ADMIN), "fila_artigos")
    assert b["acoes"] == [] and b["aviso"] == "Nada pendente." and b["indicadores"][0]["valor"] == 0


def test_fila_de_artigos_sem_a_rota_nao_tem_botao():
    quem = {**ADMIN, "pode_rota": lambda m, c: not (m == "POST" and c.startswith("/literatura/artigos/"))}
    b = _bloco(VG.montar({**_real(), "triagem": dict(TRIAGEM_REAL)}, quem), "fila_artigos")
    assert b["acoes"] == [] and b["aviso"] is None and b["indicadores"][0]["valor"] == 7


def test_fila_de_artigos_igual_nos_dois_bancos():
    real = _bloco(VG.montar({**_real(), "triagem": dict(TRIAGEM_REAL)}, ADMIN), "fila_artigos")
    vies = _bloco(VG.montar(_vies(triagem=dict(TRIAGEM_REAL)), ADMIN), "fila")
    trocar = {"fila_artigos": "fila", "artigos_pendentes": "pendentes"}
    real = {**real, "id": "fila", "indicadores": [{**i, "id": trocar[i["id"]]} for i in real["indicadores"]]}
    assert real == vies


def test_um_so_construtor_da_fila_de_artigos(monkeypatch):
    vistos = []

    def falso(triagem, pred, bid, iid):
        vistos.append((bid, iid))
        return {"id": bid, "titulo": "X", "classe": "C1", "texto": [], "indicadores": [], "acoes": []}
    monkeypatch.setattr(VG, "_bloco_fila_artigos", falso)
    assert _bloco(VG.montar({**_real(), "triagem": dict(TRIAGEM_REAL)}, ADMIN), "fila_artigos")["titulo"] == "X"
    assert _bloco(VG.montar(_vies(), ADMIN), "fila")["titulo"] == "X"
    assert vistos == [("fila_artigos", "artigos_pendentes"), ("fila", "pendentes")]


# ======================== andamento da equipe (so totais) ========================
@pytest.mark.parametrize("dados", [_real, _vies])
def test_andamento_entre_qualidade_e_operacao(dados):
    s = VG.montar(_com_atividade(dados()), ADMIN)
    ids = _ids_secoes(s)
    assert "andamento" in ids
    assert ids.index("andamento") == ids.index("qualidade") + 1 and ids[ids.index("andamento") + 1] == "operacao"
    sec = next(x for x in s if x["id"] == "andamento")
    assert sec["titulo"] == "Andamento da equipe" and [b["id"] for b in sec["blocos"]] == ["andamento"]


@pytest.mark.parametrize("quem", [ADMIN, ESTAT, ESTAT_NOMES])
@pytest.mark.parametrize("dados", [_real, _vies])
def test_andamento_so_com_totais(dados, quem):
    b = _bloco(VG.montar(_com_atividade(dados()), quem), "andamento")
    assert (b["titulo"], b["classe"], b["texto"], b["aviso"], b["vazio"]) == ("Atividade da equipe", "C3", [TEXTO], None, None)
    assert _ind(b) == [
        ("decisoes", "Decisões registradas", 9, None, "humana", "C3", DEC, "Decisões em achados e em artigos, somadas."),
        ("decisoes_achados", "Em achados", 7, 9, "humana", "C3", DEC, "Decisões de verificação de achados que não foram desfeitas."),
        ("decisoes_artigos", "Em artigos", 2, 9, "humana", "C3", DEC, "Decisões de triagem de artigos."),
        ("decisoes_recentes", "Nos últimos 30 dias", 3, 9, "humana", "C3", DEC,
         "Decisões com data entre hoje e 29 dias atrás (UTC)."),
    ]
    assert b["acoes"] == [{"texto": "Ver a atividade por revisor", "href": "/estatisticas-usuarios"}]
    assert not {"Ana", "Bia", "Caio"} & set(re.findall(r"[A-Z][a-z]+", repr(b)))      # nenhuma pessoa no bloco


@pytest.mark.parametrize("quem", [LEITOR, REVISOR, TECNICO, ANONIMO, ANONIMO_COM_CHAMADAS, ANONIMO_COM_ESTAT])
@pytest.mark.parametrize("dados", [_real, _vies])
def test_andamento_so_com_sessao_e_permissao(dados, quem):
    s = VG.montar(_com_atividade(dados()), quem)
    assert "andamento" not in _ids_secoes(s) and not _tem(s, "andamento")


def test_andamento_sem_a_leitura_nao_aparece():
    assert "andamento" not in _ids_secoes(VG.montar(_real(), ADMIN))


def test_andamento_vazio():
    b = _bloco(VG.montar(_com_atividade(_real(), []), ADMIN), "andamento")
    assert [(i["id"], i["valor"], i["denominador"]) for i in b["indicadores"]] == [
        ("decisoes", 0, None), ("decisoes_achados", 0, 0), ("decisoes_artigos", 0, 0), ("decisoes_recentes", 0, 0)]
    assert b["vazio"] == VAZIO and b["texto"] == [TEXTO]


def test_andamento_sem_a_rota_da_atividade_nao_tem_link():
    quem = {**ADMIN, "pode_rota": lambda m, c: c != "/estatisticas-usuarios"}
    assert _bloco(VG.montar(_com_atividade(_real()), quem), "andamento")["acoes"] == []


@pytest.mark.parametrize("quem", [ADMIN, ESTAT])
def test_andamento_nao_altera_os_dados(quem):
    d = _com_atividade(_real())
    VG.montar(d, quem)
    assert d == _com_atividade(_real())


def test_andamento_usa_resumir_atividade(monkeypatch):
    vistos = []

    def falso(linhas, hoje):
        vistos.append((linhas, hoje))
        return ([{"revisor": "Zé", "achados": 5, "artigos": 2, "hoje": 0, "ultimo_dia": "2020-01-01"}],
                [{"revisor": "Zé", "dia": "2020-01-01", "achados": 1, "artigos": 0}])
    monkeypatch.setattr(A, "resumir_atividade", falso)
    b = _bloco(VG.montar(_com_atividade(_real()), ADMIN), "andamento")
    assert vistos == [(ATIVIDADE, HOJE)]
    assert [(i["id"], i["valor"]) for i in b["indicadores"]] == [
        ("decisoes", 7), ("decisoes_achados", 5), ("decisoes_artigos", 2), ("decisoes_recentes", 1)]


# ======================== pagina (banco real com login) ========================
def _bloco_html(h, bid):
    assert f'id="vg-bloco-{bid}"' in h, f"bloco {bid} ausente"
    i = h.index(f'id="vg-bloco-{bid}"')
    return h[i:h.index("</section>", i)]


def _kpis(b):
    return re.findall(r'<div class="kpi" id="vg-ind-([a-z_]+)"><span class="kpi-valor">(\d+)(?: <small>de (\d+)</small>)?</span>', b)


def test_pagina_do_administrador_com_andamento(adm):
    cli, _, _, copia = adm
    _historico(copia)
    h = cli.get("/").text
    assert ("andamento", "Andamento da equipe") in _secoes(h)
    b = _bloco_html(h, "andamento")
    assert re.search(r'<h3 id="t-vg-bloco-andamento" data-ic="users" data-tom="cobalto">Atividade da equipe</h3>', b)
    # _historico: hoje 2 achados e 1 artigo; ha 40 dias 1 achado e 2 artigos; um achado desfeito e um sem nome nao contam
    assert _kpis(b) == [("decisoes", "6", ""), ("decisoes_achados", "3", "6"), ("decisoes_artigos", "3", "6"),
                        ("decisoes_recentes", "3", "6")]
    assert TEXTO in b and '<a class="botao" href="/estatisticas-usuarios">Ver a atividade por revisor</a>' in b
    assert "Ana" not in b and "Bruno" not in b and "<table>" not in b


def test_pagina_sem_ver_nomes_mostra_os_mesmos_totais(adm):
    cli, _, contas_db, copia = adm
    _historico(copia)
    total = _kpis(_bloco_html(cli.get("/").text, "andamento"))
    g = sqlite3.connect(contas_db)
    g.execute("INSERT INTO grupos (nome, fixo, criado_em) VALUES ('Estat', 0, '2026-10-29T00:00:00+00:00')")
    g.execute("INSERT INTO grupo_permissoes SELECT grupo_id, p FROM grupos, (SELECT 'ver_painel' p UNION SELECT 'ver_estatisticas_usuarios') "
              "WHERE nome='Estat'")
    g.commit()
    _criar(cli, contas_db, login="est", nome="Est", grupo="Estat")
    _sair(cli)
    _entrar(cli, "est")
    assert _kpis(_bloco_html(cli.get("/").text, "andamento")) == total


def test_pagina_andamento_vazio(adm):
    cli, _, _, copia = adm
    c = sqlite3.connect(copia)
    c.execute("DELETE FROM achados_revisoes")
    c.execute("DELETE FROM triagem_revisoes")
    c.commit()
    b = _bloco_html(cli.get("/").text, "andamento")
    assert f'<p class="vazio">{VAZIO}</p>' in b


@pytest.mark.parametrize("grupo,secoes,blocos_revisao", [
    ("Visitante", ["pesquisa", "resultados", "qualidade", "aprofundar"], []),
    ("Leitor", ["pesquisa", "resultados", "qualidade", "aprofundar"], []),
    ("Revisor", ["pesquisa", "revisao", "resultados", "qualidade", "operacao", "aprofundar"], ["fila", "fila_artigos"]),
    ("Administrador", ["pesquisa", "revisao", "resultados", "qualidade", "andamento", "operacao", "aprofundar"],
     ["fila", "fila_artigos"]),
])
def test_secoes_e_filas_por_leitor(clientes, grupo, secoes, blocos_revisao):  # noqa: F811
    h = clientes[grupo].get("/").text
    assert [s for s, _ in _secoes(h)] == secoes
    assert [b for b in _blocos(h) if b.startswith("fila")] == blocos_revisao


def test_pagina_fila_de_artigos_no_banco_real(clientes):  # noqa: F811
    b = _bloco_html(clientes["Revisor"].get("/").text, "fila_artigos")
    assert re.search(r'<h3 id="t-vg-bloco-fila_artigos" data-ic="list-checks" data-tom="cobalto">Artigos para triar</h3>', b)
    assert re.search(r'<a class="botao" href="/literatura/triagem">Continuar a triagem \(\d+\)</a>', b) or "Nada pendente." in b


def test_somente_leitura_mostra_o_andamento_e_a_fila_sem_botao(somente_leitura):  # noqa: F811
    h = somente_leitura.get("/").text
    assert "andamento" in _blocos(h) and "Continuar a triagem" not in h and 'href="/literatura/triagem"' not in _bloco_html(h, "fila_artigos")


def test_vies_administrador_ve_o_andamento(vies_grupos):  # noqa: F811
    assert "andamento" in _blocos(vies_grupos["Administrador"].get("/").text)
    for grupo in ("Visitante", "Leitor", "Revisor"):
        assert "andamento" not in _blocos(vies_grupos[grupo].get("/").text), grupo


# ======================== consultas por visita ========================
def _selects(cli, monkeypatch):
    from adaptadores import leitura_sqlite
    cli.get("/")
    cmds = []
    original = leitura_sqlite.sqlite3.connect

    def conectar(*a, **k):
        c = original(*a, **k)
        c.set_trace_callback(lambda s: cmds.append(s.strip().split()[0].upper()))
        return c
    monkeypatch.setattr(leitura_sqlite.sqlite3, "connect", conectar)
    cli.get("/")
    monkeypatch.undo()
    return sum(1 for c in cmds if c in ("SELECT", "WITH"))


def test_consultas_por_leitor(clientes, cliente_demo, monkeypatch):  # noqa: F811
    """Linha de base medida em 8423928 (com login conta tambem as consultas das contas): Visitante 12, Leitor 13, Revisor 13,
    Administrador 13, painel sem login 11. A fila de artigos do banco real soma 4 (contagem_triagem, medida) a quem pode triar;
    o andamento soma 1 (atividade_por_revisor) a quem o ve. Limites maximos: quem nao ve um bloco nao paga a leitura dele (uma
    leitura indevida da triagem somaria 4 e passaria do limite)."""
    limites = {"Visitante": 12, "Leitor": 13, "Revisor": 17, "Administrador": 18, "sem_login": 16}
    contagens = {g: _selects(clientes[g], monkeypatch) for g in ("Visitante", "Leitor", "Revisor", "Administrador")}
    contagens["sem_login"] = _selects(cliente_demo[0], monkeypatch)
    excedidos = {g: (n, limites[g]) for g, n in contagens.items() if n > limites[g]}
    assert excedidos == {}
