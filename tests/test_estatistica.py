"""Estatística pura (dominio/estatistica.py): valores de referência de livro-texto, fórmulas fechadas e contas exatas
refeitas aqui com outro caminho (frações, math.comb, formas fechadas), mais propriedades e entradas inválidas."""
import math
from fractions import Fraction

import pytest

from dominio import estatistica as est


def _binomial_exata(k, n, p, inferior=True):
    """Cauda binomial exata com frações racionais (independente da soma em escala log do módulo)."""
    p = Fraction(p).limit_denominator(10 ** 6)
    indices = range(0, k + 1) if inferior else range(k, n + 1)
    return float(sum(Fraction(math.comb(n, i)) * p ** i * (1 - p) ** (n - i) for i in indices))


def _chi2_exato(tabela):
    n = sum(map(sum, tabela))
    linhas = [sum(l) for l in tabela]
    colunas = [sum(c) for c in zip(*tabela)]
    return float(sum(Fraction((tabela[i][j] * n - linhas[i] * colunas[j]) ** 2, n * linhas[i] * colunas[j])
                     for i in range(len(linhas)) for j in range(len(colunas))))


# --------------------------------------------------------------------------------------------------------------
# Funções especiais
# --------------------------------------------------------------------------------------------------------------

def test_quantil_normal_valores_classicos():
    assert est.quantil_normal(0.975) == pytest.approx(1.959963984540054, abs=1e-12)
    assert est.quantil_normal(0.995) == pytest.approx(2.5758293035489, abs=1e-11)
    assert est.quantil_normal(0.5) == 0.0
    assert est.quantil_normal(0.025) == pytest.approx(-1.959963984540054, abs=1e-12)
    for p in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError):
            est.quantil_normal(p)


def test_qui_quadrado_p_valores_criticos_classicos():
    assert est.p_valor_qui_quadrado(3.841458820694124, 1) == pytest.approx(0.05, abs=1e-10)
    assert est.p_valor_qui_quadrado(6.634896601021213, 1) == pytest.approx(0.01, abs=1e-10)
    assert est.p_valor_qui_quadrado(5.991464547107979, 2) == pytest.approx(0.05, abs=1e-10)
    # valores de tabela com 4 decimais (df 3, 5 e 10 a 5%)
    assert est.p_valor_qui_quadrado(7.814728, 3) == pytest.approx(0.05, abs=1e-7)
    assert est.p_valor_qui_quadrado(11.0705, 5) == pytest.approx(0.05, abs=1e-6)
    assert est.p_valor_qui_quadrado(18.307, 10) == pytest.approx(0.05, abs=1e-6)


@pytest.mark.parametrize("x", [0.01, 0.5, 1.0, 3.84, 10.0, 40.0, 150.0])
def test_qui_quadrado_p_valor_contra_formas_fechadas(x):
    # gl = 1: erfc(sqrt(x/2)); gl = 2: exp(-x/2); gl = 4 e 6: soma finita de Poisson; gl = 3: erfc + termo exponencial
    assert est.p_valor_qui_quadrado(x, 1) == pytest.approx(math.erfc(math.sqrt(x / 2)), rel=1e-9, abs=1e-12)
    assert est.p_valor_qui_quadrado(x, 2) == pytest.approx(math.exp(-x / 2), rel=1e-9, abs=1e-12)
    y = x / 2
    assert est.p_valor_qui_quadrado(x, 4) == pytest.approx(math.exp(-y) * (1 + y), rel=1e-9, abs=1e-12)
    assert est.p_valor_qui_quadrado(x, 6) == pytest.approx(math.exp(-y) * (1 + y + y * y / 2), rel=1e-9, abs=1e-12)
    esperado_3 = math.erfc(math.sqrt(y)) + 2 * math.sqrt(y / math.pi) * math.exp(-y)
    assert est.p_valor_qui_quadrado(x, 3) == pytest.approx(esperado_3, rel=1e-9, abs=1e-12)


def test_qui_quadrado_p_valor_extremos():
    assert est.p_valor_qui_quadrado(0, 3) == 1.0
    assert est.p_valor_qui_quadrado(100, 2) == pytest.approx(math.exp(-50), rel=1e-9)  # cauda muito pequena
    with pytest.raises(ValueError):
        est.p_valor_qui_quadrado(-1, 2)
    with pytest.raises(ValueError):
        est.p_valor_qui_quadrado(1, 0)


def test_p_valor_t_formas_fechadas_e_tabela():
    for t in (0.0, 0.5, 1.7, 4.0, -2.0):
        assert est.p_valor_t(t, 1) == pytest.approx(1 - 2 / math.pi * math.atan(abs(t)), abs=1e-10)
        assert est.p_valor_t(t, 2) == pytest.approx(1 - abs(t) / math.sqrt(2 + t * t), abs=1e-10)
    # t crítico bilateral a 5% (tabelas): gl 5 = 2,5706; gl 10 = 2,2281
    assert est.p_valor_t(2.5705818366147, 5) == pytest.approx(0.05, abs=1e-9)
    assert est.p_valor_t(2.2281388519649, 10) == pytest.approx(0.05, abs=1e-9)
    # gl grande aproxima a normal
    assert est.p_valor_t(1.959963984540054, 100000) == pytest.approx(0.05, abs=1e-4)


# --------------------------------------------------------------------------------------------------------------
# Wilson
# --------------------------------------------------------------------------------------------------------------

Z2_95 = 3.841458820694124  # z^2 a 95% = quantil 0,95 da qui-quadrado com 1 gl


def test_wilson_zero_de_cinquenta_forma_fechada():
    # k = 0: inferior = 0 e superior = z^2 / (n + z^2)
    inferior, superior = est.intervalo_wilson(0, 50)
    assert inferior == 0.0
    assert superior == pytest.approx(Z2_95 / (50 + Z2_95), abs=1e-12)
    assert superior == pytest.approx(0.0713476, abs=1e-6)


def test_wilson_cinquenta_de_cinquenta_forma_fechada():
    inferior, superior = est.intervalo_wilson(50, 50)
    assert superior == 1.0
    assert inferior == pytest.approx(50 / (50 + Z2_95), abs=1e-12)
    assert inferior == pytest.approx(0.9286524, abs=1e-6)


def test_wilson_cinco_de_cinquenta_valor_de_livro():
    inferior, superior = est.intervalo_wilson(5, 50)
    assert inferior == pytest.approx(0.04348, abs=5e-6)
    assert superior == pytest.approx(0.21360, abs=5e-6)


def test_wilson_h4_zero_de_150_cabe_abaixo_de_dois_por_cento_so_com_mais_dados():
    # 0/150: limite superior ~ 2,50% (acima de 2%), logo 0 falsos em 150 ainda não prova p < 2% pelo IC de 95%
    assert est.intervalo_wilson(0, 150)[1] == pytest.approx(Z2_95 / (150 + Z2_95), abs=1e-12)
    assert est.intervalo_wilson(0, 150)[1] > 0.02
    assert est.intervalo_wilson(0, 300)[1] < 0.02


def test_wilson_confianca_99_forma_fechada():
    z2_99 = 6.634896601021213
    assert est.intervalo_wilson(0, 50, 0.99)[1] == pytest.approx(z2_99 / (50 + z2_99), abs=1e-12)


def test_wilson_n_zero_devolve_none():
    assert est.intervalo_wilson(0, 0) == (None, None)


def test_wilson_propriedades():
    n = 40
    anterior = (-1.0, -1.0)
    for k in range(n + 1):
        inferior, superior = est.intervalo_wilson(k, n)
        assert 0.0 <= inferior <= k / n <= superior <= 1.0
        assert inferior >= anterior[0] and superior >= anterior[1]  # monotônico em k
        anterior = (inferior, superior)
        # simetria: IC de (n - k) é o espelho de 1 - IC de k
        espelho = est.intervalo_wilson(n - k, n)
        assert espelho[0] == pytest.approx(1 - superior, abs=1e-12)
        assert espelho[1] == pytest.approx(1 - inferior, abs=1e-12)
    # mais confiança, intervalo mais largo; mais dados, mais estreito
    a = est.intervalo_wilson(10, 50, 0.90)
    b = est.intervalo_wilson(10, 50, 0.99)
    assert b[0] < a[0] and b[1] > a[1]
    c = est.intervalo_wilson(100, 500)
    d = est.intervalo_wilson(10, 50)
    assert (c[1] - c[0]) < (d[1] - d[0])


@pytest.mark.parametrize("k,n,conf", [(-1, 10, 0.95), (11, 10, 0.95), (1, -5, 0.95), (1.5, 10, 0.95),
                                      ("a", 10, 0.95), (1, 10, 0), (1, 10, 1), (1, 10, 1.5), (True, 10, 0.95)])
def test_wilson_entradas_invalidas(k, n, conf):
    with pytest.raises(ValueError):
        est.intervalo_wilson(k, n, conf)


# --------------------------------------------------------------------------------------------------------------
# Qui-quadrado
# --------------------------------------------------------------------------------------------------------------

def test_qui_quadrado_2x2_valor_conhecido():
    # esperados 12, 18, 28, 42; chi2 = 4/12 + 4/18 + 4/28 + 4/42 = 0,7937 (25/31,5)
    r = est.teste_qui_quadrado([[10, 20], [30, 40]])
    assert r["chi2"] == pytest.approx(0.7936507936507936, abs=1e-12)
    assert r["gl"] == 1
    assert r["n"] == 100
    assert r["esperados"] == [[12.0, 18.0], [28.0, 42.0]]
    assert r["p_valor"] == pytest.approx(math.erfc(math.sqrt(0.7936507936507936 / 2)), abs=1e-12)
    assert r["p_valor"] == pytest.approx(0.3730, abs=1e-4)
    assert r["celulas_esperado_menor_5"] == 0
    assert r["aviso"] is None
    # em 2x2 o resíduo padronizado ajustado ao quadrado é o próprio chi2
    for linha in r["residuos_padronizados_ajustados"]:
        for v in linha:
            assert v * v == pytest.approx(r["chi2"], abs=1e-12)
    assert r["residuos_padronizados_ajustados"][0][0] < 0 < r["residuos_padronizados_ajustados"][0][1]


def test_qui_quadrado_yates_2x2():
    # chi2_Yates = N (|ad - bc| - N/2)^2 / (r1 r2 c1 c2)
    r = est.teste_qui_quadrado([[10, 20], [30, 40]], correcao_yates=True)
    assert r["chi2"] == pytest.approx(100 * (abs(10 * 40 - 20 * 30) - 50) ** 2 / (30 * 70 * 40 * 60), abs=1e-12)
    assert r["correcao_yates"] is True
    # em tabela maior a correção é ignorada
    assert est.teste_qui_quadrado([[20, 30, 10], [10, 20, 30]], correcao_yates=True)["correcao_yates"] is False


def test_qui_quadrado_2x3_contra_forma_fechada_gl2():
    # esperados todos 15, 25, 20: chi2 = 15,3333; com 2 gl o p é exp(-chi2/2)
    tabela = [[20, 30, 10], [10, 20, 30]]
    r = est.teste_qui_quadrado(tabela)
    assert r["chi2"] == pytest.approx(_chi2_exato(tabela), rel=1e-12)
    assert r["chi2"] == pytest.approx(15.333333333333334, abs=1e-12)
    assert r["gl"] == 2
    assert r["p_valor"] == pytest.approx(math.exp(-r["chi2"] / 2), rel=1e-9)


def test_qui_quadrado_3x3_contra_calculo_exato_e_gl4():
    tabela = [[12, 5, 3], [7, 9, 4], [2, 8, 15]]
    r = est.teste_qui_quadrado(tabela)
    assert r["chi2"] == pytest.approx(_chi2_exato(tabela), rel=1e-12)
    assert r["gl"] == 4
    y = r["chi2"] / 2
    assert r["p_valor"] == pytest.approx(math.exp(-y) * (1 + y), rel=1e-9)
    # resíduos: a soma dos quadrados nunca é menor que o chi2 e o maior |resíduo| está na casela mais discrepante
    maior = max((abs(v), i, j) for i, l in enumerate(r["residuos_padronizados_ajustados"]) for j, v in enumerate(l))
    assert (maior[1], maior[2]) == (2, 2) or (maior[1], maior[2]) == (2, 0)


def test_qui_quadrado_remove_linhas_e_colunas_vazias():
    r = est.teste_qui_quadrado([[10, 0, 20], [0, 0, 0], [30, 0, 40]])
    assert r["chi2"] == pytest.approx(0.7936507936507936, abs=1e-12)
    assert r["linhas_removidas"] == [1] and r["colunas_removidas"] == [1]
    assert r["linhas_mantidas"] == [0, 2] and r["colunas_mantidas"] == [0, 2]
    assert "removidas" in r["aviso"]
    assert r["n"] == 100


def test_qui_quadrado_tabela_sem_dados_ou_degenerada():
    for tabela in ([[0, 0], [0, 0]], [[5, 0], [7, 0]], [[3, 4, 5]], [[0, 0, 0], [0, 6, 0]]):
        r = est.teste_qui_quadrado(tabela)
        assert r["chi2"] is None and r["p_valor"] is None and r["gl"] == 0
        assert r["aviso"]


def test_qui_quadrado_aviso_de_esperados_pequenos():
    r = est.teste_qui_quadrado([[1, 2], [3, 1]])
    assert r["celulas_esperado_menor_5"] == 4
    assert r["menor_esperado"] == pytest.approx(9 / 7, abs=1e-12)  # coluna 2 (soma 3) x linha 1 (soma 3) / N = 7
    assert "5" in r["aviso"] and "Monte Carlo" in r["aviso"]
    # 1 de 6 caselas (17%, abaixo do corte de 20%) com esperado < 5 não dispara o aviso: esperados 3 e 9 na 3a coluna
    grande = est.teste_qui_quadrado([[50, 50, 3], [150, 150, 9]])
    assert grande["celulas_esperado_menor_5"] == 1
    assert grande["aviso"] is None


def test_qui_quadrado_propriedades():
    tabela = [[12, 5, 3], [7, 9, 4], [2, 8, 15]]
    transposta = [list(c) for c in zip(*tabela)]
    a, b = est.teste_qui_quadrado(tabela), est.teste_qui_quadrado(transposta)
    assert a["chi2"] == pytest.approx(b["chi2"], rel=1e-12) and a["p_valor"] == pytest.approx(b["p_valor"], rel=1e-12)
    # multiplicar todas as contagens por m multiplica chi2 por m
    dobro = est.teste_qui_quadrado([[2 * v for v in l] for l in tabela])
    assert dobro["chi2"] == pytest.approx(2 * a["chi2"], rel=1e-12)
    assert dobro["p_valor"] < a["p_valor"]
    # permutar linhas não muda nada
    assert est.teste_qui_quadrado(tabela[::-1])["chi2"] == pytest.approx(a["chi2"], rel=1e-12)
    # independência perfeita
    assert est.teste_qui_quadrado([[10, 20], [20, 40]])["chi2"] == pytest.approx(0.0, abs=1e-12)
    assert est.teste_qui_quadrado([[10, 20], [20, 40]])["p_valor"] == pytest.approx(1.0, abs=1e-12)
    assert 0.0 <= a["p_valor"] <= 1.0
    # os resíduos somam zero por linha e por coluna ponderados: ao menos o sinal é coerente com O - E
    for i, linha in enumerate(a["residuos_padronizados_ajustados"]):
        for j, v in enumerate(linha):
            assert (v > 0) == (tabela[i][j] > a["esperados"][i][j]) or abs(v) < 1e-12


@pytest.mark.parametrize("tabela", [[], [[]], [[1, 2], [3]], [[1, -2], [3, 4]], [[1, "a"], [3, 4]],
                                    [[1, float("nan")], [3, 4]], "texto", [1, 2, 3]])
def test_qui_quadrado_entradas_invalidas(tabela):
    with pytest.raises(ValueError):
        est.teste_qui_quadrado(tabela)


def test_monte_carlo_contra_enumeracao_exata():
    # [[3,1],[1,3]]: com margens fixas a casela a é hipergeométrica (pesos 1,16,36,16,1 de 70);
    # chi2 observado = 2 ocorre em a = 1 e a = 3; chi2 >= 2 também em a = 0 e 4: p exato = 34/70
    r = est.teste_qui_quadrado_monte_carlo([[3, 1], [1, 3]], permutacoes=20000, semente=7)
    assert r["chi2"] == pytest.approx(2.0, abs=1e-12)
    assert r["p_valor"] == pytest.approx(34 / 70, abs=0.015)
    assert r["gl"] == 1 and r["permutacoes"] == 20000 and r["n"] == 8
    assert r["p_valor"] == (r["extremos"] + 1) / 20001


def test_monte_carlo_deterministico_e_correcao_b_mais_1():
    tabela = [[4, 1, 0], [1, 3, 2], [0, 2, 5]]
    a = est.teste_qui_quadrado_monte_carlo(tabela, permutacoes=2000, semente=11)
    b = est.teste_qui_quadrado_monte_carlo(tabela, permutacoes=2000, semente=11)
    c = est.teste_qui_quadrado_monte_carlo(tabela, permutacoes=2000, semente=12)
    assert a == b
    assert a["semente"] == 11 and c["semente"] == 12
    assert 1 / 2001 <= a["p_valor"] <= 1.0
    # associação fortíssima: nenhuma permutação chega perto, p = 1/(B+1), nunca zero
    forte = est.teste_qui_quadrado_monte_carlo([[30, 0], [0, 30]], permutacoes=500, semente=1)
    assert forte["p_valor"] == pytest.approx(1 / 501)
    # independência perfeita: toda permutação é "tão extrema quanto" ou menos; p alto
    assert est.teste_qui_quadrado_monte_carlo([[10, 20], [20, 40]], permutacoes=500, semente=1)["p_valor"] > 0.3


def test_monte_carlo_aproxima_assintotico_com_dados_grandes():
    tabela = [[30, 20], [20, 35]]
    assint = est.teste_qui_quadrado(tabela)["p_valor"]
    mc = est.teste_qui_quadrado_monte_carlo(tabela, permutacoes=10000, semente=3)["p_valor"]
    assert mc == pytest.approx(assint, abs=0.02)


def test_monte_carlo_degenerado_e_invalido():
    r = est.teste_qui_quadrado_monte_carlo([[5, 0], [7, 0]], permutacoes=10)
    assert r["p_valor"] is None and r["aviso"]
    with pytest.raises(ValueError):
        est.teste_qui_quadrado_monte_carlo([[1.5, 2], [3, 4]])
    with pytest.raises(ValueError):
        est.teste_qui_quadrado_monte_carlo([[1, 2], [3, 4]], permutacoes=0)
    with pytest.raises(ValueError):
        est.teste_qui_quadrado_monte_carlo([[1, 2], [3, 4]], semente="x")


# --------------------------------------------------------------------------------------------------------------
# Odds ratio
# --------------------------------------------------------------------------------------------------------------

def test_odds_ratio_forma_fechada():
    # OR = 20*25/(10*5) = 10; erro = sqrt(1/20 + 1/10 + 1/5 + 1/25) = 0,62450
    r = est.odds_ratio_com_ic(20, 10, 5, 25)
    erro = math.sqrt(1 / 20 + 1 / 10 + 1 / 5 + 1 / 25)
    assert r["odds_ratio"] == pytest.approx(10.0, abs=1e-12) and r["or"] == r["odds_ratio"]
    assert r["log_or"] == pytest.approx(math.log(10), abs=1e-12)
    assert r["erro_padrao"] == pytest.approx(erro, abs=1e-12)
    assert r["ic_inferior"] == pytest.approx(math.exp(math.log(10) - 1.959963984540054 * erro), rel=1e-10)
    assert r["ic_superior"] == pytest.approx(math.exp(math.log(10) + 1.959963984540054 * erro), rel=1e-10)
    assert r["ic_inferior"] == pytest.approx(2.9405, abs=1e-4) and r["ic_superior"] == pytest.approx(34.0075, abs=1e-4)
    assert r["correcao_aplicada"] is False and r["aviso"] is None


def test_odds_ratio_haldane_anscombe_com_casela_zero():
    r = est.odds_ratio_com_ic(0, 10, 5, 5)
    assert r["correcao_aplicada"] is True
    assert r["odds_ratio"] == pytest.approx((0.5 * 5.5) / (10.5 * 5.5), abs=1e-12)
    assert r["erro_padrao"] == pytest.approx(math.sqrt(1 / 0.5 + 1 / 10.5 + 1 / 5.5 + 1 / 5.5), abs=1e-12)
    assert r["ic_inferior"] < r["odds_ratio"] < r["ic_superior"]
    assert r["aviso"]


def test_odds_ratio_propriedades_e_degenerados():
    r = est.odds_ratio_com_ic(12, 7, 5, 9)
    invertido = est.odds_ratio_com_ic(5, 9, 12, 7)  # trocar as linhas inverte o OR
    assert invertido["odds_ratio"] == pytest.approx(1 / r["odds_ratio"], rel=1e-12)
    assert invertido["ic_inferior"] == pytest.approx(1 / r["ic_superior"], rel=1e-10)
    assert invertido["ic_superior"] == pytest.approx(1 / r["ic_inferior"], rel=1e-10)
    assert est.odds_ratio_com_ic(10, 10, 10, 10)["odds_ratio"] == pytest.approx(1.0)
    vazio = est.odds_ratio_com_ic(0, 0, 5, 5)
    assert vazio["odds_ratio"] is None and vazio["aviso"] and vazio["correcao_aplicada"] is False
    for args in ((-1, 2, 3, 4), (1, 2, 3, "x"), (1, 2, float("inf"), 4)):
        with pytest.raises(ValueError):
            est.odds_ratio_com_ic(*args)
    with pytest.raises(ValueError):
        est.odds_ratio_com_ic(1, 2, 3, 4, confianca=2)


# --------------------------------------------------------------------------------------------------------------
# Kappa
# --------------------------------------------------------------------------------------------------------------

def _kappa_delta(matriz, pesos, eps=1e-6):
    """Erro-padrão por método delta multinomial com derivadas numéricas (caminho independente da fórmula do módulo)."""
    k = len(matriz)
    n = sum(map(sum, matriz))
    p = [[v / n for v in l] for l in matriz]
    w = [[1.0 if (pesos == "nenhum" and i == j) else 0.0 for j in range(k)] for i in range(k)] if pesos == "nenhum" \
        else [[1 - (abs(i - j) / (k - 1)) ** (1 if pesos == "lineares" else 2) for j in range(k)] for i in range(k)]

    def kappa(q):
        r = [sum(l) for l in q]
        c = [sum(q[i][j] for i in range(k)) for j in range(k)]
        po = sum(w[i][j] * q[i][j] for i in range(k) for j in range(k))
        pe = sum(w[i][j] * r[i] * c[j] for i in range(k) for j in range(k))
        return (po - pe) / (1 - pe)

    g = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            mais = [l[:] for l in p]
            menos = [l[:] for l in p]
            mais[i][j] += eps
            menos[i][j] -= eps
            g[i][j] = (kappa(mais) - kappa(menos)) / (2 * eps)
    media = sum(p[i][j] * g[i][j] for i in range(k) for j in range(k))
    var = (sum(p[i][j] * g[i][j] ** 2 for i in range(k) for j in range(k)) - media ** 2) / n
    return math.sqrt(var)


def test_kappa_cohen_exemplo_classico_2x2():
    # exemplo clássico: 20 sim/sim, 5 sim/não, 10 não/sim, 15 não/não -> po = 0,7, pe = 0,5, kappa = 0,4
    r = est.kappa_cohen([[20, 5], [10, 15]])
    assert r["kappa"] == pytest.approx(0.4, abs=1e-12)
    assert r["concordancia_observada"] == pytest.approx(0.7, abs=1e-12)
    assert r["concordancia_esperada"] == pytest.approx(0.5, abs=1e-12)
    assert r["n"] == 50
    assert r["erro_padrao"] == pytest.approx(_kappa_delta([[20, 5], [10, 15]], "nenhum"), rel=1e-6)
    assert r["erro_padrao"] == pytest.approx(0.1270, abs=1e-4)
    assert r["ic_inferior"] == pytest.approx(0.4 - 1.959963984540054 * r["erro_padrao"], abs=1e-12)
    assert r["ic_superior"] == pytest.approx(0.4 + 1.959963984540054 * r["erro_padrao"], abs=1e-12)


def test_kappa_cohen_segundo_exemplo():
    # po = 0,6, pe = 0,6*0,7 + 0,4*0,3 = 0,54 -> kappa = 0,06/0,46
    assert est.kappa_cohen([[45, 15], [25, 15]])["kappa"] == pytest.approx(0.06 / 0.46, abs=1e-12)


def test_kappa_perfeito_e_pior_que_acaso():
    r = est.kappa_cohen([[10, 0], [0, 10]])
    assert r["kappa"] == pytest.approx(1.0) and r["erro_padrao"] == pytest.approx(0.0, abs=1e-9)
    assert r["ic_superior"] <= 1.0
    r = est.kappa_cohen([[0, 10], [10, 0]])
    assert r["kappa"] == pytest.approx(-1.0)
    assert est.kappa_cohen([[10, 5], [5, 10]])["kappa"] == pytest.approx(1 / 3, abs=1e-12)


M3 = [[22, 5, 1], [6, 18, 4], [2, 7, 15]]


@pytest.mark.parametrize("pesos,kappa,po,pe", [("nenhum", 0.5283018867924528, 0.6875, 0.3375),
                                              ("lineares", 0.5942028985507248, 0.825, 0.56875),
                                              ("quadraticos", 0.6633663366336635, 0.89375, 0.684375)])
def test_kappa_ponderado_3x3_contra_conta_a_mao_e_metodo_delta(pesos, kappa, po, pe):
    # po e pe refeitos à mão: N = 80, margens de linha (28, 28, 24)/80 e de coluna (30, 30, 20)/80
    r = est.kappa_ponderado(M3, pesos=pesos)
    assert r["concordancia_observada"] == pytest.approx(po, abs=1e-12)
    assert r["concordancia_esperada"] == pytest.approx(pe, abs=1e-12)
    assert r["kappa"] == pytest.approx((po - pe) / (1 - pe), abs=1e-12)
    assert r["kappa"] == pytest.approx(kappa, abs=1e-12)
    assert r["erro_padrao"] == pytest.approx(_kappa_delta(M3, pesos), rel=1e-5)
    assert r["ic_inferior"] < r["kappa"] < r["ic_superior"]
    assert r["pesos"] == pesos


def test_kappa_ponderado_padrao_e_quadratico_e_pesos_dao_ordem():
    assert est.kappa_ponderado(M3)["pesos"] == "quadraticos"
    # aqui as discordâncias são em geral adjacentes e valem crédito parcial: nenhum < linear < quadrático
    k = [est.kappa_ponderado(M3, pesos=p)["kappa"] for p in ("nenhum", "lineares", "quadraticos")]
    assert k[0] < k[1] < k[2]
    # 2x2: os três esquemas coincidem
    m = [[20, 5], [10, 15]]
    assert est.kappa_ponderado(m, "lineares")["kappa"] == pytest.approx(0.4)
    assert est.kappa_ponderado(m, "quadraticos")["kappa"] == pytest.approx(0.4)


def test_kappa_simetria_e_degenerados():
    transposta = [list(c) for c in zip(*M3)]
    assert est.kappa_ponderado(transposta)["kappa"] == pytest.approx(est.kappa_ponderado(M3)["kappa"], abs=1e-12)
    # nenhum par
    assert est.kappa_cohen([[0, 0], [0, 0]])["kappa"] is None
    # sem variação (todos "sim" nos dois): pe = 1, kappa indefinido, sem divisão por zero
    sem_variacao = est.kappa_cohen([[10, 0], [0, 0]])
    assert sem_variacao["kappa"] is None and sem_variacao["concordancia_esperada"] == pytest.approx(1.0)
    assert est.kappa_cohen([[7]])["kappa"] is None


@pytest.mark.parametrize("matriz", [[], [[1, 2, 3], [4, 5, 6]], [[1, 2], [3]], [[1, -2], [3, 4]], [[1, "a"], [3, 4]], "xx"])
def test_kappa_entradas_invalidas(matriz):
    with pytest.raises(ValueError):
        est.kappa_ponderado(matriz)


def test_kappa_pesos_invalidos():
    with pytest.raises(ValueError):
        est.kappa_ponderado(M3, pesos="cubicos")


def test_faixa_kappa():
    assert est.faixa_kappa(None) is None
    assert est.faixa_kappa(-0.2) == "fraca"
    assert est.faixa_kappa(0.0) == "fraca"
    assert est.faixa_kappa(0.39) == "fraca"
    assert est.faixa_kappa(0.40) == "moderada"
    assert est.faixa_kappa(0.60) == "moderada"
    assert est.faixa_kappa(0.61) == "substancial"
    assert est.faixa_kappa(0.80) == "substancial"
    assert est.faixa_kappa(0.81) == "quase perfeita"
    assert est.faixa_kappa(1.0) == "quase perfeita"
    with pytest.raises(ValueError):
        est.faixa_kappa("alto")


# --------------------------------------------------------------------------------------------------------------
# McNemar e binomial
# --------------------------------------------------------------------------------------------------------------

def test_mcnemar_exato_5_e_15():
    # n = 20, P(X <= 5) = (1 + 20 + 190 + 1140 + 4845 + 15504)/2^20 = 21700/1048576; bilateral = 0,0413895
    r = est.teste_mcnemar(5, 15)
    assert r["metodo"] == "exato"
    assert r["p_valor"] == pytest.approx(2 * 21700 / 2 ** 20, abs=1e-12)
    assert r["p_valor"] == pytest.approx(0.04139, abs=1e-5)
    assert r["statistic"] == 5
    assert est.teste_mcnemar(15, 5)["p_valor"] == pytest.approx(r["p_valor"], abs=1e-15)  # simétrico


def test_mcnemar_exato_casos_simples():
    assert est.teste_mcnemar(0, 10)["p_valor"] == pytest.approx(2 / 1024, abs=1e-15)
    assert est.teste_mcnemar(7, 7)["p_valor"] == 1.0
    assert est.teste_mcnemar(1, 1)["p_valor"] == 1.0
    # limite: 25 ainda é exato, 26 passa para a qui-quadrado
    assert est.teste_mcnemar(10, 15)["metodo"] == "exato"
    assert est.teste_mcnemar(10, 16)["metodo"] == "qui_quadrado_continuidade"


def test_mcnemar_qui_quadrado_com_continuidade():
    # (|10 - 30| - 1)^2 / 40 = 361/40 = 9,025; p = erfc(sqrt(9,025/2)) = 0,002663 (1 gl)
    r = est.teste_mcnemar(10, 30)
    assert r["metodo"] == "qui_quadrado_continuidade"
    assert r["statistic"] == pytest.approx(9.025, abs=1e-12)
    assert r["p_valor"] == pytest.approx(math.erfc(math.sqrt(9.025 / 2)), abs=1e-12)
    assert r["p_valor"] == pytest.approx(0.002663, abs=1e-6)
    # perto do limite os dois métodos devem concordar na ordem de grandeza
    exato = 2 * _binomial_exata(12, 40, 0.5)
    assert est.teste_mcnemar(12, 28)["p_valor"] == pytest.approx(exato, rel=0.2)


def test_mcnemar_sem_discordantes_e_invalidos():
    r = est.teste_mcnemar(0, 0)
    assert r["p_valor"] is None and r["statistic"] is None and r["metodo"] is None
    for a, b in ((-1, 3), (2.5, 3), ("a", 1)):
        with pytest.raises(ValueError):
            est.teste_mcnemar(a, b)


@pytest.mark.parametrize("k,n,p0,direcao", [(0, 150, 0.02, "menor"), (1, 150, 0.02, "menor"), (2, 300, 0.02, "menor"),
                                            (3, 400, 0.02, "menor"), (5, 100, 0.02, "maior"), (0, 20, 0.5, "menor"),
                                            (12, 20, 0.5, "maior")])
def test_binomial_exato_contra_soma_exata_em_fracoes(k, n, p0, direcao):
    r = est.teste_binomial_exato_unilateral(k, n, p0, direcao)
    assert r["p_valor"] == pytest.approx(_binomial_exata(k, n, p0, direcao == "menor"), rel=1e-9)
    assert r["proporcao"] == k / n and r["direcao"] == direcao


def test_binomial_h4_zero_de_150():
    r = est.teste_binomial_exato_unilateral(0, 150, 0.02)
    assert r["p_valor"] == pytest.approx(0.98 ** 150, rel=1e-12)
    assert r["p_valor"] == pytest.approx(0.0482960, abs=1e-7)
    assert est.selo_de_evidencia(r["p_valor"]) == "moderada"


def test_binomial_estavel_com_n_grande():
    # 0 em 100000 com p0 = 0,02: 0,98^100000 sub-flui para 0 em float direto, mas a soma em log devolve 0 sem erro
    r = est.teste_binomial_exato_unilateral(0, 100000, 0.02)
    assert r["p_valor"] == 0.0
    r = est.teste_binomial_exato_unilateral(1500, 100000, 0.02)
    assert 0.0 < r["p_valor"] < 1e-20  # média 2000, dp ~ 44: 1500 está a ~11 desvios


def test_binomial_propriedades():
    # p cresce com k (cauda inferior) e cai com k (cauda superior); complementaridade P(X<=k) + P(X>=k+1) = 1
    anterior = 0.0
    for k in range(0, 31):
        p = est.teste_binomial_exato_unilateral(k, 30, 0.2)["p_valor"]
        assert anterior <= p <= 1.0
        anterior = p
    for k in range(0, 30):
        soma = (est.teste_binomial_exato_unilateral(k, 30, 0.2, "menor")["p_valor"]
                + est.teste_binomial_exato_unilateral(k + 1, 30, 0.2, "maior")["p_valor"])
        assert soma == pytest.approx(1.0, abs=1e-12)
    assert est.teste_binomial_exato_unilateral(0, 0, 0.02)["p_valor"] is None


@pytest.mark.parametrize("args", [(-1, 10, 0.5), (11, 10, 0.5), (1, 10, 0), (1, 10, 1), (1, 10, 1.2), (1.5, 10, 0.5)])
def test_binomial_entradas_invalidas(args):
    with pytest.raises(ValueError):
        est.teste_binomial_exato_unilateral(*args)


def test_binomial_direcao_invalida():
    with pytest.raises(ValueError):
        est.teste_binomial_exato_unilateral(1, 10, 0.5, direcao="ambas")


# --------------------------------------------------------------------------------------------------------------
# Teste z de proporções
# --------------------------------------------------------------------------------------------------------------

def test_z_proporcoes_conta_a_mao():
    # p1 = 0,30; p2 = 0,45; pooled = 0,375; z = -0,15 / sqrt(0,375*0,625*0,02) = -2,19089; p = 0,028460
    r = est.teste_z_proporcoes(30, 100, 45, 100)
    assert r["z"] == pytest.approx(-0.15 / math.sqrt(0.375 * 0.625 * 0.02), abs=1e-12)
    assert r["z"] == pytest.approx(-2.19089, abs=1e-5)
    assert r["p_valor"] == pytest.approx(math.erfc(abs(r["z"]) / math.sqrt(2)), abs=1e-14)
    assert r["p_valor"] == pytest.approx(0.02846, abs=1e-5)
    assert r["diferenca"] == pytest.approx(-0.15, abs=1e-12)
    erro = math.sqrt(0.3 * 0.7 / 100 + 0.45 * 0.55 / 100)
    assert r["ic_inferior"] == pytest.approx(-0.15 - 1.959963984540054 * erro, abs=1e-10)
    assert r["ic_superior"] == pytest.approx(-0.15 + 1.959963984540054 * erro, abs=1e-10)
    assert r["p_agrupado"] == pytest.approx(0.375)


def test_z_proporcoes_propriedades():
    a = est.teste_z_proporcoes(30, 100, 45, 120)
    b = est.teste_z_proporcoes(45, 120, 30, 100)
    assert a["z"] == pytest.approx(-b["z"], abs=1e-12)
    assert a["p_valor"] == pytest.approx(b["p_valor"], abs=1e-12)
    assert a["ic_inferior"] == pytest.approx(-b["ic_superior"], abs=1e-12)
    assert 0.0 <= a["p_valor"] <= 1.0
    igual = est.teste_z_proporcoes(20, 100, 20, 100)
    assert igual["z"] == 0.0 and igual["p_valor"] == pytest.approx(1.0)


def test_z_proporcoes_sem_variacao_e_invalidos():
    r = est.teste_z_proporcoes(0, 10, 0, 20)
    assert r["z"] is None and r["p_valor"] is None and r["diferenca"] == 0.0
    assert est.teste_z_proporcoes(10, 10, 20, 20)["p_valor"] is None
    for args in ((1, 0, 1, 10), (1, 10, 1, 0), (11, 10, 1, 10), (-1, 10, 1, 10)):
        with pytest.raises(ValueError):
            est.teste_z_proporcoes(*args)


# --------------------------------------------------------------------------------------------------------------
# Brier e calibração
# --------------------------------------------------------------------------------------------------------------

def test_brier_conta_a_mao():
    # ((0,9-1)^2 + (0,5-0)^2 + (0,2-0)^2 + (0,9-0)^2)/4 = (0,01 + 0,25 + 0,04 + 0,81)/4 = 0,2775
    assert est.brier_score([0.9, 0.5, 0.2, 0.9], [1, 0, 0, 0]) == pytest.approx(0.2775, abs=1e-12)
    assert est.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert est.brier_score([0.0, 1.0], [1, 0]) == 1.0
    assert est.brier_score([0.5, 0.5], [True, False]) == pytest.approx(0.25)
    assert est.brier_score([], []) is None


@pytest.mark.parametrize("p,y", [([1.2], [1]), ([-0.1], [0]), ([0.5], [2]), ([0.5], ["sim"]), ([0.5, 0.5], [1]),
                                 ([float("nan")], [1])])
def test_brier_entradas_invalidas(p, y):
    with pytest.raises(ValueError):
        est.brier_score(p, y)


def test_probabilidade_por_confianca_constante():
    assert est.PROBABILIDADE_POR_CONFIANCA == {"alta": 0.9, "media": 0.5, "baixa": 0.2}


def test_tabela_calibracao():
    rotulos = ["alta"] * 10 + ["media"] * 4 + ["baixa"] * 2 + ["alta"]
    desfechos = [1] * 9 + [0] + [1, 1, 0, 0] + [0, 0] + [1]
    linhas = est.tabela_calibracao(rotulos, desfechos)
    assert [l["confianca"] for l in linhas] == ["baixa", "media", "alta"]  # ordem crescente de probabilidade
    baixa, media, alta = linhas
    assert (baixa["n"], baixa["acertos"], baixa["taxa"]) == (2, 0, 0.0)
    assert (media["n"], media["acertos"], media["taxa"]) == (4, 2, 0.5)
    assert (alta["n"], alta["acertos"]) == (11, 10)
    assert alta["taxa"] == pytest.approx(10 / 11)
    assert alta["probabilidade_prevista"] == 0.9 and baixa["probabilidade_prevista"] == 0.2
    assert (alta["ic_inferior"], alta["ic_superior"]) == pytest.approx(est.intervalo_wilson(10, 11))
    assert baixa["ic_inferior"] == 0.0


def test_tabela_calibracao_nivel_vazio_e_invalidos():
    linhas = est.tabela_calibracao(["alta", "alta"], [1, 0])
    vazios = [l for l in linhas if l["n"] == 0]
    assert {l["confianca"] for l in vazios} == {"baixa", "media"}
    assert all(l["taxa"] is None and l["ic_inferior"] is None for l in vazios)
    assert est.tabela_calibracao([], []) == est.tabela_calibracao([], [])
    with pytest.raises(ValueError):
        est.tabela_calibracao(["altissima"], [1])
    with pytest.raises(ValueError):
        est.tabela_calibracao(["alta"], [1, 0])
    with pytest.raises(ValueError):
        est.tabela_calibracao(["alta"], [3])


# --------------------------------------------------------------------------------------------------------------
# Mann-Whitney e Spearman
# --------------------------------------------------------------------------------------------------------------

def _u_por_pares(a, b):
    return sum((x > y) + 0.5 * (x == y) for x in a for y in b)


def test_mann_whitney_sem_empates_conta_a_mao():
    # U_a = pares com a > b = 1 + 2 + 3 + 3 + 3 = 12; mu = 7,5; sigma^2 = 15/12*(8+1) = 11,25
    a, b = [1.1, 2.2, 3.3, 4.4, 5.5], [0.5, 1.5, 2.5]
    r = est.mann_whitney_u(a, b)
    assert r["u"] == 12.0 and r["u_b"] == 3.0
    z = (12 - 7.5 - 0.5) / math.sqrt(11.25)
    assert r["z"] == pytest.approx(z, abs=1e-12)
    assert r["p_valor"] == pytest.approx(math.erfc(z / math.sqrt(2)), abs=1e-12)
    assert r["p_valor"] == pytest.approx(0.2330, abs=1e-4)
    assert r["efeito_rank_biserial"] == pytest.approx(2 * 12 / 15 - 1)
    assert r["u"] == _u_por_pares(a, b)


def test_mann_whitney_com_empates_correcao_da_variancia():
    # a = [1,2,2,3], b = [2,3,4,5]: U_a = 2,5 (contagem de pares); N = 8, empates t = 3 (valor 2) e t = 2 (valor 3):
    # soma(t^3 - t) = 24 + 6 = 30; sigma^2 = 16/12 * (9 - 30/56)
    a, b = [1, 2, 2, 3], [2, 3, 4, 5]
    r = est.mann_whitney_u(a, b)
    assert r["u"] == 2.5 == _u_por_pares(a, b)
    sigma = math.sqrt(16 / 12 * (9 - 30 / 56))
    z = -(abs(2.5 - 8) - 0.5) / sigma
    assert r["z"] == pytest.approx(z, abs=1e-12)
    assert r["p_valor"] == pytest.approx(math.erfc(abs(z) / math.sqrt(2)), abs=1e-12)
    assert r["p_valor"] == pytest.approx(0.1367, abs=1e-4)
    assert r["efeito_rank_biserial"] == pytest.approx(-0.6875)


def test_mann_whitney_propriedades():
    a, b = [3.1, 4.5, 1.2, 9.9, 7.7, 2.0], [0.4, 2.2, 3.3, 1.0, 5.5]
    r, s = est.mann_whitney_u(a, b), est.mann_whitney_u(b, a)
    assert r["u"] + s["u"] == len(a) * len(b)
    assert r["u"] == s["u_b"]
    assert r["z"] == pytest.approx(-s["z"], abs=1e-12)
    assert r["p_valor"] == pytest.approx(s["p_valor"], abs=1e-12)
    assert r["efeito_rank_biserial"] == pytest.approx(-s["efeito_rank_biserial"], abs=1e-12)
    # separação total: efeito = 1 e p pequeno
    sep = est.mann_whitney_u([10, 11, 12, 13, 14, 15, 16, 17], [1, 2, 3, 4, 5, 6, 7, 8])
    assert sep["efeito_rank_biserial"] == 1.0 and sep["p_valor"] < 0.001
    # transformação monotônica não muda nada
    t = est.mann_whitney_u([math.exp(v) for v in a], [math.exp(v) for v in b])
    assert t["u"] == r["u"] and t["p_valor"] == pytest.approx(r["p_valor"], abs=1e-12)
    # diferença menor que a continuidade: z = 0, p = 1
    assert est.mann_whitney_u([1, 2], [1, 2])["p_valor"] == pytest.approx(1.0)


def test_mann_whitney_todos_iguais_e_invalidos():
    r = est.mann_whitney_u([5, 5, 5], [5, 5])
    assert r["z"] is None and r["p_valor"] is None and r["efeito_rank_biserial"] == 0.0
    for a, b in (([], [1]), ([1], []), ([1, "x"], [2]), ([1, float("nan")], [2]), ("abc", [1])):
        with pytest.raises(ValueError):
            est.mann_whitney_u(a, b)


def test_spearman_contas_a_mao():
    # n = 4: d^2 = 0,1,1,0 -> rho = 1 - 6*2/(4*15) = 0,8; t = 0,8*sqrt(2/0,36); com 2 gl p = 1 - t/sqrt(2 + t^2) = 0,2
    r = est.spearman([1, 2, 3, 4], [1, 3, 2, 4])
    assert r["rho"] == pytest.approx(0.8, abs=1e-12)
    assert r["p_valor"] == pytest.approx(0.2, abs=1e-10)
    assert r["n"] == 4
    # com empates (postos médios): y = [5,6,7,8,7] -> postos 1,2,3.5,5,3.5; rho = 8/sqrt(10*9,5)
    r = est.spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7])
    assert r["rho"] == pytest.approx(8 / math.sqrt(95), abs=1e-12)
    t = r["rho"] * math.sqrt(3 / (1 - r["rho"] ** 2))
    assert r["p_valor"] == pytest.approx(est.p_valor_t(t, 3), abs=1e-14)
    assert r["p_valor"] == pytest.approx(0.0886, abs=1e-4)


def test_spearman_propriedades():
    x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    y = [2, 1, 4, 3, 7, 8, 6, 10, 9, 5]
    r = est.spearman(x, y)
    assert r["rho"] == pytest.approx(0.7454545454545455, abs=1e-12)  # 1 - 6*42/(10*99)
    assert 0 < r["p_valor"] < 0.05
    assert est.spearman(y, x)["rho"] == pytest.approx(r["rho"], abs=1e-12)
    assert est.spearman(y, x)["p_valor"] == pytest.approx(r["p_valor"], abs=1e-12)
    # monotônica crescente / decrescente
    assert est.spearman(x, [v ** 3 for v in x])["rho"] == pytest.approx(1.0)
    assert est.spearman(x, [v ** 3 for v in x])["p_valor"] == 0.0
    assert est.spearman(x, [-v for v in x])["rho"] == pytest.approx(-1.0)
    assert est.spearman(x, [-v for v in x])["p_valor"] == 0.0


def test_spearman_pouco_dado_constante_e_invalidos():
    assert est.spearman([1, 2], [2, 1]) == {"rho": None, "p_valor": None, "n": 2}
    assert est.spearman([], [])["rho"] is None
    assert est.spearman([1, 1, 1], [1, 2, 3])["rho"] is None
    with pytest.raises(ValueError):
        est.spearman([1, 2, 3], [1, 2])
    with pytest.raises(ValueError):
        est.spearman([1, 2, "x"], [1, 2, 3])


# --------------------------------------------------------------------------------------------------------------
# Bootstrap e selo
# --------------------------------------------------------------------------------------------------------------

def _media(dados):
    return sum(dados) / len(dados)


def test_bootstrap_deterministico_com_semente():
    dados = [float(v) for v in range(1, 41)]
    a = est.bootstrap_ic(_media, [dados], repeticoes=500, semente=5)
    b = est.bootstrap_ic(_media, [dados], repeticoes=500, semente=5)
    c = est.bootstrap_ic(_media, [dados], repeticoes=500, semente=6)
    assert a == b
    assert (a["ic_inferior"], a["ic_superior"]) != (c["ic_inferior"], c["ic_superior"])
    assert a["estimativa"] == 20.5 and a["repeticoes"] == 500 == a["repeticoes_validas"]


def test_bootstrap_media_proxima_da_formula_normal():
    dados = [float(v) for v in range(1, 101)]  # média 50,5; dp amostral 29,011; EP = 2,9011
    r = est.bootstrap_ic(_media, [dados], repeticoes=4000, semente=1)
    ep = 29.011491975882016 / math.sqrt(100)
    assert r["ic_inferior"] == pytest.approx(50.5 - 1.96 * ep, abs=0.5)
    assert r["ic_superior"] == pytest.approx(50.5 + 1.96 * ep, abs=0.5)
    assert r["ic_inferior"] < r["estimativa"] < r["ic_superior"]


def test_bootstrap_dois_grupos_estilo_icer_e_descarte_de_none():
    custo_a, taxa_a = [1.0, 2.0, 3.0, 4.0], [0, 1, 0, 1]
    custo_b, taxa_b = [1.0, 1.0, 2.0, 2.0], [0, 0, 1, 1]
    grupo_a = list(zip(custo_a, taxa_a))
    grupo_b = list(zip(custo_b, taxa_b))

    def icer(a, b):
        dc = sum(x for x, _ in a) / len(a) - sum(x for x, _ in b) / len(b)
        dt = sum(y for _, y in a) / len(a) - sum(y for _, y in b) / len(b)
        return dc / dt  # ZeroDivisionError quando as taxas empatam: a repetição é descartada

    r = est.bootstrap_ic(icer, [grupo_a, grupo_b], repeticoes=300, semente=2)
    assert r["estimativa"] is None  # taxas médias iguais (0,5 e 0,5) nos dados originais: divisão por zero
    assert 0 < r["repeticoes_validas"] < 300
    assert r["ic_inferior"] <= r["ic_superior"]
    # função que sempre devolve None: sem IC, sem erro
    r = est.bootstrap_ic(lambda d: None, [[1, 2, 3]], repeticoes=10, semente=1)
    assert r["repeticoes_validas"] == 0 and r["ic_inferior"] is None and r["ic_superior"] is None


def test_bootstrap_constante_e_invalidos():
    r = est.bootstrap_ic(_media, [[3.0, 3.0, 3.0]], repeticoes=50, semente=1)
    assert r["ic_inferior"] == r["ic_superior"] == 3.0
    with pytest.raises(ValueError):
        est.bootstrap_ic(_media, [[]])
    with pytest.raises(ValueError):
        est.bootstrap_ic(_media, [])
    with pytest.raises(ValueError):
        est.bootstrap_ic(_media, [[1, 2]], repeticoes=0)
    with pytest.raises(ValueError):
        est.bootstrap_ic(_media, [[1, 2]], confianca=1.0)
    with pytest.raises(ValueError):
        est.bootstrap_ic(_media, [[1, 2]], semente=1.5)
    with pytest.raises(ValueError):
        est.bootstrap_ic("nao_chamavel", [[1, 2]])


def test_bootstrap_nao_mexe_no_gerador_global():
    import random
    random.seed(99)
    esperado = random.random()
    random.seed(99)
    est.bootstrap_ic(_media, [[1.0, 2.0, 3.0]], repeticoes=20, semente=4)
    est.teste_qui_quadrado_monte_carlo([[3, 1], [1, 3]], permutacoes=20, semente=4)
    assert random.random() == esperado


def test_selo_de_evidencia():
    assert est.selo_de_evidencia(None) is None
    assert est.selo_de_evidencia(0.0) == "forte"
    assert est.selo_de_evidencia(0.0099) == "forte"
    assert est.selo_de_evidencia(0.01) == "moderada"
    assert est.selo_de_evidencia(0.0499) == "moderada"
    assert est.selo_de_evidencia(0.05) == "insuficiente"
    assert est.selo_de_evidencia(1.0) == "insuficiente"
    for p in (-0.1, 1.1, "x", float("nan")):
        with pytest.raises(ValueError):
            est.selo_de_evidencia(p)
