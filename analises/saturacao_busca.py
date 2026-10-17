"""Curva de saturação da busca acadêmica: ajuste de N(t) = K (1 - exp(-r t)) à curva cumulativa de descoberta.

t é a ordem da chamada bem-sucedida da busca acadêmica e N(t) o total acumulado de artigos novos (`v_curva_descoberta`).
Bandas de confiança por bootstrap de resíduos em blocos (blocos de 5 chamadas, porque a curva é acumulada e os resíduos
são autocorrelacionados; mesmo assim a banda tende a ser estreita demais). A DESCRIÇÃO abaixo é tudo o que o ajuste é.

NOTA DE HONESTIDADE (docs/ESTATISTICA_EXPLICADA.md, seção 14): o ajuste descreve a taxa de descoberta destas consultas neste
buscador; K NÃO é uma estimativa do total de artigos relevantes sobre o tema e o ajuste NÃO prova saturação teórica. Cada
termo foi buscado sozinho, então a subida reflete termos diferentes, e Scholar, IEEE, ACM, Scopus e SBC OpenLib não são fontes
independentes. Para sustentar abrangência use lista de controle e bola de neve, não K.

Saída: saturacao_busca.svg/.png, .txt e .csv (curva observada e ajustada)."""
import sys

import numpy as np

import _comum

BLOCO = 5
REPETICOES = 1000
NOTA = ("NOTA DE HONESTIDADE: o ajuste é uma descrição da taxa de descoberta destas consultas neste buscador. K não é uma "
        "estimativa do total de artigos sobre o tema, e o ajuste não prova saturação teórica (ESTATISTICA_EXPLICADA, seção 14).")


def _modelo(t, K, r):
    return K * (1.0 - np.exp(-r * t))


def _ajustar(t, y, partida=None):
    from scipy.optimize import curve_fit
    n_final = float(y[-1])
    limite_k = 50.0 * n_final
    melhor = None
    if partida is not None:
        partida = (min(max(partida[0], n_final * 1.0001), limite_k * 0.9999), partida[1])
    partidas = [partida] if partida is not None else [(n_final * 2, r0) for r0 in (0.001, 0.01, 0.05, 0.2)]  # o ajuste é pouco curvo e instável
    for p0 in partidas:
        try:
            p, _ = curve_fit(_modelo, t, y, p0=list(p0), bounds=([n_final, 1e-8], [limite_k, 5.0]), maxfev=3000)
        except (RuntimeError, ValueError):
            continue
        sse = float(((y - _modelo(t, *p)) ** 2).sum())
        if melhor is None or sse < melhor[0]:
            melhor = (sse, p)
    return (None, None) if melhor is None else (melhor[1], limite_k)


def analisar(curva, repeticoes=REPETICOES):
    """`curva`: DataFrame com `novos_acumulado` na ordem das chamadas. Devolve (resultado, texto)."""
    y = curva["novos_acumulado"].to_numpy(float)
    n = len(y)
    t = np.arange(1, n + 1, dtype=float)
    texto = [f"chamadas bem-sucedidas da busca acadêmica: {n}; artigos únicos acumulados: {int(y[-1])}"]
    p, limite_k = _ajustar(t, y)
    if p is None:
        texto.append("o ajuste não convergiu")
        return {"n": n, "ajustou": False}, texto
    K, r = p
    fit = _modelo(t, K, r)
    resid = y - fit
    r2 = 1 - ((y - fit) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    gerador = np.random.default_rng(_comum.SEMENTE)
    curvas, ks, rs = [], [], []
    inicios = np.arange(0, max(1, n - BLOCO + 1))
    for _ in range(repeticoes):
        blocos = [resid[i:i + BLOCO] for i in gerador.choice(inicios, size=int(np.ceil(n / BLOCO)))]
        e = np.concatenate(blocos)[:n]
        pb, _ = _ajustar(t, np.maximum.accumulate(np.maximum(fit + e, 0)), partida=(K, r))
        if pb is not None:
            ks.append(pb[0]); rs.append(pb[1]); curvas.append(_modelo(t, *pb))
    curvas = np.array(curvas)
    banda = np.percentile(curvas, [2.5, 97.5], axis=0)
    k_ic, r_ic = np.percentile(ks, [2.5, 97.5]), np.percentile(rs, [2.5, 97.5])
    no_limite = K >= 0.98 * limite_k
    pct_ultimas5 = None
    if "pct_novos" in curva and curva["pct_novos"].notna().any():
        pct_ultimas5 = float(curva["pct_novos"].dropna().tail(5).mean())
    res = {"n": n, "ajustou": True, "K": float(K), "r": float(r), "r2": float(r2), "k_ic": k_ic, "r_ic": r_ic, "banda": banda,
           "ajuste": fit, "t": t, "y": y, "K_no_limite": bool(no_limite), "pct_novos_ultimas_5": pct_ultimas5,
           "meia_vida_chamadas": float(np.log(2) / r)}
    texto += [f"ajuste: K = {K:.0f} (IC 95% por bootstrap em blocos: {k_ic[0]:.0f} a {k_ic[1]:.0f}), r = {r:.4f} por chamada "
              f"(IC 95%: {r_ic[0]:.4f} a {r_ic[1]:.4f}); R² = {r2:.3f}",
              f"metade do K seria atingida na chamada {np.log(2) / r:.0f} (descrição do ritmo; n observado = {n})"]
    if pct_ultimas5 is not None:
        texto.append(f"descrição direta, sem modelo: nas últimas 5 chamadas, {pct_ultimas5:.1f}% dos resultados eram artigos novos")
    if no_limite or k_ic[1] > 10 * y[-1]:
        texto.append("ATENÇÃO: K não é identificável com estes dados (o limite superior do IC é muito maior que o observado, ou o ajuste "
                     "encostou no limite): a curva ainda é quase uma reta, sem sinal de achatamento.")
    elif K < 1.2 * y[-1]:
        texto.append("A curva já está achatando para ESTAS consultas (K próximo do observado); isso mede o esgotamento destas consultas, não do tema.")
    texto += ["", NOTA, "Cada termo foi buscado sozinho nesta rodada: a subida reflete termos diferentes, não repetição da mesma busca."]
    return res, texto


def desenhar(res, pasta, nome="saturacao_busca"):
    fig, ax = _comum.novo_grafico(7.4, 4.6)
    t = res["t"]
    ax.fill_between(t, res["banda"][0], res["banda"][1], color=_comum.AZUL, alpha=0.18, lw=0, label="banda 95% (bootstrap em blocos)")
    ax.plot(t, res["ajuste"], color=_comum.AZUL, lw=2, label=f"ajuste K(1 - exp(-r t)): K = {res['K']:.0f}, r = {res['r']:.3f}")
    ax.plot(t, res["y"], color=_comum.TINTA, lw=1.4, label="artigos únicos acumulados (observado)")
    ax.set_xlabel("ordem da chamada bem-sucedida (busca acadêmica)")
    ax.set_ylabel("artigos únicos acumulados")
    ax.set_title("Curva de descoberta e ajuste exponencial saturante (descrição)", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.text(0.01, 0.005, "K descreve o ritmo destas consultas; não é o total de artigos do tema nem prova de saturação.",
             fontsize=7.5, color=_comum.CINZA, va="bottom")
    fig.subplots_adjust(bottom=0.2)
    return _comum.salvar_figura(fig, pasta, nome)


def sintetico(K=800, r=0.05, n=60, ruido=6.0):
    import pandas as pd
    rng = np.random.default_rng(_comum.SEMENTE)
    t = np.arange(1, n + 1)
    y = np.maximum.accumulate(np.round(K * (1 - np.exp(-r * t)) + rng.normal(0, ruido, n)))
    return pd.DataFrame({"novos_acumulado": y})


def main():
    args = _comum.ler_argumentos(__doc__.split("\n")[0])
    if args.selftest:
        res, texto = analisar(sintetico(), repeticoes=200)
        assert abs(res["K"] - 800) / 800 < 0.10 and abs(res["r"] - 0.05) < 0.01, res["K"]
        import pandas as pd
        reta, _ = analisar(pd.DataFrame({"novos_acumulado": np.arange(1, 61) * 10.0}), repeticoes=100)
        assert reta["K_no_limite"] or reta["k_ic"][1] > 10 * 600, "uma reta deveria ser marcada como não identificável"
        print(f"selftest ok: K recuperado = {res['K']:.0f} (verdadeiro 800); uma curva sem achatamento é marcada como não identificável")
        return 0
    import conexao
    con = conexao.abrir(args.banco)
    curva = conexao.curva_descoberta(con)
    if len(curva) < 8:
        _comum.dados_insuficientes(f"a curva de descoberta tem {len(curva)} chamadas (mínimo 8); faça mais buscas acadêmicas.")
    res, texto = analisar(curva)
    saida = _comum.preparar_saida(args.saida)
    if res["ajustou"]:
        desenhar(res, saida)
        import pandas as pd
        _comum.escrever_csv(saida, "saturacao_busca.csv", pd.DataFrame({"ordem": res["t"], "observado": res["y"], "ajuste": res["ajuste"],
                                                                       "banda_inferior": res["banda"][0], "banda_superior": res["banda"][1]}))
    _comum.escrever_texto(saida, "saturacao_busca.txt", ["Saturação da busca acadêmica (descrição)", ""] + texto)
    print("\n".join(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
