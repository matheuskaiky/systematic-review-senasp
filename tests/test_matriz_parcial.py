"""Gravacao da matriz de permissoes pelo adaptador (usada pelo comando atribuir-permissoes): so altera os grupos pedidos e so
se a versao deles nao mudou, conferida na mesma transacao; a formula da versao; o conversor de id do painel. A tela grava
um grupo por vez (test_edicao_por_grupo.py).
"""
import hashlib
import re
import sqlite3

import pytest

from dominio import autenticacao as A
from test_admin import _auditoria, _csrf, _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401

# o Leitor padrao de um banco de contas novo
LEITOR_PADRAO = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}


def _perms(contas_db):
    linhas = sqlite3.connect(contas_db).execute(
        "SELECT g.nome, gp.permissao FROM grupos g LEFT JOIN grupo_permissoes gp ON gp.grupo_id = g.grupo_id").fetchall()
    saida = {}
    for nome, p in linhas:
        saida.setdefault(nome, set())
        if p:
            saida[nome].add(p)
    return saida


# ---------------- versao ----------------
def _esperada(estado):
    linhas = []
    for gid in sorted(estado):
        linhas.append(f"{gid}")
        linhas += [f"{gid}\t{p}" for p in sorted(set(estado[gid]))]
    return hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("estado", [
    {}, {3: set()}, {3: {"ver_painel"}}, {2: {"b", "a"}, 10: set(), 1: {"ver_painel", "ver_chamadas"}},
])
def test_versao_permissoes_formula(estado):
    assert A.versao_permissoes(estado) == _esperada(estado)


def test_versao_distingue_estados_que_se_confundiriam():
    v = A.versao_permissoes
    assert v({1: set()}) != v({})                                         # grupo sem permissao x grupo ausente
    assert v({1: {"2"}}) != v({12: set()})                                # concatenacao ingenua de numeros
    assert v({1: {"a"}, 2: set()}) != v({1: set(), 2: {"a"}})            # a mesma permissao em grupos diferentes
    assert v({1: {"ver_painel"}}) != v({1: {"ver_painel", "ver_chamadas"}})
    assert v({2: {"a"}, 1: {"b"}}) == v({1: {"b"}, 2: {"a"}})            # nao depende da ordem do dicionario
    assert v({1: ["a", "b"]}) == v({1: {"b", "a"}})                       # nem da ordem das permissoes
    assert v({1: ["a", "a", "b"]}) == v({1: {"a", "b"}})                  # repeticoes contam uma vez (conjunto)
    assert re.fullmatch(r"[0-9a-f]{64}", v({}))


# ---------------- adaptador ----------------
def test_adaptador_confere_a_versao_na_mesma_transacao(adm):
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    atual = {l: LEITOR_PADRAO}
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_matriz({l: {"ver_painel"}}, None, versao_esperada=A.versao_permissoes({l: {"ver_painel"}}))
    assert _perms(contas_db)["Leitor"] == atual[l]
    assert contas.definir_matriz({l: {"ver_painel"}}, None, versao_esperada=A.versao_permissoes(atual)) == 3
    assert _perms(contas_db)["Leitor"] == {"ver_painel"}


def test_adaptador_sem_versao_continua_como_antes(adm):
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    assert contas.definir_matriz({l: set()}) == 4 and _perms(contas_db)["Leitor"] == set()


def test_recusa_deixa_a_conexao_livre(adm):
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_matriz({l: set()}, None, versao_esperada="0" * 64)
    assert contas.definir_permissoes(l, {"ver_painel"}) == 3                # nenhuma transacao ficou aberta


def test_versao_conferida_depois_do_begin_immediate_na_mesma_conexao(adm, monkeypatch):
    """A leitura que alimenta a versao acontece na mesma conexao e depois do BEGIN IMMEDIATE (conferir e gravar sob a mesma
    trava); a recusa nao grava nada e termina em ROLLBACK."""
    from adaptadores import contas_sqlite
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    conexoes, comandos = [], []
    original = contas_sqlite.sqlite3.connect

    def conectar(*a, **k):
        c = original(*a, **k)
        conexoes.append(c)
        c.set_trace_callback(lambda sql: comandos.append(" ".join(sql.split())))
        return c
    monkeypatch.setattr(contas_sqlite.sqlite3, "connect", conectar)
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_matriz({l: set()}, None, versao_esperada="0" * 64)
    assert len(conexoes) == 1
    i_begin = comandos.index("BEGIN IMMEDIATE")
    leituras = [i for i, c in enumerate(comandos) if c.upper().startswith("SELECT") and "grupo_permissoes" in c]
    assert leituras and min(leituras) > i_begin
    assert not any(c.upper().startswith(("INSERT", "DELETE", "UPDATE")) for c in comandos)
    assert comandos[-1] == "ROLLBACK"


def test_adaptador_com_dicionario_vazio_e_grupo_inexistente(adm):
    _, contas, contas_db, _ = adm
    antes = _perms(contas_db)
    assert contas.definir_matriz({}, None, versao_esperada=A.versao_permissoes({})) == 0
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_matriz({}, None, versao_esperada="0" * 64)
    assert contas.definir_matriz({999: set()}, None, versao_esperada=A.versao_permissoes({999: set()})) == 0
    assert _perms(contas_db) == antes


@pytest.mark.parametrize("texto,esperado", [
    ("3", 3), (" 3 ", 3), ("0003", 3), pytest.param("0" * 5000 + "3", 3, id="5000-zeros-e-3"),
    pytest.param("0" * 4301, 0, id="4301-zeros"), ("0", 0),
    ("9223372036854775807", 9223372036854775807), ("9223372036854775808", None), ("1" + "0" * 19, None),
    ("", None), ("  ", None), ("-1", None), ("1.0", None), ("٣", None), (None, None), (3, None),
])
def test_conversor_de_id_do_painel(texto, esperado):
    """Zeros a esquerda nunca chegam ao int(): o limite de digitos do Python nao decide nada."""
    from painel.rotas_extras.admin import _converter_id
    assert _converter_id(texto) == esperado


