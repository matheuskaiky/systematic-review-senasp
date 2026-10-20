"""Pagina Classificadores: seletor, comparacao de duas execucoes, 404s, numeros conferidos no SQL, XSS e somente leitura."""
import hashlib
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from painel import formatacao as fmt
from test_painel import _app, demo  # noqa: F401


@pytest.fixture
def ctx(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    return TestClient(_app(copia, raw, tmp_path)[0]), copia, raw


def _sql(copia, sql, *a):
    c = sqlite3.connect(copia)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def _gravar(copia, sql, *a):
    c = sqlite3.connect(copia)
    c.execute(sql, a)
    c.commit()
    c.close()


def _runs(copia):
    a = _sql(copia, "SELECT DISTINCT run_id FROM classificacoes WHERE classificador='demo:modelo-a'")[0][0]
    b = _sql(copia, "SELECT DISTINCT run_id FROM classificacoes WHERE classificador='demo:modelo-b'")[0][0]
    return a, b


def _url(a, b):
    return f"/classificadores?a={a}&b={b}"


def _texto(html):
    """Texto visivel aproximado, para conferir numeros e frases."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


JOIN_PARES = """FROM classificacoes x JOIN classificacoes y ON x.url_id=y.url_id AND x.uf=y.uf
                WHERE x.run_id=? AND y.run_id=?"""


# ============================== seletor e estrutura ==============================
def test_seletor_lista_as_execucoes_de_classificacao_e_so_elas(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    r = cli.get("/classificadores")
    assert r.status_code == 200
    assert a in r.text and b in r.text and "demo:modelo-a" in r.text and "demo:modelo-b" in r.text and "v3-demo" in r.text
    busca = _sql(copia, "SELECT run_id FROM execucoes WHERE comando='busca-web' LIMIT 1")[0][0]
    assert busca not in r.text
    assert re.search(r'<label for="exec-a">', r.text) and re.search(r'<select id="exec-a" name="a"', r.text)
    assert r.text.count("<h1") == 1 and "<title>Classificadores" in r.text
    assert 'href="/static/classificadores.css"' in r.text


def test_comparacao_responde_200_com_estrutura_acessivel(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    r = cli.get(_url(a, b))
    assert r.status_code == 200
    assert r.text.count("<h1") == 1 and "<title>Classificadores" in r.text
    assert "DEMONSTRAÇÃO (dados fictícios)" in r.text
    assert "<th>" not in r.text                                  # todo cabecalho de tabela tem scope
    assert not re.search(r"<th(?=[\s>])(?![^>]*scope=)", r.text)
    assert " style=" not in r.text
    assert not re.search(r"<script(?![^>]*\bsrc=)", r.text)
    for rotulo in ("1. Relevância", "2. Tecnologias e achados", "3. Qualidade e custo", "4. Divergências"):
        assert rotulo in r.text
    assert f'<a href="/execucoes/{a}">' in r.text and f'<a href="/execucoes/{b}">' in r.text
    # a execucao B esta fora do relatorio e mesmo assim e comparavel
    assert _sql(copia, "SELECT no_relatorio FROM execucoes WHERE run_id=?", b)[0][0] == 0
    assert "fora" in r.text


# ============================== numeros conferidos no banco ==============================
def test_numeros_da_demo_batem_com_o_sql(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    t = _texto(cli.get(_url(a, b)).text)
    n = _sql(copia, "SELECT COUNT(*) " + JOIN_PARES, a, b)[0][0]
    # a pagina compara PAGINAS (url + UF): a execucao A tem paginas reclassificadas (duas linhas para a mesma pagina), que contam uma vez
    total_a = _sql(copia, "SELECT COUNT(*) FROM (SELECT DISTINCT url_id, uf FROM classificacoes WHERE run_id=?)", a)[0][0]
    total_b = _sql(copia, "SELECT COUNT(*) FROM (SELECT DISTINCT url_id, uf FROM classificacoes WHERE run_id=?)", b)[0][0]
    assert n == 15 and total_a > n
    assert f"{n} páginas nas duas execuções" in t
    assert f"{total_a - n} só em A" in t and f"{total_b - n} só em B" in t
    igual = _sql(copia, "SELECT COUNT(*) " + JOIN_PARES + " AND x.relevante=y.relevante", a, b)[0][0]
    assert f"({igual} de {n} páginas)" in t and fmt.pct(igual, n) in t
    assert "indefinido" in t and "mesma resposta em todas as páginas" in t        # na demonstracao todas sao relevantes
    # achados em comum: mesma tecnologia na mesma pagina
    par = """FROM achados p JOIN classificacoes kp ON kp.classificacao_id=p.classificacao_id
             JOIN achados q ON q.tecnologia=p.tecnologia
             JOIN classificacoes kq ON kq.classificacao_id=q.classificacao_id AND kq.url_id=kp.url_id AND kq.uf=kp.uf
             WHERE kp.run_id=? AND kq.run_id=?"""
    pareados = _sql(copia, "SELECT COUNT(*) " + par, a, b)[0][0]
    st = _sql(copia, "SELECT COUNT(*) " + par + " AND p.status_reportado=q.status_reportado", a, b)[0][0]
    cf = _sql(copia, "SELECT COUNT(*) " + par + " AND p.confianca=q.confianca", a, b)[0][0]
    assert pareados > 0
    assert f"{st} de {pareados} achados em comum" in t and f"{cf} de {pareados} achados em comum" in t
    # qualidade e custo, execucao inteira
    custo_a, n_a = _sql(copia, """SELECT SUM(c.custo_usd), COUNT(*) FROM classificacoes k JOIN chamadas c
                                  ON c.chamada_id=k.chamada_id WHERE k.run_id=?""", a)[0]
    custo_b, n_b = _sql(copia, """SELECT SUM(c.custo_usd), COUNT(*) FROM classificacoes k JOIN chamadas c
                                  ON c.chamada_id=k.chamada_id WHERE k.run_id=?""", b)[0]
    assert fmt.moeda_usd(custo_a) in t and fmt.moeda_usd(custo_b) in t
    assert fmt.moeda_usd(custo_a / n_a) in t and fmt.moeda_usd(custo_b / n_b) in t
    ach_a = _sql(copia, "SELECT COUNT(*) FROM achados a JOIN classificacoes k USING(classificacao_id) WHERE k.run_id=?", a)[0][0]
    assert fmt.moeda_usd(custo_a / ach_a) in t
    # a conferencia da evidencia vale so para a classificacao mais recente de cada pagina da execucao (dominio/concordancia.py): na demonstracao
    # algumas paginas foram reclassificadas dentro da execucao A, e a leitura antiga delas nao entra
    ok_a, av_a = _sql(copia, """SELECT SUM(a.evidencia_confere), COUNT(a.evidencia_confere) FROM achados a
                                JOIN classificacoes k USING(classificacao_id) WHERE k.run_id=? AND k.classificacao_id =
                                (SELECT MAX(k2.classificacao_id) FROM classificacoes k2 WHERE k2.run_id=k.run_id AND k2.url_id=k.url_id AND k2.uf=k.uf)""", a)[0]
    assert f"({ok_a} de {av_a})" in t


def test_kappa_e_divergencias_com_relevancia_alterada(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    # B passa a dizer "nao relevante" em 3 das 15 paginas em comum (e A em 2 outras): a tabela 2x2 deixa de ser degenerada
    pares = _sql(copia, "SELECT y.classificacao_id, x.classificacao_id " + JOIN_PARES + " ORDER BY x.classificacao_id", a, b)
    for cb, _ca in pares[:3]:
        _gravar(copia, "UPDATE classificacoes SET relevante=0 WHERE classificacao_id=?", cb)
    for _cb, ca in pares[3:5]:
        _gravar(copia, "UPDATE classificacoes SET relevante=0 WHERE classificacao_id=?", ca)
    n = len(pares)
    sim_a = sim_b = ambas = 0
    for row in _sql(copia, "SELECT x.relevante, y.relevante " + JOIN_PARES, a, b):
        sim_a += row[0]; sim_b += row[1]; ambas += row[0] and row[1]
    nao_ambas = n - sim_a - sim_b + ambas
    po = (ambas + nao_ambas) / n
    pe = (sim_a * sim_b + (n - sim_a) * (n - sim_b)) / n ** 2
    kappa = (po - pe) / (1 - pe)
    t = _texto(cli.get(_url(a, b)).text)
    assert f"({ambas + nao_ambas} de {n} páginas)" in t
    assert fmt.decimal(kappa, 2) in t and "indefinido" not in t
    assert "2 de relevância" not in t and "5 de relevância" in t
    assert "A nº" in t or "B nº" in t


def test_links_de_achado_na_divergencia_levam_a_um_achado_existente(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    # forca uma divergencia de status em uma pagina em comum
    alvo = _sql(copia, """SELECT p.achado_id, q.achado_id FROM achados p JOIN classificacoes kp ON kp.classificacao_id=p.classificacao_id
                          JOIN achados q ON q.tecnologia=p.tecnologia
                          JOIN classificacoes kq ON kq.classificacao_id=q.classificacao_id AND kq.url_id=kp.url_id AND kq.uf=kp.uf
                          WHERE kp.run_id=? AND kq.run_id=? LIMIT 1""", a, b)[0]
    _gravar(copia, "UPDATE achados SET status_reportado='em_uso' WHERE achado_id=?", alvo[0])
    _gravar(copia, "UPDATE achados SET status_reportado='piloto' WHERE achado_id=?", alvo[1])
    html = cli.get(_url(a, b)).text
    assert f'href="/achados/{alvo[0]}"' in html and f'href="/achados/{alvo[1]}"' in html
    assert "Mesma tecnologia, situação diferente." in html
    assert cli.get(f"/achados/{alvo[0]}").status_code == 200 and cli.get(f"/achados/{alvo[1]}").status_code == 200


def test_custo_nulo_aparece_como_nao_calculado(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    _gravar(copia, "UPDATE chamadas SET custo_usd=NULL WHERE run_id=?", b)
    t = _texto(cli.get(_url(a, b)).text)
    assert t.count("não calculado") >= 3
    assert "US$ 0,0000" not in t


def test_ordem_a_b_se_inverte_sem_erro(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    r = cli.get(_url(b, a))
    assert r.status_code == 200
    assert "só em B (ficam de fora da comparação)" in r.text


# ============================== mensagens amigaveis e 404 ==============================
def test_execucao_desconhecida_ou_de_outro_comando_da_404_amigavel(ctx):
    cli, copia, _ = ctx
    a, _b = _runs(copia)
    busca = _sql(copia, "SELECT run_id FROM execucoes WHERE comando='busca-web' LIMIT 1")[0][0]
    for rota in (f"/classificadores?a={a}&b=nao-existe", f"/classificadores?a=nao-existe&b={a}", f"/classificadores?a={a}&b={busca}",
                 "/classificadores?a=" + "x" * 5000 + f"&b={a}", "/classificadores?a=%3Cscript%3E&b=1", f"/classificadores?a={a}&b=%27%20OR%201%3D1--"):
        r = cli.get(rota)
        assert r.status_code == 404, rota
        assert "Execução não encontrada" in r.text and "Voltar à visão geral" in r.text
        assert "<script>" not in r.text


def test_mesma_execucao_duas_vezes_mostra_mensagem(ctx):
    cli, copia, _ = ctx
    a, _b = _runs(copia)
    r = cli.get(_url(a, a))
    assert r.status_code == 200 and "Escolha duas execuções diferentes" in r.text
    assert "1. Relevância" not in r.text


def test_so_um_lado_escolhido_pede_o_outro(ctx):
    cli, copia, _ = ctx
    a, _b = _runs(copia)
    for rota in (f"/classificadores?a={a}", f"/classificadores?b={a}"):
        r = cli.get(rota)
        assert r.status_code == 200 and "Escolha as duas execuções para comparar" in r.text


def test_sem_paginas_em_comum_mostra_mensagem_e_ainda_resume_as_execucoes(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    _gravar(copia, "UPDATE classificacoes SET uf='ZZ' WHERE run_id=?", b)
    r = cli.get(_url(a, b))
    assert r.status_code == 200
    t = _texto(r.text)
    assert "nenhuma página em comum" in t and "0 páginas nas duas execuções" in t
    assert "1. Relevância" not in t and "4. Divergências" not in t
    assert "1. Qualidade e custo de cada execução" in t


def test_sem_execucoes_de_classificacao_e_sem_banco(demo, tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    r = TestClient(_app(vazio, tmp_path / "raw", tmp_path, nome="simulado")[0]).get("/classificadores")
    assert r.status_code == 200 and "Nenhuma execução de classificação registrada" in r.text
    sem = TestClient(_app(tmp_path / "naoexiste.db", tmp_path / "raw", tmp_path)[0])
    assert sem.get("/classificadores").status_code == 503 and not (tmp_path / "naoexiste.db").exists()


def test_uma_so_execucao_explica_como_gerar_a_segunda(ctx):
    cli, copia, _ = ctx
    _, b = _runs(copia)
    c = sqlite3.connect(copia)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("UPDATE execucoes SET comando='busca-web' WHERE run_id=?", (b,))
    c.commit(); c.close()
    r = cli.get("/classificadores")
    assert r.status_code == 200 and "Só há uma execução de classificação" in r.text


# ============================== seguranca ==============================
def test_texto_coletado_e_escapado_e_url_perigosa_vira_ancora_vazia(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    xss = "<script>alert(1)</script>"
    _gravar(copia, "UPDATE classificacoes SET classificador=?, prompt_versao=? WHERE run_id=?", xss, xss, b)
    _gravar(copia, "UPDATE achados SET evidencia=?, fornecedor=?", xss, xss)
    _gravar(copia, "UPDATE achados SET tecnologia=?, confianca=? WHERE achado_id IN (SELECT achado_id FROM achados a JOIN classificacoes k "
                   "USING(classificacao_id) WHERE k.run_id=? LIMIT 3)", xss, xss, b)
    _gravar(copia, "UPDATE achados SET status_reportado=? WHERE achado_id IN (SELECT achado_id FROM achados a JOIN classificacoes k "
                   "USING(classificacao_id) WHERE k.run_id=? ORDER BY achado_id DESC LIMIT 3)", xss, b)
    _gravar(copia, "UPDATE urls SET url_original='javascript:alert(1)' WHERE url_id IN (SELECT url_id FROM classificacoes WHERE run_id=?)", b)
    for rota in ("/classificadores", _url(a, b), _url(b, a)):
        r = cli.get(rota)
        assert r.status_code == 200
        assert xss not in r.text and "<script>alert" not in r.text
        assert "href=\"javascript" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in cli.get("/classificadores").text
    html = cli.get(_url(a, b)).text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert re.findall(r'<a href="([^"]*)" rel="noopener noreferrer" target="_blank"', html) or "target=\"_blank\"" not in html
    assert all("rel=\"noopener noreferrer\"" in m for m in re.findall(r'<a [^>]*target="_blank"[^>]*>', html))


def test_links_externos_usam_rel_e_target(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    _gravar(copia, "UPDATE achados SET status_reportado='em_uso' WHERE classificacao_id IN (SELECT classificacao_id FROM classificacoes WHERE run_id=?)", a)
    _gravar(copia, "UPDATE achados SET status_reportado='piloto' WHERE classificacao_id IN (SELECT classificacao_id FROM classificacoes WHERE run_id=?)", b)
    html = cli.get(_url(a, b)).text
    externos = re.findall(r'<a [^>]*target="_blank"[^>]*>', html)
    assert externos and all('rel="noopener noreferrer"' in x and 'href="http' in x for x in externos)


def test_a_pagina_nunca_escreve_no_banco(ctx):
    cli, copia, _ = ctx
    a, b = _runs(copia)
    antes = hashlib.sha256(copia.read_bytes()).hexdigest()
    for rota in ("/classificadores", _url(a, b), _url(b, a), _url(a, a), f"/classificadores?a={a}&b=nao-existe"):
        cli.get(rota)
    assert hashlib.sha256(copia.read_bytes()).hexdigest() == antes
    assert all(p.stat().st_size == 0 for p in copia.parent.glob("demo.db-wal"))   # com WAL, o -wal existe mas fica vazio
