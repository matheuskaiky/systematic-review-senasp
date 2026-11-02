"""O mesmo nome de cada tela no menu, na aba do navegador, no titulo da pagina e nos links (D155, E4): triagem de escopo pelo
modelo, comparacao de classificadores e validacao humana da triagem. As rotas nao mudam."""
from pathlib import Path

import pytest

from painel import navegacao as N

RAIZ = Path(__file__).resolve().parents[1]
NOMES = {"/triagem-escopo": "Triagem de escopo pelo modelo", "/classificadores": "Comparação de classificadores",
         "/validacao": "Validação humana da triagem"}
ANTIGOS = ["Triagem de escopo (LLM)", "Validação da triagem", "{% block titulo %}Classificadores{% endblock %}", "<h1>Classificadores</h1>"]


def test_nomes_no_menu():
    itens = {i[0]: i[1] for g in N._GRUPOS for i in g[2]}
    assert {r: itens[r] for r in NOMES} == NOMES


@pytest.mark.parametrize("modelo, titulo, h1", [
    ("triagem_escopo.html", "Triagem de escopo pelo modelo", "Triagem de escopo pelo modelo"),
    ("classificadores.html", "Comparação de classificadores", "Comparação de classificadores"),
    ("validacao.html", "Validação humana da triagem", "Validação humana da triagem"),
])
def test_aba_e_titulo_iguais_ao_menu(modelo, titulo, h1):
    fonte = (RAIZ / "painel" / "templates" / modelo).read_text(encoding="utf-8")
    assert f"{{% block titulo %}}{titulo}{{% endblock %}}" in fonte and f"<h1>{h1}</h1>" in fonte


def test_links_com_o_mesmo_nome():
    assert '<a href="/validacao">← Validação humana da triagem</a>' in (RAIZ / "painel/templates/validacao_item.html").read_text(encoding="utf-8")
    assert '("Validação humana da triagem", "/validacao"),' in (RAIZ / "painel/visao_geral.py").read_text(encoding="utf-8")


def test_nomes_antigos_sairam():
    fontes = "".join(p.read_text(encoding="utf-8") for p in list((RAIZ / "painel" / "templates").glob("*.html")) +
                     [RAIZ / "painel/navegacao.py", RAIZ / "painel/visao_geral.py"])
    for t in ANTIGOS:
        assert t not in fontes, t
