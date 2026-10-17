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
