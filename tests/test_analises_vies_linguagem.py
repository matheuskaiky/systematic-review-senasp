"""Linguagem das Analises do banco `vies`: cada bloco diz a unidade e o universo, nao chama relevancia do modelo de
inclusao, nao confunde origem da busca com angulo, avisa da classificacao automatica quando mostra rotulos do modelo, nao
le crescimento da producao nos anos nem implantacao nos paises, e o estado vazio nao afirma ausencia na literatura."""
import re

import pytest

from config.eixos_tematicos import EIXOS_EXPLORACAO
from dominio import analises_vies as AV
from painel import analises_blocos_vies as bv
from test_analises_vies import TEXTOS, _art, _itens, _t, _web

NOMES = ("A", "B")
RECORTES = {"vies_algoritmico": "Viés algorítmico", "aplicacoes_tecnologicas": "Aplicações tecnológicas"}


def _lista():
    web = [_web(1), _web(2, consultas="LA1,LB1", conjuntos="A,B"), _web(3, consultas="LB1", conjuntos="B")]
    arts = [_art(5, ano=2025), _art(6, ano=2026, consultas="LA2"), _art(7, ano=None)]
    tri = {("referencia", 1): _t(), ("referencia", 2): _t(status_bruto="media"), ("referencia", 3): _t(status_bruto="fora_do_escopo"),
           ("artigo", 5): _t(), ("artigo", 6): _t(status_bruto="baixa"), ("artigo", 7): _t()}
    for k in tri:
        tri[k]["recorte"] = "vies_algoritmico"
    return _itens(web, arts, tri)


FERRAMENTAS = [{"ferramenta": "busca_x", "fonte": "Web", "itens": 3, "alta": 1, "elegiveis": 2, "fora": 1,
                "custo_por_elegivel": 0.01, "creditos_por_elegivel": None}]


def _blocos(lista):
    return {
        "relevancia": bv.bloco_relevancia(lista), "sobreposicao": bv.bloco_sobreposicao(AV.resumo(lista)),
        "ferramentas": bv.bloco_ferramentas_relevancia(FERRAMENTAS), "grupos": bv.bloco_grupos(lista),
        "relevancia_grupo": bv.bloco_relevancia_por_grupo(lista), "tipos": bv.bloco_tipos(lista),
        "eixos": bv.bloco_eixos(lista, tuple(EIXOS_EXPLORACAO)), "eixo_relevancia": bv.bloco_eixo_relevancia(lista),
        "topicos": bv.bloco_topicos(lista, list(TEXTOS.values())), "anos": bv.bloco_anos(lista, 2026),
        "paises": bv.bloco_paises(lista), "consultas": bv.bloco_consultas(lista, {"A": ["LA1", "LA2"], "B": ["LB1"]}, TEXTOS),
        "conjuntos": bv.bloco_conjuntos(lista, NOMES), "origem_angulo": bv.bloco_origem_angulo(lista, NOMES, RECORTES),
        "dominios": bv.bloco_dominios(lista)}


def _texto(b):
    tab = b["tabela"] or {}
    return " ".join([b["titulo"], b["subtitulo"], b["aviso"] or ""] + b["texto"] + list(tab.get("cabecalho", [])))


# 1 e 2: unidade e universo
@pytest.mark.parametrize("chave, unidade", [
    ("relevancia", "item"), ("sobreposicao", "obra"), ("ferramentas", "itens"), ("grupos", "itens"),
    ("relevancia_grupo", "obra"), ("tipos", "obra"), ("eixos", "obra"), ("eixo_relevancia", "obra"), ("topicos", "obra"),
    ("anos", "artigos do Scholar"), ("paises", "obra"), ("consultas", "item"), ("conjuntos", "obra"),
    ("origem_angulo", "obra"), ("dominios", "referências da web"),
])
def test_cada_bloco_diz_a_unidade_e_o_universo(chave, unidade):
    b = _blocos(_lista())[chave]
    assert b["subtitulo"] and re.search(rf"\b{unidade}s?\b", b["subtitulo"]), (chave, b["subtitulo"])


@pytest.mark.parametrize("chave", ["tipos", "eixos"])
def test_titulo_que_conta_obras_nao_diz_itens(chave):
    titulo = _blocos(_lista())[chave]["titulo"]
    assert re.search(r"\d+ obras?\b", titulo) and not re.search(r"\d+ ite(m|ns)\b", titulo), titulo


# 3: relevancia do modelo nao e inclusao
def test_nenhum_bloco_chama_relevancia_de_elegivel_ou_inclusao():
    for chave, b in _blocos(_lista()).items():
        t = _texto(b).lower()
        assert "elegív" not in t and "incluíd" not in t and "incluída na revisão" not in t, chave


def test_aviso_diz_que_nao_e_inclusao_nem_categoria_validada():
    assert bv.AVISO_MODELO == ("Relevância, ângulo predominante, tipo de fonte, eixo, tópicos e país/escopo vêm da triagem "
                               "automática do modelo, ainda sem conferência humana: não são inclusão na revisão nem "
                               "categorias validadas.")


# 4 e 5: origem x angulo; intersecao indisponivel
def test_origem_e_angulo_separados_e_intersecao_indisponivel():
    b = _blocos(_lista())["origem_angulo"]
    t = " ".join(b["texto"])
    assert "Os conjuntos indicam onde as obras foram encontradas" in t and "classificações predominantes" in t
    assert "indisponível na triagem v2" in t and not re.search(r"interseç\w+[^.]*\b0\b", t.lower())
    assert "Ângulo" not in _blocos(_lista())["conjuntos"]["titulo"]


# 6: anos
def test_anos_nao_afirmam_crescimento_e_dizem_os_sem_ano():
    b = _blocos(_lista())["anos"]
    t = _texto(b)
    assert b["titulo"].startswith("Distribuição por ano dos artigos do Scholar no escopo com ano conhecido")
    assert "não mede o crescimento da produção científica" in t and "interesse pelo tema" not in t
    assert "1 artigo do Scholar no escopo sem ano fica fora do gráfico." in b["texto"]
    assert "não é o ano de publicação" in t and "2026 ainda está em curso" in t


# 7: paises
def test_paises_dizem_que_vem_do_modelo_e_nao_sao_implantacao():
    b = _blocos(_lista())["paises"]
    assert b["titulo"].startswith("Segundo o modelo, ") and "têm o Brasil no país/escopo atribuído" in b["titulo"]
    assert ("As consultas foram escritas em português; a busca na web foi filtrada para páginas em português do Brasil, e o "
            "Scholar rodou com e sem o filtro de português: a amostra puxa para o Brasil e para Portugal.") in b["texto"]
    assert ("O país/escopo é inferido pelo modelo a partir do texto de cada item; não indica onde uma tecnologia foi "
            "implantada.") in b["texto"]
    assert b["aviso"] == bv.AVISO_MODELO


# 8: avisos onde ha rotulos do modelo
@pytest.mark.parametrize("chave", ["relevancia", "ferramentas", "grupos", "relevancia_grupo", "tipos", "eixos", "eixo_relevancia",
                                   "topicos", "paises", "consultas", "origem_angulo"])
def test_blocos_com_rotulos_do_modelo_trazem_o_aviso(chave):
    assert _blocos(_lista())[chave]["aviso"] == bv.AVISO_MODELO


@pytest.mark.parametrize("chave", ["sobreposicao", "conjuntos", "anos", "dominios"])
def test_blocos_sem_rotulos_do_modelo_nao_repetem_o_aviso(chave):
    assert _blocos(_lista())[chave]["aviso"] is None


def test_eixo_pouco_coberto_descreve_o_corpus_recuperado():
    t = " ".join(_blocos(_lista())["eixos"]["texto"])
    assert "descreve o corpus recuperado" in t and "não necessariamente uma lacuna da literatura" in t


# 9: estados vazios
def test_estados_vazios_nao_afirmam_ausencia_na_literatura():
    vazios = _blocos([])
    for chave, b in vazios.items():
        assert "literatura" not in b["titulo"].lower() or chave == "grupos", (chave, b["titulo"])
    assert vazios["topicos"]["titulo"] == "Nenhum tópico classificado foi encontrado nos registros considerados por esta análise"
    assert vazios["topicos"]["aviso"] is None          # sem rotulos exibidos, sem o aviso (D129)
    assert vazios["origem_angulo"]["titulo"] == ("Nenhuma obra com relevância alta ou média segundo o modelo para cruzar "
                                                 "origem e ângulo predominante")


# cartoes e legenda
def test_cartoes_dizem_que_os_numeros_da_triagem_sao_itens():
    from pathlib import Path
    html = Path(__file__).resolve().parents[1].joinpath("painel/templates/analises.html").read_text(encoding="utf-8")
    for rotulo in ("<span>itens com triagem válida do modelo</span>", "<span>itens com relevância alta segundo o modelo</span>",
                   "<span>itens classificados como fora do escopo</span>", "<span>obras distintas</span>"):
        assert rotulo in html, rotulo


def test_legenda_define_elegivel_angulo_e_unidades():
    from pathlib import Path
    leg = Path(__file__).resolve().parents[1].joinpath("painel/templates/_legenda_analises.html").read_text(encoding="utf-8")
    assert "<dt>Elegível</dt><dd>Relevância alta ou média segundo o modelo: rótulo técnico da triagem automática, não é inclusão na revisão.</dd>" in leg
    assert "<dt>Ângulo predominante</dt>" in leg and "<dt>Ocorrência, item, obra e chamada</dt>" in leg


def test_ferramentas_avisam_que_a_comparacao_nao_e_de_qualidade_pura():
    b = _blocos(_lista())["ferramentas"]
    assert b["subtitulo"] == ("por fonte: os itens únicos de cada ferramenta; a parte de relevância alta ou média vem da triagem "
                              "do modelo")
    assert b["texto"][-1].startswith("A comparação entre as ferramentas não é de qualidade pura")


def test_sobreposicao_sem_interpretacao_de_complementaridade():
    from dominio import analises_vies as AV_
    r = {**AV_.resumo(_lista()), "n_obras": 100, "n_em_ambas_fontes": 1}
    assert "As duas fontes se sobrepõem pouco: poucas obras aparecem nas duas." in bv.bloco_sobreposicao(r)["texto"]


def test_introducao_e_legenda_sem_pertinencia_como_fato_nem_lingua_unica():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1] / "painel" / "templates"
    intro = (raiz / "analises.html").read_text(encoding="utf-8")
    assert "quanto o modelo julgou pertinente" in intro and "quanto é pertinente" not in intro
    assert "(consultas escritas em português, nestas fontes)" in intro and "(em português, nestas fontes)" not in intro
    leg = (raiz / "_legenda_analises.html").read_text(encoding="utf-8")
    assert ("<dt>No escopo</dt><dd>Relevância alta, média ou baixa segundo o modelo (saem o que ficou fora do escopo e o que "
            "não tem triagem válida).</dd>") in leg
    assert '(o "resultado" das tabelas de ferramentas)' in leg


@pytest.mark.parametrize("chave", ["anos", "dominios"])
def test_campos_deterministicos_sobre_universo_do_modelo_sem_aviso(chave):
    """Ano e site sao dados das fontes; o universo ("no escopo") depende do modelo e o subtitulo o diz (D129)."""
    b = _blocos(_lista())[chave]
    assert b["aviso"] is None and "no escopo" in b["subtitulo"]
