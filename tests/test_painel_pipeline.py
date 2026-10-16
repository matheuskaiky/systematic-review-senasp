"""Telas de execucoes e chamadas (F1): listas, detalhe, comparar, bruto, segredos mascarados."""
import json
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adaptadores.repositorio_sqlite import RepositorioSQLite
from test_painel import _app, demo  # noqa: F401


@pytest.fixture
def ctx(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    return TestClient(_app(copia, raw, tmp_path)[0]), copia, raw


def _um(copia, sql, *a):
    return sqlite3.connect(copia).execute(sql, a).fetchone()[0]


def test_lista_de_execucoes_mostra_todas_com_situacao_e_relatorio(ctx):
    cli, copia, _ = ctx
    h = cli.get("/execucoes").text
    n = _um(copia, "SELECT COUNT(*) FROM execucoes")
    assert len(re.findall(r'<a href="/execucoes/\d{8}_', h)) == n
    assert "concluída" in h and "interrompida" in h and "falhou" in h and ">fora<" in h.replace("\n", "")


def test_detalhe_da_execucao_traz_funil_custos_falhas_config_e_nao_mostra_json_cru(ctx):
    cli, copia, _ = ctx
    run = _um(copia, "SELECT run_id FROM execucoes WHERE comando='classificar' AND no_relatorio=1")
    h = cli.get(f"/execucoes/{run}").text
    for esperado in ("Funil", "Custo e latência por etapa", "Falhas", "Configuração desta execução", "Prompt v4", "Termos acadêmicos (46)", "Provedores"):
        assert esperado in h, esperado
    assert "&#34;" not in h.split("Configuração desta execução")[1][:3000]          # nada de JSON cru, so tabelas e arvores
    busca = _um(copia, "SELECT run_id FROM execucoes WHERE comando='busca-web' AND no_relatorio=1")
    assert "Consultas web" in cli.get(f"/execucoes/{busca}").text and "Alimentou" in cli.get(f"/execucoes/{busca}").text


def test_creditos_mostram_a_diferenca_com_nota_de_como_ler_e_travessao_se_interrompida(ctx):
    cli, copia, _ = ctx
    run = _um(copia, "SELECT run_id FROM execucoes WHERE status='concluida' LIMIT 1")
    c = sqlite3.connect(copia)
    c.execute("DELETE FROM saldos WHERE run_id=?", (run,))
    c.executemany("INSERT INTO saldos (run_id, provedor, momento, valor, registrado_em) VALUES (?,?,?,?,?)",
                  [(run, "serpapi_scholar", "inicio", 249, "2026-10-15T17:52:04+00:00"),
                   (run, "serpapi_scholar", "fim", 169, "2026-10-15T17:56:41+00:00"),
                   (run, "serpapi_scholar", "inicio", 169, "2026-10-16T09:00:00+00:00")])        # 2a passada interrompida
    c.commit()
    c.close()
    h = cli.get(f"/execucoes/{run}").text.replace("\n", " ")
    assert "Créditos antes e depois" in h and "Como ler:" in h and "negativa" in h and "positiva" in h
    assert 'title="Consumo menos chamadas ok.' in h                                   # cabecalho da coluna explica a diferenca
    linhas = re.findall(r"<tr><td>serpapi_scholar</td>(.*?)</tr>", h)
    assert len(linhas) == 2
    assert '<span class="selo alerta">80</span>' in linhas[0]            # consumo 80 sem chamadas ok registradas na janela: diferenca 80
    assert linhas[1].split("</td>")[-2].endswith("—")                                                         # interrompida: sem diferenca


def test_execucao_em_andamento_se_atualiza_sozinha_e_as_outras_nao(ctx):
    cli, copia, _ = ctx
    run = _um(copia, "SELECT run_id FROM execucoes WHERE status='concluida' LIMIT 1")
    assert 'http-equiv="refresh"' not in cli.get(f"/execucoes/{run}").text
    c = sqlite3.connect(copia)
    c.execute("UPDATE execucoes SET status='em_andamento', finalizado_em=NULL WHERE run_id=?", (run,))
    c.commit()
    assert 'http-equiv="refresh"' in cli.get(f"/execucoes/{run}").text


def test_execucao_inexistente_ou_estranha_da_404_amigavel(ctx):
    cli, _, _ = ctx
    for rota in ("/execucoes/nao-existe", "/execucoes/" + "x" * 500, "/execucoes/comparar?a=nao&b=existe", "/chamadas/99999999", "/chamadas/abc", "/chamadas/99999999/bruto"):
        r = cli.get(rota)
        assert r.status_code == 404 and "Voltar à visão geral" in r.text, rota


def test_comparar_mostra_funil_lado_a_lado_e_diferencas_de_configuracao(ctx):
    cli, copia, _ = ctx
    a, b = [r[0] for r in sqlite3.connect(copia).execute("SELECT run_id FROM execucoes WHERE comando='classificar' ORDER BY run_id")][:2]
    c = sqlite3.connect(copia)
    cfg = json.loads(c.execute("SELECT config_json FROM execucoes WHERE run_id=?", (b,)).fetchone()[0])
    cfg["prompt_versao"] = "v-outro"
    cfg["classificacao"]["max_chars_texto"] = 1234
    c.execute("UPDATE execucoes SET config_json=?, config_hash='outrohash' WHERE run_id=?", (json.dumps(cfg), b))
    c.commit()
    h = cli.get(f"/execucoes/comparar?a={a}&b={b}").text
    assert "Funil lado a lado" in h and "prompt_versao" in h and "v-outro" in h and "classificacao.max_chars_texto" in h and "1234" in h
    assert "Configuração idêntica" in cli.get(f"/execucoes/comparar?a={a}&b={a}").text
    assert cli.get("/execucoes/comparar").status_code == 200


def test_lista_de_chamadas_filtra_e_pagina(ctx):
    cli, copia, _ = ctx
    total = _um(copia, "SELECT COUNT(*) FROM chamadas")
    assert f"<strong>{total:,}</strong>".replace(",", ".") in cli.get("/chamadas").text
    falhas = _um(copia, "SELECT COUNT(*) FROM chamadas WHERE sucesso=0")
    assert f"<strong>{falhas}</strong>" in cli.get("/chamadas?resultado=falha").text
    n = _um(copia, "SELECT COUNT(*) FROM chamadas WHERE etapa='download'")
    assert f"<strong>{n}</strong>" in cli.get("/chamadas?etapa=download").text
    assert "Nenhuma chamada" in cli.get("/chamadas?uf=AC&etapa=busca_academica").text
    assert "Não há chamadas nesta página" in cli.get("/chamadas?p=900000").text
    assert cli.get("/chamadas?p=abc").status_code == 404
    assert cli.get("/chamadas?q=%25").status_code == 200


def test_detalhe_da_chamada_de_classificacao_mostra_parametros_achados_e_bruto(ctx):
    cli, copia, _ = ctx
    cid = _um(copia, "SELECT chamada_id FROM chamadas WHERE etapa='classificacao' AND sucesso=1 AND chamada_id IN (SELECT chamada_id FROM classificacoes WHERE n_achados>0) LIMIT 1")
    h = cli.get(f"/chamadas/{cid}").text
    assert "Parâmetros enviados" in h and "Classificação gravada" in h and "Resposta bruta" in h and "/achados/" in h and "baixar o arquivo" in h
    d = cli.get(f"/chamadas/{cid}/bruto")
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"]


def test_detalhe_da_chamada_de_download_e_de_falha(ctx):
    cli, copia, _ = ctx
    cid = _um(copia, "SELECT chamada_id FROM chamadas WHERE etapa='download' AND sucesso=1 LIMIT 1")
    assert "Página baixada" in cli.get(f"/chamadas/{cid}").text
    falha = _um(copia, "SELECT chamada_id FROM chamadas WHERE sucesso=0 AND etapa='classificacao' LIMIT 1")
    h = cli.get(f"/chamadas/{falha}").text
    assert "falhou" in h and "Erro:" in h and "modelo indisponível" in h


def test_segredos_sao_mascarados_na_tela_mas_nao_alterados_no_banco(ctx):
    cli, copia, raw = ctx
    segredo = "SEGREDO-DE-TESTE-12345"
    c = sqlite3.connect(copia)
    cid, caminho = c.execute("SELECT chamada_id, raw_path FROM chamadas WHERE etapa='busca_web' AND raw_path IS NOT NULL LIMIT 1").fetchone()
    c.execute("UPDATE chamadas SET parametros_json=?, extras_json=? WHERE chamada_id=?",
              (json.dumps({"api_key": segredo, "headers": {"Authorization": "Bearer " + segredo}, "ok": "visivel"}), json.dumps({"token": segredo}), cid))
    c.commit()
    (raw / caminho).write_text(json.dumps({"x": {"api_key": segredo}, "titulo": "ok"}), encoding="utf-8")
    h = cli.get(f"/chamadas/{cid}").text
    assert segredo not in h and "***" in h and "visivel" in h
    run = _um(copia, "SELECT run_id FROM chamadas WHERE chamada_id=?", cid)
    cfg = json.loads(_um(copia, "SELECT config_json FROM execucoes WHERE run_id=?", run))
    cfg["opcoes"]["perplexity_search"]["api_key"] = segredo
    c.execute("UPDATE execucoes SET config_json=? WHERE run_id=?", (json.dumps(cfg), run))
    c.commit()
    assert segredo not in cli.get(f"/execucoes/{run}").text


def test_bruto_grande_e_cortado_e_download_entrega_o_arquivo_inteiro(ctx):
    cli, copia, raw = ctx
    c = sqlite3.connect(copia)
    cid, caminho = c.execute("SELECT chamada_id, raw_path FROM chamadas WHERE etapa='download' AND raw_path IS NOT NULL LIMIT 1").fetchone()
    (raw / caminho).write_bytes(b"<html>" + b"a" * 500_000 + b"</html>")
    h = cli.get(f"/chamadas/{cid}").text
    assert "mostrando só os primeiros 200 KB" in h and len(h) < 300_000
    assert len(cli.get(f"/chamadas/{cid}/bruto").content) == 500_013


def test_conteudo_hostil_no_bruto_e_nos_parametros_e_escapado(ctx):
    cli, copia, raw = ctx
    c = sqlite3.connect(copia)
    cid, caminho = c.execute("SELECT chamada_id, raw_path FROM chamadas WHERE etapa='download' AND raw_path IS NOT NULL LIMIT 1").fetchone()
    (raw / caminho).write_text('<script>alert(1)</script><img src=x onerror=alert(1)>', encoding="utf-8")
    c.execute("UPDATE chamadas SET parametros_json=?, erro=? WHERE chamada_id=?", (json.dumps({"url": "<script>alert(2)</script>"}), "<script>alert(3)</script>", cid))
    c.commit()
    for rota in (f"/chamadas/{cid}", "/chamadas?q=script"):
        h = cli.get(rota).text
        assert "<script>alert" not in h and "<img src=x" not in h, rota
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in cli.get(f"/chamadas/{cid}").text


def test_navegacao_leva_as_telas_novas(ctx):
    cli, _, _ = ctx
    h = cli.get("/").text
    assert 'href="/execucoes"' in h and 'href="/chamadas"' in h


def test_comparar_execucoes_com_custo_nulo_nao_quebra(ctx):
    """Download nao tem custo (nulo): a soma do custo tem de tratar None (so aparecia com dados reais)."""
    cli, copia, _ = ctx
    baixar = _um(copia, "SELECT run_id FROM execucoes WHERE comando='baixar' LIMIT 1")
    busca = _um(copia, "SELECT run_id FROM execucoes WHERE comando='busca-web' AND no_relatorio=1 LIMIT 1")
    assert _um(copia, "SELECT COUNT(*) FROM chamadas WHERE run_id=? AND custo_usd IS NULL", baixar) > 0
    r = cli.get(f"/execucoes/comparar?a={baixar}&b={busca}")
    assert r.status_code == 200 and "Custo registrado" in r.text
    assert cli.get(f"/execucoes/comparar?a={baixar}&b={baixar}").status_code == 200
