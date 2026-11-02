"""A legenda das Analises do vies define a relevancia pela versao vigente do prompt de triagem (v2), e os cartoes da Visao Geral
dizem a unidade certa (testado em test_visao_geral_montador.py)."""
from pathlib import Path

from config import triagem_escopo as TE

RAIZ = Path(__file__).resolve().parents[1]
LEGENDA = (RAIZ / "painel" / "templates" / "_legenda_analises.html").read_text(encoding="utf-8")

RELEVANCIA_V2 = (
    "<dt>Relevância</dt><dd>Da triagem do modelo (versão v2): <strong>alta</strong>, IA, algoritmos ou sistemas de decisão "
    "automatizada na segurança pública, no policiamento, na investigação criminal, na perícia ou na justiça criminal, tratando "
    "de viés, discriminação, ética, direitos ou governança, ou de aplicações, implantações, resultados empíricos, soluções "
    "tecnológicas ou produtos; <strong>média</strong>, IA numa área vizinha (justiça em geral, vigilância, cidades inteligentes) "
    "que se transfere claramente para a segurança pública, ou viés e ética da IA em outra área que se transfere claramente para "
    "a segurança pública; <strong>baixa</strong>, só tangencial, inclusive tecnologia de segurança pública sem IA nem decisão "
    "automatizada (câmeras comuns, câmeras corporais, drones sem IA); <strong>fora do escopo</strong>, sem relação.</dd>")


def test_legenda_da_relevancia_e_a_da_v2():
    assert RELEVANCIA_V2 in LEGENDA
    assert "IA na segurança pública sem esse recorte" not in LEGENDA                  # a definicao da v1
    assert LEGENDA.count("<dt>Relevância</dt>") == 1


def test_legenda_amarrada_a_versao_vigente_do_prompt():
    """Se a versao do prompt mudar, este teste falha ate a legenda ser revista."""
    assert TE.PROMPT_TRIAGEM_VIES_VERSAO == "v2"
    prompt = TE._SISTEMA_VIES
    for trecho in ("applications, implementations, empirical results, technological solutions or products",
                   "AI in an adjacent area (justice in general, surveillance, smart cities)",
                   "only tangentially related, including public security technology without AI",
                   '"fora_do_escopo": unrelated'):
        assert trecho in prompt, trecho
