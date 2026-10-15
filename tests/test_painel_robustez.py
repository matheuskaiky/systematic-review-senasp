"""Revisao externa do painel: desfazer que apagaria trabalho alheio, Host/Origin, parametros invalidos, revogar e
decisoes concorrentes."""
import re
import shutil
import sqlite3

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from config import vocabulario as V
from test_painel import _app, _csrf, demo, _estado  # noqa: F401  (fixture `demo` do modulo de testes do painel)

PERMITIDOS = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)


@pytest.fixture
def ctx(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, c = _app(copia, raw, tmp_path)
    cli = TestClient(app)
    i = sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado=0 ORDER BY achado_id LIMIT 1").fetchone()[0]
    return cli, copia, i


def _form(cli, i, **extra):
    pag = cli.get(f"/achados/{i}").text
    return {"csrf": _csrf(pag), "versao": re.search(r'name="versao" value="([^"]*)"', pag).group(1), **extra}


def _planilha(copia, i, status, por):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    r = RepositorioSQLite(copia)
    r.importar_verificacao_achados(pd.DataFrame([(i, 1, status, por, "da planilha")], columns=["achado_id", "verificado", "status_final", "verificado_por", "observacao"]), PERMITIDOS)
    r.fechar()


# ---------- 1. desfazer nao pode apagar uma verificacao feita depois ----------
def test_desfazer_recusa_quando_outra_pessoa_verificou_depois_pela_planilha(ctx):
    cli, copia, i = ctx
    assert cli.post(f"/achados/{i}/verificar", data={**_form(cli, i), "status_final": "em_uso", "revisor": "Ana", "observacao": ""}, follow_redirects=False).status_code == 303
    _planilha(copia, i, "piloto", "Bia")
    pag = cli.get(f"/achados/{i}").text
    assert "/desfazer" not in pag.split('id="form-decisao"')[1]          # o botao nem aparece: nao daria para desfazer
    r = cli.post(f"/achados/{i}/desfazer", data={"csrf": _csrf(pag)})
    assert r.status_code == 409 and "alterado depois" in r.text
    assert _estado(copia, i) == (1, "piloto", "Bia")                      # a verificacao da Bia segue de pe
    assert sqlite3.connect(copia).execute("SELECT COUNT(*) FROM achados_revisoes WHERE achado_id=? AND desfeita=1", (i,)).fetchone()[0] == 0


def test_desfazer_continua_valendo_quando_nada_mudou(ctx):
    cli, copia, i = ctx
    cli.post(f"/achados/{i}/verificar", data={**_form(cli, i), "status_final": "em_uso", "revisor": "Ana", "observacao": ""})
    pag = cli.get(f"/achados/{i}").text
    assert "/desfazer" in pag
    assert cli.post(f"/achados/{i}/desfazer", data={"csrf": _csrf(pag)}, follow_redirects=False).status_code == 303
    assert _estado(copia, i)[0] == 0


def test_desfazer_de_revogacao_so_vale_se_nada_mudou(ctx):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    cli, copia, i = ctx
    r = RepositorioSQLite(copia)
    r.verificar_achado(i, "em_uso", "Ana", None, PERMITIDOS)
    r.desverificar_achado(i, "Ana", "engano")
    r.importar_verificacao_achados(pd.DataFrame([(i, 1, "piloto", "Bia", None)], columns=["achado_id", "verificado", "status_final", "verificado_por", "observacao"]), PERMITIDOS)
    with pytest.raises(SystemExit, match="alterado depois"):
        r.desfazer_ultima_decisao(i)
    assert r.conn.execute("SELECT status_final FROM achados WHERE achado_id=?", (i,)).fetchone()[0] == "piloto"


# ---------- 2. Host e Origin ----------
def test_host_estranho_e_recusado_e_nao_expoe_o_token(ctx):
    cli, _, _ = ctx
    for host in ("evil.example", "127.0.0.1.evil.example", "localhost.evil.example:8000"):
        r = cli.get("/", headers={"Host": host})
        assert r.status_code == 400 and "csrf" not in r.text.lower()
    assert cli.get("/", headers={"Host": "127.0.0.1:8000"}).status_code == 200
    assert cli.get("/", headers={"Host": "localhost:9999"}).status_code == 200


def test_post_com_origin_ou_referer_de_outro_site_e_recusado(ctx):
    cli, copia, i = ctx
    dados = {**_form(cli, i), "status_final": "em_uso", "revisor": "Ana", "observacao": ""}
    for cab in ({"Origin": "http://evil.example"}, {"Origin": "null"}, {"Referer": "http://evil.example/x"},
                {"Origin": "http://127.0.0.1:9999", "Host": "127.0.0.1:8000"}):
        r = cli.post(f"/achados/{i}/verificar", data=dados, headers=cab)
        assert r.status_code == 403 and "outro site" in r.text, cab
    assert _estado(copia, i)[0] == 0
    ok = cli.post(f"/achados/{i}/verificar", data=dados, headers={"Origin": "http://127.0.0.1:8000", "Host": "127.0.0.1:8000"}, follow_redirects=False)
    assert ok.status_code == 303 and _estado(copia, i)[0] == 1


# ---------- 3. parametros invalidos ----------
@pytest.mark.parametrize("rota", ["/achados?p=abc", "/achados?p=99999999999999999999", "/achados?p=-3", "/achados?p=0", "/achados?p=1.5",
                                  "/achados?p=", "/achados/1?completo=x", "/achados/1?ok=999999999999999999999", "/achados?q=" + "x" * 5000])
def test_parametros_invalidos_nunca_dao_500(ctx, rota):
    cli, _, _ = ctx
    r = cli.get(rota)
    assert r.status_code in (200, 404), (rota, r.status_code)
    assert "Traceback" not in r.text and "File \"" not in r.text


def test_pagina_alem_do_fim_mostra_lista_vazia_e_nao_quebra(ctx):
    cli, _, _ = ctx
    r = cli.get("/achados?p=500000")
    assert r.status_code == 200 and "Não há achados nesta página" in r.text and 'href="/achados?p=1"' in r.text


# ---------- 4. revogar ----------
def test_revogar_verificacao_da_planilha_pelo_painel(ctx):
    cli, copia, i = ctx
    _planilha(copia, i, "em_uso", "Bia")
    pag = cli.get(f"/achados/{i}").text
    assert "Revogar verificação" in pag
    r = cli.post(f"/achados/{i}/revogar", data={**_form(cli, i), "revisor": "Ana", "motivo": "marquei o achado errado"}, follow_redirects=False)
    assert r.status_code == 303 and _estado(copia, i) == (0, None, None)
    h = sqlite3.connect(copia).execute("SELECT verificado_por, status_final, observacao FROM achados_revisoes WHERE achado_id=? ORDER BY revisao_id DESC", (i,)).fetchone()
    assert h[0] == "Ana" and h[1] is None and "marquei o achado errado" in h[2]


def test_revogar_exige_motivo_revisor_csrf_e_verificacao_existente(ctx):
    cli, copia, i = ctx
    _planilha(copia, i, "em_uso", "Bia")
    base = _form(cli, i)
    assert cli.post(f"/achados/{i}/revogar", data={**base, "revisor": "Ana", "motivo": "  "}).status_code == 400
    assert cli.post(f"/achados/{i}/revogar", data={**base, "revisor": "", "motivo": "x"}).status_code == 400
    assert cli.post(f"/achados/{i}/revogar", data={"revisor": "Ana", "motivo": "x"}).status_code == 403
    assert _estado(copia, i)[0] == 1
    cli.post(f"/achados/{i}/revogar", data={**base, "revisor": "Ana", "motivo": "x"})
    assert cli.post(f"/achados/{i}/revogar", data={**_form(cli, i), "revisor": "Ana", "motivo": "x"}).status_code == 400   # ja revogado


def test_formulario_de_revogar_nao_aparece_sem_verificacao_nem_em_somente_leitura(ctx, demo, tmp_path):
    cli, copia, i = ctx
    assert "Revogar verificação" not in cli.get(f"/achados/{i}").text
    ro = TestClient(_app(copia, demo[1], tmp_path, somente_leitura=True)[0])
    _planilha(copia, i, "em_uso", "Bia")
    assert "Revogar verificação" not in ro.get(f"/achados/{i}").text
    assert ro.post(f"/achados/{i}/revogar", data={"csrf": "x", "revisor": "A", "motivo": "m"}).status_code == 403


# ---------- decisoes concorrentes ----------
def test_decisao_sobre_pagina_desatualizada_e_recusada_com_aviso(ctx):
    cli, copia, i = ctx
    antigo = _form(cli, i)                                              # pagina aberta antes de outra pessoa decidir
    _planilha(copia, i, "piloto", "Bia")
    r = cli.post(f"/achados/{i}/verificar", data={**antigo, "status_final": "em_uso", "revisor": "Ana", "observacao": ""})
    assert r.status_code == 409 and "mudou depois" in r.text and "Bia" in r.text
    assert _estado(copia, i) == (1, "piloto", "Bia")
    novo = _form(cli, i)                                                # recarregou: agora pode sobrescrever de forma consciente
    assert cli.post(f"/achados/{i}/verificar", data={**novo, "status_final": "em_uso", "revisor": "Ana", "observacao": ""}, follow_redirects=False).status_code == 303
    assert _estado(copia, i) == (1, "em_uso", "Ana")


def test_duas_abas_abertas_sobre_o_mesmo_achado_nao_se_sobrescrevem(ctx):
    cli, copia, i = ctx
    aba1, aba2 = _form(cli, i), _form(cli, i)
    assert cli.post(f"/achados/{i}/verificar", data={**aba1, "status_final": "em_uso", "revisor": "Ana", "observacao": ""}, follow_redirects=False).status_code == 303
    assert cli.post(f"/achados/{i}/verificar", data={**aba2, "status_final": "descartado", "revisor": "Bia", "observacao": ""}).status_code == 409
    assert _estado(copia, i)[1] == "em_uso"


# ---------- repositorio ----------
def test_repositorio_verificar_com_versao_antiga_nao_grava(tmp_path):
    from dados_metricas import construir_classificacao_mista
    import logging
    logging.disable(logging.CRITICAL)
    try:
        repo, _ = construir_classificacao_mista(tmp_path)
    finally:
        logging.disable(logging.NOTSET)
    a = repo.conn.execute("SELECT achado_id FROM achados LIMIT 1").fetchone()[0]
    repo.verificar_achado(a, "em_uso", "Ana", None, PERMITIDOS, versao="nao-verificado")
    with pytest.raises(SystemExit, match="mudou depois"):
        repo.verificar_achado(a, "piloto", "Bia", None, PERMITIDOS, versao="nao-verificado")
    assert not repo.conn.in_transaction
    assert repo.conn.execute("SELECT status_final FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == "em_uso"
