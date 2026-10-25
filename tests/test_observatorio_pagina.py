"""A pagina do Observatorio do banco `vies` (/observatorio): o cabecalho com unidade, universo, versao e hora da leitura, as
tres perspectivas com composicoes proprias, os filtros GET compartilhados com a lista, a matriz cujas celulas levam a lista
com exatamente as mesmas obras, os indicadores indisponiveis ditos como tal, e uma so leitura consistente por resposta."""
import re
from urllib.parse import unquote

import pytest

from dominio import observatorio_vies as OV
from test_leitura_instantaneo import _Rastreada, rastreio, renderizacoes  # noqa: F401
from test_observatorio_obras import _cli, _total, sintetico  # noqa: F401
from test_observatorio_vies import NOMES, RECORTES, _corpus, _filtros
from test_validacao_vies import banco  # noqa: F401

IDS = {"integrada": ["obs-matriz", "obs-combinacoes", "obs-identidade"],
       "vies": ["obs-vies-total", "obs-vies-eixos", "obs-vies-grupos", "obs-vies-origem", "obs-vies-indisponivel"],
       "tecnologias": ["obs-tec-total", "obs-tec-eixos", "obs-tec-origem", "obs-tec-topicos", "obs-tec-indisponivel"]}
INTERSECAO = ("Interseção temática entre viés e aplicações: indisponível na triagem v2. Requer classificação temática "
              "independente e multirrótulo.")


def _ids_blocos(html):
    return re.findall(r'<section class="an-bloco" id="([^"]+)"', html)


def _bloco(html, id_):
    return html.split(f'<section class="an-bloco" id="{id_}"', 1)[1].split("</section>", 1)[0]


# ---------- so no banco vies; erros ----------
def test_so_no_banco_vies(banco, tmp_path):
    r = _cli(banco, tmp_path, nome="real").get("/observatorio")
    assert r.status_code == 404 and "<h1>Página não encontrada</h1>" in r.text
    assert "O Observatório existe só no banco vies." in r.text


def test_banco_ausente(tmp_path):
    assert _cli(tmp_path / "nao_existe.db", tmp_path).get("/observatorio").status_code == 503


@pytest.mark.parametrize("consulta, mensagem", [
    ("fonte=x", "Filtro inválido: fonte."),
    ("perspectiva=vies&angulo=vies_algoritmico", "O ângulo já é definido pela perspectiva: tire o filtro de ângulo."),
    ("perspectiva=x", "Filtro inválido: perspectiva."),
])
def test_filtro_invalido(sintetico, rastreio, consulta, mensagem):
    cli, _ = sintetico
    rastreio.todas.clear()
    r = cli.get(f"/observatorio?{consulta}")
    assert r.status_code == 400 and "<h1>Filtro inválido</h1>" in r.text and mensagem in r.text
    assert rastreio.todas == []


def test_pagina_na_url_e_ignorada(sintetico):
    cli, _ = sintetico
    assert cli.get("/observatorio?pagina=99").status_code == 200


# ---------- cabecalho ----------
def test_cabecalho(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio").text
    assert "<h1>Observatório Analítico — Inteligência Artificial e Segurança Pública</h1>" in html
    assert ('<p class="aviso" role="status"><strong>Retratos da busca e dos rótulos automáticos.</strong> Os números '
            "descrevem as obras recuperadas pelas consultas desta busca e classificadas automaticamente pela triagem v2, sem "
            "conferência humana nem codificação temática: não são uma síntese validada da literatura nem inclusão na "
            "revisão.</p>") in html
    ficha = re.search(r'<dl class="obs-ficha">(.*?)</dl>', html, re.S).group(1)
    pares = re.findall(r"<dt>([^<]+)</dt><dd>([^<]+)</dd>", ficha)
    assert [k for k, _ in pares] == ["Obras", "Versão da triagem", "Dados lidos em"]
    assert pares[0][1] == "4 obras · universo: Relevância alta ou média"
    from config.triagem_escopo import PROMPT_TRIAGEM_VIES_VERSAO
    assert pares[1][1] == PROMPT_TRIAGEM_VIES_VERSAO
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", pares[2][1])


@pytest.mark.parametrize("consulta, texto", [
    ("universo=todas", "6 obras · universo: Todas as obras"),
    ("fonte=ambas", "1 obra · universo: Relevância alta ou média"),
    ("perspectiva=vies", "2 obras · universo: Relevância alta ou média"),
])
def test_obras_do_cabecalho_seguem_os_filtros(sintetico, consulta, texto):
    cli, _ = sintetico
    assert f"<dt>Obras</dt><dd>{texto}</dd>" in cli.get(f"/observatorio?{consulta}").text


# ---------- perspectivas ----------
def _abas(html):
    nav = re.search(r'<nav class="an-abas" aria-label="Perspectivas do Observatório">(.*?)</nav>', html, re.S).group(1)
    return re.findall(r'<a href="([^"]+)"( aria-current="page")?>([^<]+)</a>', nav)


def test_abas_das_perspectivas_preservam_os_filtros_e_tiram_o_angulo(sintetico):
    cli, _ = sintetico
    abas = _abas(cli.get("/observatorio?fonte=web&angulo=vies_algoritmico").text)
    assert abas == [("/observatorio?fonte=web&amp;angulo=vies_algoritmico", " aria-current=\"page\"", "Integrada"),
                    ("/observatorio?perspectiva=vies&amp;fonte=web", "", "Viés algorítmico e discriminação"),
                    ("/observatorio?perspectiva=tecnologias&amp;fonte=web", "", "Aplicações tecnológicas de IA")]
    abas = _abas(cli.get("/observatorio?perspectiva=tecnologias").text)
    assert [(h, bool(a)) for h, a, _ in abas] == [("/observatorio", False), ("/observatorio?perspectiva=vies", False),
                                                  ("/observatorio?perspectiva=tecnologias", True)]


@pytest.mark.parametrize("perspectiva", ["integrada", "vies", "tecnologias"])
def test_cada_perspectiva_tem_a_sua_composicao(sintetico, perspectiva):
    cli, _ = sintetico
    html = cli.get(f"/observatorio?perspectiva={perspectiva}").text
    assert _ids_blocos(html) == IDS[perspectiva]


def test_todo_bloco_diz_unidade_e_universo(sintetico):
    cli, _ = sintetico
    for p in IDS:
        html = cli.get(f"/observatorio?perspectiva={p}").text
        subs = re.findall(r'<p class="an-subtitulo">([^<]+)</p>', html)
        assert len(subs) == len(IDS[p]), p
        assert all(s.startswith("por obra · universo: ") for s in subs), subs


def test_textos_das_perspectivas(sintetico):
    cli, _ = sintetico
    integrada = cli.get("/observatorio").text
    assert INTERSECAO in _bloco(integrada, "obs-matriz")
    vies = cli.get("/observatorio?perspectiva=vies").text
    assert "2 obras com viés algorítmico como ângulo predominante" in _bloco(vies, "obs-vies-total")
    assert ("O ângulo predominante não mede quantas obras tratam de viés: uma obra classificada como aplicação "
            "tecnológica também pode discutir o tema, e a triagem v2 dá um só ângulo por obra.") in vies
    assert "Tipos de discriminação, riscos e grupos afetados: indisponíveis" in _bloco(vies, "obs-vies-indisponivel")
    assert "não são zero" in _bloco(vies, "obs-vies-indisponivel")
    tec = cli.get("/observatorio?perspectiva=tecnologias").text
    assert "1 obra com aplicações tecnológicas como ângulo predominante" in _bloco(tec, "obs-tec-total")
    assert ("Os rótulos dizem do que a obra trata, não se a tecnologia foi implantada, se funciona nem em que estágio "
            "está. Os eixos de exploração não são uma taxonomia de tecnologias.") in tec
    assert "Método, artefato, finalidade e contexto de uso: indisponíveis" in _bloco(tec, "obs-tec-indisponivel")


def test_link_para_as_obras_destes_filtros(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio?perspectiva=vies&fonte=web").text
    assert '<a class="botao secundario" href="/observatorio/obras?perspectiva=vies&amp;fonte=web">Ver as obras destes filtros</a>' in html
    assert '<a class="botao secundario" href="/observatorio/obras">Ver as obras destes filtros</a>' in cli.get("/observatorio").text


def test_formulario_compartilhado_aponta_para_a_pagina(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio?conjunto=C").text
    assert '<form class="filtros" method="get" action="/observatorio">' in html
    assert '<option value="C" selected>C</option>' in html and 'href="/observatorio">Limpar</a>' in html
    assert '<form class="filtros" method="get" action="/observatorio/obras">' in cli.get("/observatorio/obras").text


def test_sem_obras(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio?eixo=E3").text
    assert '<p class="vazio">Nenhuma obra com estes filtros. <a href="/observatorio">Limpar filtros</a></p>' in html
    assert _ids_blocos(html) == []
    assert "<dt>Obras</dt><dd>0 obras · universo: Relevância alta ou média</dd>" in html


# ---------- a matriz leva a lista com as mesmas obras ----------
def _celulas(html):
    """{href: n} dos links das celulas do mapa de calor do bloco da matriz."""
    bloco = _bloco(html, "obs-matriz")
    saida = {}
    for href, conteudo in re.findall(r'<a class="an-link" href="([^"]+)"[^>]*>(.*?)</a>', bloco, re.S):
        n = re.findall(r'<text class="an-ct[^"]*"[^>]*>([^<]+)</text>', conteudo)
        saida[href.replace("&amp;", "&")] = int(n[0].replace(".", ""))
    return saida


@pytest.mark.parametrize("base", ["", "fonte=web", "universo=todas", "eixo=E1", "conjunto=C"])
def test_cada_celula_leva_a_lista_com_o_mesmo_total(sintetico, base):
    cli, _ = sintetico
    celulas = _celulas(cli.get(f"/observatorio?{base}").text)
    obras, _ = OV.projecao(_corpus(), NOMES)
    filtros, _ = OV.ler_filtros([tuple(p.split("=")) for p in base.split("&") if p], NOMES, RECORTES, ("E1", "E2", "E3"))
    m = OV.matriz(OV.filtrar(obras, filtros, RECORTES), NOMES, RECORTES)
    assert len(celulas) == sum(1 for n in m["celulas"].values() if n) > 0     # so as celulas com obras levam a lista
    for href, n in celulas.items():
        assert href.startswith("/observatorio/obras?")
        assert _total(cli.get(href).text) == n, href
    for (l, c), n in m["celulas"].items():
        if n:
            q = "&".join(p for p in [base, f"combinacao={l}", f"angulo={c}"] if p)
            alvo = [h for h in celulas if sorted(unquote(h.split("?", 1)[1]).split("&")) == sorted(unquote(q).split("&"))]
            assert len(alvo) == 1 and celulas[alvo[0]] == n, (l, c)


def test_tabela_da_matriz_com_totais(sintetico):
    cli, _ = sintetico
    bloco = _bloco(cli.get("/observatorio").text, "obs-matriz")
    cab = re.findall(r'<th scope="col">([^<]+)</th>', bloco)
    assert cab == ["Origem", "Viés algorítmico", "Aplicações tecnológicas", "Sem ângulo", "Total de obras"]
    linhas = [re.findall(r"<td[^>]*>([^<]*)</td>", tr) for tr in bloco.split("<tbody>", 1)[1].split("<tr>")[1:]]
    assert linhas[0] == ["Só A", "1", "0", "0", "1"] and linhas[-1] == ["Total", "2", "1", "1", "4"]


def test_combinacoes_e_identidade(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio?universo=todas").text
    comb = _bloco(html, "obs-combinacoes")
    assert "Obras por combinação exata dos conjuntos: 6 obras" in comb
    ident = _bloco(html, "obs-identidade")
    pares = dict(re.findall(r"<dt>([^<]+)</dt><dd>([^<]+)</dd>", ident))
    assert pares == {"Obras com itens da web e do Scholar": "1", "Obras cujos itens divergem em algum rótulo": "1",
                     "Obras com URL compartilhada com outro artigo (possível duplicata)": "0",
                     "Referências da web ambíguas, sem obra (no banco todo)": "0"}
    assert 'href="/observatorio/obras?universo=todas&amp;fonte=ambas">Ver as obras com itens da web e do Scholar</a>' in ident


def test_topicos_marcam_o_termo_de_busca(sintetico):
    cli, _ = sintetico
    bloco = _bloco(cli.get("/observatorio?perspectiva=tecnologias&universo=todas").text, "obs-tec-topicos")
    assert "Tópicos mais citados pelo modelo" in bloco
    assert re.findall(r"<td[^>]*>([^<]*)</td>", bloco.split("<tbody>", 1)[1])[:3] == ["X", "1", "não"]


# ---------- leitura real ----------
def test_uma_leitura_consistente_por_resposta(banco, tmp_path, rastreio, renderizacoes):
    cli = _cli(banco, tmp_path)
    for p in ("integrada", "vies", "tecnologias"):
        rastreio.todas.clear()
        renderizacoes.clear()
        assert cli.get(f"/observatorio?perspectiva={p}&universo=todas").status_code == 200
        assert len(rastreio.todas) == 1 and rastreio.abertas == [] and set(renderizacoes) == {0}


def test_as_paginas_anteriores_nao_mudam(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    for rota in ("/analises", "/analises?secao=consultas", "/", "/observatorio/obras"):
        assert cli.get(rota).status_code == 200, rota


# ---------- pre-revisao ----------
def test_hora_da_leitura_tomada_dentro_da_leitura_consistente(banco, tmp_path, rastreio, monkeypatch):
    from datetime import datetime as _dt
    from painel.rotas_extras import observatorio as RO
    abertas_na_hora, ordem = [], []
    itens_originais = RO.visao_geral_vies.itens

    class Relogio:
        @staticmethod
        def now():
            ordem.append("relogio")
            abertas_na_hora.append(len(rastreio.abertas))
            return _dt(2026, 10, 25, 7, 5)
    monkeypatch.setattr(RO, "datetime", Relogio)
    monkeypatch.setattr(RO.visao_geral_vies, "itens", lambda l, c: (ordem.append("itens"), itens_originais(l, c))[1])
    html = _cli(banco, tmp_path).get("/observatorio").text
    assert ordem == ["itens", "relogio"] and abertas_na_hora == [1]
    assert "<dt>Dados lidos em</dt><dd>25/10/2026 07:05</dd>" in html


@pytest.mark.parametrize("consulta, subtitulo", [
    ("", "por obra · universo: 4 obras, relevância alta ou média"),
    ("universo=todas", "por obra · universo: 6 obras, todas as obras"),
    ("perspectiva=vies", "por obra · universo: 2 obras, relevância alta ou média"),
    ("perspectiva=tecnologias", "por obra · universo: 1 obra, relevância alta ou média"),
])
def test_subtitulo_exato_de_cada_bloco(sintetico, consulta, subtitulo):
    cli, _ = sintetico
    subs = re.findall(r'<p class="an-subtitulo">([^<]+)</p>', cli.get(f"/observatorio?{consulta}").text)
    assert subs and set(subs) == {subtitulo}


def _tabela(bloco):
    corpo = bloco.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [re.findall(r"<td[^>]*>([^<]*)</td>", tr) for tr in corpo.split("<tr>")[1:]]


def test_tabela_da_matriz_inteira(sintetico):
    cli, _ = sintetico
    assert _tabela(_bloco(cli.get("/observatorio").text, "obs-matriz")) == [
        ["Só A", "1", "0", "0", "1"], ["Só B", "0", "0", "0", "0"], ["Só C", "0", "1", "0", "1"],
        ["A + B", "0", "0", "0", "0"], ["A + C", "1", "0", "0", "1"], ["B + C", "0", "0", "0", "0"],
        ["A + B + C", "0", "0", "0", "0"], ["Sem conjunto", "0", "0", "1", "1"], ["Total", "2", "1", "1", "4"]]


COMB_PADRAO = [["Só A", "1"], ["Só B", "0"], ["Só C", "1"], ["A + B", "0"], ["A + C", "1"], ["B + C", "0"],
               ["A + B + C", "0"], ["Sem conjunto", "1"]]


@pytest.mark.parametrize("consulta, id_, linhas", [
    ("", "obs-combinacoes", COMB_PADRAO),
    ("universo=todas", "obs-combinacoes", [["Só A", "1"], ["Só B", "1"], ["Só C", "1"], ["A + B", "0"], ["A + C", "1"],
                                           ["B + C", "0"], ["A + B + C", "1"], ["Sem conjunto", "1"]]),
    ("perspectiva=vies", "obs-vies-eixos", [["E1", "2"], ["E2", "0"], ["E3", "0"]]),
    ("perspectiva=vies", "obs-vies-grupos", [["Literatura científica", "2"], ["Literatura cinzenta", "0"],
                                             ["Fonte primária", "0"]]),
    ("perspectiva=vies", "obs-vies-origem", [["Só A", "1"], ["Só B", "0"], ["Só C", "0"], ["A + B", "0"], ["A + C", "1"],
                                             ["B + C", "0"], ["A + B + C", "0"], ["Sem conjunto", "0"]]),
    ("perspectiva=tecnologias", "obs-tec-eixos", [["E2", "1"], ["E1", "0"], ["E3", "0"]]),
    ("perspectiva=tecnologias", "obs-tec-origem", [["Só A", "0"], ["Só B", "0"], ["Só C", "1"], ["A + B", "0"],
                                                   ["A + C", "0"], ["B + C", "0"], ["A + B + C", "0"], ["Sem conjunto", "0"]]),
])
def test_tabelas_das_perspectivas(sintetico, consulta, id_, linhas):
    cli, _ = sintetico
    assert _tabela(_bloco(cli.get(f"/observatorio?{consulta}").text, id_)) == linhas


def test_eixo_ausente_aparece_como_sem_eixo(sintetico):
    cli, _ = sintetico
    linhas = _tabela(_bloco(cli.get("/observatorio?perspectiva=vies&universo=todas&eixo=").text, "obs-vies-eixos"))
    assert linhas == [["E1", "2"], ["E2", "1"], ["E3", "1"]]
    linhas = _tabela(_bloco(cli.get("/observatorio?universo=todas&angulo=sem_angulo").text, "obs-combinacoes"))
    assert linhas[-1] == ["Sem conjunto", "1"]


def test_textos_literais(sintetico):
    cli, _ = sintetico
    integrada = cli.get("/observatorio").text
    matriz = _bloco(integrada, "obs-matriz")
    for t in ("Cada célula conta obras distintas na combinação exata dos conjuntos que as acharam (uma obra achada em A e "
              "em C está só em “A + C”) e no ângulo predominante que o modelo atribuiu. Clique numa célula para ver as "
              "obras que a formam.",
              "As linhas “Só …” mostram o que cada conjunto trouxe sozinho: é ali que se vê se as buscas se complementam.",
              INTERSECAO):
        assert f"<p>{t}</p>" in matriz, t
    assert ("<p>Cada obra conta uma vez, na combinação de todos os conjuntos que acharam os seus itens (web e Scholar). "
            "Uma obra achada em A e em C não conta em “Só A” nem em “Só C”.</p>") in _bloco(integrada, "obs-combinacoes")
    ident = _bloco(integrada, "obs-identidade")
    assert ("<p>Na obra que junta web e Scholar valem os rótulos do artigo do Scholar; a divergência aparece na lista de "
            "obras.</p>") in ident
    assert "<p>As possíveis duplicatas não foram juntadas: juntar ou não é decisão do pesquisador.</p>" in ident
    vies = cli.get("/observatorio?perspectiva=vies").text
    assert ("<p>Estes indicadores ainda não existem: a triagem v2 não os classifica. Requerem a codificação temática "
            "(taxonomia tx1), que ainda não foi aprovada; não são zero.</p>") in _bloco(vies, "obs-vies-indisponivel")
    assert '<a href="/observatorio/obras?perspectiva=vies">Ver estas obras</a>' in _bloco(vies, "obs-vies-total")
    tec = cli.get("/observatorio?perspectiva=tecnologias").text
    assert ("<p>Estes indicadores ainda não existem: a triagem v2 não os classifica. Requerem a codificação temática "
            "(taxonomia tx1), prevista para a Fase 2; não são zero.</p>") in _bloco(tec, "obs-tec-indisponivel")
    assert ("<p>Tópicos atribuídos pelo modelo, contados uma vez por obra (as fora do escopo não contam); “(termo de "
            "busca)” marca o tópico que aparece no texto de alguma consulta.</p>") in _bloco(tec, "obs-tec-topicos")


def test_topicos_corte_de_15_no_grafico_e_todos_na_tabela(sintetico):
    from test_observatorio_vies import _itens, _t, _web
    cli, itens = sintetico
    topicos = "; ".join(["viés algorítmico"] + [f"tópico {i:02d}" for i in range(1, 20)])
    itens["lista"] = _itens([_web(1), _web(2)], [],
                            {("referencia", 1): _t(recorte="aplicacoes_tecnologicas", topicos=topicos),
                             ("referencia", 2): _t(recorte="aplicacoes_tecnologicas", topicos="viés algorítmico")})
    bloco = _bloco(cli.get("/observatorio?perspectiva=tecnologias").text, "obs-tec-topicos")
    linhas = _tabela(bloco)
    assert linhas == [["Viés algorítmico", "2", "sim"]] + [[f"Tópico {i:02d}", "1", "não"] for i in range(1, 20)]
    grafico = bloco.split('<div class="an-grafico">', 1)[1].split("</div>", 1)[0]
    assert re.findall(r'<text class="gr-rotulo"[^>]*>([^<]+)</text>', grafico) == \
        ["Viés algorítmico (termo de busca)"] + [f"Tópico {i:02d}" for i in range(1, 15)]


def test_obra_de_vies_sem_eixo(sintetico):
    from test_observatorio_vies import _itens, _t, _web
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1), _web(2)], [], {("referencia", 1): _t(eixo="E1"), ("referencia", 2): _t(eixo=None)})
    linhas = _tabela(_bloco(cli.get("/observatorio?perspectiva=vies").text, "obs-vies-eixos"))
    assert linhas == [["E1", "1"], ["Sem eixo", "1"], ["E2", "0"], ["E3", "0"]]


def test_link_das_obras_na_perspectiva_tecnologias(sintetico):
    cli, _ = sintetico
    assert ('<a href="/observatorio/obras?perspectiva=tecnologias&amp;fonte=scholar">Ver estas obras</a>'
            in _bloco(cli.get("/observatorio?perspectiva=tecnologias&fonte=scholar").text, "obs-tec-total"))


# ---------- retrabalho R1 ----------
def test_pagina_carrega_a_folha_das_analises(sintetico):
    """O mapa de calor, as abas e os blocos usam as classes de `analises.css`, como na pagina /analises."""
    cli, _ = sintetico
    for rota in ("/observatorio", "/observatorio?perspectiva=vies"):
        assert '<link rel="stylesheet" href="/static/analises.css">' in cli.get(rota).text, rota


# ---------- F1.2: barras de combinacao e de eixo levam a lista ----------
def _barras_com_link(html, id_):
    """{href: n} dos links das barras do bloco `id_`."""
    bloco = _bloco(html, id_)
    saida = {}
    for href, conteudo in re.findall(r'<a class="an-link" href="([^"]+)"[^>]*>(.*?)</a>', bloco, re.S):
        n = re.findall(r'<text class="gr-valor"[^>]*>([^<]+)</text>', conteudo)
        saida[href.replace("&amp;", "&")] = int(n[0].replace(".", ""))
    return saida


@pytest.mark.parametrize("base, id_", [
    ("", "obs-combinacoes"), ("universo=todas", "obs-combinacoes"), ("fonte=web", "obs-combinacoes"),
    ("divergencia=sem", "obs-combinacoes"),
    ("perspectiva=vies", "obs-vies-origem"), ("perspectiva=vies&universo=todas", "obs-vies-origem"),
    ("perspectiva=tecnologias", "obs-tec-origem"),
    ("perspectiva=vies", "obs-vies-eixos"), ("perspectiva=vies&universo=todas", "obs-vies-eixos"),
    ("perspectiva=tecnologias&universo=todas", "obs-tec-eixos"),
])
def test_cada_barra_leva_a_lista_com_o_mesmo_total(sintetico, base, id_):
    cli, _ = sintetico
    links = _barras_com_link(cli.get(f"/observatorio?{base}").text, id_)
    assert links
    linhas = _tabela(_bloco(cli.get(f"/observatorio?{base}").text, id_))
    assert len(links) == sum(1 for l in linhas if l[1] != "0")       # so as barras com obras levam a lista
    from urllib.parse import parse_qsl, urlsplit
    chave = "eixo" if id_.endswith("eixos") else "combinacao"
    for href, n in links.items():
        assert href.startswith("/observatorio/obras?") and _total(cli.get(href).text) == n, href
        pares = parse_qsl(urlsplit(href).query)
        extra = [(k, v) for k, v in pares if (k, v) not in parse_qsl(base)]
        assert [k for k, _ in extra] == [chave], href                 # os filtros ativos ficam; so a chave da barra entra
        assert sorted(set(pares) - set(extra)) == sorted(parse_qsl(base)), href
    # cada barra leva ao valor dela: o rotulo da barra (no aria-label do link) da o valor esperado na URL
    rotulo_para_valor = ({r: k for k, r in OV.combinacoes(NOMES)} if chave == "combinacao" else
                         {"Sem eixo": OV.SEM_EIXO, "E1": "E1", "E2": "E2", "E3": "E3"})
    bloco = _bloco(cli.get(f"/observatorio?{base}").text, id_)
    for href, rotulo in re.findall(r'<a class="an-link" href="([^"]+)" aria-label="([^"]+): [\d.]+ \(ver os registros\)">', bloco):
        valor = dict(parse_qsl(urlsplit(href.replace("&amp;", "&")).query))[chave]
        assert valor == rotulo_para_valor[rotulo], (rotulo, href)


def test_barra_de_combinacao_usa_a_combinacao_exata(sintetico):
    cli, _ = sintetico
    links = _barras_com_link(cli.get("/observatorio?universo=todas").text, "obs-combinacoes")
    assert links["/observatorio/obras?universo=todas&combinacao=A%2BC"] == 1
    assert not any("conjunto=" in h for h in links)


def test_barras_de_eixo_e_sem_eixo(sintetico):
    from test_observatorio_vies import _itens, _t, _web
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1), _web(2), _web(3)], [],
                            {("referencia", 1): _t(eixo="E1"), ("referencia", 2): _t(eixo=None),
                             ("referencia", 3): _t(eixo="Eixo fora da configuração")})
    links = _barras_com_link(cli.get("/observatorio?perspectiva=vies").text, "obs-vies-eixos")
    assert links == {"/observatorio/obras?perspectiva=vies&eixo=E1": 1,
                     "/observatorio/obras?perspectiva=vies&eixo=sem_eixo": 1}  # o eixo fora da configuracao fica sem link


def test_matriz_continua_com_os_mesmos_links(sintetico):
    cli, _ = sintetico
    assert set(_celulas(cli.get("/observatorio").text)) == {
        "/observatorio/obras?combinacao=A&angulo=vies_algoritmico", "/observatorio/obras?combinacao=C&angulo=aplicacoes_tecnologicas",
        "/observatorio/obras?combinacao=A%2BC&angulo=vies_algoritmico", "/observatorio/obras?combinacao=nenhum&angulo=sem_angulo"}


def test_formulario_da_pagina_tem_o_filtro_de_divergencia(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio?divergencia=com").text
    assert '<option value="com" selected>Com divergência entre os itens</option>' in html
    assert "<dt>Obras</dt><dd>1 obra · universo: Relevância alta ou média</dd>" in html
