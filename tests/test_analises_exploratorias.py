"""Analises baseadas so em classificacoes automatizadas aparecem como exploratorias: o estado das hipoteses, os titulos que
afirmariam um resultado e os titulos "a maior parte" quando a parte nao e maioria. Os valores (contagens, tabelas, subtitulos,
pares, qui-quadrado, p) nao mudam: VALORES guarda o que o codigo anterior produzia para os mesmos dados."""
import copy
import json
import re
from pathlib import Path

import pytest
from markupsafe import escape

from dominio import analises_ferramentas as AF
from painel import analises_blocos as b, analises_blocos_ferramentas as bf, analises_blocos_vies as bv
from test_analises_vies import LEITURA

VALORES = json.loads((Path(__file__).parent / "valores_analises_exploratorias.json").read_text(encoding="utf-8"))
ONDE_H1_SEM = "análise exploratória baseada em classificações automatizadas, ainda sem verificação humana (veja a aba Adoção)"
ONDE_H1_PARCIAL = "análise exploratória baseada em classificações automatizadas, com verificação humana parcial (veja a aba Adoção)"
ONDE_H6_SEM = ("análise exploratória dos achados marcados pelo modelo e das respostas em formato inválido; não usa verificação "
               "humana (aba Operação)")
ONDE_H6_PARCIAL = ONDE_H6_SEM
PRONTIDAO_ATINGIDA = {"h2": {"destravado": True}, "h5": {"destravado": True}}


def _valores(bloco):
    """O que nao pode mudar: tudo menos o titulo, o texto e o grafico (o grafico leva o titulo como nome acessivel)."""
    return json.loads(json.dumps({k: bloco[k] for k in ("id", "subtitulo", "pares", "tabela", "aviso", "link")}, default=str))


def _grafico_sem_titulo(bloco):
    """Os dados do grafico: o SVG com o titulo (nome acessivel) trocado por um marcador e os identificadores internos (derivados
    do titulo) normalizados."""
    svg = str(bloco["grafico"]).replace(str(escape(bloco["titulo"])), "§TITULO§").replace(bloco["titulo"], "§TITULO§")
    return re.sub(r"\b([a-z]{2})-[0-9a-f]{8}", r"\1-ID", svg)


def _linhas_hipoteses(humano):
    res = {"tem_dados_humanos_achados": humano, "tem_dados_humanos_artigos": humano}
    bl = b.bloco_hipoteses(res, {"provedores": [{"provedor": "a"}, {"provedor": "b"}]}, {"tem_excluidos_checados": humano},
                           PRONTIDAO_ATINGIDA)
    return {l[0][:2]: l for l in bl["tabela"]["linhas"]}


@pytest.mark.parametrize("humano,onde_h1,onde_h6", [(False, ONDE_H1_SEM, ONDE_H6_SEM), (True, ONDE_H1_PARCIAL, ONDE_H6_PARCIAL)])
def test_h1_e_h6_sao_exploratorias_e_nunca_feitas(humano, onde_h1, onde_h6):
    linhas = _linhas_hipoteses(humano)
    assert linhas["H1"] == ["H1 região × tecnologia", "exploratória", onde_h1]
    assert linhas["H6"] == ["H6 tamanho do texto e falhas", "exploratória", onde_h6]
    assert "feita" not in " ".join(linhas["H1"] + linhas["H6"]).replace("exploratória", "")


def test_h2_a_h5_nao_mudam():
    """Com a prontidao atingida, H2 a H5 ficam como antes; sem ela, H2 e H5 aguardam (test_prontidao_das_analises.py)."""
    sem, com = _linhas_hipoteses(False), _linhas_hipoteses(True)
    assert {h: sem[h] for h in ("H2", "H3", "H4", "H5")} == {h: VALORES["hipoteses_sem"][h] for h in ("H2", "H3", "H4", "H5")}
    assert {h: com[h] for h in ("H2", "H3", "H4", "H5")} == {h: VALORES["hipoteses_com"][h] for h in ("H2", "H3", "H4", "H5")}


def test_texto_do_quadro_de_hipoteses():
    bl = b.bloco_hipoteses({"tem_dados_humanos_achados": False, "tem_dados_humanos_artigos": False}, {"provedores": []})
    assert bl["titulo"] == "O que o plano de análise já pode responder"
    assert bl["texto"][0] == ("As hipóteses que dependem de pessoas só são respondidas com verificação humana; a coluna Situação diz "
                              "o que falta em cada uma.")
    assert bl["texto"][1] == ("H1 é exploratória: a análise roda sobre os rótulos do modelo e descreve padrões nesses rótulos; não "
                              "responde à hipótese, porque nenhuma conclusão sobre uso ou implantação vale sem verificação humana.")


# ---------------------------------------------------------------- adocao (maturidade)
def _maturidade(n_verificados, base=None):
    d = {"n_achados": 3, "n_verificados": n_verificados, "n_descartados": 0, "tem_dados_humanos": n_verificados > 0,
         "regioes": {"PI": "Nordeste", "SP": "Sudeste", "AC": "Norte"},
         "celulas": [{"uf": "PI", "regiao": "Nordeste", "tecnologia": "reconhecimento_facial", "status_max": "em_uso",
                      "peso": 5, "por_status": {"em_uso": 2}, "n_achados": 2, "n_verificados": min(n_verificados, 2)},
                     {"uf": "SP", "regiao": "Sudeste", "tecnologia": "leitura_placas", "status_max": "piloto",
                      "peso": 4, "por_status": {"piloto": 1}, "n_achados": 1, "n_verificados": max(n_verificados - 2, 0)}]}
    if base:
        d["base"] = base
    return d


@pytest.mark.parametrize("base", [None, "status_final_ou_reportado"])
def test_titulo_da_adocao_sem_verificacao_diz_que_e_o_modelo(base):
    bl = b.bloco_maturidade(_maturidade(0, base))
    assert bl["titulo"] == ("Segundo o modelo, 1 de 3 UFs têm ao menos um achado marcado como “em uso”; nenhum achado foi "
                            "verificado por pessoa")
    assert bl["texto"][0] == ("Cada quadrado mostra o estágio mais avançado que o modelo atribuiu aos achados daquela tecnologia "
                              "naquela UF (do cinza, apenas citado, ao azul-escuro, em uso). Não é verificação de uso. "
                              "Clique para ver os achados.")
    assert _valores(bl) == VALORES["maturidade_sem"]


def test_adocao_com_verificacao_parcial_diz_a_parcialidade_e_nao_muda_os_valores():
    """Mudanca de contrato (residuo R3): com verificacao parcial, o titulo diz quantos achados foram verificados."""
    bl = b.bloco_maturidade(_maturidade(1))
    assert bl["titulo"] == ("Segundo os rótulos do modelo, com revisão humana parcial, 1 de 3 UFs têm ao menos um achado no "
                            "estágio “em uso” (confirmados por revisor: 1 de 3 achados do mapa, com o estágio do revisor; "
                            "descartados, fora do mapa: 0)")
    assert bl["texto"][0] == ("Cada quadrado mostra o estágio mais avançado encontrado para aquela tecnologia naquela UF "
                              "(do cinza, apenas citado, ao azul-escuro, em uso). Clique para ver os achados.")
    assert _valores(bl) == VALORES["maturidade_com"]


# ---------------------------------------------------------------- regiao x tecnologia (H1): qualificado ate tudo estar verificado
def _contingencia(n_verificados, forte):
    tabela = [[30, 2], [2, 30]] if forte else [[10, 10], [10, 10]]
    n = 64 if forte else 40
    return {"tem_dados_humanos": n_verificados > 0, "n_achados": n, "n_verificados": n_verificados,
            "contingencia_regiao_tecnologia": {"tabela": tabela, "regioes": ["Nordeste", "Sudeste"],
                                               "tecnologias": ["reconhecimento_facial", "leitura_placas"], "n": n}}


FORTE_SEM = "Análise exploratória (rótulos do modelo, sem verificação humana): a mistura de tecnologias varia entre as regiões"
FRACO_SEM = ("Análise exploratória (rótulos do modelo, sem verificação humana): sem evidência suficiente de que a mistura de "
             "tecnologias dependa da região")
FORTE_PARCIAL = ("Análise exploratória (rótulos do modelo, com verificação humana parcial): a mistura de tecnologias varia entre as "
                 "regiões")
FRACO_PARCIAL = ("Análise exploratória (rótulos do modelo, com verificação humana parcial): sem evidência suficiente de que a mistura "
                 "de tecnologias dependa da região")


@pytest.mark.parametrize("forte,verif,titulo", [
    (True, 0, FORTE_SEM), (False, 0, FRACO_SEM),
    (True, 1, FORTE_PARCIAL), (False, 1, FRACO_PARCIAL),
    (True, 63, FORTE_PARCIAL), (False, 39, FRACO_PARCIAL),                 # falta um: ainda parcial
    (True, 64, "A mistura de tecnologias muda de uma região para outra"),  # todos verificados: o titulo de sempre
    (False, 40, "Sem evidência suficiente de que a mistura de tecnologias dependa da região"),
])
def test_qui_quadrado_so_sem_qualificacao_com_tudo_verificado(forte, verif, titulo):
    bl = b.bloco_regiao_tecnologia(_contingencia(verif, forte))
    assert bl["titulo"] == titulo
    assert {k: v for k, v in _valores(bl).items() if k != "aviso"} == VALORES["regiao_forte" if forte else "regiao_fraco"]


@pytest.mark.parametrize("tirar,titulo", [
    (("n_verificados", "n_achados"), FORTE_SEM),            # sem as contagens: nada verificado
    (("n_verificados",), FORTE_SEM),
    (("n_achados",), FORTE_PARCIAL),                        # ha verificados, mas o total nao veio: nunca "tudo verificado"
])
def test_qui_quadrado_sem_as_contagens(tirar, titulo):
    d = _contingencia(5, True)
    for k in tirar:
        d.pop(k)
    d["tem_dados_humanos"] = "n_verificados" in d
    assert b.bloco_regiao_tecnologia(d)["titulo"] == titulo


def test_qui_quadrado_sem_verificacao_mantem_aviso_e_dados_do_grafico():
    bl = b.bloco_regiao_tecnologia(_contingencia(0, True))
    assert _valores(bl) == VALORES["regiao_forte_com_aviso"]
    assert _grafico_sem_titulo(bl) == VALORES["grafico_regiao_forte"]


# ---------------------------------------------------------------- ano: "a maior parte" so com maioria, sempre entre os que tem ano
def _temporal(anos_n, sem_ano=0):
    """`anos_n` em ordem crescente de ano, como o leitor entrega."""
    por_ano = [{"ano": a, "n_artigos": n, "n_elegiveis": 0, "n_incluidos": 0} for a, n in anos_n]
    if sem_ano:
        por_ano.append({"ano": None, "n_artigos": sem_ano, "n_elegiveis": 0, "n_incluidos": 0})
    return {"por_ano": por_ano, "n_artigos": sum(n for _a, n in anos_n) + sem_ano,
            "celulas": [{"ano": a, "grupo": "G", "n_artigos": n} for a, n in anos_n]}


@pytest.mark.parametrize("anos_n,sem_ano,titulo", [
    ([(2024, 49), (2025, 51)], 0, "A maior parte dos artigos com ano conhecido é de 2025 (51 artigos, 51%)"),
    ([(2024, 49), (2025, 51)], 20, "A maior parte dos artigos com ano conhecido é de 2025 (51 artigos, 51%)"),
    ([(2024, 99), (2025, 101)], 0, "O ano com mais artigos encontrados é 2025 (101 artigos, 50% dos que têm ano)"),
    ([(2024, 819), (2025, 337)], 0, "A maior parte dos artigos com ano conhecido é de 2024 (819 artigos, 71%)"),
    ([(2023, 300), (2024, 519), (2025, 337)], 0, "O ano com mais artigos encontrados é 2024 (519 artigos, 45% dos que têm ano)"),
    ([(2024, 50), (2025, 50)], 0, "Os anos com mais artigos encontrados são 2024 e 2025 (50 artigos cada, 50% cada dos que têm ano)"),
    ([(2023, 10), (2024, 10), (2025, 10)], 5,
     "Os anos com mais artigos encontrados são 2023, 2024 e 2025 (10 artigos cada, 33% cada dos que têm ano)"),
])
def test_titulo_temporal(anos_n, sem_ano, titulo):
    assert b.bloco_temporal(_temporal(anos_n, sem_ano))["titulo"] == titulo


def test_temporal_valores_nao_mudam():
    bl = b.bloco_temporal(_temporal([(2023, 300), (2024, 519), (2025, 337)], 12))
    assert _valores(bl) == VALORES["temporal"] and _grafico_sem_titulo(bl) == VALORES["grafico_temporal"]


# ---------------------------------------------------------------- custos
def _custos(triagem, outra, academica=0.0):
    linhas = copy.deepcopy(AF.linhas(LEITURA))
    for l in linhas:
        l["custo_usd"] = {"triagem_escopo": triagem, "busca_literatura": outra, "busca_academica": academica}.get(l["etapa"], 0.0)
    return linhas


@pytest.mark.parametrize("triagem,outra,titulo", [
    (0.20, 0.01, "O custo registrado foi US$ 0,21; a maior parte (95%) na triagem de escopo"),
    (0.37, 0.63, "O custo registrado foi US$ 1,00; a maior parte (63%) na busca de literatura na web"),
    (0.506, 0.494, "O custo registrado foi US$ 1,00; a maior parte (51%) na triagem de escopo"),
    (0.505, 0.495, "O custo registrado foi US$ 1,00; a maior parcela (50%) na triagem de escopo"),     # 50,5% aparece como 50%
    (0.50, 0.50, "O custo registrado foi US$ 1,00; empate na maior parcela (50% cada): busca de literatura na web · "
                 "perplexity_search e triagem de escopo · gemini:m"),
])
def test_titulo_dos_custos(triagem, outra, titulo):
    bl = bf.bloco_custos(_custos(triagem, outra))
    assert bl["titulo"] == titulo


def test_custo_sem_maioria_diz_maior_parcela():
    assert bf.bloco_custos(_custos(0.40, 0.35, 0.25))["titulo"] == (
        "O custo registrado foi US$ 1,00; a maior parcela (40%) na triagem de escopo")


def test_custos_empate_na_mesma_etapa_nomeia_as_ferramentas():
    linhas = _custos(0.40, 0.20)
    extra = copy.deepcopy([l for l in linhas if l["etapa"] == "triagem_escopo"][0])
    extra["ferramenta"], extra["custo_usd"] = "outro:modelo", 0.40
    assert bf.bloco_custos(linhas + [extra])["titulo"] == (
        "O custo registrado foi US$ 1,00; empate na maior parcela (40% cada): triagem de escopo · gemini:m e triagem de escopo · "
        "outro:modelo")


def test_custos_valores_nao_mudam():
    bl = bf.bloco_custos(_custos(0.37, 0.63))
    assert _valores(bl) == VALORES["custos"] and _grafico_sem_titulo(bl) == VALORES["grafico_custos"]


# ---------------------------------------------------------------- relevancia por fonte (vies): sem comparar ferramentas
def _ferramenta(nome, fonte, itens, eleg):
    return {"ferramenta": nome, "fonte": fonte, "itens": itens, "alta": eleg, "elegiveis": eleg, "fora": itens - eleg,
            "custo_por_elegivel": None, "creditos_por_elegivel": None}


@pytest.mark.parametrize("linhas,titulo", [
    ([_ferramenta("perplexity_search", "Web", 199, 199), _ferramenta("serpapi_scholar", "Scholar", 521, 468)],
     "Relevância alta ou média segundo o modelo, por fonte: Scholar 468 de 521 itens; Web 199 de 199 itens"),
    ([_ferramenta("serpapi_scholar", "Scholar", 521, 468)],
     "Relevância alta ou média segundo o modelo, por fonte: Scholar 468 de 521 itens"),
    ([_ferramenta("a_busca", "Web", 10, 4), _ferramenta("b_busca", "Web", 10, 4), _ferramenta("serpapi_scholar", "Scholar", 1, 1)],
     "Relevância alta ou média segundo o modelo, por fonte: Scholar 1 de 1 item; Web 4 itens (mais de uma ferramenta; sem total "
     "por fonte)"),
    ([_ferramenta("perplexity_search", "Web", 0, 0), _ferramenta("serpapi_scholar", "Scholar", 5, 2)],
     "Relevância alta ou média segundo o modelo, por fonte: Scholar 2 de 5 itens; Web sem itens"),
    ([_ferramenta("perplexity_search", "Web", 0, 0)],
     "Relevância alta ou média segundo o modelo, por fonte: nenhum item com triagem"),
    ([_ferramenta("a_busca", "Web", 10, 4), _ferramenta("b_busca", "Web", 7, 4), _ferramenta("serpapi_scholar", "Scholar", 1, 1)],
     "Relevância alta ou média segundo o modelo, por fonte: Scholar 1 de 1 item; Web 4 itens (mais de uma ferramenta; sem total "
     "por fonte)"),
])
def test_titulo_da_relevancia_por_fonte_sem_comparar_ferramentas(linhas, titulo):
    bl = bv.bloco_ferramentas_relevancia(linhas)
    assert bl["titulo"] == titulo
    assert "maior parte" not in bl["titulo"] and "maior proporção" not in bl["titulo"]


def test_relevancia_valores_nao_mudam():
    linhas = [_ferramenta("perplexity_search", "Web", 199, 199), _ferramenta("serpapi_scholar", "Scholar", 521, 468)]
    bl = bv.bloco_ferramentas_relevancia(linhas)
    assert _valores(bl) == VALORES["relevancia"] and _grafico_sem_titulo(bl) == VALORES["grafico_relevancia"]
