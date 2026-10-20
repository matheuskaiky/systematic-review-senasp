"""RB20 (D81): desenho "Observatorio". As fontes do CSS ficam em design/; os sete CSS de painel/static/ sao a saida do gerador; o banner leva a
conta e o botao de tema; o cockpit leva os icones dos titulos."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_autenticacao import _criar, _entrar, painel  # noqa: F401  (fixture `painel`: autenticacao ligada)
from test_painel import demo  # noqa: F401
from test_painel_navegacao import _blocos, _css, _declaracoes, _impressao

RAIZ = Path(__file__).resolve().parent.parent
DESIGN = RAIZ / "design"
FOLHAS = ("painel", "analises", "solucoes", "classificadores", "metodologia", "relevancia", "triagem_escopo")
TEMPLATES = RAIZ / "painel" / "templates"
AMBIENTE = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}


def _rodar(*args):
    return subprocess.run([sys.executable, "-B", *map(str, args)], capture_output=True, encoding="utf-8", env=AMBIENTE)


# ====================== fontes do CSS (design/) ======================
def test_pasta_de_desenho_tem_as_fontes_e_as_ferramentas():
    for rel in ("tools/gerar_painel_css.py", "tools/lint_css.py", "tools/tokens.py", "tools/tokens_analises.py",
                "tools/construir_fonte_icones.py", "tools/LEIAME.md", "python/verifica_tema.py", "icons/lista.txt",
                "build/icones.json", "src/painel/00_cabecalho.css", "src/painel/70_impressao.css", "src/analises.css"):
        assert (DESIGN / rel).is_file(), rel


def test_css_de_painel_static_e_a_saida_do_gerador(tmp_path):
    assert DESIGN.is_dir()
    copia = tmp_path / "design"

    def ignorar(pasta, nomes):
        return [n for n in nomes if n == "__pycache__" or (n == "css" and Path(pasta).name == "build")]
    shutil.copytree(DESIGN, copia, ignore=ignorar)
    r = _rodar(copia / "tools" / "gerar_painel_css.py", copia)
    assert r.returncode == 0, r.stderr
    for nome in FOLHAS:
        gerado = (copia / "build" / "css" / f"{nome}.css").read_bytes()
        assert gerado == (RAIZ / "painel" / "static" / f"{nome}.css").read_bytes(), nome


def test_linter_e_verificador_de_tema_passam_no_css_publicado():
    r = _rodar(DESIGN / "tools" / "lint_css.py", RAIZ / "painel" / "static")
    assert r.returncode == 0 and re.search(r"lint_css: 0 falha\(s\)", r.stdout), r.stdout + r.stderr
    r = _rodar(DESIGN / "python" / "verifica_tema.py", RAIZ / "painel" / "static" / "painel.css")
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), r.stdout + r.stderr


def test_arquivos_escritos_em_utf8_lf_sem_bom():
    arquivos = [p for p in DESIGN.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".css", ".txt", ".json")]
    arquivos += [RAIZ / "painel" / "static" / f"{n}.css" for n in FOLHAS] + [
        RAIZ / "painel" / "static" / "painel.js", TEMPLATES / "base.html", TEMPLATES / "_triagem_artigo.html", TEMPLATES / "_triagem_achado.html",
        RAIZ / ".gitignore"]
    for p in arquivos:
        b = p.read_bytes()
        assert b"\r\n" not in b and not b.startswith(b"\xef\xbb\xbf"), p
    assert (RAIZ / ".gitignore").read_text(encoding="utf-8").endswith("*.zip\ndesign/build/css/\n")


def test_css_sem_href_entre_aspas_duplas():
    """O relatorio estatico embute painel.css: seletor a[href="..."] seria lido como link (o gerador usa aspas simples)."""
    assert 'href="' not in (RAIZ / "painel" / "static" / "painel.css").read_text(encoding="utf-8")


def test_impressao_mantem_as_regras_do_projeto():
    imp = _impressao(_css("painel.css"))
    regras = {}
    for prefixo, corpo in _blocos(imp):
        for s in prefixo.split(","):
            regras.setdefault(s.strip(), {}).update(_declaracoes(corpo))
    for sel in (".conta", ".topo", ".tema-alternar"):
        assert regras.get(sel, {}).get("display") == "none !important", sel
    assert regras.get(".guia-interpretacao", {}).get("break-inside") == "avoid"


def test_fonte_de_icones_e_licenca_junto():
    fonte = RAIZ / "painel" / "static" / "fonts" / "observatorio-icones-v2.woff2"
    assert fonte.is_file() and fonte.read_bytes()[:4] == b"wOF2"
    assert (fonte.parent / "LICENSE-PhosphorIcons-MIT.txt").is_file()


# ====================== banner: conta e botao de tema ======================
def _banner(h):
    return re.search(r'<header class="banner[^"]*" role="banner">.*?</header>', h, flags=re.S).group(0)


def test_banner_com_conta_antes_do_botao_de_tema(painel):
    cli = painel[0]
    _criar(painel, "chefe", "Administrador", nome="Chefe")
    assert _entrar(cli, "chefe").status_code == 303
    b = _banner(cli.get("/").text)
    assert '<div class="conta">' in b and b.index('<div class="conta">') < b.index('class="tema-alternar"')
    for trecho in ('class="conta-admin" href="/admin"', '<a class="conta-nome" href="/conta" title="Minha conta">Chefe</a>', '<form method="post" action="/sair" class="form-sair">'):
        assert trecho in b, trecho


def test_banner_anonimo_tem_entrar(painel):
    b = _banner(painel[0].get("/").text)
    assert '<div class="conta"><a class="conta-entrar" href="/entrar">Entrar</a></div>' in b


def test_sem_autenticacao_banner_sem_conta(demo, tmp_path):
    from fastapi.testclient import TestClient
    from test_painel import _app
    banco, raw = demo
    app, _ = _app(banco, raw, tmp_path)
    h = TestClient(app).get("/").text
    b = _banner(h)
    assert 'class="conta"' not in b and 'class="tema-alternar"' in b and '<div class="topo">' not in h


def test_banner_quebra_linha_e_foco_visivel_na_conta():
    css = _css("painel.css")
    assert re.search(r"\.banner \{ flex-wrap: wrap; row-gap: var\(--esp-1\); \}", css)
    assert ".banner .conta a:focus-visible, .banner .form-sair button:focus-visible { outline-color: var(--texto-banner); }" in css


# ====================== icones do cockpit ======================
@pytest.mark.parametrize("arquivo,esperado", [
    ("_triagem_artigo.html", ['<h2 data-ic="compass">Onde foi encontrado</h2>', '<h2 data-ic="clock" data-tom="ambar">Histórico de decisões</h2>',
                              '<h3 data-ic="keyboard">Atalhos</h3>', '<h2 data-ic="funnel">Triagem por título e resumo</h2>',
                              '<h2 data-ic="robot" data-tom="violeta">Triagem de escopo pelo modelo</h2>', '<h2>Texto completo</h2>']),
    ("_triagem_achado.html", ['<h2 data-ic="quotes">Evidência no texto</h2>', '<h2 data-ic="clock" data-tom="ambar">Histórico de decisões</h2>',
                              '<h2 data-ic="scales">Decisão</h2>', '<h3 data-ic="keyboard">Atalhos</h3>']),
])
def test_cockpit_tem_os_icones_dos_titulos(arquivo, esperado):
    texto = (TEMPLATES / arquivo).read_text(encoding="utf-8")
    for trecho in esperado:
        assert texto.count(trecho) == 1, trecho
