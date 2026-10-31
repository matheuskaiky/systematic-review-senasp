"""Registro de administracao com filtros por acao e por alvo e paginacao de 50 linhas. So leitura: nada e gravado. A
leitura filtrada e uma consulta do repositorio de contas (SQLite e PostgreSQL), e um alvo que nao aparece no registro
nunca chega ao banco. Todos os bancos sao temporarios."""
import html
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A
from painel import rotulos as R
from test_admin import adm  # noqa: F401
from test_painel import demo  # noqa: F401
from test_painel_acessibilidade import verificar

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
CHAVES = ["id", "quando", "admin_login", "acao", "alvo", "detalhe"]
REPETIDO = "O endereço traz o mesmo filtro mais de uma vez."
ACAO_INVALIDA = "A ação escolhida não existe. Escolha uma da lista."
ALVO_INVALIDO = "O alvo escolhido não aparece no registro. Escolha um da lista."
PAGINA_INVALIDA = "O número da página não é válido."
OCUPADO = "O banco de contas está ocupado. Tente de novo em alguns segundos."


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


def _quando(i):
    return f"2026-10-{1 + i // 1440:02d}T{(i // 60) % 24:02d}:{i % 60:02d}:00+00:00"


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


def _semear(c, linhas):
    """linhas: (acao, alvo) na ordem de gravacao; o id cresce com a ordem."""
    for i, (acao, alvo) in enumerate(linhas):
        c.auditar("chefe", acao, alvo, f"d{i}", _quando(i))


def _ids(c, **k):
    return [l["detalhe"] for l in c.auditoria_filtrada(**k)["linhas"]]


def test_registro_vazio(contas):
    assert contas.auditoria_filtrada(None, None, 1, 50) == {"total": 0, "linhas": [], "alvos": []}


def test_pagina_mais_recentes_primeiro(contas):
    _semear(contas, [("criar_usuario", f"u{i % 3}") for i in range(120)])
    r = contas.auditoria_filtrada(None, None, 1, 50)
    assert r["total"] == 120 and len(r["linhas"]) == 50
    assert [l["detalhe"] for l in r["linhas"]] == [f"d{i}" for i in range(119, 69, -1)]
    assert list(r["linhas"][0]) == CHAVES
    l = r["linhas"][0]
    assert (l["quando"], l["admin_login"], l["acao"], l["alvo"]) == (_quando(119), "chefe", "criar_usuario", "u2")
    assert type(l["id"]) is int
    assert _ids(contas, acao=None, alvo=None, pagina=3, por_pagina=50) == [f"d{i}" for i in range(19, -1, -1)]
    r4 = contas.auditoria_filtrada(None, None, 4, 50)
    assert r4["total"] == 120 and r4["linhas"] == []
    assert [l["detalhe"] for l in contas.auditoria_filtrada(None, None, 2, 7)["linhas"]] == [f"d{i}" for i in range(112, 105, -1)]


def test_filtros_por_acao_alvo_e_os_dois(contas):
    _semear(contas, [("criar_usuario", "ana"), ("editar_usuario", "ana"), ("criar_usuario", "bia"),
                     ("salvar_permissoes", "Leitor"), ("criar_usuario", "ana"), ("redefinir_senha", "bia")])
    assert _ids(contas, acao="criar_usuario", alvo=None, pagina=1, por_pagina=50) == ["d4", "d2", "d0"]
    assert _ids(contas, acao=None, alvo="ana", pagina=1, por_pagina=50) == ["d4", "d1", "d0"]
    assert _ids(contas, acao="criar_usuario", alvo="ana", pagina=1, por_pagina=50) == ["d4", "d0"]
    assert contas.auditoria_filtrada("criar_usuario", "ana", 1, 50)["total"] == 2
    assert contas.auditoria_filtrada("revogar_token", None, 1, 50) == {"total": 0, "linhas": [],
                                                                         "alvos": ["ana", "bia", "Leitor"]}
    r = contas.auditoria_filtrada("criar_usuario", None, 2, 2)
    assert r["total"] == 3 and [l["detalhe"] for l in r["linhas"]] == ["d0"]


def test_filtro_de_alvo_e_exato(contas):
    _semear(contas, [("criar_usuario", "ana"), ("criar_usuario", "Ana"), ("criar_usuario", "ana "),
                     ("criar_usuario", "anabela")])
    assert _ids(contas, acao=None, alvo="ana", pagina=1, por_pagina=50) == ["d0"]
    assert _ids(contas, acao=None, alvo="Ana", pagina=1, por_pagina=50) == ["d1"]
    assert _ids(contas, acao=None, alvo="ana ", pagina=1, por_pagina=50) == ["d2"]


def test_lista_de_alvos(contas):
    _semear(contas, [("criar_usuario", "beta"), ("criar_grupo", "Ágata"), ("criar_usuario", "alfa"),
                     ("criar_grupo", "Alfa"), ("criar_usuario", "beta"), ("criar_usuario", None),
                     ("criar_usuario", ""), ("alterar_divulgacao", "real"), ("criar_grupo", "<b>&")])
    assert contas.auditoria_filtrada(None, None, 1, 50)["alvos"] == ["<b>&", "Ágata", "Alfa", "alfa", "beta", "real"]


def _espiar_consultas(contas, monkeypatch):
    """Registra (sql, parametros) de cada consulta feita dentro das conexoes do repositorio."""
    original = type(contas)._conexao
    consultas = []

    class Espia:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=()):
            consultas.append((sql, tuple(params)))
            return self._conn.execute(sql, params)

        def __getattr__(self, nome):
            return getattr(self._conn, nome)

    @contextmanager
    def espiar(self, *a, **k):
        with original(self, *a, **k) as conn:
            yield Espia(conn)
    monkeypatch.setattr(type(contas), "_conexao", espiar)
    return consultas


def test_alvo_que_nao_aparece_nao_consulta(contas, monkeypatch):
    _semear(contas, [("criar_usuario", "ana")])
    consultas = _espiar_consultas(contas, monkeypatch)
    for alvo in ("zé", "a\x00b", "x" * 5000, ""):
        consultas.clear()
        assert contas.auditoria_filtrada(None, alvo, 1, 50) == {"total": 0, "linhas": [], "alvos": ["ana"]}
        assert consultas and all(alvo not in p for _, p in consultas) and all(alvo not in q for q, _ in consultas if alvo)
    consultas.clear()
    contas.auditoria_filtrada(None, "ana", 1, 50)
    assert any("ana" in p for _, p in consultas)


def test_uma_so_transacao(contas, monkeypatch):
    _semear(contas, [("criar_usuario", "ana")])
    original = type(contas)._conexao
    chamadas = []

    def contar(self, *a, **k):
        chamadas.append(k.get("escrita", a[0] if a else False))
        return original(self, *a, **k)
    monkeypatch.setattr(type(contas), "_conexao", contar)
    contas.auditoria_filtrada("criar_usuario", "ana", 1, 50)
    contas.auditoria_filtrada(None, "inexistente", 1, 50)
    assert chamadas == [False, False]


@pytest.mark.parametrize("args", [
    ("acao_inexistente", None, 1, 50), ("", None, 1, 50), (1, None, 1, 50),
    (None, 7, 1, 50), (None, b"ana", 1, 50),
    (None, None, 0, 50), (None, None, 1_000_001, 50), (None, None, True, 50), (None, None, "1", 50), (None, None, 1.0, 50),
    (None, None, 1, 0), (None, None, 1, 201), (None, None, 1, True),
    (None, None, -1, 50), (None, None, None, 50), (None, None, 1, -1), (None, None, 1, None), (None, None, 1, "50"),
    (None, None, 1, 50.0), ("x", 7, 0, 0),
])
def test_argumentos_invalidos(tmp_path, monkeypatch, args):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    aberturas = []
    original = ContasSQLite._conexao

    def contar(self, *a, **k):
        aberturas.append(1)
        return original(self, *a, **k)
    monkeypatch.setattr(ContasSQLite, "_conexao", contar)
    with pytest.raises(ValueError):
        c.auditoria_filtrada(*args)
    assert aberturas == []


def test_limites_validos(tmp_path):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    _semear(c, [("criar_usuario", "ana")])
    assert c.auditoria_filtrada(None, None, 1_000_000, 200) == {"total": 1, "linhas": [], "alvos": ["ana"]}
    assert len(c.auditoria_filtrada(None, None, 1, 1)["linhas"]) == 1


def test_alvo_gravado_com_tipo_errado_fica_fora_da_lista(tmp_path):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    _semear(c, [("criar_usuario", "ana")])
    con = sqlite3.connect(tmp_path / "contas.db")
    con.execute("INSERT INTO auditoria_admin (quando, admin_login, acao, alvo, detalhe) "
                "VALUES ('2026-10-31T00:00:00+00:00', 'chefe', 'criar_usuario', x'41', 'blob')")
    con.commit()
    con.close()
    r = c.auditoria_filtrada(None, None, 1, 50)
    assert r["alvos"] == ["ana"] and r["total"] == 2 and r["linhas"][0]["detalhe"] == "blob"
    assert c.auditoria_filtrada(None, "A", 1, 50) == {"total": 0, "linhas": [], "alvos": ["ana"]}


def test_alvo_gravado_longo(contas):
    longo = "g" * 5000
    _semear(contas, [("criar_usuario", longo), ("criar_usuario", "ana")])
    r = contas.auditoria_filtrada(None, longo, 1, 50)
    assert r["alvos"] == ["ana", longo] and [l["detalhe"] for l in r["linhas"]] == ["d0"]


def test_auditoria_antiga_nao_muda(contas):
    _semear(contas, [("criar_usuario", "ana"), ("criar_grupo", "G")])
    assert contas.auditoria() == [
        {"quando": _quando(1), "admin_login": "chefe", "acao": "criar_grupo", "alvo": "G", "detalhe": "d1"},
        {"quando": _quando(0), "admin_login": "chefe", "acao": "criar_usuario", "alvo": "ana", "detalhe": "d0"}]


# ======================== pagina ========================

def _linhas(h):
    corpo = h[h.index("<tbody>"):h.index("</tbody>")] if "<tbody>" in h else ""
    return re.findall(r"<tr>\s*<td>[^<]*</td>\s*<td>[^<]*</td>\s*<td>[^<]*</td>\s*<td>[^<]*</td>\s*<td>([^<]*)</td>", corpo)


def _nav(h):
    assert 'class="paginacao"' in h, "a pagina nao tem a barra de paginacao"
    i = h.index('class="paginacao"')
    return h[i:h.index("</nav>", i)]


def _get(cli, qs=""):
    return cli.get("/admin/auditoria" + qs)


def _seed_pagina(contas, n=60):
    _semear(contas, [("criar_usuario" if i % 2 == 0 else "editar_usuario", "ana" if i % 3 == 0 else "bia")
                     for i in range(n)])


def test_sem_filtro_primeira_pagina(adm):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    h = _get(cli).text
    assert _linhas(h) == [f"d{i}" for i in range(59, 9, -1)]
    assert '<p class="contagem"><strong>60</strong> registro(s)</p>' in h
    nav = _nav(h)
    assert "<span>Página 1 de 2</span>" in nav and '<a href="/admin/auditoria?p=2">Próxima →</a>' in nav
    assert "Anterior" not in nav
    assert verificar(h) == []


def test_segunda_pagina(adm):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    h = _get(cli, "?p=2").text
    assert _linhas(h) == [f"d{i}" for i in range(9, -1, -1)]
    nav = _nav(h)
    assert '<a href="/admin/auditoria?p=1">← Anterior</a>' in nav and "<span>Página 2 de 2</span>" in nav
    assert "Próxima" not in nav


def test_uma_pagina_so(adm):
    cli, contas, _, _ = adm
    _seed_pagina(contas, 50)
    h = _get(cli).text
    assert len(_linhas(h)) == 50 and "<span>Página 1 de 1</span>" in _nav(h)
    assert "Anterior" not in _nav(h) and "Próxima" not in _nav(h)


def test_filtros_na_pagina_e_nos_links(adm):
    cli, contas, _, _ = adm
    _seed_pagina(contas, 240)
    h = _get(cli, "?acao=criar_usuario&alvo=ana").text
    esperadas = [f"d{i}" for i in range(239, -1, -1) if i % 2 == 0 and i % 3 == 0]
    assert len(esperadas) == 40 and _linhas(h) == esperadas
    assert '<p class="contagem"><strong>40</strong> registro(s)</p>' in h
    assert "<span>Página 1 de 1</span>" in _nav(h)
    assert '<option value="criar_usuario" selected>Criação de usuário</option>' in h
    assert '<option value="ana" selected>ana</option>' in h and '<option value="bia">bia</option>' in h
    assert '<a href="/admin/auditoria">Limpar</a>' in h
    h2 = _get(cli, "?acao=criar_usuario").text
    assert len(_linhas(h2)) == 50 and '<a href="/admin/auditoria?acao=criar_usuario&amp;p=2">Próxima →</a>' in _nav(h2)
    h3 = _get(cli, "?alvo=bia&p=2").text
    assert '<a href="/admin/auditoria?alvo=bia&amp;p=1">← Anterior</a>' in _nav(h3)
    h4 = _get(cli, "?acao=criar_usuario&alvo=bia&p=2").text
    assert '<a href="/admin/auditoria?acao=criar_usuario&amp;alvo=bia&amp;p=1">← Anterior</a>' in _nav(h4)


def test_alvo_especial_nos_links_de_pagina(adm):
    cli, contas, _, _ = adm
    alvo = "a&b=c +ç/%"
    _semear(contas, [("criar_usuario", alvo)] * 60 + [("criar_usuario", "a")])
    h = _get(cli, "?" + urlencode({"alvo": alvo})).text
    assert len(_linhas(h)) == 50
    m = re.search(r'<a href="(/admin/auditoria\?[^"]+)">Próxima →</a>', _nav(h))
    assert m and m.group(1) == "/admin/auditoria?alvo=a%26b%3Dc+%2B%C3%A7%2F%25&amp;p=2"
    h2 = cli.get(html.unescape(m.group(1))).text
    assert _linhas(h2) == [f"d{i}" for i in range(9, -1, -1)]
    assert f'<option value="{html.escape(alvo)}" selected>' in h2


def test_alvo_longo_na_pagina(adm):
    cli, contas, _, _ = adm
    longo = "g" * 5000
    _semear(contas, [("criar_usuario", longo), ("criar_usuario", "ana")])
    h = _get(cli).text
    assert f'<option value="{longo}">{longo}</option>' in h and f"<td>{longo}</td>" in h
    r = _get(cli, "?alvo=" + longo)
    assert r.status_code == 200 and f'<option value="{longo}" selected>{longo}</option>' in r.text
    assert _linhas(r.text) == ["d0"]


def test_formulario_de_filtros(adm):
    cli, contas, _, _ = adm
    _semear(contas, [("criar_usuario", "bia"), ("criar_grupo", "Ágata"), ("criar_grupo", "<b>&")])
    h = _get(cli).text
    assert '<form class="filtros" method="get" action="/admin/auditoria">' in h
    i = h.index('<form class="filtros" method="get" action="/admin/auditoria">')
    form = h[i:h.index("</form>", i)]
    assert 'name="alvo"' in form
    opcoes_acao = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', form[:form.index('name="alvo"')])
    assert opcoes_acao == [("", "todas")] + [(a, R.ACOES_AUDITORIA[a]) for a in A.ACOES_AUDITORIA]
    opcoes_alvo = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', form[form.index('name="alvo"'):])
    assert opcoes_alvo == [("", "todos"), ("&lt;b&gt;&amp;", "&lt;b&gt;&amp;"), ("Ágata", "Ágata"), ("bia", "bia")]
    assert '<label>Ação <select name="acao">' in form and '<label>Alvo <select name="alvo">' in form
    assert '<button class="botao" type="submit">Filtrar</button>' in form
    assert "Limpar" not in form and " selected" not in form
    h2 = _get(cli, "?alvo=%3Cb%3E%26").text
    assert '<option value="&lt;b&gt;&amp;" selected>&lt;b&gt;&amp;</option>' in h2 and _linhas(h2) == ["d2"]


def test_vazios(adm):
    cli, contas, _, _ = adm
    h = _get(cli).text
    assert '<p class="vazio">Nenhuma ação registrada.</p>' in h and "<table" not in h and 'class="paginacao"' not in h
    assert '<p class="contagem">' not in h and '<form class="filtros"' in h
    h = _get(cli, "?acao=criar_grupo").text
    assert ('<p class="vazio">Nenhuma ação registrada com estes filtros. <a href="/admin/auditoria">Limpar filtros</a>.</p>'
            in h) and "<table" not in h and 'class="paginacao"' not in h
    _seed_pagina(contas)
    h = _get(cli, "?p=5").text
    assert ('<p class="vazio">Não há registros nesta página: são 60 em 2 página(s). '
            '<a href="/admin/auditoria?p=1">Ir para a primeira</a>.</p>') in h
    assert "<table" not in h and 'class="paginacao"' not in h
    h = _get(cli, "?acao=editar_usuario&p=9").text
    assert ('são 30 em 1 página(s). <a href="/admin/auditoria?acao=editar_usuario&amp;p=1">Ir para a primeira</a>.'
            in h)
    h = _get(cli, "?acao=revogar_token").text
    assert "Nenhuma ação registrada com estes filtros." in h


@pytest.mark.parametrize("qs", ["", "?acao=", "?alvo=", "?p=", "?acao=&alvo=&p=", "?p=1", "?p=%201%20", "?p=01"])
def test_valores_que_valem_como_sem_filtro(adm, qs):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    r = _get(cli, qs)
    assert r.status_code == 200 and _linhas(r.text)[:1] == ["d59"] and "<span>Página 1 de 2</span>" in r.text


@pytest.mark.parametrize("qs,texto", [
    ("?acao=a&acao=a", REPETIDO), ("?alvo=ana&alvo=ana", REPETIDO), ("?p=1&p=1", REPETIDO), ("?acao=&acao=", REPETIDO),
    ("?acao=x&p=0&acao=y", REPETIDO),
    ("?acao=x", ACAO_INVALIDA), ("?acao=CRIAR_USUARIO", ACAO_INVALIDA), ("?acao=%20criar_usuario", ACAO_INVALIDA),
    ("?acao=x&p=0", ACAO_INVALIDA), ("?acao=x&alvo=zz", ACAO_INVALIDA),
    ("?p=0", PAGINA_INVALIDA), ("?p=-1", PAGINA_INVALIDA), ("?p=abc", PAGINA_INVALIDA), ("?p=1.5", PAGINA_INVALIDA),
    ("?p=%2B1", PAGINA_INVALIDA), ("?p=1000001", PAGINA_INVALIDA), ("?p=%D9%A2", PAGINA_INVALIDA),
    ("?p=%20", PAGINA_INVALIDA), ("?p=" + "9" * 30, PAGINA_INVALIDA), ("?p=0&alvo=zz", PAGINA_INVALIDA),
    ("?alvo=zz", ALVO_INVALIDO), ("?alvo=Ana", ALVO_INVALIDO), ("?alvo=%00", ALVO_INVALIDO),
    ("?alvo=ana%20", ALVO_INVALIDO),
])
def test_parametros_invalidos(adm, qs, texto):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    r = _get(cli, qs)
    assert r.status_code == 404 and f"<p>{texto}</p>" in r.text
    titulo = "Página inválida" if texto == PAGINA_INVALIDA else "Filtro inválido"
    assert f"<h1>{titulo}</h1>" in r.text and "<table" not in r.text


def test_pagina_maxima_valida(adm):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    r = _get(cli, "?p=1000000")
    assert r.status_code == 200 and "são 60 em 2 página(s)" in r.text


def test_a_rota_usa_a_leitura_filtrada(adm, monkeypatch):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    chamadas = []
    original = contas.auditoria_filtrada

    def espia(acao, alvo, pagina, por_pagina):
        chamadas.append((acao, alvo, pagina, por_pagina))
        return original(acao, alvo, pagina, por_pagina)
    monkeypatch.setattr(contas, "auditoria_filtrada", espia)
    _get(cli)
    _get(cli, "?acao=criar_usuario&alvo=ana&p=2")
    _get(cli, "?alvo=zz")
    _get(cli, "?acao=x")
    _get(cli, "?p=0")
    assert chamadas == [(None, None, 1, 50), ("criar_usuario", "ana", 2, 50), (None, "zz", 1, 50)]


def test_a_tabela_vem_da_leitura_filtrada(adm, monkeypatch):
    cli, contas, _, _ = adm
    monkeypatch.setattr(contas, "auditoria_filtrada", lambda *a: {
        "total": 51, "alvos": ["Leitor"],
        "linhas": [{"id": 9, "quando": "2026-10-31T12:00:00+00:00", "admin_login": "outro", "acao": "salvar_permissoes",
                    "alvo": "Leitor", "detalhe": '{"antes": [], "depois": ["triar_artigos"], "concedidas": '
                                                '["triar_artigos"], "retiradas": [], "justificativa": "", "origem": "edicao"}'},
                   {"id": 8, "quando": "2026-10-31T11:00:00+00:00", "admin_login": "outro", "acao": "renomear_grupo",
                    "alvo": "Leitor", "detalhe": "A -> Leitor"}]})
    h = _get(cli).text
    assert _linhas(h) == ["Concedidas: triar_artigos. Retiradas: nenhuma.", "A -&gt; Leitor"]
    assert "<td>Permissões salvas</td>" in h and "<td>outro</td>" in h
    assert '<p class="contagem"><strong>51</strong> registro(s)</p>' in h and "<span>Página 1 de 2</span>" in _nav(h)


def test_contas_ocupadas(adm, monkeypatch):
    cli, contas, _, _ = adm

    def ocupado(*a):
        raise A.ContasOcupadas("x")
    monkeypatch.setattr(contas, "auditoria_filtrada", ocupado)
    r = _get(cli, "?acao=criar_usuario")
    assert r.status_code == 503 and OCUPADO in r.text


def test_ok_continua(adm):
    cli, contas, _, _ = adm
    _seed_pagina(contas)
    h = _get(cli, "?ok=1&p=2").text
    assert "Alteração gravada." in h and '<a href="/admin/auditoria?p=1">← Anterior</a>' in _nav(h)


def test_nada_e_gravado(adm):
    cli, contas, contas_db, _ = adm
    _seed_pagina(contas)
    antes = sqlite3.connect(contas_db).execute("SELECT * FROM auditoria_admin ORDER BY id").fetchall()
    for qs in ("", "?acao=criar_usuario", "?alvo=ana&p=2", "?p=5", "?acao=x"):
        _get(cli, qs)
    assert sqlite3.connect(contas_db).execute("SELECT * FROM auditoria_admin ORDER BY id").fetchall() == antes
