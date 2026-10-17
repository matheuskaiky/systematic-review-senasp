"""Paginas /solucoes e /buscar-texto sobre o banco de demonstracao com linhas semeadas: cada situacao de uma solucao conhecida, busca
no texto, validacao das entradas, XSS, URLs perigosas, teto de resultados e acessibilidade."""
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
from test_leitura_solucoes import S1, S2, S3, S4, SOLUCOES, XSS_TEXTO, XSS_TITULO, Montagem, semear  # noqa: E402

from adaptadores.leitura_sqlite import LeituraPainelSQLite  # noqa: E402
from painel.rotas_extras import solucoes as rota  # noqa: E402


@pytest.fixture(scope="module")
def modelo(demo, tmp_path_factory):
    """Demonstracao com o cenario semeado (copiada uma vez; cada teste usa o banco como esta, pois as paginas so leem)."""
    banco0, raw0 = demo
    pasta = tmp_path_factory.mktemp("painel_solucoes")
    banco, raw = pasta / "demo.db", pasta / "raw"
    shutil.copy(banco0, banco)
    shutil.copytree(raw0, raw)
    ids = semear(banco, raw)
    app, ctx = _app(banco, raw, pasta)
    ctx.solucoes_conhecidas = SOLUCOES
    return TestClient(app), ids, banco, raw, ctx


@pytest.fixture
def cli(modelo):
    return modelo[0]


def texto(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def cartao(html, nome):
    """HTML do cartao da solucao `nome` (cada um e uma <section id="sol-N">)."""
    for s in re.findall(r'<section class="cartao cartao-solucao".*?</section>', html, re.S):
        if f">{nome} <small>" in s:
            return s
    raise AssertionError(f"sem cartao para {nome}")


def linha_do_resumo(html, nome):
    for tr in re.findall(r"<tr>.*?</tr>", html, re.S):
        if f'>{nome}</a></th>' in tr:
            return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>.*?</t[dh]>", tr, re.S)]
    raise AssertionError(nome)


# ---------- respostas e estrutura ----------
def test_as_duas_paginas_respondem_e_sao_acessiveis(cli):
    for url in ("/solucoes", "/buscar-texto", "/buscar-texto?q=Gama+App&inteira=1", "/buscar-texto?q=ab", "/buscar-texto?q=zzzzqqqq"):
        r = cli.get(url)
        assert r.status_code in (200, 400), url
        assert verificar(r.text) == [], url
        assert 'aria-current="page"' in r.text


def test_menu_tem_os_dois_itens(cli):
    h = cli.get("/").text
    assert '<a href="/solucoes">Soluções conhecidas</a>' in h and '<a href="/buscar-texto">Buscar no texto</a>' in h
    assert '<a href="/solucoes" aria-current="page">' in cli.get("/solucoes").text
    assert '<a href="/buscar-texto" aria-current="page">' in cli.get("/buscar-texto").text


def test_sem_script_nem_estilo_embutido_e_so_get(cli):
    for url in ("/solucoes", "/buscar-texto?q=Gama+App"):
        h = cli.get(url).text
        assert not re.search(r"<script(?![^>]*\bsrc=)", h) and 'style="' not in h and "onclick" not in h
    assert cli.post("/solucoes").status_code == 405 and cli.post("/buscar-texto").status_code == 405


def test_sem_banco_responde_503(tmp_path):
    app, _ = _app(tmp_path / "nao_existe.db", tmp_path / "raw", tmp_path)
    c = TestClient(app)
    assert c.get("/solucoes").status_code == 503 and c.get("/buscar-texto?q=abc").status_code == 503


# ---------- /solucoes: uma situacao por solucao ----------
def test_cada_situacao_aparece_no_resumo_e_no_cartao(cli):
    h = cli.get("/solucoes").text
    esperado = {"Zeta Alfa": ("0", "0", "0", "Não apareceu nos resultados da busca"),
                "Beta Sistema": ("2", "0", "0", "Apareceu nos resultados, mas nenhuma página baixada cita o nome"),
                "Gama App": ("0", "1", "0", "Está no texto de página baixada, mas nenhum achado cita o nome"),
                "Delta Bot": ("0", "1", "1", "Citada em achados")}
    for nome, (res, pag, ach, rotulo) in esperado.items():
        linha = linha_do_resumo(h, nome)
        assert linha[2:] == [res, pag, ach, rotulo], (nome, linha)
        assert f"Situação: {rotulo}." in texto(cartao(h, nome))


def test_cartao_da_solucao_so_nos_resultados_marca_pagina_nunca_baixada_e_fora_do_relatorio(cli):
    c = texto(cartao(cli.get("/solucoes").text, "Beta Sistema"))
    assert "página nunca baixada" in c and "só em execução fora do relatório" in c
    assert "consulta C-PI-a" in c and "posição 3" in c and "execução SOL0" in c
    assert "NÃO prova" in texto(cartao(cli.get("/solucoes").text, "Zeta Alfa"))


def test_cartao_com_pagina_sem_achado_mostra_os_achados_da_pagina_e_o_link(cli, modelo):
    ids = modelo[1]
    h = cartao(cli.get("/solucoes").text, "Gama App")
    assert "Achados desta página que não citam o nome" in texto(h) and f'href="/achados/{ids["a_gama"]}"' in h
    assert "Nenhum achado cita o nome" in texto(h)


def test_cartao_com_achado_linka_o_achado_e_o_apelido_vale(cli, modelo):
    ids = modelo[1]
    h = cartao(cli.get("/solucoes").text, "Delta Bot")
    assert f'href="/achados/{ids["a_delta"]}"' in h and "citado na evidência" in texto(h)
    t = texto(h)
    assert "delta bot" in t and "db bot" in t                                        # nomes procurados
    assert "Ceará" not in t and "ce.gov.br" not in h                                  # outra UF nao entra
    assert "/buscar-texto?q=Delta%20Bot&amp;uf=PI&amp;inteira=1" in h


def test_pagina_sem_arquivo_ou_sem_texto_nao_conta_e_nao_quebra(cli):
    h = cli.get("/solucoes").text
    assert linha_do_resumo(h, "Delta Bot")[3] == "1"        # a do Ceara, a sem arquivo e a sem texto extraido ficam de fora


def test_como_ler_deixa_claro_que_ausente_nao_prova(cli):
    t = texto(cli.get("/solucoes").text)
    assert "não prova que ela não é usada" in t and "CASO_BO_FACIL" in t and "config/solucoes_conhecidas.py" in t


def test_sem_solucoes_configuradas_a_pagina_explica(modelo):
    _, _, banco, raw, ctx = modelo
    app, ctx2 = _app(banco, raw, banco.parent)
    r = TestClient(app).get("/solucoes")
    assert r.status_code == 200 and "Nenhuma solução conhecida foi informada" in r.text and verificar(r.text) == []


def test_xss_e_url_perigosa_em_solucoes(cli):
    h = cli.get("/solucoes").text
    assert "<script>alert(1)</script>" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h
    assert "<img src=x onerror" not in h
    assert not re.search(r'href="javascript', h, re.I)


def test_solucoes_nao_grava_no_banco(modelo):
    _, _, banco, _, _ = modelo
    antes = banco.read_bytes()
    modelo[0].get("/solucoes"); modelo[0].get("/buscar-texto?q=Gama+App")
    assert banco.read_bytes() == antes


# ---------- /buscar-texto ----------
def test_busca_destaca_o_trecho_no_texto_original_e_escapa_tudo(cli, modelo):
    ids = modelo[1]
    r = cli.get("/buscar-texto?q=gama+app&inteira=1")
    assert r.status_code == 200
    h = r.text
    assert "<mark>Gama App</mark>" in h and "<mark>Gama Apps</mark>" not in h          # destaque no original; palavra inteira
    assert "<img src=x onerror" not in h and "&lt;img src=x onerror=alert(2)&gt;" in h
    assert f'href="/achados/{ids["a_gama"]}"' in h and "Outra aplicação de IA" in h
    assert 'href="/achados?q=gama+app"' in h
    assert 'href="https://ssp.pi.gov.br/final"' in h and "rel=\"noopener noreferrer\"" in h


def test_busca_sem_diferenca_de_acento_e_caixa(cli):
    h = cli.get("/buscar-texto?q=CIDADAO").text
    assert "<mark>cidadão</mark>" in h
    assert "<mark>Cidadao</mark>" not in h


def test_palavra_inteira_ou_qualquer_trecho(cli):
    assert "Nenhuma página baixada cita" in cli.get("/buscar-texto?q=elta+bo&inteira=1").text
    assert re.search(r"<mark>elta[ -]Bo</mark>", cli.get("/buscar-texto?q=elta+bo").text, re.I)


def test_filtro_por_uf_e_contagem_de_paginas_pesquisadas(cli, modelo):
    leitura = LeituraPainelSQLite(modelo[2])
    total = len(leitura.paginas_para_busca_texto())
    h = cli.get("/buscar-texto?q=delta+bot&inteira=1").text
    assert f"Foram pesquisadas <strong>{total}</strong> página(s)" in h
    assert "ce.gov.br" in h
    so_pi = cli.get("/buscar-texto?q=delta+bot&inteira=1&uf=PI").text
    assert "ce.gov.br" not in so_pi and f"<strong>{len(leitura.paginas_para_busca_texto(['PI']))}</strong> página(s) da UF PI" in so_pi
    assert 'href="/achados?q=delta+bot&amp;uf=PI"' in so_pi


def test_pagina_sem_arquivo_e_avisada(cli):
    assert "ficaram de fora porque o arquivo de texto não foi encontrado" in cli.get("/buscar-texto?q=delta+bot").text


def test_formulario_vazio_explica_e_nao_busca(cli):
    h = cli.get("/buscar-texto").text
    assert "Como ler" in h and "não prova" in h and "Foram pesquisadas" not in h
    for rotulo in ("Nome ou frase", "UF", "Só palavra inteira"):
        assert rotulo in h
    assert cli.get("/buscar-texto?uf=PI").status_code == 200


@pytest.mark.parametrize("q", ["ab", "a" * 81, "!!!", "  x "])
def test_busca_invalida_responde_400_com_a_mensagem(cli, q):
    r = cli.get("/buscar-texto", params={"q": q})
    assert r.status_code == 400 and 'role="alert"' in r.text and "Foram pesquisadas" not in r.text
    assert verificar(r.text) == []


def test_limites_da_busca_aceitos(cli):
    assert cli.get("/buscar-texto", params={"q": "abc"}).status_code == 200
    assert cli.get("/buscar-texto", params={"q": "a" * 80}).status_code == 200
    assert "A busca precisa ter de 3 a 80 caracteres (a sua tem 2)" in cli.get("/buscar-texto?q=ab").text


def test_uf_invalida_responde_400(cli):
    r = cli.get("/buscar-texto?q=abc&uf=ZZ")
    assert r.status_code == 400 and "A UF escolhida não existe" in r.text
    assert cli.get("/buscar-texto?q=abc&uf=pi").status_code == 200                   # minuscula vale


def test_xss_na_consulta_e_escapado(cli):
    r = cli.get("/buscar-texto", params={"q": '"><script>alert(9)</script>'})
    assert "<script>alert(9)</script>" not in r.text and verificar(r.text) == []
    r = cli.get("/buscar-texto", params={"q": "<img src=x onerror=alert(8)> Gama App"})
    assert "<img src=x onerror=alert(8)>" not in r.text


def test_titulo_xss_dos_resultados_e_escapado_e_endereco_perigoso_sem_link(cli):
    h = cli.get("/solucoes").text
    cartao_beta = cartao(h, "Beta Sistema")
    assert "&lt;script&gt;alert(1)&lt;/script&gt; Beta Sistema inaugurado" in cartao_beta
    assert 'href="javascript:' not in cartao_beta.lower()
    assert "Beta Sistema em aviso" in cartao_beta                                        # o resultado existe, mas sem link


def test_teto_de_100_resultados_com_aviso(modelo):
    cli, ids, banco, raw, ctx = modelo
    m = Montagem(banco, raw)
    conn = sqlite3.connect(banco)
    try:
        for i in range(105):
            conn.execute("INSERT INTO urls(url_normalizada, url_original, dominio) VALUES (?, ?, 'pi.gov.br')", (f"https://pi.gov.br/cap{i}#n", f"https://pi.gov.br/cap{i}"))
            u = conn.execute("SELECT url_id FROM urls WHERE url_normalizada=?", (f"https://pi.gov.br/cap{i}#n",)).fetchone()[0]
            conn.execute("INSERT INTO selecao_download(run_id, url_id, uf, selecionada) VALUES ('SOL1', ?, 'PI', 1)", (u,))
            caminho, _ = m.bruto.salvar("texto", "SOL1", f"cap{i}", ("marcadorcap " * (i + 1)).encode(), "txt")
            ch = conn.execute("INSERT INTO chamadas(run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em, sucesso) VALUES ('SOL1','download','p','{}',?,'2026-10-16',1)", (f"cap{i}",)).lastrowid
            conn.execute("INSERT INTO paginas(run_id, url_id, chamada_id, url_final, http_status, texto_path, n_chars, extracao_ok, dominio_final) VALUES ('SOL1',?,?,?,200,?,10,1,'pi.gov.br')",
                         (u, ch, f"https://pi.gov.br/cap{i}", caminho))
        conn.commit()
    finally:
        conn.close()
    h = cli.get("/buscar-texto?q=marcadorcap&inteira=1").text
    assert "<strong>105</strong> citam" in h and "mostrando as 100 com mais ocorrências" in h
    assert h.count('<p class="trecho">') == 200                                        # 2 trechos por pagina, 100 paginas
    assert len(re.findall(r"<tr>", h)) == 101                                          # cabecalho + 100
    assert 'href="https://pi.gov.br/cap104"' in h and 'href="https://pi.gov.br/cap0"' not in h   # as mais citadas primeiro
    assert rota.MAX_RESULTADOS == 100 and rota.MAX_TRECHOS == 2


def test_buscar_texto_e_solucoes_apontam_um_para_o_outro(cli):
    assert 'href="/buscar-texto?q=Gama%20App&amp;uf=PI&amp;inteira=1"' in cli.get("/solucoes").text
    assert 'href="/solucoes"' in cli.get("/buscar-texto").text


def test_aquecimento_le_os_textos_ao_abrir_o_painel(modelo):
    """Com o servidor no ar (`with TestClient`), a tarefa de fundo enche o cache antes de qualquer busca."""
    _, _, banco, raw, ctx = modelo
    app, _ = _app(banco, raw, banco.parent)
    with TestClient(app) as cliente:
        app.state.aquecimento_cache_texto.join(timeout=60)
        assert app.state.cache_textos.tamanho() > 0
        assert cliente.get("/buscar-texto?q=reconhecimento").status_code == 200


def test_sem_servidor_nao_ha_aquecimento_e_falha_do_aquecimento_nao_derruba(modelo, tmp_path):
    _, _, banco, raw, ctx = modelo
    app, _ = _app(banco, raw, banco.parent)
    TestClient(app)                                             # sem `with`: o evento de inicio nao dispara
    assert not hasattr(app.state, "aquecimento_cache_texto")
    # banco que nao existe: o aquecimento termina sem erro e o painel sobe
    app2, _ = _app(tmp_path / "nao_existe.db", tmp_path / "raw", tmp_path)
    with TestClient(app2) as c2:
        app2.state.aquecimento_cache_texto.join(timeout=10)
        assert app2.state.cache_textos.tamanho() == 0
        assert c2.get("/buscar-texto").status_code in (200, 503)


# ---------- Etapa 4 do front-end: a cadeia de drill-down solucoes -> buscar-texto -> achados ----------
def _hrefs(html, prefixo):
    import html as h
    import re as _re
    return [h.unescape(x) for x in _re.findall(r'href="(' + _re.escape(prefixo) + r'[^"]*)"', html)]


def test_cadeia_solucoes_busca_no_texto_achado(cli):
    """Segue os links como uma pessoa: soluções -> busca no texto (com <mark>) -> achado, tudo respondendo 200."""
    s = cli.get("/solucoes")
    assert s.status_code == 200
    buscas = _hrefs(s.text, "/buscar-texto?")
    assert buscas, "a tela de soluções deveria ligar as páginas baixadas à busca no texto"
    achou_marca, achou_achado = False, False
    for url in dict.fromkeys(buscas):
        b = cli.get(url)
        assert b.status_code == 200, url
        if "<mark>" in b.text:
            achou_marca = True
        for url_achado in dict.fromkeys(_hrefs(b.text, "/achados/")):
            a = cli.get(url_achado)
            assert a.status_code == 200, url_achado
            achou_achado = True
    assert achou_marca, "a busca aberta pelo link deveria destacar o termo com <mark>"
    assert achou_achado, "algum resultado deveria levar a um achado da página"
    # o outro caminho: o número de achados leva à lista de achados já filtrada
    for url in dict.fromkeys(_hrefs(s.text, "/achados?")):
        assert cli.get(url).status_code == 200, url


# =====================================================================================================================
# RC23: entidades de nome_solucao no painel (agrupamento pelo nome canonico, filtro, dica, valor bruto intacto)
# =====================================================================================================================
from urllib.parse import quote  # noqa: E402

from dominio.entidades_solucao import resolver_entidades  # noqa: E402
from dominio.solucoes import SolucaoConhecida  # noqa: E402

POLI = SolucaoConhecida("Policiamento Preditivo Inteligente", "SP")
BO_SP = SolucaoConhecida("BO Fácil", "SP", apelidos=("B.O. Fácil",))
NOMES_SP = ["Policiamento Preditivo Inteligente", "Policiamnto Preditivo Inteligente", "SNA", "Sistema Sigma Nacional Aberto", "Operação Zeta I",
            "Operação Zeta II", "Radar Alfa", "Radar Alfa", "BO Fácil", "B.O. Fácil", "<i>Raro</i>", "Delta Bot"]


@pytest.fixture(scope="module")
def modelo_entidades(demo, tmp_path_factory):
    """Demonstracao com o cenario das solucoes e nomes de solucao escritos de varios jeitos, todos em achados vigentes: o cadastro Delta Bot (PI) com
    tres grafias; no SP, um cadastro com typo, sigla e nome por extenso, romanos e a mesma grafia de outra UF."""
    banco0, raw0 = demo
    pasta = tmp_path_factory.mktemp("painel_entidades")
    banco, raw = pasta / "demo.db", pasta / "raw"
    shutil.copy(banco0, banco)
    shutil.copytree(raw0, raw)
    ids = semear(banco, raw)

    def vigentes(uf):
        con = sqlite3.connect(banco)
        try:
            return [r[0] for r in con.execute("SELECT achado_id FROM v_achados_revisao WHERE uf=? ORDER BY achado_id", (uf,))]
        finally:
            con.close()

    def sql_(comando, args=()):
        con = sqlite3.connect(banco)
        try:
            cur = con.execute(comando, args)
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    sp, rj = vigentes("SP"), vigentes("RJ")
    assert len(sp) >= len(NOMES_SP) and len(rj) >= 1, (len(sp), len(rj))
    sql_("UPDATE achados SET nome_solucao='Delta Bot' WHERE achado_id=?", (ids["a_delta"],))
    sql_("UPDATE achados SET nome_solucao='Gama App' WHERE achado_id=?", (ids["a_gama"],))
    con = sqlite3.connect(banco)
    k = con.execute("SELECT classificacao_id FROM achados WHERE achado_id=?", (ids["a_delta"],)).fetchone()[0]
    con.close()
    ids["db_bot"], ids["delta_hifen"] = [sql_("""INSERT INTO achados(classificacao_id, uf, tecnologia, status_reportado, evidencia, confianca, nome_solucao)
                                                 VALUES (?, 'PI', 'outra_ia', 'em_uso', 'outro trecho', 'alta', ?)""", (k, nome)) for nome in ("DB Bot", "Delta-Bot")]
    ids["sp"] = {}
    for i, nome in zip(sp, NOMES_SP):
        sql_("UPDATE achados SET nome_solucao=? WHERE achado_id=?", (nome, i))
        ids["sp"].setdefault(nome, []).append(i)
    ids["rj"] = rj[0]
    sql_("UPDATE achados SET nome_solucao='Radar Alfa' WHERE achado_id=?", (rj[0],))
    app, ctx = _app(banco, raw, pasta)
    ctx.solucoes_conhecidas = SOLUCOES + (POLI, BO_SP)
    return TestClient(app), ids, banco, ctx


def _nomes_no_banco(banco):
    con = sqlite3.connect(banco)
    try:
        return con.execute("SELECT achado_id, nome_solucao FROM achados ORDER BY achado_id").fetchall()
    finally:
        con.close()


def _contagens(banco):
    con = sqlite3.connect(banco)
    try:
        return {(n, u): k for n, u, k in con.execute(
            "SELECT nome_solucao, uf, COUNT(*) FROM r_achados WHERE TRIM(COALESCE(nome_solucao,'')) <> '' GROUP BY 1, 2")}
    finally:
        con.close()


def _total(html):
    return int(re.search(r"<strong>([\d.]+)</strong> achado\(s\)", html).group(1).replace(".", ""))


def test_entidades_o_resumo_conta_entidades_e_achados_nomeados(modelo_entidades):
    cli, ids, banco, ctx = modelo_entidades
    contagens = _contagens(banco)
    res = resolver_entidades(contagens, ctx.solucoes_conhecidas)
    h = cli.get("/achados").text
    assert f"Soluções nomeadas: {len(res.entidades)} entidade(s), {sum(contagens.values())} achado(s)" in texto(h)
    assert 'href="/achados?solucao=nomeada"' in h
    # cada entidade do resumo e um link para o filtro pelo nome canonico (a UF vai junto quando a entidade e de uma UF so)
    assert 'href="/achados?solucao=Delta+Bot&amp;uf=PI"' in h and 'href="/achados?solucao=Delta+Bot&amp;uf=SP"' in h
    assert verificar(h) == []


def test_entidades_o_filtro_por_nome_canonico_traz_todas_as_grafias_da_entidade(modelo_entidades):
    cli, ids, banco, _ = modelo_entidades
    h = cli.get("/achados?solucao=Delta+Bot&uf=PI").text
    assert _total(h) == 3                                                 # "Delta Bot", "DB Bot" e "Delta-Bot": a mesma solucao do cadastro
    for i in (ids["a_delta"], ids["db_bot"], ids["delta_hifen"]):
        assert f'href="/achados/{i}"' in h
    assert f'href="/achados/{ids["sp"]["Delta Bot"][0]}"' not in h        # a mesma grafia no SP e outra entidade
    assert _total(cli.get("/achados?solucao=Delta+Bot&uf=SP").text) == 1
    assert _total(cli.get("/achados?solucao=Delta+Bot").text) == 4        # sem UF: as entidades que tem o mesmo nome canonico
    assert _total(cli.get("/achados?solucao=Policiamento+Preditivo+Inteligente").text) == 2     # typo unido por semelhanca
    assert _total(cli.get("/achados?solucao=BO+F%C3%A1cil").text) == 2
    # a busca q continua valendo sobre o texto bruto, sem unir nada
    assert _total(cli.get("/achados?q=Delta-Bot").text) == 1 and _total(cli.get("/achados?q=DB+Bot").text) == 2     # o texto bruto, tambem na evidencia
    assert _total(cli.get("/achados?q=Delta").text) >= 3


def test_entidades_filtro_combina_com_outros_filtros_e_com_a_fila(modelo_entidades):
    cli, ids, banco, _ = modelo_entidades
    assert "solucao=Delta+Bot" in cli.get("/achados?solucao=Delta+Bot&uf=PI&verificacao=pendente").text
    r = cli.get("/revisao/achados?solucao=Delta+Bot&uf=PI", follow_redirects=False)
    assert r.status_code == 303 and "solucao=Delta+Bot" in r.headers["location"]
    assert int(re.search(r"/achados/(\d+)", r.headers["location"]).group(1)) in (ids["a_delta"], ids["db_bot"], ids["delta_hifen"])
    assert verificar(cli.get(r.headers["location"]).text) == []


def test_entidades_nome_desconhecido_nao_filtra_e_nomeada_continua(modelo_entidades):
    cli, *_ = modelo_entidades
    todos = _total(cli.get("/achados").text)
    assert _total(cli.get("/achados?solucao=Nome+Que+Nao+E+De+Ninguem").text) == todos
    nomeadas = _total(cli.get("/achados?solucao=nomeada").text)
    assert 0 < nomeadas < todos


def test_entidades_o_selo_mostra_o_canonico_com_dica_das_grafias_reunidas(modelo_entidades):
    cli, ids, _, _ = modelo_entidades
    h = cli.get("/achados?solucao=Delta+Bot&uf=PI").text
    assert 'title="Delta Bot (inclui: DB Bot; Delta-Bot)"' in h
    assert h.count('<span class="solucao-nome">Delta Bot</span>') == 3           # o selo mostra sempre o nome canonico
    assert '<span class="solucao-nome">DB Bot</span>' not in h and '<span class="solucao-nome">Delta-Bot</span>' not in h
    assert 'class="so-leitor"> (inclui: DB Bot; Delta-Bot)</span>' in h             # leitor de tela tambem ouve a dica
    assert "Entidade «Delta Bot»" in texto(h)
    # sem nada unificado nao ha dica no selo
    h2 = cli.get("/achados?solucao=Radar+Alfa&uf=SP").text
    assert "inclui:" not in h2.split("<table", 1)[1]


def test_entidades_detalhe_mostra_o_canonico_e_o_valor_bruto_como_o_modelo_escreveu(modelo_entidades):
    cli, ids, _, _ = modelo_entidades
    d = cli.get(f"/achados/{ids['db_bot']}").text                                  # grafia bruta "DB Bot"
    assert '<span class="solucao-nome">Delta Bot</span>' in d
    assert "Como o modelo escreveu: <q>DB Bot</q>" in d
    assert "<dt>Como o modelo escreveu</dt><dd>DB Bot</dd>" in d
    assert 'href="/achados?solucao=Delta+Bot&amp;uf=PI"' in d and "ver os 3 achado(s) desta solução" in d
    assert "O painel a reúne ao nome «Delta Bot» (cadastro: «DB Bot» equivale ao apelido cadastrado «DB Bot» de Delta Bot)" in texto(d)
    assert "/achados?q=DB%20Bot" in d                                                  # o link da busca pelo texto bruto continua
    so = cli.get(f"/achados/{ids['sp']['Radar Alfa'][0]}").text                        # "Radar Alfa": nada unificado
    assert "Como o modelo escreveu: <q>Radar Alfa</q>" in so and "O painel a reúne" not in so
    assert verificar(d) == []


def test_entidades_pagina_do_estado_mostra_o_canonico(modelo_entidades):
    cli, *_ = modelo_entidades
    h = cli.get("/estados/PI").text
    assert '<span class="solucao-nome">Delta Bot</span>' in h and 'title="Delta Bot (inclui: DB Bot; Delta-Bot)"' in h
    assert '<span class="solucao-nome">DB Bot</span>' not in h


def test_entidades_regra_da_uf_e_siglas_na_lista(modelo_entidades):
    cli, ids, banco, ctx = modelo_entidades
    r = resolver_entidades(_contagens(banco), ctx.solucoes_conhecidas)
    assert r.entidade_de("Delta Bot", "PI").conhecida is not None and r.entidade_de("Delta Bot", "SP").conhecida is None
    assert r.entidade_de("SNA", "SP") is r.entidade_de("Sistema Sigma Nacional Aberto", "SP")
    assert r.entidade_de("Operação Zeta I", "SP") is not r.entidade_de("Operação Zeta II", "SP")
    assert r.entidade_de("Radar Alfa", "SP") is not r.entidade_de("Radar Alfa", "RJ")
    h = cli.get("/achados?solucao=SNA&uf=SP").text
    assert _total(h) == 2 and "inclui:" in h
    assert _total(cli.get("/achados?solucao=Opera%C3%A7%C3%A3o+Zeta+I&uf=SP").text) == 1
    assert _total(cli.get("/achados?solucao=Radar+Alfa&uf=SP").text) == 2 and _total(cli.get("/achados?solucao=Radar+Alfa&uf=RJ").text) == 1


def test_entidades_nome_com_html_e_escapado_nas_opcoes_no_resumo_e_na_dica(modelo_entidades):
    cli, ids, _, _ = modelo_entidades
    for url in ("/achados", f"/achados/{ids['sp']['<i>Raro</i>'][0]}", "/estados/SP", "/solucoes", "/achados?solucao=" + quote("<i>Raro</i>")):
        h = cli.get(url).text
        assert "<i>Raro</i>" not in h and "&lt;i&gt;Raro&lt;/i&gt;" in h, url
        assert verificar(h) == [], url


def test_entidades_seletor_de_solucao_lista_os_nomes_canonicos(modelo_entidades):
    cli, *_ = modelo_entidades
    h = cli.get("/achados?solucao=Delta+Bot&uf=PI").text
    assert '<option value="Delta Bot" selected>Delta Bot</option>' in h and '<option value="nomeada">só as nomeadas</option>' in h
    assert h.count('<option value="Delta Bot"') == 1                                 # duas entidades com o mesmo nome: uma opcao so
    assert '<option value="DB Bot"' not in h                                         # grafia bruta nao e opcao


def test_entidades_solucoes_cartoes_somam_as_variantes_ao_cadastro(modelo_entidades):
    cli, ids, banco, ctx = modelo_entidades
    h = cli.get("/solucoes").text
    delta = cartao(h, "Delta Bot")
    assert "<code>DB Bot</code>" in delta and "<code>Delta-Bot</code>" in delta and "pelo cadastro" in delta
    assert "unificado por semelhança" not in delta
    assert linha_do_resumo(h, "Delta Bot")[4] == "3"                                    # os tres achados do PI; o "Delta Bot" do SP e de outra entidade
    poli = cartao(h, "Policiamento Preditivo Inteligente")
    assert "<code>Policiamnto Preditivo Inteligente</code>" in poli and "unificado por semelhança" in poli
    assert "semelhança lexical" in poli and "Ver os 2 achados da entidade" in texto(poli)
    assert linha_do_resumo(h, "Policiamento Preditivo Inteligente")[4] == "2"           # o typo entra na conta mesmo sem citar o nome exato
    assert "pela grafia «Policiamnto Preditivo Inteligente», unificada a este nome" in texto(poli)
    assert "Situação: Citada em achados" in texto(poli)


def test_entidades_solucoes_tabela_de_todas_as_nomeadas_marca_as_camadas(modelo_entidades):
    cli, *_ = modelo_entidades
    h = cli.get("/solucoes").text
    secao = re.search(r'<section class="cartao" aria-labelledby="todas-nomeadas-h".*?</section>', h, re.S).group(0)
    assert "pelo cadastro" in secao and "sigla e nome por extenso" in secao and "unificado por semelhança" in secao
    assert "<code>Sistema Sigma Nacional Aberto</code>" in secao and "<code>SNA</code>" in secao
    assert "fora da lista" in secao and "solução conhecida" in secao
    assert ">Operação Zeta I</a>" in secao and ">Operação Zeta II</a>" in secao                     # nada escondido: sao entidades diferentes
    assert "&lt;i&gt;Raro&lt;/i&gt;" in secao
    assert verificar(h) == []


def test_entidades_nunca_alteram_o_valor_bruto_nem_o_banco(modelo_entidades):
    cli, ids, banco, _ = modelo_entidades
    antes_nomes, antes_bytes = _nomes_no_banco(banco), banco.read_bytes()
    for url in ("/achados", "/achados?solucao=Delta+Bot&uf=PI", "/achados?solucao=nomeada&p=2", f"/achados/{ids['db_bot']}", "/estados/PI", "/solucoes",
                "/revisao/achados?solucao=Delta+Bot&uf=PI"):
        assert cli.get(url, follow_redirects=True).status_code == 200, url
    assert _nomes_no_banco(banco) == antes_nomes and banco.read_bytes() == antes_bytes
    assert dict(antes_nomes)[ids["db_bot"]] == "DB Bot" and dict(antes_nomes)[ids["delta_hifen"]] == "Delta-Bot"       # como o modelo escreveu


def test_entidades_cache_e_invalidado_quando_o_conjunto_de_nomes_muda(modelo_entidades, tmp_path):
    cli, ids, banco, ctx = modelo_entidades
    copia = tmp_path / "c.db"
    shutil.copy(banco, copia)
    app, ctx2 = _app(copia, banco.parent / "raw", tmp_path)
    ctx2.solucoes_conhecidas = ctx.solucoes_conhecidas
    c2 = TestClient(app)
    assert _total(c2.get("/achados?solucao=Radar+Alfa&uf=SP").text) == 2
    con = sqlite3.connect(copia)
    con.execute("UPDATE achados SET nome_solucao='RADAR ALFA' WHERE achado_id=?", (ids["sp"]["B.O. Fácil"][0],))        # uma grafia nova na base
    con.commit()
    con.close()
    assert _total(c2.get("/achados?solucao=Radar+Alfa&uf=SP").text) == 3                                              # entrou na entidade existente
    assert _total(c2.get("/achados?solucao=B.O.+F%C3%A1cil&uf=SP").text) == _total(c2.get("/achados?uf=SP").text)   # grafia bruta (nao e nome canonico): nao filtra


def test_entidades_a_demonstracao_mostra_cada_camada_e_a_regra_da_uf(demo):
    import painel_demo
    banco, _ = demo
    r = resolver_entidades(_contagens(banco), painel_demo.SOLUCOES_CONHECIDAS_DEMO)
    assert {v.camada for e in r.entidades for v in e.variantes} == {0, 1, 2, 3}
    assert r.entidade_de("Rosto-Seguro", "SP") is r.entidade_de("Rosto Seguro", "SP") and r.entidade_de("Rosto Seguro", "SP").canonico == "Rosto Seguro"
    assert r.entidade_de("P. Atenta", "RJ").camada_max == 1 and r.entidade_de("P. Atenta", "RJ").canonico == "Placa Atenta"
    assert r.entidade_de("STIO", "BA") is r.entidade_de("Sistema de Triagem Inteligente de Ocorrências", "BA")
    assert r.entidade_de("SIPAT", "GO") is r.entidade_de("SIPAT - Sistema Integrado de Patrulhamento", "GO")
    assert r.entidade_de("PlacaAtenta", "PR") is r.entidade_de("Placa Atenta", "PR") and r.entidade_de("Placa Atenta", "PR").conhecida is None
    assert r.entidade_de("Placa Atenta", "PR") is not r.entidade_de("Placa Atenta", "RJ")          # o cadastro do RJ nao absorve o nome de outra UF
