"""Barras horizontais com link por barra: so caminhos do proprio painel viram link (a mesma regra dos outros graficos), a
barra sem link fica como era, e o grafico sem links nao muda."""
from painel import graficos, graficos_analises

ITENS = [("Só A", 3), ("Só B", 0), ("A + C", 2)]


def test_sem_links_nao_muda():
    assert graficos.barras_horizontais(ITENS, "t", "d") == graficos.barras_horizontais(ITENS, "t", "d", hrefs=None)
    assert "<a " not in graficos.barras_horizontais(ITENS, "t", "d")


def test_link_por_barra_e_rotulo_acessivel():
    svg = graficos.barras_horizontais(ITENS, "t", "d", str, hrefs=["/observatorio/obras?combinacao=A", None,
                                                                     "/observatorio/obras?combinacao=A%2BC&x=1"])
    assert svg.count('<a class="an-link"') == 2
    assert '<a class="an-link" href="/observatorio/obras?combinacao=A" aria-label="Só A: 3 (ver os registros)">' in svg
    assert 'href="/observatorio/obras?combinacao=A%2BC&amp;x=1"' in svg
    sem_link = svg.split('aria-label="Só A: 3 (ver os registros)">', 1)[1].split("</a>", 1)[1]
    assert sem_link.split("Só B", 1)[0].count("<a ") == 0


def test_cada_barra_inteira_fica_dentro_do_link():
    svg = graficos.barras_horizontais(ITENS[:1], "t", "d", str, hrefs=["/x"])
    dentro = svg.split('<a class="an-link"', 1)[1].split("</a>", 1)[0]
    assert 'class="gr-rotulo"' in dentro and 'class="gr-barra"' in dentro and 'class="gr-valor"' in dentro


def test_href_inseguro_nao_vira_link():
    for ruim in ("javascript:alert(1)", "//evil.example/x", "https://evil.example/", "/a b", "/x\\y", 7):
        assert "<a " not in graficos.barras_horizontais(ITENS[:1], "t", "d", str, hrefs=[ruim]), ruim


def test_a_regra_de_link_e_a_dos_outros_graficos(monkeypatch):
    chamadas = []
    original = graficos_analises._link

    def contada(href, rotulo, conteudo):
        chamadas.append(href)
        return original(href, rotulo, conteudo)
    monkeypatch.setattr(graficos_analises, "_link", contada)
    graficos.barras_horizontais(ITENS, "t", "d", str, hrefs=["/a", None, "/c"])
    assert chamadas == ["/a", "/c"]


# ---------- pre-revisao ----------
def test_saida_sem_links_igual_a_de_antes():
    """Hashes da saida de antes desta mudanca (F105), para dois graficos fixos."""
    import hashlib
    assert hashlib.sha256(graficos.barras_horizontais(ITENS, "t", "d").encode()).hexdigest() == "1c3713eb9ebaaf68135aeb2d199bf3e79e2e43c67be15f2242510d824be11022"
    assert hashlib.sha256(graficos.barras_horizontais([("Um rótulo bem comprido para cortar no meio do caminho", 1234567)],
                                                      "título", "descrição", str, 285, 44).encode()).hexdigest() == "71cd53676e32fc8039b435da5bacfbcb347e91467165898bf1ff920eba5d39fd"


def test_ordem_dos_elementos_dentro_do_link():
    svg = graficos.barras_horizontais(ITENS[:1], "t", "d", str, hrefs=["/x"])
    dentro = svg.split('<a class="an-link"', 1)[1].split("</a>", 1)[0]
    assert dentro.index('class="gr-rotulo"') < dentro.index('class="gr-barra"') < dentro.index('class="gr-valor"')
