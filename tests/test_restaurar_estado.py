"""Diferencas entre o estado atual de um grupo e o estado anterior a uma alteracao do seu historico. So leitura: a pagina
lista as diferencas e nao grava nada, nao marca nada e nao leva a nenhuma gravacao. Todos os bancos sao temporarios."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from dominio import autenticacao as A
from test_admin import _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401
from test_painel_acessibilidade import verificar

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
ADMIN = "O grupo Administrador tem acesso integral e não pode ser alterado."
FORA = "Esta alteração não está no histórico deste grupo."
SEM_ANTES = "Esta alteração foi registrada sem o estado anterior completo; não há o que restaurar."
OCUPADO = "O banco de contas está ocupado. Tente de novo em alguns segundos."
IGUAL = "Este grupo já está igual ao estado anterior a esta alteração."
SO_MOSTRA = "<p>Esta página só mostra; nada é alterado aqui.</p>"


@pytest.fixture(autouse=True)
def _nunca_abre_o_data_real(monkeypatch):
    """Todo teste deste arquivo falha se algo tentar abrir um arquivo SQLite dentro do data/ de verdade (contas reais)."""
    original = sqlite3.connect

    def conectar(caminho, *a, **k):
        alvo = Path(str(caminho)).resolve() if str(caminho) != ":memory:" else None
        if alvo is not None and (alvo == DADOS_REAIS or DADOS_REAIS in alvo.parents):
            raise AssertionError(f"teste tentou abrir {alvo}")
        return original(caminho, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", conectar)


def _det(concedidas=(), retiradas=(), antes=(), justificativa="", origem="edicao"):
    return json.dumps({"antes": sorted(antes), "depois": sorted((set(antes) | set(concedidas)) - set(retiradas)),
                       "concedidas": list(concedidas), "retiradas": list(retiradas), "justificativa": justificativa,
                       "origem": origem}, ensure_ascii=False)


def _entrada(antes, i=7):
    return {"id": i, "quando": "2026-10-05T12:00:00+00:00", "admin_login": "ana", "nome": "Leitor",
            "detalhe": json.loads(_det(antes=antes)), "texto": None}


def _chaves(itens):
    return [i["permissao"] for i in itens]


# ======================== diferencas_entre ========================

@pytest.mark.parametrize("atuais,alvo,conceder,retirar", [
    (set(), set(), [], []),
    ({"ver_painel"}, {"ver_painel"}, [], []),
    ({"ver_painel"}, {"ver_painel", "ver_custos", "triar_artigos"}, ["triar_artigos", "ver_custos"], []),
    ({"ver_painel", "ver_chamadas", "ver_custos"}, {"ver_painel"}, [], ["ver_chamadas", "ver_custos"]),
    ({"ver_painel", "ver_chamadas"}, {"ver_custos"}, ["ver_custos"], ["ver_painel", "ver_chamadas"]),
    ({"ver_painel", "permissao_antiga"}, {"outra_antiga", "ver_painel"}, [], []),
    ({"ver_painel"}, frozenset({"ver_custos"}), ["ver_custos"], ["ver_painel"]),
    (["ver_painel", "ver_painel"], ["ver_custos", "ver_custos", "permissao_antiga"], ["ver_custos"], ["ver_painel"]),
])
def test_diferencas_entre(atuais, alvo, conceder, retirar):
    ordem = list(A.PERMISSOES)
    r = A.diferencas_entre(atuais, alvo)
    assert list(r) == ["conceder", "retirar"]
    assert _chaves(r["conceder"]) == sorted(conceder, key=ordem.index)
    assert _chaves(r["retirar"]) == sorted(retirar, key=ordem.index)
    for item in r["conceder"] + r["retirar"]:
        p = item["permissao"]
        assert item == {"permissao": p, "descricao": A.PERMISSOES[p],
                        "sensivel": A.CATALOGO_PERMISSOES[p]["sensibilidade"] in A.ROTULOS_SENSIBILIDADE, "marcada": False}


def test_referencia_usa_as_diferencas(monkeypatch):
    falso = {"conceder": [{"permissao": "x", "descricao": "X", "sensivel": False, "marcada": False}], "retirar": []}
    vistos = []
    monkeypatch.setattr(A, "diferencas_entre", lambda atuais, alvo: vistos.append((set(atuais), set(alvo))) or falso)
    r = A.comparar_com_referencia("Leitor", {"ver_painel"}, "publico")
    assert vistos == [({"ver_painel"}, {"ver_painel"})]
    assert r["conceder"] == falso["conceder"] and r["retirar"] == [] and r["perfil"] == "publico" and r["erros"] == []


def test_referencia_nao_muda():
    r = A.comparar_com_referencia("Leitor", {"ver_painel", "ver_custos"}, "estudante_direito")
    assert _chaves(r["conceder"]) == [k for k in A.PERMISSOES if k in A.REFERENCIAS_PERFIS["estudante_direito"] - {"ver_painel"}]
    assert _chaves(r["retirar"]) == ["ver_custos"]


# ======================== comparar_com_alteracao ========================

def test_alteracao_com_diferencas():
    r = A.comparar_com_alteracao("Leitor", {"ver_painel", "ver_chamadas"}, _entrada(["ver_painel", "ver_custos"]))
    assert list(r) == ["registro", "conceder", "retirar", "erros"]
    assert r["registro"] == 7 and r["erros"] == []
    assert _chaves(r["conceder"]) == ["ver_custos"] and _chaves(r["retirar"]) == ["ver_chamadas"]


def test_alteracao_usa_as_diferencas(monkeypatch):
    falso = {"conceder": [], "retirar": [{"permissao": "y", "descricao": "Y", "sensivel": True, "marcada": False}]}
    vistos = []
    monkeypatch.setattr(A, "diferencas_entre", lambda atuais, alvo: vistos.append((set(atuais), set(alvo))) or falso)
    r = A.comparar_com_alteracao("Leitor", {"ver_painel"}, _entrada(["ver_custos"]))
    assert vistos == [({"ver_painel"}, {"ver_custos"})] and r["retirar"] == falso["retirar"]


@pytest.mark.parametrize("grupo,entrada,erro", [
    ("Administrador", _entrada(["ver_painel"]), ADMIN),
    ("Administrador", None, ADMIN),
    ("Leitor", None, FORA),
    ("Leitor", {**_entrada([]), "detalhe": None, "texto": "+x"}, SEM_ANTES),
    ("Leitor", {**_entrada([]), "detalhe": None, "texto": None}, SEM_ANTES),
])
def test_alteracao_com_erro(grupo, entrada, erro):
    r = A.comparar_com_alteracao(grupo, {"ver_painel"}, entrada)
    assert r == {"registro": None, "conceder": [], "retirar": [], "erros": [erro]}


def test_visitante_lista_o_estado_anterior_como_esta():
    r = A.comparar_com_alteracao("Visitante", {"ver_painel"}, _entrada(["ver_painel", "ver_custos", "triar_artigos"]))
    assert _chaves(r["conceder"]) == ["triar_artigos", "ver_custos"] and r["erros"] == []


def test_alteracao_sem_diferencas():
    r = A.comparar_com_alteracao("Visitante", {"ver_painel"}, _entrada(["ver_painel"], i=3))
    assert r == {"registro": 3, "conceder": [], "retirar": [], "erros": []}


# ======================== pagina ========================

def _grava(contas, alvo, detalhe, quando="2026-10-05T12:00:00+00:00", quem="ana", acao="salvar_permissoes"):
    contas.auditar(quem, acao, alvo, detalhe, quando)


def _ultimo_id(contas_db):
    return sqlite3.connect(contas_db).execute("SELECT max(id) FROM auditoria_admin").fetchone()[0]


def _get(cli, contas_db, nome="Leitor", qs=""):
    return cli.get(f"/admin/grupos/{_gid(contas_db, nome)}/restaurar{qs}")


def _definir(contas_db, nome, permissoes):
    con = sqlite3.connect(contas_db)
    gid = con.execute("SELECT grupo_id FROM grupos WHERE nome=?", (nome,)).fetchone()[0]
    con.execute("DELETE FROM grupo_permissoes WHERE grupo_id=?", (gid,))
    con.executemany("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, ?)", [(gid, p) for p in permissoes])
    con.commit()


def _listas(h):
    secoes = {}
    for titulo, corpo in re.findall(r"<h2>([^<]+)</h2>\s*<ul>(.*?)</ul>", h, re.S):
        secoes[titulo] = [re.sub(r"\s+", " ", x).strip() for x in re.findall(r"<li>(.*?)</li>", corpo, re.S)]
    return secoes


def test_pagina_lista_as_diferencas(adm):
    cli, contas, contas_db, _ = adm
    _definir(contas_db, "Leitor", {"ver_painel", "ver_chamadas", "triar_artigos"})
    _grava(contas, "Leitor", _det(["ver_chamadas"], ["ver_custos"], antes=["ver_painel", "ver_custos"]))
    i = _ultimo_id(contas_db)
    r = _get(cli, contas_db, qs=f"?registro={i}")
    assert r.status_code == 200
    h = r.text
    assert "<h1>Diferenças para um estado anterior: Leitor</h1>" in h
    assert "<title>Diferenças para um estado anterior — Leitor" in h
    assert "<p>Estado anterior à alteração de 05/10/2026 12:00 por ana.</p>" in h
    sens = A.ROTULOS_SENSIBILIDADE[A.CATALOGO_PERMISSOES["ver_custos"]["sensibilidade"]]
    sens_ch = A.ROTULOS_SENSIBILIDADE[A.CATALOGO_PERMISSOES["ver_chamadas"]["sensibilidade"]]
    assert _listas(h) == {
        "O estado anterior tem e o grupo não (1)": [f'{A.PERMISSOES["ver_custos"]} <span class="perm-sensivel">◆ {sens}</span>'],
        "O grupo tem e o estado anterior não (2)": [
            f'{A.PERMISSOES["ver_chamadas"]} <span class="perm-sensivel">◆ {sens_ch}</span>', A.PERMISSOES["triar_artigos"]],
    }
    assert h.index("O estado anterior tem e o grupo não") < h.index("O grupo tem e o estado anterior não")
    assert SO_MOSTRA in h
    corpo = h[h.index("<main"):h.index("</main>")]
    assert "<form" not in corpo and "<input" not in corpo and "<button" not in corpo
    assert f'<p><a href="/admin/grupos/{_gid(contas_db, "Leitor")}">Voltar ao grupo</a></p>' in h
    assert verificar(h) == []


def test_so_uma_lista(adm):
    cli, contas, contas_db, _ = adm
    _definir(contas_db, "Leitor", {"ver_painel"})
    _grava(contas, "Leitor", _det(["ver_painel"], [], antes=["ver_painel", "triar_artigos"]))
    h = _get(cli, contas_db, qs=f"?registro={_ultimo_id(contas_db)}").text
    assert list(_listas(h)) == ["O estado anterior tem e o grupo não (1)"]
    assert "O grupo tem e o estado anterior não" not in h


def test_sem_diferencas(adm):
    cli, contas, contas_db, _ = adm
    _definir(contas_db, "Leitor", {"ver_painel"})
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]))
    h = _get(cli, contas_db, qs=f"?registro={_ultimo_id(contas_db)}").text
    assert f'<p class="vazio">{IGUAL}</p>' in h and "<h2>" not in h[h.index("<main"):] and SO_MOSTRA not in h


def test_nome_antigo(adm):
    cli, contas, contas_db, _ = adm
    q = "2026-10-01T11:00:00+00:00"
    gid = contas.criar_grupo("Monitores", q, auditoria=("chefe", "criar_grupo", "Monitores", None, q))
    _grava(contas, "Monitores", _det(["triar_artigos"], [], antes=["ver_painel"]), quem="chefe")
    i = _ultimo_id(contas_db)
    q = "2026-10-06T11:00:00+00:00"
    contas.renomear_grupo(gid, "Bolsistas", auditoria=("chefe", "renomear_grupo", "Bolsistas", "Monitores -> Bolsistas", q))
    h = cli.get(f"/admin/grupos/{gid}/restaurar?registro={i}").text
    assert "<p>Estado anterior à alteração de 05/10/2026 12:00 por chefe · com o nome «Monitores».</p>" in h


def test_registro_sem_estado_anterior(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", "antes: ver_painel; depois: ver_custos, ver_painel", quem="linha-de-comando")
    r = _get(cli, contas_db, qs=f"?registro={_ultimo_id(contas_db)}")
    assert r.status_code == 200 and f'<p class="aviso" role="status">{SEM_ANTES}</p>' in r.text
    assert "<p>Estado anterior à alteração de 05/10/2026 12:00 por linha-de-comando.</p>" in r.text
    assert r.text.index("<p>Estado anterior") < r.text.index(SEM_ANTES)
    assert "<h2>" not in r.text[r.text.index("<main"):] and SO_MOSTRA not in r.text


@pytest.mark.parametrize("qs", ["", "?registro=", "?registro=abc", "?registro=-1", "?registro=0", "?registro=1.5",
                                "?registro=99999", "?registro=" + "9" * 30, "?registro=%D9%A2",
                                "?registro={i}&registro={i}"])
def test_registro_invalido_ou_fora(adm, qs, monkeypatch):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]))
    i = _ultimo_id(contas_db)
    leituras = []
    original = contas.registros_de_permissoes
    monkeypatch.setattr(contas, "registros_de_permissoes", lambda: leituras.append(1) or original())
    r = _get(cli, contas_db, qs=qs.format(i=i))
    assert r.status_code == 404 and "<h1>Alteração não encontrada</h1>" in r.text and f"<p>{FORA}</p>" in r.text
    assert leituras == ([1] if qs in ("?registro=99999", "?registro=0") else [])


def test_registro_com_espacos_vale(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]))
    r = _get(cli, contas_db, qs=f"?registro=%20{_ultimo_id(contas_db)}%20")
    assert r.status_code == 200


@pytest.mark.parametrize("caso", ["outro_grupo", "outra_acao", "nome_reaproveitado"])
def test_registro_de_fora_do_historico(adm, caso):
    cli, contas, contas_db, _ = adm
    if caso == "outro_grupo":
        _grava(contas, "Revisor", _det(["ver_custos"], [], antes=["ver_painel"]))
        i = _ultimo_id(contas_db)
        r = _get(cli, contas_db, "Leitor", f"?registro={i}")
    elif caso == "outra_acao":
        _grava(contas, "Leitor", None, acao="criar_usuario")
        i = _ultimo_id(contas_db)
        r = _get(cli, contas_db, "Leitor", f"?registro={i}")
    else:
        q = "2026-10-01T11:00:00+00:00"
        g1 = contas.criar_grupo("Monitores", q, auditoria=("chefe", "criar_grupo", "Monitores", None, q))
        _grava(contas, "Monitores", _det(["triar_artigos"], [], antes=["ver_painel"]))
        i = _ultimo_id(contas_db)
        q = "2026-10-06T11:00:00+00:00"
        contas.renomear_grupo(g1, "Bolsistas", auditoria=("chefe", "renomear_grupo", "Bolsistas", "Monitores -> Bolsistas", q))
        q = "2026-10-07T11:00:00+00:00"
        g2 = contas.criar_grupo("Monitores", q, auditoria=("chefe", "criar_grupo", "Monitores", None, q))
        r = cli.get(f"/admin/grupos/{g2}/restaurar?registro={i}")
        assert cli.get(f"/admin/grupos/{g1}/restaurar?registro={i}").status_code == 200
    assert r.status_code == 404 and f"<p>{FORA}</p>" in r.text


def test_administrador(adm):
    cli, contas, contas_db, _ = adm
    r = _get(cli, contas_db, "Administrador", "?registro=1")
    assert r.status_code == 404 and f"<p>{FORA}</p>" in r.text
    _grava(contas, "Administrador", _det(["ver_custos"], [], antes=["ver_painel"]))
    i = _ultimo_id(contas_db)
    r = _get(cli, contas_db, "Administrador", f"?registro={i}")
    assert r.status_code == 200 and f'<p class="aviso" role="status">{ADMIN}</p>' in r.text
    assert "<h2>" not in r.text[r.text.index("<main"):] and SO_MOSTRA not in r.text
    h = cli.get(f"/admin/grupos/{_gid(contas_db, 'Administrador')}").text
    assert "Concedidas:" in h and "/restaurar?registro=" not in h


@pytest.mark.parametrize("caminho,texto", [
    ("/admin/grupos/9999/restaurar?registro=1", "Não existe o grupo nº 9999."),
    ("/admin/grupos/9999/restaurar?registro=abc", "Não existe o grupo nº 9999."),
    ("/admin/grupos/abc/restaurar?registro=abc", "Algum número ou parâmetro do endereço não é válido."),
])
def test_grupo_resolvido_antes_do_registro(adm, caminho, texto):
    cli, _, _, _ = adm
    r = cli.get(caminho)
    assert r.status_code == 404 and texto in r.text and FORA not in r.text


def test_permissao_gravada_invalida(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]))
    i = _ultimo_id(contas_db)
    con = sqlite3.connect(contas_db)
    con.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, x'41')", (_gid(contas_db, "Leitor"),))
    con.commit()
    for qs in (f"?registro={i}", "?registro=abc"):
        r = _get(cli, contas_db, qs=qs)
        assert r.status_code == 409 and "As permissões gravadas deste grupo têm um valor inválido. Nada foi alterado." in r.text


def test_contas_ocupadas(adm, monkeypatch):
    cli, contas, contas_db, _ = adm

    def ocupado():
        raise A.ContasOcupadas("x")
    monkeypatch.setattr(contas, "registros_de_permissoes", ocupado)
    r = _get(cli, contas_db, qs="?registro=1")
    assert r.status_code == 503 and OCUPADO in r.text


def test_a_rota_usa_o_historico_e_a_comparacao(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]))
    i = _ultimo_id(contas_db)
    leituras, vistos = [], []
    original = contas.registros_de_permissoes
    monkeypatch.setattr(contas, "registros_de_permissoes", lambda: leituras.append(1) or original())
    hist = A.historico_do_grupo
    monkeypatch.setattr(A, "historico_do_grupo", lambda nome, regs: vistos.append(nome) or hist(nome, regs))
    falso = {"registro": i, "conceder": [], "retirar": [], "erros": []}
    monkeypatch.setattr(A, "comparar_com_alteracao", lambda g, atuais, e: vistos.append((g, e["id"])) or falso)
    h = _get(cli, contas_db, qs=f"?registro={i}").text
    assert leituras == [1] and vistos == ["Leitor", ("Leitor", i)] and IGUAL in h


def test_nada_e_gravado(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]))
    con = sqlite3.connect(contas_db)
    antes = (con.execute("SELECT * FROM auditoria_admin ORDER BY id").fetchall(),
             con.execute("SELECT * FROM grupo_permissoes ORDER BY grupo_id, permissao").fetchall())
    _get(cli, contas_db, qs=f"?registro={_ultimo_id(contas_db)}")
    con = sqlite3.connect(contas_db)
    assert (con.execute("SELECT * FROM auditoria_admin ORDER BY id").fetchall(),
            con.execute("SELECT * FROM grupo_permissoes ORDER BY grupo_id, permissao").fetchall()) == antes


# ======================== link no historico ========================

LINK = '<p><a href="/admin/grupos/{gid}/restaurar?registro={i}">Ver as diferenças para o estado anterior a esta alteração</a></p>'


def test_link_no_historico(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "Leitor", "+triar_artigos", "2026-10-01T12:00:00+00:00")
    _grava(contas, "Leitor", _det(["ver_custos"], [], antes=["ver_painel"]), "2026-10-02T12:00:00+00:00")
    i = _ultimo_id(contas_db)
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}").text
    sec = h[h.index('<h2 id="historico">'):h.index("</section>", h.index('<h2 id="historico">'))]
    assert sec.count("/restaurar?registro=") == 1 and LINK.format(gid=gid, i=i) in sec
    itens = re.findall(r'<li class="historico-item">(.*?)</li>', re.sub(r">\s+<", "><", sec), re.S)
    assert itens[0].endswith(LINK.format(gid=gid, i=i)) and "restaurar" not in itens[1]
