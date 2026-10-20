"""Etapa 2 do painel: destaque da solução nomeada (selo, filtro `solucao=nomeada`), origem do texto (completo ou só snippet), links de
aprofundamento de /solucoes até /buscar-texto e /achados, marca de TODA ocorrência na busca no texto e as duas razões de bloqueio pelo
robots.txt (proibido pelo site x bloqueio preventivo) em /analises, /chamadas e /chamadas/{id}. Tudo sobre o banco de demonstração
(com linhas semeadas). Nenhum teste chama API."""
import re
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401
from test_painel_acessibilidade import _hex, _temas, contraste, verificar  # noqa: E402
from test_leitura_solucoes import SOLUCOES, Montagem, semear  # noqa: E402

from dominio.solucoes import SolucaoConhecida, marcar_ocorrencias  # noqa: E402
from painel import rotulos  # noqa: E402

XSS_NOME = '<img src=x onerror=alert(5)> Zeta'
LONGO = "BO Fácil"


def sql(banco, comando, args=()):
    conn = sqlite3.connect(banco)
    try:
        cur = conn.execute(comando, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@pytest.fixture(scope="module")
def modelo(demo, tmp_path_factory):
    """Demonstração + cenário das soluções conhecidas, com nomes de solução: Delta Bot (apelido na evidência), Gama App (só o nome),
    um nome com XSS, um nome só com espaços e achados nomeados em quantidade suficiente para paginar o filtro."""
    banco0, raw0 = demo
    pasta = tmp_path_factory.mktemp("destaques")
    banco, raw = pasta / "demo.db", pasta / "raw"
    shutil.copy(banco0, banco)
    shutil.copytree(raw0, raw)
    ids = semear(banco, raw)
    m = Montagem(banco, raw)
    sql(banco, "UPDATE achados SET nome_solucao='Delta Bot' WHERE achado_id=?", (ids["a_delta"],))
    sql(banco, "UPDATE achados SET nome_solucao='Gama App' WHERE achado_id=?", (ids["a_gama"],))
    # outros achados da MESMA classificação de Gama App (cada `Montagem.achado` cria uma classificação nova, e só a mais recente é vigente)
    conn = sqlite3.connect(banco)
    k = conn.execute("SELECT classificacao_id FROM achados WHERE achado_id=?", (ids["a_gama"],)).fetchone()[0]
    conn.close()
    for chave, evidencia, tecnologia, nome in (("a_xss", "texto sem o nome", "leitura_placas", XSS_NOME),
                                               ("a_branco", "outro texto", "analise_preditiva", "   ")):
        ids[chave] = sql(banco, """INSERT INTO achados(classificacao_id, uf, tecnologia, status_reportado, evidencia, confianca, nome_solucao)
                                   VALUES (?, 'PI', ?, 'em_uso', ?, 'alta', ?)""", (k, tecnologia, evidencia, nome))
    # mais nomeados: o filtro passa de 50 achados (duas páginas) e a paginação precisa guardar `solucao=nomeada`
    sql(banco, """UPDATE achados SET nome_solucao='Nome Extra' WHERE achado_id IN
                  (SELECT achado_id FROM v_achados_revisao WHERE nome_solucao IS NULL ORDER BY achado_id LIMIT 12)""")
    # texto com várias ocorrências (acento, caixa, hífen, palavra colada) para a marca de /buscar-texto
    ids["u_multi"] = m.url("https://ssp.pi.gov.br/multi", "ssp.pi.gov.br")
    m.selecao("SOL1", ids["u_multi"])
    ids["p_multi"] = m.pagina("SOL1", ids["u_multi"], "O BO Fácil atende. Dizem que o bo-facil é bom, e o BÓ FACIL também; "
                              "mas BO Facilitado é outro sistema.", dominio="ssp.pi.gov.br")
    ids["a_multi"] = m.achado("SOL1", ids["u_multi"], ids["p_multi"], "O BO Fácil atende", nome="BO Fácil")
    # chamada de download bloqueada depois de um redirecionamento
    ids["c_redir"] = sql(banco, """INSERT INTO chamadas(run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em, sucesso, erro, alvo_id)
                                   VALUES ('SOL1', 'download', 'p', '{}', ?, '2026-10-16T00:00:00', 0, ?, '999999')""",
                         (uuid.uuid4().hex, "robots_inacessivel_apos_redirecionamento: https://outro.gov.br/x"))
    app, ctx = _app(banco, raw, pasta)
    ctx.solucoes_conhecidas = SOLUCOES + (SolucaoConhecida(LONGO, "PI", apelidos=("BOFacil",)), SolucaoConhecida("<b>Xis</b>", "PI"))
    return TestClient(app), ids, banco, raw


@pytest.fixture
def cli(modelo):
    return modelo[0]


def n_achados(html):
    return int(re.search(r"<strong>([\d.]+)</strong> achado", html).group(1).replace(".", ""))


def sem_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---------- 1. solução nomeada ----------
def test_selo_de_solucao_nomeada_nas_tres_paginas(cli, modelo):
    ids = modelo[1]
    # lista: o selo tem o nome acessível "Solução nomeada: ..."
    h = cli.get("/achados?q=Gama+App").text
    assert 'class="selo solucao-nomeada"' in h and "Solução nomeada: </span><span class=\"solucao-nome\">Gama App</span>" in h
    # detalhe: destaque no topo da coluna principal
    d = cli.get(f"/achados/{ids['a_gama']}").text
    assert '<div class="solucao-destaque">' in d and "Solução nomeada: </span><span class=\"solucao-nome\">Gama App</span>" in d
    assert d.index("solucao-destaque") < d.index("<h1>")
    assert "sem-nome-dica" not in d
    # estado: o selo vem antes do achado
    e = cli.get("/estados/PI").text
    assert 'class="selo solucao-nomeada"' in e and "Gama App" in e and "Delta Bot" in e


def test_achado_sem_nome_nao_tem_selo_e_diz_que_e_anonimo(cli, modelo):
    ids = modelo[1]
    d = cli.get(f"/achados/{ids['a_branco']}").text
    assert "solucao-destaque" not in d and 'class="selo solucao-nomeada"' not in d
    assert "Achado sem nome de solução" in d and 'class="sem-nome"' in d
    # na lista, as linhas sem nome mostram a dica discreta; o nome só com espaços também conta como sem nome
    lista = cli.get("/achados?q=outro+texto").text
    assert 'class="sem-nome"' in lista and 'class="selo solucao-nomeada"' not in lista.split("<tbody>")[1]


def test_nome_com_html_e_escapado_nas_tres_paginas_e_nos_cartoes(cli, modelo):
    ids = modelo[1]
    for url in ("/achados?q=Zeta", f"/achados/{ids['a_xss']}", "/estados/PI", "/solucoes"):
        h = cli.get(url).text
        assert "<img src=x onerror" not in h and "<b>Xis</b>" not in h, url
        assert verificar(h) == [], url
    assert "&lt;img src=x onerror=alert(5)&gt; Zeta" in cli.get(f"/achados/{ids['a_xss']}").text
    assert "&lt;b&gt;Xis&lt;/b&gt;" in cli.get("/solucoes").text
    # o link para a lista leva o nome codificado (nunca cru)
    assert "/achados?q=%3Cimg" in cli.get(f"/achados/{ids['a_xss']}").text


def test_filtro_so_as_nomeadas_conta_e_pagina_guardando_o_parametro(cli, modelo):
    banco = modelo[2]
    c = sqlite3.connect(banco)
    esperado = c.execute("SELECT COUNT(*) FROM v_achados_revisao WHERE nome_solucao IS NOT NULL AND TRIM(nome_solucao) <> ''").fetchone()[0]
    todos = c.execute("SELECT COUNT(*) FROM v_achados_revisao").fetchone()[0]
    c.close()
    assert 50 < esperado < todos
    h = cli.get("/achados?solucao=nomeada").text
    assert n_achados(h) == esperado and n_achados(cli.get("/achados").text) == todos
    assert "Página 1 de 2" in h and 'href="/achados?solucao=nomeada&amp;p=2"' in h
    h2 = cli.get("/achados?solucao=nomeada&p=2").text
    assert 'href="/achados?solucao=nomeada&amp;p=1"' in h2
    # nenhuma linha anônima passa pelo filtro, e o seletor mostra a opção marcada
    assert 'class="sem-nome"' not in h and '<option value="nomeada" selected>só as nomeadas</option>' in h
    # combina com outros filtros e continua valendo na revisão
    so_sp = n_achados(cli.get("/achados?solucao=nomeada&uf=PI").text)
    assert 0 < so_sp <= esperado
    assert "solucao=nomeada" in cli.get("/achados?solucao=nomeada&verificacao=pendente").text
    # o valor desconhecido não filtra nada
    assert n_achados(cli.get("/achados?solucao=qualquer").text) == todos


def test_o_filtro_nao_conta_nome_so_com_espacos(cli, modelo):
    ids = modelo[1]
    assert f'href="/achados/{ids["a_branco"]}"' not in cli.get("/achados?solucao=nomeada&q=outro+texto").text
    assert f'href="/achados/{ids["a_gama"]}"' in cli.get("/achados?solucao=nomeada&q=Gama+App").text


def test_a_busca_q_encontra_pelo_nome_da_solucao(cli, modelo):
    ids = modelo[1]
    # a evidência de Gama App ("o aplicativo atende o cidadão pelo celular") não tem o nome: só o campo nome_solucao casa
    h = cli.get("/achados?q=Gama+App").text
    assert f'href="/achados/{ids["a_gama"]}"' in h and n_achados(h) >= 1
    assert "Nenhum achado" in cli.get("/achados?q=Nome+Que+Nao+Existe").text


# ---------- 2. texto completo x somente snippet ----------
def test_origem_do_texto_aparece_na_lista_com_selo_ambar_para_snippet(cli):
    h = cli.get("/achados?origem=snippet").text
    corpo = h.split("<tbody>")[1]
    assert "origem-snippet" in corpo and "Somente snippet" in corpo and "origem-pagina" not in corpo
    assert "<th>Texto</th>" in h
    assert rotulos.EXPLICACAO_SNIPPET in h and "limitada a “baixa”" in h
    p = cli.get("/achados?origem=pagina").text.split("<tbody>")[1]
    assert "origem-pagina" in p and "Texto completo" in p and "origem-snippet" not in p


def test_origem_do_texto_no_achado_e_no_estado(cli, modelo):
    banco = modelo[2]
    c = sqlite3.connect(banco)
    snip = c.execute("""SELECT a.achado_id, a.uf FROM v_achados_revisao a WHERE a.origem_texto='snippet' ORDER BY a.achado_id LIMIT 1""").fetchone()
    pag = c.execute("""SELECT a.achado_id FROM v_achados_revisao a WHERE a.origem_texto='pagina' ORDER BY a.achado_id LIMIT 1""").fetchone()
    c.close()
    d = cli.get(f"/achados/{snip[0]}").text
    assert "origem-snippet" in d and "Modo degradado: somente snippet" in d and "limitada a “baixa”" in d
    assert "origem-pagina" in cli.get(f"/achados/{pag[0]}").text and "Modo degradado" not in cli.get(f"/achados/{pag[0]}").text
    e = cli.get(f"/estados/{snip[1]}").text
    assert "origem-snippet" in e and "origem-pagina" in e


# ---------- 3. aprofundamento a partir de /solucoes ----------
def _linha(html, nome):
    for tr in re.findall(r"<tr>.*?</tr>", html, re.S):
        if f'>{nome}</a></th>' in tr:
            return tr
    raise AssertionError(nome)


def _cartao(html, i):
    return re.search(rf'<section class="cartao cartao-solucao"[^>]*id="solucao-{i}">.*?</section>', html, re.S).group(0)


def test_solucoes_resumo_tem_links_exatos_e_zero_nao_e_link(cli):
    h = cli.get("/solucoes").text
    # Delta Bot (4a da lista): 0 resultados, 1 página, 1 achado
    linha = _linha(h, "Delta Bot")
    assert 'href="#solucao-4"' in linha                        # a âncora do cartão (o nome na primeira coluna)
    assert 'href="/buscar-texto?q=Delta%20Bot&amp;uf=PI&amp;inteira=1"' in linha
    assert 'href="/achados?uf=PI&amp;q=Delta%20Bot"' in linha
    # o zero de "Resultados de busca" não é link: texto apagado
    assert '<td class="num"><span class="indicador-zero" title="Nenhum">0</span></td>' in linha
    # Zeta Alfa: tudo zero, nenhum link além do nome
    zeta = _linha(h, "Zeta Alfa")
    assert zeta.count("<a ") == 1 and zeta.count("indicador-zero") == 3
    # Beta Sistema: 2 resultados levam ao cartão; as demais contagens são zero
    beta = _linha(h, "Beta Sistema")
    assert 'class="indicador" href="#solucao-2"' in beta and beta.count("indicador-zero") == 2


def test_solucoes_cartao_tem_ancora_estavel_e_indicadores_clicaveis(cli):
    h = cli.get("/solucoes").text
    for i in range(1, 7):
        assert f'id="solucao-{i}"' in h and f'aria-labelledby="solucao-{i}-h"' in h and f'id="solucao-{i}-h"' in h
    assert "#sol-" not in h
    c = _cartao(h, 4)
    assert '<ul class="presenca"' in c
    assert 'href="/buscar-texto?q=Delta%20Bot&amp;uf=PI&amp;inteira=1"' in c and 'href="/achados?uf=PI&amp;q=Delta%20Bot"' in c
    c2 = _cartao(h, 2)                                         # Beta Sistema: resultados > 0, leva à listagem do cartão
    assert 'href="#solucao-2-resultados"' in c2 and 'id="solucao-2-resultados"' in c2
    c1 = _cartao(h, 1)
    assert c1.count('class="indicador"') == 0 and c1.count("indicador-zero") == 3
    # o nome de acessibilidade diz o que o número abre
    assert 'aria-label="Ver os achados que citam Delta Bot"' in c


def test_nome_com_acento_e_codificado_nos_links(cli):
    h = cli.get("/solucoes").text
    assert "/buscar-texto?q=BO%20F%C3%A1cil&amp;uf=PI&amp;inteira=1" in h
    linha = _linha(h, LONGO)
    assert 'href="/achados?uf=PI&amp;q=BO%20F%C3%A1cil"' in linha
    assert "<script" not in h.lower().replace("<script src", "")


def _hrefs(trecho):
    return [h.replace("&amp;", "&") for h in re.findall(r'href="([^"]+)"', trecho)]


def test_cadeia_solucoes_para_buscar_texto_para_achados(cli, modelo):
    ids = modelo[1]
    linha = _linha(cli.get("/solucoes").text, "Delta Bot")
    hrefs = _hrefs(linha)
    h_paginas = next(x for x in hrefs if x.startswith("/buscar-texto"))
    h_achados = next(x for x in hrefs if x.startswith("/achados"))
    # solucoes -> buscar-texto: a página do Delta Bot aparece, com trecho marcado e o achado dela
    r = cli.get(h_paginas)
    assert r.status_code == 200 and "<mark>DELTA-BOT</mark>" in r.text and verificar(r.text) == []
    ligacao = re.search(r'href="(/achados/\d+)"', r.text).group(1)
    assert ligacao == f"/achados/{ids['a_delta']}"
    # buscar-texto -> achado: o achado nomeado mostra o selo da solução
    rd = cli.get(ligacao)
    assert rd.status_code == 200 and "Solução nomeada: </span><span class=\"solucao-nome\">Delta Bot</span>" in rd.text
    # solucoes -> achados (nome exato): lista com o mesmo achado
    ra = cli.get(h_achados)
    assert ra.status_code == 200 and f'href="/achados/{ids["a_delta"]}"' in ra.text and n_achados(ra.text) >= 1
    # o link do achado leva de volta aos achados da solução
    assert "/achados?q=Delta%20Bot" in rd.text


# ---------- 3b. buscar-texto ----------
def test_marca_toda_ocorrencia_com_acento_caixa_e_hifen_sem_marcar_palavra_maior(cli):
    h = cli.get("/buscar-texto?q=bo+facil&inteira=1&uf=PI").text
    trecho = re.findall(r'<p class="trecho">(.*?)</p>', h, re.S)
    ocorrencias = [t for t in trecho if "bom, e" in t][0]
    assert re.findall(r"<mark>(.*?)</mark>", ocorrencias) == ["BO Fácil", "bo-facil", "BÓ FACIL"]
    assert "<mark>BO Facilitado</mark>" not in ocorrencias and "BO Facilitado" in ocorrencias


def test_sem_palavra_inteira_marca_tambem_o_prefixo(cli):
    h = cli.get("/buscar-texto?q=bo+facil&uf=PI").text
    t = [x for x in re.findall(r'<p class="trecho">(.*?)</p>', h, re.S) if "bom, e" in x][0]
    assert re.findall(r"<mark>(.*?)</mark>", t) == ["BO Fácil", "bo-facil", "BÓ FACIL", "BO Facil"]


def test_marcar_ocorrencias_unidade():
    assert marcar_ocorrencias("a BO Fácil e bo facil", "BO FACIL") == [("a ", False), ("BO Fácil", True), (" e ", False), ("bo facil", True)]
    assert "".join(p for p, _ in marcar_ocorrencias("x <b>BO</b> Fácil y", "bo facil")) == "x <b>BO</b> Fácil y"      # sem perda
    assert marcar_ocorrencias("nada aqui", "xyz") == [("nada aqui", False)] and marcar_ocorrencias("", "xyz") == []
    # palavra inteira: "spia" não casa em "espiando"; sem a opção, casa
    assert [p for p, m in marcar_ocorrencias("espiando SPiA", "spia", True) if m] == ["SPiA"]
    assert [p for p, m in marcar_ocorrencias("espiando SPiA", "spia", False) if m] == ["spia", "SPiA"]
    # ocorrência colada a um corte (…) não é marcada com palavra inteira: a palavra pode estar pela metade
    assert [p for p, m in marcar_ocorrencias("…spia aqui e spia ali…", "spia", True) if m] == ["spia"]      # só a do meio
    assert [p for p, m in marcar_ocorrencias("…spia aqui", "spia", True) if m] == []
    assert [p for p, m in marcar_ocorrencias("…xx spia aqui e spia ali xx…", "spia", True) if m] == ["spia", "spia"]


def test_cada_resultado_tem_link_para_a_pagina_original_e_para_os_achados(cli, modelo):
    ids = modelo[1]
    h = cli.get("/buscar-texto?q=bo+facil&inteira=1&uf=PI").text
    assert 'href="https://ssp.pi.gov.br/final"' in h and "Abrir a página original" in h and 'rel="noopener noreferrer"' in h
    assert f'href="/achados/{ids["a_multi"]}"' in h and "Solução nomeada: </span><span class=\"solucao-nome\">BO Fácil</span>" in h
    assert verificar(h) == []
    # endereço que não é http/https: sem link
    j = cli.get("/buscar-texto?q=gama+app&inteira=1").text
    assert 'href="javascript:' not in j.lower()


# ---------- 4. robots.txt: duas razões, cor + glifo + texto ----------
def test_rotulos_dos_dois_motivos_e_variantes_apos_redirecionamento():
    assert rotulos.MOTIVOS_DOWNLOAD["bloqueado_por_robots"] == "Proibido pelo site (diretiva Disallow do robots.txt)"
    assert rotulos.MOTIVOS_DOWNLOAD["robots_inacessivel"] == "Bloqueio preventivo (RFC 9309): robots.txt do site indisponível"
    assert rotulos.motivo_robots("bloqueado_por_robots")["chave"] == "bloqueado_por_robots"
    pos = rotulos.motivo_robots("robots_inacessivel_apos_redirecionamento: https://x.gov.br/a")
    assert pos["chave"] == "robots_inacessivel" and pos["apos_redirecionamento"] and pos["rotulo"].endswith(", após redirecionamento")
    pos = rotulos.motivo_robots("bloqueado_por_robots_apos_redirecionamento: https://x.gov.br/a")
    assert pos["chave"] == "bloqueado_por_robots" and pos["apos_redirecionamento"]
    assert rotulos.motivo_robots("HTTP 404") is None and rotulos.motivo_robots(None) is None and rotulos.motivo_robots("") is None


def _ids_chamadas(banco):
    c = sqlite3.connect(banco)
    try:
        return (c.execute("SELECT MIN(chamada_id) FROM chamadas WHERE erro = 'bloqueado_por_robots'").fetchone()[0],
                c.execute("SELECT MIN(chamada_id) FROM chamadas WHERE erro = 'robots_inacessivel'").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM chamadas WHERE erro LIKE 'bloqueado_por_robots%'").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM chamadas WHERE erro LIKE 'robots_inacessivel%'").fetchone()[0])
    finally:
        c.close()


def test_chamadas_distingue_as_duas_razoes_no_filtro_e_na_coluna(cli, modelo):
    _, _, n_proib, n_inac = _ids_chamadas(modelo[2])
    assert n_proib >= 1 and n_inac >= 2                                    # inclui a chamada semeada após redirecionamento
    p = cli.get("/chamadas?resultado=robots_proibido").text
    assert f"<strong>{n_proib}</strong> chamada(s)" in p
    corpo = p.split("<tbody>")[1]
    assert "robots-proibido" in corpo and "robots-preventivo" not in corpo
    assert "Proibido pelo site (diretiva Disallow do robots.txt)" in corpo and "✕ falha" not in corpo
    i = cli.get("/chamadas?resultado=robots_inacessivel").text
    assert f"<strong>{n_inac}</strong> chamada(s)" in i
    corpo = i.split("<tbody>")[1]
    assert "robots-preventivo" in corpo and "robots-proibido" not in corpo
    assert "Bloqueio preventivo (RFC 9309): robots.txt do site indisponível" in corpo
    assert "após redirecionamento" in corpo and "https://outro.gov.br/x" in corpo
    # o seletor oferece os dois valores, marcados; a legenda tem os dois selos com link
    assert '<option value="robots_proibido" selected>' in p and '<option value="robots_inacessivel" selected>' in i
    for h in (p, i):
        assert 'class="selo robots-proibido" href="/chamadas?etapa=download&amp;resultado=robots_proibido"' in h
        assert 'class="selo robots-preventivo" href="/chamadas?etapa=download&amp;resultado=robots_inacessivel"' in h
        assert verificar(h) == []
    # falha comum continua com o selo de falha
    assert "✕ falha" in cli.get("/chamadas?resultado=falha&etapa=download").text
    # os dois valores novos guardam os outros filtros na paginação
    assert "resultado=robots_inacessivel" in cli.get("/chamadas?resultado=robots_inacessivel&etapa=download").text


def test_chamada_individual_tem_cabecalho_proprio_para_cada_razao(cli, modelo):
    banco = modelo[2]
    prib, inac, _, _ = _ids_chamadas(banco)
    h = cli.get(f"/chamadas/{prib}").text
    assert 'class="selo robots-proibido"' in h and "Proibido pelo site (diretiva Disallow do robots.txt)" in h
    assert 'class="aviso robots-proibido"' in h and "foi decisão do site" in h and "HTTP 200" in h
    assert "robots-preventivo" not in h and "✕ falhou" not in h
    h = cli.get(f"/chamadas/{inac}").text
    assert 'class="selo robots-preventivo"' in h and "Bloqueio preventivo (RFC 9309): robots.txt do site indisponível" in h
    assert 'class="aviso robots-preventivo"' in h and "não foi decisão do site" in h and "HTTP 503" in h and "3 leitura(s)" in h
    h = cli.get(f"/chamadas/{modelo[1]['c_redir']}").text
    assert "após redirecionamento" in h and "https://outro.gov.br/x" in h and "robots-preventivo" in h
    for rota in (f"/chamadas/{prib}", f"/chamadas/{inac}", f"/chamadas/{modelo[1]['c_redir']}"):
        assert verificar(cli.get(rota).text) == [], rota


def test_analises_operacao_distingue_as_duas_razoes_por_cor_glifo_e_texto(cli):
    h = cli.get("/analises?secao=operacao").text
    assert 'class="selo robots-proibido"' in h and 'class="selo robots-preventivo"' in h
    assert "Proibido pelo site (diretiva Disallow do robots.txt)" in h
    assert "Bloqueio preventivo (RFC 9309): robots.txt do site indisponível" in h
    # a tabela do ranking: colunas e legenda com as duas razões
    assert 'class="an-motivos"' in h
    assert "robots.txt do site indisponível" in h and "✕" in h and "⚠" in h
    # os motivos têm link para as chamadas filtradas
    assert "/chamadas?etapa=download&amp;resultado=robots_inacessivel" in h and "/chamadas?etapa=download&amp;resultado=robots_proibido" in h
    assert verificar(h) == []


def test_ranking_semaforo_zero_sem_selo_e_coluna_preventiva_so_quando_informada():
    from painel import graficos_analises as ga
    sem = ga.ranking_semaforo([{"dominio": "a.gov.br", "total": 10, "bloqueadas": 2}], "t")
    assert "robots-preventivo" not in sem and "Bloqueio preventivo" not in sem and "robots-proibido" in sem
    com = ga.ranking_semaforo([{"dominio": "a.gov.br", "total": 10, "bloqueadas": 0, "inacessiveis": 5}], "t")
    assert '<span class="an-zero">0</span>' in com and "robots-preventivo" in com and "Bloqueio preventivo (RFC 9309)" in com
    assert 'class="selo robots-proibido"' not in com                          # o zero não ganha selo


# ---------- contraste e CSS ----------
@pytest.mark.parametrize("indice,nome", [(0, "claro"), (1, "escuro")])
def test_contraste_dos_selos_novos(indice, nome):
    tema = _temas()[indice]
    ruins = []
    for seletor in (".selo.solucao-nomeada", ".selo.texto-completo", ".selo.robots-proibido", ".selo.robots-preventivo"):
        d = tema["regras"][seletor]
        c = contraste(_hex(d["color"], tema["tokens"]), _hex(d["background"], tema["tokens"]))
        if c < 4.5:
            ruins.append(f"{seletor}: {c:.2f}")
    assert not ruins, f"tema {nome}: " + "; ".join(ruins)


def test_as_duas_razoes_de_robots_diferem_alem_da_cor():
    regras = _temas()[0]["regras"]
    prib, prev = regras[".selo.robots-proibido"], regras[".selo.robots-preventivo"]
    assert "solid" in prib["border"] and "dashed" in prev["border"]                  # estilo de borda diferente
    assert prib["color"] != prev["color"] and prib["background"] != prev["background"]


def test_css_novo_nao_traz_hexadecimal_fora_dos_tokens():
    pasta = Path(__file__).resolve().parent.parent / "painel" / "static"
    for nome in ("painel.css", "solucoes.css"):
        css = re.sub(r"/\*.*?\*/", "", (pasta / nome).read_text(encoding="utf-8"), flags=re.S)
        fora = css.split("@media (prefers-color-scheme: dark)")[0] if nome == "painel.css" else css
        if nome == "painel.css":
            fora = fora.split(":root {", 1)[1].split("}", 1)[1]                          # depois do bloco de tokens
            fora = fora.split("@media print")[0]
        for linha in fora.splitlines():
            if any(x in linha for x in ("solucao-", "robots-", "texto-completo", "indicador", "presenca", "sem-nome", "legenda-")):
                assert not re.search(r"#[0-9a-fA-F]{3,8}\b", linha), linha
    analises = (pasta / "analises.css").read_text(encoding="utf-8")
    trecho = analises.split("razões de bloqueio pelo robots.txt", 1)[1].split("selos estatísticos", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", trecho)


def test_paginas_novas_nao_gravam_e_continuam_acessiveis(cli, modelo):
    banco = modelo[2]
    antes = banco.read_bytes()
    for rota in ("/achados?solucao=nomeada", "/solucoes", "/buscar-texto?q=bo+facil&inteira=1", "/chamadas?resultado=robots_proibido",
                 "/analises?secao=operacao"):
        r = cli.get(rota)
        assert r.status_code == 200 and verificar(r.text) == [], rota
    assert banco.read_bytes() == antes
