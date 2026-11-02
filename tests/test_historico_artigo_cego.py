"""Historico de decisoes do artigo sem a revisao independente, como ja e o historico dos achados: o painel nunca a mostra.

A revisao independente entra por planilha (`triagem-importar --independente`) so para o kappa e as discordancias; o painel nunca a
mostra a quem decide. O consenso continua por planilha. Os registros independentes ficam no banco, e o kappa nao muda."""
import sqlite3

import pandas as pd
import pytest

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from test_apresentacao_publica import _nunca_abre_o_data_real  # noqa: F401
from test_painel import demo  # noqa: F401
from test_painel_literatura import _pendente, ctx  # noqa: F401


def _linha(artigo_id, revisor, decisao):
    return {"artigo_id": artigo_id, "decisao": decisao, "motivo": None, "confirmado_em_base": None, "link_confirmado": None,
            "revisor": revisor}


def _importar(copia, linhas, so_historico):
    repo = RepositorioSQLite(copia)
    try:
        repo.importar_triagem(pd.DataFrame(linhas), so_historico=so_historico)
    finally:
        repo.fechar()


def _dois_artigos(copia):
    ids = [r[0] for r in sqlite3.connect(copia).execute(
        "SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id WHERE t.decisao IS NULL "
        "ORDER BY a.artigo_id LIMIT 2")]
    assert len(ids) == 2
    return ids


def _independentes(copia):
    return sqlite3.connect(copia).execute("SELECT COUNT(*) FROM triagem_revisoes WHERE independente=1").fetchone()[0]


def test_leitura_do_artigo_nao_traz_a_revisao_independente(ctx):  # noqa: F811
    _, copia, _ = ctx
    a, b = _dois_artigos(copia)
    _importar(copia, [_linha(a, "Ana Indep", "incluir"), _linha(b, "Ana Indep", "excluir")], so_historico=True)
    _importar(copia, [_linha(a, "Bia Indep", "excluir"), _linha(b, "Bia Indep", "excluir")], so_historico=True)
    leitura = LeituraPainelSQLite(copia)
    assert leitura.artigo(a)["historico"] == [] and leitura.artigo(b)["historico"] == []
    _importar(copia, [_linha(a, "Carla Consenso", "incluir")], so_historico=False)      # a planilha do consenso
    _importar(copia, [_linha(a, "Dora Consenso", "excluir")], so_historico=False)       # uma segunda decisao final, depois
    h = LeituraPainelSQLite(copia).artigo(a)["historico"]
    assert [x["revisor"] for x in h] == ["Dora Consenso", "Carla Consenso"]                # ordem: a mais recente primeiro
    assert [set(x) for x in h] == [CHAVES, CHAVES]                                          # as mesmas chaves de hoje


CHAVES = {"revisor", "decisao", "motivo", "decisao_texto_completo", "motivo_texto_completo", "importado_em", "independente"}


def test_registros_independentes_e_kappa_ficam_no_banco(ctx):  # noqa: F811
    _, copia, _ = ctx
    a, b = _dois_artigos(copia)
    _importar(copia, [_linha(a, "Ana Indep", "incluir"), _linha(b, "Ana Indep", "excluir")], so_historico=True)
    _importar(copia, [_linha(a, "Bia Indep", "excluir"), _linha(b, "Bia Indep", "excluir")], so_historico=True)
    LeituraPainelSQLite(copia).artigo(a)
    assert _independentes(copia) == 4
    k = [dict(zip(("a", "b", "n", "disc"), r)) for r in sqlite3.connect(copia).execute(
        "SELECT revisor_a, revisor_b, n_artigos_em_comum, discordancias FROM v_concordancia_revisores")]
    assert k == [{"a": "Ana Indep", "b": "Bia Indep", "n": 2, "disc": 1}]


def test_pagina_do_artigo_nao_mostra_a_revisao_independente(ctx):  # noqa: F811
    cli, copia, _ = ctx
    a, _b = _dois_artigos(copia)
    _importar(copia, [_linha(a, "Ana Indep", "incluir")], so_historico=True)
    _importar(copia, [_linha(a, "Bia Indep", "excluir")], so_historico=True)
    h = cli.get(f"/literatura/artigos/{a}").text
    assert "revisão independente" not in h and "Ana Indep" not in h and "Bia Indep" not in h
    assert "Histórico de decisões" not in h                     # sem decisao que nao seja independente, nao ha historico
    _importar(copia, [_linha(a, "Carla Consenso", "incluir")], so_historico=False)
    h = cli.get(f"/literatura/artigos/{a}").text
    assert "Histórico de decisões" in h and "Carla Consenso" in h
    assert "revisão independente" not in h and "Ana Indep" not in h and "Bia Indep" not in h
