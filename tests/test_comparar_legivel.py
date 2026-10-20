"""Comparar execucoes: as caixas de escolha mostram o run_id inteiro (o sufixo e o que distingue duas execucoes do mesmo
segundo) e nenhum cabecalho de tabela muda a caixa de um identificador."""
import re
from pathlib import Path

from test_painel_navegacao import cliente, demo  # noqa: F401

PAINEL = Path(__file__).resolve().parent.parent / "painel"


def test_css_nao_muda_a_caixa_de_codigo_no_cabecalho():
    css = (PAINEL / "static" / "painel.css").read_text(encoding="utf-8")
    assert "th code { text-transform: none; letter-spacing: normal; }" in css
    assert css.index("th { white-space: nowrap;") < css.index("th code { text-transform: none;")   # vem depois e vence


def test_caixas_de_escolha_ocupam_duas_colunas(cliente):
    cli, ids = cliente
    for rota in ("/execucoes/comparar", f"/execucoes/comparar?a={ids['run']}&b={ids['run']}"):
        html = cli.get(rota).text
        assert '<label class="larga">Execução A <select name="a">' in html
        assert '<label class="larga">Execução B <select name="b">' in html


def test_run_id_aparece_inteiro_nas_opcoes_e_no_cabecalho(cliente):
    cli, ids = cliente
    html = cli.get(f"/execucoes/comparar?a={ids['run']}&b={ids['run']}").text
    assert re.search(rf'<option value="{ids["run"]}" selected>{ids["run"]} · ', html)
    assert html.count(f"<code>{ids['run']}</code></a></th>") == 2
