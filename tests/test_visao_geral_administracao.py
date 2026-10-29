"""Visao Geral, secao "Administracao": so para o Administrador com sessao; contas ativas e inativas, as ultimas 5 alteracoes
de permissoes (resumo da auditoria) e o lembrete de que a divulgacao publica ainda nao tem controle. As contas so sao lidas
para quem ve o bloco; o banco de contas ocupado nao derruba a pagina."""
import re

import pytest

from dominio import autenticacao as A
from painel import visao_geral as VG
from test_admin import _criar, adm  # noqa: F401
from test_autenticacao import painel  # noqa: F401
from test_menu_e_acoes_por_permissao import clientes  # noqa: F401
from test_painel import cliente_demo, demo  # noqa: F401
from test_visao_geral_montador import ADMIN, ANONIMO, LEITOR, TECNICO, _quem, _real, _vies
from test_visao_geral_pagina import _blocos, _secoes

AVISO_DIVULGACAO = "A divulgação pública dos resultados ainda não tem controle no painel: nada é publicado por aqui."
OCUPADO = "O banco de contas está ocupado. Tente de novo em alguns segundos."
UNIVERSO = "Contas do painel."
SEM_ALTERACOES = "Nenhuma alteração de permissões registrada."
REVISOR = _quem("Revisor", set(A.GRUPOS_PADRAO["Revisor"]))
ESTAT = _quem("Estat", {"ver_painel", "ver_estatisticas_usuarios"})
TODAS = _quem("Quase", set(A.PERMISSOES))                          # todas as permissoes, mas nao e o Administrador


def _detalhe(concedidas, retiradas, justificativa=""):
    import json
    return json.dumps({"antes": [], "depois": concedidas, "concedidas": concedidas, "retiradas": retiradas,
                       "justificativa": justificativa, "origem": "formulario"})


AUDITORIA = [  # ordem de ContasSQLite.auditoria: a mais recente primeiro
    {"quando": "2026-10-29T10:00:00+00:00", "admin_login": "chefe", "acao": "criar_usuario", "alvo": "ana", "detalhe": None},
    {"quando": "2026-10-29T09:00:00+00:00", "admin_login": "chefe", "acao": "salvar_permissoes", "alvo": "Leitor",
     "detalhe": _detalhe(["ver_custos"], [], "pedido do orientador")},
    {"quando": "2026-10-28T09:00:00+00:00", "admin_login": "chefe", "acao": "salvar_permissoes", "alvo": "Revisor",
     "detalhe": "texto antigo"},                                    # detalhe fora do formato: aparece o texto cru
    {"quando": "2026-10-27T09:00:00+00:00", "admin_login": "bia", "acao": "salvar_permissoes", "alvo": "Leitor", "detalhe": None},
    {"quando": "2026-10-26T09:00:00+00:00", "admin_login": "chefe", "acao": "salvar_permissoes", "alvo": "Revisor",
     "detalhe": _detalhe([], ["triar_artigos"])},
    {"quando": "2026-10-25T09:00:00+00:00", "admin_login": "chefe", "acao": "salvar_permissoes", "alvo": "Leitor",
     "detalhe": _detalhe(["ver_chamadas"], [])},
    {"quando": "2026-10-24T09:00:00+00:00", "admin_login": "chefe", "acao": "salvar_permissoes", "alvo": "Leitor",
     "detalhe": _detalhe(["ver_nomes_revisores"], [])},             # sexta alteracao: fica de fora
]
USUARIOS = [{"login": "a", "ativo": 1}, {"login": "b", "ativo": 0}, {"login": "c", "ativo": 1}, {"login": "d", "ativo": 1}]


class _Contas:
    def __init__(self, usuarios=USUARIOS, auditoria=AUDITORIA, erro=None):
        self.chamadas = []
        self._u, self._a, self._erro = usuarios, auditoria, erro

    def listar_usuarios(self):
        self.chamadas.append("listar_usuarios")
        if self._erro == "usuarios":
            raise A.ContasOcupadas()
        return [dict(u) for u in self._u]

    def auditoria(self, limite=200):
        self.chamadas.append(("auditoria", limite))
        if self._erro == "auditoria":
            raise A.ContasOcupadas()
        return [dict(x) for x in self._a][:limite]


def _bloco(s, bid):
    achados = [b for x in s for b in x["blocos"] if b["id"] == bid]
    assert len(achados) == 1, f"bloco {bid}: {len(achados)}"
    return achados[0]


def _tem(s, bid):
    return any(b["id"] == bid for x in s for b in x["blocos"])


# ======================== quem ve ========================
@pytest.mark.parametrize("quem,ve", [
    (ADMIN, True),
    (_quem("Administrador", set(), logado=False), False),
    (REVISOR, False), (LEITOR, False), (TECNICO, False), (ESTAT, False), (TODAS, False), (ANONIMO, False),
    (None, False), ({}, False), ({"logado": True}, False), ({"logado": True, "grupo": "Administrador"}, False),
    ({"logado": True, "permissoes": frozenset()}, False),
    ({"logado": True, "grupo": "Administrador", "permissoes": None}, False),     # pode() aceitaria o grupo sem olhar as permissoes
    ({"logado": True, "grupo": None, "permissoes": frozenset(A.PERMISSOES)}, False),
])
def test_quem_ve_a_administracao(quem, ve):
    assert VG.ve_administracao(quem) is ve


def test_a_regra_usa_pode_com_so_admin(monkeypatch):
    vistos = []
    monkeypatch.setattr(A, "pode", lambda g, p, exigida: vistos.append(exigida) or False)
    assert VG.ve_administracao(ADMIN) is False and vistos == [A.SO_ADMIN]


# ======================== ler_contas: so para quem ve ========================
@pytest.mark.parametrize("quem", [None, ANONIMO, LEITOR, REVISOR, TODAS])
def test_ler_contas_nao_le_para_quem_nao_ve(quem):
    c = _Contas()
    assert VG.ler_contas(c, quem) is None and c.chamadas == []


def test_ler_contas_sem_banco_de_contas():
    assert VG.ler_contas(None, ADMIN) is None


def test_ler_contas_do_administrador():
    c = _Contas()
    r = VG.ler_contas(c, ADMIN)
    assert c.chamadas == ["listar_usuarios", ("auditoria", 200)]
    assert r == {"ativas": 3, "inativas": 1, "total": 4, "alteracoes": [
        {"quando": "2026-10-29T09:00:00+00:00", "admin_login": "chefe", "alvo": "Leitor",
         "resumo": "Concedidas: ver_custos. Retiradas: nenhuma. Justificativa: pedido do orientador"},
        {"quando": "2026-10-28T09:00:00+00:00", "admin_login": "chefe", "alvo": "Revisor", "resumo": "texto antigo"},
        {"quando": "2026-10-27T09:00:00+00:00", "admin_login": "bia", "alvo": "Leitor", "resumo": "—"},
        {"quando": "2026-10-26T09:00:00+00:00", "admin_login": "chefe", "alvo": "Revisor",
         "resumo": "Concedidas: nenhuma. Retiradas: triar_artigos."},
        {"quando": "2026-10-25T09:00:00+00:00", "admin_login": "chefe", "alvo": "Leitor",
         "resumo": "Concedidas: ver_chamadas. Retiradas: nenhuma."},
    ]}


def test_ler_contas_usa_o_resumo_da_auditoria(monkeypatch):
    monkeypatch.setattr(A, "resumo_detalhe_auditoria", lambda texto: "R")
    r = VG.ler_contas(_Contas(), ADMIN)
    assert [x["resumo"] for x in r["alteracoes"]] == ["R"] * 5


@pytest.mark.parametrize("ativo,ativas,inativas", [(1, 1, 0), (0, 0, 1), (None, 0, 1), ("1", 0, 1), (True, 1, 0), (2, 0, 1)])
def test_ler_contas_conta_ativa_so_com_um(ativo, ativas, inativas):
    r = VG.ler_contas(_Contas(usuarios=[{"login": "x", "ativo": ativo}], auditoria=[]), ADMIN)
    assert (r["ativas"], r["inativas"], r["total"], r["alteracoes"]) == (ativas, inativas, 1, [])


@pytest.mark.parametrize("erro,chamadas", [
    ("usuarios", ["listar_usuarios"]),                                   # a auditoria nem e lida
    ("auditoria", ["listar_usuarios", ("auditoria", 200)]),
])
def test_ler_contas_com_o_banco_ocupado(erro, chamadas):
    c = _Contas(erro=erro)
    assert VG.ler_contas(c, ADMIN) == {"indisponivel": True} and c.chamadas == chamadas


def test_ler_contas_vazio_le_as_duas_vezes():
    c = _Contas(usuarios=[], auditoria=[])
    assert VG.ler_contas(c, ADMIN) == {"ativas": 0, "inativas": 0, "total": 0, "alteracoes": []}
    assert c.chamadas == ["listar_usuarios", ("auditoria", 200)]


@pytest.mark.parametrize("n", [1, 3, 4])
def test_ler_contas_com_menos_de_cinco_alteracoes(n):
    linhas = [r for r in AUDITORIA if r["acao"] == "salvar_permissoes"][:n]
    assert len(VG.ler_contas(_Contas(auditoria=linhas), ADMIN)["alteracoes"]) == n


@pytest.mark.parametrize("detalhe,resumo", [("", "—"), (None, "—"), ("   ", "   "), ("x" * 3000, "x" * 3000)])
def test_ler_contas_resumo_sem_formato(detalhe, resumo):
    linha = {"quando": "2026-10-29T09:00:00+00:00", "admin_login": "chefe", "acao": "salvar_permissoes", "alvo": None,
             "detalhe": detalhe}
    r = VG.ler_contas(_Contas(auditoria=[linha]), ADMIN)
    assert r["alteracoes"] == [{"quando": "2026-10-29T09:00:00+00:00", "admin_login": "chefe", "alvo": None, "resumo": resumo}]


def test_ler_contas_segue_a_regra(monkeypatch):
    monkeypatch.setattr(VG, "ve_administracao", lambda quem: True)
    c = _Contas()
    assert VG.ler_contas(c, ANONIMO) is not None and "listar_usuarios" in c.chamadas


# ======================== o bloco ========================
def _contas_resumo():
    return VG.ler_contas(_Contas(), ADMIN)


@pytest.mark.parametrize("dados", [_real, _vies])
def test_administracao_depois_da_operacao(dados):
    s = VG.montar({**dados(), "contas_resumo": _contas_resumo()}, ADMIN)
    ids = [x["id"] for x in s]
    assert "administracao" in ids
    assert ids.index("administracao") == ids.index("operacao") + 1 and ids[ids.index("administracao") + 1] == "aprofundar"
    sec = next(x for x in s if x["id"] == "administracao")
    assert sec["titulo"] == "Administração" and [b["id"] for b in sec["blocos"]] == ["administracao"]


def test_bloco_da_administracao():
    b = _bloco(VG.montar({**_real(), "contas_resumo": _contas_resumo()}, ADMIN), "administracao")
    assert (b["titulo"], b["classe"], b["texto"], b["aviso"], b["vazio"]) == (
        "Contas e permissões", "C3", [AVISO_DIVULGACAO], None, None)
    assert [(i["id"], i["rotulo"], i["valor"], i["denominador"], i["origem"], i["origem_rotulo"], i["validacao"], i["classe"],
             i["universo"], i["definicao"]) for i in b["indicadores"]] == [
        ("contas_ativas", "Contas ativas", 3, 4, "administracao", "Administração", "Registro do banco de contas do painel.",
         "C3", UNIVERSO, "Contas que podem entrar no painel."),
        ("contas_inativas", "Contas desativadas", 1, 4, "administracao", "Administração", "Registro do banco de contas do painel.",
         "C3", UNIVERSO, "Contas desativadas por um administrador; não entram no painel."),
    ]
    assert b["alteracoes"] == _contas_resumo()["alteracoes"]
    assert b["acoes"] == [{"texto": "Gerenciar contas", "href": "/admin/usuarios"},
                          {"texto": "Ver o registro de administração", "href": "/admin/auditoria"}]


def test_bloco_sem_alteracoes():
    resumo = VG.ler_contas(_Contas(auditoria=[AUDITORIA[0]]), ADMIN)
    b = _bloco(VG.montar({**_real(), "contas_resumo": resumo}, ADMIN), "administracao")
    assert b["alteracoes"] == [] and b["vazio"] == SEM_ALTERACOES and len(b["indicadores"]) == 2


def test_bloco_com_o_banco_ocupado():
    b = _bloco(VG.montar({**_real(), "contas_resumo": {"indisponivel": True}}, ADMIN), "administracao")
    assert (b["aviso"], b["indicadores"], b["alteracoes"], b["vazio"], b["texto"]) == (OCUPADO, [], [], None, [AVISO_DIVULGACAO])


@pytest.mark.parametrize("negados,acoes", [
    (set(), ["/admin/usuarios", "/admin/auditoria"]),
    ({"/admin/usuarios"}, ["/admin/auditoria"]),
    ({"/admin/auditoria"}, ["/admin/usuarios"]),
    ({"/admin/usuarios", "/admin/auditoria"}, []),
])
def test_links_seguem_a_regra_das_rotas(negados, acoes):
    quem = {**ADMIN, "pode_rota": lambda m, c: c not in negados}
    b = _bloco(VG.montar({**_real(), "contas_resumo": _contas_resumo()}, quem), "administracao")
    assert [a["href"] for a in b["acoes"]] == acoes


@pytest.mark.parametrize("quem", [REVISOR, LEITOR, TECNICO, ESTAT, TODAS, ANONIMO])
def test_sem_administrador_nao_ha_bloco_mesmo_com_os_dados(quem):
    s = VG.montar({**_real(), "contas_resumo": _contas_resumo()}, quem)
    assert "administracao" not in [x["id"] for x in s] and not _tem(s, "administracao")


@pytest.mark.parametrize("resumo", [None, "ausente"])
def test_sem_os_dados_nao_ha_bloco(resumo):
    d = _real() if resumo == "ausente" else {**_real(), "contas_resumo": None}
    assert not _tem(VG.montar(d, ADMIN), "administracao")


def test_montar_nao_altera_os_dados():
    d = {**_real(), "contas_resumo": _contas_resumo()}
    VG.montar(d, ADMIN)
    assert d == {**_real(), "contas_resumo": _contas_resumo()}


# ======================== pagina (banco real com login) ========================
def _bloco_html(h, bid):
    assert f'id="vg-bloco-{bid}"' in h, f"bloco {bid} ausente"
    i = h.index(f'id="vg-bloco-{bid}"')
    return h[i:h.index("</section>", i)]


def test_pagina_do_administrador(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    _criar(cli, contas_db, login="ana", nome="Ana", grupo="Leitor")
    h = cli.get("/").text
    assert ("administracao", "Administração") in _secoes(h)
    b = _bloco_html(h, "administracao")
    assert re.search(r'<h3 id="t-vg-bloco-administracao" data-ic="user-check" data-tom="cobalto">Contas e permissões</h3>', b)
    assert re.findall(r'<div class="kpi" id="vg-ind-([a-z_]+)"><span class="kpi-valor">(\d+) <small>de (\d+)</small>', b) == [
        ("contas_ativas", "2", "2"), ("contas_inativas", "0", "2")]
    assert AVISO_DIVULGACAO in b and f'<p class="vazio">{SEM_ALTERACOES}</p>' in b
    assert '<a class="botao" href="/admin/usuarios">Gerenciar contas</a>' in b


def test_pagina_mostra_as_alteracoes(adm):  # noqa: F811
    cli, contas, _, _ = adm
    leitor = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Leitor")
    assert "ver_chamadas" not in A.GRUPOS_PADRAO["Leitor"]                   # uma mudanca de verdade grava a auditoria
    contas.definir_permissoes(leitor, set(A.GRUPOS_PADRAO["Leitor"]) | {"ver_chamadas"},
                              auditoria=("chefe", "salvar_permissoes", "Leitor",
                                         _detalhe(["ver_chamadas"], [], "teste"), "2026-10-29T09:00:00+00:00"))
    b = _bloco_html(cli.get("/").text, "administracao")
    assert '<div class="tabela-rolavel"><table>' in b
    assert re.findall(r"<th[^>]*>([^<]+)</th>", b) == ["Quando", "Quem", "Grupo", "Alteração"]
    assert re.findall(r"<tr><td>[^<]+</td><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>", b) == [
        ("chefe", "Leitor", "Concedidas: ver_chamadas. Retiradas: nenhuma. Justificativa: teste")]


def test_pagina_com_cinco_alteracoes_em_ordem(adm):  # noqa: F811
    from painel import formatacao as fmt
    cli, contas, _, _ = adm
    quandos = [f"2026-10-2{i}T0{i}:00:00+00:00" for i in range(1, 7)]
    for i, q in enumerate(quandos, 1):                                   # a sexta (a mais recente) entra; a primeira sai
        contas.auditar("chefe", "salvar_permissoes", None if i == 6 else f"G{i}", "" if i == 6 else f"det {i}", q)
    b = _bloco_html(cli.get("/").text, "administracao")
    linhas = re.findall(r"<tr><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td><td>([^<]*)</td></tr>", b)
    assert linhas == [(fmt.data_hora(quandos[5]), "chefe", "—", "—")] + [
        (fmt.data_hora(quandos[i]), "chefe", f"G{i + 1}", f"det {i + 1}") for i in (4, 3, 2, 1)]


def test_pagina_mostra_o_detalhe_longo_inteiro_no_conteiner(adm):  # noqa: F811
    cli, contas, _, _ = adm
    contas.auditar("chefe", "salvar_permissoes", "Leitor", "y" * 3000, "2026-10-29T09:00:00+00:00")
    b = _bloco_html(cli.get("/").text, "administracao")
    assert '<div class="tabela-rolavel"><table>' in b and "<td>" + "y" * 3000 + "</td>" in b


@pytest.mark.parametrize("grupo", ["Visitante", "Leitor", "Revisor"])
def test_quem_nao_e_administrador_nao_le_as_contas(clientes, painel, monkeypatch, grupo):  # noqa: F811
    _, contas, _, _ = painel
    clientes[grupo].get("/")
    vistos = []
    monkeypatch.setattr(contas, "listar_usuarios", lambda *a, **k: vistos.append("listar_usuarios") or [{"login": "SENTINELA", "ativo": 1}])
    monkeypatch.setattr(contas, "auditoria", lambda *a, **k: vistos.append("auditoria") or [
        {"quando": "2026-10-29T09:00:00+00:00", "admin_login": "SENTINELA", "acao": "salvar_permissoes", "alvo": "X", "detalhe": "SENTINELA"}])
    h = clientes[grupo].get("/").text
    assert vistos == [] and "SENTINELA" not in h


@pytest.mark.parametrize("grupo", ["Visitante", "Leitor", "Revisor"])
def test_outros_grupos_nao_veem(clientes, grupo):  # noqa: F811
    h = clientes[grupo].get("/").text
    assert "administracao" not in _blocos(h) and "Contas e permissões" not in h


def test_painel_sem_login_nao_tem_administracao(cliente_demo):  # noqa: F811
    assert "administracao" not in _blocos(cliente_demo[0].get("/").text)


def test_pagina_com_o_banco_de_contas_ocupado(adm, monkeypatch):  # noqa: F811
    cli, contas, _, _ = adm
    cli.get("/")

    def ocupado(*a, **k):
        raise A.ContasOcupadas()
    monkeypatch.setattr(contas, "listar_usuarios", ocupado)
    r = cli.get("/")
    assert r.status_code == 200 and f'<p class="aviso" role="note">{OCUPADO}</p>' in _bloco_html(r.text, "administracao")


def test_rota_passa_as_contas_e_quem(adm, monkeypatch):  # noqa: F811
    cli, contas, _, _ = adm
    vistos = []
    original = VG.ler_contas
    monkeypatch.setattr(VG, "ler_contas", lambda c, quem: vistos.append((c, quem["grupo"], quem["logado"])) or original(c, quem))
    cli.get("/")
    assert vistos == [(contas, "Administrador", True)]


# ======================== consultas por visita ========================
def test_consultas_por_leitor(clientes, cliente_demo, monkeypatch):  # noqa: F811
    """Tetos depois da P7-02 (Visitante 12, Leitor 13, Revisor 17, Administrador 18, sem login 16); a administracao soma 2
    (listar_usuarios e auditoria, no banco de contas) so ao Administrador."""
    from test_visao_geral_andamento import _selects
    limites = {"Visitante": 12, "Leitor": 13, "Revisor": 17, "Administrador": 20, "sem_login": 16}
    contagens = {g: _selects(clientes[g], monkeypatch) for g in ("Visitante", "Leitor", "Revisor", "Administrador")}
    contagens["sem_login"] = _selects(cliente_demo[0], monkeypatch)
    assert {g: (n, limites[g]) for g, n in contagens.items() if n > limites[g]} == {}
