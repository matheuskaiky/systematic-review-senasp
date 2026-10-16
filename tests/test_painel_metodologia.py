"""Pagina Metodologia no painel: numeros iguais ao SQL, links validos, escape de texto coletado, banco vazio e sem JavaScript."""
import json
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adaptadores.repositorio_sqlite import RepositorioSQLite
from painel import formatacao as fmt
from test_painel import _app, demo  # noqa: F401


@pytest.fixture
def ctx(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, c = _app(copia, raw, tmp_path)
    c.bases = ("IEEE", "ACM", "Scopus", "SBC OpenLib")
    return TestClient(app), copia, c


def _sql(copia, sql, *a):
    conn = sqlite3.connect(copia)
    try:
        return conn.execute(sql, a).fetchone()[0]
    finally:
        conn.close()


def _exec(copia, sql, *a):
    conn = sqlite3.connect(copia)
    conn.execute(sql, a)
    conn.commit()
    conn.close()


def _texto_da_pagina(html):
    """Conteudo da div do texto (sem tags)."""
    miolo = html.split('id="texto-metodologia"', 1)[1].split(">", 1)[1]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", miolo))


# ---------- a pagina e seus numeros ----------
def test_pagina_responde_na_demo_com_banner_secoes_e_ressalvas(ctx):
    cli, _, _ = ctx
    r = cli.get("/metodologia")
    assert r.status_code == 200
    assert "DEMONSTRAÇÃO (dados fictícios)" in r.text
    for titulo in ("Busca na literatura acadêmica", "Levantamento nas secretarias", "Classificação automática", "Verificação humana",
                   "Resultados confirmados por UF", "Custos", "Reprodutibilidade", "Ressalvas sobre os dados"):
        assert titulo in r.text, titulo
    assert 'aria-current="page"' in r.text and "Copiar texto" in r.text


def test_numeros_da_pagina_sao_os_do_sql(ctx):
    cli, copia, _ = ctx
    html = cli.get("/metodologia").text
    texto = _texto_da_pagina(html)
    total = _sql(copia, "SELECT COUNT(*) FROM r_achados")
    ok = _sql(copia, "SELECT COUNT(*) FROM r_achados WHERE evidencia_confere=1")
    ver = _sql(copia, "SELECT COUNT(*) FROM r_achados WHERE verificado=1")
    conf = _sql(copia, "SELECT COUNT(*) FROM r_achados WHERE verificado=1 AND COALESCE(status_final,'')<>'descartado'")
    desc = _sql(copia, "SELECT COUNT(*) FROM r_achados WHERE verificado=1 AND status_final='descartado'")
    assert total and ver == conf + desc
    assert f"Dos {fmt.numero(total)} achados, {fmt.numero(ver)} ({100 * ver / total:.1f}%".replace(".", ",") in texto
    assert f"{fmt.numero(conf)} confirmados e {fmt.numero(desc)} descartados" in texto
    assert f"em {fmt.numero(ok)} de {fmt.numero(total)} achados ({100 * ok / total:.1f}%)".replace(".", ",") in texto
    assert f'href="/achados?verificacao=confirmado">{fmt.numero(conf)}</a>' in html
    # secao 16 da especificacao: UFs confirmadas / so classificadas / sem achados
    c, s, z = sqlite3.connect(copia).execute("""SELECT SUM(CASE WHEN n_confirmados > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN n_achados > 0 AND n_confirmados = 0 THEN 1 ELSE 0 END), 27 - COUNT(*) FROM v_resumo_uf""").fetchone()
    assert f"{c} de 27 UFs têm ao menos um achado confirmado" in texto
    assert f"{s} só têm achados classificados pelo modelo" in texto and f"e {z} não têm nenhum achado" in texto
    # busca web e download
    f = sqlite3.connect(copia).execute("""SELECT
        (SELECT COUNT(*) FROM r_chamadas WHERE etapa='busca_web' AND sucesso=1), (SELECT COUNT(*) FROM r_resultados_web),
        (SELECT COUNT(DISTINCT url_id) FROM r_resultados_web), (SELECT COUNT(*) FROM r_paginas),
        (SELECT COUNT(*) FROM r_paginas WHERE extracao_ok=1)""").fetchone()
    assert f"{fmt.numero(f[0])} consultas bem-sucedidas" in texto
    assert f"devolveram {fmt.numero(f[1])} resultados, correspondentes a {fmt.numero(f[2])} URLs únicas" in texto
    assert f"Foram baixadas {fmt.numero(f[3])} páginas, das quais {fmt.numero(f[4])} tiveram texto extraído" in texto
    # literatura
    n_art = _sql(copia, "SELECT COUNT(*) FROM r_artigos")
    req = _sql(copia, "SELECT COUNT(*) FROM r_chamadas WHERE etapa='busca_academica'")
    ret = _sql(copia, "SELECT SUM(n_retornados) FROM r_chamadas WHERE etapa='busca_academica' AND sucesso=1")
    assert f"Ao todo, {fmt.numero(n_art)} artigos únicos foram identificados" in texto
    removidos = _sql(copia, "SELECT valor FROM v_prisma WHERE metrica LIKE 'removidos por ferramenta automatica%'")
    para_triagem = _sql(copia, "SELECT valor FROM v_prisma WHERE metrica='artigos unicos para triagem'")
    assert removidos + para_triagem == n_art
    if removidos:
        assert f"Antes da triagem humana, {fmt.numero(removidos)} foram removidos por uma ferramenta automática" in texto
        assert f"e {fmt.numero(para_triagem)} seguiram para a triagem por título e resumo" in texto
    else:
        assert "Todos seguiram para a triagem por título e resumo." in texto
    assert f"em {fmt.numero(req)} requisições" in texto and f"retornaram {fmt.numero(ret)} registros" in texto
    ieee = sqlite3.connect(copia).execute("SELECT COUNT(*), SUM(n_resultados) FROM buscas_manuais WHERE base='IEEE'").fetchone()
    assert f"IEEE: {ieee[0]} buscas" in texto and f"{fmt.numero(ieee[1])} resultados informados" in texto
    # custos
    gasto = _sql(copia, "SELECT COALESCE(SUM(custo_usd), 0) FROM chamadas")
    assert f"o gasto registrado foi de {fmt.moeda_usd(gasto)}" in texto
    registrado = _sql(copia, "SELECT COALESCE(SUM(custo_usd), 0) FROM r_chamadas")
    assert f"foi de {fmt.moeda_usd(registrado)}, somando só as chamadas com custo calculado" in texto
    assert "custo não calculado (preço não informado)" in texto      # a busca academica da demo nao tem preco


def test_todos_os_links_do_texto_sao_internos_e_levam_a_paginas_que_existem(ctx):
    cli, _, _ = ctx
    html = cli.get("/metodologia").text
    corpo = html.split('id="texto-metodologia"', 1)[1]
    hrefs = set(re.findall(r'<a href="([^"]+)"', corpo))
    assert len(hrefs) > 20
    for h in sorted(hrefs):
        assert h.startswith("/") and not h.startswith("//"), h
        r = cli.get(h.replace("&amp;", "&"), follow_redirects=True)
        assert r.status_code == 200, h


def test_ressalvas_da_demo_cobrem_pendentes_triagem_e_custo(ctx):
    cli, _, _ = ctx
    t = _texto_da_pagina(cli.get("/metodologia").text)
    for esperado in ("Estes dados são fictícios (demonstração)", "ainda não foram verificados por humano", "A triagem está incompleta",
                     "Custo não calculado: preços não informados", "fora do relatório"):
        assert esperado in t, esperado


def test_sem_verificacao_nenhum_achado_e_resultado(ctx):
    cli, copia, _ = ctx
    _exec(copia, "UPDATE achados SET verificado=0, status_final=NULL, verificado_por=NULL, verificado_em=NULL")
    t = _texto_da_pagina(cli.get("/metodologia").text)
    assert "Nenhum achado foi verificado por humano ainda" in t
    assert "0 de 27 UFs têm ao menos um achado confirmado" in t
    assert "0 confirmados e 0 descartados" in t


def test_sem_busca_manual_a_ressalva_lista_as_bases(ctx):
    cli, copia, _ = ctx
    _exec(copia, "DELETE FROM buscas_manuais")
    _exec(copia, "DELETE FROM ocorrencias_manuais")
    t = _texto_da_pagina(cli.get("/metodologia").text)
    assert "Nenhuma busca manual foi importada: as bases IEEE, ACM, Scopus, SBC OpenLib não têm contagens no banco" in t


def test_commit_sujo_aparece_como_ressalva(ctx):
    cli, copia, _ = ctx
    _exec(copia, "UPDATE execucoes SET commit_git='abc1234+sujo:deadbeef' WHERE no_relatorio=1")
    t = _texto_da_pagina(cli.get("/metodologia").text)
    assert "commit com “+sujo”" in t and "commit abc1234+sujo:deadbeef" in t


def test_escopo_municipal_aparece_quando_ha_cidade_e_bate_com_o_sql(ctx):
    cli, copia, _ = ctx
    _exec(copia, """UPDATE classificacoes SET cidade='Vila Modelo' WHERE classificacao_id IN
                    (SELECT classificacao_id FROM r_classificacoes WHERE uf='SP' ORDER BY classificacao_id LIMIT 12)""")
    n, cid, conf = sqlite3.connect(copia).execute("SELECT SUM(n_achados), COUNT(*), SUM(n_confirmados) FROM v_resumo_municipio").fetchone()
    assert n
    t = _texto_da_pagina(cli.get("/metodologia").text)
    assert f"{n} achados em secretarias municipais de {cid} cidade, dos quais {conf} confirmados" in t
    assert "Não há achados de secretarias municipais" not in t


# ---------- seguranca ----------
def test_texto_coletado_e_escapado_no_html(ctx):
    cli, copia, _ = ctx
    xss = "<script>alert(1)</script>"
    _exec(copia, "UPDATE classificacoes SET classificador=?, prompt_versao=?", xss, '"><img src=x onerror=alert(1)>')
    _exec(copia, "UPDATE chamadas SET provedor=? WHERE etapa='busca_web'", "<b onmouseover=alert(2)>x</b>")
    _exec(copia, "UPDATE buscas_manuais SET base=? WHERE base='ACM'", "<svg onload=alert(3)>")
    _exec(copia, "UPDATE execucoes SET comando=?, run_id=run_id", "<iframe src=x>")
    conf = json.loads(sqlite3.connect(copia).execute("SELECT config_json FROM execucoes LIMIT 1").fetchone()[0])
    conf["termos"][0]["query"] = "<script>alert(4)</script>"
    _exec(copia, "UPDATE execucoes SET config_json=?", json.dumps(conf))
    r = cli.get("/metodologia")
    assert r.status_code == 200
    html = r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    for perigoso in ("<script>alert", "<img src=x", "<b onmouseover", "<svg onload", "<iframe", '"><img'):
        assert perigoso not in html, perigoso
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    # o texto do atributo data-texto tambem sai escapado
    assert 'data-texto="' in html and "<svg onload" not in html.split('data-texto="', 1)[1].split('"', 1)[0]


def test_sem_script_inline_nem_estilo_inline_e_com_csp(ctx):
    cli, _, _ = ctx
    r = cli.get("/metodologia")
    assert not re.search(r"<script(?![^>]*\bsrc=)", r.text) and ' style="' not in r.text and "onclick=" not in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert 'src="/static/metodologia.js"' in r.text and 'href="/static/metodologia.css"' in r.text


def test_pagina_funciona_sem_javascript(ctx):
    """O botao nasce escondido (so o JS o mostra) e o texto esta no HTML do servidor, nao montado no navegador."""
    cli, _, _ = ctx
    html = cli.get("/metodologia").text
    botao = re.search(r'<button[^>]*id="copiar-texto"[^>]*>', html).group(0)
    assert " hidden" in botao and 'type="button"' in botao
    assert "A busca no Google Scholar foi feita" in _texto_da_pagina(html)
    js = cli.get("/static/metodologia.js")
    assert js.status_code == 200 and "navigator.clipboard" in js.text and "execCommand" in js.text and "getSelection" in js.text
    assert cli.get("/static/metodologia.css").status_code == 200


def test_texto_para_copiar_e_o_mesmo_texto_da_pagina(ctx):
    cli, _, _ = ctx
    html = cli.get("/metodologia").text
    import html as h
    copiavel = h.unescape(html.split('data-texto="', 1)[1].split('"', 1)[0])
    assert copiavel.startswith("Busca na literatura acadêmica")
    assert "Ressalvas sobre os dados" in copiavel and "<a " not in copiavel
    visivel = _texto_da_pagina(html)
    for trecho in re.findall(r"Dos \d+ achados, \d+ \([\d,]+%\)", copiavel):
        assert trecho in visivel


# ---------- sem dados ----------
def test_banco_vazio_responde_200_com_ressalvas_de_nada_ainda(tmp_path):
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    app, ctx = _app(vazio, tmp_path / "raw", tmp_path, nome="simulado")
    ctx.bases = ("IEEE", "ACM")
    r = TestClient(app).get("/metodologia")
    assert r.status_code == 200
    t = _texto_da_pagina(r.text)
    assert "Nada foi coletado ainda" in t and "Ressalvas sobre os dados" in t
    assert "Nenhuma busca acadêmica, busca web ou classificação registrada; nenhuma verificação humana feita" in t
    assert "simulados (teste, sem chamadas reais)" in t
    assert 'id="copiar-texto"' in r.text


def test_sem_banco_responde_503_sem_criar_o_arquivo(tmp_path):
    app, _ = _app(tmp_path / "naoexiste.db", tmp_path / "raw", tmp_path)
    r = TestClient(app).get("/metodologia")
    assert r.status_code == 503 and "ainda não existe" in r.text
    assert not (tmp_path / "naoexiste.db").exists()


def test_leitura_nao_escreve_no_banco(ctx):
    cli, copia, _ = ctx
    antes = copia.read_bytes()
    assert cli.get("/metodologia").status_code == 200
    assert copia.read_bytes() == antes
