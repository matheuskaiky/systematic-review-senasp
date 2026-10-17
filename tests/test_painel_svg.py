"""Auditoria dos SVG do painel: todo grafico gerado no servidor (graficos.py, graficos_analises.py, o mapa e o relatorio estatico)
precisa ser responsivo (viewBox, sem largura/altura fixas na raiz) e acessivel (role="img", <title> como primeiro filho, <desc> com os
dados, ids unicos na pagina). Tambem confere no CSS que cada classe de SVG nao estoura o container."""
import re
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401
from test_painel_acessibilidade import _ids  # noqa: E402
from test_graficos_analises import TODOS as TODOS_OS_GERADORES_DE_ANALISES  # noqa: E402

from adaptadores.leitura_sqlite import LeituraPainelSQLite  # noqa: E402
from config import consultas as C  # noqa: E402
from painel import graficos, relatorio  # noqa: E402
from painel.rotas_extras.analises import ABAS  # noqa: E402

PAINEL = Path(__file__).resolve().parent.parent / "painel"


class Auditor(HTMLParser):
    """Percorre o HTML e junta, para cada <svg> da raiz, o que a auditoria confere (`filhos` = tags dentro dele, na ordem)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.svgs, self.ids, self.profundidade = [], [], 0
        self._atual, self._coleta = None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "svg":
            self.profundidade += 1
            if self.profundidade == 1:
                self._atual = {"attrs": a, "filhos": [], "titulo": "", "desc": ""}
                self.svgs.append(self._atual)
            return
        if self._atual is None:
            return
        primeiro = not self._atual["filhos"]
        self._atual["filhos"].append(tag)
        if (tag == "title" and primeiro) or (tag == "desc" and not self._atual["desc"]):
            self._coleta = "titulo" if tag == "title" else "desc"

    def handle_endtag(self, tag):
        if tag in ("title", "desc"):
            self._coleta = None
        elif tag == "svg" and self.profundidade:
            self.profundidade -= 1
            if self.profundidade == 0:
                self._atual = None

    def handle_data(self, dados):
        if self._atual is not None and self._coleta:
            self._atual[self._coleta] += dados


def auditar(html):
    """Lista de problemas dos SVG de uma pagina (vazia quando esta tudo certo). Devolve tambem quantos SVG havia."""
    p = Auditor()
    p.feed(html)
    problemas = []
    for i, s in enumerate(p.svgs, 1):
        a = s["attrs"]
        nome = f"svg {i} ({a.get('class', 'sem classe')})"
        if a.get("aria-hidden") == "true":
            continue                                    # decorativo: fora da arvore de acessibilidade
        if not re.fullmatch(r"-?[\d.]+ -?[\d.]+ [\d.]+ [\d.]+", (a.get("viewbox") or "").strip()):
            problemas.append(f"{nome}: viewBox ausente ou malformado ({a.get('viewbox')!r})")
        for medida in ("width", "height"):
            if a.get(medida) is not None:
                problemas.append(f"{nome}: {medida}={a[medida]!r} fixo na raiz (so viewBox e CSS)")
        if a.get("role") != "img":
            problemas.append(f"{nome}: sem role=\"img\"")
        if s["filhos"][:1] != ["title"] or not s["titulo"].strip():
            problemas.append(f"{nome}: o primeiro filho nao e um <title> preenchido")
        if "desc" not in s["filhos"] or not s["desc"].strip():
            problemas.append(f"{nome}: sem <desc> com a descricao dos dados")
        if "style" in a:
            problemas.append(f"{nome}: atributo style (a politica de seguranca do navegador o bloqueia)")
        for ref in (a.get("aria-labelledby") or "").split():
            if ref not in p.ids:
                problemas.append(f"{nome}: aria-labelledby aponta para o id inexistente {ref!r}")
    duplicados = sorted({i for i in p.ids if p.ids.count(i) > 1})
    if duplicados:
        problemas.append(f"ids duplicados na pagina: {duplicados[:5]}")
    return problemas, len(p.svgs)


# ============================== o proprio auditor ==============================
def test_o_auditor_pega_os_defeitos_conhecidos():
    ruim = ('<svg width="800" height="300"><rect/></svg>'
            '<svg viewBox="0 0 10 10" role="img" aria-labelledby="x"><g/><title id="t">t</title></svg>'
            '<svg viewBox="0 0 10 10" role="img"><title>so titulo</title></svg><p id="d"></p><p id="d"></p>')
    problemas, n = auditar(ruim)
    texto = " | ".join(problemas)
    assert n == 3
    for trecho in ("viewBox ausente", "width='800'", "height='300'", "sem role", "primeiro filho", "sem <desc>", "id inexistente", "ids duplicados"):
        assert trecho.lower() in texto.lower(), trecho
    assert auditar('<svg viewBox="0 0 9 9" role="img"><title>t</title><desc>d</desc><rect/></svg>') == ([], 1)
    assert auditar('<svg aria-hidden="true" width="9"><rect/></svg>') == ([], 1)


# ============================== geradores isolados ==============================
def test_geradores_do_painel_produzem_svg_conforme():
    saidas = [graficos.barras_horizontais([("a", 3), ("b", 0)], "T", "D"),
              graficos.mapa_do_brasil({"PI": ("confirmado", "x")}, "T", "D"),
              graficos.barra_empilhada([(1, "be-conf", "Confirmados"), (2, "be-desc", "Descartados")], 4, "Revisão: 1 confirmado, 2 descartados"),
              graficos.barra_empilhada([], 0, "Nada revisado"),
              graficos.colunas([("2019", 3), ("2020", 0)], "T", "D", "ano", "artigos"),
              graficos.mapa_de_calor(["A", "B"], {("A", "B"): 2, ("A", "A"): 3, ("B", "B"): 1}, "T", "D")]
    for svg in saidas:
        problemas, n = auditar(svg)
        assert n == 1 and not problemas, (svg[:80], problemas)


def test_ids_dos_graficos_nao_colidem_quando_o_mesmo_grafico_aparece_duas_vezes():
    a = graficos.barras_horizontais([("a", 1)], "Primeiro", "D1")
    b = graficos.barras_horizontais([("a", 2)], "Segundo", "D2")
    problemas, n = auditar(a + b)
    assert n == 2 and not problemas, problemas
    mapas = graficos.mapa_do_brasil({}, "A", "B") + graficos.mapa_do_brasil({"PI": ("confirmado", "x")}, "C", "D")
    assert auditar(mapas)[0] == []


@pytest.mark.parametrize("nome", sorted(TODOS_OS_GERADORES_DE_ANALISES))
def test_geradores_das_analises_produzem_svg_conforme(nome):
    problemas, n = auditar(TODOS_OS_GERADORES_DE_ANALISES[nome]())
    assert n >= 1 and not problemas, problemas


# ============================== paginas ==============================
@pytest.fixture(scope="module")
def cliente_svg(demo, tmp_path_factory):
    banco, raw = demo
    app, _ = _app(banco, raw, tmp_path_factory.mktemp("svg"))
    return TestClient(app, raise_server_exceptions=False), _ids(banco)


def _rotas(ids):
    fixas = ["/", "/estados", "/estados/SP", "/literatura", "/literatura/prisma", "/literatura/artigos", "/metodologia", "/classificadores",
             "/triagem-escopo", "/solucoes", "/execucoes", f"/execucoes/{ids['run']}", f"/execucoes/comparar?a={ids['run']}&b={ids['run']}",
             "/sobre", "/chamadas", f"/achados/{ids['achado']}", f"/literatura/artigos/{ids['artigo']}"]
    return fixas + [f"/analises?secao={chave}" for chave, _ in ABAS]


def test_todo_svg_de_toda_pagina_da_demo_e_responsivo_e_acessivel(cliente_svg):
    cli, ids = cliente_svg
    falhas, por_pagina = {}, {}
    for rota in _rotas(ids):
        r = cli.get(rota)
        assert r.status_code == 200, (rota, r.status_code)
        problemas, n = auditar(r.text)
        por_pagina[rota] = n
        if problemas:
            falhas[rota] = problemas
    assert not falhas, "\n".join(f"{rota}: {p}" for rota, p in falhas.items())
    # a auditoria so vale se de fato viu graficos: estas paginas desenham SVG na demonstracao (as abas "termos" e "web" so desenham com
    # dados que a demonstracao nao tem; os geradores delas sao auditados abaixo e as paginas, na copia do banco real, a mao)
    for rota in ("/", "/estados", "/literatura", "/analises?secao=adocao", "/analises?secao=busca",
                 "/analises?secao=literatura", "/analises?secao=auditoria", "/analises?secao=operacao"):
        assert por_pagina[rota] > 0, f"{rota} nao tem nenhum SVG (a auditoria nao a cobriu)"
    assert sum(por_pagina.values()) >= 25, por_pagina


def test_relatorio_estatico_tem_svg_conforme(demo):
    banco = demo[0]
    dados = relatorio.coletar_dados(LeituraPainelSQLite(banco), dict(C.UFS), {t.id: t.query for t in C.TERMOS}, tuple(C.BASES_MANUAIS),
                                    "demo", "demo.db", "2026-10-15T14:30:00", False)
    html = relatorio.montar_relatorio(dados, False, "")
    problemas, n = auditar(html)
    assert n >= 4 and not problemas, problemas


# ============================== CSS: nenhum SVG estoura o container ==============================
def _css(nome):
    return re.sub(r"/\*.*?\*/", "", (PAINEL / "static" / nome).read_text(encoding="utf-8"), flags=re.S)


def test_css_limita_cada_classe_de_svg_a_largura_do_container():
    painel, analises = _css("painel.css"), _css("analises.css")
    for classe in ("svg.grafico", "svg.mapa", "svg.barra-empilhada"):
        assert re.search(re.escape(classe) + r"[^{]*\{[^}]*width:\s*100%", painel.split("@media print")[0]), classe
    assert re.search(r"svg\.calor\s*\{[^}]*width:\s*100%[^}]*max-width:\s*900px", painel)
    assert re.search(r"\.an-svg\s*\{[^}]*width:\s*100%[^}]*height:\s*auto", analises)
    # nenhuma regra de SVG fixa largura em px (so max-width)
    for css in (painel, analises):
        for regra in re.findall(r"(svg[^{]*)\{([^}]*)\}", css):
            assert not re.search(r"(?<!max-)(?<!min-)width:\s*\d+px", regra[1]), regra


# ============================== a pagina de uma execucao nao ganha rolagem horizontal ==============================
def test_selo_do_motivo_de_exclusao_da_execucao_quebra_linha():
    """Regressao (achada ao medir a copia do banco real a 1280, 1366 e 420 px): o motivo de exclusao e texto livre e longo; no selo sem quebra
    de linha ele alargava a pagina inteira (scrollWidth 1382 contra 1280)."""
    modelo = (PAINEL / "templates" / "execucao.html").read_text(encoding="utf-8")
    assert 'class="selo alerta selo-longo">fora do relatório' in modelo
    css = _css("painel.css")
    assert re.search(r"\.selo\.selo-longo\s*\{[^}]*white-space:\s*normal", css) or re.search(r"\.selo\.selo-longo[^{]*\{[^}]*white-space:\s*normal", css)
    assert re.search(r"\.selo\.selo-longo\s*\{[^}]*max-width:\s*100%[^}]*overflow-wrap:\s*anywhere", css)
