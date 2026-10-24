"""Tela Referências: a legenda do fim da página explica cada código e cada coluna (consultas e conjuntos, ID, fonte,
execução, colunas da triagem, recorte, local, colunas de leitura e os dois downloads), com ou sem referências."""
import html as H
import re

import pytest

from config import consultas as C, triagem_escopo as TE
from dominio import referencias_busca as RB
from test_referencias_recorte import CONJUNTO, TEXTOS, _cli, banco  # noqa: F401  (fixture `banco`: vies com triagem)

PARES = [
    ("ID", "<strong>W-n</strong> é a referência da web nº n e <strong>A-n</strong>, o artigo do Scholar nº n; o código abre a ficha."),
    ("Fonte da busca", "<strong>Web</strong> é a busca na web; <strong>Scholar</strong>, o Google Scholar."),
    ("Idioma da busca", "Só nos artigos do Scholar, que roda cada consulta com o filtro só português e sem filtro de idioma: "
                        "<strong>Só português</strong> quando só a busca com o filtro achou o artigo; <strong>Sem filtro</strong> "
                        "quando só a busca sem filtro o achou; <strong>As duas</strong> quando as duas o acharam; "
                        "<strong>Outro filtro</strong> quando alguma busca usou outro idioma. Contam todas as buscas que acharam o artigo, "
                        "de qualquer conjunto. Vazio nas referências da web."),
    ("Conjunto", "A letra do conjunto das consultas que acharam a referência (tabela acima); várias letras quando consultas de "
                 "mais de um conjunto a acharam."),
    ("Consultas", "As consultas que acharam a referência, por extenso."),
    ("Execução", "O código de cada execução que achou a referência: data e hora do início em UTC (<code>AAAAMMDD_HHMMSS</code>) e "
                 "seis caracteres que separam execuções do mesmo segundo. Com permissão para ver as chamadas, o código abre a execução."),
    ("Tipo de fonte, País/escopo e Tópicos e palavras-chave",
     "Da triagem do modelo; ficam vazios enquanto a referência não foi triada ou quando a triagem não passou nas conferências."),
    ("Recorte", "Da triagem do modelo. <strong>Viés algorítmico</strong>: o assunto principal é viés, discriminação, equidade, ética, "
                "direitos, transparência, responsabilização ou governança da IA ou de algoritmos. <strong>Aplicações tecnológicas</strong>: "
                "o assunto principal é o uso, a implantação, o desempenho, os produtos ou as soluções de IA ou de tecnologia, sem centrar "
                "no viés ou na ética. Quando o item trata dos dois, vale o que domina o título e o resumo."),
    ("Local", "Pelo país/escopo da triagem: <strong>Brasil</strong> quando alguma parte (separada por \"/\") é Brasil; "
              "<strong>Indeterminado</strong> sem país ou com \"Indeterminado\"; <strong>Internacional</strong> no resto."),
    ("Prioridade de leitura, Status de leitura e Notas", "Para preencher na planilha baixada; o status começa como \"Não iniciado\"."),
    ("Baixar", "<strong>Modelo Érico</strong>: a planilha no modelo de referências ampliado, com as abas \"Referências ampliadas\" e "
               "\"Esquema de exploração\". <strong>Colunas selecionadas</strong>: uma aba \"Referências\" só com as colunas marcadas em "
               "\"Colunas\". As duas levam só as linhas dos filtros desta página."),
]


def _legenda(html):
    m = re.search(r'<section class="legenda-pagina" id="legenda" aria-labelledby="t-legenda">(.*?)</section>', html, re.S)
    assert m, "sem a legenda"
    return m.group(1)


def _pares(legenda):
    return [(H.unescape(dt), H.unescape(dd)) for dt, dd in re.findall(r"<dt>(.*?)</dt><dd>(.*?)</dd>", legenda, re.S)]


@pytest.mark.parametrize("consulta", ["", "?q=nenhuma-referencia-tem-este-texto", "?colunas=ID", "?p=1"])
def test_legenda_no_fim_com_todos_os_pares_na_ordem(banco, tmp_path, consulta):
    html = _cli(banco, tmp_path).get("/literatura/referencias" + consulta).text
    leg = _legenda(html)
    assert '<h2 id="t-legenda">Legenda</h2>' in leg and '<p class="sub">O que significam os códigos e as colunas desta página.</p>' in leg
    assert _pares(leg) == [(dt, H.unescape(dd)) for dt, dd in PARES]
    assert html.index('id="legenda"') > html.index("referência(s).")             # depois da lista (e da paginacao)
    assert html.index("</section>", html.index('id="legenda"')) < html.index("</main>")


def test_tabela_de_consultas_e_conjuntos_na_ordem_da_configuracao(banco, tmp_path):
    leg = _legenda(_cli(banco, tmp_path).get("/literatura/referencias").text)
    linhas = re.findall(r"<tr><td><code>([^<]+)</code></td><td>([^<]+)</td><td>([^<]*)</td></tr>", leg)
    esperado = [(t.id, nome, t.query) for nome, ts in C.CONJUNTOS_LITERATURA.items() for t in ts]
    assert [(c, n, H.unescape(q)) for c, n, q in linhas] == esperado and len(esperado) == 15
    assert '<thead><tr><th scope="col">Código</th><th scope="col">Conjunto</th><th scope="col">Consulta</th></tr></thead>' in leg
    assert leg.index("<h3>Consultas e conjuntos</h3>") < leg.index("<h3>Códigos e colunas</h3>")


def test_legenda_cita_os_rotulos_reais_da_tela():
    """Os nomes da legenda sao os da tela: colunas, recortes, locais, status inicial, abas e modelos de download."""
    texto = " ".join(dt + " " + dd for dt, dd in PARES)
    for coluna in RB.COLUNAS_TELA:
        if coluna not in ("Autor/Instituição", "Ano", "Título", "URL"):          # colunas que se explicam pelo nome
            assert coluna in texto, coluna
    for rotulo in list(TE.RECORTES_VIES.values()) + list(RB.LOCAIS.values()) + list(RB.IDIOMAS_DA_BUSCA.values()) + [RB.IDIOMA_OUTRO]:
        assert f"<strong>{rotulo}</strong>" in texto, rotulo
    for nome in (RB.STATUS_NAO_INICIADO, RB.ABA_REFERENCIAS, RB.ABA_ESQUEMA, RB.ABA_COLUNAS, RB.FONTE_WEB, RB.FONTE_SCHOLAR):
        assert nome in texto, nome


def test_legenda_sem_o_nome_do_orientador_alem_do_modelo(banco, tmp_path):
    leg = _legenda(_cli(banco, tmp_path).get("/literatura/referencias").text)
    assert "orientador" not in leg.lower() and leg.count("Érico") == 1
