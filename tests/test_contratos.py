import pathlib

import pytest

FIX = pathlib.Path(__file__).parent / "fixtures"

_PERPLEXITY_REAL = FIX / "perplexity_search.json"


@pytest.mark.skipif(not _PERPLEXITY_REAL.exists(),
                    reason="fixture real ainda nao existe (criada no M3, depois da primeira busca real)")
def test_busca_perplexity_interpreta_bruto_real():
    from adaptadores.busca_perplexity import BuscaPerplexity
    resultados, _ = BuscaPerplexity.interpretar(_PERPLEXITY_REAL.read_text(encoding="utf-8"))
    assert resultados and all(r.url and r.posicao >= 1 for r in resultados)
