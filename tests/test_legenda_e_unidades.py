"""A legenda das Analises do vies define a relevancia pela versao vigente do prompt de triagem (v2), e os cartoes da Visao Geral
dizem a unidade certa (testado em test_visao_geral_montador.py)."""
from pathlib import Path

from config import triagem_escopo as TE
from test_analises_vies import _cli, banco  # noqa: F401  (fixture do banco vies com triagem)

RAIZ = Path(__file__).resolve().parents[1]
LEGENDA = (RAIZ / "painel" / "templates" / "_legenda_analises.html").read_text(encoding="utf-8")

RELEVANCIA_V2 = (
    "<dt>Relevância</dt><dd>Da triagem do modelo (versão v2): <strong>alta</strong>, diretamente sobre IA, algoritmos ou sistemas "
    "de decisão automatizada na segurança pública, no policiamento, na investigação criminal, na perícia ou na justiça criminal, "
    "tratando de viés, discriminação, ética, direitos ou governança, ou de aplicações, implantações, resultados empíricos, "
    "soluções tecnológicas ou produtos; <strong>média</strong>, IA numa área vizinha (justiça em geral, vigilância, cidades "
    "inteligentes) que se transfere claramente para a segurança pública, ou viés e ética da IA em outra área que se transfere "
    "claramente para a segurança pública; <strong>baixa</strong>, só tangencial, inclusive tecnologia de segurança pública sem "
    "IA nem decisão automatizada (câmeras comuns, câmeras corporais, drones sem IA); <strong>fora do escopo</strong>, sem "
    "relação com o tema; o modelo é instruído a usar esta classe só quando tem certeza, e então com confiança alta.</dd>")


def _legenda_renderizada(banco, tmp_path):
    html = _cli(banco, tmp_path).get("/analises").text
    i = html.index('<section class="an-bloco" id="legenda"')
    return html[i:html.index("</section>", i)]


def test_legenda_da_relevancia_e_a_da_v2(banco, tmp_path):  # noqa: F811
    """Mudanca de contrato (verificacao cientifica da A3b): a alta e "diretamente sobre" o tema, e o fora do escopo diz a
    regra de uso (so com certeza e confianca alta), que explica por que so esses itens ficam ocultos."""
    leg = _legenda_renderizada(banco, tmp_path)
    assert RELEVANCIA_V2 in leg
    assert "IA na segurança pública sem esse recorte" not in leg                      # a definicao da v1
    assert leg.count("<dt>Relevância</dt>") == 1
    assert "IA na segurança pública sem esse recorte" not in LEGENDA


def test_legenda_segue_a_fonte_unica(banco, tmp_path, monkeypatch):  # noqa: F811
    from painel import rotulos
    monkeypatch.setattr(rotulos, "RELEVANCIA_V2", {k: f"trocado-{k}" for k in ("alta", "media", "baixa", "fora_do_escopo")})
    leg = _legenda_renderizada(banco, tmp_path)
    assert ("<strong>alta</strong>, trocado-alta; <strong>média</strong>, trocado-media; <strong>baixa</strong>, trocado-baixa; "
            "<strong>fora do escopo</strong>, trocado-fora_do_escopo.</dd>") in leg


def test_legenda_amarrada_a_versao_vigente_do_prompt():
    """Se a versao do prompt mudar, este teste falha ate a legenda ser revista."""
    assert TE.PROMPT_TRIAGEM_VIES_VERSAO == "v2"
    prompt = TE._SISTEMA_VIES
    for trecho in ("applications, implementations, empirical results, technological solutions or products",
                   "AI in an adjacent area (justice in general, surveillance, smart cities)",
                   "only tangentially related, including public security technology without AI",
                   '"fora_do_escopo": unrelated', '"alta": directly about AI',
                   'Use it ONLY when you are certain; then "confianca" must be "alta"'):
        assert trecho in prompt, trecho
