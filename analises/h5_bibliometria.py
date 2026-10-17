"""H5: determinantes bibliométricos da inclusão na revisão (citações, posição no Scholar, abrangência entre termos).

Uma linha por ARTIGO (não por ocorrência): posição = a MELHOR (menor) posição do artigo entre as ocorrências; n_termos = quantos
termos o acharam. A decisão é a triagem humana por título e resumo (`triagem.decisao` em incluir ou excluir).
Testes: Mann-Whitney (citações, posição e n_termos de incluídos x excluídos, com efeito rank-biserial lido como probabilidade
de superioridade) e Spearman entre posição e inclusão. Os três p-valores de Mann-Whitney são ajustados por Holm.
Gráficos: violinos das citações (escala log1p) e taxa de inclusão por faixa de 10 posições (Wilson 95%).

RECUSA RODAR com menos de 50 decisões humanas (ou menos de 10 em algum dos dois grupos): com 0 decisões hoje, só recusa.
`--selftest` prova o cálculo em dados sintéticos de efeito conhecido. Exploratório: a posição pode refletir o próprio algoritmo
do buscador; associação não é causa."""
import sys

import numpy as np

import _comum

MIN_DECISOES = 50
MIN_POR_GRUPO = 10
CONSULTA = """
SELECT a.artigo_id, a.citacoes, a.ano, t.decisao,
       (SELECT MIN(o.posicao) FROM r_ocorrencias o WHERE o.artigo_id = a.artigo_id AND o.posicao >= 1) AS melhor_posicao,
       m.n_termos
FROM r_artigos a JOIN triagem t ON t.artigo_id = a.artigo_id AND t.decisao IN ('incluir', 'excluir')
LEFT JOIN v_artigos_multi_termo m ON m.artigo_id = a.artigo_id"""


def recusa(df):
    """Mensagem em português se as decisões humanas não bastam; None se bastam."""
    n = len(df)
    n_inc = int((df["decisao"] == "incluir").sum()) if n else 0
    n_exc = n - n_inc
    if n < MIN_DECISOES or min(n_inc, n_exc) < MIN_POR_GRUPO:
        return (f"a análise H5 só roda com pelo menos {MIN_DECISOES} decisões humanas de triagem e pelo menos {MIN_POR_GRUPO} em cada grupo "
                f"(incluir e excluir). Hoje: {n} decisões ({n_inc} incluir, {n_exc} excluir). Faça a triagem humana antes.")
    return None


def analisar(df):
    from scipy import stats
    from statsmodels.stats.multitest import multipletests
    from statsmodels.stats.proportion import proportion_confint
    d = df.copy()
    d["incluido"] = (d["decisao"] == "incluir").astype(int)
    texto = [f"n = {len(d)} artigos com decisão humana ({int(d.incluido.sum())} incluir, {int((1 - d.incluido).sum())} excluir)"]
    testes = []
    for coluna, nome in (("citacoes", "citações"), ("melhor_posicao", "melhor posição no Scholar"), ("n_termos", "número de termos que acharam o artigo")):
        g = d.dropna(subset=[coluna])
        a, b = g.loc[g.incluido == 1, coluna].to_numpy(float), g.loc[g.incluido == 0, coluna].to_numpy(float)
        if len(a) < 2 or len(b) < 2 or len(set(a) | set(b)) < 2:
            texto.append(f"{nome}: dados insuficientes (n incluídos = {len(a)}, excluídos = {len(b)})")
            continue
        u = stats.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic", use_continuity=True)
        rb = 2 * u.statistic / (len(a) * len(b)) - 1
        testes.append({"variavel": coluna, "nome": nome, "n_inc": len(a), "n_exc": len(b), "mediana_inc": float(np.median(a)),
                       "mediana_exc": float(np.median(b)), "u": float(u.statistic), "p": float(u.pvalue), "rank_biserial": float(rb),
                       "prob_superioridade": (rb + 1) / 2})
    if testes:
        ajust = multipletests([t["p"] for t in testes], method="holm")[1]
        texto.append("Mann-Whitney (incluídos x excluídos); a probabilidade de superioridade é a chance de um incluído sorteado ter valor MAIOR que um excluído:")
        for t, pa in zip(testes, ajust):
            t["p_holm"] = float(pa)
            texto.append(f"  {t['nome']}: mediana incluídos = {t['mediana_inc']:g} (n = {t['n_inc']}), excluídos = {t['mediana_exc']:g} (n = {t['n_exc']}); "
                         f"U = {t['u']:.0f}, p = {t['p']:.3g}, p ajustado (Holm) = {pa:.3g}; rank-biserial = {t['rank_biserial']:+.2f} "
                         f"(prob. de superioridade = {100 * t['prob_superioridade']:.0f}%)")
    pos = d.dropna(subset=["melhor_posicao"])
    rho = None
    if len(pos) >= 10 and pos.melhor_posicao.nunique() > 1 and pos.incluido.nunique() > 1:
        r = stats.spearmanr(pos.melhor_posicao, pos.incluido)
        rho = {"rho": float(r.statistic), "p": float(r.pvalue), "n": len(pos)}
        texto.append(f"Spearman entre melhor posição e inclusão (0/1): rho = {r.statistic:+.3f}, p = {r.pvalue:.3g}, n = {len(pos)} "
                     "(rho negativo = posição melhor, isto é, número menor, vai com mais inclusão)")
    faixas = []
    for k, g in pos.assign(faixa=(pos.melhor_posicao - 1) // 10).groupby("faixa"):
        n, inc = len(g), int(g.incluido.sum())
        lo, hi = proportion_confint(inc, n, method="wilson")
        faixas.append({"faixa": f"{int(k) * 10 + 1}-{int(k) * 10 + 10}", "n": n, "incluidos": inc, "taxa": inc / n, "inf": lo, "sup": hi})
    if faixas:
        texto.append("Taxa de inclusão por faixa de posição: " + "; ".join(f"{f['faixa']}: {f['incluidos']}/{f['n']}" for f in faixas))
    texto += ["", "Leitura: com centenas de artigos, diferenças pequenas dão p pequeno; leia o EFEITO (probabilidade de superioridade), não só o p.",
              "Posição e citações no Scholar dependem do algoritmo do buscador; a decisão de inclusão é de uma ou poucas pessoas."]
    return {"testes": testes, "spearman": rho, "faixas": faixas, "dados": d}, texto


def desenhar(res, pasta):
    import matplotlib.pyplot as plt
    _comum.novo_grafico()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.2))
    d = res["dados"].dropna(subset=["citacoes"])
    grupos = [np.log1p(d.loc[d.incluido == 0, "citacoes"].to_numpy(float)), np.log1p(d.loc[d.incluido == 1, "citacoes"].to_numpy(float))]
    partes = a1.violinplot([g for g in grupos if len(g)], showmedians=True, showextrema=False)
    for corpo, cor in zip(partes["bodies"], (_comum.CINZA, _comum.AZUL)):
        corpo.set_facecolor(cor); corpo.set_alpha(0.5)
    partes["cmedians"].set_color(_comum.TINTA)
    a1.set_xticks([1, 2][:len([g for g in grupos if len(g)])])
    a1.set_xticklabels([f"excluir (n = {len(grupos[0])})", f"incluir (n = {len(grupos[1])})"][:len([g for g in grupos if len(g)])])
    a1.set_ylabel("log(1 + citações)")
    a1.set_title("H5: citações por decisão", loc="left", fontsize=11)
    f = res["faixas"]
    if f:
        x = np.arange(len(f))
        a2.errorbar(x, [i["taxa"] for i in f], yerr=[[i["taxa"] - i["inf"] for i in f], [i["sup"] - i["taxa"] for i in f]],
                    fmt="o-", color=_comum.AZUL, lw=1.5, capsize=3, ms=5)
        a2.set_xticks(x); a2.set_xticklabels([f"{i['faixa']}\n(n = {i['n']})" for i in f], fontsize=8)
        a2.set_ylim(0, 1)
    a2.set_xlabel("faixa da melhor posição no Scholar"); a2.set_ylabel("proporção incluída (Wilson 95%)")
    a2.set_title("Inclusão por faixa de posição", loc="left", fontsize=11)
    return _comum.salvar_figura(fig, pasta, "h5_bibliometria")


def sintetico(n=300, semente=_comum.SEMENTE):
    import pandas as pd
    rng = np.random.default_rng(semente)
    inc = (rng.random(n) < 0.35).astype(int)
    cit = np.round(np.exp(rng.normal(1.5 + 1.2 * inc, 1.4))).astype(int)
    pos = np.clip(np.round(rng.normal(32 - 14 * inc, 14)), 1, 60).astype(int)
    nt = 1 + rng.poisson(0.5 + 0.8 * inc)
    return pd.DataFrame({"artigo_id": np.arange(n), "citacoes": cit, "ano": 2020, "decisao": np.where(inc == 1, "incluir", "excluir"),
                         "melhor_posicao": pos, "n_termos": nt})


def main():
    args = _comum.ler_argumentos(__doc__.split("\n")[0])
    if args.selftest:
        df = sintetico()
        assert recusa(df) is None
        res, _ = analisar(df)
        t = {x["variavel"]: x for x in res["testes"]}
        assert t["citacoes"]["p"] < 1e-6 and t["citacoes"]["prob_superioridade"] > 0.6
        assert t["melhor_posicao"]["p"] < 1e-6 and t["melhor_posicao"]["prob_superioridade"] < 0.4
        assert res["spearman"]["rho"] < -0.3 and t["n_termos"]["p_holm"] < 0.01
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            desenhar(res, pasta)
        assert recusa(sintetico(n=30)) and recusa(df.head(0))
        print("selftest ok: efeitos conhecidos detectados (citações e abrangência maiores e posição menor nos incluídos); recusa com poucas decisões")
        return 0
    import conexao
    con = conexao.abrir(args.banco)
    df = conexao.tabela(con, CONSULTA)
    motivo = recusa(df)
    if motivo:
        _comum.dados_insuficientes(motivo)
    res, texto = analisar(df)
    saida = _comum.preparar_saida(args.saida)
    desenhar(res, saida)
    import pandas as pd
    _comum.escrever_csv(saida, "h5_bibliometria.csv", pd.DataFrame(res["testes"]))
    _comum.escrever_texto(saida, "h5_bibliometria.txt", ["H5: determinantes bibliométricos da inclusão (exploratório)", ""] + texto)
    print("\n".join(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
