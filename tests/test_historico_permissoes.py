"""Historico das alteracoes de permissoes de um grupo e o filtro "Alteradas" da pagina do grupo. So leitura: nada e
gravado. O historico segue as renomeacoes registradas ("antigo -> novo") e para no registro de criacao do grupo, para que
um nome reaproveitado nao herde o historico de outro grupo. Todos os bancos sao temporarios."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A
from test_admin import _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401
from test_painel_acessibilidade import verificar

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
OCUPADO = "O banco de contas está ocupado. Tente de novo em alguns segundos."
SEM_HISTORICO = "Nenhuma alteração de permissões registrada para este grupo."
FILTRO_SEM_HISTORICO = "Este grupo ainda não tem alterações de permissões registradas."
FILTRO_ANTIGA = ("A última alteração deste grupo foi registrada sem a lista das permissões alteradas. "
                 "Veja o histórico abaixo.")
VAZIO = "Nenhuma permissão corresponde à busca e aos filtros."


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


def _det(concedidas=(), retiradas=(), justificativa="", origem="edicao", antes=(), depois=None, escolhidas=None):
    d = {"antes": sorted(antes), "depois": sorted(depois if depois is not None else set(antes) | set(concedidas)),
         "concedidas": list(concedidas), "retiradas": list(retiradas), "justificativa": justificativa, "origem": origem}
    if escolhidas is not None:
        d["escolhidas"] = list(escolhidas)
    return json.dumps(d, ensure_ascii=False)


def _r(i, acao, alvo, detalhe=None, quem="chefe"):
    return {"id": i, "quando": f"2026-10-{i:02d}T12:00:00+00:00", "admin_login": quem, "acao": acao, "alvo": alvo,
            "detalhe": detalhe}


# ======================== ler_detalhe_auditoria ========================

DET_OK = _det(["triar_artigos"], [], "j", antes=["ver_painel"])


@pytest.mark.parametrize("texto,esperado", [
    (DET_OK, json.loads(DET_OK)),
    (_det(["triar_artigos"], escolhidas=["triar_artigos"], origem="referencia:publico"),
     json.loads(_det(["triar_artigos"], escolhidas=["triar_artigos"], origem="referencia:publico"))),
    (None, None), (7, None), ("", None), ("{", None), ("[]", None), ("null", None),
    ("+triar_artigos, -ver_custos", None), ("antes: ver_painel; depois: ver_painel, ver_custos", None),
    (DET_OK.replace('"origem"', '"extra": 1, "origem"'), None),
    (DET_OK.replace('"justificativa": "j"', '"justificativa": 1'), None),
    (DET_OK.replace('"antes": ["ver_painel"]', '"antes": "ver_painel"'), None),
    (DET_OK.replace('"antes": ["ver_painel"]', '"antes": [1]'), None),
    (DET_OK.replace('"origem": "edicao"', '"origem": null'), None),
])
def test_ler_detalhe(texto, esperado):
    assert A.ler_detalhe_auditoria(texto) == esperado


def test_resumo_usa_a_leitura(monkeypatch):
    monkeypatch.setattr(A, "ler_detalhe_auditoria", lambda t: None)
    assert A.resumo_detalhe_auditoria(DET_OK) is None
    falso = json.loads(_det(["ver_custos"], ["triar_artigos"]))
    monkeypatch.setattr(A, "ler_detalhe_auditoria", lambda t: falso)
    assert A.resumo_detalhe_auditoria("qualquer") == "Concedidas: ver_custos. Retiradas: triar_artigos."


# ======================== historico_do_grupo ========================

def _hist(nome, registros):
    return [(h["id"], h["nome"]) for h in A.historico_do_grupo(nome, registros)]


def test_historico_vazio():
    assert A.historico_do_grupo("Leitor", []) == []


def test_entrada_completa():
    regs = [_r(3, "salvar_permissoes", "Leitor", DET_OK, quem="ana"), _r(2, "salvar_permissoes", "Leitor", "+x, -y"),
            _r(1, "salvar_permissoes", "Leitor", None)]
    assert A.historico_do_grupo("Leitor", regs) == [
        {"id": 3, "quando": "2026-10-03T12:00:00+00:00", "admin_login": "ana", "nome": "Leitor",
         "detalhe": json.loads(DET_OK), "texto": None},
        {"id": 2, "quando": "2026-10-02T12:00:00+00:00", "admin_login": "chefe", "nome": "Leitor", "detalhe": None,
         "texto": "+x, -y"},
        {"id": 1, "quando": "2026-10-01T12:00:00+00:00", "admin_login": "chefe", "nome": "Leitor", "detalhe": None,
         "texto": None}]


def test_entrada_usa_a_leitura_do_detalhe(monkeypatch):
    chamadas = []
    monkeypatch.setattr(A, "ler_detalhe_auditoria", lambda t: chamadas.append(t) or {"lido": t})
    h = A.historico_do_grupo("Leitor", [_r(1, "salvar_permissoes", "Leitor", "abc")])
    assert chamadas == ["abc"] and h[0]["detalhe"] == {"lido": "abc"} and h[0]["texto"] is None


@pytest.mark.parametrize("nome,registros,esperado", [
    # so as alteracoes de permissoes do grupo, na ordem recebida
    ("Leitor", [_r(5, "salvar_permissoes", "Revisor", DET_OK), _r(4, "salvar_permissoes", "Leitor", DET_OK),
                _r(3, "criar_usuario", "Leitor"), _r(2, "editar_usuario", "Leitor"),
                _r(1, "salvar_permissoes", "Leitor", DET_OK)],
     [(4, "Leitor"), (1, "Leitor")]),
    # comparacao exata do nome
    ("Leitor", [_r(3, "salvar_permissoes", "leitor", DET_OK), _r(2, "salvar_permissoes", "Leitor ", DET_OK),
                _r(1, "salvar_permissoes", "Leitor", DET_OK)], [(1, "Leitor")]),
    # renomeacao: os registros anteriores ficam com o nome antigo
    ("Bolsistas", [_r(4, "salvar_permissoes", "Bolsistas", DET_OK), _r(3, "renomear_grupo", "Bolsistas", "Monitores -> Bolsistas"),
                   _r(2, "salvar_permissoes", "Monitores", DET_OK), _r(1, "salvar_permissoes", "Bolsistas", DET_OK)],
     [(4, "Bolsistas"), (2, "Monitores")]),
    # varias renomeacoes em cadeia, inclusive so de maiusculas
    ("C", [_r(6, "salvar_permissoes", "C", DET_OK), _r(5, "renomear_grupo", "C", "b -> C"),
           _r(4, "salvar_permissoes", "b", DET_OK), _r(3, "renomear_grupo", "b", "B -> b"),
           _r(2, "salvar_permissoes", "B", DET_OK), _r(1, "salvar_permissoes", "C", DET_OK)],
     [(6, "C"), (4, "b"), (2, "B")]),
    # para no registro de criacao: um nome reaproveitado nao herda o historico antigo
    ("Monitores", [_r(5, "salvar_permissoes", "Monitores", DET_OK), _r(4, "criar_grupo", "Monitores"),
                   _r(3, "renomear_grupo", "Bolsistas", "Monitores -> Bolsistas"),
                   _r(2, "salvar_permissoes", "Monitores", DET_OK), _r(1, "criar_grupo", "Monitores")],
     [(5, "Monitores")]),
    # o grupo que tinha o nome antes segue com o seu historico
    ("Bolsistas", [_r(5, "salvar_permissoes", "Monitores", DET_OK), _r(4, "criar_grupo", "Monitores"),
                   _r(3, "renomear_grupo", "Bolsistas", "Monitores -> Bolsistas"),
                   _r(2, "salvar_permissoes", "Monitores", DET_OK), _r(1, "criar_grupo", "Monitores")],
     [(2, "Monitores")]),
    # criacao e renomeacao de outro grupo, sem o nome acompanhado, nao interrompem
    ("Leitor", [_r(5, "salvar_permissoes", "Leitor", DET_OK), _r(4, "criar_grupo", "Outro"),
                _r(3, "renomear_grupo", "Outro", "Antigo -> Outro"), _r(2, "renomear_grupo", "Leitora", "Leitor2 -> Leitora"),
                _r(1, "salvar_permissoes", "Leitor", DET_OK)],
     [(5, "Leitor"), (1, "Leitor")]),
    # outro grupo que tinha o nome acompanhado e o largou: os registros anteriores sao daquele grupo
    ("Leitor", [_r(4, "salvar_permissoes", "Leitor", DET_OK), _r(3, "criar_grupo", "Outro2"),
                _r(2, "renomear_grupo", "Outro", "Leitor -> Outro"), _r(1, "salvar_permissoes", "Leitor", DET_OK)],
     [(4, "Leitor")]),
    # depois de seguir uma renomeacao, quem largou o nome antigo tambem encerra
    ("B", [_r(5, "salvar_permissoes", "B", DET_OK), _r(4, "renomear_grupo", "B", "A -> B"),
           _r(3, "salvar_permissoes", "A", DET_OK), _r(2, "renomear_grupo", "Z", "A -> Z"),
           _r(1, "salvar_permissoes", "A", DET_OK)],
     [(5, "B"), (3, "A")]),
    # so a renomeacao exata ("<nome> -> <alvo>") de outro grupo encerra
    ("Leitor", [_r(3, "salvar_permissoes", "Leitor", DET_OK), _r(2, "renomear_grupo", "Outro", "leitor -> Outro"),
                _r(1, "salvar_permissoes", "Leitor", DET_OK)],
     [(3, "Leitor"), (1, "Leitor")]),
    # nome com " -> " dentro: o nome antigo e tudo antes do ultimo " -> " + nome atual
    ("c", [_r(3, "renomear_grupo", "c", "a -> b -> c"), _r(2, "salvar_permissoes", "a -> b", DET_OK),
           _r(1, "salvar_permissoes", "a", DET_OK)], [(2, "a -> b")]),
    # renomeacao para o mesmo nome continua
    ("X", [_r(3, "renomear_grupo", "X", "X -> X"), _r(2, "salvar_permissoes", "X", DET_OK)], [(2, "X")]),
])
def test_cadeia(nome, registros, esperado):
    assert _hist(nome, registros) == esperado


@pytest.mark.parametrize("detalhe", [None, 7, "", "Monitores->Bolsistas", "Monitores -> bolsistas", " -> Bolsistas",
                                     "Monitores -> Bolsistas ", "Bolsistas"])
def test_renomeacao_ilegivel_para_o_historico(detalhe):
    regs = [_r(3, "salvar_permissoes", "Bolsistas", DET_OK), _r(2, "renomear_grupo", "Bolsistas", detalhe),
            _r(1, "salvar_permissoes", "Monitores", DET_OK), _r(0, "salvar_permissoes", "Bolsistas", DET_OK)]
    assert _hist("Bolsistas", regs) == [(3, "Bolsistas")]


@pytest.mark.parametrize("ruim", [
    {"alvo": 7}, {"alvo": None}, {"alvo": b"Leitor"}, {"acao": None}, {"acao": 3},
])
def test_registro_com_tipo_errado_e_ignorado(ruim):
    r = _r(2, "salvar_permissoes", "Leitor", DET_OK)
    r.update(ruim)
    assert _hist("Leitor", [r, _r(1, "salvar_permissoes", "Leitor", DET_OK)]) == [(1, "Leitor")]


def test_texto_so_quando_e_texto():
    h = A.historico_do_grupo("Leitor", [_r(2, "salvar_permissoes", "Leitor", 5), _r(1, "salvar_permissoes", "Leitor", "")])
    assert [(x["detalhe"], x["texto"]) for x in h] == [(None, None), (None, "")]


# ======================== repositorio ========================

@pytest.fixture(params=["sqlite", "postgres"])
def contas(request, tmp_path):
    if request.param == "sqlite":
        c = ContasSQLite(tmp_path / "contas.db")
        c.garantir_padrao()
        yield c
        return
    from adaptadores import migrador_postgres as M
    from adaptadores.contas_postgres import ContasPostgres
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    url = request.getfixturevalue("pg_url")
    M.aplicar(url)
    pool = criar_pool(url, maximo=8)
    c = ContasPostgres(pool, chaves_do_banco(pool))
    c.garantir_padrao()
    yield c
    pool.close()


def test_registros_de_permissoes(contas):
    for i, (acao, alvo) in enumerate([("criar_usuario", "ana"), ("criar_grupo", "G"), ("salvar_permissoes", "G"),
                                      ("renomear_grupo", "H"), ("alterar_divulgacao", "real"), ("salvar_permissoes", "Leitor")]):
        contas.auditar("chefe", acao, alvo, f"d{i}", f"2026-10-31T00:00:0{i}+00:00")
    r = contas.registros_de_permissoes()
    assert [(l["acao"], l["alvo"], l["detalhe"]) for l in r] == [
        ("salvar_permissoes", "Leitor", "d5"), ("renomear_grupo", "H", "d3"), ("salvar_permissoes", "G", "d2"),
        ("criar_grupo", "G", "d1")]
    assert all(list(l) == ["id", "quando", "admin_login", "acao", "alvo", "detalhe"] for l in r)
    assert [l["id"] for l in r] == sorted((l["id"] for l in r), reverse=True) and type(r[0]["id"]) is int
    assert r[0]["quando"] == "2026-10-31T00:00:05+00:00" and r[0]["admin_login"] == "chefe"


def test_registros_de_permissoes_vazio(contas):
    assert contas.registros_de_permissoes() == []


def test_registros_uma_so_conexao(contas, monkeypatch):
    original = type(contas)._conexao
    chamadas = []

    def contar(self, *a, **k):
        chamadas.append(k.get("escrita", a[0] if a else False))
        return original(self, *a, **k)
    monkeypatch.setattr(type(contas), "_conexao", contar)
    contas.registros_de_permissoes()
    assert chamadas == [False]


# ======================== pagina do grupo ========================

def _grava(contas, acao, alvo, detalhe, quando, quem="chefe"):
    contas.auditar(quem, acao, alvo, detalhe, quando)


def _secao(h):
    assert '<h2 id="historico">Histórico de alterações</h2>' in h
    i = h.index('<h2 id="historico">Histórico de alterações</h2>')
    fim = h.index("</section>", i)
    return h[i:fim]


RESTAURAR = re.compile(r'<p><a href="/admin/grupos/\d+/restaurar\?registro=\d+">Ver as diferenças para o estado anterior a esta '
                       r'alteração</a></p>')


def _itens(sec):
    """As entradas do historico sem o link de restauracao (coberto em test_restaurar_estado.py)."""
    sec = RESTAURAR.sub("", re.sub(r">\s+<", "><", sec).strip())
    return re.findall(r'<li class="historico-item">(.*?)</li>\s*(?=<li class="historico-item">|</ol>)', sec, re.S)


def _pagina(cli, contas_db, nome="Leitor", qs=""):
    return cli.get(f"/admin/grupos/{_gid(contas_db, nome)}{qs}").text


def test_secao_vazia(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, contas_db)
    sec = _secao(h)
    assert f'<p class="vazio">{SEM_HISTORICO}</p>' in sec and "<ol" not in sec
    assert verificar(h) == []


def test_secao_com_entradas(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", "+triar_artigos", "2026-10-01T12:00:00+00:00")
    _grava(contas, "salvar_permissoes", "Leitor", None, "2026-10-02T12:00:00+00:00")
    _grava(contas, "salvar_permissoes", "Leitor",
           _det(["triar_artigos", "ver_custos"], ["ver_nomes_revisores"], "Pedido <da> coordenação",
                origem="referencia:estudante_direito", antes=["ver_painel", "ver_nomes_revisores"],
                escolhidas=["triar_artigos"]), "2026-10-03T12:00:00+00:00", quem="ana")
    _grava(contas, "salvar_permissoes", "Leitor", _det([], ["ver_custos"]), "2026-10-04T12:00:00+00:00")
    h = _pagina(cli, contas_db)
    sec = _secao(h)
    assert '<ol class="historico">' in sec
    itens = _itens(sec)
    assert len(itens) == 4
    assert itens[0] == (
        '<p><strong>04/10/2026 12:00</strong> · chefe</p>'
        '<p>Concedidas: nenhuma.</p>'
        f'<p>Retiradas: {A.PERMISSOES["ver_custos"]}.</p>')
    assert itens[1] == (
        '<p><strong>03/10/2026 12:00</strong> · ana</p>'
        f'<p>Concedidas: {A.PERMISSOES["triar_artigos"]}, {A.PERMISSOES["ver_custos"]}.</p>'
        f'<p>Retiradas: {A.PERMISSOES["ver_nomes_revisores"]}.</p>'
        '<p>Origem: comparação com a referência de Estudante de Direito.</p>'
        '<p>Justificativa: Pedido &lt;da&gt; coordenação</p>')
    assert itens[2] == ('<p><strong>02/10/2026 12:00</strong> · chefe</p>'
                        '<p>Registro sem detalhe legível.</p>')
    assert itens[3] == ('<p><strong>01/10/2026 12:00</strong> · chefe</p>'
                        '<p>Registro antigo: +triar_artigos</p>')
    assert verificar(h) == []


def test_chave_desconhecida_e_origem_desconhecida(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["permissao_antiga"], [], origem="referencia:x"),
           "2026-10-01T12:00:00+00:00")
    itens = _itens(_secao(_pagina(cli, contas_db)))
    assert itens == ['<p><strong>01/10/2026 12:00</strong> · chefe</p><p>Concedidas: permissao_antiga.</p>'
                     '<p>Retiradas: nenhuma.</p>']


def _renomeado(contas):
    """Grupo criado como Monitores, alterado e renomeado para Bolsistas pelos metodos do repositorio."""
    q = "2026-10-01T11:00:00+00:00"
    gid = contas.criar_grupo("Monitores", q, auditoria=("chefe", "criar_grupo", "Monitores", None, q))
    _grava(contas, "salvar_permissoes", "Monitores", _det(["triar_artigos"]), "2026-10-01T12:00:00+00:00")
    q = "2026-10-02T12:00:00+00:00"
    contas.renomear_grupo(gid, "Bolsistas", auditoria=("chefe", "renomear_grupo", "Bolsistas", "Monitores -> Bolsistas", q))


def test_ordem_gravada_das_permissoes(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["ver_custos", "triar_artigos"], ["ver_chamadas", "ver_painel"]),
           "2026-10-01T12:00:00+00:00")
    itens = _itens(_secao(_pagina(cli, contas_db)))
    assert itens == ['<p><strong>01/10/2026 12:00</strong> · chefe</p>'
                     f'<p>Concedidas: {A.PERMISSOES["ver_custos"]}, {A.PERMISSOES["triar_artigos"]}.</p>'
                     f'<p>Retiradas: {A.PERMISSOES["ver_chamadas"]}, {A.PERMISSOES["ver_painel"]}.</p>']


def test_nome_antigo_aparece(adm):
    cli, contas, contas_db, _ = adm
    _renomeado(contas)
    itens = _itens(_secao(_pagina(cli, contas_db, "Bolsistas")))
    assert itens == ['<p><strong>01/10/2026 12:00</strong> · chefe · com o nome «Monitores»</p>'
                     f'<p>Concedidas: {A.PERMISSOES["triar_artigos"]}.</p><p>Retiradas: nenhuma.</p>']


def test_vinte_mais_recentes(adm):
    cli, contas, contas_db, _ = adm
    for i in range(23):
        _grava(contas, "salvar_permissoes", "Leitor", _det([], [], justificativa=f"j{i}"),
               f"2026-10-01T12:{i:02d}:00+00:00")
    sec = _secao(_pagina(cli, contas_db))
    itens = _itens(sec)
    assert len(itens) == 20 and "Justificativa: j22" in itens[0] and "Justificativa: j3" in itens[19]
    assert ('<p>Mostrando as 20 alterações mais recentes de 23. As anteriores estão no '
            '<a href="/admin/auditoria?acao=salvar_permissoes">registro de administração</a>.</p>') in sec
    for i in range(3):
        _grava(contas, "salvar_permissoes", "Revisor", DET_OK, "2026-10-02T12:00:00+00:00")
    assert "Mostrando" not in _secao(_pagina(cli, contas_db, "Revisor"))


def test_exatamente_vinte(adm):
    cli, contas, contas_db, _ = adm
    for i in range(20):
        _grava(contas, "salvar_permissoes", "Leitor", DET_OK, "2026-10-01T12:00:00+00:00")
    sec = _secao(_pagina(cli, contas_db))
    assert len(_itens(sec)) == 20 and "Mostrando" not in sec


def test_secao_no_lugar(adm):
    cli, contas, contas_db, _ = adm
    h = _pagina(cli, contas_db)
    assert '<h2 id="historico">' in h and 'class="modulo"' in h and 'class="perm-previa"' in h
    assert h.index('<h2 id="historico">') > h.index('class="modulo"')
    assert h.index('<h2 id="historico">') < h.index('class="perm-previa"')
    assert '<section class="perm-historico" aria-labelledby="historico">' in h


def test_administrador_tem_a_secao(adm):
    cli, _, contas_db, _ = adm
    assert SEM_HISTORICO in _secao(_pagina(cli, contas_db, "Administrador"))


def test_a_pagina_le_os_registros_uma_vez(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    original = contas.registros_de_permissoes
    chamadas = []
    monkeypatch.setattr(contas, "registros_de_permissoes", lambda: chamadas.append(1) or original())
    _pagina(cli, contas_db)
    _pagina(cli, contas_db, qs="?filtro=alteradas")
    assert chamadas == [1, 1]


def test_a_pagina_usa_o_historico_do_dominio(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", DET_OK, "2026-10-01T12:00:00+00:00")
    vistos = []
    falso = [{"id": 99, "quando": "2026-10-05T12:00:00+00:00", "admin_login": "zeca", "nome": "Leitor",
              "detalhe": None, "texto": "falso"}]
    monkeypatch.setattr(A, "historico_do_grupo", lambda nome, regs: vistos.append((nome, len(regs))) or falso)
    itens = _itens(_secao(_pagina(cli, contas_db)))
    assert vistos == [("Leitor", 1)] and itens == ['<p><strong>05/10/2026 12:00</strong> · zeca</p>'
                                                   '<p>Registro antigo: falso</p>']


def test_contas_ocupadas_no_historico(adm, monkeypatch):
    cli, contas, contas_db, _ = adm

    def ocupado():
        raise A.ContasOcupadas("x")
    monkeypatch.setattr(contas, "registros_de_permissoes", ocupado)
    r = cli.get(f"/admin/grupos/{_gid(contas_db, 'Leitor')}")
    assert r.status_code == 503 and OCUPADO in r.text


# ======================== filtro "Alteradas" ========================

def _chaves(h):
    return re.findall(r'<li class="perm" data-chave="([^"]+)">', h)


def _opcoes_filtro(h):
    i = h.index('<select id="perm-filtro" name="filtro">')
    return re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', h[i:h.index("</select>", i)])


def test_opcao_alteradas(adm):
    cli, _, contas_db, _ = adm
    for nome in ("Leitor", "Visitante", "Revisor"):
        op = _opcoes_filtro(_pagina(cli, contas_db, nome))
        assert ("alteradas", "Alteradas na última alteração") in op
        assert op.index(("alteradas", "Alteradas na última alteração")) == op.index(("administrativas", "Administrativas")) + 1
    assert ("alteradas", "Alteradas na última alteração") not in _opcoes_filtro(_pagina(cli, contas_db, "Administrador"))
    h = _pagina(cli, contas_db, qs="?filtro=alteradas")
    assert '<option value="alteradas" selected>Alteradas na última alteração</option>' in h


def test_alteradas_lista_a_ultima(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["ver_chamadas"]), "2026-10-01T12:00:00+00:00")
    _grava(contas, "salvar_permissoes", "Leitor", _det(["triar_artigos"], ["ver_custos"]), "2026-10-02T12:00:00+00:00",
           quem="ana")
    h = _pagina(cli, contas_db, qs="?filtro=alteradas")
    assert _chaves(h) == [k for k in A.PERMISSOES if k in {"triar_artigos", "ver_custos"}]
    assert ("<p>Permissões concedidas ou retiradas na última alteração, em 02/10/2026 12:00, por ana. "
            "Esta página só mostra; nada é alterado aqui.</p>") in h


def test_alteradas_com_busca_e_modulo(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["triar_artigos"], ["ver_custos"]), "2026-10-02T12:00:00+00:00")
    modulo_custos = A.CATALOGO_PERMISSOES["ver_custos"]["modulo"]
    h = _pagina(cli, contas_db, qs=f"?filtro=alteradas&modulo={modulo_custos}")
    assert _chaves(h) == ["ver_custos"]
    h = _pagina(cli, contas_db, qs="?filtro=alteradas&q=zzzz")
    assert _chaves(h) == [] and f'<p class="vazio">{VAZIO}</p>' in h
    assert "Permissões concedidas ou retiradas na última alteração" in h


def test_alteradas_sem_historico(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, contas_db, qs="?filtro=alteradas")
    assert _chaves(h) == [] and f'<p class="aviso" role="status">{FILTRO_SEM_HISTORICO}</p>' in h
    assert VAZIO not in h


@pytest.mark.parametrize("detalhe", ["+triar_artigos", None, "antes: ver_painel; depois: ver_painel, ver_custos", "{"])
def test_alteradas_com_ultima_ilegivel(adm, detalhe):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["triar_artigos"]), "2026-10-01T12:00:00+00:00")
    _grava(contas, "salvar_permissoes", "Leitor", detalhe, "2026-10-02T12:00:00+00:00")
    h = _pagina(cli, contas_db, qs="?filtro=alteradas")
    assert _chaves(h) == [] and f'<p class="aviso" role="status">{FILTRO_ANTIGA}</p>' in h and VAZIO not in h


def test_alteradas_com_chave_fora_do_catalogo(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["permissao_antiga"], ["ver_custos"]), "2026-10-01T12:00:00+00:00")
    assert _chaves(_pagina(cli, contas_db, qs="?filtro=alteradas")) == ["ver_custos"]


def test_alteradas_segue_a_renomeacao(adm):
    cli, contas, contas_db, _ = adm
    _renomeado(contas)
    assert _chaves(_pagina(cli, contas_db, "Bolsistas", "?filtro=alteradas")) == ["triar_artigos"]


def test_alteradas_nao_toca_no_formulario_de_edicao(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["triar_artigos"]), "2026-10-01T12:00:00+00:00")
    h = cli.get(f"/admin/grupos/{_gid(contas_db, 'Leitor')}/editar?filtro=alteradas").text
    assert len(re.findall(r'name="exibida" value="([^"]+)"', h)) == len(A.PERMISSOES)


@pytest.mark.parametrize("filtro", ["alteradas", "", "habilitadas"])
def test_filtrar_permissoes_com_alteradas(filtro):
    alteradas = {"triar_artigos", "ver_custos"}
    r = A.filtrar_permissoes("Leitor", {"ver_painel", "ver_custos"}, "", filtro, "", alteradas=alteradas)
    if filtro == "alteradas":
        assert r == [k for k in A.PERMISSOES if k in alteradas]
    else:
        assert r == A.filtrar_permissoes("Leitor", {"ver_painel", "ver_custos"}, "", filtro, "")


@pytest.mark.parametrize("alteradas", [None, set(), frozenset()])
def test_filtrar_alteradas_sem_conjunto(alteradas):
    assert A.filtrar_permissoes("Leitor", {"ver_painel"}, "", "alteradas", "", alteradas=alteradas) == []


def test_nada_e_gravado(adm):
    cli, contas, contas_db, _ = adm
    _grava(contas, "salvar_permissoes", "Leitor", _det(["triar_artigos"]), "2026-10-01T12:00:00+00:00")
    con = sqlite3.connect(contas_db)
    antes = (con.execute("SELECT * FROM auditoria_admin ORDER BY id").fetchall(),
             con.execute("SELECT * FROM grupo_permissoes ORDER BY grupo_id, permissao").fetchall())
    for qs in ("", "?filtro=alteradas"):
        _pagina(cli, contas_db, qs=qs)
    con = sqlite3.connect(contas_db)
    assert (con.execute("SELECT * FROM auditoria_admin ORDER BY id").fetchall(),
            con.execute("SELECT * FROM grupo_permissoes ORDER BY grupo_id, permissao").fetchall()) == antes
