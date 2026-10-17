"""Calibração de tokens: regressão de `tokens_entrada` sobre `n_chars_enviados` (checagem da constante de 3,4 caracteres por token).

Modelo: tokens = a + b x caracteres. O intercepto `a` é o prompt fixo (instruções) e a inclinação `b` é o custo por caractere
de TEXTO; logo caracteres por token do texto = 1 / b (a razão simples chars/tokens é menor porque inclui o prompt).
Intervalos de 95% com erro-padrão robusto (HC3); o de 1/b vem da inversão dos limites de b.

Saída: calibracao_tokens.svg/.png, .txt e .csv. Exploratório: um classificador e um tipo de texto por vez podem diferir."""
import sys

import numpy as np

import _comum

CONSTANTE_CONFIG = 3.4     # caracteres por token adotados em config/triagem_escopo.py (valor do plano; só para comparar)


def _ajuste(chars, tokens):
    import statsmodels.api as sm
    X = sm.add_constant(np.asarray(chars, float))
    m = sm.OLS(np.asarray(tokens, float), X).fit(cov_type="HC3")
    (a_lo, a_hi), (b_lo, b_hi) = m.conf_int()
    res = {"n": len(chars), "a": float(m.params[0]), "b": float(m.params[1]), "a_ic": (float(a_lo), float(a_hi)),
           "b_ic": (float(b_lo), float(b_hi)), "r2": float(m.rsquared)}
    res["chars_por_token"] = 1 / res["b"] if res["b"] > 0 else None
    res["cpt_ic"] = (1 / b_hi, 1 / b_lo) if b_lo > 0 else None
    return res


def analisar(df):
    """`df`: colunas chars, tokens (e opcionais classificador, origem_texto). Devolve (resultado, texto)."""
    df = df[(df.chars > 0) & (df.tokens > 0)]
    if len(df) < 10:
        return None, [f"dados insuficientes: {len(df)} chamadas de classificação com tokens (mínimo 10)"]
    razao = df.chars / df.tokens
    res = _ajuste(df.chars, df.tokens)
    texto = [f"n = {res['n']} chamadas de classificação (histórico do relatório)",
             f"razão simples caracteres/tokens: mediana = {razao.median():.2f}, média = {razao.mean():.2f} (inclui o prompt fixo)",
             f"regressão tokens = a + b x chars: a = {res['a']:.0f} tokens (IC 95%: {res['a_ic'][0]:.0f} a {res['a_ic'][1]:.0f}; prompt fixo), "
             f"b = {res['b']:.5f} (IC 95%: {res['b_ic'][0]:.5f} a {res['b_ic'][1]:.5f}), R² = {res['r2']:.3f}"]
    if res["chars_por_token"]:
        lo, hi = res["cpt_ic"]
        dentro = lo <= CONSTANTE_CONFIG <= hi
        texto.append(f"caracteres por token do texto (1/b) = {res['chars_por_token']:.2f} (IC 95%: {lo:.2f} a {hi:.2f}); a constante {CONSTANTE_CONFIG} "
                     + ("ESTÁ dentro do intervalo." if dentro else "está FORA do intervalo: "
                        + ("o texto custa mais tokens que o assumido (estimativa de custo baixa demais)." if CONSTANTE_CONFIG > hi
                           else "o texto custa menos tokens que o assumido (estimativa de custo alta demais).")))
        res["constante_dentro"] = dentro
    else:
        texto.append("inclinação não positiva: não há relação linear aproveitável.")
    for coluna in ("classificador", "origem_texto"):
        if coluna in df and df[coluna].nunique() > 1:
            texto.append(f"por {coluna}:")
            for nome, g in df.groupby(coluna):
                if len(g) >= 10 and g.chars.nunique() > 3:
                    r = _ajuste(g.chars, g.tokens)
                    ic = f" (IC 95%: {r['cpt_ic'][0]:.2f} a {r['cpt_ic'][1]:.2f})" if r["cpt_ic"] else ""
                    texto.append(f"  {nome}: n = {r['n']}, chars/token do texto = {r['chars_por_token']:.2f}{ic}, prompt fixo = {r['a']:.0f} tokens")
                else:
                    texto.append(f"  {nome}: n = {len(g)} (insuficiente para ajustar)")
    texto += ["", "Leitura: o tokenizador é do provedor; esta é uma medida empírica deste modelo e deste idioma (português),",
              "não uma propriedade geral. Os tokens de entrada incluem também o prompt do sistema."]
    return res, texto


def desenhar(df, res, pasta):
    fig, ax = _comum.novo_grafico(7.2, 4.6)
    ax.scatter(df.chars, df.tokens, s=9, alpha=0.3, color=_comum.AZUL, linewidths=0, label=f"chamadas (n = {len(df)})")
    x = np.linspace(0, df.chars.max(), 100)
    ax.plot(x, res["a"] + res["b"] * x, color=_comum.TINTA, lw=2, label=f"ajuste: {res['chars_por_token']:.2f} chars/token do texto")
    ax.plot(x, res["a"] + x / CONSTANTE_CONFIG, color=_comum.LARANJA, lw=1.5, ls="--", label=f"constante {CONSTANTE_CONFIG} (mesmo intercepto)")
    ax.set_xlabel("caracteres enviados")
    ax.set_ylabel("tokens de entrada")
    ax.set_title("Calibração de tokens: tokens de entrada x caracteres enviados", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8)
    return _comum.salvar_figura(fig, pasta, "calibracao_tokens")


def sintetico():
    import pandas as pd
    rng = np.random.default_rng(_comum.SEMENTE)
    chars = rng.integers(200, 60000, 400)
    tokens = (800 + chars / 3.0 + rng.normal(0, 150, 400)).round()
    return pd.DataFrame({"chars": chars, "tokens": tokens, "classificador": "sintetico"})


def main():
    args = _comum.ler_argumentos(__doc__.split("\n")[0])
    if args.selftest:
        res, _ = analisar(sintetico())
        assert abs(res["chars_por_token"] - 3.0) < 0.1 and res["cpt_ic"][0] < 3.0 < res["cpt_ic"][1], res
        assert not res["constante_dentro"], "3,4 deveria ficar fora do intervalo de uma série gerada com 3,0"
        print(f"selftest ok: chars/token recuperado = {res['chars_por_token']:.2f} (verdadeiro 3,0) e 3,4 corretamente fora do IC")
        return 0
    import conexao
    con = conexao.abrir(args.banco)
    df = conexao.tabela(con, """SELECT k.n_chars_enviados AS chars, c.tokens_entrada AS tokens, k.classificador, k.origem_texto
                                FROM r_classificacoes_historico k JOIN r_chamadas c ON c.chamada_id = k.chamada_id
                                WHERE c.etapa = 'classificacao' AND k.n_chars_enviados > 0 AND c.tokens_entrada > 0""")
    res, texto = analisar(df)
    if res is None:
        _comum.dados_insuficientes(texto[0])
    saida = _comum.preparar_saida(args.saida)
    desenhar(df, res, saida)
    _comum.escrever_csv(saida, "calibracao_tokens.csv", df)
    _comum.escrever_texto(saida, "calibracao_tokens.txt", ["Calibração de tokens (exploratório)", ""] + texto)
    print("\n".join(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
