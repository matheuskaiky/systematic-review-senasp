"""Tela de permissoes de um grupo, so de leitura: resumo, modulos, busca e filtros por GET, sensibilidade em texto, dependencias,
identificador tecnico so nos detalhes e previa do menu calculada pela mesma regra de acesso do servidor. Nada se grava aqui.
"""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from dominio import autenticacao as A
from painel import navegacao
from test_admin import _csrf, _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401

SENSIVEIS_TEXTO = {"supervisao": "supervisão", "dados_pessoais": "dados pessoais", "tecnica_restrita": "técnica restrita",
                   "escrita_externa": "escrita externa", "dados_revisao": "dados de revisão", "financeira": "financeira"}
TODAS = list(A.PERMISSOES)
ORDEM_DA_PAGINA = [p for m in A.MODULOS_PERMISSAO for p in TODAS if A.CATALOGO_PERMISSOES[p]["modulo"] == m]


# ---------------- dominio ----------------
def test_rotulos_de_sensibilidade():
    assert A.ROTULOS_SENSIBILIDADE == SENSIVEIS_TEXTO and list(A.ROTULOS_SENSIBILIDADE) == list(SENSIVEIS_TEXTO)


def _efetivas(grupo, perms):
    return [p for p in TODAS if A.pode(grupo, perms, p)]


def _oraculo(grupo, perms):
    hab = _efetivas(grupo, perms)
    modulos = [m for m in A.MODULOS_PERMISSAO if any(A.CATALOGO_PERMISSOES[p]["modulo"] == m for p in hab)]
    sens = [p for p in hab if A.CATALOGO_PERMISSOES[p]["sensibilidade"] in SENSIVEIS_TEXTO]
    return {"habilitadas": hab, "total": len(TODAS), "modulos_com_acesso": modulos, "sensiveis_habilitadas": sens}


@pytest.mark.parametrize("grupo,permissoes", [
    ("Administrador", set()), ("Administrador", {"ver_painel"}),
    ("Visitante", set(TODAS)), ("Visitante", {"ver_painel", "ver_chamadas"}), ("Visitante", set()),
    ("Leitor", {"ver_painel", "ver_nomes_revisores"}), ("Revisor", set(A.GRUPOS_PADRAO["Revisor"])),
    ("Novo", set()), ("Novo", {"permissao_que_nao_existe", "ver_painel"}), ("Novo", frozenset({"enviar_coletas"})),
])
def test_resumo_do_grupo(grupo, permissoes):
    r = A.resumo_do_grupo(grupo, permissoes)
    assert r == _oraculo(grupo, permissoes)
    assert list(r) == ["habilitadas", "total", "modulos_com_acesso", "sensiveis_habilitadas"]


def test_resumo_usa_a_regra_pode(monkeypatch):
    monkeypatch.setattr(A, "pode", lambda g, p, e: e in ("ver_chamadas", "revogar_verificacao"))
    assert A.resumo_do_grupo("Leitor", set()) == {"habilitadas": ["ver_chamadas", "revogar_verificacao"], "total": len(TODAS),
                                                  "modulos_com_acesso": ["revisao", "tecnico"],
                                                  "sensiveis_habilitadas": ["ver_chamadas", "revogar_verificacao"]}


LEITOR = {"ver_painel", "ver_nomes_revisores"}


@pytest.mark.parametrize("busca,filtro,modulo,esperado", [
    ("", "", "", TODAS),
    (" " * 300, "", "", TODAS),                                             # so espacos: sem busca
    ("TRIAR", "", "", ["triar_artigos", "triar_texto_completo"]),          # casefold
    ("título", "", "", ["triar_artigos"]),
    ("titulo", "", "", ["triar_artigos"]),                                  # sem acento
    ("TÍTULO", "", "", ["triar_artigos"]),
    ("́́", "", "", TODAS),                                        # so marcas combinantes: vazio depois de normalizar
    ("\u0301" * 100, "", "", TODAS),                                       # 100 caracteres: ainda vale (e normaliza a vazio)
    ("\u0301" * 101, "", "", []),                                          # 101: o limite vem antes da normalizacao
    ("ver_chamadas", "", "", ["ver_chamadas"]),                             # tambem no identificador
    ("x" * 100, "", "", []),
    ("x" * 101, "", "", []),                                                # mais de 100 caracteres: nada
    ("  " + "triar" + " " * 200, "", "", ["triar_artigos", "triar_texto_completo"]),   # o limite vale depois do strip
    ("", "habilitadas", "", ["ver_painel", "ver_nomes_revisores"]),
    ("", "desabilitadas", "", [p for p in TODAS if p not in LEITOR]),
    ("", "sensiveis", "", ["ver_nomes_revisores", "ver_chamadas", "revogar_verificacao", "ver_estatisticas_usuarios",
                            "enviar_coletas", "ver_registros_revisao", "ver_custos"]),
    ("", "", "acompanhamento", ["ver_nomes_revisores", "ver_estatisticas_usuarios"]),
    ("ver", "habilitadas", "acompanhamento", ["ver_nomes_revisores"]),
    ("", "desabilitadas", "acompanhamento", ["ver_estatisticas_usuarios"]),
    ("", "Habilitadas", "", TODAS), ("", " habilitadas", "", TODAS), ("", "outro", "", TODAS),     # valor fora da lista: todas
    ("", "", "Revisao", TODAS), ("", "", "outro", TODAS),
    ("nada-assim", "", "", []),
])
def test_filtrar_permissoes(busca, filtro, modulo, esperado):
    assert A.filtrar_permissoes("Leitor", LEITOR, busca, filtro, modulo) == esperado


def test_busca_normaliza_compatibilidade():
    """NFKD: a ligadura "ﬁ" busca como "fi"."""
    fi = A.filtrar_permissoes("Leitor", LEITOR, "fi", "", "")
    assert fi and A.filtrar_permissoes("Leitor", LEITOR, "ﬁ", "", "") == fi


def test_filtro_segue_a_regra_efetiva():
    assert A.filtrar_permissoes("Administrador", set(), "", "habilitadas", "") == TODAS
    assert A.filtrar_permissoes("Visitante", set(TODAS), "", "habilitadas", "") == _efetivas("Visitante", set(TODAS))
    assert A.filtrar_permissoes("Visitante", set(TODAS), "", "desabilitadas", "") == sorted(
        A.PERMISSOES_PROIBIDAS_VISITANTE, key=TODAS.index)


def test_filtro_usa_a_regra_pode(monkeypatch):
    monkeypatch.setattr(A, "pode", lambda g, p, e: e == "enviar_coletas")
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "habilitadas", "") == ["enviar_coletas"]
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "desabilitadas", "") == [p for p in TODAS if p != "enviar_coletas"]


# ---------------- rota ----------------
def test_regra_da_rota_nova():
    assert A.regra_explicita("GET", "/admin/grupos/3") == ("GET", "/admin/grupos/{grupo_id:digitos}", A.SO_ADMIN)


def _pagina(cli, gid, **params):
    r = cli.get(f"/admin/grupos/{gid}", params=params)
    assert r.status_code == 200
    return r.text


def _itens(h):
    """{chave: html do item} de cada permissao listada, e a ordem em que aparecem."""
    achados = re.findall(r'<li class="perm" data-chave="([a-z_]+)">(.*?)</li>\s*(?=<li class="perm"|</ul>)', h, re.S)
    return dict(achados), [c for c, _ in achados]


def _modulos(h):
    return re.findall(r'<details open class="modulo" data-modulo="([a-z_]+)">\s*<summary>([^<]+)</summary>', h)


def _ativos(contas_db, gid):
    return sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM usuarios WHERE grupo_id=? AND ativo=1", (gid,)).fetchone()[0]


@pytest.mark.parametrize("grupo", ["Administrador", "Visitante", "Leitor", "Revisor"])
def test_resumo_e_itens_de_cada_grupo(adm, grupo):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, grupo)
    perms = next(g["permissoes"] for g in contas.grupos() if g["grupo_id"] == gid)
    r = _oraculo(grupo, perms)
    h = _pagina(cli, gid)
    assert f"<h1>{grupo}</h1>" in h
    assert (f'<p class="perm-resumo">{_ativos(contas_db, gid)} usuários ativos · {len(r["habilitadas"])} de {r["total"]} capacidades · '
            f'{len(r["modulos_com_acesso"])} módulos com acesso · Sensíveis habilitadas: {len(r["sensiveis_habilitadas"])}</p>') in h
    itens, ordem = _itens(h)
    assert ordem == ORDEM_DA_PAGINA                                         # por modulo; dentro dele, na ordem do catalogo
    for chave in TODAS:
        meta, item = A.CATALOGO_PERMISSOES[chave], itens[chave]
        assert f'<span class="perm-descricao">{A.PERMISSOES[chave]}</span>' in item
        if grupo == "Visitante" and chave in A.PERMISSOES_PROIBIDAS_VISITANTE:
            assert '<span class="perm-estado">Não permitida a quem não entrou</span>' in item
        else:
            estado = "Habilitada" if chave in r["habilitadas"] else "Não habilitada"
            assert f'<span class="perm-estado">{estado}</span>' in item
        sens = SENSIVEIS_TEXTO.get(meta["sensibilidade"])
        assert (f'<span class="perm-sensivel">◆ {sens}</span>' in item) if sens else ("perm-sensivel" not in item)
        deps = [f'<span class="perm-depende">precisa de: {A.PERMISSOES[d]}</span>' for d in meta["depende_de"]]
        assert re.findall(r'<span class="perm-depende">[^<]*</span>', item) == deps
        assert f'<details><summary>Detalhes técnicos</summary><code>{chave}</code></details>' in item
        assert item.count(chave) == 1                                       # a chave so aparece nos detalhes
    for m, corpo in re.findall(r'<details open class="modulo" data-modulo="([a-z_]+)">(.*?)</ul>\s*</details>', h, re.S):
        assert all(A.CATALOGO_PERMISSOES[c]["modulo"] == m for c in re.findall(r'data-chave="([a-z_]+)"', corpo))
    for chave, item in itens.items():                                       # partes do item, na ordem, sem repeticao
        partes = [x or "detalhes" for x in re.findall(r'class="perm-(descricao|estado|sensivel|depende)"|<details>', item)]
        sens = SENSIVEIS_TEXTO.get(A.CATALOGO_PERMISSOES[chave]["sensibilidade"])
        esperado = ["descricao", "estado"] + (["sensivel"] if sens else []) \
            + ["depende"] * len(A.CATALOGO_PERMISSOES[chave]["depende_de"]) + ["detalhes"]
        assert partes == esperado, chave
    modulos = _modulos(h)
    assert [m for m, _ in modulos] == list(A.MODULOS_PERMISSAO)
    for m, titulo in modulos:
        do_modulo = [p for p in TODAS if A.CATALOGO_PERMISSOES[p]["modulo"] == m]
        hab = [p for p in do_modulo if p in r["habilitadas"]]
        assert titulo == f"{A.MODULOS_PERMISSAO[m]} — {len(hab)} de {len(do_modulo)}"


def test_administrador_tem_aviso(adm):
    cli, _, contas_db, _ = adm
    assert "O Administrador tem todas as capacidades e não pode ser alterado." in _pagina(cli, _gid(contas_db, "Administrador"))
    assert "O Administrador tem todas" not in _pagina(cli, _gid(contas_db, "Leitor"))


def test_usuarios_ativos_por_grupo(adm):
    cli, contas, contas_db, _ = adm
    from test_admin import _criar
    for login, grupo in (("ana", "Leitor"), ("bia", "Leitor"), ("dani", "Leitor"), ("eva", "Leitor"), ("caio", "Revisor")):
        assert _criar(cli, contas_db, login=login, nome=login.title(), grupo=grupo).status_code == 303
    con = sqlite3.connect(contas_db)
    con.execute("UPDATE usuarios SET ativo=0 WHERE login='bia'")
    con.execute("UPDATE usuarios SET ativo=2 WHERE login='eva'")            # so 1 conta como ativo
    con.commit()
    assert '<p class="perm-resumo">2 usuários ativos ·' in _pagina(cli, _gid(contas_db, "Leitor"))
    assert '<p class="perm-resumo">1 usuários ativos ·' in _pagina(cli, _gid(contas_db, "Revisor"))
    assert '<p class="perm-resumo">0 usuários ativos ·' in _pagina(cli, _gid(contas_db, "Visitante"))


def test_busca_e_filtros_pela_url(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _pagina(cli, gid, q="triar")
    assert _itens(h)[1] == ["triar_artigos", "triar_texto_completo"] and [m for m, _ in _modulos(h)] == ["revisao"]
    assert 'name="q" value="triar"' in h
    h = _pagina(cli, gid, filtro="habilitadas")
    assert _itens(h)[1] == ["ver_painel", "ver_registros_revisao", "ver_nomes_revisores", "ver_custos"]   # o Leitor padrao, na ordem
    assert [m for m, _ in _modulos(h)] == ["consulta", "acompanhamento", "tecnico"]                       # da pagina (por modulo)
    assert _modulos(h)[1][1] == "Acompanhamento — 1 de 2"                    # contagem do modulo inteiro, nao do filtro
    assert '<option value="habilitadas" selected>Habilitadas</option>' in h
    h = _pagina(cli, gid, modulo="tecnico", filtro="desabilitadas")
    assert _itens(h)[1] == ["ver_chamadas", "enviar_coletas"] and '<option value="tecnico" selected>' in h
    h = _pagina(cli, gid, q="nada-assim")
    assert _itens(h)[1] == [] and _modulos(h) == []
    assert '<p class="vazio">Nenhuma permissão corresponde à busca e aos filtros.</p>' in h
    assert 'aria-label="Prévia do menu"' in h                               # a previa nao depende dos filtros


def test_valores_fora_da_lista_selecionam_todas(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="outro", modulo="Revisao")
    assert '<option value="" selected>Todas</option>' in h and '<option value="" selected>Todos</option>' in h
    assert _itens(h)[1] == ORDEM_DA_PAGINA


def test_parametro_repetido_vale_o_ultimo(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    assert _itens(cli.get(f"/admin/grupos/{gid}?q=triar&q=chamadas").text)[1] == ["ver_chamadas"]
    assert _itens(cli.get(f"/admin/grupos/{gid}?filtro=sensiveis&filtro=habilitadas").text)[1] == [
        "ver_painel", "ver_registros_revisao", "ver_nomes_revisores", "ver_custos"]
    assert _itens(cli.get(f"/admin/grupos/{gid}?modulo=revisao&modulo=tecnico").text)[1] == ["ver_chamadas", "enviar_coletas", "ver_custos"]


def test_tres_filtros_juntos_na_rota(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), q="ver", filtro="habilitadas", modulo="acompanhamento")
    assert _itens(h)[1] == ["ver_nomes_revisores"]


def test_formulario_de_filtro(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"))
    form = h[h.index('<form class="perm-filtros" method="get">'):]
    form = form[:form.index("</form>")]
    assert '<label for="perm-q">Buscar</label>' in form and '<input id="perm-q" type="search" name="q" value="">' in form
    assert '<label for="perm-filtro">Mostrar</label>' in form and '<select id="perm-filtro" name="filtro">' in form
    assert '<label for="perm-modulo">Módulo</label>' in form and '<select id="perm-modulo" name="modulo">' in form
    i_f, i_m = form.index('<select id="perm-filtro"'), form.index('<select id="perm-modulo"')
    sel_filtro, sel_modulo = form[i_f:form.index("</select>", i_f)], form[i_m:form.index("</select>", i_m)]
    opcao = r'<option value="([a-z]*)"(?: selected)?>([^<]+)</option>'
    assert re.findall(opcao, sel_filtro) == [("", "Todas"), ("habilitadas", "Habilitadas"), ("desabilitadas", "Desabilitadas"),
                                             ("sensiveis", "Sensíveis"), ("financeiras", "Financeiras"),
                                             ("administrativas", "Administrativas"), ("diferentes", "Diferentes da referência")]
    assert re.findall(opcao, sel_modulo) == [("", "Todos")] + list(A.MODULOS_PERMISSAO.items())
    assert "placeholder" not in form
    assert '<button class="botao" type="submit">Filtrar</button>' in form


@pytest.mark.parametrize("q", ['<script>alert(1)</script>', '"><b>x</b>', "a&b"])
def test_busca_e_escapada(adm, q):
    cli, _, contas_db, _ = adm
    from markupsafe import escape
    h = _pagina(cli, _gid(contas_db, "Leitor"), q=q)
    assert f'name="q" value="{escape(q)}"' in h and _itens(h)[1] == []         # escapado e usado na busca
    corpo = h[h.index("<main"):]
    assert q not in corpo or q == "a&b" and "a&amp;b" in corpo


def test_nome_do_grupo_e_escapado(adm):
    cli, _, contas_db, _ = adm
    r = cli.post("/admin/grupos/novo", data={"nome": 'A<b>&"c', "csrf": _csrf(cli, "/admin/grupos")}, follow_redirects=False)
    assert r.status_code == 303
    gid = sqlite3.connect(contas_db).execute("SELECT grupo_id FROM grupos WHERE nome=?", ('A<b>&"c',)).fetchone()[0]
    h = _pagina(cli, gid)
    assert "<h1>A&lt;b&gt;&amp;&#34;c</h1>" in h and 'A<b>&"c' not in h
    m = cli.get("/admin/grupos").text
    assert f'<th scope="col">A&lt;b&gt;&amp;&#34;c <a href="/admin/grupos/{gid}">Ver as permissões</a></th>' in m and 'A<b>&"c' not in m


@pytest.mark.parametrize("caminho,status,texto", [
    ("/admin/grupos/999", 404, "Não existe o grupo nº 999."),
    ("/admin/grupos/0999", 404, "Não existe o grupo nº 999."),             # o numero canonico, sem zeros a esquerda
    ("/admin/grupos/0", 404, "Não existe o grupo nº 0."),
    ("/admin/grupos/" + "0" * 5000 + "999", 404, "Não existe o grupo nº 999."),
    ("/admin/grupos/9223372036854775807", 404, "Não existe o grupo nº 9223372036854775807."),
    ("/admin/grupos/9223372036854775808", 404, "Algum número ou parâmetro do endereço não é válido."),
    ("/admin/grupos/x", 404, ""),                                           # so algarismos ASCII casam com a rota: 404 do roteador
    ("/admin/grupos/-1", 404, ""),
    ("/admin/grupos/%D9%A3", 404, ""),
])
def test_grupo_inexistente_ou_endereco_invalido(adm, caminho, status, texto):
    cli, _, _, _ = adm
    r = cli.get(caminho)
    assert r.status_code == status and texto in r.text


def test_zeros_a_esquerda_de_um_grupo_que_existe(adm):
    cli, _, contas_db, _ = adm
    assert "<h1>Administrador</h1>" in _pagina(cli, "0" * 5000 + str(_gid(contas_db, "Administrador")))


def test_usuarios_so_lidos_depois_de_achar_o_grupo(adm, monkeypatch):
    from adaptadores.contas_sqlite import ContasSQLite
    cli, _, contas_db, _ = adm
    lidos = []
    original = ContasSQLite.listar_usuarios
    monkeypatch.setattr(ContasSQLite, "listar_usuarios", lambda self: lidos.append(1) or original(self))
    cli.get("/admin/grupos/999")
    cli.get("/admin/grupos/x")
    assert lidos == []
    _pagina(cli, _gid(contas_db, "Leitor"))
    assert lidos == [1]
    monkeypatch.setattr(ContasSQLite, "listar_usuarios", lambda self: (_ for _ in ()).throw(A.ContasOcupadas("x")))
    assert cli.get(f"/admin/grupos/{_gid(contas_db, 'Leitor')}").status_code == 503


def test_contas_ocupadas_vence_o_grupo_inexistente(adm, monkeypatch):
    from adaptadores.contas_sqlite import ContasSQLite
    cli, _, _, _ = adm
    monkeypatch.setattr(ContasSQLite, "grupos", lambda self: (_ for _ in ()).throw(A.ContasOcupadas("x")))
    assert cli.get("/admin/grupos/999").status_code == 503


@pytest.mark.parametrize("grupo", ["Administrador", "Visitante", "Leitor", "Revisor"])
def test_previa_do_menu_pela_mesma_regra(adm, grupo):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, grupo)
    perms = next(g["permissoes"] for g in contas.grupos() if g["grupo_id"] == gid)
    h = _pagina(cli, gid)
    previa = h[h.index('<section class="perm-previa" aria-label="Prévia do menu">'):]
    previa = previa[:previa.index("</section>")]
    esperado = navegacao.grupos("/", admin=(grupo == "Administrador"), banco="real",
                                pode=lambda m, c: A.pode_acessar(grupo, perms, m, c))
    obtido = re.findall(r'<li class="previa-grupo"><span>([^<]+)</span><ul>(.*?)</ul></li>', previa, re.S)
    assert [n for n, _ in obtido] == [g["nome"] for g in esperado]
    for (_, itens), g in zip(obtido, esperado):
        assert re.findall(r"<li>([^<]+)</li>", itens) == [i["texto"] for i in g["itens"]]
    assert "<a " not in previa


def test_previa_usa_a_navegacao_do_painel(adm, monkeypatch):
    cli, _, contas_db, _ = adm
    chamadas = []

    def falso(*a, **k):
        chamadas.append((a, k))
        return [{"id": "x", "nome": "Grupo de teste", "aberto": False, "itens": [{"href": "/", "texto": "Item de teste", "atual": False}]}]
    monkeypatch.setattr(navegacao, "grupos", falso)
    h = _pagina(cli, _gid(contas_db, "Leitor"))
    da_previa = [k for a, k in chamadas if a == ("/",) and "pode" in k and k.get("admin") is False]
    assert len(da_previa) == 1 and da_previa[0]["banco"] == "real"
    assert da_previa[0]["pode"]("GET", "/execucoes") is False and da_previa[0]["pode"]("GET", "/estados") is True
    assert '<li class="previa-grupo"><span>Grupo de teste</span><ul><li>Item de teste</li></ul></li>' in h


def test_lista_de_grupos_liga_a_cada_pagina(adm):
    cli, contas, _, _ = adm
    cli.post("/admin/grupos/novo", data={"nome": "Bolsistas", "csrf": _csrf(cli, "/admin/grupos")})
    h = cli.get("/admin/grupos").text
    for g in contas.grupos():
        assert h.count(f'<a href="/admin/grupos/{g["grupo_id"]}">Ver as permissões</a>') == 1, g["nome"]
        assert f'<th scope="col">{g["nome"]} <a href="/admin/grupos/{g["grupo_id"]}">Ver as permissões</a></th>' in h
    assert '<th scope="col">Permissão</th>' in h and "Salvar permissões" not in h      # a matriz continua, so de leitura


def test_pagina_so_de_leitura(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    antes = sorted(sqlite3.connect(contas_db).execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall())
    h = _pagina(cli, gid, q="x", filtro="habilitadas")
    formularios = re.findall(r"<form\b[^>]*>", h)
    assert [f for f in formularios if 'action="/sair"' not in f] == ['<form class="perm-filtros" method="get">']
    assert sum('action="/sair"' in f for f in formularios) == 1 and 'type="checkbox"' not in h          # e o "Sair" do topo
    r = cli.post(f"/admin/grupos/{gid}", data={"csrf": _csrf(cli, "/admin/grupos")}, follow_redirects=False)
    assert r.status_code == 405
    assert sorted(sqlite3.connect(contas_db).execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall()) == antes


def test_pagina_nao_le_o_banco_da_pesquisa(adm, monkeypatch):
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    cli, _, contas_db, _ = adm
    for nome in [n for n in dir(LeituraPainelSQLite) if not n.startswith("__") and callable(getattr(LeituraPainelSQLite, n))]:
        monkeypatch.setattr(LeituraPainelSQLite, nome, lambda *a, _n=nome, **k: (_ for _ in ()).throw(AssertionError(_n)))
    assert cli.get(f"/admin/grupos/{_gid(contas_db, 'Leitor')}").status_code == 200


def test_so_o_administrador_abre(adm):
    cli, _, contas_db, _ = adm
    anonimo = TestClient(cli.app)
    r = anonimo.get(f"/admin/grupos/{_gid(contas_db, 'Leitor')}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar")


def test_estilo_da_pagina_vem_da_fonte_do_desenho_e_so_toca_a_pagina():
    """O painel.css e gerado (design/tools/gerar_painel_css.py): as regras desta pagina ficam numa fonte propria e so usam seletores
    da pagina, sem mudar componentes compartilhados."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    fonte = raiz / "design" / "src" / "painel" / "36_permissoes.css"
    assert fonte.exists()
    texto = re.sub(r"/\*.*?\*/", "", fonte.read_text(encoding="utf-8"), flags=re.S)
    seletores = [x.strip() for bloco in re.findall(r"([^{}]+)\{", texto) for x in bloco.split(",") if x.strip()]
    assert seletores
    fora = [x for x in seletores if not re.search(r"\.perm[-\w]*|\.modulo\b|\.previa-grupo|main:has\(\.perm-resumo\)", x)
            and not x.startswith("@")]
    assert fora == []


def test_nome_longo_quebra_nos_cartoes_de_renomear(adm):
    """Um nome de 40 caracteres sem espaco nao pode alargar a pagina de grupos no celular: nos cartoes de renomear o nome fica num
    span que quebra a palavra."""
    from pathlib import Path
    cli, _, contas_db, _ = adm
    nome = "W" * 40
    assert cli.post("/admin/grupos/novo", data={"nome": nome, "csrf": _csrf(cli, "/admin/grupos")}, follow_redirects=False).status_code == 303
    h = cli.get("/admin/grupos").text
    assert f'Renomear <span class="perm-nome">{nome}</span></h2>' in h
    assert f'Novo nome para <span class="perm-nome">{nome}</span></label>' in h
    fonte = (Path(__file__).resolve().parents[1] / "design" / "src" / "painel" / "36_permissoes.css").read_text(encoding="utf-8")
    regra = re.search(r"\.perm-nome\s*\{([^}]*)\}", fonte)
    assert regra and "overflow-wrap: anywhere" in regra.group(1)
