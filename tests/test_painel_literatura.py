"""Literatura no painel: visao geral, artigos, triagem com escrita, PRISMA e seguranca dos links."""
import re
import shutil
import sqlite3
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from adaptadores.repositorio_sqlite import RepositorioSQLite
from painel import rotulos
from painel.graficos import colunas, mapa_de_calor
from test_painel import _app, _csrf, demo  # noqa: F401


@pytest.fixture
def ctx(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, c = _app(copia, raw, tmp_path)
    c.termos = {"T01": '"reconhecimento facial"'}
    c.bases = ("IEEE", "ACM", "Scopus", "SBC OpenLib")
    return TestClient(app), copia, c


def _um(copia, sql, *a):
    return sqlite3.connect(copia).execute(sql, a).fetchone()[0]


def _pendente(copia):
    return _um(copia, "SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id WHERE t.decisao IS NULL ORDER BY a.artigo_id LIMIT 1")


def _form(cli, i, **extra):
    pag = cli.get(f"/literatura/artigos/{i}").text
    return {"csrf": _csrf(pag), "versao": re.search(r'name="versao" value="([^"]*)"', pag).group(1), **extra}


# ---------- paginas ----------
def test_todas_as_paginas_de_literatura_respondem(ctx):
    cli, copia, _ = ctx
    for rota in ("/literatura", "/literatura/artigos", "/literatura/artigos?decisao=pendente&multi=1&termo=T01", "/literatura/artigos?q=estudo&ano_de=2020&ano_ate=2023",
                 "/literatura/artigos?base=IEEE", "/literatura/prisma", f"/literatura/artigos/{_pendente(copia)}"):
        assert cli.get(rota).status_code == 200, rota
    assert cli.get("/literatura/triagem", follow_redirects=False).status_code == 303


def test_visao_geral_traz_numeros_graficos_e_buscas_manuais(ctx):
    cli, copia, _ = ctx
    h = cli.get("/literatura").text
    n = _um(copia, "SELECT COUNT(*) FROM r_artigos")
    assert f'<span class="kpi-valor">{n}</span><span class="kpi-rotulo">Artigos únicos</span>' in h.replace("\n", "")
    assert "Artigos por ano" in h and "Termos em comum" in h and "<svg" in h and "IEEE" in h and "SBC OpenLib" not in h.split("Buscas manuais por base")[1].split("Termos em comum")[0]
    assert "sem contagem de citações" in h


def test_lista_filtra_por_decisao_termo_ano_e_busca(ctx):
    cli, copia, _ = ctx
    def total(rota):
        return int(re.search(r"<strong>([\d.]+)</strong> artigo", cli.get(rota).text).group(1).replace(".", ""))
    todos = total("/literatura/artigos")
    pend = total("/literatura/artigos?decisao=pendente")
    inc = total("/literatura/artigos?decisao=incluir")
    exc = total("/literatura/artigos?decisao=excluir")
    assert pend + inc + exc == todos and pend > 0 and inc > 0 and exc > 0
    assert 0 < total("/literatura/artigos?multi=1") < todos
    assert total("/literatura/artigos?ano_de=2024") < todos and total("/literatura/artigos?ano_de=2030") == 0
    assert total("/literatura/artigos?termo=T01") == _um(copia, "SELECT COUNT(DISTINCT artigo_id) FROM r_ocorrencias WHERE termo_id='T01'")
    assert total("/literatura/artigos?q=Estudo+demonstrativo+003") >= 1 and total("/literatura/artigos?q=%25") == 0
    assert total("/literatura/artigos?base=IEEE") == _um(copia, "SELECT COUNT(DISTINCT artigo_id) FROM ocorrencias_manuais WHERE base='IEEE'")


def test_ordem_poe_os_achados_varias_vezes_primeiro(ctx):
    cli, copia, _ = ctx
    primeiro = int(re.search(r'href="/literatura/artigos/(\d+)"', cli.get("/literatura/artigos").text).group(1))
    n_primeiro = _um(copia, "SELECT COUNT(*) FROM r_ocorrencias WHERE artigo_id=?", primeiro) + _um(copia, "SELECT COUNT(DISTINCT base) FROM ocorrencias_manuais WHERE artigo_id=?", primeiro)
    maximo = _um(copia, "SELECT MAX(n) FROM (SELECT (SELECT COUNT(DISTINCT termo_id) FROM r_ocorrencias o WHERE o.artigo_id=a.artigo_id) + (SELECT COUNT(DISTINCT base) FROM ocorrencias_manuais m WHERE m.artigo_id=a.artigo_id) AS n FROM r_artigos a)")
    assert n_primeiro == maximo


def test_detalhe_do_artigo_mostra_onde_foi_encontrado_e_historico(ctx):
    cli, copia, _ = ctx
    i = _um(copia, "SELECT artigo_id FROM triagem LIMIT 1")
    h = cli.get(f"/literatura/artigos/{i}").text
    assert "Onde foi encontrado" in h and "Histórico de decisões" in h and "Revisora Demo" in h
    manual = _um(copia, "SELECT artigo_id FROM ocorrencias_manuais LIMIT 1")
    assert "Buscas manuais" in cli.get(f"/literatura/artigos/{manual}").text


def test_404_amigavel_para_artigo_e_pagina_invalidos(ctx):
    cli, _, _ = ctx
    for rota in ("/literatura/artigos/99999999", "/literatura/artigos/abc", "/literatura/artigos?p=abc"):
        r = cli.get(rota)
        assert r.status_code == 404 and "Voltar à visão geral" in r.text, rota
    assert "Não há artigos nesta página" in cli.get("/literatura/artigos?p=900000").text


# ---------- triagem (escrita) ----------
def test_incluir_grava_historico_e_aparece_no_prisma(ctx):
    cli, copia, _ = ctx
    i = _pendente(copia)
    antes = _um(copia, "SELECT valor FROM v_prisma WHERE metrica='incluidos por titulo e resumo'")
    r = cli.post(f"/literatura/artigos/{i}/triar", data={**_form(cli, i), "decisao": "incluir", "revisor": "Ana", "base": "IEEE", "link": "https://exemplo.example/x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/literatura/artigos/{i}?ok={i}"
    t = sqlite3.connect(copia).execute("SELECT decisao, revisor, confirmado_em_base, link_confirmado FROM triagem WHERE artigo_id=?", (i,)).fetchone()
    assert t == ("incluir", "Ana", "IEEE", "https://exemplo.example/x")
    assert _um(copia, "SELECT valor FROM v_prisma WHERE metrica='incluidos por titulo e resumo'") == antes + 1
    assert _um(copia, "SELECT COUNT(*) FROM triagem_revisoes WHERE artigo_id=? AND revisor='Ana' AND independente=0", i) == 1


def test_excluir_exige_motivo_e_motivo_aparece_nos_motivos_de_exclusao(ctx):
    cli, copia, _ = ctx
    i = _pendente(copia)
    r = cli.post(f"/literatura/artigos/{i}/triar", data={**_form(cli, i), "decisao": "excluir", "revisor": "Ana", "motivo": "  "})
    assert r.status_code == 400 and "motivo da exclusão" in r.text
    assert _um(copia, "SELECT COUNT(*) FROM triagem WHERE artigo_id=?", i) == 0
    cli.post(f"/literatura/artigos/{i}/triar", data={**_form(cli, i), "decisao": "excluir", "revisor": "Ana", "motivo": "motivo único de teste"})
    assert _um(copia, "SELECT n FROM v_motivos_exclusao WHERE motivo='motivo único de teste'") == 1
    assert "motivo único de teste" in cli.get("/literatura/prisma").text


def test_validacoes_decisao_revisor_link_base(ctx):
    cli, copia, _ = ctx
    i = _pendente(copia)
    base = _form(cli, i)
    casos = [({"decisao": "talvez", "revisor": "Ana"}, "Invalid decision"), ({"decisao": "incluir", "revisor": " "}, "revisor"),
             ({"decisao": "incluir", "revisor": "Ana", "link": "javascript:alert(1)"}, "http"),
             ({"decisao": "incluir", "revisor": "Ana", "base": "BaseInventada"}, "Base desconhecida")]
    for dados, trecho in casos:
        r = cli.post(f"/literatura/artigos/{i}/triar", data={**base, **dados})
        assert r.status_code == 400 and trecho in r.text, dados
    assert _um(copia, "SELECT COUNT(*) FROM triagem WHERE artigo_id=?", i) == 0


def test_csrf_origem_e_somente_leitura(ctx, demo, tmp_path):
    cli, copia, c = ctx
    i = _pendente(copia)
    dados = {**_form(cli, i), "decisao": "incluir", "revisor": "Ana"}
    assert cli.post(f"/literatura/artigos/{i}/triar", data={**dados, "csrf": "x"}).status_code == 403
    assert cli.post(f"/literatura/artigos/{i}/triar", data=dados, headers={"Origin": "http://evil.example"}).status_code == 403
    ro = TestClient(_app(copia, demo[1], tmp_path, somente_leitura=True)[0])
    assert "<form method=\"post\"" not in ro.get(f"/literatura/artigos/{i}").text
    assert ro.post(f"/literatura/artigos/{i}/triar", data=dados).status_code == 403
    assert _um(copia, "SELECT COUNT(*) FROM triagem WHERE artigo_id=?", i) == 0


def test_decisao_sobre_pagina_desatualizada_e_recusada(ctx):
    cli, copia, _ = ctx
    i = _pendente(copia)
    antigo = _form(cli, i)
    r = RepositorioSQLite(copia)
    r.registrar_triagem(i, "excluir", "Bia", "fora do escopo")
    r.fechar()
    resp = cli.post(f"/literatura/artigos/{i}/triar", data={**antigo, "decisao": "incluir", "revisor": "Ana"})
    assert resp.status_code == 409 and "mudou depois" in resp.text and "Bia" in resp.text
    assert _um(copia, "SELECT decisao FROM triagem WHERE artigo_id=?", i) == "excluir"
    novo = _form(cli, i)
    assert cli.post(f"/literatura/artigos/{i}/triar", data={**novo, "decisao": "incluir", "revisor": "Ana"}, follow_redirects=False).status_code == 303


def test_texto_completo_so_para_incluidos_e_preserva_a_primeira_etapa(ctx):
    cli, copia, _ = ctx
    i = _pendente(copia)
    r = cli.post(f"/literatura/artigos/{i}/triar", data={**_form(cli, i), "decisao": "incluir", "revisor": "Ana", "etapa": "texto_completo"})
    assert r.status_code == 400 and "precisa estar incluído" in r.text
    cli.post(f"/literatura/artigos/{i}/triar", data={**_form(cli, i), "decisao": "incluir", "revisor": "Ana", "motivo": "ok"})
    assert "Texto completo" in cli.get(f"/literatura/artigos/{i}").text
    cli.post(f"/literatura/artigos/{i}/triar", data={**_form(cli, i), "decisao": "excluir", "revisor": "Ana", "motivo": "metodologia fraca", "etapa": "texto_completo"})
    t = sqlite3.connect(copia).execute("SELECT decisao, motivo, decisao_texto_completo, motivo_texto_completo FROM triagem WHERE artigo_id=?", (i,)).fetchone()
    assert t == ("incluir", "ok", "excluir", "metodologia fraca")
    assert _um(copia, "SELECT n FROM v_motivos_exclusao WHERE etapa='texto_completo' AND motivo='metodologia fraca'") == 1


def test_fila_de_triagem_anda_e_acaba(tmp_path, demo):
    banco, raw = demo
    copia = tmp_path / "pequeno.db"
    shutil.copy(banco, copia)
    c = sqlite3.connect(copia)
    c.execute("INSERT OR REPLACE INTO triagem (artigo_id, decisao, revisor, revisado_em) SELECT artigo_id, 'excluir', 'x', '2026-01-01T00:00:00+00:00' FROM r_artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT 3)")
    c.execute("DELETE FROM triagem WHERE artigo_id IN (SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT 3)")
    c.commit()
    cli = TestClient(_app(copia, raw, tmp_path)[0])
    destino = cli.get("/literatura/triagem", follow_redirects=False).headers["location"]
    n = 0
    while destino.startswith("/literatura/artigos/") and n < 10:
        i = int(re.search(r"/artigos/(\d+)", destino).group(1))
        pag = cli.get(destino)
        assert "fila de triagem" in pag.text
        r = cli.post(f"/literatura/artigos/{i}/triar?fila=1", data={"decisao": "incluir", "revisor": "Ana", "csrf": _csrf(pag.text), "versao": "nao-triado"}, follow_redirects=False)
        assert r.status_code == 303
        destino = r.headers["location"]
        n += 1
    assert n == 3 and "Triagem por título e resumo concluída" in cli.get("/literatura/triagem").text


# ---------- PRISMA ----------
def test_prisma_mostra_caixas_origem_e_nao_informado(ctx, tmp_path):
    cli, copia, _ = ctx
    h = cli.get("/literatura/prisma").text
    for fase in ("Identificação", "Triagem (título e resumo)", "Elegibilidade (texto completo)", "Inclusão"):
        assert fase in h
    assert "origem: <code>v_prisma</code>" in h and "contagem informada por você" in h
    vazio = tmp_path / "v.db"
    RepositorioSQLite(vazio).fechar()
    hv = TestClient(_app(vazio, tmp_path / "raw", tmp_path)[0]).get("/literatura/prisma").text
    assert "não informado" in hv and "não executado" in hv


def test_prisma_numeros_batem_com_a_view(ctx):
    cli, copia, _ = ctx
    h = cli.get("/literatura/prisma").text.replace("\n", " ")
    for metrica, valor in sqlite3.connect(copia).execute("SELECT metrica, valor FROM v_prisma WHERE fase IN ('triagem','elegibilidade','inclusao')"):
        texto = rotulos.rotulo(rotulos.PRISMA, metrica)                 # a tela mostra o rotulo acentuado da chave da view
        assert re.search(rf'<span class="num-prisma">{valor}</span>\s*<span>{re.escape(texto)}', h), metrica


def _kpi(h, rotulo):
    return int(re.search(rf'<span class="kpi-valor">([\d.]+)</span><span class="kpi-rotulo">{rotulo}</span>', h.replace("\n", "")).group(1).replace(".", ""))


def _veredito_escopo(copia, artigo_id, status="excluido", run="RUN_ESCOPO_TESTE"):
    c = sqlite3.connect(copia)
    c.execute("INSERT OR IGNORE INTO execucoes (run_id, comando, status, iniciado_em, config_hash, config_json) VALUES (?,?,?,?,?,?)",
              (run, "triar-escopo", "concluida", "2026-10-16T10:00:00+00:00", "h", "{}"))
    c.execute("""INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, status, valido, criado_em) VALUES (?,?,?,?,?,1,?)""",
              (run, "artigo", artigo_id, "", status, "2026-10-16T10:00:00+00:00"))
    c.commit()
    c.close()


def test_prisma_e_visao_geral_concordam_sobre_os_artigos_para_triagem(ctx):
    cli, copia, _ = ctx
    unicos = _um(copia, "SELECT COUNT(*) FROM r_artigos")
    avaliados = _um(copia, "SELECT valor FROM v_prisma WHERE metrica='avaliados por titulo e resumo'")
    # sem veredito do modelo: nada removido e os dois numeros iguais ao total
    h = cli.get("/literatura/prisma").text.replace("\n", " ")
    assert re.search(r'<span class="num-prisma">0</span>\s*<span>removidos por ferramenta automática', h)
    assert _kpi(cli.get("/literatura").text, "Artigos únicos") == unicos
    # o modelo exclui 2 artigos pendentes e 1 artigo que uma pessoa ja decidiu
    pendentes = [r[0] for r in sqlite3.connect(copia).execute(
        "SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id WHERE COALESCE(t.decisao,'pendente')='pendente' ORDER BY 1 LIMIT 2")]
    decidido = _um(copia, "SELECT artigo_id FROM triagem WHERE decisao IN ('incluir','excluir') ORDER BY artigo_id LIMIT 1")
    for i in (*pendentes, decidido):
        _veredito_escopo(copia, i)
    h = cli.get("/literatura/prisma").text.replace("\n", " ")
    assert re.search(r'<span class="num-prisma">2</span>\s*<span>removidos por ferramenta automática \(triagem de escopo do modelo, sem decisão humana\)', h)
    assert re.search(rf'<span class="num-prisma">{unicos - 2}</span>\s*<span>artigos únicos para triagem', h)
    assert "decisão humana sempre vence" in h and "/triagem-escopo" in h
    kpi = _kpi(cli.get("/literatura").text, "Artigos únicos")        # o KPI esconde os `llm_oculto` (mesma regra)
    assert kpi == unicos - 2 == _um(copia, "SELECT valor FROM v_prisma WHERE metrica='artigos unicos para triagem'")
    pend_prisma = _um(copia, "SELECT valor FROM v_prisma WHERE metrica='pendentes de titulo e resumo'")
    assert pend_prisma == _kpi(cli.get("/literatura").text, "Pendentes")
    # a decisao humana sempre vence: o artigo triado pela pessoa segue no fluxo humano (as avaliacoes nao mudam)
    assert _um(copia, "SELECT valor FROM v_prisma WHERE metrica='avaliados por titulo e resumo'") == avaliados
    assert _um(copia, "SELECT COUNT(*) FROM triagem WHERE artigo_id=? AND decisao IN ('incluir','excluir')", decidido) == 1


def test_kpi_de_varios_termos_usa_a_mesma_regra_do_filtro_da_lista(ctx):
    cli, copia, _ = ctx
    h = cli.get("/literatura").text
    assert "Achados por 2 ou mais termos ou bases" in h
    kpi = _kpi(h, "Achados por 2 ou mais termos ou bases")
    na_lista = int(re.search(r"<strong>([\d.]+)</strong> artigo", cli.get("/literatura/artigos?multi=1").text).group(1).replace(".", ""))
    assert kpi == na_lista > 0
    so_scholar = _um(copia, "SELECT COUNT(*) FROM v_artigos_multi_termo WHERE n_termos >= 2")
    soma = _um(copia, """SELECT COUNT(*) FROM r_artigos a WHERE (SELECT COUNT(DISTINCT termo_id) FROM r_ocorrencias o WHERE o.artigo_id=a.artigo_id)
                         + (SELECT COUNT(DISTINCT base) FROM ocorrencias_manuais m WHERE m.artigo_id=a.artigo_id) >= 2""")
    assert kpi == soma
    # um artigo achado por 1 termo do Scholar e por 1 base manual entra na regra nova e fica fora da antiga (so Scholar)
    c = sqlite3.connect(copia)
    i = c.execute("""SELECT a.artigo_id FROM r_artigos a WHERE (SELECT COUNT(DISTINCT termo_id) FROM r_ocorrencias o WHERE o.artigo_id=a.artigo_id) = 1
                     AND (SELECT COUNT(DISTINCT base) FROM ocorrencias_manuais m WHERE m.artigo_id=a.artigo_id) = 0 LIMIT 1""").fetchone()[0]
    c.execute("INSERT INTO ocorrencias_manuais (artigo_id, base, termo_id, data_busca, posicao) VALUES (?,?,?,?,?)", (i, "IEEE", "T01", "2026-10-16", 1))
    c.commit()
    c.close()
    h2 = cli.get("/literatura").text
    assert _kpi(h2, "Achados por 2 ou mais termos ou bases") == kpi + 1
    assert _um(copia, "SELECT COUNT(*) FROM v_artigos_multi_termo WHERE n_termos >= 2") == so_scholar     # a view continua so do Scholar
    na_lista2 = int(re.search(r"<strong>([\d.]+)</strong> artigo", cli.get("/literatura/artigos?multi=1").text).group(1).replace(".", ""))
    assert na_lista2 == kpi + 1


# ---------- seguranca ----------
def test_link_do_artigo_com_esquema_perigoso_nao_vira_href(ctx):
    cli, copia, _ = ctx
    i = _pendente(copia)
    c = sqlite3.connect(copia)
    c.execute("UPDATE artigos SET link='javascript:alert(1)', titulo='<script>alert(9)</script>', snippet='\"><img src=x onerror=alert(2)>' WHERE artigo_id=?", (i,))
    c.commit()
    h = cli.get(f"/literatura/artigos/{i}").text
    assert 'href="javascript:' not in h and "<script>alert(9)" not in h and "<img src=x" not in h
    assert 'href="#"' in h and "&lt;script&gt;alert(9)&lt;/script&gt;" in h
    for rota in ("/literatura/artigos", "/literatura", "/literatura/prisma"):
        assert "<script>alert(9)" not in cli.get(rota).text


# ---------- graficos ----------
def test_graficos_da_literatura_sao_xml_valido_e_acessiveis():
    svg = colunas([("2019", 3), ("2020", 0), ("2021", 9)], "T", "D", "ano", "artigos")
    assert ET.fromstring(svg).tag.endswith("svg") and "<title" in svg and "<desc" in svg
    assert colunas([], "T", "D") == ""
    calor = mapa_de_calor(["T01", "T02", "T03"], {("T01", "T02"): 4, ("T01", "T03"): 1, ("T01", "T01"): 9, ("T02", "T02"): 5, ("T03", "T03"): 2}, "T", "D", {"T01": "x"})
    raiz = ET.fromstring(calor)
    celulas = [e for e in raiz.iter() if e.tag.endswith("rect")]
    assert len(celulas) == 9 and calor.count("calor-diag") == 3 and "T01 × T02: 4" in calor and "T01: 9 artigos (x)" in calor
    assert mapa_de_calor([], {}, "T", "D") == ""


def test_heatmap_e_simetrico():
    v = {("A", "B"): 3, ("A", "A"): 5, ("B", "B"): 4}
    svg = mapa_de_calor(["A", "B"], v, "T", "D")
    assert svg.count("A × B: 3") == 1 and svg.count("B × A: 3") == 1


# ---------- repositorio ----------
def test_repositorio_registrar_triagem_valida_e_nao_deixa_transacao_aberta(ctx):
    cli, copia, _ = ctx
    r = RepositorioSQLite(copia)
    with pytest.raises(SystemExit, match="Artigo inexistente"):
        r.registrar_triagem(99999999, "incluir", "Ana")
    with pytest.raises(SystemExit, match="Etapa"):
        r.registrar_triagem(_pendente(copia), "incluir", "Ana", etapa="outra")
    assert not r.conn.in_transaction
    r.registrar_triagem(_pendente(copia), "incluir", "Ana", versao="nao-triado")
    assert not r.conn.in_transaction


def test_prisma_avisa_quando_selecionados_informados_nao_batem_com_os_importados(ctx):
    cli, copia, _ = ctx
    selecionados = _um(copia, "SELECT COALESCE(SUM(n_selecionados), 0) FROM buscas_manuais")
    importados = _um(copia, "SELECT COUNT(DISTINCT artigo_id || '|' || base) FROM ocorrencias_manuais")
    assert selecionados != importados                                    # na demonstracao a divergencia e proposital
    h = cli.get("/literatura/prisma").text
    assert "Confira as buscas manuais" in h and f"{selecionados}" in h and f"{importados}" in h
    c = sqlite3.connect(copia)
    c.execute("UPDATE buscas_manuais SET n_selecionados = 0")
    c.execute("UPDATE buscas_manuais SET n_selecionados = ? WHERE id = (SELECT MIN(id) FROM buscas_manuais)", (importados,))
    c.commit()
    assert "Confira as buscas manuais" not in cli.get("/literatura/prisma").text
