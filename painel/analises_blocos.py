"""Blocos da pagina /analises: cada bloco junta um grafico (SVG do servidor), um titulo que CONTA A CONCLUSAO, uma frase em
linguagem simples (modo gestor) e a memoria de calculo (modo pesquisador, dentro de um <details>).

Tudo aqui e funcao pura: recebe os dicionarios que `adaptadores/leitura_analises.py` devolve e devolve blocos. Nao toca no
banco. Regras do plano de visualizacao: nenhum numero sem a quantidade de casos, nenhum resultado que dependa de revisao
humana e apresentado como confirmado quando ainda nao ha verificacao, e cada barra ou celula leva aos registros."""
from urllib.parse import urlencode

from markupsafe import Markup

from dominio import estatistica as est
from painel import formatacao as fmt, graficos_analises as g, rotulos, selos_estatisticos as selos

ORDEM_REGIOES = ("Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul")
LIMITE_FALSA_EXCLUSAO = 0.02
LIMITE_TEXTO_MODELO = 60_000          # igual a CLASSIFICACAO["max_chars_texto"] (o painel nao le config/)
AVISO_NAO_VERIFICADO = ("Estes números são de achados classificados pelo modelo, ainda sem verificação humana; "
                        "não são resultados confirmados.")
AVISO_SEM_HUMANOS = "Aguardando verificação humana: este gráfico só aparece quando houver decisões de uma pessoa."


def _href(caminho, **params):
    limpos = {k: v for k, v in params.items() if v not in (None, "")}
    return caminho + ("?" + urlencode(limpos) if limpos else "")


def _tec(chave):
    return rotulos.TECNOLOGIAS.get(chave, chave or "—")


def _bloco(id_, titulo, grafico=None, subtitulo="", texto=(), selo=None, aviso=None, pares=(), tabela=None, link=None):
    """`grafico` ja e HTML seguro vindo de `graficos_analises` (por isso Markup). `texto` = paragrafos simples (escapados)."""
    return {"id": id_, "titulo": titulo, "subtitulo": subtitulo, "grafico": Markup(grafico) if grafico else None,
            "texto": [t for t in texto if t], "selo": selo, "aviso": aviso, "pares": list(pares), "tabela": tabela, "link": link}


def _pct(parte, total):
    return fmt.pct(parte, total)


# ---------------------------------------------------------------- adocao
def bloco_maturidade(d):
    regioes = d.get("regioes") or {}
    tecnologias = list(rotulos.TECNOLOGIAS)
    ufs = sorted(regioes, key=lambda u: (ORDEM_REGIOES.index(regioes[u]) if regioes[u] in ORDEM_REGIOES else 99, u))
    linhas = [{"chave": u, "rotulo": u, "grupo": regioes[u]} for u in ufs]
    colunas = [{"chave": t, "rotulo": _tec(t)} for t in tecnologias]
    celulas, com_dados, em_uso = {}, set(), set()
    for c in d.get("celulas") or []:
        celulas[(c["uf"], c["tecnologia"])] = {"contagens": c["por_status"],
                                               "href": _href("/achados", uf=c["uf"], tecnologia=c["tecnologia"])}
        com_dados.add(c["uf"])
        if c["status_max"] == "em_uso":
            em_uso.add(c["uf"])
    total = len(ufs) or 27
    base = "confirmadas por humano" if d.get("base") == "confirmados" else "classificadas pelo modelo"
    titulo = (f"{len(em_uso)} de {total} UFs têm ao menos uma tecnologia em uso ({base})" if d.get("n_achados")
              else "Ainda não há achados para mapear")
    texto = ["Cada quadrado mostra o estágio mais avançado encontrado para aquela tecnologia naquela UF "
             "(do cinza, apenas citado, ao azul-escuro, em uso). Clique para ver os achados."]
    por_status = {}
    for c in d.get("celulas") or []:
        for st, n in (c.get("por_status") or {}).items():
            por_status[st] = por_status.get(st, 0) + n
    soma = sum(por_status.values())
    if soma and por_status.get("em_uso", 0) / soma > 0.5 and not d.get("tem_dados_humanos"):
        texto.append(f"Cuidado: o modelo classificou {_pct(por_status['em_uso'], soma)} dos achados como em uso e, por mostrar o estágio "
                     "mais avançado, o mapa tende a ficar quase todo azul. Sem verificação humana, não leia como retrato da adoção.")
    return _bloco("maturidade", titulo, g.matriz_maturidade(linhas, colunas, celulas),
                  f"{fmt.numero(d.get('n_achados'))} achados em {len(com_dados)} UFs; pesos ordinais em_uso=5 … apenas_citado=0",
                  texto, aviso=None if d.get("tem_dados_humanos") else AVISO_NAO_VERIFICADO,
                  pares=[("Achados considerados", fmt.numero(d.get("n_achados"))),
                         ("Achados verificados por humano", fmt.numero(d.get("n_verificados"))),
                         ("Achados descartados (fora da conta)", fmt.numero(d.get("n_descartados"))),
                         ("UFs com algum achado", f"{len(com_dados)} de {total}")])


def bloco_regiao_tecnologia(d):
    """Qui-quadrado de independencia regiao x tecnologia (hipotese H1) com os residuos padronizados no mosaico."""
    c = d.get("contingencia_regiao_tecnologia") or {}
    tabela, regioes, tecs = c.get("tabela") or [], c.get("regioes") or [], c.get("tecnologias") or []
    if not tabela or not c.get("n"):
        return _bloco("regiao", "Região e tecnologia: sem achados para comparar", aviso="Sem achados classificados ainda.")
    teste = est.teste_qui_quadrado(tabela)
    metodo, p = "qui-quadrado de Pearson", teste["p_valor"]
    if teste["p_valor"] is not None and (teste["proporcao_esperado_menor_5"] or 0) > 0.2:
        mc = est.teste_qui_quadrado_monte_carlo([[int(v) for v in linha] for linha in tabela], permutacoes=10000, semente=1)
        p, metodo = mc["p_valor"], "qui-quadrado com simulação de Monte Carlo (10.000 permutações; muitas caselas esperadas < 5)"
    residuos = {}
    if teste["residuos_padronizados_ajustados"]:
        for i, li in enumerate(teste["linhas_mantidas"]):
            for j, cj in enumerate(teste["colunas_mantidas"]):
                residuos[(regioes[li], tecs[cj])] = teste["residuos_padronizados_ajustados"][i][j]
    tabela_d = {(regioes[i], tecs[j]): tabela[i][j] for i in range(len(regioes)) for j in range(len(tecs))}
    graf = g.mosaico(tabela_d, [{"chave": r, "rotulo": r} for r in regioes], [{"chave": t, "rotulo": _tec(t)} for t in tecs],
                     "Mistura de tecnologias por região", residuos=residuos or None)
    s = selos.selo(p)
    if p is None:
        titulo = "Região e tecnologia: dados insuficientes para o teste"
    elif p < 0.05:
        titulo = "A mistura de tecnologias muda de uma região para outra"
    else:
        titulo = "Sem evidência suficiente de que a mistura de tecnologias dependa da região"
    texto = [s["texto"],
             "Atenção: a unidade contada é o achado, não a UF; vários achados da mesma UF pesam várias vezes. "
             "Leia como indício, não como prova."]
    return _bloco("regiao", titulo, graf, f"{metodo}; χ² = {fmt.decimal(teste['chi2'], 2)}, gl = {teste['gl']}, "
                  f"p = {'—' if p is None else fmt.decimal(p, 4)}, N = {fmt.numero(teste['n'])}", texto, selo=s,
                  aviso=None if d.get("tem_dados_humanos") else AVISO_NAO_VERIFICADO,
                  pares=[("Método", metodo), ("χ²", fmt.decimal(teste["chi2"], 3)), ("Graus de liberdade", str(teste["gl"])),
                         ("p-valor", "—" if p is None else fmt.decimal(p, 4)), ("N (achados)", fmt.numero(teste["n"])),
                         ("Caselas com esperado < 5", str(teste["celulas_esperado_menor_5"])),
                         ("Aviso do teste", teste.get("aviso") or "nenhum")])


def bloco_lgpd(d):
    itens = [{"rotulo": _tec(x["tecnologia"]), "total": x["n_achados"], "parte": x["n_cita_lgpd"],
              "href": _href("/achados", tecnologia=x["tecnologia"])} for x in d.get("por_tecnologia") or []]
    tot, parte = d.get("n_achados") or 0, d.get("n_cita_lgpd") or 0
    titulo = (f"{_pct(parte, tot)} dos achados têm um trecho que cita a proteção de dados (LGPD)" if tot
              else "Sem achados para medir a citação da LGPD")
    graf = g.barras_proporcao(itens, titulo, "Parte dos achados de cada tecnologia cujo trecho citado menciona a LGPD",
                              rotulo_parte="Cita a LGPD", rotulo_resto="Não cita")
    return _bloco("lgpd", titulo, graf, f"{fmt.numero(tot)} achados; mede `evidencia_cita_lgpd` (o trecho cita a LGPD), "
                  "não o que o modelo marcou",
                  ["Mede se o trecho da página que sustenta o achado fala de proteção de dados. Não prova que a política "
                   "não exista: ela pode estar em outra página."], aviso=None if d.get("tem_dados_humanos") else AVISO_NAO_VERIFICADO,
                  pares=[("Achados", fmt.numero(tot)), ("Trecho cita a LGPD", fmt.numero(parte)),
                         ("Modelo marcou menciona_lgpd", fmt.numero(d.get("n_menciona_lgpd")))])


def bloco_fornecedores(d):
    top = (d.get("top") or [])[:10]
    informado = d.get("n_informado") or 0
    itens = [{"rotulo": x["fornecedor"], "total": informado, "parte": x["n_achados"],
              "href": _href("/achados", q=x["fornecedor"])} for x in top]
    if not informado:
        return _bloco("fornecedores", "Nenhum fornecedor foi identificado nos achados",
                      texto=["As páginas costumam não citar a empresa; o campo fica em branco."],
                      pares=[("Achados sem fornecedor informado", fmt.numero(d.get("n_nao_informado")))])
    share = d.get("share_top3")
    titulo = f"As 3 maiores empresas aparecem em {_pct(share or 0, 1)} dos achados com fornecedor informado"
    graf = g.barras_proporcao(itens, titulo, "Participação de cada empresa entre os achados com fornecedor informado",
                              rotulo_parte="Achados da empresa", rotulo_resto="Demais empresas")
    return _bloco("fornecedores", titulo, graf, f"{fmt.numero(informado)} achados com fornecedor; {fmt.numero(d.get('n_nao_informado'))} sem",
                  ["Concentração calculada só sobre os achados em que a página nomeia a empresa."],
                  aviso=None if d.get("tem_dados_humanos") else AVISO_NAO_VERIFICADO,
                  tabela={"cabecalho": ["Empresa", "Achados", "UFs", "Tecnologias"],
                          "linhas": [[x["fornecedor"], fmt.numero(x["n_achados"]), fmt.numero(x["n_ufs"]),
                                      fmt.numero(x["n_tecnologias"])] for x in top]})


# ---------------------------------------------------------------- busca
def bloco_funil(d):
    # achados e confirmados ficam fora da sequencia: um achado e por tecnologia e uma pagina gera varios, entao o numero
    # pode passar do degrau anterior e a conversao "mais de 100%" enganaria
    degraus = ("resultados", "urls_unicas", "paginas_com_texto", "classificacoes_relevantes")
    funis = [{"rotulo": p["provedor"], "etapas": [(e["rotulo"], e["n"]) for e in p["etapas"] if e["chave"] in degraus]}
             for p in (d.get("provedores") or [])[:2]]
    if not funis:
        return _bloco("funil", "Sem dados de busca web para o funil", aviso="Nenhuma busca web registrada.")
    p0 = d["provedores"][0]
    unico = len(d["provedores"]) == 1
    titulo = (f"De {fmt.numero(p0['resultados'])} resultados da busca, {fmt.numero(p0['paginas_com_texto'])} viraram páginas com texto "
              f"e {fmt.numero(p0['classificacoes_relevantes'])} foram julgadas relevantes")
    texto = ["Cada degrau mostra quanto sobra do anterior; os degraus que afinam demais indicam onde a coleta perde material.",
             f"Das páginas relevantes saíram {fmt.numero(p0['achados'])} achados (um por tecnologia; uma página pode gerar vários) "
             f"e {fmt.numero(p0['confirmados'])} estão confirmados por humano."]
    if unico:
        texto.append("Só um buscador tem dados. A comparação entre buscadores precisa de uma coleta real com o segundo.")
    return _bloco("funil", titulo, g.funil_comparativo(funis, titulo, "Resultados, URLs únicas, páginas com texto, relevantes, achados e confirmados"),
                  "contagens por etapa; um mesmo endereço achado por dois buscadores conta para cada um", texto,
                  aviso=None if d.get("tem_dados_humanos") else "Nenhum achado está confirmado porque ainda não há verificação humana.",
                  pares=[(f"{p['provedor']}: consultas / custo", f"{fmt.numero(p['n_consultas'])} / {fmt.moeda_usd(p['custo_usd'])}")
                         for p in d["provedores"]])


def bloco_posicao_web(d):
    linhas = d.get("linhas") or []
    pontos = [(x["posicao"], x["pct_elegiveis"]) for x in linhas if x.get("pct_elegiveis") is not None]
    if not pontos:
        return _bloco("posicao_web", "Posição do resultado e utilidade: sem triagem de escopo para comparar",
                      aviso="Rode `triar-escopo --fonte web` para medir.")
    primeiro, ultimo = pontos[0][1], pontos[-1][1]
    titulo = (f"Na busca web, {fmt.decimal(primeiro, 0)}% dos resultados da 1ª posição são elegíveis e "
              f"{fmt.decimal(ultimo, 0)}% dos da {pontos[-1][0]}ª")
    graf = g.linha_com_corte(pontos, titulo, "Percentual de resultados web julgados elegíveis pelo modelo, por posição",
                             "Posição no resultado da busca", "% elegíveis")
    return _bloco("posicao_web", titulo, graf, f"{fmt.numero(d.get('n_total'))} resultados; elegível = opinião do modelo sobre o escopo",
                  ["Se a linha não cai com a posição, olhar só os primeiros resultados deixa material bom de fora."],
                  tabela={"cabecalho": ["Posição", "Resultados", "Selecionados p/ download", "Elegíveis"],
                          "linhas": [[x["posicao"], fmt.numero(x["n_resultados"]), fmt.numero(x["n_selecionados"]),
                                      fmt.numero(x["n_elegiveis"])] for x in linhas]})


def bloco_posicao_scholar(d):
    linhas = d.get("linhas") or []
    pontos = [(i + 1, x["pct_elegiveis"]) for i, x in enumerate(linhas) if x.get("pct_elegiveis") is not None]
    if not pontos:
        return _bloco("posicao_scholar", "Posição no Scholar e utilidade: sem triagem de escopo para comparar",
                      aviso="Rode `triar-escopo --fonte artigos` para medir.")
    titulo = (f"No Scholar, {fmt.decimal(pontos[0][1], 0)}% dos artigos das posições {linhas[0]['rotulo']} são elegíveis, "
              f"contra {fmt.decimal(pontos[-1][1], 0)}% nas posições {linhas[len(pontos) - 1]['rotulo']}")
    graf = g.linha_com_corte(pontos, titulo, "Percentual de artigos elegíveis por faixa de 10 posições", "Faixa de posições (1 = 1–10)",
                             "% elegíveis")
    return _bloco("posicao_scholar", titulo, graf, f"{fmt.numero(d.get('n_total'))} ocorrências",
                  ["Indica até que página do Scholar vale a pena olhar."],
                  tabela={"cabecalho": ["Faixa", "Artigos", "Triados", "Elegíveis"],
                          "linhas": [[x["rotulo"], fmt.numero(x["n_artigos"]), fmt.numero(x["n_triados"]),
                                      fmt.numero(x["n_elegiveis"])] for x in linhas]})


def bloco_saturacao(d):
    curva = d.get("curva") or []
    if not curva:
        return _bloco("saturacao", "Sem buscas acadêmicas para medir saturação", aviso="Nenhuma chamada ao Scholar registrada.")
    pontos = [(x["ordem"], x["novos_acumulado"]) for x in curva]
    ult = d.get("pct_novos_ultimas_5")
    titulo = (f"Nas últimas 5 buscas, {fmt.decimal(ult, 0)}% dos resultados eram artigos novos" if ult is not None
              else "Curva de descoberta de artigos")
    graf = g.linha_com_corte(pontos, titulo, "Artigos únicos acumulados ao longo das buscas ao Scholar", "Ordem da busca",
                             "Artigos únicos acumulados")
    return _bloco("saturacao", titulo, graf, f"{fmt.numero(d.get('n_novos_total'))} artigos únicos em {fmt.numero(d.get('n_chamadas'))} chamadas",
                  ["Uma curva que ainda sobe forte indica que a busca está longe de esgotar o tema; uma curva que deita indica saturação. "
                   "Nesta rodada cada termo foi buscado sozinho, então a subida reflete termos diferentes, não repetição."])


# ---------------------------------------------------------------- literatura
def bloco_temporal(d):
    por_ano = [x for x in d.get("por_ano") or [] if x.get("ano") is not None]
    if not por_ano:
        return _bloco("temporal", "Sem artigos com ano conhecido", aviso="Nenhum artigo registrado.")
    anos = sorted({x["ano"] for x in por_ano})
    grupos = sorted({c["grupo"] for c in d["celulas"] if c.get("ano") is not None})
    mapa = {(c["ano"], c["grupo"]): c["n_artigos"] for c in d["celulas"] if c.get("ano") is not None}
    series = [{"rotulo": gr, "valores": [mapa.get((a, gr), 0) for a in anos]} for gr in grupos]
    pico = max(por_ano, key=lambda x: x["n_artigos"])
    titulo = f"A maior parte dos artigos encontrados é de {pico['ano']} ({fmt.numero(pico['n_artigos'])} artigos)"
    graf = g.areas_empilhadas(anos, series, titulo, "Artigos por ano de publicação e grupo de termo")
    return _bloco("temporal", titulo, graf, f"{fmt.numero(d.get('n_artigos'))} artigos; um artigo conta em cada grupo que o encontrou",
                  ["A forma do gráfico mostra tanto o interesse da pesquisa quanto o viés do Scholar por trabalhos recentes."],
                  tabela={"cabecalho": ["Ano", "Artigos", "Elegíveis (modelo)", "Incluídos (humano)"],
                          "linhas": [[x["ano"], fmt.numero(x["n_artigos"]), fmt.numero(x["n_elegiveis"]),
                                      fmt.numero(x["n_incluidos"])] for x in por_ano]})


def bloco_multitermo(d):
    faixas = d.get("faixas") or []
    itens = [{"rotulo": f"Achado por {x['faixa']} termo(s)", "total": x["n_triados"], "parte": x["n_elegiveis"],
              "faixa": x["faixa"], "href": _href("/literatura/artigos", multi=1) if x["n_termos_min"] >= 2 else None}   # o filtro `multi` = 2 ou mais
             for x in faixas if x["n_triados"]]
    if not itens:
        return _bloco("multitermo", "Sem triagem de escopo para comparar os artigos por número de termos",
                      aviso="Rode `triar-escopo --fonte artigos`.")
    t1, tn = itens[0], itens[-1]
    titulo = (f"Artigos achados por mais termos são elegíveis com mais frequência: {_pct(t1['parte'], t1['total'])} "
              f"({t1['faixa']} termo, n = {fmt.numero(t1['total'])}) contra {_pct(tn['parte'], tn['total'])} "
              f"({tn['faixa']} termos, n = {fmt.numero(tn['total'])})"
              if len(itens) > 1 and (tn["parte"] / tn["total"]) > (t1["parte"] / t1["total"])
              else "Elegibilidade dos artigos por número de termos que os encontraram")
    graf = g.barras_proporcao(itens, titulo, "Parte de cada grupo julgada elegível pelo modelo", rotulo_parte="Elegíveis",
                              rotulo_resto="Não elegíveis")
    return _bloco("multitermo", titulo, graf, f"{fmt.numero(d.get('n_artigos'))} artigos do Scholar; elegível = opinião do modelo",
                  ["Se o artigo aparece em vários termos, é mais provável que seja central para o tema."])


# ---------------------------------------------------------------- auditoria da IA
def bloco_calibracao(d):
    nomes = {"alta": "A IA disse: confiança alta", "media": "A IA disse: confiança média", "baixa": "A IA disse: confiança baixa"}
    grupos = []
    for x in d.get("por_confianca") or []:
        n, ok = x["n_verificados"], x["n_confirmados"]
        inf, sup = est.intervalo_wilson(ok, n) if n else (None, None)
        grupos.append({"chave": x["confianca"], "rotulo": nomes.get(x["confianca"], x["confianca"]), "n": n, "concordam": ok,
                       "ic_inf": inf, "ic_sup": sup, "href": _href("/achados", confianca=x["confianca"], verificacao="confirmado")})
    if not d.get("tem_dados_humanos"):
        return _bloco("calibracao", "A IA sabe quando tem certeza? Ainda não dá para medir",
                      g.barras_calibracao(grupos, "Acerto real por nível de certeza"), aviso=AVISO_SEM_HUMANOS,
                      texto=["Compara a confiança que o modelo declarou com o que a pessoa confirmou."],
                      pares=[("Achados no total", fmt.numero(d.get("n_achados"))), ("Verificados", "0")])
    por = {x["chave"]: x for x in grupos}
    a, b = por.get("alta"), por.get("baixa")
    titulo = "Confiança do modelo e acerto real por nível"
    if a and b and a["n"] and b["n"]:
        titulo = (f"Quando o modelo diz confiança alta a pessoa confirma {_pct(a['concordam'], a['n'])}; "
                  f"quando diz baixa, {_pct(b['concordam'], b['n'])}")
    return _bloco("calibracao", titulo, g.barras_calibracao(grupos, titulo), f"{fmt.numero(d.get('n_verificados'))} achados verificados; "
                  "intervalo de Wilson 95%", ["Se a coluna 'alta' acerta bem mais que 'baixa', a confiança serve de guia para priorizar a revisão."],
                  tabela={"cabecalho": ["Confiança", "Verificados", "Confirmados", "Descartados"],
                          "linhas": [[CONF[x["confianca"]], fmt.numero(x["n_verificados"]), fmt.numero(x["n_confirmados"]),
                                      fmt.numero(x["n_descartados"])] for x in d["por_confianca"]]})


CONF = rotulos.CONFIANCA


def _n_minimo_sem_erros(limite, confianca=0.95):
    """Menor n de artigos conferidos, SEM nenhuma falsa exclusão, para o limite superior unilateral ficar abaixo de `limite`.
    Calculado com `limite_superior_binomial_exato(0, n)` (decrescente em n), por busca binária; nada fixo no código."""
    baixo, alto = 1, 1_000_000
    while baixo < alto:
        meio = (baixo + alto) // 2
        if est.limite_superior_binomial_exato(0, meio, confianca) < limite:
            alto = meio
        else:
            baixo = meio + 1
    return baixo


def _pct_taxa(x):
    """Fração -> texto em percentual com duas casas (0,0199 -> '1,99%'), para o limite não parecer igual à meta por arredondamento."""
    return f"{fmt.decimal(100 * x, 2)}%"


def bloco_falsa_exclusao(d):
    """Falsa exclusão = o modelo excluiu e a pessoa quis incluir. A taxa é sobre os artigos EXCLUÍDOS PELO MODELO que uma pessoa
    conferiu (`n_excluidos_checados`), não sobre todos os triados por humano. Um critério só de "seguro": o limite superior
    unilateral de 95% (binomial exato) abaixo da meta; o selo vem do mesmo teste (p < 0,05 equivale a limite < meta)."""
    n, k = d.get("n_excluidos_checados") or 0, d.get("n_falsas_exclusoes") or 0
    n_exc = d.get("n_excluidos") or 0
    meta = f"{100 * LIMITE_FALSA_EXCLUSAO:g}%"                                 # 0,02 -> '2%'
    if not n:
        pares = [("Artigos com veredito do modelo", fmt.numero(d.get("n_artigos_com_veredito"))),
                 ("Artigos excluídos pelo modelo", fmt.numero(n_exc)),
                 ("Excluídos conferidos por uma pessoa", "0"),
                 ("Artigos triados por humano (qualquer veredito)", fmt.numero(d.get("n_humanos")))]
        base = ["Mede quantos artigos que o modelo excluiu uma pessoa incluiu. "
                f"A meta de {meta} definida para este projeto vale para o limite superior unilateral de 95% (binomial exato)."]
        if not n_exc:
            return _bloco("falsa_exclusao", "A triagem automática é segura? Ainda não dá para medir", aviso=AVISO_SEM_HUMANOS,
                          texto=base, pares=pares)
        n_zero = _n_minimo_sem_erros(LIMITE_FALSA_EXCLUSAO)
        n_amostra = 30
        sup_amostra = est.limite_superior_binomial_exato(0, n_amostra)
        memoria = [f"Memória de cálculo: com zero erros, seriam necessários cerca de {fmt.numero(n_zero)} artigos excluídos conferidos "
                   f"para mostrar que a taxa de falsa exclusão está abaixo de {meta} (limite superior unilateral de 95%, binomial exato).",
                   f"Uma amostra de {n_amostra} conferidos sem nenhum erro só descarta falhas grosseiras: o limite superior seria "
                   f"{_pct_taxa(sup_amostra)}, ainda bem acima da meta de {meta} definida para este projeto."]
        return _bloco("falsa_exclusao", "A triagem automática é segura? Ainda não dá para medir",
                      aviso=(f"O modelo excluiu {fmt.numero(n_exc)} artigos e nenhum foi conferido por uma pessoa; a triagem automática "
                             "só pode ser considerada segura depois de conferir uma amostra aleatória dos excluídos."),
                      texto=base + memoria, pares=pares)
    taxa = k / n
    sup = est.limite_superior_binomial_exato(k, n)
    binom = est.teste_binomial_exato_unilateral(k, n, LIMITE_FALSA_EXCLUSAO, "menor")
    s = selos.selo(binom["p_valor"])
    graf = g.semaforo_limite(
        taxa, taxa, sup, LIMITE_FALSA_EXCLUSAO, "Taxa de falsa exclusão",
        f"Triagem automatizada segura: o limite superior unilateral de 95% da taxa de falsa exclusão está abaixo da meta de {meta} "
        "definida para este projeto",
        f"Atenção: a taxa de falsa exclusão observada passa da meta de {meta} definida para este projeto",
        f"Resultado inconclusivo: o limite superior unilateral de 95% fica acima da meta de {meta} definida para este projeto. "
        "A amostra de excluídos conferidos ainda é pequena para garantir segurança.", n=n, unilateral=True)
    # o fluxo cobre só quem uma pessoa triou: as decisões pendentes (sem triagem) ficam de fora
    cruz = d.get("cruzamento") or {}
    fluxos = {(o, de): v for o, linha in cruz.items() for de, v in linha.items() if v and de in ("incluir", "excluir")}
    graf2 = g.fluxo_duas_colunas([{"chave": c, "rotulo": c.capitalize()} for c in ("elegivel", "quarentena", "excluido")],
                                 [{"chave": c, "rotulo": c.capitalize()} for c in ("incluir", "excluir")],
                                 fluxos, [("excluido", "incluir")],
                                 "Veredito do modelo e decisão humana (só os artigos que uma pessoa triou)")
    texto = [s["texto"],
             f"A taxa é calculada só sobre os artigos que o modelo excluiu e uma pessoa conferiu ({fmt.numero(n)}"
             + (f" de {fmt.numero(n_exc)} excluídos" if n_exc >= n else "") + "). "
             "Só vale para todos os excluídos se a amostra conferida foi sorteada ao acaso.",
             "O fluxo abaixo cobre apenas os artigos que uma pessoa triou, de qualquer veredito do modelo."]
    return _bloco("falsa_exclusao",
                  f"{k} de {n} artigos excluídos pelo modelo e conferidos por uma pessoa foram incluídos pela pessoa",
                  graf + graf2,
                  f"Taxa de falsa exclusão = {fmt.decimal(100 * taxa, 1)}% ({k} de {n}); limite superior unilateral de 95% (binomial exato) = "
                  f"{_pct_taxa(sup)}; teste binomial exato (H₀: p ≥ {meta}) p = {fmt.decimal(binom['p_valor'], 4)}",
                  texto, selo=s,
                  pares=[("Falsas exclusões", str(k)), ("Excluídos conferidos por uma pessoa", fmt.numero(n)),
                         ("Artigos excluídos pelo modelo", fmt.numero(n_exc)),
                         ("Limite superior unilateral de 95%", _pct_taxa(sup)),
                         ("Categorias dos casos", ", ".join(f"{c}: {v}" for c, v in (d.get("por_categoria_falsa") or {}).items()) or "nenhum")])


def bloco_hipoteses(resumo, funil, falsa_exclusao=None):
    """Quadro do que cada hipotese do plano de analise ja pode ser testada e o que falta."""
    achados_h = bool(resumo.get("tem_dados_humanos_achados"))
    artigos_h = bool(resumo.get("tem_dados_humanos_artigos"))
    dois = len((funil or {}).get("provedores") or []) >= 2
    excluidos_h = bool((falsa_exclusao or {}).get("tem_excluidos_checados"))

    def estado(ok, falta):
        return "pode ser feita" if ok else "aguarda: " + falta
    linhas = [
        ["H1 região × tecnologia", estado(True, ""), "feita com achados classificados (veja a aba Adoção)"],
        ["H2 evidência e confirmação (regressão)", estado(achados_h, "verificação humana dos achados"), "fase 3 (`analises/`)"],
        ["H3 buscadores (custo por achado confirmado)", estado(achados_h and dois, "um segundo buscador usado na coleta e a verificação humana"), "fase 3"],
        ["H4 falsa exclusão da triagem", estado(excluidos_h, "conferência por uma pessoa de uma amostra sorteada dos artigos que o modelo excluiu"),
         "feita na aba Confiança na IA quando houver essa conferência"],
        ["H5 citações e posição × inclusão", estado(artigos_h, "triagem humana dos artigos"), "fase 3"],
        ["H6 tamanho do texto e falhas", estado(True, ""), "feita com a classificação (aba Operação)"],
    ]
    return _bloco("hipoteses", "O que o plano de análise já pode responder", texto=["As hipóteses que dependem de pessoas ficam à espera da verificação."],
                  tabela={"cabecalho": ["Hipótese", "Situação", "Onde"], "linhas": linhas})


# ---------------------------------------------------------------- operacao
def bloco_opacidade(d):
    linhas = [{"dominio": x["dominio"], "total": x["n_tentadas"], "bloqueadas": x["n_robots"] + x["n_http_bloqueio"],
               "inacessiveis": x.get("n_robots_inacessivel", 0), "href": _href("/chamadas", etapa="download", q=x["dominio"])}
              for x in (d.get("dominios") or [])[:40]]
    if not d.get("n_tentadas"):
        return _bloco("opacidade", "Sem downloads registrados", aviso="Nenhuma página foi baixada ainda.")
    n_inacessivel = d.get("n_robots_inacessivel") or 0
    titulo = (f"{fmt.decimal(d['pct_bloqueado'], 0)}% das {fmt.numero(d['n_tentadas'])} páginas tentadas foram proibidas pelo site "
              f"({fmt.numero(d['n_robots'])} pelo robots.txt, {fmt.numero(d['n_http_bloqueio'])} por erro 401/403/429)")
    if n_inacessivel:
        titulo += (f"; outras {fmt.numero(n_inacessivel)} não puderam ser baixadas porque o robots.txt do site estava inacessível")
    texto = ["Uma proibição explícita do site (robots.txt ou erro 401/403/429) é, em si, um dado sobre transparência: a página pode "
             "existir e não ter sido lida."]
    if n_inacessivel:
        texto.append("Já o robots.txt inacessível (erro do servidor, tempo esgotado ou falha de rede) não é decisão do site: por política "
                     "(RFC 9309) o sistema trata como proibido, tenta de novo e só conclui depois de algumas leituras. Essas páginas "
                     "ficam fora da fatia bloqueada.")
    return _bloco("opacidade", titulo, g.ranking_semaforo(linhas, "Portais com mais páginas proibidas"),
                  f"{fmt.numero(d.get('n_dominios'))} domínios; proibido pelo site = robots.txt ou HTTP 401/403/429; "
                  f"{rotulos.MOTIVOS_DOWNLOAD['robots_inacessivel']}: {fmt.numero(n_inacessivel)} páginas",
                  texto,
                  pares=[("Páginas tentadas", fmt.numero(d["n_tentadas"])), ("Lidas com sucesso", fmt.numero(d["n_ok"])),
                         (rotulos.MOTIVOS_DOWNLOAD["bloqueado_por_robots"], fmt.numero(d["n_robots"] + d["n_http_bloqueio"])),
                         (rotulos.MOTIVOS_DOWNLOAD["robots_inacessivel"], fmt.numero(n_inacessivel)),
                         ("Outros erros (404, extração…)", fmt.numero(d["n_outros"]))])


def bloco_tokens(d):
    pares = d.get("pares") or []
    if not pares:
        return _bloco("tokens", "Sem classificações para calibrar o custo", aviso="Nenhuma classificação registrada.")
    reg = d.get("regressao")
    curva = None
    if reg:
        xs = [p[0] for p in pares]
        x0, x1 = min(xs), max(xs)
        curva = [(x0, reg["intercepto"] + reg["inclinacao"] * x0), (x1, reg["intercepto"] + reg["inclinacao"] * x1)]
    marginal = (reg or {}).get("chars_por_token_marginal")
    titulo = (f"Cada token a mais custa cerca de {fmt.decimal(marginal, 1)} caracteres de texto (o sistema estima 3,4)"
              if marginal else "Caracteres enviados e tokens cobrados")
    graf = g.dispersao([(c, t) for c, t in pares], titulo, "Caracteres enviados ao modelo e tokens de entrada cobrados",
                       "Caracteres enviados", "Tokens de entrada", curva=curva)
    return _bloco("tokens", titulo, graf, f"{fmt.numero(d.get('n'))} classificações; razão mediana {fmt.decimal(d.get('razao_mediana'), 2)} caracteres por token",
                  ["A razão média fica abaixo da marginal porque o prompt fixo também consome tokens; a marginal é a que vale para estimar o custo de um texto a mais."],
                  pares=[("Razão mediana (caracteres/token)", fmt.decimal(d.get("razao_mediana"), 2)),
                         ("Razão marginal (regressão)", fmt.decimal(marginal, 2)),
                         ("R² da regressão", fmt.decimal((reg or {}).get("r2"), 3))])


def bloco_tamanho(d):
    pares = [(p[0], p[1]) for p in d.get("pares") or [] if p[2]]
    if not pares:
        return _bloco("tamanho", "Sem classificações para comparar tamanho e achados", aviso="Nenhuma classificação válida.")
    tr = d["truncamento"]["truncados"]
    inteiros = d["truncamento"]["integros"]
    titulo = (f"Textos acima de {fmt.numero(LIMITE_TEXTO_MODELO)} caracteres são cortados: {fmt.numero(tr['n'])} de "
              f"{fmt.numero(d['n'])} classificações")
    graf = g.dispersao(pares, titulo, "Tamanho do texto enviado e número de achados por classificação", "Caracteres enviados",
                       "Achados na página", corte_x=LIMITE_TEXTO_MODELO, rotulo_corte="limite de envio", log_x=True)
    return _bloco("tamanho", titulo, graf, f"{fmt.numero(d['n'])} classificações; JSON inválido: {fmt.numero(d['n_json_invalido'])}",
                  ["Mostra se o modelo deixa de achar coisas ou erra o formato quando o texto é muito grande."],
                  tabela={"cabecalho": ["Tamanho", "Classificações", "JSON inválido", "Achados por mil caracteres"],
                          "linhas": [[x["faixa"], fmt.numero(x["n"]), fmt.numero(x["n_json_invalido"]),
                                      fmt.decimal(x["achados_por_mil_chars"], 2)] for x in d.get("faixas") or []]},
                  pares=[("Cortadas (truncadas)", fmt.numero(tr["n"])), ("Íntegras", fmt.numero(inteiros["n"]))])
