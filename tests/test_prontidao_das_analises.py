"""Analises de achados que dependem de verificacao humana: o estado das hipoteses H2 e H5 segue a prontidao metodologica
(o minimo de rotulagem humana), a H6 tem a sua propria explicacao, o titulo da Adocao diz quando a verificacao e parcial
(a mesma regra do qui-quadrado) e a calibracao so compara os niveis de confianca com o minimo da classe menos frequente.
Os valores (pares, tabelas, subtitulos, graficos) nao mudam."""
import hashlib
import json

import pytest

from dominio import prontidao as P
from painel import analises_blocos as b, analises_blocos_ferramentas as bf
from test_analises_exploratorias import _grafico_sem_titulo

DOIS = {"provedores": [{"provedor": "a"}, {"provedor": "b"}]}
AGUARDA_H2 = "aguarda: o mínimo de verificação humana dos achados (veja o quadro de rotulagem humana acima)"
AGUARDA_H5 = "aguarda: o mínimo de triagem humana dos artigos (veja o quadro de rotulagem humana acima)"
ONDE_H6 = ("análise exploratória dos achados marcados pelo modelo e das respostas em formato inválido; não usa verificação "
           "humana (aba Operação)")
TEXTO_HIPOTESES = [
    "As hipóteses que dependem de pessoas só são respondidas com verificação humana; a coluna Situação diz o que falta em cada uma.",
    "H1 é exploratória: a análise roda sobre os rótulos do modelo e descreve padrões nesses rótulos; não responde à hipótese, "
    "porque nenhuma conclusão sobre uso ou implantação vale sem verificação humana.",
    "H6 é exploratória: relaciona o tamanho do texto enviado ao modelo com o número de achados que ele marcou e com as respostas "
    "em formato inválido; sem verificação humana, descreve o comportamento do modelo, não a perda real de aplicações.",
    "H2 e H5 só podem ser feitas quando o mínimo de rotulagem humana do quadro acima é atingido.",
]


def _prontidao(h2, h5):
    return {"h2": {"destravado": h2, "faltam": 0 if h2 else 40}, "h5": {"destravado": h5, "faltam": 0 if h5 else 10},
            "auditoria": {"destravado": False, "faltam": 59}}


def _situacao(achados_h, artigos_h, prontidao, excluidos_h=True, funil=DOIS):
    res = {"tem_dados_humanos_achados": achados_h, "tem_dados_humanos_artigos": artigos_h}
    bl = b.bloco_hipoteses(res, funil, {"tem_excluidos_checados": excluidos_h}, prontidao)
    return {l[0][:2]: l for l in bl["tabela"]["linhas"]}


# ---------------- R1: H2 e H5 pela prontidao ----------------
@pytest.mark.parametrize("achados_h,artigos_h,prontidao,h2,h5", [
    (False, False, None, "aguarda: verificação humana dos achados", "aguarda: triagem humana dos artigos"),
    (False, False, _prontidao(True, True), "aguarda: verificação humana dos achados", "aguarda: triagem humana dos artigos"),
    (True, True, None, AGUARDA_H2, AGUARDA_H5),
    (True, True, {}, AGUARDA_H2, AGUARDA_H5),
    (True, True, _prontidao(False, False), AGUARDA_H2, AGUARDA_H5),
    (True, True, _prontidao(True, False), "pode ser feita", AGUARDA_H5),
    (True, True, _prontidao(False, True), AGUARDA_H2, "pode ser feita"),
    (True, True, _prontidao(True, True), "pode ser feita", "pode ser feita"),
    (True, False, _prontidao(True, True), "pode ser feita", "aguarda: triagem humana dos artigos"),
    (False, True, _prontidao(True, True), "aguarda: verificação humana dos achados", "pode ser feita"),
])
def test_h2_e_h5_so_podem_ser_feitas_com_a_prontidao_atingida(achados_h, artigos_h, prontidao, h2, h5):
    s = _situacao(achados_h, artigos_h, prontidao)
    assert s["H2"][1] == h2 and s["H5"][1] == h5
    assert s["H2"][2] == "fase 3 (`analises/`)" and s["H5"][2] == "fase 3"


@pytest.mark.parametrize("achados_h,excluidos_h,funil,h3,h4", [
    (True, True, DOIS, "pode ser feita", "pode ser feita"),
    (True, False, {"provedores": [{"provedor": "a"}]}, "aguarda: um segundo buscador usado na coleta e a verificação humana",
     "aguarda: conferência por uma pessoa de uma amostra sorteada dos artigos que o modelo excluiu"),
    (False, True, DOIS, "aguarda: um segundo buscador usado na coleta e a verificação humana", "pode ser feita"),
])
def test_h3_e_h4_nao_dependem_da_prontidao(achados_h, excluidos_h, funil, h3, h4):
    for prontidao in (None, _prontidao(False, False), _prontidao(True, True)):
        s = _situacao(achados_h, True, prontidao, excluidos_h, funil)
        assert s["H3"][1] == h3 and s["H4"][1] == h4


def test_estado_da_h2_segue_a_mesma_trava_do_cartao_de_prontidao():
    """O quadro e o cartao leem a mesma trava: com 598 confirmados e 0 descartados, o cartao diz "faltam 40" e o quadro aguarda."""
    pr = {"h2": P.prontidao_h2(598, 0), "h5": {}, "auditoria": {}}
    cartao = next(c for c in b.bloco_prontidao(pr)["cartoes"] if c["id"] == "h2")
    assert cartao["status"] == "faltam 40" and not cartao["destravado"]
    assert _situacao(True, True, pr)["H2"][1] == AGUARDA_H2


# ---------------- H6 com explicacao propria ----------------
@pytest.mark.parametrize("humano", [False, True])
def test_h6_com_a_sua_explicacao(humano):
    """A H6 nao usa rotulo humano: o texto e o mesmo com ou sem verificacao (nunca o qualificador da H1)."""
    s = _situacao(humano, humano, _prontidao(True, True))
    assert s["H6"] == ["H6 tamanho do texto e falhas", "exploratória", ONDE_H6]
    assert s["H1"][1] == "exploratória" and "uso ou implantação" not in " ".join(s["H6"])


def test_texto_do_quadro_de_hipoteses_por_hipotese():
    bl = b.bloco_hipoteses({"tem_dados_humanos_achados": False, "tem_dados_humanos_artigos": False}, {"provedores": []}, None, None)
    assert bl["titulo"] == "O que o plano de análise já pode responder"
    assert bl["texto"] == TEXTO_HIPOTESES


# ---------------- R3: Adocao com verificacao parcial ----------------
def _maturidade(n_verificados, n_achados=3, base=None, n_descartados=0):
    d = {"n_achados": n_achados, "n_verificados": n_verificados, "n_descartados": n_descartados,
         "tem_dados_humanos": n_verificados > 0,
         "regioes": {"PI": "Nordeste", "SP": "Sudeste", "AC": "Norte"},
         "celulas": [{"uf": "PI", "regiao": "Nordeste", "tecnologia": "reconhecimento_facial", "status_max": "em_uso",
                      "peso": 5, "por_status": {"em_uso": 2}, "n_achados": 2, "n_verificados": min(n_verificados, 2)},
                     {"uf": "SP", "regiao": "Sudeste", "tecnologia": "leitura_placas", "status_max": "piloto",
                      "peso": 4, "por_status": {"piloto": 1}, "n_achados": 1, "n_verificados": max(n_verificados - 2, 0)}]}
    if base:
        d["base"] = base
    return d


TUDO = "1 de 3 UFs com ao menos um achado no estágio “em uso” (estágio do revisor quando ele o registrou; nos demais, o do modelo)"


SEM_HUMANO = "Segundo o modelo, 1 de 3 UFs têm ao menos um achado marcado como “em uso”; nenhum achado foi verificado por pessoa"


def _parcial(nv, na, nd):
    return ("Segundo os rótulos do modelo, com revisão humana parcial, 1 de 3 UFs têm ao menos um achado no estágio “em uso” "
            f"(confirmados por revisor: {nv} de {na} achados do mapa, com o estágio do revisor; descartados, fora do mapa: {nd})")


@pytest.mark.parametrize("nv,na,base,nd,titulo", [
    (1, 3, None, 0, _parcial("1", "3", "0")),
    (2, 3, "status_final_ou_reportado", 0, _parcial("2", "3", "0")),
    (41, 207, None, 16, _parcial("41", "207", "16")),                    # o caso da demonstracao: 57 verificados, 16 descartados
    (1234, 2000, None, 1500, _parcial("1.234", "2.000", "1.500")),
    (1, 3, None, None, _parcial("1", "3", "0")),                         # n_descartados None conta 0
    (1, 3, None, "ausente", _parcial("1", "3", "0")),                    # sem a chave n_descartados: conta 0
    (3, 3, None, 5, TUDO),
    (4, 3, None, 0, TUDO),
    (1, 3, "confirmados", 2, "1 de 3 UFs com ao menos um achado confirmado por revisor no estágio “em uso” (estágio do revisor "
                             "quando ele o registrou; nos demais, o do modelo)"),
    (0, 3, None, 0, SEM_HUMANO),
    (0, 3, None, None, SEM_HUMANO),
    (0, 3, None, "ausente", SEM_HUMANO),
    (0, 3, None, 4, "Segundo o modelo, 1 de 3 UFs têm ao menos um achado marcado como “em uso”; nenhum achado do mapa foi "
                    "confirmado por revisor (descartados, fora do mapa: 4)"),
    (0, 3, None, 1500, "Segundo o modelo, 1 de 3 UFs têm ao menos um achado marcado como “em uso”; nenhum achado do mapa foi "
                       "confirmado por revisor (descartados, fora do mapa: 1.500)"),
])
def test_titulo_da_adocao_diz_a_verificacao_parcial(nv, na, base, nd, titulo):
    d = _maturidade(nv, na, base, nd)
    if nd == "ausente":
        del d["n_descartados"]
    assert b.bloco_maturidade(d)["titulo"] == titulo


AVISO_PARCIAL = ("Só parte destes achados foi conferida por uma pessoa; nos demais, o estágio é o que o modelo atribuiu. "
                 "Não leia o mapa como retrato confirmado da adoção.")


@pytest.mark.parametrize("nv,base,nd,aviso", [
    (0, None, 0, b.AVISO_NAO_VERIFICADO),
    (0, None, 4, b.AVISO_NAO_VERIFICADO),                               # so descartados: nenhum achado do mapa foi conferido
    (1, None, 0, AVISO_PARCIAL),
    (1, None, 4, AVISO_PARCIAL),
    (2, "status_final_ou_reportado", 0, AVISO_PARCIAL),
    (3, None, 0, None),
    (3, None, 4, None),                                                 # todo o mapa confirmado; descartados fora do mapa
    (4, None, 0, None),
    (1, "confirmados", 0, None),
])
def test_aviso_da_adocao_segue_a_verificacao(nv, base, nd, aviso):
    """Com verificacao parcial do mapa, o aviso continua (outro texto); some so com todo o mapa confirmado ou na base de
    confirmados. Os descartados ficam fora do mapa e nao mudam o aviso."""
    assert b.AVISO_VERIFICACAO_PARCIAL == AVISO_PARCIAL
    assert b.bloco_maturidade(_maturidade(nv, 3, base, nd))["aviso"] == aviso


def test_aviso_parcial_usa_a_regra_de_tudo_verificado(monkeypatch):
    monkeypatch.setattr(b, "_tudo_verificado", lambda d: True)
    assert b.bloco_maturidade(_maturidade(1))["aviso"] is None
    monkeypatch.setattr(b, "_tudo_verificado", lambda d: False)
    assert b.bloco_maturidade(_maturidade(3))["aviso"] == AVISO_PARCIAL


def test_par_da_adocao_diz_que_conta_so_os_confirmados():
    pares = dict(b.bloco_maturidade(_maturidade(41, 207, None, 16))["pares"])
    assert pares["Achados do mapa confirmados por revisor"] == "41"
    assert pares["Achados descartados (fora da conta)"] == "16"
    assert "Achados verificados por humano" not in pares


def test_adocao_e_qui_quadrado_usam_a_mesma_regra_de_tudo_verificado(monkeypatch):
    chamadas = []
    original = b._tudo_verificado

    def espiao(d):
        chamadas.append(d)
        return original(d)

    monkeypatch.setattr(b, "_tudo_verificado", espiao)
    d = _maturidade(1)
    b.bloco_maturidade(d)
    assert chamadas and chamadas[-1] is d
    n = len(chamadas)
    d["contingencia_regiao_tecnologia"] = {"tabela": [[30, 2], [2, 30]], "regioes": ["Norte", "Sul"],
                                           "tecnologias": ["reconhecimento_facial", "leitura_placas"], "n": 64}
    b.bloco_regiao_tecnologia(d)
    assert len(chamadas) == n + 1
    monkeypatch.setattr(b, "_tudo_verificado", lambda d: True)
    assert b.bloco_maturidade(_maturidade(1))["titulo"] == TUDO


@pytest.mark.parametrize("nv,na,esperado", [(None, 3, False), (3, None, False), (0, 0, False), (2, 3, False), (3, 3, True),
                                            (4, 3, True), (1, 1, True)])
def test_regra_de_tudo_verificado(nv, na, esperado):
    assert b._tudo_verificado({"n_verificados": nv, "n_achados": na}) is esperado


# ---------------- R4: calibracao so com o minimo da classe menos frequente ----------------
def _calibracao(alta, media, baixa):
    linhas = [{"confianca": c, "n_achados": ok + des, "n_verificados": ok + des, "n_confirmados": ok, "n_descartados": des}
              for c, (ok, des) in zip(("alta", "media", "baixa"), (alta, media, baixa))]
    return {"tem_dados_humanos": True, "n_achados": sum(x["n_achados"] for x in linhas),
            "n_verificados": sum(x["n_verificados"] for x in linhas), "por_confianca": linhas}


@pytest.mark.parametrize("alta,media,baixa,titulo", [
    ((598, 0), (300, 0), (100, 0),
     "Confiança do modelo e acerto real: ainda não dá para comparar os níveis (998 confirmados e 0 descartados; o painel só "
     "compara os níveis com ao menos 40 de cada)"),
    ((19, 1), (6, 4), (3, 7),
     "Confiança do modelo e acerto real: ainda não dá para comparar os níveis (28 confirmados e 12 descartados; o painel só "
     "compara os níveis com ao menos 40 de cada)"),
    ((0, 20), (0, 10), (0, 10),
     "Confiança do modelo e acerto real: ainda não dá para comparar os níveis (0 confirmados e 40 descartados; o painel só "
     "compara os níveis com ao menos 40 de cada)"),
    ((30, 10), (10, 10), (5, 20),
     "Quando o modelo diz confiança alta a pessoa confirma 75% (40 verificados); quando diz baixa, 20% (25 verificados)"),
    ((30, 10), (0, 0), (10, 30),
     "Quando o modelo diz confiança alta a pessoa confirma 75% (40 verificados); quando diz baixa, 25% (40 verificados)"),
    ((1, 0), (39, 40), (0, 1),
     "Quando o modelo diz confiança alta a pessoa confirma 100% (1 verificado); quando diz baixa, 0% (1 verificado)"),
    ((1200, 34), (39, 40), (0, 2),
     "Quando o modelo diz confiança alta a pessoa confirma 97% (1.234 verificados); quando diz baixa, 0% (2 verificados)"),
])
def test_calibracao_so_afirma_com_o_minimo_de_cada_classe(alta, media, baixa, titulo):
    assert b.bloco_calibracao(_calibracao(alta, media, baixa))["titulo"] == titulo


def test_calibracao_le_o_minimo_da_prontidao(monkeypatch):
    monkeypatch.setattr(P, "H2_MIN_CLASSE_RARA", 5)
    assert b.bloco_calibracao(_calibracao((19, 1), (6, 4), (3, 7)))["titulo"] == (
        "Quando o modelo diz confiança alta a pessoa confirma 95% (20 verificados); quando diz baixa, 30% (10 verificados)")
    monkeypatch.setattr(P, "H2_MIN_CLASSE_RARA", 13)
    bl = b.bloco_calibracao(_calibracao((19, 1), (6, 4), (3, 7)))
    assert "o painel só compara os níveis com ao menos 13 de cada" in bl["titulo"]
    assert bl["texto"] == ["Os níveis de confiança só são comparados quando há ao menos 13 achados confirmados e 13 descartados."]


SEM_HUMANOS = {"tem_dados_humanos": False, "n_achados": 10,
               "por_confianca": [{"confianca": c, "n_achados": 3, "n_verificados": 0, "n_confirmados": 0, "n_descartados": 0}
                                 for c in ("alta", "media", "baixa")]}


def _congelado(bl):
    """Tudo menos o titulo: id, subtitulo, pares, tabela, aviso, link, texto e os dados do grafico (o titulo, nome acessivel
    do grafico, trocado por um marcador). Os valores esperados sao os do codigo anterior (F153) para as mesmas entradas, com o
    texto das linhas travadas trocado pelo texto que nao convida a comparar os niveis."""
    v = json.dumps({k: bl[k] for k in ("id", "subtitulo", "pares", "tabela", "aviso", "link", "texto")}, default=str,
                   ensure_ascii=False)
    return hashlib.sha256((v + _grafico_sem_titulo(bl)).encode()).hexdigest()[:16]


@pytest.mark.parametrize("d,esperado", [
    (SEM_HUMANOS, "2c53ac5febd51014"),
    (_calibracao((598, 0), (300, 0), (100, 0)), "0a66e6f240cb56ef"),     # travada: so o texto muda (R1)
    (_calibracao((19, 1), (6, 4), (3, 7)), "ed76e1813fcbcc12"),          # travada: so o texto muda (R1)
    (_calibracao((30, 10), (10, 10), (5, 20)), "6ed731fdb13b10c3"),
    (_calibracao((1, 0), (39, 40), (0, 1)), "10dd00c07888c1da"),
])
def test_calibracao_mantem_os_valores(d, esperado):
    bl = b.bloco_calibracao(d)
    assert _congelado(bl) == esperado
    if d is not SEM_HUMANOS:
        assert bl["subtitulo"].endswith("achados verificados; intervalo de Wilson 95%")


TEXTO_COMPARA = ["Se a coluna 'alta' acerta bem mais que 'baixa', a confiança serve de guia para priorizar a revisão."]
TEXTO_TRAVADA = ["Os níveis de confiança só são comparados quando há ao menos 40 achados confirmados e 40 descartados."]


@pytest.mark.parametrize("alta,media,baixa,texto", [
    ((598, 0), (300, 0), (100, 0), TEXTO_TRAVADA),
    ((19, 1), (6, 4), (3, 7), TEXTO_TRAVADA),
    ((0, 20), (0, 10), (0, 10), TEXTO_TRAVADA),
    ((30, 10), (10, 10), (5, 20), TEXTO_COMPARA),
    ((1, 0), (39, 40), (0, 1), TEXTO_COMPARA),
])
def test_calibracao_travada_nao_convida_a_comparar(alta, media, baixa, texto):
    assert b.bloco_calibracao(_calibracao(alta, media, baixa))["texto"] == texto


def test_calibracao_sem_humanos_continua():
    assert b.bloco_calibracao(SEM_HUMANOS)["titulo"] == "A IA sabe quando tem certeza? Ainda não dá para medir"


# ---------------- R12: um auxiliar so para juntar com "e" ----------------
def test_ferramentas_usam_o_mesmo_juntar_e():
    assert bf._juntar_e is b._juntar_e


# ---------------- a rota le a prontidao uma vez e a passa ao quadro ----------------
def test_visao_geral_le_a_prontidao_uma_vez_e_o_quadro_usa_a_mesma(monkeypatch):
    from painel.rotas_extras import analises as rota

    class Leitura:
        n = 0

        def analise_resumo(self):
            return {"tem_dados_humanos_achados": True, "tem_dados_humanos_artigos": True}

        def analise_funil_por_provedor(self):
            return DOIS

        def analise_falsa_exclusao(self):
            return {"tem_excluidos_checados": True}

        def analise_prontidao(self):
            Leitura.n += 1
            return _prontidao(True, False)

        def analise_maturidade_uf_tecnologia(self):
            return {"n_achados": 3, "n_verificados": 1, "tem_dados_humanos": True}

    blocos, _ = rota.montar(Leitura(), "visao")
    assert Leitura.n == 1
    s = {l[0][:2]: l[1] for l in blocos[1]["tabela"]["linhas"]}
    assert s["H2"] == "pode ser feita" and s["H5"] == AGUARDA_H5
