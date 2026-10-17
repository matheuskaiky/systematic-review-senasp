"""Painel: rotas, seguranca (XSS, CSRF, somente leitura, CSP), revisao com desfazer, backup e destaque da evidencia."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

import painel_demo
from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dados_metricas import construir_classificacao_mista
from painel import rotulos
from painel.app import Contexto, criar_app
from painel import mapa_ufs


def _app(banco, raw, tmp_path, somente_leitura=False, nome="demo"):
    ctx = Contexto(banco=nome, nome_banco=banco.name, somente_leitura=somente_leitura, pasta_backup=tmp_path / "backups",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver", "127.0.0.1", "localhost"))
    return criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(raw), ctx), ctx


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("demo")
    return painel_demo.construir(pasta), pasta / "raw_demo"


@pytest.fixture
def cliente_demo(demo, tmp_path):
    """Copia o banco de demonstracao para cada teste: os que gravam nao contaminam os outros."""
    import shutil
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, ctx = _app(copia, raw, tmp_path)
    return TestClient(app), ctx, copia


def _csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _estado(copia, i):
    c = sqlite3.connect(copia)
    return c.execute("SELECT verificado, status_final, verificado_por FROM achados WHERE achado_id=?", (i,)).fetchone()


# ============================== rotas ==============================
def test_todas_as_paginas_respondem_200_na_demo(cliente_demo):
    cli, _, _ = cliente_demo
    for rota in ("/", "/estados", "/estados/SP", "/estados/AC", "/achados", "/achados?uf=SP&verificacao=pendente&p=2", "/achados?q=reconhecimento"):
        r = cli.get(rota)
        assert r.status_code == 200, rota
        assert "DEMONSTRAÇÃO (dados fictícios)" in r.text
    assert cli.get("/revisao/achados", follow_redirects=False).status_code == 303


def test_paginas_respondem_em_banco_vazio_e_simulado(tmp_path):
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    cli = TestClient(_app(vazio, tmp_path / "raw", tmp_path, nome="simulado")[0])
    for rota in ("/", "/estados", "/estados/PI", "/achados", "/revisao/achados"):
        assert cli.get(rota).status_code == 200, rota
    assert "Ainda não há achados" in cli.get("/revisao/achados").text or "Nenhum achado" in cli.get("/achados").text
    sem = TestClient(_app(tmp_path / "naoexiste.db", tmp_path / "raw", tmp_path)[0])
    r = sem.get("/")
    assert r.status_code == 503 and "ainda não existe" in r.text and "python main.py pipeline-uf" in r.text
    assert not (tmp_path / "naoexiste.db").exists()


def test_paginas_amigaveis_para_ids_e_ufs_invalidos(cliente_demo):
    cli, _, _ = cliente_demo
    for rota in ("/achados/99999999", "/achados/abc", "/estados/ZZ", "/rota-que-nao-existe"):
        r = cli.get(rota)
        assert r.status_code == 404 and "Voltar à visão geral" in r.text, rota


def test_filtros_combinam_e_paginacao(cliente_demo, demo):
    cli, _, _ = cliente_demo
    todos = cli.get("/achados").text
    n_total = int(re.search(r"<strong>([\d.]+)</strong> achado", todos).group(1).replace(".", ""))
    assert n_total > 100 and "Página 1 de" in todos
    so_sp = int(re.search(r"<strong>([\d.]+)</strong> achado", cli.get("/achados?uf=SP").text).group(1))
    sp_pend = int(re.search(r"<strong>([\d.]+)</strong> achado", cli.get("/achados?uf=SP&verificacao=pendente").text).group(1))
    assert 0 < sp_pend <= so_sp < n_total
    assert "Nenhum achado com estes filtros" in cli.get("/achados?uf=AC").text


def test_visao_geral_mostra_numeros_e_nao_conta_execucao_fora_do_relatorio(cliente_demo):
    cli, _, copia = cliente_demo
    c = sqlite3.connect(copia)
    esperado = c.execute("SELECT COUNT(*) FROM r_achados").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM achados").fetchone()[0]
    assert esperado < total                                           # a execucao de comparacao esta fora do relatorio
    html = cli.get("/").text
    assert f'<span class="kpi-valor">{esperado}</span><span class="kpi-rotulo">Achados</span>' in html.replace("\n", "")


# ============================== evidencia no texto ==============================
def test_evidencia_que_confere_tem_destaque_e_a_que_nao_confere_mostra_o_aviso(cliente_demo):
    cli, _, copia = cliente_demo
    c = sqlite3.connect(copia)
    ok = c.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                      WHERE a.evidencia_confere=1 AND k.origem_texto='pagina' LIMIT 1""").fetchone()[0]
    ruim = c.execute("SELECT achado_id FROM achados WHERE evidencia_confere=0 LIMIT 1").fetchone()[0]
    h_ok = cli.get(f"/achados/{ok}").text
    m = re.search(r'<mark id="evidencia">(.+?)</mark>', h_ok, re.S)
    assert m and "Evidência confere" in h_ok and "Evidência não localizada no texto enviado" not in h_ok
    h_ruim = cli.get(f"/achados/{ruim}").text
    assert "Evidência não localizada no texto enviado" in h_ruim and "Evidência confere" not in h_ruim.split("Evidência no texto")[1]


def test_todo_achado_da_demo_com_evidencia_ok_tem_destaque(cliente_demo):
    cli, _, copia = cliente_demo
    c = sqlite3.connect(copia)
    ids = [r[0] for r in c.execute("SELECT achado_id FROM achados WHERE evidencia_confere=1 ORDER BY achado_id LIMIT 40")]
    for i in ids:
        assert '<mark id="evidencia">' in cli.get(f"/achados/{i}").text, i


def test_texto_ausente_no_disco_mostra_aviso_sem_quebrar(cliente_demo, demo):
    cli, _, copia = cliente_demo
    c = sqlite3.connect(copia)
    i, path = c.execute("""SELECT a.achado_id, p.texto_path FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                           JOIN paginas p ON p.pagina_id=k.pagina_id WHERE k.origem_texto='pagina' LIMIT 1""").fetchone()
    (demo[1] / path).rename(demo[1] / (path + ".bak"))
    try:
        r = cli.get(f"/achados/{i}")
        assert r.status_code == 200 and "não foi encontrado em data/raw" in r.text
    finally:
        (demo[1] / (path + ".bak")).rename(demo[1] / path)


# ============================== seguranca ==============================
PAYLOADS = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>']


def test_conteudo_coletado_e_escapado_em_todas_as_paginas(tmp_path):
    repo, _ = construir_classificacao_mista(tmp_path)
    banco = tmp_path / "cl.db"
    i = repo.conn.execute("SELECT achado_id FROM achados ORDER BY achado_id").fetchone()[0]
    for n, p in enumerate(PAYLOADS):
        repo.conn.execute("UPDATE achados SET evidencia=?, fornecedor=?, observacao=? WHERE achado_id=?",
                          (p, p, p, i + n))
    repo.conn.execute("UPDATE resultados_web SET titulo=?, snippet=?", (PAYLOADS[0], PAYLOADS[1]))
    repo.conn.execute("UPDATE classificacoes SET resposta_texto=?", (PAYLOADS[0],))
    repo.conn.commit()
    repo.fechar()
    cli = TestClient(_app(banco, tmp_path / "raw", tmp_path)[0])
    paginas = ["/", "/estados", "/estados/PI", "/achados", "/achados?q=%3Cscript", f"/achados/{i}", f"/achados/{i + 1}", f"/achados/{i}?completo=1"]
    for rota in paginas:
        r = cli.get(rota)
        assert r.status_code == 200, rota
        assert "<script>alert(1)" not in r.text and '"><img' not in r.text and "onerror=alert" not in r.text.replace("&#34;&gt;&lt;img src=x onerror=alert(1)&gt;", ""), rota
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in cli.get(f"/achados/{i}").text


def test_cabecalhos_de_seguranca_e_sem_script_inline(cliente_demo):
    cli, _, _ = cliente_demo
    r = cli.get("/")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "style-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    for rota in ("/", "/estados", "/achados", "/revisao/achados"):
        html = cli.get(rota, follow_redirects=True).text
        assert not re.search(r"<script(?![^>]*\bsrc=)", html) and ' style="' not in html and "onclick=" not in html, rota
        assert 'src="http' not in html and "<link" not in html.replace('href="/static/painel.css"', "").replace('<link rel="stylesheet" >', ""), rota
    assert "cdn" not in cli.get("/").text.lower()


def test_links_externos_tem_noopener(cliente_demo):
    cli, _, copia = cliente_demo
    i = sqlite3.connect(copia).execute("SELECT achado_id FROM achados LIMIT 1").fetchone()[0]
    html = cli.get(f"/achados/{i}").text
    assert 'target="_blank" rel="noopener noreferrer"' in html


def test_post_sem_token_ou_com_token_errado_e_recusado(cliente_demo):
    cli, _, copia = cliente_demo
    i = sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado=0 LIMIT 1").fetchone()[0]
    cli.get(f"/achados/{i}")
    for corpo in ({"status_final": "em_uso", "revisor": "Ana"}, {"status_final": "em_uso", "revisor": "Ana", "csrf": "errado"}):
        r = cli.post(f"/achados/{i}/verificar", data=corpo)
        assert r.status_code == 403 and "Formulário recusado" in r.text
    assert _estado(copia, i)[0] == 0
    assert cli.post(f"/achados/{i}/desfazer", data={}).status_code == 403


def test_cookies_sao_samesite_strict_e_httponly(cliente_demo):
    cli, _, _ = cliente_demo
    r = cli.get("/")
    cookie = r.headers["set-cookie"].lower()
    assert "samesite=strict" in cookie and "httponly" in cookie


def test_modo_somente_leitura_esconde_formularios_e_rejeita_post(demo, tmp_path):
    import shutil
    banco, raw = demo
    copia = tmp_path / "ro.db"
    shutil.copy(banco, copia)
    cli = TestClient(_app(copia, raw, tmp_path, somente_leitura=True)[0])
    i = sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado=0 LIMIT 1").fetchone()[0]
    html = cli.get(f"/achados/{i}").text
    assert "somente leitura" in html and "<form method=\"post\"" not in html and 'name="status_final"' not in html
    r = cli.post(f"/achados/{i}/verificar", data={"status_final": "em_uso", "revisor": "Ana", "csrf": "x"})
    assert r.status_code == 403 and "somente leitura" in r.text.lower()
    assert _estado(copia, i)[0] == 0
    assert not (tmp_path / "backups").exists()


# ============================== revisao ==============================
def _decidir(cli, i, status, revisor="Ana", fila=False, **extra):
    pagina = cli.get(f"/achados/{i}" + ("?fila=1" if fila else ""))
    return cli.post(f"/achados/{i}/verificar" + ("?fila=1" if fila else ""),
                    data={"status_final": status, "revisor": revisor, "observacao": "", "csrf": _csrf(pagina.text), **extra},
                    follow_redirects=False)


def test_verificar_grava_redireciona_e_atualiza_secretarias_e_resumo(cliente_demo):
    cli, _, copia = cliente_demo
    c = sqlite3.connect(copia)
    i = c.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                     WHERE a.verificado=0 AND k.run_id=(SELECT run_id FROM execucoes WHERE comando='classificar' AND no_relatorio=1)
                     ORDER BY a.achado_id LIMIT 1""").fetchone()[0]
    antes = c.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0]
    r = _decidir(cli, i, "piloto", revisor="Maria Silva")
    assert r.status_code == 303 and r.headers["location"] == f"/achados/{i}?ok={i}"
    assert _estado(copia, i) == (1, "piloto", "Maria Silva")
    assert sqlite3.connect(copia).execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0] == antes + 1
    assert "Desfazer" in cli.get(r.headers["location"]).text
    assert "Maria Silva" in cli.get(f"/achados/{i}").text          # o nome fica em cookie e preenche o campo


def test_status_invalido_ou_sem_revisor_nao_grava_e_explica(cliente_demo):
    cli, _, copia = cliente_demo
    i = sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado=0 LIMIT 1").fetchone()[0]
    r = _decidir(cli, i, "inventado")
    assert r.status_code == 400 and "status_final" in r.text
    r = _decidir(cli, i, "em_uso", revisor="   ")
    assert r.status_code == 400 and "revisor" in r.text
    assert _estado(copia, i)[0] == 0


def test_desfazer_restaura_o_estado_anterior(cliente_demo):
    cli, _, copia = cliente_demo
    i = sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado=0 LIMIT 1").fetchone()[0]
    _decidir(cli, i, "em_uso")
    assert _estado(copia, i)[0] == 1
    pag = cli.get(f"/achados/{i}")
    r = cli.post(f"/achados/{i}/desfazer", data={"csrf": _csrf(pag.text)}, follow_redirects=False)
    assert r.status_code == 303 and _estado(copia, i) == (0, None, None)
    r = cli.post(f"/achados/{i}/desfazer", data={"csrf": _csrf(pag.text)})
    assert r.status_code == 400 and "Nada a desfazer" in r.text


def test_copia_de_seguranca_uma_vez_por_sessao_antes_da_primeira_escrita(cliente_demo, tmp_path):
    cli, ctx, copia = cliente_demo
    ids = [r[0] for r in sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado=0 LIMIT 3")]
    assert not ctx.pasta_backup.exists()
    _decidir(cli, ids[0], "em_uso")
    feitas = list(ctx.pasta_backup.glob("*.db"))
    assert len(feitas) == 1
    assert sqlite3.connect(feitas[0]).execute("SELECT verificado FROM achados WHERE achado_id=?", (ids[0],)).fetchone()[0] == 0   # antes da decisao
    _decidir(cli, ids[1], "piloto")
    assert len(list(ctx.pasta_backup.glob("*.db"))) == 1


def test_fila_anda_ate_acabar_e_mostra_o_progresso(demo, tmp_path):
    repo, _ = construir_classificacao_mista(tmp_path)
    banco = tmp_path / "cl.db"
    repo.fechar()
    cli = TestClient(_app(banco, tmp_path / "raw", tmp_path)[0])
    destino = cli.get("/revisao/achados", follow_redirects=False).headers["location"]
    n = 0
    while destino.startswith("/achados/") and n < 50:
        i = int(re.search(r"/achados/(\d+)", destino).group(1))
        pag = cli.get(destino)
        assert "fila de revisão" in pag.text and "pendente(s)" in pag.text
        r = cli.post(f"/achados/{i}/verificar?fila=1", data={"status_final": "em_uso", "revisor": "Ana", "observacao": "", "csrf": _csrf(pag.text)}, follow_redirects=False)
        assert r.status_code == 303
        destino = r.headers["location"]
        n += 1
    assert 0 < n < 50
    final = cli.get("/revisao/achados")
    assert final.status_code == 200 and "Tudo revisado" in final.text


def test_pular_nao_muda_nada_e_vai_para_o_proximo_da_fila(cliente_demo):
    cli, _, copia = cliente_demo
    r = cli.get("/revisao/achados", follow_redirects=False)
    primeiro = int(re.search(r"/achados/(\d+)", r.headers["location"]).group(1))
    pag = cli.get(r.headers["location"]).text
    m = re.search(r'href="/achados/(\d+)\?[^"]*" data-tecla="n"', pag)
    assert m and int(m.group(1)) != primeiro and _estado(copia, primeiro)[0] == 0


# ============================== rotulos, mapa, arquitetura ==============================
def test_todo_codigo_do_vocabulario_tem_rotulo():
    assert set(V.TECNOLOGIAS) <= set(rotulos.TECNOLOGIAS)
    assert set(V.STATUS) | set(V.STATUS_FINAL_EXTRA) <= set(rotulos.STATUS)
    assert set(V.CONFIANCA) <= set(rotulos.CONFIANCA)
    assert {"pagina", "snippet"} <= set(rotulos.ORIGEM_TEXTO)
    assert {"dominio_excluido", "nao_oficial", "prefiltro_palavras", "limite_por_uf"} <= set(rotulos.MOTIVOS_DESCARTE)
    assert rotulos.motivo_falha("tipo_nao_suportado:application/zip").startswith("Tipo de arquivo não suportado")
    assert rotulos.motivo_falha("texto_insuficiente") == "Texto insuficiente na página"


def test_mapa_tem_as_27_ufs_com_contorno_e_rotulo_dentro_da_area():
    import re
    assert set(mapa_ufs.CAMINHOS) == set(C.UFS) == set(mapa_ufs.ROTULOS) and len(mapa_ufs.CAMINHOS) == 27
    x0, y0, larg, alt = (float(v) for v in mapa_ufs.VIEWBOX.split())
    for uf, caminho in mapa_ufs.CAMINHOS.items():
        assert caminho.startswith("M") and caminho.rstrip().endswith("Z"), uf
        pares = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", caminho)]
        assert len(pares) >= 3 and all(x0 <= x <= x0 + larg and y0 <= y <= y0 + alt for x, y in pares), uf
        x, y, fonte, ancora, guia = mapa_ufs.ROTULOS[uf]
        assert ancora in ("middle", "start") and (guia is None) == (ancora == "middle"), uf
        assert x0 <= x <= x0 + larg and y0 <= y <= y0 + alt and 6 <= fonte <= 24, uf
    # geografia: o DF fica dentro da caixa de Goias, e o RS abaixo de SC
    def caixa(uf):
        p = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", mapa_ufs.CAMINHOS[uf])]
        return min(x for x, _ in p), min(y for _, y in p), max(x for x, _ in p), max(y for _, y in p)
    df, go = caixa("DF"), caixa("GO")
    assert go[0] <= df[0] and df[2] <= go[2] + 40 and go[1] <= df[1] <= go[3]
    assert caixa("RS")[1] > caixa("SC")[1] and caixa("AM")[0] < caixa("PA")[0]


def test_mapa_pinta_cada_uf_pela_classe_e_liga_para_a_pagina_da_uf():
    from painel.graficos import mapa_do_brasil
    svg = mapa_do_brasil({"PI": ("confirmado", "2 achados"), "CE": ("classificado", "1 achado")}, "T", "D")
    assert svg.count("<path") == 27 and svg.count('<a href="/estados/') == 27
    assert 'href="/estados/PI"><g class="bloco confirmado"' in svg and 'href="/estados/CE"><g class="bloco classificado"' in svg
    assert 'href="/estados/SP"><g class="bloco sem-dados"' in svg
    assert " style=" not in svg and "<script" not in svg


def test_mapa_svg_e_bem_formado_e_acessivel(cliente_demo):
    import xml.etree.ElementTree as ET
    from painel.graficos import barra_empilhada, barras_horizontais, mapa_do_brasil
    for svg in (mapa_do_brasil({"PI": ("confirmado", "x")}, "T", "D"), barras_horizontais([("a", 3), ("b", 0)], "T", "D"),
                barra_empilhada([(1, "be-conf", "x")], 4, "d")):
        raiz = ET.fromstring(svg)
        assert raiz.tag.endswith("svg")
    assert "<title" in mapa_do_brasil({}, "T", "D") and "<desc" in barras_horizontais([("a", 1)], "T", "D")


def test_painel_respeita_a_regra_de_dependencias():
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent
    proibidos = re.compile(r"^\s*(from|import)\s+(adaptadores|composicao|sqlite3|requests)\b|os\.environ|getenv", re.M)
    ruins = [str(p) for p in (raiz / "painel").rglob("*.py") if proibidos.search(p.read_text(encoding="utf-8"))]
    assert not ruins, ruins
    for pasta in ("dominio", "aplicacao", "adaptadores", "infra"):
        assert not [p for p in (raiz / pasta).rglob("*.py") if re.search(r"^\s*(from|import)\s+painel\b", p.read_text(encoding="utf-8"), re.M)]


def test_demo_e_deterministica_e_nao_toca_nos_outros_bancos(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    pa, pb = painel_demo.construir(a), painel_demo.construir(b)
    consulta = "SELECT uf, tecnologia, status_reportado, evidencia, confianca, evidencia_confere FROM achados ORDER BY achado_id"
    assert sqlite3.connect(pa).execute(consulta).fetchall() == sqlite3.connect(pb).execute(consulta).fetchall()
    assert sorted(p.name for p in a.iterdir()) == ["demo.db", "raw_demo"]


def test_demo_cobre_todos_os_casos_de_tela(demo):
    c = sqlite3.connect(demo[0])
    um = lambda q: c.execute(q).fetchone()[0]
    assert um("SELECT COUNT(DISTINCT status_reportado) FROM achados") == 6 and um("SELECT COUNT(DISTINCT confianca) FROM achados") == 3
    assert um("SELECT COUNT(DISTINCT tecnologia) FROM achados") == 6 and um("SELECT COUNT(DISTINCT uf) FROM achados") < 27
    assert um("SELECT COUNT(*) FROM achados WHERE evidencia_confere=0") > 0 and um("SELECT COUNT(*) FROM classificacoes WHERE origem_texto='snippet'") > 0
    assert {r[0] for r in c.execute("SELECT status FROM execucoes")} >= {"concluida", "interrompida", "falhou"}
    assert um("SELECT COUNT(*) FROM chamadas WHERE sucesso=0") > 0 and um("SELECT COUNT(DISTINCT motivo) FROM selecao_download WHERE selecionada=0") >= 2
    assert um("SELECT COUNT(*) FROM achados WHERE verificado=1") > 0 and um("SELECT COUNT(*) FROM achados WHERE verificado=0") > 0
    assert um("SELECT COUNT(*) FROM execucoes WHERE no_relatorio=0") >= 2
    assert not re.search(r"\.gov\.br|\.com\.br", " ".join(r[0] for r in c.execute("SELECT url_original FROM urls")).replace("exemplo.gov.br", ""))


def _app_demo_com_solucoes(demo, tmp_path):
    """O painel sobre a demonstracao com a lista de solucoes da PROPRIA demonstracao (a mesma que `painel --demo` usa)."""
    banco, raw = demo
    app, ctx = _app(banco, raw, tmp_path)
    ctx.solucoes_conhecidas = painel_demo.SOLUCOES_CONHECIDAS_DEMO
    return TestClient(app), ctx


def test_demo_cobre_os_nomes_de_solucao_e_a_reclassificacao(demo):
    """(a) nome_solucao em boa parte dos achados, com grafias diferentes do mesmo sistema e um nome descartado; (d) texto completo e snippet;
    (e) uma pagina reclassificada, com a classificacao antiga substituida pela mais recente."""
    c = sqlite3.connect(demo[0])
    um = lambda q: c.execute(q).fetchone()[0]
    total = um("SELECT COUNT(*) FROM achados")
    nomeados = um("SELECT COUNT(*) FROM achados WHERE TRIM(COALESCE(nome_solucao, '')) <> ''")
    assert nomeados >= 0.12 * total, (nomeados, total)
    nomes = {r[0] for r in c.execute("SELECT DISTINCT nome_solucao FROM achados WHERE nome_solucao IS NOT NULL")}
    assert {"Rosto Seguro", "Rosto-Seguro"} <= nomes and {"Placa Atenta", "P. Atenta"} <= nomes     # duas grafias do mesmo sistema
    assert um("SELECT COALESCE(SUM(valor), 0) FROM metricas_run WHERE chave='classificacao_nome_solucao_descartado'") >= 1   # nome inventado, descartado
    assert um("SELECT COUNT(*) FROM classificacoes WHERE origem_texto='pagina'") > 0 and um("SELECT COUNT(*) FROM classificacoes WHERE origem_texto='snippet'") > 0
    substituidos = um("""SELECT COUNT(*) FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                         JOIN execucoes e ON e.run_id=k.run_id WHERE e.no_relatorio=1
                         AND a.classificacao_id NOT IN (SELECT classificacao_id FROM r_classificacoes)""")
    assert substituidos >= 1
    assert um("SELECT COUNT(DISTINCT prompt_versao) FROM classificacoes") >= 2          # o prompt mudou entre a classificacao antiga e a nova


def test_demo_cobre_as_duas_razoes_de_robots_e_as_paginas_nao_verificaveis(demo):
    """(c) bloqueio pelo robots.txt (Disallow, status 200) e robots.txt indisponivel (503, varias tentativas), texto insuficiente e 404."""
    c = sqlite3.connect(demo[0])
    um = lambda q: c.execute(q).fetchone()[0]
    assert um("""SELECT COUNT(*) FROM chamadas WHERE erro='bloqueado_por_robots' AND json_extract(extras_json, '$.robots_status')=200
                 AND json_extract(extras_json, '$.robots_inacessivel')=0""") >= 1
    assert um("""SELECT COUNT(*) FROM chamadas WHERE erro='robots_inacessivel' AND json_extract(extras_json, '$.robots_status')=503
                 AND json_extract(extras_json, '$.robots_inacessivel')=1 AND json_extract(extras_json, '$.robots_tentativas')>1""") >= 1
    assert um("SELECT COUNT(*) FROM paginas WHERE motivo_falha='texto_insuficiente'") >= 1
    assert um("SELECT COUNT(*) FROM chamadas WHERE etapa='download' AND http_status=404") >= 1


def test_demo_mostra_as_telas_novas_com_dados(demo, tmp_path):
    cli, _ = _app_demo_com_solucoes(demo, tmp_path)
    operacao = cli.get("/analises?secao=operacao").text
    assert 'id="nao_verificaveis"' in operacao and "robots" in operacao.lower()
    for resultado in ("robots_proibido", "robots_inacessivel"):
        pagina = cli.get(f"/chamadas?resultado={resultado}")
        assert pagina.status_code == 200 and "Nenhuma chamada com estes filtros" not in pagina.text, resultado
    c = sqlite3.connect(demo[0])
    antigo = c.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                          JOIN execucoes e ON e.run_id=k.run_id WHERE e.no_relatorio=1
                          AND a.classificacao_id NOT IN (SELECT classificacao_id FROM r_classificacoes) ORDER BY a.achado_id LIMIT 1""").fetchone()[0]
    assert "substituído por uma classificação mais recente" in cli.get(f"/achados/{antigo}").text
    assert "Solução nomeada" in cli.get("/achados?solucao=nomeada").text
    snippet = cli.get("/achados?origem=snippet")
    assert snippet.status_code == 200 and "Somente snippet" in snippet.text


def test_demo_solucoes_mostra_os_quatro_vereditos_e_a_busca_no_texto_acha_os_nomes(demo, tmp_path):
    """(b) /solucoes na demonstracao: uma solucao em cada veredito, todas com nomes ficticios que existem nos dados da demonstracao."""
    from dominio import solucoes as dom
    cli, ctx = _app_demo_com_solucoes(demo, tmp_path)
    r = cli.get("/solucoes")
    assert r.status_code == 200 and "DEMONSTRAÇÃO (dados fictícios)" in r.text
    for situacao in dom.SITUACOES:
        assert dom.rotulo_da_situacao(situacao) in r.text, situacao
    esperado = {"Rosto Seguro": dom.EM_ACHADOS, "Placa Atenta": dom.EM_ACHADOS, "Guardião Digital": dom.PAGINA_SEM_ACHADO,
                "Vigia Nuvem": dom.SO_NOS_RESULTADOS, "Sentinela Norte": dom.NAO_APARECEU}
    assert {s.nome for s in ctx.solucoes_conhecidas} == set(esperado)
    for nome, situacao in esperado.items():
        assert f"{nome} <small>" in r.text and dom.rotulo_da_situacao(situacao) in r.text
    for q in ("Rosto Seguro", "Guardião Digital", "P. Atenta"):
        b = cli.get("/buscar-texto", params={"q": q, "inteira": 1})
        assert b.status_code == 200 and "<mark>" in b.text and "Nenhuma página baixada cita" not in b.text, q
    assert "Nenhuma página baixada cita" in cli.get("/buscar-texto", params={"q": "Sentinela Norte", "inteira": 1}).text
    assert "Nenhuma solução conhecida foi informada" not in r.text


def test_painel_demo_usa_a_lista_de_solucoes_da_demonstracao_e_o_real_usa_a_do_pesquisador(ambiente_cli, monkeypatch):
    """`painel --demo` usa `painel_demo.SOLUCOES_CONHECIDAS_DEMO`; sem --demo vale `config/solucoes_conhecidas.py`. Sem subir servidor."""
    import types
    import uvicorn
    import main
    import painel.app as painel_app
    from composicao import Fabrica
    from config.solucoes_conhecidas import SOLUCOES_CONHECIDAS
    capturado = {}
    criar_original = painel_app.criar_app
    monkeypatch.setattr(painel_app, "criar_app", lambda leitura, fab, bruto, contexto: capturado.update(contexto=contexto) or criar_original(leitura, fab, bruto, contexto))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: capturado.update(app=app))
    painel_demo.construir(main.S.DATA_DIR)
    a = types.SimpleNamespace(host="127.0.0.1", porta=8000, somente_leitura=True, demo=True, simulado=False)
    main.abrir_painel(a, Fabrica(demo=True))
    assert capturado["contexto"].banco == "demo" and capturado["contexto"].solucoes_conhecidas == tuple(painel_demo.SOLUCOES_CONHECIDAS_DEMO)
    cli = TestClient(capturado["app"], base_url="http://127.0.0.1")
    r = cli.get("/solucoes")
    assert r.status_code == 200 and "Rosto Seguro" in r.text and "BO Fácil" not in r.text
    a = types.SimpleNamespace(host="127.0.0.1", porta=8000, somente_leitura=True, demo=False, simulado=True)
    main.abrir_painel(a, Fabrica(simulado=True))
    assert capturado["contexto"].banco == "simulado" and capturado["contexto"].solucoes_conhecidas == tuple(SOLUCOES_CONHECIDAS)


def test_painel_demo_do_cli_gera_o_banco_com_as_solucoes(ambiente_cli, monkeypatch, capsys):
    import main
    monkeypatch.setattr("sys.argv", ["main.py", "painel-demo"])
    main.main()
    assert "demo.db" in capsys.readouterr().out and (main.S.DATA_DIR / "demo.db").exists()


def test_bruto_local_recusa_caminho_fora_da_raiz(tmp_path):
    raiz = tmp_path / "raw"
    raiz.mkdir()
    (tmp_path / "segredo.txt").write_text("x")
    (raiz / "ok.txt").write_text("ok")
    b = BrutoLocal(raiz)
    assert b.ler("ok.txt") == b"ok"
    for ruim in ("../segredo.txt", str(tmp_path / "segredo.txt")):
        with pytest.raises(ValueError):
            b.ler(ruim)
