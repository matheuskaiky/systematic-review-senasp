"""Validação cruzada de `dominio/estatistica.py` contra scipy, statsmodels e scikit-learn.

Para cada função estatística do domínio, sorteia muitas entradas aleatórias (semente fixa), calcula a resposta com a
biblioteca de referência e registra a MAIOR diferença absoluta (e relativa) observada. Cada linha da tabela tem uma
tolerância; passa se a diferença máxima fica abaixo dela. É um portão de qualidade: se uma função discorda além da
tolerância, o script termina com código 1 e a tabela mostra qual. Nada é corrigido aqui, só relatado.

Não abre o banco. `--selftest` roda poucas entradas e prova que o comparador acusa uma discordância plantada."""
import math
import sys
import warnings
from datetime import date

import numpy as np

import _comum

sys.path.insert(0, str(_comum.RAIZ))
from dominio import estatistica as E  # noqa: E402  (a função sob teste; este script só lê)

TOL_P = 1e-8            # p-valores e quantis determinísticos (o domínio declara ~1e-10)
TOL_EST = 1e-9          # estatísticas e intervalos fechados
TOL_CAUDA = math.inf    # caudas extremas (p < 1e-6): linha só informativa (registra a ordem de grandeza do erro), sem critério
TOL_REL = 5e-8          # diferença relativa em caudas
TOL_KAPPA_EP = 1e-6


class Comparador:
    """Acumula, por (função, quantidade), n de comparações e as maiores diferenças."""

    def __init__(self):
        self.linhas = {}

    def registrar(self, funcao, quantidade, obtido, referencia, tolerancia, relativa=False):
        if obtido is None or referencia is None or (isinstance(referencia, float) and math.isnan(referencia)):
            chave = (funcao, quantidade)
            self.linhas.setdefault(chave, {"n": 0, "abs": 0.0, "rel": 0.0, "tol": tolerancia, "descartes": 0})["descartes"] += 1
            return
        d = abs(float(obtido) - float(referencia))
        r = d / max(abs(float(referencia)), 1e-12) if float(referencia) != 0.0 else 0.0
        linha = self.linhas.setdefault((funcao, quantidade), {"n": 0, "abs": 0.0, "rel": 0.0, "tol": tolerancia, "descartes": 0})
        linha["n"] += 1
        linha["abs"] = max(linha["abs"], d)
        linha["rel"] = max(linha["rel"], r)
        linha["tol"] = tolerancia
        linha["relativa"] = relativa

    def tabela(self):
        saida = []
        for (f, q), l in self.linhas.items():
            valor = l["rel"] if l.get("relativa") else l["abs"]
            saida.append({"funcao": f, "quantidade": q, "n_comparacoes": l["n"], "max_dif_abs": l["abs"],
                          "max_dif_rel": l["rel"], "tolerancia": l["tol"],
                          "criterio": "relativa" if l.get("relativa") else "absoluta",
                          "descartes": l["descartes"], "ok": None if math.isinf(l["tol"]) else (l["n"] > 0 and valor <= l["tol"])})
        return saida


def _tabela_aleatoria(rng, linhas, colunas, maximo, zeros=False):
    t = rng.integers(0, maximo, size=(linhas, colunas))
    if not zeros:
        t = t + 1
    return t


def validar(cmp, n):
    """Roda todas as comparações com `n` entradas aleatórias por função (n menor nos testes pesados)."""
    from scipy import stats
    from statsmodels.stats import proportion as sp
    from statsmodels.stats.inter_rater import cohens_kappa
    from statsmodels.stats.contingency_tables import Table2x2, mcnemar
    from sklearn.metrics import brier_score_loss, cohen_kappa_score
    rng = np.random.default_rng(_comum.SEMENTE)
    warnings.simplefilter("ignore")

    # quantil normal: faixa de uso real (níveis de confiança) e caudas extremas, separadas de propósito. A bisseção parte de
    # 1 - p, e perto de 1 a subtração perde dígitos: abaixo de p ~ 1e-6 o erro passa de 1e-8 (o docstring promete 1e-14).
    for p in np.concatenate([rng.uniform(1e-6, 1 - 1e-6, n), [0.025, 0.5, 0.975, 0.995, 1e-6, 1 - 1e-6]]):
        cmp.registrar("quantil_normal", "z (p entre 1e-6 e 1-1e-6: uso real)", E.quantil_normal(float(p)), stats.norm.ppf(p), TOL_P)
    for p in np.concatenate([10 ** rng.uniform(-14, -6, max(20, n // 10)), [1e-10, 1e-12]]):
        for q in (float(p), 1.0 - float(p)):
            cmp.registrar("quantil_normal", "z (caudas extremas, p < 1e-6: limitação conhecida)", E.quantil_normal(q), stats.norm.ppf(q), TOL_CAUDA)
    for _ in range(n):
        x, gl = float(rng.uniform(0, 200)), int(rng.integers(1, 60))
        cmp.registrar("p_valor_qui_quadrado", "p", E.p_valor_qui_quadrado(x, gl), stats.chi2.sf(x, gl), TOL_P)
        cmp.registrar("p_valor_qui_quadrado", "p (relativa)", E.p_valor_qui_quadrado(x, gl), stats.chi2.sf(x, gl), TOL_REL, True) if stats.chi2.sf(x, gl) > 1e-100 else None
        t, g = float(rng.uniform(-25, 25)), int(rng.integers(1, 500))
        cmp.registrar("p_valor_t", "p", E.p_valor_t(t, g), 2 * stats.t.sf(abs(t), g), TOL_P)

    # Wilson
    for _ in range(n):
        tam = int(rng.integers(1, 5000))
        k = int(rng.integers(0, tam + 1))
        conf = float(rng.uniform(0.5, 0.999))
        ref = sp.proportion_confint(k, tam, alpha=1 - conf, method="wilson")
        inf, sup = E.intervalo_wilson(k, tam, conf)
        cmp.registrar("intervalo_wilson", "limite inferior", inf, ref[0], TOL_EST)
        cmp.registrar("intervalo_wilson", "limite superior", sup, ref[1], TOL_EST)

    # teste z de duas proporções (variância agrupada) e IC de Wald da diferença
    for _ in range(n):
        n1, n2 = int(rng.integers(5, 3000)), int(rng.integers(5, 3000))
        k1, k2 = int(rng.integers(1, n1)), int(rng.integers(1, n2))
        conf = float(rng.uniform(0.8, 0.99))
        r = E.teste_z_proporcoes(k1, n1, k2, n2, conf)
        z, p = sp.proportions_ztest([k1, k2], [n1, n2], value=0, alternative="two-sided", prop_var=False)
        cmp.registrar("teste_z_proporcoes", "z", r["z"], z, TOL_EST)
        cmp.registrar("teste_z_proporcoes", "p_valor", r["p_valor"], p, TOL_P)
        lo, hi = sp.confint_proportions_2indep(k1, n1, k2, n2, method="wald", compare="diff", alpha=1 - conf)
        cmp.registrar("teste_z_proporcoes", "IC da diferença (inferior)", r["ic_inferior"], lo, TOL_EST)
        cmp.registrar("teste_z_proporcoes", "IC da diferença (superior)", r["ic_superior"], hi, TOL_EST)

    # binomial exato e limite superior de Clopper-Pearson
    for _ in range(n):
        tam = int(rng.integers(1, 1500))
        k = int(rng.integers(0, max(2, tam // 5)))
        k = min(k, tam)
        p0 = float(rng.uniform(0.005, 0.6))
        for direcao, alt in (("menor", "less"), ("maior", "greater")):
            r = E.teste_binomial_exato_unilateral(k, tam, p0, direcao)
            cmp.registrar("teste_binomial_exato_unilateral", f"p_valor ({direcao})", r["p_valor"],
                          stats.binomtest(k, tam, p0, alternative=alt).pvalue, TOL_P)
        conf = float(rng.uniform(0.8, 0.995))
        ref = 1.0 if k == tam else float(stats.beta.ppf(conf, k + 1, tam - k))
        cmp.registrar("limite_superior_binomial_exato", "limite", E.limite_superior_binomial_exato(k, tam, conf), ref, TOL_P)
    for tam in (30, 59, 93, 149, 150, 236, 313, 435, 1000):      # tamanhos do projeto, com 0 a 3 eventos
        for k in range(4):
            cmp.registrar("limite_superior_binomial_exato", "limite (tamanhos do projeto)",
                          E.limite_superior_binomial_exato(k, tam, 0.95), float(stats.beta.ppf(0.95, k + 1, tam - k)), TOL_P)

    # McNemar: exato até 25 discordâncias, qui-quadrado com continuidade acima
    for _ in range(n):
        a, b = int(rng.integers(0, 60)), int(rng.integers(0, 60))
        if a + b == 0:
            continue
        r = E.teste_mcnemar(a, b)
        tabela = [[10, a], [b, 10]]
        ref = mcnemar(tabela, exact=(a + b <= 25), correction=True)
        cmp.registrar("teste_mcnemar", f"p_valor ({r['metodo']})", r["p_valor"], ref.pvalue, TOL_P)
        cmp.registrar("teste_mcnemar", f"estatística ({r['metodo']})", r["statistic"], ref.statistic, TOL_EST)

    # razão de chances: Wald no log (Woolf); casela zero com Haldane-Anscombe (+0,5 nas quatro caselas)
    for _ in range(n):
        t = rng.integers(0, 80, size=4)
        if min(t[0] + t[1], t[2] + t[3], t[0] + t[2], t[1] + t[3]) == 0:
            continue
        conf = float(rng.uniform(0.8, 0.99))
        r = E.odds_ratio_com_ic(*[int(v) for v in t], confianca=conf)
        base = np.array(t, dtype=float).reshape(2, 2) + (0.5 if (t == 0).any() else 0.0)
        ref = Table2x2(base)
        lo, hi = ref.oddsratio_confint(alpha=1 - conf, method="normal")
        cmp.registrar("odds_ratio_com_ic", "razão de chances", r["odds_ratio"], ref.oddsratio, TOL_EST, True)
        cmp.registrar("odds_ratio_com_ic", "IC inferior", r["ic_inferior"], lo, TOL_EST, True)
        cmp.registrar("odds_ratio_com_ic", "IC superior", r["ic_superior"], hi, TOL_EST, True)
        cmp.registrar("odds_ratio_com_ic", "erro-padrão de ln(OR)", r["erro_padrao"], ref.log_oddsratio_se, TOL_EST)

    # qui-quadrado de independência (scipy) e resíduos padronizados ajustados (fórmula independente em numpy)
    for _ in range(n):
        li, co = int(rng.integers(2, 6)), int(rng.integers(2, 7))
        t = _tabela_aleatoria(rng, li, co, int(rng.choice([4, 30, 300])), zeros=bool(rng.integers(0, 2)))
        if (t.sum(axis=0) == 0).any() or (t.sum(axis=1) == 0).any():
            continue
        r = E.teste_qui_quadrado(t.tolist())
        chi2, p, gl, esp = stats.chi2_contingency(t, correction=False)
        cmp.registrar("teste_qui_quadrado", "chi2", r["chi2"], chi2, TOL_EST, True)
        cmp.registrar("teste_qui_quadrado", "p_valor", r["p_valor"], p, TOL_P)
        cmp.registrar("teste_qui_quadrado", "gl", r["gl"], gl, 0)
        cmp.registrar("teste_qui_quadrado", "esperados (máx.)", np.abs(np.array(r["esperados"]) - esp).max(), 0.0, TOL_EST)
        total = t.sum()
        ref_res = (t - esp) / np.sqrt(esp * (1 - t.sum(1, keepdims=True) / total) * (1 - t.sum(0, keepdims=True) / total))
        cmp.registrar("teste_qui_quadrado", "resíduos ajustados (máx.)",
                      np.abs(np.array(r["residuos_padronizados_ajustados"]) - ref_res).max(), 0.0, TOL_EST)
    for _ in range(n):                                            # 2x2 com correção de Yates
        t = _tabela_aleatoria(rng, 2, 2, 60)
        r = E.teste_qui_quadrado(t.tolist(), correcao_yates=True)
        chi2, p, _, _ = stats.chi2_contingency(t, correction=True)
        cmp.registrar("teste_qui_quadrado (Yates 2x2)", "chi2", r["chi2"], chi2, TOL_EST, True)
        cmp.registrar("teste_qui_quadrado (Yates 2x2)", "p_valor", r["p_valor"], p, TOL_P)

    # Monte Carlo: a estatística é exata; o p-valor é comparado com uma simulação independente (numpy), em erros-padrão
    for i in range(max(8, n // 25)):
        t = _tabela_aleatoria(rng, int(rng.integers(2, 4)), int(rng.integers(2, 5)), 8)
        B = 4000
        r = E.teste_qui_quadrado_monte_carlo(t.tolist(), permutacoes=B, semente=i)
        cmp.registrar("teste_qui_quadrado_monte_carlo", "chi2", r["chi2"], stats.chi2_contingency(t, correction=False)[0], TOL_EST, True)
        rotulos_l = np.repeat(np.arange(t.shape[0]), t.sum(axis=1))
        colunas = np.concatenate([np.full(int(c), j) for l in range(t.shape[0]) for j, c in enumerate(t[l])])
        linhas_ = np.concatenate([np.full(int(c), l) for l in range(t.shape[0]) for j, c in enumerate(t[l])])
        g = np.random.default_rng(1000 + i)
        esp = np.outer(t.sum(1), t.sum(0)) / t.sum()
        obs = ((t - esp) ** 2 / esp).sum()
        extremos = 0
        for _ in range(B):
            c = g.permutation(colunas)
            m = np.zeros_like(t)
            np.add.at(m, (linhas_, c), 1)
            extremos += ((m - esp) ** 2 / esp).sum() >= obs - 1e-9 * max(1, obs)
        ref = (extremos + 1) / (B + 1)
        ep = math.sqrt(2 * max(ref * (1 - ref), 1e-4) / B)
        cmp.registrar("teste_qui_quadrado_monte_carlo", "p_valor (dif./erro-padrão combinado)",
                      abs(r["p_valor"] - ref) / ep, 0.0, 4.5)

    # kappa de Cohen ponderado (scikit-learn) e erro-padrão (statsmodels, quando as fórmulas coincidem)
    for _ in range(n):
        k = int(rng.integers(2, 6))
        m = _tabela_aleatoria(rng, k, k, 40, zeros=True) + np.eye(k, dtype=int) * int(rng.integers(0, 30))
        if m.sum() == 0:
            continue
        a = np.repeat(np.arange(k), m.sum(axis=1))
        b = np.concatenate([np.repeat(np.arange(k), m[i]) for i in range(k)])
        for pesos, w_sk, w_sm in (("quadraticos", "quadratic", "quadratic"), ("lineares", "linear", "linear"), ("nenhum", None, None)):
            r = E.kappa_ponderado(m.tolist(), pesos=pesos)
            if r["kappa"] is None:
                continue
            cmp.registrar("kappa_ponderado", f"kappa ({pesos})", r["kappa"], cohen_kappa_score(a, b, weights=w_sk), TOL_EST)
            sm = cohens_kappa(m, wt=w_sm)
            cmp.registrar("kappa_ponderado", f"erro-padrão ({pesos})", r["erro_padrao"], sm.std_kappa, TOL_KAPPA_EP)
        cmp.registrar("kappa_cohen", "kappa", E.kappa_cohen(m.tolist())["kappa"] if E.kappa_cohen(m.tolist())["kappa"] is not None else None,
                      cohen_kappa_score(a, b), TOL_EST)

    # Brier
    for _ in range(max(10, n // 10)):
        tam = int(rng.integers(5, 400))
        y = rng.integers(0, 2, tam)
        p = rng.uniform(0, 1, tam)
        cmp.registrar("brier_score", "Brier", E.brier_score(p.tolist(), y.tolist()), brier_score_loss(y, p), TOL_EST)

    # Mann-Whitney (aproximação normal, empates e continuidade) e Spearman
    for _ in range(n):
        na, nb = int(rng.integers(3, 80)), int(rng.integers(3, 80))
        escala = int(rng.choice([3, 10, 1000]))
        a, b = rng.integers(0, escala, na) + rng.integers(0, 2), rng.integers(0, escala, nb)
        if len(set(a.tolist()) | set(b.tolist())) < 2:
            continue
        r = E.mann_whitney_u([float(v) for v in a], [float(v) for v in b])
        ref = stats.mannwhitneyu(a, b, alternative="two-sided", use_continuity=True, method="asymptotic")
        cmp.registrar("mann_whitney_u", "U", r["u"], ref.statistic, TOL_EST)
        cmp.registrar("mann_whitney_u", "p_valor", r["p_valor"], ref.pvalue, TOL_P)
        cmp.registrar("mann_whitney_u", "rank-biserial", r["efeito_rank_biserial"], 2 * ref.statistic / (na * nb) - 1, TOL_EST)
    for _ in range(n):
        tam = int(rng.integers(5, 200))
        x = rng.integers(0, int(rng.choice([4, 20, 500])), tam).astype(float)
        y = x * float(rng.uniform(-1, 1)) + rng.normal(0, float(rng.uniform(0.5, 8)), tam)
        r = E.spearman(x.tolist(), y.tolist())
        if r["rho"] is None or abs(r["rho"]) >= 1:
            continue
        ref = stats.spearmanr(x, y)
        cmp.registrar("spearman", "rho", r["rho"], ref.statistic, TOL_EST)
        cmp.registrar("spearman", "p_valor", r["p_valor"], ref.pvalue, TOL_P)

    # bootstrap por percentis: estimativa exata; limites comparados com scipy.stats.bootstrap (erro de Monte Carlo)
    for i in range(max(6, n // 30)):
        x = rng.lognormal(0, 1, int(rng.integers(15, 120)))
        r = E.bootstrap_ic(lambda v: sum(v) / len(v), [x.tolist()], repeticoes=4000, semente=i)
        cmp.registrar("bootstrap_ic", "estimativa", r["estimativa"], float(x.mean()), TOL_EST)
        ref = stats.bootstrap((x,), np.mean, n_resamples=4000, confidence_level=0.95, method="percentile",
                              random_state=np.random.default_rng(i))
        ep = float(ref.standard_error)
        cmp.registrar("bootstrap_ic", "limites (dif./erro-padrão do bootstrap)",
                      max(abs(r["ic_inferior"] - ref.confidence_interval.low), abs(r["ic_superior"] - ref.confidence_interval.high)) / ep, 0.0, 0.25)


def imprimir(linhas):
    cab = f"{'função':36} {'quantidade':56} {'n':>6} {'max |dif|':>11} {'max dif.rel':>11} {'tolerância':>10} {'critério':>9}  ok"
    saida = [cab, "-" * len(cab)]
    for l in linhas:
        saida.append(f"{l['funcao']:36} {l['quantidade']:56} {l['n_comparacoes']:>6} {l['max_dif_abs']:>11.2e} "
                     f"{l['max_dif_rel']:>11.2e} {l['tolerancia']:>10.0e} {l['criterio']:>9}  {'info' if l['ok'] is None else ('sim' if l['ok'] else 'NÃO')}")
    return saida


def selftest():
    """Prova que o comparador detecta uma discordância (função errada plantada) e aceita uma concordância."""
    from scipy import stats
    cmp = Comparador()
    for p in (0.1, 0.5, 0.9):
        cmp.registrar("plantada_certa", "z", E.quantil_normal(p), stats.norm.ppf(p), TOL_P)
        cmp.registrar("plantada_errada", "z", E.quantil_normal(p) + 1e-4, stats.norm.ppf(p), TOL_P)
    ok = {l["funcao"]: l["ok"] for l in cmp.tabela()}
    assert ok == {"plantada_certa": True, "plantada_errada": False}, ok
    cmp2 = Comparador()
    validar(cmp2, 12)
    assert cmp2.tabela() and all(l["n_comparacoes"] > 0 for l in cmp2.tabela()), "alguma comparação não rodou"
    print("selftest ok: o comparador acusa discordância plantada e todas as comparações rodam em modo reduzido")


def main():
    args = _comum.ler_argumentos(__doc__.split("\n")[0], lambda p: p.add_argument("--n", type=int, default=400, help="entradas aleatórias por função"))
    if args.selftest:
        selftest()
        return 0
    cmp = Comparador()
    validar(cmp, args.n)
    linhas = cmp.tabela()
    saida = _comum.preparar_saida(args.saida)
    import pandas as pd
    _comum.escrever_csv(saida, "validar_estatistica.csv", pd.DataFrame(linhas))
    texto = [f"Validação cruzada de dominio/estatistica.py em {date.today().isoformat()} (n = {args.n} entradas por função, semente {_comum.SEMENTE})", ""] + imprimir(linhas)
    falhas = [l for l in linhas if l["ok"] is False]
    texto += ["", "DISCORDÂNCIAS: " + (", ".join(f"{l['funcao']} / {l['quantidade']}" for l in falhas) if falhas else "nenhuma além da tolerância")]
    for l in linhas:
        if l["ok"] is None:
            texto.append(f"INFORMATIVO: {l['funcao']} / {l['quantidade']}: maior diferença absoluta {l['max_dif_abs']:.1e} (sem critério de aprovação)")
    _comum.escrever_texto(saida, "validar_estatistica.txt", texto)
    print("\n".join(texto))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
