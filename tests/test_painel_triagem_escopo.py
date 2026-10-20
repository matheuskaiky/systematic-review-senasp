"""Pagina Triagem de escopo (LLM) e o veredito do modelo nas telas de artigos: numeros conferidos no SQL, ocultacao por padrao dos
excluidos (a decisao humana sempre vence), filtros, paginacao, XSS, URLs perigosas, somente leitura e banco sem a tabela.
Todos os vereditos sao sinteticos, gravados em uma copia do banco de demonstracao."""
import hashlib
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401
from test_painel_acessibilidade import verificar  # noqa: E402

from adaptadores.leitura_sqlite import LeituraPainelSQLite  # noqa: E402
from adaptadores.repositorio_sqlite import RepositorioSQLite  # noqa: E402
from painel.rotas_extras.triagem_escopo import palavras_centrais  # noqa: E402

T_ALFA, T_BETA, T_XSS = "T alpha", "T beta", "<b>termo xss</b>"
COLUNAS = ("run_id", "chamada_id", "fonte", "item_id", "uf", "termos_consulta", "status", "status_bruto", "confianca", "categoria_motivo",
           "justificativa", "termo_gerador", "sinal_negativo", "dominio_tematico", "escopo_geografico", "tipo_documento", "valido",
           "prompt_versao", "criado_em")


def _linha(run, chamada, fonte, item, status, termos, uf="", valido=1, confianca="alta", cat=None, just="", gerador=None, sinal=None,
           dominio=None, escopo="brasil"):
    import json
    return (run, chamada, fonte, item, uf, json.dumps(termos), status, status, confianca, cat, just, gerador, sinal, dominio, escopo,
            "artigo_periodico", valido, "t1", "2026-10-16T12:00:00")


def _gravar(copia, sql, *a):
    c = sqlite3.connect(copia)
    c.execute(sql, a)
    c.commit()
    c.close()


def _sql(copia, sql, *a):
    c = sqlite3.connect(copia)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def _nova_execucao(c, run):
    c.execute("INSERT INTO execucoes(run_id, iniciado_em, comando, config_hash, config_json) VALUES (?, '2026-10-16T12:00:00', 'triar-escopo', 'h', '{}')", (run,))


def _nova_chamada(c, run, custo, chave):
    return c.execute("""INSERT INTO chamadas(run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em, sucesso, custo_usd)
                        VALUES (?, 'triagem_escopo', 'gemini', '{}', ?, '2026-10-16T12:00:00', 1, ?)""", (run, chave, custo)).lastrowid


def semear(copia):
    """Grava vereditos sinteticos para artigos e web; devolve os ids usados."""
    c = sqlite3.connect(copia)
    pend = [r[0] for r in c.execute("""SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id
                                       WHERE COALESCE(t.decisao,'pendente')='pendente' ORDER BY a.artigo_id""")]
    inc = c.execute("SELECT artigo_id FROM triagem WHERE decisao='incluir' ORDER BY artigo_id").fetchone()[0]
    exc = c.execute("SELECT artigo_id FROM triagem WHERE decisao='excluir' ORDER BY artigo_id").fetchone()[0]
    a, b, cq, f, g, h, i = pend[:7]
    titulos = {a: "Reconhecimento facial na polícia do Brasil", b: "Hospital municipal usa IA", cq: "Câmeras de hospital universitário",
               inc: "Hospital com reconhecimento facial", exc: "Agricultura de precisão", f: "Fazenda e agricultura",
               g: "<script>alert(3)</script> IA na agricultura", h: "Reconhecimento facial para diagnóstico médico", i: "Hospital central"}
    for k, t in titulos.items():
        c.execute("UPDATE artigos SET titulo=?, snippet='' WHERE artigo_id=?", (t, k))
    _nova_execucao(c, "ESC1")
    ch1, ch2 = _nova_chamada(c, "ESC1", 0.0123, "l1"), _nova_chamada(c, "ESC1", 0.0077, "l2")
    ab, tg = [T_ALFA, T_BETA], [T_ALFA]
    linhas = [
        _linha("ESC1", ch1, "artigo", a, "elegivel", ab),
        _linha("ESC1", ch1, "artigo", b, "excluido", tg, cat="FORA_SEGURANCA_PUBLICA", just="<img src=x onerror=alert(1)>", gerador=T_ALFA,
               sinal="hospital", dominio="saude", escopo="internacional"),
        _linha("ESC1", ch1, "artigo", cq, "quarentena", [T_BETA], confianca="media", cat="AMBIGUIDADE_LEXICAL", just="termo polissêmico",
               gerador=T_BETA, dominio="saude"),
        _linha("ESC1", ch2, "artigo", inc, "excluido", tg, cat="FORA_SEGURANCA_PUBLICA", just="hospital", gerador=T_ALFA, sinal="hospital",
               dominio="saude"),
        _linha("ESC1", ch2, "artigo", exc, "excluido", [T_BETA], cat="FORA_SEGURANCA_PUBLICA", just="agro", gerador=T_BETA,
               sinal="agricultura", dominio="agropecuaria_meio_ambiente", escopo="internacional"),
        _linha("ESC1", ch2, "artigo", f, "excluido", [T_BETA], valido=0, cat="RUIDO_WEB", just="falhou", sinal="agricultura"),
        _linha("ESC1", ch2, "artigo", g, "excluido", tg, cat="FORA_SEGURANCA_PUBLICA", just="agro", gerador=T_ALFA, sinal="agricultura",
               dominio="agropecuaria_meio_ambiente"),
        _linha("ESC1", ch2, "artigo", h, "excluido", ab + [T_XSS], cat="FORA_SEGURANCA_PUBLICA", just="diagnóstico", gerador=T_BETA,
               sinal="reconhecimento facial", dominio="saude"),
    ]
    web = c.execute("SELECT url_id, uf FROM resultados_web GROUP BY url_id, uf ORDER BY url_id, uf LIMIT 3").fetchall()
    c.execute("UPDATE urls SET url_original='javascript:alert(7)' WHERE url_id=?", (web[0][0],))
    c.execute("UPDATE resultados_web SET titulo='<script>alert(5)</script> pagina web' WHERE url_id=? AND uf=?", web[0])
    for k, (url_id, uf) in enumerate(web):
        linhas.append(_linha("ESC1", ch2, "web", url_id, ["excluido", "elegivel", "quarentena"][k], ["consulta web " + str(k % 2)], uf=uf,
                             cat="RUIDO_WEB" if k != 1 else None, gerador="consulta web 0" if k == 0 else None,
                             sinal="pagina" if k == 0 else None))
    c.executemany(f"INSERT INTO triagem_escopo({', '.join(COLUNAS)}) VALUES ({', '.join('?' * len(COLUNAS))})", linhas)
    c.commit()
    c.close()
    return {"a": a, "b": b, "c": cq, "d": inc, "e": exc, "f": f, "g": g, "h": h, "i": i, "web": web}


def segunda_execucao(copia, ids):
    """Uma execucao mais nova que reavalia so o artigo `a` (quarentena) e custou US$ 0,50."""
    c = sqlite3.connect(copia)
    _nova_execucao(c, "ESC2")
    ch = _nova_chamada(c, "ESC2", 0.5, "l3")
    c.execute(f"INSERT INTO triagem_escopo({', '.join(COLUNAS)}) VALUES ({', '.join('?' * len(COLUNAS))})",
              _linha("ESC2", ch, "artigo", ids["a"], "quarentena", [T_ALFA, T_BETA], confianca="baixa", cat="METODOLOGIA_IRRELEVANTE", just="mudou"))
    c.commit()
    c.close()


@pytest.fixture
def cenario(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    ids = semear(copia)
    return TestClient(_app(copia, raw, tmp_path)[0]), copia, ids, LeituraPainelSQLite(copia)


def texto(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def linha_de(html, rotulo, tag="th"):
    """Texto das celulas da linha da tabela cuja primeira celula contem `rotulo`."""
    for tr in re.findall(r"<tr>.*?</tr>", html, re.S):
        if rotulo in tr:
            return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
    raise AssertionError(f"linha com {rotulo!r} nao encontrada")


def ids_na_lista(html):
    return {int(x) for x in re.findall(r'<td[^>]*>\s*<a href="/literatura/artigos/(\d+)"', html)}


# ============================== resumo, ficha e operadores (numeros conferidos) ==============================
def test_resumo_do_leitor_bate_com_a_recontagem_direta_no_sql(cenario):
    _, copia, ids, leitura = cenario
    r = leitura.resumo_triagem_escopo("artigo")
    sql = dict(_sql(copia, "SELECT status, COUNT(*) FROM triagem_escopo WHERE fonte='artigo' AND valido=1 GROUP BY status"))
    assert r["por_status"] == {"elegivel": sql.get("elegivel", 0), "quarentena": sql.get("quarentena", 0), "excluido": sql.get("excluido", 0)}
    assert r["por_status"] == {"elegivel": 1, "quarentena": 1, "excluido": 5}                   # a, c, e (b d e g h) calculados a mao
    assert (r["n_total"], r["n_validos"], r["n_invalidos"]) == (8, 7, 1)
    assert r["por_categoria"] == {"FORA_SEGURANCA_PUBLICA": 5, "AMBIGUIDADE_LEXICAL": 1}
    assert r["por_escopo"] == {"brasil": 5, "internacional": 2} and r["por_dominio"]["saude"] == 4
    assert r["custo_usd"] == pytest.approx(0.02) and r["n_chamadas"] == 2
    assert leitura.resumo_triagem_escopo("web")["n_total"] == 3


def test_pagina_mostra_os_numeros_do_resumo_e_a_ficha_de_cada_termo(cenario):
    cli, _, _, _ = cenario
    r = cli.get("/triagem-escopo?fonte=artigo")
    assert r.status_code == 200
    t = texto(r.text)
    assert "itens avaliados" in t and re.search(r">\s*7\s*</span>\s*<span class=\"kpi-rotulo\">itens avaliados", r.text)
    assert "US$ 0,02" in t and "2 chamada(s)" in t
    # T alpha: a, b, d, g, h = 5 itens (1 elegivel, 4 excluidos): 20% / 0% / 80%, ruido 80%, internacional 1 de 5 = 20%
    alfa = linha_de(r.text, T_ALFA)
    assert alfa[:7] == [T_ALFA, "5", "20%", "0%", "80%", "80%", "fora de segurança pública"] and alfa[7] == "Saúde" and alfa[8] == "20%"
    # T beta: a, c, e, h = 4 itens validos (f e invalido): 25% / 25% / 50%, ruido 75%
    beta = linha_de(r.text, "T beta")
    assert beta[1:6] == ["4", "25%", "25%", "50%", "75%"] and "1 linha(s) com conferência falha" in beta[0]
    assert r.text.index(T_ALFA) < r.text.index(">T beta<")                                  # 80% antes de 75%


def test_operadores_negativos_seguro_arriscado_perigoso_e_palavra_central(cenario):
    cli, _, ids, leitura = cenario
    aval = __import__("dominio.refinamento_busca", fromlist=["x"]).avaliar_negativos(
        leitura.veredictos("artigo"), leitura.corpus_triagem_escopo("artigo"), palavras_centrais())
    por = {n["chave"]: n for n in aval["negativos"]}
    # hospital: contem b, c, d, i (4); colateral: c (quarentena) e d (incluido pelo humano) = 2 de 4 = 50%
    assert (por["hospital"]["n_no_corpus"], por["hospital"]["n_colateral"], por["hospital"]["veredito"]) == (4, 2, "perigoso")
    assert sorted(por["hospital"]["ids_colaterais"]) == sorted([ids["c"], ids["d"]]) and por["hospital"]["n_colateral_humano"] == 1
    # agricultura: e (excluido pelo humano, nao conta como bom), f (invalido), g: nenhum bom contem -> seguro
    assert (por["agricultura"]["n_colateral"], por["agricultura"]["veredito"], por["agricultura"]["n_sugerido_por"]) == (0, "seguro", 2)
    # palavra central do tema: perigoso mesmo se nenhum bom o contivesse
    assert por["reconhecimento facial"]["protegida"] and por["reconhecimento facial"]["veredito"] == "perigoso"
    t = cli.get("/triagem-escopo?fonte=artigo").text
    tabela = t[t.index('id="h-neg"'):t.index('id="lista"')]
    assert linha_de(tabela, '-"agricultura"')[1:4] == ["✔ Seguro", "2", "2"] and linha_de(tabela, '-"hospital"')[1] == "✕ Perigoso"
    assert "palavra central do tema" in t and "Sugestão do modelo, validada contra os itens bons; a decisão é sua" in t
    # o dano colateral lista os artigos bons com ligacao
    assert f'href="/literatura/artigos/{ids["c"]}"' in t and "incluído por você" in t
    # na ficha do termo, so entram operadores nao perigosos (ganho 2 em T alpha: b/d nao: hospital e perigoso; g sim)
    seguros_alfa = [x for x in aval["por_termo"][T_ALFA]]
    assert [x["chave"] for x in seguros_alfa] == ["agricultura"] and seguros_alfa[0]["ganho"] == 1 and seguros_alfa[0]["seguro_no_termo"]
    assert "+1/−0" in linha_de(t, T_ALFA)[9]


# ============================== lista: ocultacao por padrao, filtros e paginacao ==============================
def test_lista_padrao_mostra_elegivel_e_quarentena_e_conta_os_ocultos(cenario):
    cli, _, ids, _ = cenario
    h = cli.get("/triagem-escopo?fonte=artigo").text
    lista = h[h.index('id="h-lista"'):h.index('id="h-execs"')]
    assert ids_na_lista(lista) == {ids["a"], ids["c"], ids["f"]}            # f: excluido, mas a conferencia falhou (nao e oculto)
    assert re.search(r"<strong class=\"em-linha\">5</strong> item\(ns\) excluído\(s\) pelo modelo estão ocultos desta lista", lista)
    assert "nada foi apagado e a decisão é sua" in lista and 'href="/triagem-escopo?fonte=artigo&amp;status=todos#lista"' in lista
    todos = cli.get("/triagem-escopo?fonte=artigo&status=todos").text
    assert ids_na_lista(todos) == {ids[k] for k in "abcdefgh"} and "estão ocultos desta lista" not in todos
    so_exc = cli.get("/triagem-escopo?fonte=artigo&status=excluido").text
    assert ids_na_lista(so_exc) == {ids[k] for k in "bdefgh"}


def test_filtros_combinam_e_valores_desconhecidos_sao_ignorados(cenario):
    cli, _, ids, _ = cenario
    base = "/triagem-escopo?fonte=artigo&status=todos"
    assert ids_na_lista(cli.get(base + "&dominio_tematico=saude").text) == {ids[k] for k in "bcdh"}
    assert ids_na_lista(cli.get(base + "&dominio_tematico=saude&escopo_geografico=internacional").text) == {ids["b"]}
    assert ids_na_lista(cli.get(base + "&termo=" + T_BETA.replace(" ", "+")).text) == {ids[k] for k in "acefh"}
    assert ids_na_lista(cli.get(base + "&termo=T+beta&categoria_motivo=AMBIGUIDADE_LEXICAL").text) == {ids["c"]}
    assert ids_na_lista(cli.get(base + "&valido=0").text) == {ids["f"]}
    assert ids_na_lista(cli.get(base + "&confianca=media").text) == {ids["c"]}
    ignorado = cli.get(base + "&dominio_tematico=nao_existe&status=invalido&termo=nenhum&valido=x&confianca=zzz")
    assert ignorado.status_code == 200 and ids_na_lista(ignorado.text) == {ids[k] for k in "acf"}     # status invalido -> padrao


def test_paginacao_tamanho_maximo_e_404_em_pagina_invalida(cenario):
    cli, _, ids, leitura = cenario
    h = cli.get("/triagem-escopo?fonte=artigo&status=todos&tam=3").text
    assert len(ids_na_lista(h)) == 3 and "Página 1 de 3" in h and "p=2" in h
    assert len(ids_na_lista(cli.get("/triagem-escopo?fonte=artigo&status=todos&tam=3&p=3").text)) == 2
    assert "Não há itens nesta página" in cli.get("/triagem-escopo?fonte=artigo&status=todos&p=9").text
    assert leitura.itens_triagem_escopo("artigo", {}, 1, 100000)["por_pagina"] == 200
    assert cli.get("/triagem-escopo?tam=100000").status_code == 200
    for ruim in ("abc", "0", "-1", "1.5", "99999999999999999999"):
        r = cli.get(f"/triagem-escopo?p={ruim}")
        assert r.status_code == 404 and "Página inválida" in r.text, ruim


# ============================== seguranca ==============================
def test_texto_coletado_sai_escapado_e_url_perigosa_nao_vira_link(cenario):
    cli, _, ids, _ = cenario
    for rota in ("/triagem-escopo?fonte=artigo&status=todos", "/triagem-escopo?fonte=web&status=todos"):
        h = cli.get(rota).text
        for perigoso in ("<script>alert", "<img src=x", "<b>termo xss</b>"):
            assert perigoso not in h, (rota, perigoso)
    h = cli.get("/triagem-escopo?fonte=artigo&status=todos").text
    assert "&lt;img src=x onerror=alert(1)&gt;" in h and "&lt;b&gt;termo xss&lt;/b&gt;" in h and "&lt;script&gt;alert(3)&lt;/script&gt;" in h
    w = cli.get("/triagem-escopo?fonte=web&status=todos").text
    assert "&lt;script&gt;alert(5)&lt;/script&gt;" in w
    assert 'href="javascript:' not in w and 'href="#"' not in w.split('id="lista"')[1]        # nem como link neutro
    assert re.search(r'href="https?://[^"]+" rel="noopener noreferrer" target="_blank"', w)    # os demais links externos sao seguros
    assert not re.search(r"<script(?![^>]*\bsrc=)", h) and " style=" not in h


def test_a_pagina_nunca_escreve_no_banco(cenario):
    cli, copia, ids, _ = cenario
    antes = hashlib.sha256(copia.read_bytes()).hexdigest()
    for rota in ("/triagem-escopo", "/triagem-escopo?fonte=web", "/triagem-escopo?fonte=artigo&status=todos&termo=T+alpha&p=2",
                 "/triagem-escopo?run=ESC1", f"/literatura/artigos/{ids['b']}", "/literatura/artigos?llm=todos", "/literatura", "/literatura/triagem"):
        assert cli.get(rota, follow_redirects=True).status_code == 200, rota
    assert hashlib.sha256(copia.read_bytes()).hexdigest() == antes
    assert cli.post("/triagem-escopo").status_code in (404, 405)


# ============================== estados vazios e banco antigo ==============================
def test_estado_vazio_explica_o_piloto_e_mostra_o_comando_de_estimativa(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    r = TestClient(_app(copia, raw, tmp_path)[0]).get("/triagem-escopo")
    assert r.status_code == 200 and "Ainda não há triagem de escopo" in r.text and "piloto" in r.text
    assert "python main.py triar-escopo --fonte artigos --amostra 60 --estratificar --estimar" in r.text
    assert verificar(r.text) == []


def test_banco_antigo_sem_a_tabela_nao_quebra_nenhuma_tela(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "antigo.db"
    shutil.copy(banco, copia)
    _gravar(copia, "DROP TABLE triagem_escopo")
    cli = TestClient(_app(copia, raw, tmp_path)[0])
    i = _sql(copia, "SELECT MIN(artigo_id) FROM artigos")[0][0]
    for rota in ("/triagem-escopo", "/triagem-escopo?fonte=web", "/literatura", "/literatura/artigos", "/literatura/artigos?llm=excluido",
                 f"/literatura/artigos/{i}", "/literatura/triagem"):
        assert cli.get(rota, follow_redirects=True).status_code == 200, rota
    assert "Ainda não há triagem de escopo" in cli.get("/triagem-escopo").text


# ============================== selecao de execucao ==============================
def test_por_padrao_vale_a_avaliacao_mais_recente_de_cada_item_e_run_escolhe_uma_execucao(cenario):
    cli, copia, ids, leitura = cenario
    segunda_execucao(copia, ids)
    atual = {v["item_id"]: v for v in leitura.veredictos("artigo")}
    assert atual[ids["a"]]["status"] == "quarentena" and atual[ids["a"]]["run_id"] == "ESC2" and len(atual) == 8
    r = leitura.resumo_triagem_escopo("artigo")
    assert r["por_status"] == {"elegivel": 0, "quarentena": 2, "excluido": 5} and r["custo_usd"] == pytest.approx(0.0123 + 0.0077 + 0.5)
    h = cli.get("/triagem-escopo?fonte=artigo").text
    assert "avaliação <strong>mais recente de cada item</strong>" in h and "US$ 0,52" in h
    h1 = cli.get("/triagem-escopo?fonte=artigo&run=ESC1").text
    assert "só as respostas da execução" in h1 and "US$ 0,02" in h1
    assert leitura.resumo_triagem_escopo("artigo", "ESC1")["por_status"]["elegivel"] == 1
    h2 = cli.get("/triagem-escopo?fonte=artigo&run=ESC2").text
    assert "1 linha" not in h2 and leitura.resumo_triagem_escopo("artigo", "ESC2")["n_total"] == 1 and "US$ 0,50" in h2
    assert "só as respostas" not in cli.get("/triagem-escopo?run=nao-existe").text                # execucao desconhecida: ignorada
    runs = {e["run_id"]: e for e in leitura.execucoes_triagem_escopo()}
    assert runs["ESC1"]["n_linhas"] == 11 and runs["ESC2"]["n_linhas"] == 1 and runs["ESC2"]["custo_usd"] == pytest.approx(0.5)
    assert runs["ESC1"]["prompt_versao"] == "t1"


def test_acessibilidade_da_pagina_e_do_estado_vazio_de_filtros(cenario):
    cli, _, _, _ = cenario
    for rota in ("/triagem-escopo", "/triagem-escopo?fonte=web", "/triagem-escopo?fonte=artigo&status=excluido&termo=T+alpha", "/triagem-escopo?p=999"):
        h = cli.get(rota).text
        assert verificar(h) == [], rota
        assert h.count("<h1") == 1 and 'aria-current="page"' in h and "<th>" not in h
        assert not re.search(r"<th(?=[\s>])(?![^>]*scope=)", h)
        assert 'href="/static/triagem_escopo.css"' in h
    assert '<label>Status <select name="status">' in h


# ============================== artigos: ocultacao padrao, contagem, alternancia, fila, decisao humana ==============================
def test_lista_de_artigos_oculta_os_excluidos_pelo_modelo_mas_nunca_os_decididos_por_pessoas(cenario):
    cli, _, ids, leitura = cenario
    visiveis = ids_na_lista(cli.get("/literatura/artigos?" + "decisao=pendente").text)
    assert ids["a"] in visiveis and ids["c"] in visiveis and ids["f"] in visiveis                 # elegivel, quarentena, conferencia falhou
    assert not ({ids["b"], ids["g"], ids["h"]} & visiveis)                                        # pendentes excluidos pelo modelo: ocultos
    todos = ids_na_lista(cli.get("/literatura/artigos?llm=todos&decisao=pendente").text)
    assert {ids["b"], ids["g"], ids["h"]} <= todos
    # decisao humana vence: d (incluido) e e (excluido pela pessoa) aparecem mesmo com veredito `excluido`
    assert ids["d"] in ids_na_lista(cli.get("/literatura/artigos?decisao=incluir").text)
    assert ids["e"] in ids_na_lista(cli.get("/literatura/artigos?decisao=excluir").text)
    res = leitura.artigos({}, 1, 200)
    assert {ids["d"], ids["e"]} <= {a["artigo_id"] for a in res["itens"]}
    assert not ({ids["b"], ids["g"], ids["h"]} & {a["artigo_id"] for a in res["itens"]})
    assert res["ocultos_llm"] == 3 and res["total"] == leitura.artigos({"llm": "todos"}, 1, 200)["total"] - 3


def test_linha_de_contagem_e_alternancia_da_triagem_llm(cenario):
    cli, _, ids, leitura = cenario
    h = cli.get("/literatura/artigos").text
    assert re.search(r"<strong class=\"em-linha\">3</strong> artigo\(s\) excluído\(s\) pelo modelo estão ocultos desta lista", h)
    assert 'href="/literatura/artigos?llm=todos">Mostrar</a>' in h and "llm=excluido" in h
    assert '<select name="llm">' in h and "padrão (sem os excluídos pelo modelo)" in h and "apenas excluídos pelo modelo" in h
    # a linha respeita os outros filtros e some quando o filtro ja mostra os excluidos
    assert "estão ocultos" not in cli.get("/literatura/artigos?llm=todos").text
    assert "estão ocultos" not in cli.get("/literatura/artigos?llm=excluido").text
    assert ids_na_lista(cli.get("/literatura/artigos?llm=excluido").text) >= {ids["b"], ids["d"], ids["e"], ids["g"], ids["h"]}
    assert ids_na_lista(cli.get("/literatura/artigos?llm=elegivel").text) == {ids["a"]}
    assert ids_na_lista(cli.get("/literatura/artigos?llm=quarentena").text) == {ids["c"]}
    sem = ids_na_lista(cli.get("/literatura/artigos?llm=sem_avaliacao&decisao=pendente").text)
    assert ids["i"] in sem and not ({ids["a"], ids["b"], ids["c"]} & sem)
    h_dec = cli.get("/literatura/artigos?decisao=pendente").text
    assert re.search(r"<strong class=\"em-linha\">3</strong> artigo\(s\) excluído\(s\)", h_dec)                       # filtros combinam com a linha
    assert "estão ocultos" not in cli.get("/literatura/artigos?decisao=incluir").text
    assert leitura.artigos({"decisao": "incluir"}, 1, 50)["ocultos_llm"] == 0                      # incluidos nunca estao ocultos
    # paginacao e fila mantem a escolha
    h_todos = cli.get("/literatura/artigos?llm=todos&decisao=pendente").text
    assert 'href="/literatura/triagem?decisao=pendente&amp;llm=todos"' in h_todos
    assert 'href="/literatura/triagem?decisao=pendente"' in h_dec


def test_fila_de_triagem_oculta_por_padrao_e_mantem_a_escolha(cenario):
    cli, _, ids, leitura = cenario
    fila = set(leitura.ids_fila_triagem({}))
    assert {ids["a"], ids["c"], ids["f"]} <= fila and not ({ids["b"], ids["g"], ids["h"]} & fila)
    assert {ids["b"], ids["g"], ids["h"], ids["a"]} <= set(leitura.ids_fila_triagem({"llm": "todos"}))
    assert not ({ids["d"], ids["e"]} & fila)                                                         # decididos nao estao pendentes
    r = cli.get("/literatura/triagem", follow_redirects=False)
    assert r.status_code == 303 and "llm=" not in r.headers["location"]
    destino = int(re.search(r"/artigos/(\d+)", r.headers["location"]).group(1))
    assert destino not in (ids["b"], ids["g"], ids["h"])
    r = cli.get("/literatura/triagem?llm=excluido&decisao=pendente", follow_redirects=False)
    assert int(re.search(r"/artigos/(\d+)", r.headers["location"]).group(1)) in (ids["b"], ids["g"], ids["h"], ids["f"]) and "llm=excluido" in r.headers["location"]
    pg = cli.get(r.headers["location"]).text
    assert "fila de triagem" in pg and "llm=excluido" in pg                                         # a escolha acompanha a fila


def test_contagens_da_visao_de_literatura_e_de_relevancia_ignoram_os_ocultos(cenario):
    cli, copia, ids, leitura = cenario
    total = _sql(copia, "SELECT COUNT(*) FROM r_artigos")[0][0]
    d = leitura.literatura()
    assert d["n_artigos"] == total - 3 and d["n_ocultos_llm"] == 3
    tri = leitura.contagem_triagem()
    assert tri["total"] == total - 3 and tri["ocultos_llm"] == 3
    assert sum(leitura.contagem_relevancia().values()) == total - 3
    h = cli.get("/literatura").text
    assert re.search(r"<strong class=\"em-linha\">3</strong> artigo\(s\) excluído\(s\) pelo modelo estão ocultos destas contagens", h)
    assert f'<span class="kpi-valor">{total - 3}</span><span class="kpi-rotulo">Artigos únicos' in h.replace("\n", "")


def test_artigo_aberto_direto_mostra_o_cartao_com_aviso_de_excluido_pelo_modelo(cenario):
    cli, _, ids, _ = cenario
    h = cli.get(f"/literatura/artigos/{ids['b']}").text
    assert 'id="triagem-llm"' in h and "Excluído pelo modelo." in h and "quarentena temporária" in h
    assert "Nada foi apagado: você decide" in h and "llm=excluido" in h
    assert "hospital" in h and "Termo gerador do ruído" in h and T_ALFA in h and "&lt;img src=x onerror=alert(1)&gt;" in h and "<img src=x" not in h
    assert "fora de segurança pública" in h and verificar(h) == []
    # com decisao humana, o aviso diz que ela prevalece
    hd = cli.get(f"/literatura/artigos/{ids['d']}").text
    assert "a sua decisão prevalece" in hd
    # quarentena e sem avaliacao
    assert "Triagem LLM: quarentena" in cli.get(f"/literatura/artigos/{ids['c']}").text
    assert "ainda não foi avaliado pelo modelo" in cli.get(f"/literatura/artigos/{ids['i']}").text


def test_selo_do_veredito_na_lista_de_artigos(cenario):
    cli, _, ids, _ = cenario

    def linha(rota, i):
        return re.search(rf'<tr><td><a href="/literatura/artigos/{i}">.*?</tr>', cli.get(rota).text, re.S).group(0)

    assert "<th>Triagem LLM</th>" in cli.get("/literatura/artigos?llm=elegivel").text
    linha_a = linha("/literatura/artigos?llm=elegivel", ids["a"])
    linha_b = linha("/literatura/artigos?llm=excluido&decisao=pendente", ids["b"])
    linha_i = linha("/literatura/artigos?llm=sem_avaliacao&q=Hospital+central", ids["i"])
    assert "Elegível" in linha_a and "✔" in linha_a
    assert "Excluído pelo modelo" in linha_b and "✕" in linha_b and "fora de segurança pública" in linha_b
    assert "sem avaliação" in linha_i
    assert verificar(cli.get("/literatura/artigos?llm=todos").text) == []
