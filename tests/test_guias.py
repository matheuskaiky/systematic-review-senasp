"""RB15 (D75): camada educativa: um guia de leitura no fim de /, /analises e /solucoes, com os textos aprovados do pacote."""
import shutil

import pytest
from fastapi.testclient import TestClient

from test_painel import _app, demo  # noqa: F401
from test_painel_acessibilidade import verificar

PAGINAS = [("/", "guia-geral"), ("/analises", "guia-analises"), ("/solucoes", "guia-solucoes")]
PROIBIDOS = ("Evidência confere", "Evidência não localizada no texto enviado", "sem nome", "Tudo revisado", "onclick", "style=",
             "http://", "cdn", "kpi-valor", "kpi-rotulo", "solucao-destaque", "tabela-rolavel", "barra-progresso")


@pytest.fixture
def cli(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    return TestClient(app)


@pytest.mark.parametrize("caminho,ident", PAGINAS)
def test_guia_uma_vez_no_fim_da_pagina(cli, caminho, ident):
    h = cli.get(caminho).text
    assert h.count('class="guia-interpretacao"') == 1 and f'aria-labelledby="{ident}"' in h
    assert f'<h2 id="{ident}">Como interpretar esta página e suas métricas</h2>' in h
    assert h.index("<h1") < h.index('class="guia-interpretacao"') < h.index("</main>")
    assert verificar(h) == []


@pytest.mark.parametrize("caminho,ident", PAGINAS)
def test_guia_sem_frases_e_classes_fixadas_por_outros_testes(cli, caminho, ident):
    h = cli.get(caminho).text
    assert 'class="guia-interpretacao"' in h
    i = h.index('class="guia-interpretacao"')
    guia = h[i:h.index("</main>", i)]                     # o guia e o ultimo elemento de <main>
    for proibido in PROIBIDOS:
        assert proibido not in guia, proibido


def test_outras_paginas_sem_guia(cli):
    for caminho in ("/estados", "/achados", "/literatura"):
        assert 'class="guia-interpretacao"' not in cli.get(caminho).text
    assert "<details open" not in cli.get("/estados").text
