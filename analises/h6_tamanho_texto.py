"""H6: tamanho do texto enviado ao classificador x achados e falhas de JSON (análise exploratória).

Usa o HISTÓRICO de classificações (`r_classificacoes_historico`: toda chamada feita), como a análise H6 do painel.
1. Curva LOWESS dos achados por 1.000 caracteres contra os caracteres enviados (linha de corte em 60.000);
2. qui-quadrado (e exato de Fisher) da taxa de JSON inválido em páginas truncadas x íntegras;
3. regressão linear ROBUSTA (Huber) do número de achados contra os caracteres enviados.

Saída: h6_tamanho_texto.svg/.png, h6_tamanho_texto.txt e h6_tamanho_texto.csv (dados usados).
Os números são exploratórios: uma classificação por chamada, e a mesma página pode aparecer mais de uma vez."""
import sys

import numpy as np

import _comum

CORTE_CHARS = 60000


def analisar(df):
    """Devolve (resultado: dict, linhas de texto). `df`: colunas n_chars_enviados, texto_truncado, json_valido, n_achados."""
    from scipy import stats
    import statsmodels.api as sm
    from statsmodels.stats.proportion import proportion_confint
    df = df.copy()
    df["json_invalido"] = (df["json_valido"].fillna(0).astype(int) != 1).astype(int)
    df["truncado"] = df["texto_truncado"].fillna(0).astype(int)
    texto = [f"n de classificações (histórico): {len(df)}; truncadas: {int(df.truncado.sum())}; JSON inválido: {int(df.json_invalido.sum())}", ""]
    res = {"n": len(df)}

    # 2. JSON inválido em truncadas x íntegras
    t = df.groupby("truncado")["json_invalido"].agg(["sum", "count"])
    texto.append("JSON inválido em páginas truncadas x íntegras")
    for grupo, nome in ((1, "truncadas"), (0, "íntegras")):
        if grupo in t.index:
            k, n = int(t.loc[grupo, "sum"]), int(t.loc[grupo, "count"])
            lo, hi = proportion_confint(k, n, method="wilson")
            texto.append(f"  {nome}: {k} de {n} ({100 * k / n:.1f}%; Wilson 95%: {100 * lo:.1f}% a {100 * hi:.1f}%)")
    if len(t) == 2 and t["sum"].sum() > 0 and t["sum"].sum() < t["count"].sum():
        tabela = np.array([[t.loc[g, "sum"], t.loc[g, "count"] - t.loc[g, "sum"]] for g in (1, 0)])
        chi2, p, _, esp = stats.chi2_contingency(tabela, correction=False)
        res.update({"chi2": float(chi2), "p_chi2": float(p), "p_fisher": float(stats.fisher_exact(tabela)[1])})
        texto.append(f"  qui-quadrado = {chi2:.3f}, p = {p:.4g}; exato de Fisher p = {res['p_fisher']:.4g}"
                     + ("  (esperado < 5 em alguma casela: use o exato de Fisher)" if (esp < 5).any() else ""))
    else:
        res.update({"chi2": None, "p_chi2": None})
        texto.append("  teste NÃO definido: não há variação (nenhum JSON inválido, ou todos inválidos, ou falta um dos grupos).")

    # 1. densidade e LOWESS (só classificações com JSON válido e texto > 0)
    ok = df[(df.json_invalido == 0) & (df.n_chars_enviados > 0)].copy()
    ok["por_mil"] = 1000.0 * ok["n_achados"] / ok["n_chars_enviados"]
    texto += ["", f"Achados por 1.000 caracteres (JSON válido, n = {len(ok)})"]
    for grupo, nome in ((0, "íntegras"), (1, "truncadas")):
        g = ok[ok.truncado == grupo]
        if len(g):
            texto.append(f"  {nome}: n = {len(g)}, mediana = {g.por_mil.median():.3f}, média = {g.por_mil.mean():.3f}; "
                         f"achados por classificação, média = {g.n_achados.mean():.2f}")
    curva = None
    if len(ok) >= 20:
        curva = sm.nonparametric.lowess(ok["por_mil"], np.log10(ok["n_chars_enviados"]), frac=0.4)
        res["lowess"] = curva
    # 3. regressão robusta
    if len(ok) >= 20 and ok["n_chars_enviados"].nunique() > 2:
        X = sm.add_constant(ok["n_chars_enviados"].to_numpy(float) / 10000.0)
        rlm = sm.RLM(ok["n_achados"].to_numpy(float), X, M=sm.robust.norms.HuberT()).fit()
        ols = sm.OLS(ok["n_achados"].to_numpy(float), X).fit(cov_type="HC3")
        res.update({"inclinacao_rlm": float(rlm.params[1]), "ic_rlm": [float(v) for v in rlm.conf_int()[1]],
                    "p_rlm": float(rlm.pvalues[1]), "inclinacao_ols": float(ols.params[1])})
        texto += ["", "Regressão linear robusta (Huber): achados = a + b x (caracteres / 10.000)",
                  f"  b = {rlm.params[1]:.3f} achados por 10.000 caracteres (IC 95%: {res['ic_rlm'][0]:.3f} a {res['ic_rlm'][1]:.3f}; p = {rlm.pvalues[1]:.3g})",
                  f"  para comparação, mínimos quadrados com erro robusto HC3: b = {ols.params[1]:.3f}"]
    else:
        texto += ["", "Regressão robusta: dados insuficientes (menos de 20 classificações válidas)."]
    texto += ["", "Leitura: associação, não causa. Páginas longas são de outros tipos (portais, diários) e o texto truncado em 60.000",
              "caracteres perde o que vem depois do corte; a densidade menor nelas pode ser do tipo de página, e não do modelo."]
    return res, texto, ok


def desenhar(ok, res, pasta):
    fig, ax = _comum.novo_grafico(7.4, 4.6)
    for origem, cor in (("pagina", _comum.AZUL), ("snippet", _comum.LARANJA)):
        g = ok[ok["origem_texto"] == origem] if "origem_texto" in ok else ok
        if len(g):
            ax.scatter(g["n_chars_enviados"], g["por_mil"], s=10, alpha=0.35, color=cor, label=f"{origem} (n = {len(g)})", linewidths=0)
    if res.get("lowess") is not None:
        ax.plot(10 ** res["lowess"][:, 0], np.clip(res["lowess"][:, 1], 0, None), color=_comum.TINTA, lw=2,
                label="LOWESS (fração 0,4, em log10 dos caracteres; valores negativos cortados em 0)")
    ax.axvline(CORTE_CHARS, color=_comum.CINZA, ls="--", lw=1.2)
    ax.text(CORTE_CHARS, ax.get_ylim()[1] * 0.97, " corte de 60.000", ha="right", va="top", color=_comum.CINZA, fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("caracteres enviados ao classificador (escala log)")
    ax.set_ylabel("achados por 1.000 caracteres")
    ax.set_title("H6: densidade de achados x tamanho do texto (JSON válido)", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8)
    return _comum.salvar_figura(fig, pasta, "h6_tamanho_texto")


def sintetico():
    """Dados com efeito conhecido: acima de 60.000 trunca; JSON inválido mais comum nas truncadas; achados por caractere caem."""
    import pandas as pd
    rng = np.random.default_rng(_comum.SEMENTE)
    n = 900
    chars = np.minimum(np.exp(rng.normal(8.4, 1.3, n)).astype(int) + 50, CORTE_CHARS)
    trunc = (chars >= CORTE_CHARS).astype(int)
    inval = (rng.random(n) < np.where(trunc == 1, 0.30, 0.02)).astype(int)
    achados = rng.poisson(np.maximum(0.2, 2.5 - 0.00003 * chars))
    return pd.DataFrame({"n_chars_enviados": chars, "texto_truncado": trunc, "json_valido": 1 - inval, "n_achados": achados,
                         "origem_texto": np.where(chars < 1500, "snippet", "pagina")})


def main():
    args = _comum.ler_argumentos(__doc__.split("\n")[0])
    if args.selftest:
        df = sintetico()
    else:
        import conexao
        con = conexao.abrir(args.banco)
        df = conexao.tabela(con, "SELECT classificacao_id, n_chars_enviados, texto_truncado, json_valido, n_achados, origem_texto "
                                 "FROM r_classificacoes_historico")
        if df.empty:
            _comum.dados_insuficientes("não há classificações no histórico do relatório; rode a classificação antes.")
    res, texto, ok = analisar(df)
    if args.selftest:
        assert res["p_chi2"] < 0.001 and res["inclinacao_rlm"] < 0 and res["ic_rlm"][1] < 0, res
        print("selftest ok: efeito conhecido recuperado (JSON inválido mais comum nas truncadas; inclinação robusta negativa)")
    saida = _comum.preparar_saida(args.saida)
    if not args.selftest:
        desenhar(ok, res, saida)
        _comum.escrever_texto(saida, "h6_tamanho_texto.txt", ["H6: tamanho do texto x achados e falhas de JSON (exploratório)", ""] + texto)
        _comum.escrever_csv(saida, "h6_tamanho_texto.csv", ok.drop(columns=["por_mil"]).assign(por_mil_chars=ok["por_mil"]))
        print("\n".join(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
