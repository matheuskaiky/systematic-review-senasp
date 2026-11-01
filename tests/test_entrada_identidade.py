"""Tela de entrada e identidade da plataforma: a mesma marca em todas as paginas (um so modelo parcial), a frase-guia, a
descricao da pesquisa vinda da mesma regra da Visao Geral publica (so a descricao, nunca perguntas nem limitacoes), o item de
revisao de achados so onde ha achados, e nenhum numero na entrada, com a pesquisa divulgada ou nao."""
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from apoio_divulgacao import gravar_politica
from dominio import apresentacao as AP
from painel.app import criar_app
from test_apresentacao_publica import TEXTOS, _ctx, _nunca_abre_o_data_real  # noqa: F401
from test_painel import demo  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
MODELOS = RAIZ / "painel" / "templates"
MARCA = '<a class="marca" href="/">IA na Segurança Pública<br><small>UFPI · SENASP</small></a>'
CHAMADA = ('<p class="entrada-chamada">Resultados produzidos por modelos de inteligência artificial não são considerados '
           'resultados validados da pesquisa sem confirmação humana.</p>')
APRESENTACAO_ARIA = '<aside class="entrada-apresentacao" aria-label="Sobre a pesquisa">'
TRIAGEM = ('<div><strong>Triagem de artigos</strong><span>Leia o título e o resumo e registre a decisão de incluir ou '
           'excluir.</span></div>')
ACHADOS = '<div><strong>Revisão de achados</strong><span>Confirme ou descarte cada achado a partir do trecho da página.</span></div>'
AUTORIA = ('<div><strong>Decisão com autoria</strong><span>Cada decisão guarda o nome de quem decidiu, para a pesquisa poder '
           'ser auditada.</span></div>')
CREDITO = '<p class="entrada-credito">Pesquisa desenvolvida na UFPI para a SENASP.</p>'
ANTIGOS = ["Levantamento<br>", "Cada achado passa por uma pessoa", "O levantamento reúne", "Sobre o levantamento",
           "decida o que entra na revisão sistemática"]


def _app(demo, tmp_path, banco="real", publica=True, apresentacao=None):  # noqa: F811
    db, raw = demo
    tmp_path.mkdir(parents=True, exist_ok=True)
    copia = tmp_path / "demo.db"
    shutil.copy(db, copia)
    ctx = _ctx(banco_=banco, apresentacao=apresentacao if apresentacao is not None else {})
    contas = ContasSQLite(tmp_path / "contas.db")
    gravar_politica(contas, banco, publica=publica)
    app = criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas)
    return TestClient(app), ctx


@pytest.mark.parametrize("banco", ["real", "demo", "simulado"])
def test_entrada_com_os_textos_e_o_item_de_achados(demo, tmp_path, banco):  # noqa: F811
    cli, _ = _app(demo, tmp_path, banco=banco)
    h = cli.get("/entrar").text
    for t in (MARCA, APRESENTACAO_ARIA, CHAMADA, TRIAGEM, ACHADOS, AUTORIA, CREDITO):
        assert t in h, t
    assert h.index(TRIAGEM) < h.index(ACHADOS) < h.index(AUTORIA)
    for t in ANTIGOS:
        assert t not in h, t


def test_entrada_do_vies_sem_o_item_de_achados(demo, tmp_path):  # noqa: F811
    cli, _ = _app(demo, tmp_path, banco="vies")
    h = cli.get("/entrar").text
    for t in (MARCA, APRESENTACAO_ARIA, CHAMADA, TRIAGEM, AUTORIA, CREDITO):
        assert t in h, t
    assert "Revisão de achados" not in h and h.count("<li data-matiz=") == 2


@pytest.mark.parametrize("publica", [True, False])
def test_descricao_da_pesquisa_logo_depois_da_frase_e_so_ela(demo, tmp_path, publica):  # noqa: F811
    """A entrada mostra so a descricao valida da pesquisa (um paragrafo por item), com a pesquisa divulgada ou nao; perguntas,
    metodo, abrangencia, limitacoes e instituicao nunca aparecem nela."""
    textos = dict(TEXTOS, descricao=("Primeiro parágrafo da descrição.", "Segundo parágrafo da descrição."))
    cli, _ = _app(demo, tmp_path, publica=publica, apresentacao=textos)
    h = cli.get("/entrar").text
    assert re.search(re.escape(CHAMADA) + r'\s*<p class="entrada-texto">Primeiro parágrafo da descrição\.</p>'
                     r'\s*<p class="entrada-texto">Segundo parágrafo da descrição\.</p>\s*<ul class="entrada-itens">', h)
    for sid, paragrafos in TEXTOS.items():
        if sid != "descricao":
            for p in paragrafos:
                assert p not in h, (sid, p)
    assert "vg-ap-" not in h


@pytest.mark.parametrize("descricao", [("PREENCHA",), None, ("",), ["lista"]], ids=["marcador", "ausente", "vazia", "lista"])
def test_sem_descricao_valida_nao_ha_paragrafo(demo, tmp_path, descricao):  # noqa: F811
    textos = {} if descricao is None else {"descricao": descricao}
    cli, _ = _app(demo, tmp_path, apresentacao=textos)
    h = cli.get("/entrar").text
    assert 'class="entrada-texto"' not in h and re.search(re.escape(CHAMADA) + r'\s*<ul class="entrada-itens">', h)


def test_descricao_escapada(demo, tmp_path):  # noqa: F811
    cli, _ = _app(demo, tmp_path, apresentacao={"descricao": ("<b>negrito</b> & aspas \"",)})
    h = cli.get("/entrar").text
    assert '<p class="entrada-texto">&lt;b&gt;negrito&lt;/b&gt; &amp; aspas &#34;</p>' in h


def test_entrada_usa_a_regra_da_visao_geral(demo, tmp_path, monkeypatch):  # noqa: F811
    """A descricao vem de dominio.apresentacao.secoes_publicas (a mesma regra da Visao Geral), lida a cada visita."""
    vistos = []
    monkeypatch.setattr(AP, "secoes_publicas", lambda t: vistos.append(t) or
                        {"antes": [{"id": "descricao", "titulo": "x", "lista": None, "paragrafos": ["Descrição trocada."]}],
                         "depois": []})
    cli, ctx = _app(demo, tmp_path, apresentacao={"qualquer": ("coisa",)})
    h = cli.get("/entrar").text
    assert vistos == [{"qualquer": ("coisa",)}] and '<p class="entrada-texto">Descrição trocada.</p>' in h
    ctx.apresentacao = {"outra": ("coisa",)}
    cli.get("/entrar")
    assert vistos[-1] == {"outra": ("coisa",)}


def test_entrada_nao_depende_dos_dados_da_pesquisa(demo, tmp_path):  # noqa: F811
    """Nenhum numero dos dados chega a entrada: a pagina e a mesma com o banco da pesquisa cheio ou ausente. Um numero escrito
    na propria descricao (um ano, por exemplo) aparece como esta."""
    textos = {"descricao": ("Pesquisa iniciada em 2026.",)}
    cheio, _ = _app(demo, tmp_path / "cheio", apresentacao=textos)
    (tmp_path / "vazio").mkdir()
    ausente = tmp_path / "vazio" / "nao_existe.db"
    contas = ContasSQLite(tmp_path / "vazio" / "contas.db")
    gravar_politica(contas, "real")
    ctx = _ctx(apresentacao=textos)
    vazio = TestClient(criar_app(LeituraPainelSQLite(ausente), lambda: RepositorioSQLite(ausente), BrutoLocal(tmp_path), ctx,
                                 contas=contas))

    def aside(h):
        i = h.index(APRESENTACAO_ARIA)
        return h[i:h.index("</aside>", i)]
    a, b = cheio.get("/entrar").text, vazio.get("/entrar").text
    assert APRESENTACAO_ARIA in a and APRESENTACAO_ARIA in b
    assert aside(a) == aside(b) and '<p class="entrada-texto">Pesquisa iniciada em 2026.</p>' in aside(a)
    sem_csrf = lambda h: re.sub(r'name="csrf" value="[^"]*"', 'name="csrf" value=""', h)  # noqa: E731
    assert sem_csrf(a) == sem_csrf(b)                       # a pagina inteira, nao so o painel de apresentacao
    assert 'class="kpi' not in a and not ausente.exists()


def test_mesma_marca_em_todas_as_paginas_por_um_so_modelo(demo, tmp_path):  # noqa: F811
    """A marca esta num so modelo parcial (_marca.html), incluido pela base e pela entrada; nenhum outro modelo a escreve."""
    cli, _ = _app(demo, tmp_path)
    assert MARCA in cli.get("/").text and MARCA in cli.get("/entrar").text and MARCA in cli.get("/sobre").text
    parcial = (MODELOS / "_marca.html").read_text(encoding="utf-8")
    assert parcial in (MARCA, MARCA + "\n")
    for nome in ("base.html", "entrar.html"):
        fonte = (MODELOS / nome).read_text(encoding="utf-8")
        assert '{% include "_marca.html" %}' in fonte and 'class="marca"' not in fonte, nome
    outros = [p.name for p in MODELOS.glob("*.html") if p.name != "_marca.html" and 'class="marca"' in p.read_text(encoding="utf-8")]
    assert outros == []


def _bloco_celular(css):
    """O bloco @media (max-width: 900px) da tela de entrada (o que tem .layout-entrada), com os espacos normalizados."""
    i = css.index("@media (max-width: 900px) {\n  .layout-entrada")
    fim = css.index("\n}\n", i)
    return re.sub(r"\s+", " ", css[i:fim])


@pytest.mark.parametrize("arquivo", ["painel/static/painel.css", "design/src/painel/65_login.css"])
def test_no_celular_a_frase_e_a_descricao_continuam_visiveis(arquivo):
    """Em telas estreitas a apresentacao fica acima do formulario, compacta: frase-guia e descricao visiveis, sem os itens."""
    bloco = _bloco_celular((RAIZ / arquivo).read_text(encoding="utf-8"))
    assert ".entrada-lateral::before, .entrada-itens { display: none; }" in bloco
    assert ".entrada-apresentacao { margin: var(--esp-3) 0 0; }" in bloco
    assert ".entrada-chamada { font-size: var(--fs-lg); line-height: 1.3; }" in bloco
    assert ".entrada-texto { margin-top: var(--esp-2); font-size: var(--fs-md); }" in bloco
    assert not re.search(r"\.entrada-apresentacao[^{]*\{ display: none", bloco)
