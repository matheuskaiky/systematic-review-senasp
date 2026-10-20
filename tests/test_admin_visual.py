"""Administracao no padrao visual do painel: grupo proprio no menu lateral (so para administradores), ladrilho no titulo pelo
item atual, formularios em cartao com largura de leitura e botoes do painel (desativar conta em tom de perigo)."""
import re
from pathlib import Path

import pytest

from painel import navegacao
from test_admin import adm, _criar  # noqa: F401
from test_autenticacao import _criar as _criar_conta, _entrar, painel  # noqa: F401
from test_painel import demo  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent
ITENS_ADMIN = [("/admin/usuarios", "Usuários"), ("/admin/grupos", "Permissões por grupo"),
               ("/admin/auditoria", "Registro de administração"), ("/estatisticas-usuarios", "Atividade dos revisores")]
TEMPLATES = ["admin_usuarios", "admin_usuario", "admin_grupos", "admin_auditoria", "estatisticas_usuarios"]


def _grupo_admin(html):
    nav = html[html.index('<nav class="menu"'):html.index("</nav>")]
    m = re.search(r'<details class="menu-grupo" data-grupo="administracao"([^>]*)>(.*?)</details>', nav, re.S)
    return m and (bool(re.search(r"\bopen\b", m.group(1))), re.findall(r'<a href="([^"]+)"([^>]*)>([^<]+)</a>', m.group(2)))


@pytest.mark.parametrize("caminho,admin,ids", [("/admin/usuarios", True, True), ("/admin/usuarios", False, False),
                                               ("/", True, True), ("/", False, False)])
def test_grupo_de_administracao_so_para_administrador(caminho, admin, ids):
    nomes = [g["id"] for g in navegacao.grupos(caminho, admin=admin)]
    assert nomes == ["revisao", "analises", "auditoria"] + (["administracao"] if ids else [])


@pytest.mark.parametrize("caminho,atual", [("/admin/usuarios", "/admin/usuarios"), ("/admin/usuarios/7", "/admin/usuarios"),
                                           ("/admin/grupos", "/admin/grupos"), ("/admin/auditoria", "/admin/auditoria"),
                                           ("/estatisticas-usuarios", "/estatisticas-usuarios"), ("/", None)])
def test_item_atual_do_grupo(caminho, atual):
    g = navegacao.grupos(caminho, admin=True)[3]
    assert [(i["href"], i["texto"]) for i in g["itens"]] == ITENS_ADMIN
    assert [i["href"] for i in g["itens"] if i["atual"]] == ([atual] if atual else [])
    assert g["aberto"] is (atual is not None)


def test_menu_do_administrador_tem_o_grupo_e_marca_a_pagina(adm):
    cli = adm[0]
    aberto, links = _grupo_admin(cli.get("/admin/grupos").text)
    assert aberto and [(h, t) for h, _, t in links] == ITENS_ADMIN
    assert [h for h, extra, _ in links if 'aria-current="page"' in extra] == ["/admin/grupos"]
    aberto, _ = _grupo_admin(cli.get("/").text)
    assert not aberto


def test_revisor_nao_ve_o_grupo(painel):
    cli = painel[0]
    _criar_conta(painel, "revisora", "Revisor")
    assert _entrar(cli, "revisora").status_code == 303
    assert _grupo_admin(cli.get("/").text) is None


def test_templates_sem_abas_antigas_e_com_botoes_do_painel():
    for nome in TEMPLATES:
        t = (RAIZ / "painel" / "templates" / f"{nome}.html").read_text(encoding="utf-8")
        assert "admin-abas" not in t and "form-entrar" not in t, nome
        assert '<button type="submit">' not in t, nome                        # todo botao com a classe do painel
    u = (RAIZ / "painel" / "templates" / "admin_usuario.html").read_text(encoding="utf-8")
    assert '<button class="botao perigo" type="submit">Desativar conta</button>' in u
    assert '<button class="botao secundario" type="submit">Reativar conta</button>' in u


@pytest.mark.parametrize("arquivo,titulos", [
    ("admin_usuarios", [("user", "Novo usuário")]),
    ("admin_usuario", [("identification-badge", "Dados do usuário"), ("lock", "Redefinir senha"), ("shield-warning", "Situação da conta")]),
    ("admin_grupos", [("users", "Novo grupo"), ("tag", "Renomear {{ g.nome }}")]),
])
def test_formularios_em_cartao_com_icone(arquivo, titulos):
    t = (RAIZ / "painel" / "templates" / f"{arquivo}.html").read_text(encoding="utf-8")
    for ic, titulo in titulos:
        assert f'<section class="cartao"><h2 data-ic="{ic}" data-tom="cobalto">{titulo}</h2>' in t, titulo
    assert t.count('<section class="cartao">') == t.count("</section>") == len(titulos)


def test_css_do_admin():
    css = (RAIZ / "painel" / "static" / "painel.css").read_text(encoding="utf-8")
    assert ".form-admin { display: grid; gap: .35rem; max-width: 32rem; margin: 0; }" in css
    assert ".botao.perigo { background-color: var(--superficie); background-image: none; color: var(--perigo); border-color: var(--perigo); box-shadow: none; }" in css
    for href in ("/admin/usuarios", "/admin/grupos", "/admin/auditoria", "/estatisticas-usuarios"):
        assert f".layout:has(.menu-lista a[href='{href}'][aria-current=\"page\"]) {{ --pg-ic:" in css, href   # ladrilho do titulo
    assert '.menu-grupo[data-grupo="administracao"] > summary {' in css
