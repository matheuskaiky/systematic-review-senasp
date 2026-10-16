"""Estatística inferencial pura (sem E/S, só biblioteca padrão: math e random).

Cada função declara a fórmula e os pressupostos no docstring. Convenções:

- Entradas inválidas (negativos, tamanhos incompatíveis, probabilidades fora de [0, 1]) levantam ValueError com
  mensagem em português.
- Quando uma conta não está definida (divisão por zero, amostra vazia, variância nula), a função NÃO levanta erro:
  devolve None nos campos afetados e, quando útil, um texto em "aviso". Quem exibe decide o que mostrar.
- Tudo é determinístico. As funções com sorteio (Monte Carlo, bootstrap) recebem `semente` explícita e usam um
  random.Random próprio; nunca o gerador global.
- Funções especiais (quantil normal, gama incompleta, beta incompleta) são implementadas aqui, sem scipy.
  Precisão alvo: cerca de 1e-10 em valores de p.
"""
import math
import random

from dominio.concordancia import interpretar_kappa

# SUPOSIÇÃO, não medida: probabilidade atribuída a cada nível de confiança do classificador (diagrama de
# confiabilidade e Brier). Os números 0,9 / 0,5 / 0,2 são uma ESCOLHA DE PESQUISA (cenário "padrao"), sem base empírica:
# o Brier mede sobretudo se esse mapeamento bate com a realidade, não só se o modelo separa bons de maus. Por isso
# qualquer Brier divulgado deve vir rotulado como suposição, ao lado de `CENARIOS_PROBABILIDADE` (análise de
# sensibilidade) e da referência "sempre a taxa geral" (`brier_referencia`). Ver docs/ESTATISTICA_EXPLICADA.md, seção 10.
PROBABILIDADE_POR_CONFIANCA = {"alta": 0.9, "media": 0.5, "baixa": 0.2}

# Três mapeamentos nomeados para a análise de sensibilidade do Brier ("padrao" é o PROBABILIDADE_POR_CONFIANCA acima).
CENARIOS_PROBABILIDADE = {
    "padrao": {"alta": 0.9, "media": 0.5, "baixa": 0.2},
    "otimista": {"alta": 0.95, "media": 0.8, "baixa": 0.5},
    "conservador": {"alta": 0.8, "media": 0.6, "baixa": 0.4},
}

_EPS = 1e-300


# ----------------------------------------------------------------------------------------------------------------
# Validação
# ----------------------------------------------------------------------------------------------------------------

def _contagem_inteira(valor, nome):
    """Aceita int (não bool) ou float com valor inteiro; devolve int >= 0."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"{nome} deve ser um número inteiro, recebido {valor!r}")
    if isinstance(valor, float):
        if not math.isfinite(valor) or not float(valor).is_integer():
            raise ValueError(f"{nome} deve ser um número inteiro, recebido {valor!r}")
        valor = int(valor)
    if valor < 0:
        raise ValueError(f"{nome} não pode ser negativo, recebido {valor}")
    return valor


def _confianca_valida(confianca):
    if isinstance(confianca, bool) or not isinstance(confianca, (int, float)) or not (0 < confianca < 1):
        raise ValueError(f"confianca deve estar entre 0 e 1 (exclusivo), recebido {confianca!r}")
    return float(confianca)


def _numero_finito(valor, nome):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError(f"{nome} deve ser um número finito, recebido {valor!r}")
    return float(valor)


def _semente_valida(semente):
    if isinstance(semente, bool) or not isinstance(semente, int):
        raise ValueError(f"semente deve ser um inteiro, recebido {semente!r}")
    return semente


def _inteiro_positivo(valor, nome):
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise ValueError(f"{nome} deve ser um inteiro >= 1, recebido {valor!r}")
    return valor


# ----------------------------------------------------------------------------------------------------------------
# Funções especiais
# ----------------------------------------------------------------------------------------------------------------

def _normal_cdf(z):
    """Função de distribuição da normal padrão: Phi(z) = erfc(-z/sqrt(2))/2."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def _normal_sf_bilateral(z):
    """P(|Z| >= |z|) = erfc(|z|/sqrt(2))."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def quantil_normal(p):
    """Quantil da normal padrão (inversa de Phi), 0 < p < 1, por bisseção sobre erfc (erro < 1e-14)."""
    if not (0 < p < 1):
        raise ValueError(f"p deve estar entre 0 e 1 (exclusivo), recebido {p!r}")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -quantil_normal(1.0 - p)
    inferior, superior = 0.0, 40.0
    for _ in range(200):
        meio = (inferior + superior) / 2.0
        if _normal_cdf(meio) < p:
            inferior = meio
        else:
            superior = meio
    return (inferior + superior) / 2.0


def _z_bilateral(confianca):
    """z crítico bilateral: Phi^-1(1 - (1 - confianca)/2)."""
    return quantil_normal(1.0 - (1.0 - confianca) / 2.0)


def _gama_superior_regularizada(a, x):
    """Q(a, x) = Gamma(a, x)/Gamma(a): série para x < a + 1; fração contínua de Lentz caso contrário."""
    if x <= 0:
        return 1.0
    log_prefixo = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1.0:
        termo = soma = 1.0 / a
        n = a
        for _ in range(100000):
            n += 1.0
            termo *= x / n
            soma += termo
            if abs(termo) < abs(soma) * 1e-17:
                break
        return max(0.0, min(1.0, 1.0 - soma * math.exp(log_prefixo)))
    b = x + 1.0 - a
    c = 1.0 / _EPS
    d = 1.0 / b
    h = d
    for i in range(1, 100000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _EPS:
            d = _EPS
        c = b + an / c
        if abs(c) < _EPS:
            c = _EPS
        d = 1.0 / d
        atraso = d * c
        h *= atraso
        if abs(atraso - 1.0) < 1e-16:
            break
    return max(0.0, min(1.0, math.exp(log_prefixo) * h))


def p_valor_qui_quadrado(estatistica, gl):
    """Cauda superior da qui-quadrado: P(X >= estatistica) com `gl` graus de liberdade = Q(gl/2, estatistica/2)."""
    estatistica = _numero_finito(estatistica, "estatistica")
    if isinstance(gl, bool) or not isinstance(gl, int) or gl < 1:
        raise ValueError(f"gl deve ser um inteiro >= 1, recebido {gl!r}")
    if estatistica < 0:
        raise ValueError("a estatística qui-quadrado não pode ser negativa")
    return _gama_superior_regularizada(gl / 2.0, estatistica / 2.0)


def _fracao_continua_beta(a, b, x):
    """Fração contínua de Lentz para a beta incompleta (Numerical Recipes, betacf)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _EPS:
        d = _EPS
    d = 1.0 / d
    h = d
    for m in range(1, 100000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _EPS:
            d = _EPS
        c = 1.0 + aa / c
        if abs(c) < _EPS:
            c = _EPS
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _EPS:
            d = _EPS
        c = 1.0 + aa / c
        if abs(c) < _EPS:
            c = _EPS
        d = 1.0 / d
        atraso = d * c
        h *= atraso
        if abs(atraso - 1.0) < 1e-16:
            break
    return h


def _beta_incompleta_regularizada(a, b, x):
    """I_x(a, b), regularizada."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_prefixo = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    prefixo = math.exp(log_prefixo)
    if x < (a + 1.0) / (a + b + 2.0):
        return prefixo * _fracao_continua_beta(a, b, x) / a
    return 1.0 - prefixo * _fracao_continua_beta(b, a, 1.0 - x) / b


def p_valor_t(t, gl):
    """P(|T| >= |t|) bilateral da t de Student com `gl` graus de liberdade: I_x(gl/2, 1/2), x = gl/(gl + t^2)."""
    t = _numero_finito(t, "t")
    if isinstance(gl, bool) or not isinstance(gl, (int, float)) or gl <= 0:
        raise ValueError(f"gl deve ser positivo, recebido {gl!r}")
    return max(0.0, min(1.0, _beta_incompleta_regularizada(gl / 2.0, 0.5, gl / (gl + t * t))))


def _logsomaexp(valores):
    maior = max(valores)
    if maior == -math.inf:
        return -math.inf
    return maior + math.log(sum(math.exp(v - maior) for v in valores))


def _log_pmf_binomial(i, n, p):
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def _cauda_binomial(k, n, p, inferior):
    """P(X <= k) se `inferior`, senão P(X >= k), com X ~ Binomial(n, p), somada em escala log (0 < p < 1)."""
    faixa = range(0, k + 1) if inferior else range(k, n + 1)
    return min(1.0, math.exp(_logsomaexp([_log_pmf_binomial(i, n, p) for i in faixa])))


# ----------------------------------------------------------------------------------------------------------------
# Proporções
# ----------------------------------------------------------------------------------------------------------------

def intervalo_wilson(k, n, confianca=0.95):
    """Intervalo de Wilson (escore) para uma proporção k/n. Devolve (inferior, superior), ambos em [0, 1].

    Fórmula, com p = k/n e z = quantil normal bilateral:
        centro = (p + z^2/(2n)) / (1 + z^2/n)
        meia   = z / (1 + z^2/n) * sqrt(p(1-p)/n + z^2/(4n^2))
    Vale para n pequeno e p perto de 0 ou 1 (k = 0 dá inferior = 0; k = n dá superior = 1).
    n = 0 não tem proporção: devolve (None, None). Exige 0 <= k <= n.
    """
    k = _contagem_inteira(k, "k")
    n = _contagem_inteira(n, "n")
    confianca = _confianca_valida(confianca)
    if k > n:
        raise ValueError(f"k ({k}) não pode ser maior que n ({n})")
    if n == 0:
        return (None, None)
    z = _z_bilateral(confianca)
    p = k / n
    denominador = 1.0 + z * z / n
    centro = (p + z * z / (2.0 * n)) / denominador
    meia = z / denominador * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    inferior = 0.0 if k == 0 else max(0.0, centro - meia)
    superior = 1.0 if k == n else min(1.0, centro + meia)
    return (inferior, superior)


def teste_z_proporcoes(k1, n1, k2, n2, confianca=0.95):
    """Teste z bilateral para a diferença de duas proporções independentes (p1 - p2).

    Estatística (variância agrupada sob H0: p1 = p2): z = (p1 - p2) / sqrt(pa(1-pa)(1/n1 + 1/n2)), pa = (k1+k2)/(n1+n2).
    p_valor = P(|Z| >= |z|). O IC da diferença usa o erro-padrão não agrupado (Wald):
    (p1 - p2) +- z_crit * sqrt(p1(1-p1)/n1 + p2(1-p2)/n2). Pressupõe amostras grandes o bastante (n*p >= 5 em
    cada grupo); com poucas ocorrências prefira o teste exato.
    n1 ou n2 igual a 0 levanta ValueError. Se pa for 0 ou 1 (nenhuma variação), z e p_valor são None.
    Devolve dict: z, p_valor, diferenca, ic_inferior, ic_superior, p1, p2, p_agrupado.
    """
    k1, n1 = _contagem_inteira(k1, "k1"), _contagem_inteira(n1, "n1")
    k2, n2 = _contagem_inteira(k2, "k2"), _contagem_inteira(n2, "n2")
    confianca = _confianca_valida(confianca)
    if n1 == 0 or n2 == 0:
        raise ValueError("n1 e n2 devem ser maiores que zero")
    if k1 > n1 or k2 > n2:
        raise ValueError("k não pode ser maior que n em nenhum dos grupos")
    p1, p2 = k1 / n1, k2 / n2
    agrupado = (k1 + k2) / (n1 + n2)
    diferenca = p1 - p2
    z_critico = _z_bilateral(confianca)
    erro = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    resultado = {"z": None, "p_valor": None, "diferenca": diferenca,
                 "ic_inferior": diferenca - z_critico * erro, "ic_superior": diferenca + z_critico * erro,
                 "p1": p1, "p2": p2, "p_agrupado": agrupado}
    variancia = agrupado * (1 - agrupado) * (1.0 / n1 + 1.0 / n2)
    if variancia > 0:
        z = diferenca / math.sqrt(variancia)
        resultado["z"] = z
        resultado["p_valor"] = _normal_sf_bilateral(z)
    return resultado


def teste_binomial_exato_unilateral(k, n, p0, direcao="menor"):
    """Teste binomial exato unilateral de H0 contra a proporção de referência p0 (0 < p0 < 1).

    direcao="menor": H1: p < p0, p_valor = P(X <= k) = soma_{i<=k} C(n,i) p0^i (1-p0)^(n-i)   (caso H4: p0 = 0.02).
    direcao="maior": H1: p > p0, p_valor = P(X >= k).
    A soma usa log-gama e log-soma-exp, estável para n grande e p0 pequeno.
    n = 0 não tem dado: p_valor None. Devolve dict: p_valor, k, n, p0, direcao, proporcao (k/n ou None).
    """
    k = _contagem_inteira(k, "k")
    n = _contagem_inteira(n, "n")
    if k > n:
        raise ValueError(f"k ({k}) não pode ser maior que n ({n})")
    if isinstance(p0, bool) or not isinstance(p0, (int, float)) or not (0 < p0 < 1):
        raise ValueError(f"p0 deve estar entre 0 e 1 (exclusivo), recebido {p0!r}")
    if direcao not in ("menor", "maior"):
        raise ValueError(f"direcao deve ser 'menor' ou 'maior', recebido {direcao!r}")
    resultado = {"p_valor": None, "k": k, "n": n, "p0": float(p0), "direcao": direcao,
                 "proporcao": (k / n) if n else None}
    if n > 0:
        resultado["p_valor"] = _cauda_binomial(k, n, float(p0), inferior=(direcao == "menor"))
    return resultado


def limite_superior_binomial_exato(k, n, confianca=0.95):
    """Limite superior unilateral exato (Clopper-Pearson) de confiança `confianca` para uma proporção, dados k eventos em n.

    É o p tal que P(X <= k | p) = 1 - confianca, com X ~ Binomial(n, p), achado por bisseção sobre a cauda binomial (as
    mesmas funções em escala log do teste exato). Leitura: com `confianca` de 95%, a proporção verdadeira é no máximo
    este valor. k = n dá 1. n = 0 não tem dado: devolve None. Exige 0 <= k <= n.

    Equivalência exata com o teste binomial unilateral: `limite_superior_binomial_exato(k, n, c) < p0` se e somente se
    `teste_binomial_exato_unilateral(k, n, p0, "menor")["p_valor"] < 1 - c` (a cauda P(X <= k | p) só diminui quando p
    cresce; só um empate exato em ponto flutuante pode desfazer a igualdade). Assim o veredito "o limite está abaixo da meta p0" e o p-valor nunca discordam. Com k = 0 vale
    1 - (1 - c)^(1/n), próximo de 3/n para c = 0,95 (regra dos três).
    """
    k = _contagem_inteira(k, "k")
    n = _contagem_inteira(n, "n")
    confianca = _confianca_valida(confianca)
    if k > n:
        raise ValueError(f"k ({k}) não pode ser maior que n ({n})")
    if n == 0:
        return None
    if k == n:
        return 1.0
    alfa = 1.0 - confianca
    inferior, superior = 0.0, 1.0
    for _ in range(200):
        meio = (inferior + superior) / 2.0
        if meio <= inferior or meio >= superior:
            break
        if _cauda_binomial(k, n, meio, inferior=True) > alfa:
            inferior = meio
        else:
            superior = meio
    return (inferior + superior) / 2.0


def teste_mcnemar(so_a, so_b):
    """Teste de McNemar para pares discordantes (so_a: só A marcou; so_b: só B marcou). H0: so_a e so_b equiprováveis.

    Com so_a + so_b <= 25 usa o teste exato bilateral: p = min(1, 2 * P(X <= min(so_a, so_b))), X ~ Binomial(n, 0.5),
    n = so_a + so_b; statistic = min(so_a, so_b). Acima disso usa a qui-quadrado (1 gl) com correção de continuidade:
    statistic = (|so_a - so_b| - 1)^2 / (so_a + so_b).
    Sem discordantes (n = 0) não há o que testar: statistic, p_valor e metodo = None.
    Devolve dict: statistic, p_valor, metodo ("exato" | "qui_quadrado_continuidade"), so_a, so_b.
    """
    so_a = _contagem_inteira(so_a, "so_a")
    so_b = _contagem_inteira(so_b, "so_b")
    n = so_a + so_b
    resultado = {"statistic": None, "p_valor": None, "metodo": None, "so_a": so_a, "so_b": so_b}
    if n == 0:
        return resultado
    if n <= 25:
        menor = min(so_a, so_b)
        resultado["statistic"] = float(menor)
        resultado["p_valor"] = min(1.0, 2.0 * _cauda_binomial(menor, n, 0.5, inferior=True))
        resultado["metodo"] = "exato"
    else:
        estatistica = (abs(so_a - so_b) - 1) ** 2 / n
        resultado["statistic"] = estatistica
        resultado["p_valor"] = p_valor_qui_quadrado(estatistica, 1)
        resultado["metodo"] = "qui_quadrado_continuidade"
    return resultado


def odds_ratio_com_ic(a, b, c, d, confianca=0.95):
    """Razão de chances de uma tabela 2x2 [[a, b], [c, d]] com IC de Wald na escala log.

    OR = (a*d)/(b*c); erro-padrão de ln(OR) = sqrt(1/a + 1/b + 1/c + 1/d); IC = exp(ln(OR) +- z * erro).
    Se alguma casela é 0 aplica-se a correção de Haldane-Anscombe (soma 0,5 às quatro caselas) e
    `correcao_aplicada` = True. Se uma linha ou coluna inteira é zero o OR não é estimável: campos None e `aviso`.
    Devolve dict: odds_ratio (também em "or"), ic_inferior, ic_superior, log_or, erro_padrao, correcao_aplicada, aviso.
    """
    caselas = [_numero_finito(v, nome) for v, nome in ((a, "a"), (b, "b"), (c, "c"), (d, "d"))]
    if any(v < 0 for v in caselas):
        raise ValueError("as caselas da tabela 2x2 não podem ser negativas")
    confianca = _confianca_valida(confianca)
    a, b, c, d = caselas
    vazio = {"odds_ratio": None, "or": None, "ic_inferior": None, "ic_superior": None, "log_or": None,
             "erro_padrao": None, "correcao_aplicada": False, "aviso": None}
    if a + b == 0 or c + d == 0 or a + c == 0 or b + d == 0:
        vazio["aviso"] = "linha ou coluna da tabela 2x2 é toda zero: razão de chances não estimável"
        return vazio
    correcao = any(v == 0 for v in caselas)
    if correcao:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    razao = (a * d) / (b * c)
    log_or = math.log(razao)
    erro = math.sqrt(1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d)
    z = _z_bilateral(confianca)
    vazio.update({"odds_ratio": razao, "or": razao, "ic_inferior": math.exp(log_or - z * erro),
                  "ic_superior": math.exp(log_or + z * erro), "log_or": log_or, "erro_padrao": erro,
                  "correcao_aplicada": correcao})
    if correcao:
        vazio["aviso"] = "casela zero: aplicada a correção de Haldane-Anscombe (+0,5 em cada casela)"
    return vazio


# ----------------------------------------------------------------------------------------------------------------
# Qui-quadrado
# ----------------------------------------------------------------------------------------------------------------

def _preparar_tabela(tabela):
    """Valida a tabela e remove linhas/colunas de soma zero. Devolve (dados, linhas, colunas, rem_l, rem_c, total)."""
    if not isinstance(tabela, (list, tuple)) or len(tabela) == 0:
        raise ValueError("a tabela de contingência deve ser uma lista não vazia de linhas")
    largura = None
    linhas_validas = []
    for i, linha in enumerate(tabela):
        if not isinstance(linha, (list, tuple)) or len(linha) == 0:
            raise ValueError(f"a linha {i} da tabela deve ser uma lista não vazia")
        if largura is None:
            largura = len(linha)
        elif len(linha) != largura:
            raise ValueError("todas as linhas da tabela devem ter o mesmo número de colunas")
        valores = []
        for j, v in enumerate(linha):
            v = _numero_finito(v, f"tabela[{i}][{j}]")
            if v < 0:
                raise ValueError(f"tabela[{i}][{j}] não pode ser negativo")
            valores.append(v)
        linhas_validas.append(valores)
    soma_linhas = [sum(l) for l in linhas_validas]
    soma_colunas = [sum(l[j] for l in linhas_validas) for j in range(largura)]
    manter_l = [i for i, s in enumerate(soma_linhas) if s > 0]
    manter_c = [j for j, s in enumerate(soma_colunas) if s > 0]
    removidas_l = [i for i, s in enumerate(soma_linhas) if s == 0]
    removidas_c = [j for j, s in enumerate(soma_colunas) if s == 0]
    dados = [[linhas_validas[i][j] for j in manter_c] for i in manter_l]
    return dados, manter_l, manter_c, removidas_l, removidas_c, sum(soma_linhas)


def _esperados(dados):
    total = sum(sum(l) for l in dados)
    soma_l = [sum(l) for l in dados]
    soma_c = [sum(l[j] for l in dados) for j in range(len(dados[0]))]
    return [[soma_l[i] * soma_c[j] / total for j in range(len(soma_c))] for i in range(len(soma_l))], soma_l, soma_c, total


def teste_qui_quadrado(tabela, correcao_yates=False):
    """Teste qui-quadrado de independência de Pearson sobre uma tabela de contingência (lista de listas de contagens).

    E_ij = (soma_linha_i * soma_coluna_j) / N;  chi2 = soma (O_ij - E_ij)^2 / E_ij;  gl = (L - 1)(C - 1);
    p_valor = Q(gl/2, chi2/2) (gama incompleta superior regularizada, implementação própria).
    Resíduos padronizados ajustados: (O - E) / sqrt(E (1 - linha_i/N)(1 - coluna_j/N)); |r| > 2 sugere cela
    super ou sub-representada. `correcao_yates=True` só vale para 2x2: usa (|O - E| - 0,5)^2 / E (limitado a 0).
    Linhas e colunas de soma zero são removidas antes do cálculo (índices originais em `linhas_removidas` e
    `colunas_removidas`, índices mantidos em `linhas_mantidas` e `colunas_mantidas`; `esperados` e
    `residuos_padronizados_ajustados` têm o formato da tabela reduzida). Se sobrar menos de 2 linhas ou 2 colunas
    (ou N = 0) o teste não é definido: chi2, gl = 0, p_valor e residuos None, com `aviso`.
    `celulas_esperado_menor_5`: contagem de caselas com E < 5; `aviso` também aparece quando isso ocorre em mais
    de 20% das caselas (use então teste_qui_quadrado_monte_carlo).
    Devolve dict: chi2, gl, p_valor, esperados, residuos_padronizados_ajustados, n, celulas_esperado_menor_5,
    menor_esperado, proporcao_esperado_menor_5, aviso, linhas_removidas, colunas_removidas, linhas_mantidas,
    colunas_mantidas, correcao_yates.
    """
    dados, manter_l, manter_c, rem_l, rem_c, total = _preparar_tabela(tabela)
    resultado = {"chi2": None, "gl": 0, "p_valor": None, "esperados": None, "residuos_padronizados_ajustados": None,
                 "n": total, "celulas_esperado_menor_5": 0, "menor_esperado": None,
                 "proporcao_esperado_menor_5": None, "aviso": None, "linhas_removidas": rem_l,
                 "colunas_removidas": rem_c, "linhas_mantidas": manter_l, "colunas_mantidas": manter_c,
                 "correcao_yates": False}
    avisos = []
    if rem_l:
        avisos.append(f"linhas de soma zero removidas (índices {rem_l})")
    if rem_c:
        avisos.append(f"colunas de soma zero removidas (índices {rem_c})")
    if total == 0 or len(dados) < 2 or len(dados[0]) < 2:
        avisos.append("teste não definido: restam menos de 2 linhas ou 2 colunas com dados")
        resultado["aviso"] = "; ".join(avisos)
        return resultado
    esperados, soma_l, soma_c, total = _esperados(dados)
    yates = bool(correcao_yates) and len(dados) == 2 and len(dados[0]) == 2
    chi2 = 0.0
    residuos = []
    for i, linha in enumerate(dados):
        res_linha = []
        for j, observado in enumerate(linha):
            esperado = esperados[i][j]
            desvio = abs(observado - esperado)
            if yates:
                desvio = max(0.0, desvio - 0.5)
            chi2 += desvio * desvio / esperado
            variancia = esperado * (1.0 - soma_l[i] / total) * (1.0 - soma_c[j] / total)
            res_linha.append((observado - esperado) / math.sqrt(variancia))
        residuos.append(res_linha)
    gl = (len(dados) - 1) * (len(dados[0]) - 1)
    caselas = [e for l in esperados for e in l]
    abaixo = sum(1 for e in caselas if e < 5)
    proporcao = abaixo / len(caselas)
    if proporcao > 0.20:
        avisos.append(f"{abaixo} de {len(caselas)} caselas ({proporcao:.0%}) com frequência esperada < 5: "
                      "a aproximação qui-quadrado pode ser imprecisa; prefira a simulação de Monte Carlo")
    resultado.update({"chi2": chi2, "gl": gl, "p_valor": p_valor_qui_quadrado(chi2, gl), "esperados": esperados,
                      "residuos_padronizados_ajustados": residuos, "n": total, "celulas_esperado_menor_5": abaixo,
                      "menor_esperado": min(caselas), "proporcao_esperado_menor_5": proporcao,
                      "aviso": "; ".join(avisos) if avisos else None, "correcao_yates": yates})
    return resultado


def teste_qui_quadrado_monte_carlo(tabela, permutacoes=10000, semente=0):
    """Qui-quadrado de independência por permutação (Monte Carlo), para tabelas com frequências esperadas pequenas.

    Embaralha os rótulos de coluna entre as unidades, preservando as margens de linha e de coluna, e recalcula
    chi2 = soma O^2/E - N em cada permutação. p_valor = (b + 1) / (B + 1), em que b conta as permutações com
    chi2 >= o observado (tolerância relativa 1e-9) e B = `permutacoes`; nunca é zero. Exige contagens inteiras.
    Determinístico para a mesma `semente`. Linhas/colunas de soma zero são removidas, como em teste_qui_quadrado.
    Se o teste não é definido (menos de 2 linhas ou colunas), p_valor e chi2 são None.
    Devolve dict: chi2, gl, p_valor, extremos (b), permutacoes, semente, n, aviso, linhas_removidas, colunas_removidas.
    """
    permutacoes = _inteiro_positivo(permutacoes, "permutacoes")
    semente = _semente_valida(semente)
    dados, manter_l, manter_c, rem_l, rem_c, total = _preparar_tabela(tabela)
    for linha in dados:
        for v in linha:
            if v != int(v):
                raise ValueError("a simulação de Monte Carlo exige contagens inteiras")
    resultado = {"chi2": None, "gl": 0, "p_valor": None, "extremos": None, "permutacoes": permutacoes,
                 "semente": semente, "n": int(total), "aviso": None, "linhas_removidas": rem_l,
                 "colunas_removidas": rem_c}
    if total == 0 or len(dados) < 2 or len(dados[0]) < 2:
        resultado["aviso"] = "teste não definido: restam menos de 2 linhas ou 2 colunas com dados"
        return resultado
    esperados, soma_l, soma_c, total = _esperados(dados)
    n_l, n_c = len(dados), len(dados[0])
    rotulos_linha = []
    rotulos_coluna = []
    for i in range(n_l):
        for j in range(n_c):
            quantidade = int(dados[i][j])
            rotulos_linha.extend([i] * quantidade)
            rotulos_coluna.extend([j] * quantidade)
    invertidos = [[1.0 / esperados[i][j] for j in range(n_c)] for i in range(n_l)]

    def estatistica(contagens):
        return sum(contagens[i][j] ** 2 * invertidos[i][j] for i in range(n_l) for j in range(n_c)) - total

    observado = estatistica(dados)
    limite = observado - 1e-9 * max(1.0, abs(observado))
    gerador = random.Random(semente)
    extremos = 0
    for _ in range(permutacoes):
        gerador.shuffle(rotulos_coluna)
        contagens = [[0] * n_c for _ in range(n_l)]
        for i, j in zip(rotulos_linha, rotulos_coluna):
            contagens[i][j] += 1
        if estatistica(contagens) >= limite:
            extremos += 1
    resultado.update({"chi2": observado, "gl": (n_l - 1) * (n_c - 1), "extremos": extremos,
                      "p_valor": (extremos + 1) / (permutacoes + 1)})
    return resultado


# ----------------------------------------------------------------------------------------------------------------
# Concordância
# ----------------------------------------------------------------------------------------------------------------

def _pesos_kappa(k, pesos):
    if pesos not in ("quadraticos", "lineares", "nenhum"):
        raise ValueError(f"pesos deve ser 'quadraticos', 'lineares' ou 'nenhum', recebido {pesos!r}")
    matriz = []
    for i in range(k):
        linha = []
        for j in range(k):
            if pesos == "nenhum":
                linha.append(1.0 if i == j else 0.0)
            elif k == 1:
                linha.append(1.0)
            elif pesos == "lineares":
                linha.append(1.0 - abs(i - j) / (k - 1))
            else:
                linha.append(1.0 - ((i - j) / (k - 1)) ** 2)
        matriz.append(linha)
    return matriz


def kappa_ponderado(matriz, pesos="quadraticos", confianca=0.95):
    """Kappa de Cohen ponderado a partir de uma matriz de contingência quadrada (linhas: avaliador A; colunas: B).

    Com p_ij = n_ij/N, margens r_i (linhas) e c_j (colunas) e pesos de concordância w_ij em [0, 1] (w_ii = 1):
        po = soma w_ij p_ij;  pe = soma w_ij r_i c_j;  kappa = (po - pe) / (1 - pe).
    Pesos: "quadraticos" w = 1 - ((i-j)/(k-1))^2; "lineares" w = 1 - |i-j|/(k-1); "nenhum" w = identidade
    (kappa de Cohen simples). Para pesos ordinais as categorias devem estar na ordem natural.
    IC aproximado (grandes amostras), variância de Fleiss, Cohen e Everitt (1969), valendo também sem pesos:
        Var(kappa) = { soma p_ij [w_ij (1 - pe) - (wA_i + wB_j)(1 - po)]^2 - (po pe - 2 pe + po)^2 } / (N (1 - pe)^4)
        com wA_i = soma_j w_ij c_j e wB_j = soma_i w_ij r_i;  IC = kappa +- z * sqrt(Var), limitado a [-1, 1].
    É uma aproximação: com N pequeno ou kappa perto de 1 o IC é pouco confiável.
    Não definido (kappa None, demais campos derivados None) se N = 0, k = 1 ou pe = 1 (sem variação).
    Devolve dict: kappa, concordancia_observada, concordancia_esperada, erro_padrao, ic_inferior, ic_superior, n, pesos.
    """
    confianca = _confianca_valida(confianca)
    if not isinstance(matriz, (list, tuple)) or len(matriz) == 0:
        raise ValueError("a matriz deve ser uma lista não vazia de linhas")
    k = len(matriz)
    contagens = []
    for i, linha in enumerate(matriz):
        if not isinstance(linha, (list, tuple)) or len(linha) != k:
            raise ValueError("a matriz de concordância deve ser quadrada")
        valores = []
        for j, v in enumerate(linha):
            v = _numero_finito(v, f"matriz[{i}][{j}]")
            if v < 0:
                raise ValueError(f"matriz[{i}][{j}] não pode ser negativo")
            valores.append(v)
        contagens.append(valores)
    w = _pesos_kappa(k, pesos)
    total = sum(sum(l) for l in contagens)
    resultado = {"kappa": None, "concordancia_observada": None, "concordancia_esperada": None, "erro_padrao": None,
                 "ic_inferior": None, "ic_superior": None, "n": total, "pesos": pesos}
    if total == 0:
        return resultado
    p = [[v / total for v in l] for l in contagens]
    r = [sum(l) for l in p]
    c = [sum(p[i][j] for i in range(k)) for j in range(k)]
    po = sum(w[i][j] * p[i][j] for i in range(k) for j in range(k))
    pe = sum(w[i][j] * r[i] * c[j] for i in range(k) for j in range(k))
    resultado["concordancia_observada"] = po
    resultado["concordancia_esperada"] = pe
    if 1.0 - pe <= 1e-12:
        return resultado
    kappa = (po - pe) / (1.0 - pe)
    resultado["kappa"] = kappa
    w_a = [sum(w[i][j] * c[j] for j in range(k)) for i in range(k)]
    w_b = [sum(w[i][j] * r[i] for i in range(k)) for j in range(k)]
    soma = sum(p[i][j] * (w[i][j] * (1.0 - pe) - (w_a[i] + w_b[j]) * (1.0 - po)) ** 2
               for i in range(k) for j in range(k))
    variancia = max(0.0, (soma - (po * pe - 2.0 * pe + po) ** 2) / (total * (1.0 - pe) ** 4))
    erro = math.sqrt(variancia)
    z = _z_bilateral(confianca)
    resultado["erro_padrao"] = erro
    resultado["ic_inferior"] = max(-1.0, kappa - z * erro)
    resultado["ic_superior"] = min(1.0, kappa + z * erro)
    return resultado


def kappa_cohen(matriz, confianca=0.95):
    """Kappa de Cohen sem ponderação (caso particular de kappa_ponderado com pesos="nenhum")."""
    return kappa_ponderado(matriz, pesos="nenhum", confianca=confianca)


def faixa_kappa(kappa):
    """Faixa de leitura do kappa, em português, com a MESMA escala de `dominio.concordancia.interpretar_kappa`
    (fonte única; Landis e Koch, 1977): < 0 "pior que o acaso"; até 0,20 "fraca"; até 0,40 "razoável"; até 0,60
    "moderada"; até 0,80 "substancial"; acima disso "quase perfeita". None devolve None. Entrada não numérica levanta
    ValueError. As faixas são só uma leitura aproximada.
    """
    if kappa is None:
        return None
    return interpretar_kappa(_numero_finito(kappa, "kappa"))


# ----------------------------------------------------------------------------------------------------------------
# Calibração
# ----------------------------------------------------------------------------------------------------------------

def _desfecho_binario(valor, nome):
    if isinstance(valor, (bool, int, float)) and valor in (0, 1):
        return int(valor)
    raise ValueError(f"{nome} deve ser 0 ou 1, recebido {valor!r}")


def brier_score(probabilidades, desfechos):
    """Brier score: BS = (1/N) soma (p_i - y_i)^2, com p_i em [0, 1] e y_i em {0, 1}. Menor é melhor (0 = perfeito).

    As duas listas devem ter o mesmo tamanho. Lista vazia devolve None.
    """
    if len(probabilidades) != len(desfechos):
        raise ValueError("probabilidades e desfechos devem ter o mesmo tamanho")
    if len(probabilidades) == 0:
        return None
    soma = 0.0
    for p, y in zip(probabilidades, desfechos):
        p = _numero_finito(p, "probabilidade")
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"probabilidade fora de [0, 1]: {p}")
        soma += (p - _desfecho_binario(y, "desfecho")) ** 2
    return soma / len(probabilidades)


def brier_referencia(desfechos):
    """Brier da referência ingênua "sempre prever a taxa geral": p_barra (1 - p_barra), p_barra = média dos desfechos.

    Um Brier só diz algo lido ao lado deste valor: se não fica abaixo dele, o mapeamento de confiança em
    probabilidade não acrescenta nada a "chutar a taxa geral". Lista vazia devolve None.
    """
    if len(desfechos) == 0:
        return None
    taxa = sum(_desfecho_binario(y, "desfecho") for y in desfechos) / len(desfechos)
    return taxa * (1.0 - taxa)


def brier_por_cenario(rotulos, desfechos):
    """Brier em cada mapeamento de `CENARIOS_PROBABILIDADE` (análise de sensibilidade) mais a referência ingênua.

    `rotulos`: "alta", "media" ou "baixa" por item; `desfechos`: 1 se a revisão humana confirmou, senão 0. Devolve
    {cenario: brier, ..., "brier_referencia": brier de "sempre a taxa geral"}; sem itens, todos os valores são None.
    Os mapeamentos são suposições de pesquisa: se a conclusão muda de um cenário para outro, ela depende da suposição.
    Rótulo desconhecido ou tamanhos diferentes levantam ValueError.
    """
    if len(rotulos) != len(desfechos):
        raise ValueError("rotulos e desfechos devem ter o mesmo tamanho")
    for rotulo in rotulos:
        if rotulo not in PROBABILIDADE_POR_CONFIANCA:
            raise ValueError(f"nível de confiança desconhecido: {rotulo!r}")
    saida = {nome: brier_score([mapa[r] for r in rotulos], desfechos) for nome, mapa in CENARIOS_PROBABILIDADE.items()}
    saida["brier_referencia"] = brier_referencia(desfechos)
    return saida


def tabela_calibracao(rotulos, desfechos, confianca=0.95):
    """Tabela de confiabilidade por nível de confiança do classificador.

    `rotulos`: "alta", "media" ou "baixa" por item; `desfechos`: 1 se a revisão humana confirmou, senão 0. Para cada
    nível, em ordem crescente de probabilidade prevista (baixa, media, alta): n, acertos, taxa = acertos/n e IC de
    Wilson. Se o classificador é bem calibrado, `taxa` fica perto de `probabilidade_prevista`
    (PROBABILIDADE_POR_CONFIANCA). Níveis sem itens aparecem com n = 0 e taxa/IC None. Rótulo desconhecido levanta
    ValueError. Devolve lista de dicts: confianca, probabilidade_prevista, n, acertos, taxa, ic_inferior, ic_superior.
    """
    if len(rotulos) != len(desfechos):
        raise ValueError("rotulos e desfechos devem ter o mesmo tamanho")
    contagem = {nivel: [0, 0] for nivel in PROBABILIDADE_POR_CONFIANCA}
    for rotulo, y in zip(rotulos, desfechos):
        if rotulo not in contagem:
            raise ValueError(f"nível de confiança desconhecido: {rotulo!r}")
        contagem[rotulo][0] += 1
        contagem[rotulo][1] += _desfecho_binario(y, "desfecho")
    linhas = []
    for nivel in sorted(PROBABILIDADE_POR_CONFIANCA, key=PROBABILIDADE_POR_CONFIANCA.get):
        n, acertos = contagem[nivel]
        inferior, superior = intervalo_wilson(acertos, n, confianca)
        linhas.append({"confianca": nivel, "probabilidade_prevista": PROBABILIDADE_POR_CONFIANCA[nivel], "n": n,
                       "acertos": acertos, "taxa": (acertos / n) if n else None, "ic_inferior": inferior,
                       "ic_superior": superior})
    return linhas


# ----------------------------------------------------------------------------------------------------------------
# Não paramétricos
# ----------------------------------------------------------------------------------------------------------------

def _postos_medios(valores):
    """Postos 1..N com média nos empates. Devolve (postos, tamanhos_dos_grupos_empatados)."""
    ordem = sorted(range(len(valores)), key=lambda i: valores[i])
    postos = [0.0] * len(valores)
    grupos = []
    i = 0
    while i < len(ordem):
        j = i
        while j + 1 < len(ordem) and valores[ordem[j + 1]] == valores[ordem[i]]:
            j += 1
        medio = (i + j) / 2.0 + 1.0
        for pos in range(i, j + 1):
            postos[ordem[pos]] = medio
        grupos.append(j - i + 1)
        i = j + 1
    return postos, grupos


def _amostra_numerica(valores, nome):
    if isinstance(valores, (str, bytes)) or not hasattr(valores, "__len__"):
        raise ValueError(f"{nome} deve ser uma lista de números")
    return [_numero_finito(v, f"{nome}[{i}]") for i, v in enumerate(valores)]


def mann_whitney_u(a, b):
    """Teste U de Mann-Whitney bilateral por aproximação normal, com correção de empates e de continuidade.

    U_a = R_a - n_a (n_a + 1)/2, R_a = soma dos postos (médios nos empates) de `a` na amostra conjunta; U_b = n_a n_b - U_a.
    mu = n_a n_b / 2;  sigma^2 = n_a n_b / 12 * ((N + 1) - soma(t^3 - t) / (N (N - 1))), N = n_a + n_b, t = tamanho
    de cada grupo de empate;  z = (|U_a - mu| - 0,5) / sigma com o sinal de (U_a - mu) (0 se |U_a - mu| < 0,5).
    p_valor = P(|Z| >= |z|). Efeito rank-biserial = 2 U_a / (n_a n_b) - 1 em [-1, 1] (positivo: valores de `a`
    tendem a ser maiores que os de `b`). A aproximação normal é razoável com n_a, n_b >= 8 ou 10.
    Amostra vazia levanta ValueError. Se todos os valores são iguais (sigma = 0), z e p_valor são None.
    Devolve dict: u (U de a), u_b, z, p_valor, efeito_rank_biserial, n_a, n_b.
    """
    a = _amostra_numerica(a, "a")
    b = _amostra_numerica(b, "b")
    if not a or not b:
        raise ValueError("as duas amostras devem ter ao menos uma observação")
    na, nb = len(a), len(b)
    n = na + nb
    postos, grupos = _postos_medios(a + b)
    u_a = sum(postos[:na]) - na * (na + 1) / 2.0
    u_b = na * nb - u_a
    media = na * nb / 2.0
    ajuste = sum(t ** 3 - t for t in grupos) / (n * (n - 1)) if n > 1 else 0.0
    variancia = na * nb / 12.0 * ((n + 1) - ajuste)
    resultado = {"u": u_a, "u_b": u_b, "z": None, "p_valor": None,
                 "efeito_rank_biserial": 2.0 * u_a / (na * nb) - 1.0, "n_a": na, "n_b": nb}
    if variancia > 0:
        desvio = u_a - media
        corrigido = max(0.0, abs(desvio) - 0.5)
        z = math.copysign(corrigido, desvio) / math.sqrt(variancia)
        resultado["z"] = z
        resultado["p_valor"] = _normal_sf_bilateral(z)
    return resultado


def spearman(x, y):
    """Correlação de postos de Spearman: rho = Pearson dos postos médios; p bilateral pela aproximação t.

    t = rho sqrt((n - 2)/(1 - rho^2)) com n - 2 graus de liberdade (p_valor = 0 se |rho| = 1). x e y devem ter o
    mesmo tamanho. Com n < 3, ou se x ou y é constante (variância de postos zero), rho e p_valor são None.
    Devolve dict: rho, p_valor, n.
    """
    x = _amostra_numerica(x, "x")
    y = _amostra_numerica(y, "y")
    if len(x) != len(y):
        raise ValueError("x e y devem ter o mesmo tamanho")
    n = len(x)
    resultado = {"rho": None, "p_valor": None, "n": n}
    if n < 3:
        return resultado
    px, _ = _postos_medios(x)
    py, _ = _postos_medios(y)
    mx, my = sum(px) / n, sum(py) / n
    sxx = sum((v - mx) ** 2 for v in px)
    syy = sum((v - my) ** 2 for v in py)
    if sxx == 0 or syy == 0:
        return resultado
    rho = sum((u - mx) * (v - my) for u, v in zip(px, py)) / math.sqrt(sxx * syy)
    rho = max(-1.0, min(1.0, rho))
    resultado["rho"] = rho
    if abs(rho) >= 1.0:
        resultado["p_valor"] = 0.0
    else:
        resultado["p_valor"] = p_valor_t(rho * math.sqrt((n - 2) / (1.0 - rho * rho)), n - 2)
    return resultado


# ----------------------------------------------------------------------------------------------------------------
# Bootstrap e selo
# ----------------------------------------------------------------------------------------------------------------

def _quantil_interpolado(ordenados, q):
    """Quantil empírico por interpolação linear (tipo 7) sobre valores já ordenados."""
    posicao = q * (len(ordenados) - 1)
    baixo = int(math.floor(posicao))
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (posicao - baixo) * (ordenados[alto] - ordenados[baixo])


def bootstrap_ic(funcao, amostras, repeticoes=10_000, semente=0, confianca=0.95):
    """IC por percentis do bootstrap não paramétrico (reamostragem com reposição), determinístico para a `semente`.

    `amostras`: sequência de GRUPOS, cada grupo uma lista de observações (qualquer objeto). Em cada repetição cada
    grupo é reamostrado com reposição, mantendo seu tamanho, e `funcao(*reamostras)` calcula a estatística (um grupo:
    amostras=[dados], funcao(dados); dois grupos, como o ICER: amostras=[g1, g2], funcao(g1, g2)). Repetições em que
    funcao devolve None, não finito, ou levanta ZeroDivisionError são descartadas e contadas à parte.
    IC = quantis (1 - confianca)/2 e 1 - (1 - confianca)/2 das estatísticas válidas (interpolação linear).
    Grupo vazio levanta ValueError. Sem nenhuma repetição válida, ic_inferior e ic_superior são None.
    O padrão é 10.000 repetições (antes 2.000): o custo extra é desprezível para os tamanhos de amostra do projeto e o
    intervalo por percentis fica mais estável (menos variação entre sementes nos quantis das caudas).
    Devolve dict: estimativa (funcao nos dados originais, ou None), ic_inferior, ic_superior, repeticoes,
    repeticoes_validas, semente.
    """
    repeticoes = _inteiro_positivo(repeticoes, "repeticoes")
    semente = _semente_valida(semente)
    confianca = _confianca_valida(confianca)
    if not callable(funcao):
        raise ValueError("funcao deve ser chamável")
    grupos = [list(g) for g in amostras]
    if not grupos or any(len(g) == 0 for g in grupos):
        raise ValueError("cada grupo de amostras deve ter ao menos uma observação")

    def avaliar(*dados):
        try:
            valor = funcao(*dados)
        except ZeroDivisionError:
            return None
        if valor is None or isinstance(valor, bool):
            return None
        valor = float(valor)
        return valor if math.isfinite(valor) else None

    gerador = random.Random(semente)
    estatisticas = []
    for _ in range(repeticoes):
        reamostras = [[g[gerador.randrange(len(g))] for _ in range(len(g))] for g in grupos]
        valor = avaliar(*reamostras)
        if valor is not None:
            estatisticas.append(valor)
    estatisticas.sort()
    resultado = {"estimativa": avaliar(*grupos), "ic_inferior": None, "ic_superior": None, "repeticoes": repeticoes,
                 "repeticoes_validas": len(estatisticas), "semente": semente}
    if estatisticas:
        cauda = (1.0 - confianca) / 2.0
        resultado["ic_inferior"] = _quantil_interpolado(estatisticas, cauda)
        resultado["ic_superior"] = _quantil_interpolado(estatisticas, 1.0 - cauda)
    return resultado


def selo_de_evidencia(p_valor):
    """Classifica um p-valor: "forte" (p < 0,01), "moderada" (0,01 <= p < 0,05), "insuficiente" (p >= 0,05).

    None devolve None. Não tem texto de exibição: o painel decide os rótulos. p fora de [0, 1] levanta ValueError.
    """
    if p_valor is None:
        return None
    p_valor = _numero_finito(p_valor, "p_valor")
    if not (0.0 <= p_valor <= 1.0):
        raise ValueError(f"p_valor deve estar entre 0 e 1, recebido {p_valor}")
    if p_valor < 0.01:
        return "forte"
    if p_valor < 0.05:
        return "moderada"
    return "insuficiente"
