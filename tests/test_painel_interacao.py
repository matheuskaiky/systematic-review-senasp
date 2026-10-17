"""Melhorias progressivas do painel (painel.js): ordenacao de colunas e atalho "/" para a busca.

pytest nao executa JavaScript: a primeira parte confere o MARCADO (atributos, cabecalhos em texto simples sem o script, ausencia de
manipuladores embutidos) e o que o proprio painel.js declara. A segunda parte, em um navegador Chromium de verdade, confere o
COMPORTAMENTO; ela e pulada, com o motivo escrito, quando o Chromium ou o Playwright nao estao disponiveis nesta maquina."""
import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, _app_demo_com_solucoes, demo  # noqa: E402,F401

PAINEL = Path(__file__).resolve().parent.parent / "painel"
JS = (PAINEL / "static" / "painel.js").read_text(encoding="utf-8")
CSS = (PAINEL / "static" / "painel.css").read_text(encoding="utf-8")
PAGINAS_DE_BUSCA = ("/achados", "/literatura/artigos", "/buscar-texto", "/chamadas")


@pytest.fixture(scope="module")
def cli(demo, tmp_path_factory):
    return _app_demo_com_solucoes(demo, tmp_path_factory.mktemp("interacao"))[0]


def _tabelas(html):
    return re.findall(r"<table[^>]*>", html)


# ============================== marcado ==============================
def test_tabelas_de_estados_solucoes_e_chamadas_sao_ordenaveis(cli):
    for rota in ("/estados", "/solucoes", "/chamadas"):
        html = cli.get(rota).text
        marcadas = [t for t in _tabelas(html) if "data-ordenavel" in t]
        assert len(marcadas) == 1, (rota, _tabelas(html))
        assert "<script" not in re.sub(r'<script src="/static/[a-z_]+\.js"[^>]*></script>', "", html)


def test_cabecalho_sem_javascript_e_texto_simples_e_a_ordenacao_e_opt_in(cli):
    html = cli.get("/estados").text
    cabecalho = re.search(r"<thead>.*?</thead>", html, re.S).group(0)
    assert "<button" not in cabecalho and "aria-sort" not in cabecalho and "Achados</th>" in cabecalho     # o botao e o aria-sort nascem no navegador
    # onde a ordem do servidor e o ponto, nada e marcado: fila de revisao, PRISMA, listas de achados/artigos, execucoes
    for rota in ("/achados", "/literatura/artigos", "/literatura/prisma", "/execucoes", "/analises?secao=operacao"):
        assert "data-ordenavel" not in cli.get(rota).text, rota


def test_celulas_numericas_e_de_data_carregam_data_valor(cli):
    estados = cli.get("/estados").text
    assert re.search(r'<td class="num" data-valor="\d+">', estados)
    chamadas = cli.get("/chamadas").text
    assert re.search(r'<td data-valor="20\d\d-\d\d-\d\dT[^"]+">\d\d/\d\d/20\d\d', chamadas)
    assert re.search(r'<td class="num" data-valor="\d+">[\d.]+ ms</td>', chamadas)
    assert 'data-valor="None"' not in chamadas and 'data-valor="None"' not in cli.get("/solucoes").text
    solucoes = cli.get("/solucoes").text
    assert len(re.findall(r'<td class="quebra" data-valor="[0-3]">', solucoes)) == 5


def test_a_dica_de_ordenacao_so_existe_onde_ha_paginacao_e_nasce_escondida(cli):
    chamadas = cli.get("/chamadas").text
    dica = re.search(r'<p class="dica-ordenar" data-dica-ordenar hidden>(.*?)</p>', chamadas, re.S)
    assert dica and "só para as linhas desta página" in dica.group(1) and "não reordena as demais páginas" in dica.group(1)
    assert "data-dica-ordenar" not in cli.get("/estados").text and "data-dica-ordenar" not in cli.get("/solucoes").text


def test_campos_de_busca_declaram_o_atalho(cli):
    for rota in PAGINAS_DE_BUSCA:
        html = cli.get(rota).text
        campos = re.findall(r"<input[^>]*data-atalho-busca[^>]*>", html)
        assert len(campos) == 1, rota
        assert 'aria-keyshortcuts="/"' in campos[0] and 'name="q"' in campos[0], (rota, campos[0])


def test_nenhum_manipulador_embutido_nas_paginas_com_as_novas_funcoes(cli):
    for rota in ("/estados", "/solucoes", "/chamadas") + PAGINAS_DE_BUSCA:
        html = cli.get(rota).text
        assert not re.search(r"\son[a-z]+\s*=", html) and 'style="' not in html and "javascript:" not in html, rota
        assert '<script src="/static/painel.js" defer></script>' in html, rota


def test_a_barra_nao_conflita_com_os_atalhos_da_revisao():
    teclas = set()
    for modelo in (PAINEL / "templates").glob("*.html"):
        teclas |= set(re.findall(r'data-tecla="([^"]+)"', modelo.read_text(encoding="utf-8")))
    assert "/" not in teclas and teclas, teclas       # os atalhos da revisao (1 a 6, d, n, u, i, x, p) continuam sendo so de letras e numeros


# ============================== o que o painel.js declara ==============================
def test_painel_js_tem_a_ordenacao_e_o_atalho_sem_dependencias():
    for trecho in ("table[data-ordenavel]", "aria-sort", '"ascending"', '"descending"', '"none"', "Intl.Collator", '"pt-BR"', "numeric: true",
                   'role", "status"', "aria-live", "data-valor", "data-dica-ordenar", "input[data-atalho-busca]", 'e.key !== "/"', '"Escape"',
                   "isContentEditable", "ctrlKey", "metaKey", "altKey"):
        assert trecho in JS, trecho
    for proibido in ("eval(", "innerHTML", "document.write", "XMLHttpRequest", "fetch(", "import(", "http://", "https://", "jQuery", "require("):
        assert proibido not in JS, proibido
    # os comportamentos que ja existiam continuam
    for trecho in ("irParaEvidencia", "details.menu-grupo", "data-tecla", "requestSubmit", "painel.menu."):
        assert trecho in JS, trecho


def test_css_da_ordenacao_usa_so_tokens_e_volta_a_texto_no_papel():
    regras = [l for l in CSS.splitlines() if "ordenar" in l or "aria-sort" in l or "atalho-dica" in l]
    assert len(regras) >= 8
    for linha in regras:
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", linha), linha                # nada de cor em hexadecimal fora dos tokens
    assert "var(--acento)" in " ".join(regras) and "var(--texto)" in " ".join(regras)
    impressao = CSS.split("@media print {")[1]
    assert "th button.ordenar" in impressao and ".ordenar-seta" in impressao and "display: none !important" in impressao


# ============================== comportamento no Chromium (pulado, com motivo, se nao houver navegador) ==============================
def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def navegador(demo, tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright não está instalado neste ambiente: o comportamento do painel.js não foi conferido no navegador.")
    import uvicorn
    pasta = tmp_path_factory.mktemp("navegador")
    app, ctx = _app(demo[0], demo[1], pasta)       # com revisao habilitada (os botoes de atalho existem); este teste so le, nunca decide
    ctx.hosts_permitidos = ("127.0.0.1", "localhost")
    from painel_demo import SOLUCOES_CONHECIDAS_DEMO
    ctx.solucoes_conhecidas = SOLUCOES_CONHECIDAS_DEMO
    porta = _porta_livre()
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="error"))
    fio = threading.Thread(target=servidor.run, daemon=True)
    fio.start()
    for _ in range(100):
        if servidor.started:
            break
        time.sleep(0.05)
    playwright = sync_playwright().start()
    try:
        chromium = playwright.chromium.launch()
    except Exception as erro:       # noqa: BLE001 - sem o executavel ou sem as bibliotecas do sistema, o motivo vai na mensagem do skip
        playwright.stop()
        servidor.should_exit = True
        pytest.skip(f"Chromium não pôde ser aberto ({str(erro).splitlines()[0][:120]}): o comportamento do painel.js não foi conferido no navegador. "
                    "Instale o navegador (playwright install chromium) e as bibliotecas do sistema.")
    yield chromium, f"http://127.0.0.1:{porta}"
    chromium.close()
    playwright.stop()
    servidor.should_exit = True
    fio.join(timeout=5)


@pytest.fixture
def pagina(navegador):
    chromium, base = navegador
    ctx = chromium.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.goto_rota = lambda rota: pg.goto(base + rota)
    yield pg
    ctx.close()


def expect(localizador):
    from playwright.sync_api import expect as esperar
    return esperar(localizador)


def _th(pg, texto):
    """O <th> (da tabela ordenavel) cujo titulo e `texto`, e o botao dentro dele."""
    th = pg.locator("table[data-ordenavel] thead th").filter(has_text=re.compile(rf"^\s*{re.escape(texto)}\s*$"))
    return th, th.locator("button.ordenar")


def _numeros(pg, coluna):
    return [float(t.replace(".", "").replace(",", ".")) for t in pg.eval_on_selector_all(
        f"table[data-ordenavel] tbody tr td:nth-child({coluna})", "els => els.map(e => e.textContent.trim())")]


def test_navegador_clicar_no_cabecalho_ordena_e_atualiza_aria_sort(pagina):
    pagina.goto_rota("/estados")
    th, botao = _th(pagina, "Achados")
    assert th.get_attribute("aria-sort") == "none"
    links_antes = pagina.locator("table[data-ordenavel] tbody a").count()
    original = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:first-child", "els => els.map(e => e.textContent.trim())")
    botao.click()
    assert th.get_attribute("aria-sort") == "ascending"
    cresc = _numeros(pagina, 3)
    assert cresc == sorted(cresc) and len(cresc) == 27
    botao.click()
    assert th.get_attribute("aria-sort") == "descending"
    decresc = _numeros(pagina, 3)
    assert decresc == sorted(decresc, reverse=True)
    botao.click()
    assert th.get_attribute("aria-sort") == "none"
    assert pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:first-child", "els => els.map(e => e.textContent.trim())") == original
    assert pagina.locator("table[data-ordenavel] tbody a").count() == links_antes
    th_outro, outro = _th(pagina, "Estado")
    botao.click()
    outro.click()
    assert th.get_attribute("aria-sort") == "none" and th_outro.get_attribute("aria-sort") == "ascending"
    nomes = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:nth-child(2)", "els => els.map(e => e.textContent.trim())")
    assert nomes == sorted(nomes, key=lambda n: n.casefold().replace("ã", "a").replace("á", "a").replace("â", "a").replace("é", "e").replace("í", "i").replace("ô", "o").replace("ú", "u").replace("ç", "c"))


def test_navegador_cabecalho_opera_so_com_teclado_e_anuncia_a_ordem(pagina):
    pagina.goto_rota("/estados")
    th, botao = _th(pagina, "Verificados")
    botao.focus()
    pagina.keyboard.press("Enter")
    assert th.get_attribute("aria-sort") == "ascending"
    expect(pagina.locator("#anuncio-ordem")).to_have_text("Tabela ordenada por Verificados, em ordem crescente.")
    assert pagina.get_attribute("#anuncio-ordem", "aria-live") == "polite"
    pagina.keyboard.press("Space")
    assert th.get_attribute("aria-sort") == "descending"
    expect(pagina.locator("#anuncio-ordem")).to_have_text("Tabela ordenada por Verificados, em ordem decrescente.")


def test_navegador_chamadas_numeros_datas_e_vazios_e_a_dica_aparece(pagina):
    pagina.goto_rota("/chamadas")
    assert pagina.locator("[data-dica-ordenar]").is_visible()
    botao = _th(pagina, "Latência")[1]
    botao.click()
    lat = [int(t.replace(".", "").replace(" ms", "")) for t in pagina.eval_on_selector_all(
        "table[data-ordenavel] tbody tr td:nth-child(7)", "els => els.map(e => e.textContent.trim())")]
    assert lat == sorted(lat)
    _th(pagina, "Quando")[1].click()
    datas = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:nth-child(2)", "els => els.map(e => e.getAttribute('data-valor'))")
    assert datas == sorted(datas)
    _th(pagina, "Custo")[1].click()      # "—" vai para o fim
    custos = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:nth-child(8)", "els => els.map(e => e.textContent.trim())")
    vazios = [i for i, c in enumerate(custos) if c == "—"]
    assert not vazios or vazios == list(range(len(custos) - len(vazios), len(custos)))
    _th(pagina, "Custo")[1].click()      # decrescente: o vazio continua no fim
    custos = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:nth-child(8)", "els => els.map(e => e.textContent.trim())")
    vazios = [i for i, c in enumerate(custos) if c == "—"]
    assert not vazios or vazios == list(range(len(custos) - len(vazios), len(custos)))


def test_navegador_solucoes_ordena_pela_profundidade_do_funil(pagina):
    pagina.goto_rota("/solucoes")
    _th(pagina, "Situação")[1].click()
    ordem = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr td:last-child", "els => els.map(e => e.getAttribute('data-valor'))")
    assert ordem == sorted(ordem) and ordem[0] == "0" and ordem[-1] == "3"
    _th(pagina, "Solução")[1].click()
    nomes = pagina.eval_on_selector_all("table[data-ordenavel] tbody tr th a", "els => els.map(e => e.textContent.trim())")
    assert nomes == sorted(nomes, key=str.casefold) and nomes[0] == "Guardião Digital"


def test_navegador_barra_foca_a_busca_e_nao_rouba_a_digitacao(pagina):
    for rota in PAGINAS_DE_BUSCA:
        pagina.goto_rota(rota)
        assert pagina.evaluate("document.activeElement.name") != "q"
        assert pagina.locator("kbd.atalho-dica").first.is_visible(), rota                # a dica "/" aparece no rotulo (so com JavaScript)
        assert pagina.get_attribute("input[data-atalho-busca]", "aria-keyshortcuts") == "/"
        pagina.keyboard.press("/")
        assert pagina.evaluate("document.activeElement.name") == "q", rota
        assert pagina.input_value("input[data-atalho-busca]") == ""                       # a barra nao foi digitada no campo
        pagina.keyboard.type("a/b")
        assert pagina.input_value("input[data-atalho-busca]") == "a/b" and pagina.evaluate("document.activeElement.name") == "q"
        pagina.keyboard.press("Escape")
        assert pagina.evaluate("document.activeElement.name") != "q"
        assert pagina.input_value("input[data-atalho-busca]") == "a/b"                    # Esc devolve o foco sem apagar o texto
        pagina.keyboard.press("Control+/")
        assert pagina.evaluate("document.activeElement.name") != "q"                      # com modificador o atalho e ignorado


def test_navegador_barra_em_outro_campo_nao_move_o_foco(pagina):
    pagina.goto_rota("/achados")
    pagina.focus("select[name=uf]")
    pagina.keyboard.press("/")
    assert pagina.evaluate("document.activeElement.name") == "uf"
    pagina.goto_rota("/estados")                       # pagina sem campo de busca: a barra nao faz nada e nao da erro
    erros = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.keyboard.press("/")
    assert not erros


def test_navegador_os_atalhos_da_revisao_continuam(pagina, demo):
    import sqlite3
    achado = sqlite3.connect(demo[0]).execute("SELECT MIN(achado_id) FROM v_achados_revisao WHERE verificado=0").fetchone()[0]
    pagina.goto_rota(f"/achados/{achado}")
    erros = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    assert pagina.locator("[data-tecla]").count() > 0
    pagina.keyboard.press("e")                          # 'e' (ir a evidencia) segue funcionando e a barra nao atrapalha
    pagina.keyboard.press("/")
    assert not erros and pagina.evaluate("document.activeElement.tagName") != "INPUT"
