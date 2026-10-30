"""Padronizacao editorial do lote 1 (menu, tela de entrada e administracao): textos novos exatos, rotulos das acoes do
registro de administracao, e nada alem do texto muda (rotas, ids, valores gravados)."""
import re

import pytest

from dominio import autenticacao as A
from painel import navegacao, rotulos
from test_admin import _criar, _historico, adm  # noqa: F401
from test_autenticacao import painel  # noqa: F401
from test_painel import cliente_demo, demo  # noqa: F401

ROTULOS_ACOES = {
    "criar_usuario": "Criação de usuário",
    "editar_usuario": "Edição de usuário",
    "redefinir_senha": "Redefinição de senha",
    "desativar_usuario": "Desativação",
    "reativar_usuario": "Reativação",
    "salvar_permissoes": "Permissões salvas",
    "criar_grupo": "Criação de grupo",
    "renomear_grupo": "Renomeação de grupo",
    "gerar_token": "Geração de token de envio",
    "revogar_token": "Revogação de token de envio",
    "alterar_divulgacao": "Alteração da divulgação pública",
}


# ---------------- registro de administracao (T064) ----------------
def test_rotulo_para_cada_acao_gravada():
    assert rotulos.ACOES_AUDITORIA == ROTULOS_ACOES
    assert set(rotulos.ACOES_AUDITORIA) == set(A.ACOES_AUDITORIA)            # nenhuma acao sem rotulo, nenhuma inventada


def test_registro_mostra_o_rotulo_e_guarda_o_valor(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    _criar(cli, contas_db, login="ana", nome="Ana", grupo="Leitor")
    h = cli.get("/admin/auditoria").text
    assert "<td>Criação de usuário</td>" in h and "<td>criar_usuario</td>" not in h
    assert [l["acao"] for l in contas.auditoria()][0] == "criar_usuario"      # o valor gravado nao muda


def test_acao_desconhecida_aparece_como_esta(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    import sqlite3
    c = sqlite3.connect(contas_db)
    c.execute("INSERT INTO auditoria_admin (quando, admin_login, acao, alvo, detalhe) VALUES "
              "('2026-10-29T09:00:00+00:00', 'chefe', 'acao_antiga', NULL, NULL)")
    c.commit()
    assert "<td>acao_antiga</td>" in cli.get("/admin/auditoria").text


def test_registro_usa_a_tabela_de_rotulos(adm, monkeypatch):  # noqa: F811
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db, login="ana", nome="Ana", grupo="Leitor")
    monkeypatch.setattr(rotulos, "ACOES_AUDITORIA", {"criar_usuario": "Rótulo de teste"})
    assert "<td>Rótulo de teste</td>" in cli.get("/admin/auditoria").text


# ---------------- topo da pagina (T003) ----------------
def test_link_do_topo_com_o_nome_da_tela(adm):  # noqa: F811
    cli, _, _, _ = adm
    h = cli.get("/").text
    assert '<a class="conta-estatisticas" href="/estatisticas-usuarios">Atividade dos revisores</a>' in h


# ---------------- atividade dos revisores (T109) ----------------
def test_coluna_de_hoje_diz_o_fuso(adm):  # noqa: F811
    cli, _, _, copia = adm
    _historico(copia)
    h = cli.get("/estatisticas-usuarios").text
    assert '<th scope="col">Hoje (horário UTC)</th>' in h and "Hoje (UTC)" not in h


# ---------------- edicao de usuario (T121) ----------------
def test_aviso_sobre_troca_de_nome(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    _criar(cli, contas_db, login="ana", nome="Ana", grupo="Leitor")
    uid = next(u["usuario_id"] for u in contas.listar_usuarios() if u["login"] == "ana")
    h = cli.get(f"/admin/usuarios/{uid}").text
    assert ("<p><small>Alterar o nome não muda as decisões já registradas, que guardam o nome usado na época. Essas decisões "
            "só podem ser desfeitas por um administrador ou depois que o nome antigo for restaurado.</small></p>") in h
    assert "Mudar o nome não altera" not in h


# ---------------- tela de entrada (T123-T124; a T122 fica para decisao do pesquisador) ----------------
ENTRADA_NOVA = [
    '<p class="entrada-texto">O levantamento reúne evidências públicas sobre o uso, a contratação e o estudo de inteligência '
    'artificial na segurança pública brasileira, além da literatura sobre o tema.</p>',
    '<div><strong>Revisão de achados</strong><span>Confirme ou descarte cada achado a partir do trecho da página.</span></div>',
]
ENTRADA_ANTIGA = ["O levantamento reúne onde",
                  "Entre para revisar os achados e triar os artigos da literatura.", "a partir do trecho da notícia."]


def test_tela_de_entrada_com_os_textos_novos(painel):  # noqa: F811
    cli, _, _, _ = painel
    h = cli.get("/entrar").text
    for t in ENTRADA_NOVA:
        assert t in h, t
    for t in ENTRADA_ANTIGA:
        assert t not in h, t


# ---------------- menu (P002) ----------------
def test_grupo_do_menu_com_o_nome_novo():
    for banco in ("real", "vies"):
        g = navegacao.grupos("/", banco=banco)
        assert [x["nome"] for x in g if x["id"] == "revisao"] == ["Levantamento e revisão"]
        assert all(x["nome"] != "Revisão sistemática" for x in g)


def test_menu_na_pagina(cliente_demo):  # noqa: F811
    h = cliente_demo[0].get("/").text
    assert re.search(r'<details class="menu-grupo" data-grupo="revisao" open>\s*<summary>Levantamento e revisão</summary>', h)
