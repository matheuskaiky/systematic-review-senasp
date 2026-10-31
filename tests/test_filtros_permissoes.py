"""Filtros que faltavam na pagina de leitura de um grupo: Financeiras, Administrativas e Diferentes da referencia. Os filtros
so escolhem o que aparece na lista; a referencia vem sempre do perfil escolhido na tela (?perfil=), nunca do nome do grupo, e
nada aqui grava, marca ou monta alteracoes."""
import re
import sqlite3

import pytest

from dominio import autenticacao as A
from test_admin import _csrf, _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401

TODAS = list(A.PERMISSOES)
ORDEM_DA_PAGINA = [p for m in A.MODULOS_PERMISSAO for p in TODAS if A.CATALOGO_PERMISSOES[p]["modulo"] == m]
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}     # o Leitor padrao do banco de teste
ESCOLHA = "Escolha um dos perfis de referência da lista."
SO_ADMIN_TEXTO = ("As capacidades de administração são exclusivas do grupo Administrador e não podem ser dadas a outro "
                  "grupo.")
GENERICO = "Nenhuma permissão corresponde à busca e aos filtros."


def _nota(rotulo):
    return (f"<p>Comparação com a referência de {rotulo}. Habilitada: o grupo tem e a referência não. Não habilitada: a "
            "referência tem e o grupo não. Esta página só mostra; nada é alterado aqui.</p>")


def _difs(grupo, atuais, perfil):
    r = A.comparar_com_referencia(grupo, atuais, perfil)
    return {i["permissao"] for i in r["conceder"] + r["retirar"]}


# ---------------- dominio ----------------

@pytest.mark.parametrize("grupo,atuais", [("Leitor", LEITOR), ("Administrador", set()), ("Visitante", {"ver_painel"}),
                                          ("Vazio", set()), ("Tudo", set(TODAS))])
def test_financeiras_independe_do_estado(grupo, atuais):
    assert A.filtrar_permissoes(grupo, atuais, "", "financeiras", "") == ["ver_custos"]


@pytest.mark.parametrize("grupo,atuais", [("Leitor", LEITOR), ("Administrador", set(TODAS)), ("Visitante", set()),
                                          ("Tudo", set(TODAS))])
@pytest.mark.parametrize("busca,modulo", [("", ""), ("ver", ""), ("", "tecnico")])
def test_administrativas_nunca_lista_nada(grupo, atuais, busca, modulo):
    assert A.filtrar_permissoes(grupo, atuais, busca, "administrativas", modulo) == []


def test_financeiras_segue_o_catalogo(monkeypatch):
    catalogo = {k: dict(v) for k, v in A.CATALOGO_PERMISSOES.items()}
    catalogo["ver_chamadas"]["sensibilidade"] = "financeira"
    monkeypatch.setattr(A, "CATALOGO_PERMISSOES", catalogo)
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "financeiras", "") == ["ver_chamadas", "ver_custos"]


@pytest.mark.parametrize("perfil", list(A.PERFIS_REFERENCIA))
@pytest.mark.parametrize("grupo,atuais", [("Leitor", LEITOR), ("Vazio", set()), ("Tudo", set(TODAS)),
                                          ("Professor de Direito", set())])
def test_diferentes_lista_as_diferencas_na_ordem_do_catalogo(grupo, atuais, perfil):
    esperado = [p for p in TODAS if p in _difs(grupo, atuais, perfil)]
    assert A.filtrar_permissoes(grupo, atuais, "", "diferentes", "", perfil=perfil) == esperado


def test_diferentes_exemplo_literal():
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "diferentes", "", perfil="estudante_direito") == [
        "ver_nomes_revisores", "verificar_achados", "triar_artigos", "triar_texto_completo", "ver_custos"]


def test_diferentes_combina_com_busca_e_modulo():
    assert A.filtrar_permissoes("Leitor", LEITOR, "triar", "diferentes", "", perfil="estudante_direito") == [
        "triar_artigos", "triar_texto_completo"]
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "diferentes", "tecnico", perfil="estudante_direito") == ["ver_custos"]
    assert A.filtrar_permissoes("Leitor", LEITOR, "x" * 101, "diferentes", "", perfil="estudante_direito") == []


@pytest.mark.parametrize("perfil", ["", " publico", "Publico", "público", "x", "gerir_validacao"])
def test_diferentes_sem_perfil_valido_nao_lista_nada(perfil):
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "diferentes", "", perfil=perfil) == []


def test_diferentes_sem_o_argumento_perfil_nao_lista_nada():
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "diferentes", "") == []


def test_diferentes_no_administrador_e_no_visitante():
    assert A.filtrar_permissoes("Administrador", set(), "", "diferentes", "", perfil="publico") == []
    assert A.filtrar_permissoes("Visitante", {"ver_painel"}, "", "diferentes", "", perfil="professor_direito") == []
    assert A.filtrar_permissoes("Visitante", set(), "", "diferentes", "", perfil="publico") == ["ver_painel"]


def test_diferentes_segue_a_comparacao(monkeypatch):
    def falsa(grupo, atuais, perfil):
        return {"perfil": perfil, "rotulo": "R", "erros": [], "retirar": [],
                "conceder": [{"permissao": "enviar_coletas", "descricao": "d", "sensivel": True, "marcada": False}]}
    monkeypatch.setattr(A, "comparar_com_referencia", falsa)
    assert A.filtrar_permissoes("Leitor", LEITOR, "", "diferentes", "", perfil="publico") == ["enviar_coletas"]


@pytest.mark.parametrize("filtro", ["", "habilitadas", "desabilitadas", "sensiveis", "financeiras", "administrativas",
                                    "outro"])
def test_perfil_nao_muda_os_outros_filtros(filtro):
    assert A.filtrar_permissoes("Leitor", LEITOR, "", filtro, "", perfil="publico") == \
        A.filtrar_permissoes("Leitor", LEITOR, "", filtro, "")


@pytest.mark.parametrize("filtro", ["Financeiras", " financeiras", "Administrativas", "Diferentes", "diferentes "])
def test_filtros_novos_so_pelo_valor_exato(filtro):
    assert A.filtrar_permissoes("Leitor", LEITOR, "", filtro, "", perfil="publico") == TODAS


# ---------------- rota ----------------

def _pagina(cli, gid, **params):
    r = cli.get(f"/admin/grupos/{gid}", params=params)
    assert r.status_code == 200
    return r.text


def _itens(h):
    return re.findall(r'<li class="perm" data-chave="([a-z_]+)">', h)


def _form(h):
    f = h[h.index('<form class="perm-filtros" method="get">'):]
    return f[:f.index("</form>")]


OPCAO = r'<option value="([a-z_]*)"(?: selected)?>([^<]+)</option>'


def _opcoes(form, sid):
    assert f'<select id="{sid}"' in form
    i = form.index(f'<select id="{sid}"')
    return re.findall(OPCAO, form[i:form.index("</select>", i)])


def _selecionada(form, sid):
    assert f'<select id="{sid}"' in form
    i = form.index(f'<select id="{sid}"')
    return re.findall(r'<option value="([a-z_]*)" selected>', form[i:form.index("</select>", i)])


FILTROS_BASE = [("", "Todas"), ("habilitadas", "Habilitadas"), ("desabilitadas", "Desabilitadas"),
                ("sensiveis", "Sensíveis"), ("financeiras", "Financeiras"), ("administrativas", "Administrativas")]
PERFIS = [("", "Nenhuma")] + [(p, A.ROTULOS_PERFIL_REFERENCIA[p]) for p in A.PERFIS_REFERENCIA]


def test_formulario_de_um_grupo_comum(adm):
    cli, _, contas_db, _ = adm
    form = _form(_pagina(cli, _gid(contas_db, "Leitor")))
    assert _opcoes(form, "perm-filtro") == FILTROS_BASE + [("diferentes", "Diferentes da referência")]
    assert '<label for="perm-perfil">Referência</label>' in form and '<select id="perm-perfil" name="perfil">' in form
    assert _opcoes(form, "perm-perfil") == PERFIS
    assert _selecionada(form, "perm-perfil") == [""]
    ordem = [form.index(x) for x in ('id="perm-q"', 'id="perm-filtro"', 'id="perm-modulo"', 'id="perm-perfil"',
                                     '<button class="botao" type="submit">Filtrar</button>')]
    assert ordem == sorted(ordem)


def test_formulario_do_visitante_so_oferece_o_publico(adm):
    cli, _, contas_db, _ = adm
    form = _form(_pagina(cli, _gid(contas_db, "Visitante")))
    assert _opcoes(form, "perm-filtro") == FILTROS_BASE + [("diferentes", "Diferentes da referência")]
    assert _opcoes(form, "perm-perfil") == [("", "Nenhuma"), ("publico", "Público")]


def test_formulario_do_administrador_sem_referencia(adm):
    cli, _, contas_db, _ = adm
    form = _form(_pagina(cli, _gid(contas_db, "Administrador")))
    assert _opcoes(form, "perm-filtro") == FILTROS_BASE
    assert 'perm-perfil' not in form and 'name="perfil"' not in form


def test_diferentes_da_referencia_na_pagina(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="diferentes", perfil="estudante_direito")
    esperado = [p for p in ORDEM_DA_PAGINA if p in _difs("Leitor", LEITOR, "estudante_direito")]
    assert _itens(h) == esperado
    form = _form(h)
    assert _selecionada(form, "perm-filtro") == ["diferentes"] and _selecionada(form, "perm-perfil") == ["estudante_direito"]
    assert h.count(_nota("Estudante de Direito")) == 1
    assert 'class="aviso' not in h.split("<main", 1)[1].split('<form class="perm-filtros"', 1)[1]


def test_diferentes_exemplo_da_pagina(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="diferentes", perfil="estudante_direito")
    assert _itens(h) == ["verificar_achados", "triar_artigos", "triar_texto_completo", "ver_nomes_revisores", "ver_custos"]


def test_a_nota_vem_depois_do_formulario_e_antes_da_lista(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="diferentes", perfil="professor_computacao")
    assert _nota("Professor de Computação") in h
    i_form, i_nota = h.index("</form>", h.index('<form class="perm-filtros"')), h.index(_nota("Professor de Computação"))
    assert i_form < i_nota < h.index('<details open class="modulo"')


@pytest.mark.parametrize("params", [{"filtro": "diferentes"}, {"filtro": "diferentes", "perfil": ""},
                                    {"filtro": "diferentes", "perfil": "x"}, {"filtro": "diferentes", "perfil": " publico"},
                                    {"filtro": "diferentes", "perfil": "<b>x</b>"}])
def test_diferentes_sem_referencia_pede_a_escolha(adm, params):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), **params)
    assert _itens(h) == []
    assert h.count(f'<p class="aviso" role="status">{ESCOLHA}</p>') == 1
    assert f'<p class="vazio">{GENERICO}</p>' in h
    assert _selecionada(_form(h), "perm-perfil") == [""]
    assert "<b>x</b>" not in h and "Comparação com a referência" not in h


def test_visitante_com_perfil_que_nao_e_o_publico(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Visitante"), filtro="diferentes", perfil="professor_direito")
    assert _itens(h) == [] and h.count(f'<p class="aviso" role="status">{ESCOLHA}</p>') == 1
    assert _selecionada(_form(h), "perm-perfil") == [""]


def test_visitante_com_o_publico(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Visitante"), filtro="diferentes", perfil="publico")
    assert _itens(h) == [] and f'<p class="vazio">{GENERICO}</p>' in h      # o Visitante padrao ja tem so ver_painel
    assert h.count(_nota("Público")) == 1 and 'class="aviso"' not in h


def test_administrador_ignora_diferentes(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Administrador"), filtro="diferentes", perfil="publico")
    assert _itens(h) == ORDEM_DA_PAGINA
    assert _selecionada(_form(h), "perm-filtro") == [""]
    assert ESCOLHA not in h and "Comparação com a referência" not in h


def test_financeiras_na_pagina(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="financeiras")
    assert _itens(h) == ["ver_custos"] and _selecionada(_form(h), "perm-filtro") == ["financeiras"]


@pytest.mark.parametrize("grupo", ["Leitor", "Administrador", "Visitante"])
def test_administrativas_explica_que_nao_sao_atribuiveis(adm, grupo):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, grupo), filtro="administrativas")
    assert _itens(h) == []
    assert h.count(f'<p class="vazio">{SO_ADMIN_TEXTO}</p>') == 1 and GENERICO not in h


def test_perfil_sem_o_filtro_diferentes_so_fica_selecionado(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="habilitadas", perfil="publico")
    assert _itens(h) == ["ver_painel", "ver_registros_revisao", "ver_nomes_revisores", "ver_custos"]
    assert _selecionada(_form(h), "perm-perfil") == ["publico"]
    assert "Comparação com a referência" not in h and ESCOLHA not in h


def test_perfil_repetido_vale_o_ultimo(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}?filtro=diferentes&perfil=publico&perfil=estudante_direito").text
    assert _selecionada(_form(h), "perm-perfil") == ["estudante_direito"] and _nota("Estudante de Direito") in h


def test_nome_do_grupo_nunca_escolhe_a_referencia(adm):
    cli, _, contas_db, _ = adm
    assert cli.post("/admin/grupos/novo", data={"nome": "Professor de Direito", "csrf": _csrf(cli, "/admin/grupos")},
                    follow_redirects=False).status_code == 303
    gid = _gid(contas_db, "Professor de Direito")
    h = _pagina(cli, gid)
    assert _selecionada(_form(h), "perm-perfil") == [""] and "Comparação com a referência" not in h
    h = _pagina(cli, gid, filtro="diferentes")
    assert _itens(h) == [] and f'<p class="aviso" role="status">{ESCOLHA}</p>' in h


@pytest.mark.parametrize("params", [{"filtro": "diferentes", "perfil": "professor_computacao"},
                                    {"filtro": "financeiras"}, {"filtro": "administrativas"}])
def test_filtros_so_de_leitura(adm, params):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    antes = sorted(sqlite3.connect(contas_db).execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall())
    aud = sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0]
    h = _pagina(cli, gid, **params)
    formularios = [f for f in re.findall(r"<form\b[^>]*>", h) if 'action="/sair"' not in f]
    assert formularios == ['<form class="perm-filtros" method="get">'] and 'type="checkbox"' not in h
    assert f'<a class="botao" href="/admin/grupos/{gid}/editar">Editar permissões</a>' in h
    assert sorted(sqlite3.connect(contas_db).execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall()) == antes
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0] == aud


def test_edicao_continua_com_o_catalogo_inteiro(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}/editar", params={"filtro": "diferentes", "perfil": "publico", "q": "triar"}).text
    marcaveis = re.findall(r'<input type="checkbox" id="p-([a-z_]+)" name="marcada" value="\1"( checked)?>', h)
    assert [c for c, _ in marcaveis] and sorted(c for c, _ in marcaveis) == sorted(TODAS)
    assert {c for c, v in marcaveis if v} == LEITOR


def test_previa_do_menu_nao_depende_dos_filtros(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")

    def previa(h):
        assert 'aria-label="Prévia do menu"' in h
        return h[h.index('aria-label="Prévia do menu"'):h.index("</section>", h.index('aria-label="Prévia do menu"'))]
    base = previa(_pagina(cli, gid))
    for params in ({"filtro": "diferentes", "perfil": "publico"}, {"filtro": "administrativas"}, {"filtro": "financeiras"}):
        assert previa(_pagina(cli, gid, **params)) == base


def test_pagina_segue_a_comparacao_do_dominio(adm, monkeypatch):
    """A rota nunca calcula diferencas nem o texto do aviso: lista, rotulo da nota e aviso vem de comparar_com_referencia."""
    cli, _, contas_db, _ = adm

    def falsa(grupo, atuais, perfil):
        if perfil == "publico":
            return {"perfil": perfil, "rotulo": "Rótulo de teste", "erros": [], "retirar": [],
                    "conceder": [{"permissao": "enviar_coletas", "descricao": "d", "sensivel": True, "marcada": False}]}
        return {"perfil": None, "rotulo": None, "conceder": [], "retirar": [], "erros": ["Aviso de teste."]}
    monkeypatch.setattr(A, "comparar_com_referencia", falsa)
    gid = _gid(contas_db, "Leitor")
    h = _pagina(cli, gid, filtro="diferentes", perfil="publico")
    assert _itens(h) == ["enviar_coletas"] and _nota("Rótulo de teste") in h
    h = _pagina(cli, gid, filtro="diferentes")
    assert '<p class="aviso" role="status">Aviso de teste.</p>' in h and ESCOLHA not in h


def test_aviso_depois_do_formulario_e_antes_do_vazio(adm):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), filtro="diferentes")
    aviso = f'<p class="aviso" role="status">{ESCOLHA}</p>'
    assert aviso in h
    i_form = h.index("</form>", h.index('<form class="perm-filtros"'))
    assert i_form < h.index(aviso) < h.index(f'<p class="vazio">{GENERICO}</p>')


@pytest.mark.parametrize("params", [{"filtro": "diferentes", "perfil": "zzq9"}, {"filtro": "zzq9"},
                                    {"filtro": "diferentes", "perfil": "<b>zzq9</b>"}])
def test_valores_invalidos_nunca_sao_ecoados(adm, params):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, "Leitor"), **params)
    assert "zzq9" not in h
