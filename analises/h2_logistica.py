"""H2: a integridade da evidência prediz a confirmação humana? Regressão logística binária multivariada.

Desfecho Y = 1 se o achado verificado NÃO foi descartado (`status_final <> 'descartado'`), 0 se foi descartado.
Preditores (todos binários): evidencia_confere, evidencia_cita_tecnologia, fonte_oficial_efetiva, origem_pagina
(origem_texto = 'pagina'). Saída: razão de chances ajustada com IC 95% (Wald) e, como sensibilidade, IC com erro-padrão
robusto por UF (achados da mesma UF não são independentes); AUC (no mesmo conjunto e por validação cruzada de 5 partes);
curva ROC do modelo completo contra a ordenação simples por `confianca`; gráfico de floresta.

RECUSA RODAR com dados insuficientes (ESTATISTICA_EXPLICADA, seção 13): menos de 200 achados verificados ou menos de 40 na
classe menos frequente. Hoje não há achados verificados por pessoa, então o script só recusa; `--selftest` prova o ajuste em
dados sintéticos de efeito conhecido. Exploratório, salvo se o plano declarar H2 como confirmatória."""
import sys

import numpy as np

import _comum

MIN_VERIFICADOS = 200
MIN_CLASSE_RARA = 40
PREDITORES = ["evidencia_confere", "evidencia_cita_tecnologia", "fonte_oficial_efetiva", "origem_pagina"]
ROTULOS = {"evidencia_confere": "evidência confere no texto", "evidencia_cita_tecnologia": "evidência cita a tecnologia",
           "fonte_oficial_efetiva": "fonte oficial (.gov.br)", "origem_pagina": "texto da página (e não só resumo)"}


def preparar(df):
    """Mantém os verificados e monta y e os preditores 0/1. Devolve (dados completos, n_verificados, n_sem_preditor)."""
    v = df[df["verificado"].fillna(0).astype(int) == 1].copy()
    v["y"] = (v["status_final"].fillna("") != "descartado").astype(int)
    v["origem_pagina"] = (v["origem_texto"] == "pagina").astype(int)
    completos = v.dropna(subset=["evidencia_confere", "evidencia_cita_tecnologia", "fonte_oficial_efetiva"]).copy()
    return completos, len(v), len(v) - len(completos)


def recusa(n_verificados, y):
    """Mensagem em português se os dados não bastam; None se bastam."""
    classe_rara = int(min((y == 1).sum(), (y == 0).sum())) if len(y) else 0
    if n_verificados < MIN_VERIFICADOS or classe_rara < MIN_CLASSE_RARA:
        return (f"a regressão logística (H2) só roda com pelo menos {MIN_VERIFICADOS} achados verificados e pelo menos "
                f"{MIN_CLASSE_RARA} na classe menos frequente (ESTATISTICA_EXPLICADA, seção 13). Hoje: {n_verificados} verificados, "
                f"{classe_rara} na classe menos frequente. Antes disso, reporte razões de chances 2x2 com intervalo e diga "
                "'amostra insuficiente para ajuste conjunto'.")
    return None


def ajustar(d):
    """Ajusta a logística e devolve (resultado, texto). Preditores sem variação são retirados e avisados."""
    import statsmodels.api as sm
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, roc_curve
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    texto, usados = [], []
    for p in PREDITORES:
        if d[p].nunique() < 2:
            texto.append(f"preditor '{p}' retirado: não varia nos dados (separação completa; a razão de chances não é estimável).")
        else:
            usados.append(p)
    if not usados:
        return None, texto + ["nenhum preditor com variação."]
    X = sm.add_constant(d[usados].astype(float))
    y = d["y"].to_numpy()
    modelo = sm.Logit(y, X).fit(disp=0, maxiter=200)
    robusto = sm.Logit(y, X).fit(disp=0, maxiter=200, cov_type="cluster", cov_kwds={"groups": d["uf"].astype("category").cat.codes}) if "uf" in d and d["uf"].nunique() > 1 else None
    ic, ic_r = modelo.conf_int(), (robusto.conf_int() if robusto is not None else None)
    linhas = []
    texto.append(f"n = {len(d)} achados verificados; confirmados (Y = 1): {int(y.sum())}; descartados: {int((y == 0).sum())}")
    texto.append(f"{'preditor':36} {'RC':>7} {'IC 95% (Wald)':>18} {'IC 95% (cluster UF)':>20} {'p':>8}")
    for p in usados:
        lin = {"preditor": p, "rc": float(np.exp(modelo.params[p])), "inf": float(np.exp(ic.loc[p, 0])), "sup": float(np.exp(ic.loc[p, 1])),
               "p": float(modelo.pvalues[p]), "z_wald": float(modelo.tvalues[p])}
        if ic_r is not None:
            lin.update({"inf_cluster": float(np.exp(ic_r.loc[p, 0])), "sup_cluster": float(np.exp(ic_r.loc[p, 1]))})
        linhas.append(lin)
        extra = f"{lin['inf_cluster']:.2f} a {lin['sup_cluster']:.2f}" if "inf_cluster" in lin else "-"
        texto.append(f"{ROTULOS[p]:36} {lin['rc']:>7.2f} {lin['inf']:>8.2f} a {lin['sup']:<7.2f} {extra:>20} {lin['p']:>8.3g}")
    prob = modelo.predict(X)
    auc = float(roc_auc_score(y, prob))
    cv = StratifiedKFold(5, shuffle=True, random_state=_comum.SEMENTE)
    prob_cv = cross_val_predict(LogisticRegression(C=1e6, max_iter=1000), d[usados].astype(float), y, cv=cv, method="predict_proba")[:, 1]
    auc_cv = float(roc_auc_score(y, prob_cv))
    ordem = {"alta": 3, "media": 2, "baixa": 1}
    simples = d["confianca"].map(ordem).fillna(0).to_numpy(float) if "confianca" in d else None
    auc_simples = float(roc_auc_score(y, simples)) if simples is not None and len(set(simples)) > 1 else None
    texto.append(f"AUC do modelo completo: {auc:.3f} no mesmo conjunto (otimista) e {auc_cv:.3f} por validação cruzada de 5 partes"
                 + (f"; ordenação simples por confiança: {auc_simples:.3f}" if auc_simples is not None else ""))
    texto += ["", "Leitura: razão de chances é razão de CHANCES, não de probabilidades. Achados da mesma UF não são independentes (veja o IC por UF).",
              "Preditores correlacionados (fonte oficial e origem do texto) dificultam ler cada coeficiente sozinho."]
    res = {"linhas": linhas, "auc": auc, "auc_cv": auc_cv, "auc_simples": auc_simples, "y": y, "prob_cv": prob_cv, "simples": simples,
           "roc_modelo": roc_curve(y, prob_cv), "roc_simples": roc_curve(y, simples) if auc_simples is not None else None}
    return res, texto


def desenhar(res, pasta):
    import matplotlib.pyplot as plt
    _comum.novo_grafico()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.2), gridspec_kw={"width_ratios": [1.5, 1]})
    linhas = res["linhas"][::-1]
    for i, l in enumerate(linhas):
        a1.plot([l["inf"], l["sup"]], [i, i], color=_comum.AZUL, lw=2)
        a1.plot(l["rc"], i, "o", color=_comum.AZUL, ms=7)
    a1.axvline(1, color=_comum.CINZA, ls="--", lw=1)
    a1.set_yticks(range(len(linhas)))
    a1.set_yticklabels([ROTULOS[l["preditor"]] for l in linhas])
    a1.set_xscale("log")
    a1.set_xlabel("razão de chances ajustada (IC 95%, escala log)")
    a1.set_title("H2: floresta das razões de chances", loc="left", fontsize=11)
    fpr, tpr, _ = res["roc_modelo"]
    a2.plot(fpr, tpr, color=_comum.AZUL, lw=2, label=f"modelo completo (AUC {res['auc_cv']:.2f}, validação cruzada)")
    if res["roc_simples"] is not None:
        a2.plot(res["roc_simples"][0], res["roc_simples"][1], color=_comum.LARANJA, lw=2, label=f"só a confiança (AUC {res['auc_simples']:.2f})")
    a2.plot([0, 1], [0, 1], color=_comum.CINZA, ls="--", lw=1)
    a2.set_xlabel("falsos positivos"); a2.set_ylabel("verdadeiros positivos")
    a2.set_title("Curva ROC", loc="left", fontsize=11)
    a2.legend(frameon=False, fontsize=8, loc="lower right")
    return _comum.salvar_figura(fig, pasta, "h2_logistica")


def sintetico(n=600, efeitos=(1.6, 0.9, 0.5, 0.4), intercepto=-0.2, semente=_comum.SEMENTE):
    import pandas as pd
    rng = np.random.default_rng(semente)
    X = (rng.random((n, 4)) < [0.8, 0.7, 0.6, 0.5]).astype(int)
    eta = intercepto + X @ np.array(efeitos)
    y = (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(int)
    return pd.DataFrame({"verificado": 1, "status_final": np.where(y == 1, "em_uso", "descartado"), "evidencia_confere": X[:, 0],
                         "evidencia_cita_tecnologia": X[:, 1], "fonte_oficial_efetiva": X[:, 2],
                         "origem_texto": np.where(X[:, 3] == 1, "pagina", "snippet"), "uf": rng.choice(list("ABCDEFGHIJ"), n),
                         "confianca": np.where(X[:, 0] == 1, rng.choice(["alta", "media"], n, p=[.8, .2]), rng.choice(["media", "baixa"], n))})


def main():
    args = _comum.ler_argumentos(__doc__.split("\n")[0])
    if args.selftest:
        d, nv, _ = preparar(sintetico())
        assert recusa(nv, d["y"].to_numpy()) is None
        res, texto = ajustar(d)
        for l, verdadeiro in zip(res["linhas"], (1.6, 0.9, 0.5, 0.4)):
            assert l["inf"] < np.exp(verdadeiro) < l["sup"], (l["preditor"], l)
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:        # a figura também é exercitada, sem sujar outputs/
            desenhar(res, pasta)
        pequeno, nvp, _ = preparar(sintetico(n=120))
        assert recusa(nvp, pequeno["y"].to_numpy()) and "amostra insuficiente" in recusa(nvp, pequeno["y"].to_numpy())
        print("selftest ok: os quatro efeitos conhecidos ficam dentro dos IC 95% e a recusa por amostra pequena funciona")
        return 0
    import conexao
    con = conexao.abrir(args.banco)
    df = conexao.tabela(con, """SELECT a.achado_id, a.uf, a.verificado, a.status_final, a.evidencia_confere, a.evidencia_cita_tecnologia,
                                       a.confianca, f.fonte_oficial_efetiva, k.origem_texto
                                FROM r_achados a JOIN r_classificacoes k ON k.classificacao_id = a.classificacao_id
                                LEFT JOIN v_fonte_da_classificacao f ON f.classificacao_id = a.classificacao_id""")
    d, n_verificados, sem_preditor = preparar(df)
    motivo = recusa(len(d), d["y"].to_numpy())
    if motivo:
        extra = f" ({sem_preditor} verificados ficaram de fora por falta de algum preditor.)" if sem_preditor else ""
        _comum.dados_insuficientes(motivo + extra)
    res, texto = ajustar(d)
    if res is None:
        _comum.dados_insuficientes(" ".join(texto))
    saida = _comum.preparar_saida(args.saida)
    desenhar(res, saida)
    import pandas as pd
    _comum.escrever_csv(saida, "h2_logistica.csv", pd.DataFrame(res["linhas"]))
    _comum.escrever_texto(saida, "h2_logistica.txt", ["H2: regressão logística da confirmação humana (exploratório)", ""] + texto)
    print("\n".join(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
