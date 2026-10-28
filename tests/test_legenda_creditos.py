"""Legenda de /analises: os creditos de consulta (paginas do Scholar, unidade do metodo) ficam separados dos creditos do
provedor (diferenca de saldo da conta, informacao de cobranca, so para quem ve custos). Nenhum calculo muda."""
import dataclasses
from pathlib import Path

from fastapi.testclient import TestClient

from test_custos_nas_paginas import clis  # noqa: F401
from test_autenticacao import painel  # noqa: F401
from test_validacao_vies import banco  # noqa: F401
from test_painel import demo  # noqa: F401

CONSULTA = ("<dt>Créditos de consulta</dt><dd>Nos blocos dos termos de busca: páginas de resultados consultadas no Google "
            "Scholar, 1 crédito por chamada bem-sucedida. É a unidade de esforço da busca (por exemplo, em elegíveis por "
            "crédito), não um saldo nem um valor em dinheiro.</dd>")
PROVEDOR = ("<dt>Créditos do provedor</dt><dd>Na coluna Créditos das tabelas de ferramentas: consumo da conta do provedor "
            "de busca, o saldo no início menos o do fim de cada execução que registrou os dois. É informação de cobrança; "
            "não são dólares.</dd>")
ANTIGO = "Unidade de cobrança do provedor da busca no Scholar"
MODELO = Path(__file__).resolve().parents[1] / "painel" / "templates" / "_legenda_analises.html"


def _legenda(html):
    i = html.index('<section class="an-bloco" id="legenda"')
    return html[i:html.index("</section>", i)]


def test_modelo_sem_a_definicao_antiga():
    texto = MODELO.read_text(encoding="utf-8")
    assert ANTIGO not in texto and "<dt>Créditos</dt>" not in texto
    assert texto.count("<dt>Créditos do provedor</dt>") == 2 and texto.count("<dt>Créditos de consulta</dt>") == 1


def test_banco_real_sem_ver_custos_so_creditos_de_consulta(clis):  # noqa: F811
    for grupo in ("Visitante", "Consulta", "TecnicoSemCustos"):
        leg = _legenda(clis[grupo].get("/analises?secao=termos").text)
        assert CONSULTA in leg, grupo
        assert "Créditos do provedor" not in leg and ANTIGO not in leg, grupo


def test_banco_real_com_ver_custos_os_dois_na_ordem(clis):  # noqa: F811
    for grupo in ("Administrador", "TecnicoComCustos"):
        leg = _legenda(clis[grupo].get("/analises?secao=termos").text)
        assert CONSULTA in leg and PROVEDOR in leg, grupo
        assert leg.index(CONSULTA) < leg.index(PROVEDOR) and ANTIGO not in leg, grupo


def test_legenda_igual_em_todas_as_abas(clis):  # noqa: F811
    from painel.rotas_extras.analises import ABAS
    for chave, _ in ABAS:
        com = _legenda(clis["TecnicoComCustos"].get(f"/analises?secao={chave}").text)
        sem = _legenda(clis["Visitante"].get(f"/analises?secao={chave}").text)
        assert PROVEDOR in com and CONSULTA in com, chave
        assert PROVEDOR not in sem and CONSULTA in sem, chave


def test_banco_vies_so_creditos_do_provedor_e_so_com_ver_custos(banco, tmp_path):  # noqa: F811
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.contas_sqlite import ContasSQLite
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from painel.app import criar_app
    from test_validacao_vies import _cli as _cli_sem_login, _contexto
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    app = criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx,
                    contas=ContasSQLite(tmp_path / "contas_vies.db"))
    visitante = _legenda(TestClient(app).get("/analises?secao=ferramentas").text)
    assert "Créditos do provedor" not in visitante and "Créditos de consulta" not in visitante and ANTIGO not in visitante
    todas = _legenda(_cli_sem_login(banco, tmp_path).get("/analises?secao=ferramentas").text)     # sem login: todas as permissoes
    assert PROVEDOR in todas and "Créditos de consulta" not in todas and ANTIGO not in todas
