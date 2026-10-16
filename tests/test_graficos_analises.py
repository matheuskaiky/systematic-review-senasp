"""Gráficos da página /analises (painel/graficos_analises.py), selos estatísticos e analises.css: SVG bem formado, acessível, sem
estilo embutido, com texto escapado, só com links relativos, determinístico, com padrões definidos e cores com contraste."""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from painel import graficos_analises as ga
from painel import selos_estatisticos as se

RAIZ = Path(__file__).resolve().parent.parent
CSS = RAIZ / "painel" / "static" / "analises.css"
R = "<b>x</b>&"       # rótulo hostil: precisa sair escapado em todo lugar


# ============================== dados de exemplo (um por gerador) ==============================
def _matriz(r=R):
    return ga.matriz_maturidade(
        [{"chave": "SP", "rotulo": r, "grupo": "Sudeste"}, {"chave": "RJ", "rotulo": "RJ", "grupo": "Sudeste"},
         {"chave": "AC", "rotulo": "AC", "grupo": r}],
        [{"chave": "rf", "rotulo": r}, {"chave": "lp", "rotulo": "Leitura de placas de veículos"}],
        {("SP", "rf"): {"contagens": {"em_uso": 1, "piloto": 9}, "href": "/achados?uf=SP&tecnologia=rf"},
         ("RJ", "lp"): "piloto", ("AC", "rf"): {"status": "descartado", "n": 1}}, titulo=r)


def _barras(r=R):
    return ga.barras_proporcao([{"rotulo": r, "total": 25, "parte": 3, "href": "/achados?lgpd=1"},
                                {"rotulo": "B", "total": 0, "parte": 0}], r, r, rotulo_parte=r)


def _funil(r=R):
    return ga.funil_comparativo(
        [{"rotulo": r, "etapas": [(r, 1000), ("B", 300, "/chamadas?x=1"), ("C", 5)]},
         {"rotulo": "Google", "etapas": [("A", 300), ("B", 200), ("C", 40)]}], r, r)


def _linha(r=R):
    return ga.linha_com_corte([(i, 40 / i) for i in range(1, 61)], r, r, rotulo_x=r, rotulo_y=r, corte=10, teto=45,
                              rotulo_corte=r, rotulo_teto=r)


def _areas(r=R):
    return ga.areas_empilhadas([2020, 2021, 2022], [{"rotulo": r, "valores": [1, 2, 3], "href": "/literatura/artigos?termo=a"},
                                                    {"rotulo": "B", "valores": [0, 1]}], r, r)


def _kappa(r=R):
    return ga.regua_kappa(0.72, (0.6, 0.83), titulo=r)


def _semaforo(r=R):
    return ga.semaforo_limite(0.004, 0.0, 0.014, 0.02, r, r, r)


def _calibracao(r=R):
    return ga.barras_calibracao(
        [{"chave": "alta", "rotulo": r, "n": 25, "concordam": 23, "ic_inf": 0.75, "ic_sup": 0.98, "href": "/achados?confianca=alta"},
         {"chave": "media", "rotulo": "M", "n": 10, "concordam": 5}, {"chave": "baixa", "rotulo": "B", "n": 0}], r)


def _floresta(r=R):
    return ga.floresta_odds([{"rotulo": r, "or_": 8.5, "ic_inf": 6, "ic_sup": 11.2, "href": "/achados?evidencia=1"},
                             {"rotulo": "neutro", "or_": 1.2, "ic_inf": 0.8, "ic_sup": 1.9},
                             {"rotulo": "menos", "or_": 0.4, "ic_inf": 0.2, "ic_sup": 0.8},
                             {"rotulo": "sem", "or_": None, "ic_inf": None, "ic_sup": None}], r)


_TAB = {("N", "a"): 10, ("N", "b"): 5, ("S", "a"): 2, ("S", "b"): 30}


def _mosaico(r=R):
    return ga.mosaico(_TAB, [{"chave": "N", "rotulo": r}, {"chave": "S", "rotulo": "Sul"}],
                      [{"chave": "a", "rotulo": r}, {"chave": "b", "rotulo": "Tecnologia B"}], r,
                      hrefs={("N", "a"): "/achados?uf=N"})


def _mosaico_res(r=R):
    return ga.mosaico(_TAB, [{"chave": "N", "rotulo": r}, {"chave": "S", "rotulo": "Sul"}],
                      [{"chave": "a", "rotulo": r}, {"chave": "b", "rotulo": "Tecnologia B"}], r,
                      residuos={("N", "a"): 3.4, ("N", "b"): -2.4, ("S", "a"): -3.4, ("S", "b"): 0.3})


def _calor(r=R):
    return ga.mapa_de_calor_assimetrico([{"chave": "x", "rotulo": r}, {"chave": "y", "rotulo": "Y"}],
                                        [{"chave": "p", "rotulo": r}, {"chave": "q", "rotulo": "Q"}],
                                        {("x", "p"): 10, ("x", "q"): 0, ("y", "p"): 3, ("y", "q"): None}, r,
                                        hrefs={("x", "p"): "/achados?a=1"})


def _fluxo(r=R):
    return ga.fluxo_duas_colunas([{"chave": "exc", "rotulo": r}, {"chave": "eleg", "rotulo": "Elegível"}],
                                 [{"chave": "inc", "rotulo": "Incluído"}, {"chave": "nao", "rotulo": r}],
                                 {("exc", "inc"): 1, ("exc", "nao"): 50, ("eleg", "inc"): 40, ("eleg", "nao"): 9},
                                 [("exc", "inc")], r, hrefs={("exc", "inc"): "/literatura/artigos?decisao=incluir"})


def _dispersao(r=R):
    return ga.dispersao([(100 * i, i % 7, f"{r} {i}", "/literatura/artigos?i=1") for i in range(1, 30)], r, r, rotulo_x=r, rotulo_y=r,
                        corte_x=60000, curva=[(100, 2), (3000, 3), (60000, 2)], rotulo_corte=r)


def _ranking(r=R):
    return ga.ranking_semaforo([{"dominio": r, "total": 40, "bloqueadas": 28, "href": "/chamadas?q=x"},
                                {"dominio": "ok.gov.br", "total": 10, "bloqueadas": 0},
                                {"dominio": "meio.gov.br", "total": 10, "bloqueadas": 3}], r)


GERADORES = {"matriz": _matriz, "barras": _barras, "funil": _funil, "linha": _linha, "areas": _areas, "kappa": _kappa,
             "semaforo": _semaforo, "calibracao": _calibracao, "floresta": _floresta, "mosaico": _mosaico,
             "mosaico_res": _mosaico_res, "calor": _calor, "fluxo": _fluxo, "dispersao": _dispersao}
HTML_COM_TABELA = {"ranking": _ranking}
TODOS = {**GERADORES, **HTML_COM_TABELA}


def _xml(html):
    return ET.fromstring(f"<raiz>{html}</raiz>")


def _svgs(raiz):
    return [e for e in raiz.iter() if e.tag == "svg"]


def _tag(e):
    return e.tag.split("}")[-1]


# ============================== estrutura, acessibilidade e segurança ==============================
@pytest.mark.parametrize("nome", sorted(TODOS))
def test_xml_bem_formado_com_title_desc_e_role_img(nome):
    raiz = _xml(TODOS[nome]())
    svgs = _svgs(raiz)
    assert svgs, nome
    for svg in svgs:
        assert svg.get("role") == "img"
        filhos = [_tag(c) for c in svg]
        assert filhos[:2] == ["title", "desc"], (nome, filhos[:3])
        assert svg.get("viewBox")
        rotulos = svg.get("aria-labelledby").split()
        ids = {e.get("id") for e in svg.iter() if e.get("id")}
        assert set(rotulos) <= ids, (nome, rotulos, ids)
        assert "".join(svg.find("title").itertext()).strip() and "".join(svg.find("desc").itertext()).strip()


@pytest.mark.parametrize("nome", sorted(TODOS))
def test_sem_estilo_embutido_script_ou_manipuladores(nome):
    html = TODOS[nome]()
    assert "style=" not in html.lower()
    assert "<script" not in html.lower() and "<style" not in html.lower()
    assert "javascript:" not in html.lower()
    for e in _xml(html).iter():
        for atributo in e.attrib:
            assert not atributo.lower().startswith("on"), (nome, atributo)
            assert atributo.lower() != "style"


@pytest.mark.parametrize("nome", sorted(TODOS))
def test_texto_dos_rotulos_sai_escapado(nome):
    html = TODOS[nome]()
    assert "<b>" not in html and "</b>" not in html, nome
    assert "&lt;b&gt;" in html, nome
    _xml(html)      # continua XML válido (o & vira &amp;)


@pytest.mark.parametrize("nome", sorted(TODOS))
def test_saida_deterministica(nome):
    assert TODOS[nome]() == TODOS[nome]()


def test_ids_nao_se_repetem_quando_todos_os_graficos_estao_na_mesma_pagina():
    pagina = "".join(f() for f in TODOS.values()) + _barras("outro") + _funil("outro")
    ids = [e.get("id") for e in _xml(pagina).iter() if e.get("id")]
    assert ids and len(ids) == len(set(ids))


def test_hash_dos_ids_nao_depende_da_semente_do_python():
    """Conjuntos (destaques) e dicionários entram no hash dos ids: a ordem não pode variar entre execuções."""
    codigo = ("from tests.test_graficos_analises import _fluxo, _matriz, _mosaico_res; import hashlib;"
              "print(hashlib.sha1((_fluxo()+_matriz()+_mosaico_res()).encode()).hexdigest())")
    saidas = set()
    for semente in ("1", "2", "3"):
        r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": semente})
        assert r.returncode == 0, r.stderr
        saidas.add(r.stdout.strip())
    assert len(saidas) == 1


def test_padroes_e_simbolos_referenciados_existem_no_proprio_svg():
    for nome, f in TODOS.items():
        for svg in _svgs(_xml(f())):
            definidos = {e.get("id") for e in svg.iter() if _tag(e) in ("pattern", "symbol")}
            usados = set()
            for e in svg.iter():
                m = re.fullmatch(r"url\(#([\w-]+)\)", e.get("fill", ""))
                if m:
                    usados.add(m.group(1))
                if _tag(e) == "use":
                    usados.add(e.get("href").lstrip("#"))
            assert usados <= definidos, (nome, usados - definidos)
    # os que dependem de padrão para funcionar em escala de cinza de fato os definem
    for nome in ("matriz", "areas", "mosaico", "mosaico_res", "kappa", "calibracao", "fluxo", "funil", "semaforo"):
        assert "<pattern" in TODOS[nome](), nome
    assert "<symbol" in _matriz() and "<use" in _matriz()          # glifos de cada estágio, além do padrão


def test_padroes_nao_usam_so_cor_a_matriz_tem_padrao_distinto_por_status():
    svg = _svgs(_xml(_matriz()))[0]
    tipos = {}
    for p in svg.iter():
        if _tag(p) == "pattern":
            tipos[p.get("id").split("-", 2)[2]] = [c.get("d") for c in p if _tag(c) == "path"]
    sem_traco = [k for k, v in tipos.items() if not v]
    assert set(sem_traco) == {"em_uso", "apenas_citado"}      # só os dois extremos são lisos; os demais têm traço próprio
    desenhos = [tuple(v) for k, v in tipos.items() if v]
    assert len(desenhos) == len(set(desenhos))


def _hrefs(html):
    return [e.get("href") for e in _xml(html).iter() if _tag(e) == "a"]


def test_so_links_relativos_e_o_resto_e_descartado():
    hostis = ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "http://evil.com/x", "https://evil.com", "//evil.com/x", "/\\evil.com",
              "data:text/html,x", "vbscript:x", "evil.com", "", None, 7, "/a b", "/a\tb", "/x\njavascript:1"]
    itens = [{"rotulo": f"i{i}", "total": 10, "parte": 2, "href": h} for i, h in enumerate(hostis)]
    itens.append({"rotulo": "bom", "total": 10, "parte": 2, "href": "/achados?uf=SP&q=<2>"})
    html = ga.barras_proporcao(itens, "t", "d")
    assert _hrefs(html) == ["/achados?uf=SP&q=<2>"]
    assert "href=\"/achados?uf=SP&amp;q=&lt;2&gt;\"" in html
    # o mesmo vale nos demais geradores que aceitam href
    ruim = "http://evil.com"
    for html in (ga.funil_comparativo([{"rotulo": "a", "etapas": [("x", 3, ruim)]}], "t", "d"),
                 ga.areas_empilhadas([1, 2], [{"rotulo": "a", "valores": [1, 2], "href": ruim}], "t", "d"),
                 ga.floresta_odds([{"rotulo": "a", "or_": 2, "ic_inf": 1.2, "ic_sup": 3, "href": ruim}], "t"),
                 ga.matriz_maturidade(["a"], ["b"], {("a", "b"): {"status": "em_uso", "href": ruim}}),
                 ga.dispersao([(1, 2, "p", ruim)], "t", "d"),
                 ga.ranking_semaforo([{"dominio": "a", "total": 1, "bloqueadas": 1, "href": ruim}], "t")):
        assert _hrefs(html) == [] and "evil" not in html


def test_todo_link_tem_nome_acessivel_e_so_aponta_para_caminho_relativo():
    for nome, f in TODOS.items():
        for a in (e for e in _xml(f()).iter() if _tag(e) == "a"):
            assert a.get("href").startswith("/") and not a.get("href").startswith("//"), nome
            assert a.get("aria-label") or "".join(a.itertext()).strip(), nome


# ============================== dados vazios, nulos e zerados ==============================
CHAMADAS_VAZIAS = {
    "matriz": lambda: ga.matriz_maturidade(None, None, None),
    "matriz2": lambda: ga.matriz_maturidade([], ["a"], {}),
    "barras": lambda: ga.barras_proporcao(None, "t", "d"),
    "funil": lambda: ga.funil_comparativo(None, "t", "d"),
    "funil2": lambda: ga.funil_comparativo([{"rotulo": "a", "etapas": []}], "t", "d"),
    "linha": lambda: ga.linha_com_corte(None, "t", "d"),
    "linha2": lambda: ga.linha_com_corte([(None, None), ("a", "b")], "t", "d", corte="x", teto=None),
    "areas": lambda: ga.areas_empilhadas(None, None, "t", "d"),
    "areas2": lambda: ga.areas_empilhadas([2020], [{"rotulo": "a", "valores": [0]}], "t", "d"),
    "kappa": lambda: ga.regua_kappa(None),
    "kappa_nan": lambda: ga.regua_kappa(float("nan")),
    "semaforo": lambda: ga.semaforo_limite(None, None, None, None, "t", "a", "b"),
    "semaforo2": lambda: ga.semaforo_limite(0.01, None, 0.02, 0.02, "t", "a", "b"),
    "semaforo3": lambda: ga.semaforo_limite(0.01, 0.0, 0.02, 0, "t", "a", "b"),
    "calibracao": lambda: ga.barras_calibracao(None, "t"),
    "floresta": lambda: ga.floresta_odds(None, "t"),
    "floresta2": lambda: ga.floresta_odds([{"rotulo": "a", "or_": None, "ic_inf": None, "ic_sup": None}], "t"),
    "mosaico": lambda: ga.mosaico(None, None, None, "t"),
    "mosaico0": lambda: ga.mosaico({("a", "b"): 0}, ["a"], ["b"], "t"),
    "calor": lambda: ga.mapa_de_calor_assimetrico(None, None, None, "t"),
    "calor2": lambda: ga.mapa_de_calor_assimetrico(["a"], ["b"], {("a", "b"): None}, "t"),
    "fluxo": lambda: ga.fluxo_duas_colunas(None, None, None, None, "t"),
    "fluxo0": lambda: ga.fluxo_duas_colunas(["a"], ["b"], {("a", "b"): 0}, [("a", "b")], "t"),
    "dispersao": lambda: ga.dispersao(None, "t", "d"),
    "dispersao_log": lambda: ga.dispersao([(0, 1), (-3, 2)], "t", "d", log_x=True),
    "ranking": lambda: ga.ranking_semaforo(None, "t"),
}


@pytest.mark.parametrize("nome", sorted(CHAMADAS_VAZIAS))
def test_dados_vazios_ou_nulos_devolvem_mensagem_neutra_sem_svg(nome):
    html = CHAMADAS_VAZIAS[nome]()
    assert html.startswith('<p class="vazio') and "<svg" not in html
    _xml(html)


def test_totais_zero_e_valores_estranhos_nao_levantam_erro():
    assert "sem casos" in ga.barras_proporcao([{"rotulo": "a", "total": 0, "parte": 5}], "t", "d")
    ga.barras_proporcao([{"rotulo": "a", "total": "x", "parte": None}, {"rotulo": "b", "total": -3, "parte": 99}], "t", "d")
    _xml(ga.funil_comparativo([{"rotulo": "a", "etapas": [("x", 0), ("y", 0), ("z", None)]}], "t", "d"))
    _xml(ga.areas_empilhadas([2020, 2021], [{"rotulo": "a", "valores": ["x", None]}, {"rotulo": "b", "valores": [1]}], "t", "d"))
    _xml(ga.semaforo_limite(0, 0, 0.0, 0.02, "t", "ok", "alerta"))
    _xml(ga.semaforo_limite(0.5, 0.4, 0.6, 0.02, "t", "ok", "alerta"))
    _xml(ga.mapa_de_calor_assimetrico(["a", "b"], ["c"], {("a", "c"): 0, ("b", "c"): 0}, "t"))
    _xml(ga.regua_kappa(-0.4))
    _xml(ga.regua_kappa(1.7, ic=(None, 3)))
    _xml(ga.dispersao([(5, 5)], "t", "d", corte_x=5))
    _xml(ga.linha_com_corte([(1, 0)], "t", "d", corte=1, teto=0))
    assert ga.ranking_semaforo([{"dominio": "a", "total": 0, "bloqueadas": 0}], "t").count("sem páginas") >= 1
    html = ga.barras_calibracao([{"chave": "alta", "rotulo": "Alta", "n": 0}], "t")
    assert "sem verificação" in html and "humana ainda" in html          # o texto quebra em linhas


def test_calibracao_sem_n_mostra_estado_sem_verificacao_humana():
    html = ga.barras_calibracao([{"chave": "alta", "rotulo": "Alta", "n": 0}, {"chave": "baixa", "rotulo": "Baixa", "n": 0}], "t")
    texto = " ".join("".join(t.itertext()) for t in _xml(html).iter() if _tag(t) == "text")
    assert "sem verificação" in texto and "humana ainda" in texto and "n = 0" in texto
    assert "an-col-vazia" in html and 'class="an-col"' not in html


# ============================== lógica visual ==============================
def test_matriz_usa_o_status_de_maior_peso_e_nao_o_mais_frequente():
    assert ga.status_mais_avancado({"em_uso": 1, "piloto": 9, "apenas_citado": 40}) == "em_uso"
    assert ga.status_mais_avancado(["apenas_citado", "licitacao", "anunciado"]) == "licitacao"
    assert ga.status_mais_avancado({"em_uso": 0, "piloto": 2}) == "piloto"         # n = 0 não conta
    assert ga.status_mais_avancado("em_estudo") == "em_estudo"
    assert ga.status_mais_avancado(["descartado", "em_estudo"]) == "em_estudo"      # descartado só vale sozinho
    assert ga.status_mais_avancado(["descartado"]) == "descartado"
    assert ga.status_mais_avancado(None) is None and ga.status_mais_avancado([]) is None and ga.status_mais_avancado("xyz") is None
    raiz = _xml(_matriz("rotulo"))
    por_titulo = {"".join(g.find("title").itertext()): g for g in raiz.iter() if _tag(g) == "g" and g.find("title") is not None}
    sp = next(g for t, g in por_titulo.items() if t.startswith("rotulo × rotulo"))
    assert "Em uso operacional (10 achados)" in "".join(sp.find("title").itertext())
    assert "an-c-em_uso" in sp.find("rect").get("class")
    rj = next(g for t, g in por_titulo.items() if t.startswith("RJ ×") and "Leitura" in t)
    assert "an-c-piloto" in rj.find("rect").get("class")
    ac = next(g for t, g in por_titulo.items() if t.startswith("AC ×") and "descartado" in t.lower())
    assert "an-c-descartado" in ac.find("rect").get("class")
    assert any("sem dados" in t for t in por_titulo)       # AC x Leitura de placas não tem célula


def test_matriz_status_explicito_vale_e_status_invalido_vira_sem_dados():
    html = ga.matriz_maturidade(["a"], ["b", "c"], {("a", "b"): {"status": "inventado"}, ("a", "c"): {"status": "anunciado", "n": 2}})
    titulos = [t.text for t in _xml(html).iter() if _tag(t) == "title"]
    assert any("a × b: sem dados" == t for t in titulos) and any("Anunciado (2 achados)" in t for t in titulos)


def test_matriz_separa_regioes_e_traz_legenda_com_os_sete_estagios():
    raiz = _xml(_matriz("Rot"))
    grupos = [e.text for e in raiz.iter() if _tag(e) == "text" and e.get("class") == "an-grupo"]
    assert grupos == ["Sudeste", "Rot"]                  # SP e RJ no mesmo grupo: um separador só
    legenda = " ".join("".join(e.itertext()) for e in raiz.iter() if _tag(e) == "text" and e.get("class") == "an-leg")
    for rotulo in ("Em uso operacional", "Projeto piloto", "Licitação/contrato", "Anunciado", "Em estudo", "Apenas citado", "Descartado", "Sem dados"):
        assert rotulo in legenda


def _x_ponteiro(html):
    m = re.search(r'class="an-ponteiro" points="([-\d.]+),[-\d.]+ ([-\d.]+),[-\d.]+ ([-\d.]+),', html)
    assert m, html
    return float(m.group(3))


def test_ponteiro_do_kappa_cresce_com_o_valor_e_fica_dentro_da_regua():
    xs = [_x_ponteiro(ga.regua_kappa(v)) for v in (0.0, 0.1, 0.39, 0.4, 0.55, 0.61, 0.8, 0.81, 1.0)]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    assert _x_ponteiro(ga.regua_kappa(-0.5)) == _x_ponteiro(ga.regua_kappa(0)) == min(xs)
    assert _x_ponteiro(ga.regua_kappa(1.5)) == _x_ponteiro(ga.regua_kappa(1)) == max(xs)


def test_faixas_do_kappa():
    # escala unificada de 5 faixas positivas (mudança deliberada: antes eram 4, com fraca < 0,40)
    esperado = {0.0: "fraca", 0.20: "fraca", 0.21: "razoavel", 0.39: "razoavel", 0.40: "razoavel", 0.41: "moderada",
                0.60: "moderada", 0.61: "substancial", 0.80: "substancial", 0.81: "quase", 1.0: "quase"}
    for valor, faixa in esperado.items():
        assert ga.faixa_kappa(valor)[0] == faixa, valor
    assert ga.faixa_kappa(-0.2) == ("pior", "Pior que o acaso")
    assert ga.faixa_kappa(None) is None and ga.faixa_kappa(float("nan")) is None
    html = ga.regua_kappa(0.72, ic=(0.6, 0.83))
    for nome in ("Fraca", "Razoável", "Moderada", "Substancial", "Quase perfeita"):
        assert nome in html
    assert html.count("an-faixa-atual") == 2 and "an-faixa-substancial an-faixa-atual" in html      # faixa + rótulo destacados
    assert "an-ic-linha" in html and "IC 95%" in html
    assert "an-ic-linha" not in ga.regua_kappa(0.72)
    assert "κ = 0,72" in html
    assert "pior que o acaso" not in html


def test_faixa_kappa_do_grafico_concorda_com_interpretar_kappa():
    from dominio.concordancia import interpretar_kappa
    for i in range(-100, 101):
        v = i / 100
        assert ga.faixa_kappa(v)[1].lower() == interpretar_kappa(v), v


def test_regua_do_kappa_tem_cinco_faixas_com_padroes_distintos():
    html = ga.regua_kappa(0.5)
    padroes = re.findall(r'<pattern id="pt-[0-9a-f]+-k-(\w+)"[^>]*>(.*?)</pattern>', html)
    assert [c for c, _ in padroes] == ["fraca", "razoavel", "moderada", "substancial", "quase"]
    assert len({corpo for _, corpo in padroes}) == 5                       # cada faixa tem preenchimento diferente
    assert html.count('class="an-faixa an-faixa-') == 5


def test_semaforo_unilateral_diz_ate_no_maximo_e_o_padrao_continua_bilateral():
    uni = ga.semaforo_limite(0.0, 0.0, 0.015, 0.02, "t", "ok", "alerta", unilateral=True)
    assert "até no máximo 1,5%" in uni and "limite superior unilateral de 95%" in uni and "an-veredito-ok" in uni
    assert "intervalo de 95%" not in uni
    bi = ga.semaforo_limite(0.0, 0.0, 0.015, 0.02, "t", "ok", "alerta")
    assert "intervalo de 95%" in bi and "unilateral" not in bi


def test_kappa_negativo_tem_marcador_e_texto_pior_que_o_acaso():
    html = ga.regua_kappa(-0.4)
    assert "pior que o acaso" in html and "κ = -0,40" in html
    assert 'class="an-limite"' in html                                       # marcador próprio no início da régua
    assert "an-faixa-atual" not in html                                      # nenhuma das 5 faixas é a "atual"
    assert "pior que o acaso" in re.search(r"<desc[^>]*>(.*?)</desc>", html).group(1)
    assert _x_ponteiro(html) == _x_ponteiro(ga.regua_kappa(0))               # o ponteiro trava no início
    assert "pior que o acaso" not in ga.regua_kappa(0.0)


@pytest.mark.parametrize("args,veredito", [((0.004, 0.0, 0.014), "ok"), ((0.015, 0.008, 0.03), "incerto"),
                                           ((0.05, 0.03, 0.07), "acima"), ((0.01, 0.0, 0.02), "incerto"),    # ic_sup == limite
                                           ((0.03, 0.02, 0.05), "incerto")])                                  # ic_inf == limite
def test_semaforo_tres_ramos_do_veredito(args, veredito):
    html = ga.semaforo_limite(*args, 0.02, "t", "TUDO-BEM", "PERIGO")
    outros = {"ok", "incerto", "acima"} - {veredito}
    assert all(f'class="an-veredito an-veredito-{o}"' not in html for o in outros)
    assert f'class="an-veredito an-veredito-{veredito}"' in html
    texto = " ".join("".join(t.itertext()) for t in _xml(html).iter() if _tag(t) == "text" and t.get("class") == "an-veredito-texto")
    assert ("TUDO-BEM" in texto) == (veredito == "ok") and ("PERIGO" in texto) == (veredito == "acima")
    assert ("inconclusivo" in texto) == (veredito == "incerto")
    assert ga.veredito_limite(args[1], args[2], 0.02) == veredito


def test_semaforo_desenha_limite_sombra_e_porcentagens_em_pt_br():
    html = ga.semaforo_limite(0.004, 0.0, 0.014, 0.02, "t", "ok", "alerta", n=250)
    assert "an-limite" in html and "an-ic-sombra" in html and "an-obs-barra" in html
    assert "Limite: 2%" in html and "0,4%" in html and "1,4%" in html and "amostra de 250" in html
    # a linha do limite fica à direita da sombra quando o intervalo está todo abaixo
    limite_x = float(re.search(r'class="an-limite" x1="([\d.]+)"', html).group(1))
    sombra = re.search(r'class="an-ic-sombra" x="([\d.]+)" y="44" width="([\d.]+)"', html)
    assert float(sombra.group(1)) + float(sombra.group(2)) < limite_x


def test_funil_mostra_conversao_e_aceita_um_ou_dois_funis():
    html = ga.funil_comparativo([{"rotulo": "A", "etapas": [("l", 1000), ("m", 450), ("n", 9)]}], "t", "d")
    assert "▼ 45%" in html and "an-conv-baixa" in html and html.count("an-conv-baixa") == 1      # 9/450 = 2%
    assert "an-fn1" not in html
    um = _xml(html)
    assert float(um.find("svg").get("viewBox").split()[2]) < float(_xml(_funil("A")).find("svg").get("viewBox").split()[2])
    dois = _funil("A")
    assert "an-fn0" in dois and "an-fn1" in dois and dois.count("▼") == 4
    # mesma escala nos dois funis: 300 do Google é mais estreito que 1000 do primeiro
    larguras = [float(m) for m in re.findall(r'class="an-fn[01]"[^>]* width="([\d.]+)"', dois)]
    assert larguras[0] > larguras[3]


def test_linha_com_corte_e_teto_so_desenha_o_que_foi_pedido():
    base = ga.linha_com_corte([(1, 5), (2, 8), (3, 9)], "t", "d", "posição", "achados")
    assert "an-linha" in base and "an-corte" not in base and "an-teto" not in base
    com = ga.linha_com_corte([(1, 5), (2, 8), (3, 9)], "t", "d", corte=2, teto=12, rotulo_teto="Teto estimado (K)")
    assert 'class="an-corte"' in com and 'class="an-teto"' in com and "Teto estimado (K) (12)" in com
    x_corte = float(re.search(r'class="an-corte" x1="([\d.]+)"', com).group(1))
    y_teto = float(re.search(r'class="an-teto" x1="[\d.]+" x2="[\d.]+" y1="([\d.]+)"', com).group(1))
    y_topo_linha = min(float(p.split(",")[1]) for p in re.search(r'<polyline class="an-linha" points="([^"]+)"', com).group(1).split())
    assert y_teto < y_topo_linha                              # o teto fica acima do ponto mais alto da curva
    assert 58 < x_corte < 616


def test_areas_empilhadas_um_ano_vira_coluna_e_varios_viram_poligono():
    um = ga.areas_empilhadas([2022], [{"rotulo": "a", "valores": [3]}, {"rotulo": "b", "valores": [2]}], "t", "d")
    assert um.count("<rect class=\"an-area-s\"") >= 2 and "<polygon" not in um
    varios = _areas("a")
    assert varios.count("<polygon") == 2 and "2021" in varios and "<pattern" in varios
    pol = _xml(varios).findall(".//polygon")
    assert len({p.get("fill") for p in pol}) == 2           # cada série com seu padrão


def test_calibracao_mostra_taxa_n_e_bigode():
    html = _calibracao("Alta")
    assert "92%" in html and "n = 25" in html and "n = 10" in html and "50%" in html
    assert html.count('class="an-ic"') == 1                  # só o grupo que trouxe IC
    assert "an-col-vazia" in html                            # o grupo com n = 0
    assert "IC 95%: 75% a 98%" in html


def test_floresta_classifica_pelo_intervalo_e_marca_o_um():
    html = _floresta("citação")
    assert 'class="an-or-mais"' in html and 'class="an-or-neutro"' in html and 'class="an-or-menos"' in html
    assert "8,5x" in html and "6x a 11x" in html and "sem estimativa" in html and "1x = sem efeito" in html
    assert "▲" in html and "▼" in html
    # na escala log o 1x fica entre 0,5x e 2x
    x = {t: float(re.search(r'<line class="an-grade" x1="([\d.]+)"[^>]*/><text class="an-eixo-val"[^>]*>' + t + "</text>", html).group(1))
         for t in ("0,5x", "1x", "2x")}
    assert x["0,5x"] < x["1x"] < x["2x"]
    assert abs((x["1x"] - x["0,5x"]) - (x["2x"] - x["1x"])) < 0.3     # simétrico em escala logarítmica


def test_floresta_aceita_limites_infinitos_sem_levantar_erro():
    html = ga.floresta_odds([{"rotulo": "a", "or_": 5, "ic_inf": 0, "ic_sup": float("inf")}], "t")
    assert "∞" in html
    _xml(html)


def test_mosaico_largura_proporcional_ao_total_e_residuos_com_padrao_e_sinal():
    html = _mosaico("Rot")
    segs = {}
    for s in _xml(html).iter():
        if _tag(s) == "rect" and (s.get("class") or "").startswith("an-seg an-seg-s") and float(s.get("width")) > 25:
            segs.setdefault(s.get("x"), float(s.get("width")))
    larguras = sorted(segs.values())
    assert len(larguras) >= 2 and larguras[1] / larguras[0] == pytest.approx(32 / 15, rel=0.02)     # totais: N = 15, S = 32
    res = _mosaico_res("Rot")
    for nivel in ("res-mais3", "res-mais2", "res-menos2", "res-menos3", "res-zero"):
        assert f"an-seg-{nivel}" in res
    assert "+ " in res and "− " in res and "<pattern" in res and "Muito acima do esperado" in res
    assert "resíduo padronizado 3,4" in res


def test_mapa_de_calor_mostra_numero_na_celula_e_nivel_pelo_maior_valor():
    html = _calor("R")
    assert ">10<" in html and ">3<" in html and ">0<" in html and "—" in html
    assert "an-calor-4" in html and "an-calor-0" in html
    assert 'href="/achados?a=1"' in html
    formatado = ga.mapa_de_calor_assimetrico(["a"], ["b"], {("a", "b"): 0.256}, "t", formato=lambda v: f"{100 * v:.0f}%")
    assert ">26%<" in formatado


def test_fluxo_destaca_so_o_que_foi_listado_e_resume_em_porcentagem():
    html = _fluxo("Rot")
    raiz = _xml(html)
    fitas = [p for p in raiz.iter() if _tag(p) == "path" and "an-fluxo" in (p.get("class") or "")]
    assert len(fitas) == 4
    alerta = [p for p in fitas if "an-fluxo-alerta" in p.get("class")]
    assert len(alerta) == 1 and alerta[0].get("fill").startswith("url(#pt-")
    assert "Fluxo destacado em vermelho: 1 de 100 (1,0% do fluxo total)." in html
    assert 'href="/literatura/artigos?decisao=incluir"' in html
    # a fita destacada é a última desenhada (fica por cima) e tem pelo menos 2px de espessura
    assert "an-fluxo-alerta" in [p.get("class") for p in fitas][-1]
    sem = ga.fluxo_duas_colunas(["a"], ["b"], {("a", "b"): 4}, [], "t")
    assert "an-fluxo-alerta" not in sem and "Fluxo destacado" not in sem
    nenhum = ga.fluxo_duas_colunas(["a", "c"], ["b"], {("a", "b"): 4, ("c", "b"): 0}, [("c", "b")], "t")
    assert "nenhum caso (0 de 4)" in nenhum


def test_dispersao_log_corte_curva_e_reducao_de_pontos_grandes():
    pontos = [(10 ** (i / 10), i % 5) for i in range(1, 40)]
    html = ga.dispersao(pontos, "t", "d", corte_x=60000, curva=[(10, 1), (100, 3)], log_x=True)
    assert "an-corte" in html and "an-curva" in html and "60.000" in html and "1.000" in html
    assert ga.dispersao(pontos, "t", "d").count("an-corte") == 0
    muitos = [(i, i % 9) for i in range(1, 9000)]
    html = ga.dispersao(muitos, "t", "d")
    assert html.count('class="an-ponto"') <= 4000 and html.count("<title>") == 0     # sem dica por ponto (só o <title id=...> do SVG)
    assert "amostra de" in html and len(html) < 400_000


def test_ranking_ordena_por_fatia_bloqueada_e_classifica_pelos_limiares():
    html = _ranking("Rot")
    assert html.startswith('<div class="tabela-rolavel"><table')
    raiz = _xml(html)
    assert [th.get("scope") for th in raiz.iter() if _tag(th) == "th"][:6].count("col") == 6
    linhas = [tr for tr in raiz.iter() if _tag(tr) == "tr" and tr.get("class")]
    assert [tr.get("class") for tr in linhas] == ["an-nivel-fechado", "an-nivel-parcial", "an-nivel-aberto"]
    assert ga.nivel_bloqueio(0.19) == "aberto" and ga.nivel_bloqueio(0.2) == "parcial" and ga.nivel_bloqueio(0.49) == "parcial"
    assert ga.nivel_bloqueio(0.5) == "fechado" and ga.nivel_bloqueio(1) == "fechado"
    assert "70%" in html and "Fechado" in html and "Parcial" in html and "Aberto" in html      # o nível também sai em texto
    ties = ga.ranking_semaforo([{"dominio": "b", "total": 10, "bloqueadas": 5}, {"dominio": "a", "total": 10, "bloqueadas": 5},
                                {"dominio": "c", "total": 20, "bloqueadas": 10}], "t")
    assert [m for m in re.findall(r'<th scope="row">([abc])</th>', ties)] == ["c", "a", "b"]


# ============================== selos estatísticos ==============================
@pytest.mark.parametrize("p,classe,texto", [
    (0.0, "ev-forte", "Diferença muito improvável de ser acaso (p < 0,01)"),
    (0.0099, "ev-forte", "Diferença muito improvável de ser acaso (p < 0,01)"),
    (0.01, "ev-moderada", "Diferença improvável de ser acaso (p < 0,05)"),
    (0.0499, "ev-moderada", "Diferença improvável de ser acaso (p < 0,05)"),
    (0.05, "ev-insuficiente", "Os dados não permitem afirmar diferença; isso não prova que os grupos sejam iguais"),
    (0.9, "ev-insuficiente", "Os dados não permitem afirmar diferença; isso não prova que os grupos sejam iguais"),
    ("forte", "ev-forte", "Diferença muito improvável de ser acaso (p < 0,01)"),
    ("moderada", "ev-moderada", "Diferença improvável de ser acaso (p < 0,05)"),
    ("insuficiente", "ev-insuficiente", "Os dados não permitem afirmar diferença; isso não prova que os grupos sejam iguais"),
])
def test_selo_mapeia_p_valor_e_nivel_para_os_textos_do_plano(p, classe, texto):
    s = se.selo(p)
    assert set(s) == {"classe", "rotulo", "texto"} and s["classe"] == classe and s["texto"] == texto and s["rotulo"]


@pytest.mark.parametrize("p", [None, float("nan"), -0.1, 1.5, "abc", True, [], "FORTE"])
def test_selo_sem_dados_ou_invalido_e_neutro(p):
    s = se.selo(p)
    assert s["classe"] == "ev-sem" and "Sem" in s["rotulo"] and s["texto"]


def test_frase_odds_nos_tres_casos():
    # mudança deliberada: razão de chances NÃO é "N vezes mais provável"; a frase fala em chance (odds) e traz a nota
    assert se.frase_odds("citação literal verificada", 8.5, 6.0, 11.2) == \
        ("Achados com citação literal verificada: a chance (odds) de serem confirmados pelo perito humano é entre 6x e 11x "
         "a dos achados sem essa característica. Razão de chances não é o mesmo que probabilidade.")
    assert "entre 1,2x e 4,2x a dos achados sem essa característica" in se.frase_odds("fonte oficial", 2.2, 1.2, 4.2)
    menos = se.frase_odds("snippet", 0.25, 0.1, 0.5)
    assert "entre 0,10x e 0,50x a dos achados sem essa característica (menor)" in menos
    neutra = se.frase_odds("domínio .gov.br", 1.3, 0.8, 2.1)
    assert "não há evidência" in neutra and "inclui 1x" in neutra
    assert "de pelo menos 3x a dos achados" in se.frase_odds("x", 9, 3, float("inf"))
    for ruim in ((None, 1, 2), (2, None, 3), (2, 1, None), ("a", "b", "c"), (0, 0, 0), (float("nan"), 1, 2)):
        assert "sem estimativa" in se.frase_odds("x", *ruim)
    assert se.frase_odds("", 3, 2, 4).startswith("Achados com essa característica")


@pytest.mark.parametrize("args", [(8.5, 6.0, 11.2), (2.2, 1.2, 4.2), (0.25, 0.1, 0.5), (1.3, 0.8, 2.1), (9, 3, float("inf"))])
def test_frase_odds_nunca_diz_vezes_mais_provavel_e_sempre_traz_a_nota(args):
    f = se.frase_odds("x", *args)
    assert "chance (odds)" in f and se.NOTA_RAZAO_DE_CHANCES in f
    for proibido in ("mais chance", "menos chance", "mais provável", "mais provavel", "vezes mais"):
        assert proibido not in f


def test_textos_dos_selos_nao_superam_o_p_valor():
    textos = " ".join(se.selo(p)["texto"] for p in (0.001, 0.03, 0.5))
    for proibido in ("comprovado", "altíssima confiança", "margem do acaso"):
        assert proibido not in textos
    assert "isso não prova que os grupos sejam iguais" in se.selo(0.5)["texto"]


# ============================== CSS (analises.css) ==============================
def _css():
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def _tokens(bloco):
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+):\s*([^;]+);", bloco)}


def _temas():
    css = _css()
    claro = re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)
    escuro = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}\s*\}", css, re.S).group(1)
    impressao = re.search(r"@media print \{\s*:root \{(.*?)\}", css, re.S).group(1)
    base = _tokens(claro)
    return base, {**base, **_tokens(escuro)}, _tokens(impressao)


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (c(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b):
    la, lb = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("indice,nome", [(0, "claro"), (1, "escuro")])
def test_contraste_do_texto_sobre_cada_estagio_e_cada_nivel_do_mapa_de_calor(indice, nome):
    t = _temas()[indice]
    pares = [(f"an-{s}-tx", f"an-{s}") for s in ga.STATUS_ORDEM] + [(f"an-calor-tx{i}", f"an-calor{i}") for i in range(5)]
    ruins = [f"{a} sobre {b}: {_contraste(t[a], t[b]):.2f}" for a, b in pares if _contraste(t[a], t[b]) < 4.5]
    assert not ruins, f"tema {nome}: {ruins}"


def test_impressao_fixa_todos_os_tokens_no_tema_claro():
    claro, _, impressao = _temas()
    assert claro and set(claro) == set(impressao)
    for k, v in impressao.items():
        assert "var(" not in v, k                      # na impressão nada herda do tema escuro da tela
    assert all(impressao[k] == claro[k] for k in claro if "var(" not in claro[k])


def test_todas_as_classes_emitidas_existem_no_css():
    css = _css()
    conhecidas = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    emprestadas = {"vazio", "tabela-rolavel", "so-leitor", "num"}                       # de painel.css
    usadas = set()
    for f in TODOS.values():
        for e in _xml(f()).iter():
            usadas |= set((e.get("class") or "").split())
    for f in (lambda: _matriz("a"), _mosaico_res, _semaforo, _kappa):
        for e in _xml(f()).iter():
            usadas |= set((e.get("class") or "").split())
    # ganchos sem regra própria: tipo do gráfico (para a página estilizar um deles se quiser) e variante de cor de cada segmento
    ganchos = {"an-matriz", "an-proporcao", "an-funil", "an-linha-corte", "an-areas", "an-kappa", "an-semaforo", "an-calibracao",
               "an-floresta", "an-mosaico", "an-calor", "an-fluxo-svg", "an-dispersao", "an-veredito", "an-ic", "an-bg"}
    ganchos |= {c for c in usadas if c.startswith(("an-seg-", "an-faixa-")) and c != "an-faixa-atual"}
    faltando = usadas - conhecidas - emprestadas - ganchos
    assert not faltando, sorted(faltando)
    for classe in se._NIVEIS.values():
        assert classe[0] in conhecidas


def test_css_so_usa_classes_nao_tem_import_url_externa_nem_expressao():
    css = _css()
    assert "@import" not in css and "http" not in css and "expression(" not in css and "javascript:" not in css
    assert "outline: none" not in css and "outline:none" not in css
    assert "prefers-color-scheme: dark" in css and "@media print" in css and ":focus-visible" in css
    # presentation attribute `fill` perde para qualquer regra CSS de `fill`: os elementos preenchidos por padrão não podem ter `fill` no CSS
    for seletor in (".an-seg ", ".an-seg{", ".an-area-s ", ".an-c ", ".an-col "):
        for trecho in re.findall(re.escape(seletor) + r"[^}]*\}", css):
            assert "fill:" not in trecho.split("{", 1)[1].replace("fill-opacity", ""), trecho


def test_ranking_semaforo_coluna_de_robots_inacessivel_so_aparece_quando_informada():
    sem = ga.ranking_semaforo([{"dominio": "a.gov.br", "total": 10, "bloqueadas": 2}], "t")
    assert "robots.txt inacessível" not in sem
    com = ga.ranking_semaforo([{"dominio": "a.gov.br", "total": 10, "bloqueadas": 2, "inacessiveis": 5},
                               {"dominio": "b.gov.br", "total": 4, "bloqueadas": 0, "inacessiveis": 0}], "t")
    assert "robots.txt inacessível (bloqueado pela política)" in com and com.count("<td") == 2 * 6
    assert "20% bloqueadas" in com                                            # a fatia/situacao conta so a proibicao real, nao as inacessiveis
