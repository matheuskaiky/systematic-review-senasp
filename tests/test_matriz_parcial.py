"""Salvar a matriz de permissoes so altera os grupos que a pagina exibiu, e so se nada mudou desde que ela foi aberta: um grupo
ausente do envio, ou criado depois, fica como esta; uma alteracao feita por outra pessoa no meio recusa o envio inteiro.
"""
import hashlib
import re
import sqlite3

import pytest

from dominio import autenticacao as A
from test_admin import _auditoria, _csrf, _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401

RECUSA = "As permissões mudaram depois que esta página foi aberta. Nada foi gravado: recarregue a página e refaça as alterações."


def _formulario(cli):
    """O formulario exatamente como a pagina o entrega: csrf, grupos exibidos, versao e as caixas marcadas habilitadas."""
    h = cli.get("/admin/grupos").text
    form = h[h.index('<form method="post" action="/admin/grupos">'):]
    form = form[:form.index("</form>")]
    dados = [("csrf", re.search(r'name="csrf" value="([^"]+)"', form).group(1))]
    dados += [("grupos", v) for v in re.findall(r'<input type="hidden" name="grupos" value="([^"]*)">', form)]
    dados += [("versao", v) for v in re.findall(r'<input type="hidden" name="versao" value="([^"]*)">', form)]
    for tag in re.findall(r"<input type=\"checkbox\"[^>]*>", form):
        if " checked" in tag and " disabled" not in tag:
            dados.append((re.search(r'name="([^"]+)"', tag).group(1), "on"))
    return dados


def _perms(contas_db):
    linhas = sqlite3.connect(contas_db).execute(
        "SELECT g.nome, gp.permissao FROM grupos g LEFT JOIN grupo_permissoes gp ON gp.grupo_id = g.grupo_id").fetchall()
    saida = {}
    for nome, p in linhas:
        saida.setdefault(nome, set())
        if p:
            saida[nome].add(p)
    return saida


def _post(cli, dados):
    """Envia os pares como formulario (campos repetidos viram lista, na ordem dos pares)."""
    corpo = {}
    for k, v in dados:
        corpo.setdefault(k, []).append(v)
    return cli.post("/admin/grupos", data=corpo, follow_redirects=False)


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


# ---------------- pagina ----------------
def test_pagina_lista_os_grupos_exibidos_e_a_versao(adm):
    cli, contas, contas_db, _ = adm
    dados = _formulario(cli)
    exibidos = [int(v) for k, v in dados if k == "grupos"]
    assert exibidos == [g["grupo_id"] for g in contas.grupos() if g["nome"] != "Administrador"]
    versoes = [v for k, v in dados if k == "versao"]
    assert versoes == [A.versao_permissoes({g["grupo_id"]: g["permissoes"] for g in contas.grupos() if g["nome"] != "Administrador"})]


# ---------------- grupo ausente e grupo novo ----------------
def test_grupo_ausente_do_envio_fica_inalterado(adm):
    """O defeito: antes, todo grupo cujas caixas nao vinham no envio ficava sem nenhuma permissao."""
    cli, _, contas_db, _ = adm
    l = str(_gid(contas_db, "Leitor"))
    dados = [(k, v) for k, v in _formulario(cli) if not (k == "grupos" and v == l) and not k.startswith(f"p-{l}-")]
    antes = _perms(contas_db)
    r = _post(cli, dados)
    assert r.status_code == 409 and RECUSA in r.text                     # a versao cobre os grupos listados: outro conjunto
    assert _perms(contas_db) == antes


def test_grupo_ausente_com_versao_dos_listados_fica_inalterado(adm):
    cli, contas, contas_db, _ = adm
    l, v = _gid(contas_db, "Leitor"), _gid(contas_db, "Visitante")
    listados = {g["grupo_id"]: g["permissoes"] for g in contas.grupos() if g["nome"] not in ("Administrador", "Leitor")}
    dados = [("csrf", _csrf(cli, "/admin/grupos")), ("versao", A.versao_permissoes(listados))]
    dados += [("grupos", str(gid)) for gid in listados]
    dados += [(f"p-{gid}-{p}", "on") for gid, ps in listados.items() for p in ps if gid != v]   # Visitante desmarcado
    dados.append((f"p-{l}-ver_chamadas", "on"))                          # caixa de grupo nao listado: ignorada
    antes = _perms(contas_db)
    r = _post(cli, dados)
    assert r.status_code == 303 and r.headers["location"] == "/admin/grupos?ok=1"
    depois = _perms(contas_db)
    assert depois["Leitor"] == antes["Leitor"] and depois["Visitante"] == set() and depois["Revisor"] == antes["Revisor"]
    assert _auditoria(contas_db) == [("salvar_permissoes", "Visitante", "-ver_painel")]


def test_grupo_criado_depois_de_abrir_a_pagina_fica_inalterado(adm):
    cli, contas, contas_db, _ = adm
    dados = _formulario(cli)
    gid_novo = contas.criar_grupo("Bolsistas", "2026-10-27T00:00:00+00:00")
    contas.definir_permissoes(gid_novo, {"ver_painel", "ver_nomes_revisores"})
    l = _gid(contas_db, "Leitor")
    dados = [(k, v) for k, v in dados if k != f"p-{l}-ver_nomes_revisores"]
    r = _post(cli, dados)
    assert r.status_code == 303
    depois = _perms(contas_db)
    assert depois["Bolsistas"] == {"ver_painel", "ver_nomes_revisores"} and depois["Leitor"] == {"ver_painel"}


# ---------------- concorrencia ----------------
def test_alteracao_de_outra_pessoa_no_meio_recusa_o_envio_inteiro(adm):
    cli, contas, contas_db, _ = adm
    dados = _formulario(cli)
    contas.definir_permissoes(_gid(contas_db, "Leitor"), {"ver_painel"})        # outra pessoa, depois de a pagina abrir
    antes = _perms(contas_db)
    n_aud = len(_auditoria(contas_db))
    r = _post(cli, [(k, v) for k, v in dados if k != f"p-{_gid(contas_db, 'Revisor')}-ver_chamadas"])
    assert r.status_code == 409 and RECUSA in r.text and "Permissões alteradas" in r.text
    assert _perms(contas_db) == antes and len(_auditoria(contas_db)) == n_aud


def test_alteracao_concorrente_em_grupo_nao_listado_nao_recusa(adm):
    cli, contas, contas_db, _ = adm
    dados = _formulario(cli)
    gid_novo = contas.criar_grupo("Bolsistas", "2026-10-27T00:00:00+00:00")
    contas.definir_permissoes(gid_novo, {"ver_painel"})
    assert _post(cli, dados).status_code == 303 and _perms(contas_db)["Bolsistas"] == {"ver_painel"}


@pytest.mark.parametrize("versao", [None, "", " ", "x", "0" * 64, "A" * 64])
def test_versao_ausente_ou_invalida_recusa_sem_gravar(adm, versao):
    cli, _, contas_db, _ = adm
    dados = [(k, v) for k, v in _formulario(cli) if k != "versao"]
    dados = [(k, v) for k, v in dados if not k.startswith(f"p-{_gid(contas_db, 'Leitor')}-")]
    if versao is not None:
        dados.append(("versao", versao))
    antes = _perms(contas_db)
    r = _post(cli, dados)
    assert r.status_code == 409 and RECUSA in r.text and _perms(contas_db) == antes


def test_versao_repetida_vale_a_primeira(adm):
    cli, _, contas_db, _ = adm
    dados = _formulario(cli)
    dados.append(("versao", "0" * 64))
    l = _gid(contas_db, "Leitor")
    r = _post(cli, [(k, v) for k, v in dados if k != f"p-{l}-ver_nomes_revisores"])
    assert r.status_code == 303 and _perms(contas_db)["Leitor"] == {"ver_painel"}


# ---------------- lista de grupos forjada ----------------
@pytest.mark.parametrize("valor", ["", " ", "x", "-1", "0", "999", "1.0", "01" * 20, "9" * 30, "١"])
def test_grupo_listado_invalido_ou_inexistente_e_ignorado(adm, valor):
    cli, _, contas_db, _ = adm
    dados = _formulario(cli) + [("grupos", valor), (f"p-{valor.strip() or 'v'}-ver_painel", "on")]
    antes = _perms(contas_db)
    r = _post(cli, dados)
    assert r.status_code == 303 and _perms(contas_db) == antes


def test_administrador_listado_e_ignorado(adm):
    cli, _, contas_db, _ = adm
    a = str(_gid(contas_db, "Administrador"))
    antes = _perms(contas_db)
    r = _post(cli, _formulario(cli) + [("grupos", a)])
    assert r.status_code == 303 and _perms(contas_db) == antes


def test_grupo_listado_duas_vezes_conta_uma(adm):
    cli, _, contas_db, _ = adm
    l = str(_gid(contas_db, "Leitor"))
    dados = [(k, v) for k, v in _formulario(cli) if k != f"p-{l}-ver_nomes_revisores"] + [("grupos", l)]
    r = _post(cli, dados)
    assert r.status_code == 303 and _perms(contas_db)["Leitor"] == {"ver_painel"}


def test_sem_grupo_listado_nada_muda(adm):
    cli, _, contas_db, _ = adm
    dados = [(k, v) for k, v in _formulario(cli) if k != "grupos"]
    antes = _perms(contas_db)
    r = _post(cli, dados)
    assert r.status_code == 409 and _perms(contas_db) == antes            # a versao foi calculada sobre os grupos exibidos


def test_visitante_continua_sem_permissoes_proibidas(adm):
    cli, _, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    r = _post(cli, _formulario(cli) + [(f"p-{v}-verificar_achados", "on"), (f"p-{v}-ver_estatisticas_usuarios", "on")])
    assert r.status_code == 303 and _perms(contas_db)["Visitante"] == {"ver_painel"}


# ---------------- adaptador ----------------
def test_adaptador_confere_a_versao_na_mesma_transacao(adm):
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    atual = {l: {"ver_painel", "ver_nomes_revisores"}}
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_matriz({l: {"ver_painel"}}, None, versao_esperada=A.versao_permissoes({l: {"ver_painel"}}))
    assert _perms(contas_db)["Leitor"] == atual[l]
    assert contas.definir_matriz({l: {"ver_painel"}}, None, versao_esperada=A.versao_permissoes(atual)) == 1
    assert _perms(contas_db)["Leitor"] == {"ver_painel"}


def test_adaptador_sem_versao_continua_como_antes(adm):
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    assert contas.definir_matriz({l: set()}) == 2 and _perms(contas_db)["Leitor"] == set()


def test_recusa_deixa_a_conexao_livre(adm):
    _, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_matriz({l: set()}, None, versao_esperada="0" * 64)
    assert contas.definir_permissoes(l, {"ver_painel"}) == 1                # nenhuma transacao ficou aberta


def _form_sem_leitor(cli, contas, contas_db, extra):
    """Formulario que lista todos os grupos menos o Leitor, com a versao so dos listados, mais os campos de `extra`."""
    l = _gid(contas_db, "Leitor")
    listados = {g["grupo_id"]: g["permissoes"] for g in contas.grupos() if g["nome"] not in ("Administrador", "Leitor")}
    dados = [("csrf", _csrf(cli, "/admin/grupos")), ("versao", A.versao_permissoes(listados))]
    dados += [("grupos", str(gid)) for gid in listados]
    dados += [(f"p-{gid}-{p}", "on") for gid, ps in listados.items() for p in ps]
    return dados + [(k, v.replace("{L}", str(l))) for k, v in extra]


def _digitos_arabes(n):
    return "".join(chr(0x0660 + int(c)) for c in str(n))


def test_valor_que_um_conversor_frouxo_tomaria_pelo_leitor_e_ignorado(adm):
    """O conversor do painel so aceita algarismos ASCII: um id em algarismos arabe-indicos nao lista o Leitor."""
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    antes = _perms(contas_db)
    r = _post(cli, _form_sem_leitor(cli, contas, contas_db, [("grupos", _digitos_arabes(l))]))
    assert r.status_code == 303 and _perms(contas_db) == antes


@pytest.mark.parametrize("valor", ["{L}", " {L} ", "000{L}", pytest.param("0" * 5000 + "{L}", id="5000-zeros-e-o-id")])
def test_id_do_leitor_aceito_pelo_conversor_entra_na_lista(adm, valor):
    """Com espacos ou zeros a esquerda o id continua valido (a mesma regra do resto do painel): o Leitor passa a ser listado,
    a versao enviada nao o inclui e o envio inteiro e recusado."""
    cli, contas, contas_db, _ = adm
    antes = _perms(contas_db)
    r = _post(cli, _form_sem_leitor(cli, contas, contas_db, [("grupos", valor)]))
    assert r.status_code == 409 and RECUSA in r.text and _perms(contas_db) == antes


def test_a_rota_usa_o_conversor_do_painel(adm, monkeypatch):
    from painel.rotas_extras import admin
    cli, _, contas_db, _ = adm
    dados = _formulario(cli)
    monkeypatch.setattr(admin, "_converter_id", lambda texto: None)        # nenhum grupo passa: nada listado
    antes = _perms(contas_db)
    r = _post(cli, dados)
    assert r.status_code == 409 and _perms(contas_db) == antes


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


def test_reenvio_da_mesma_pagina_e_recusado(adm):
    """Um segundo clique em Salvar leva a versao antiga: e recusado, mesmo que o estado ja seja o pedido."""
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    dados = [(k, v) for k, v in _formulario(cli) if k != f"p-{l}-ver_nomes_revisores"]
    assert _post(cli, dados).status_code == 303
    r = _post(cli, dados)
    assert r.status_code == 409 and _perms(contas_db)["Leitor"] == {"ver_painel"}


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


def test_segundo_clique_depois_de_salvar_sem_mudanca_nao_grava_nada(adm):
    """Se o primeiro envio nao mudou nada, a versao continua a mesma: o segundo tambem passa e tambem nao grava nada."""
    cli, _, contas_db, _ = adm
    dados = _formulario(cli)
    antes, n_aud = _perms(contas_db), len(_auditoria(contas_db))
    assert _post(cli, dados).status_code == 303 and _post(cli, dados).status_code == 303
    assert _perms(contas_db) == antes and len(_auditoria(contas_db)) == n_aud
