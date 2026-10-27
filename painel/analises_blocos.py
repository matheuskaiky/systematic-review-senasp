"""Blocos da pagina /analises: cada bloco junta um grafico (SVG do servidor), um titulo que CONTA A CONCLUSAO, uma frase em
linguagem simples (modo gestor) e a memoria de calculo (modo pesquisador, dentro de um <details>).

Tudo aqui e funcao pura: recebe os dicionarios que `adaptadores/leitura_analises.py` devolve e devolve blocos. Nao toca no
banco. Regras do plano de visualizacao: nenhum numero sem a quantidade de casos, nenhum resultado que dependa de revisao
humana e apresentado como confirmado quando ainda nao ha verificacao, e cada barra ou celula leva aos registros."""
from urllib.parse import urlencode

from markupsafe import Markup

from dominio import estatistica as est
from dominio.auditoria_negativos import amostra_minima_sem_erros
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


def _bloco(id_, titulo, grafico=None, subtitulo="", texto=(), selo=None, aviso=None, pares=(), tabela=None, link=None, motivos=()):
    """`grafico` ja e HTML seguro vindo de `graficos_analises` (por isso Markup). `texto` = paragrafos simples (escapados).
    `motivos` = [{"chave": "bloqueado_por_robots" | "robots_inacessivel", "n": int}]: as razoes de bloqueio pelo robots.txt, mostradas
    com selo proprio (cor, glifo e texto; ver `rotulos.MOTIVOS_DOWNLOAD`)."""
    return {"id": id_, "titulo": titulo, "subtitulo": subtitulo, "grafico": Markup(grafico) if grafico else None,
            "texto": [t for t in texto if t], "selo": selo, "aviso": aviso, "pares": list(pares), "tabela": tabela, "link": link,
            "motivos": list(motivos)}


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
    if not d.get("n_achados"):
        titulo = "Ainda não há achados para mapear"
    elif d.get("base") == "confirmados":
        titulo = (f"{len(em_uso)} de {total} UFs com ao menos um achado confirmado por revisor no estágio “em uso” "
                  f"(estágio do revisor quando ele o registrou; nos demais, o do modelo)")
    else:
        titulo = (f"{len(em_uso)} de {total} UFs com ao menos um achado no estágio “em uso” "
                  f"(estágio do revisor quando ele o registrou; nos demais, o do modelo)")
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
    return amostra_minima_sem_erros(limite, confianca)


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


def bloco_prontidao(d):
    """Prontidão metodológica: para cada análise travada por falta de decisão humana (H2, H5 e a auditoria dos negativos), o que já
    foi rotulado contra o mínimo que o script exige, uma barra de progresso, a situação ("destravado" ou "faltam N") e onde agir.
    `d` = `analise_prontidao()`. O bloco traz `cartoes` (lidos por `_prontidao.html`, também na página inicial)."""
    h2, h5, au = d.get("h2") or {}, d.get("h5") or {}, d.get("auditoria") or {}

    def cartao(id_, titulo, trava, condicao, href, rotulo_link, comando=None, nota=None, situacao=None):
        condicoes = [{**c, "texto": f"{fmt.numero(c['n'])} / {fmt.numero(c['minimo'])}",
                      "barra": Markup(g.barra_progresso(c["n"], c["minimo"], c["rotulo"]))} for c in trava.get("condicoes") or []]
        if situacao:
            status, classe = situacao
        elif trava.get("destravado"):
            status, classe = "destravado", "ok"
        else:
            status, classe = f"faltam {fmt.numero(trava.get('faltam'))}", "neutro"
        return {"id": id_, "titulo": titulo, "condicao": condicao, "condicoes": condicoes, "status": status, "classe": classe,
                "destravado": bool(trava.get("destravado")), "faltam": trava.get("faltam", 0), "href": href, "rotulo_link": rotulo_link,
                "comando": comando, "nota": nota}

    c2, c5, ca = h2.get("condicoes") or [{}, {}], h5.get("condicoes") or [{}, {}], au.get("condicoes") or [{}]
    rara = min(h2.get("n_confirmados", 0), h2.get("n_descartados", 0))
    cartoes = [
        cartao("h2", "H2: regressão logística da confirmação", h2,
               f"{fmt.numero(c2[0].get('n'))} achados verificados de {fmt.numero(c2[0].get('minimo'))} necessários; classe minoritária "
               f"{fmt.numero(rara)} de {fmt.numero(c2[1].get('minimo'))} necessários "
               f"({fmt.numero(h2.get('n_confirmados'))} confirmados, {fmt.numero(h2.get('n_descartados'))} descartados).",
               "/revisao/achados", "Verificar achados",
               nota="Faltam, no mínimo, tantos achados quanto a maior das duas faltas: um mesmo achado pode contar nas duas."),
        cartao("h5", "H5: citações e posição × inclusão", h5,
               f"{fmt.numero(c5[0].get('n'))} artigos com decisão de triagem de {fmt.numero(c5[0].get('minimo'))}; "
               f"{fmt.numero(h5.get('n_incluir'))} incluídos e {fmt.numero(h5.get('n_excluir'))} excluídos (mínimo {fmt.numero(c5[1].get('minimo'))} de cada).",
               "/literatura/triagem", "Triar artigos"),
        cartao("auditoria", "Auditoria dos negativos do modelo", au,
               f"{fmt.numero(ca[0].get('n'))} páginas negativas auditadas de {fmt.numero(ca[0].get('minimo'))}, "
               f"do universo de {fmt.numero(au.get('n_universo'))}.",
               None, None, comando="python main.py auditoria-negativos-modelo --amostra %d" % (ca[0].get("minimo") or 0),
               nota=("O mínimo vale se nenhuma aplicação perdida for encontrada; achando alguma, a meta de 5% exige mais páginas."),
               situacao=(("mínimo atingido, mas há aplicação perdida: meta não provada", "alerta selo-longo")
                         if ca[0].get("destravado") and au.get("n_perdidas") else None)),
    ]
    abertas = [c for c in cartoes if not c["destravado"]]
    titulo = ("Os três mínimos de rotulagem humana estão atingidos" if not abertas else
              f"{len(abertas)} de 3 análises ainda dependem de rotulagem humana")
    return {**_bloco("prontidao", titulo, subtitulo="Cada barra compara o que já foi rotulado por uma pessoa com o mínimo que o script da análise exige.",
                     texto=["Para rotular só o necessário, com uma pequena folga: python main.py rotulagem-modelo --listar (mostra as contagens) e, "
                            "depois, python main.py rotulagem-modelo (gera as planilhas)."]),
            "cartoes": cartoes}


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


def bloco_concordancia_achados(d):
    """Concordância entre revisores humanos nos achados (kappa de Cohen sobre confirmado x descartado), só com revisão
    independente. Usa a régua de faixas do projeto; a tabela traz todos os pares. Sem revisão independente, explica como obter."""
    pares_d = d.get("pares") or []
    if not d.get("tem_dados") or not pares_d:
        return _bloco("concordancia_achados", "Dois revisores chegam à mesma decisão? Ainda não dá para medir",
                      aviso="Aguardando revisão independente: este bloco só aparece com as decisões de dois ou mais revisores sobre os mesmos achados.",
                      texto=["Mede o quanto duas pessoas concordam, além do que o acaso explicaria, em confirmar ou descartar um achado "
                             "(kappa de Cohen). Cada revisor decide sozinho, sem ver a decisão do outro.",
                             "Como obter: cada revisor marca a aba Achados da planilha exportada e importa com "
                             "python main.py achados-importar <arquivo> --independente. Essa revisão só entra no histórico e não muda a decisão final do achado."],
                      pares=[("Revisores com revisão independente", fmt.numero(d.get("n_revisores"))),
                             ("Achados revisados de forma independente", fmt.numero(d.get("n_achados_revisados")))])
    p = pares_d[0]
    kappa = p.get("kappa")
    ic = (p.get("ic_inferior"), p.get("ic_superior"))
    nomes = f"{p['revisor_a']} e {p['revisor_b']}"
    if kappa is None:
        titulo = f"{nomes} decidiram igual em todos os {fmt.numero(p['n'])} achados em comum, mas o kappa não pode ser calculado"
        graf = g.regua_kappa(None)
    else:
        titulo = f"{nomes} concordam de forma {p['interpretacao']} (κ = {fmt.decimal(kappa, 2)}) em {fmt.numero(p['n'])} achados"
        graf = g.regua_kappa(kappa, ic, titulo)
    texto = [f"Em {fmt.numero(p['n'])} achados revisados por {nomes}, os dois decidiram igual em {fmt.decimal(p['concordancia_pct'], 0)}% "
             f"(confirmar ou descartar). Quando o desfecho é muito mais comum que o outro, o kappa pode ser baixo mesmo com concordância alta; "
             "por isso as duas medidas aparecem juntas."]
    if kappa is None:
        texto.append("Sem nenhuma discordância e com um só desfecho (por exemplo, todos confirmados), o acaso esperado é 100% e a conta "
                     "do kappa não tem solução. Não é um defeito dos revisores.")
    if p["n"] < 30:
        texto.append("Com menos de 30 achados em comum o intervalo do kappa é muito largo: trate o valor como indício, não como medida firme.")
    if d.get("n_discordancias"):
        texto.append(f"{fmt.numero(d['n_discordancias'])} achado(s) com decisões diferentes esperam a reunião de consenso (aba Discordancias_achados da exportação).")
    linhas = [[f"{x['revisor_a']} × {x['revisor_b']}", fmt.numero(x["n"]), f"{fmt.decimal(x['concordancia_pct'], 1)}%",
               fmt.decimal(x["kappa"], 2) if x["kappa"] is not None else "—", x["interpretacao"] or "—",
               f"{fmt.decimal(x['concordancia_status_pct'], 1)}%"] for x in pares_d]
    return _bloco("concordancia_achados", titulo, graf,
                  f"{fmt.numero(d.get('n_achados_revisados'))} achados com revisão independente; desfecho = confirmado (qualquer status final "
                  "diferente de descartado) ou descartado; intervalo de 95% aproximado",
                  texto, pares=[("Revisores", fmt.numero(d.get("n_revisores"))), ("Pares de revisores", fmt.numero(d.get("n_pares"))),
                                ("Achados em comum no par mostrado", fmt.numero(p["n"])),
                                ("Mesmo status final (par mostrado)", f"{fmt.decimal(p['concordancia_status_pct'], 1)}%")],
                  tabela={"cabecalho": ["Par de revisores", "Achados em comum", "Concordância", "Kappa", "Leitura", "Mesmo status final"],
                          "linhas": linhas})


def bloco_auditoria_negativos(d):
    """Falsos negativos do modelo: páginas que ele deixou SEM achado e que uma pessoa conferiu. Taxa com intervalo de Wilson, limite
    superior exato e o tamanho de amostra necessário com zero erros (calculado, não fixo). Sem conferência, pede a amostra."""
    n, k = d.get("n_auditadas") or 0, d.get("n_perdidas") or 0
    metas = d.get("metas") or []
    por_meta = {m["meta"]: m for m in metas}
    rotulo_meta = {m["meta"]: f"{100 * m['meta']:g}%" for m in metas}
    universo = d.get("n_universo") or 0
    if not n:
        n_amostra = 30
        sup30 = est.limite_superior_binomial_exato(0, n_amostra)
        if not universo:
            return _bloco("auditoria_negativos", "O modelo deixa passar aplicações? Ainda não há páginas sem achado para conferir",
                          aviso="Aguardando conferência humana: não há classificações sem achado sobre o texto da página.",
                          texto=["Este bloco mede, com uma amostra sorteada, quantas páginas que o modelo deixou sem achado tinham uma "
                                 "aplicação de IA."])
        frases = [f"{fmt.numero(m['n_sem_erros'])} páginas para mostrar que a taxa está abaixo de {rotulo_meta[m['meta']]}" for m in metas]
        texto = ["Mede quantas páginas que o modelo deixou SEM achado tinham, na verdade, uma aplicação de IA (falso negativo). É o que "
                 "diz se o levantamento deixou de ver algo, e só uma pessoa lendo as páginas pode responder.",
                 "Quantas conferir: se a pessoa não achar nenhuma aplicação perdida, bastam " + " e ".join(frases) + " (limite superior de 95%, "
                 f"binomial exato). Com só {n_amostra} páginas e nenhum erro, a taxa ainda poderia chegar a {_pct_taxa(sup30)}.",
                 f"Como obter: python main.py auditoria-negativos-modelo --amostra {metas[0]['n_sem_erros'] if metas else n_amostra}; a pessoa "
                 "preenche o CSV (1 = havia uma aplicação que o modelo não marcou, 0 = o modelo acertou) e importa com "
                 "python main.py auditoria-negativos-importar <arquivo>."]
        return _bloco("auditoria_negativos", "O modelo deixa passar aplicações? Aguardando conferência humana",
                      aviso="Aguardando conferência humana: nenhuma página sem achado foi conferida por uma pessoa ainda.",
                      texto=texto,
                      pares=[("Páginas sem achado (texto da página)", fmt.numero(universo)), ("Conferidas por uma pessoa", "0")]
                      + [(f"Amostra com zero erros para a meta de {rotulo_meta[m['meta']]}", fmt.numero(m["n_sem_erros"])) for m in metas])
    taxa, sup = k / n, d["limite_superior"]
    inf_w, sup_w = d["ic_wilson"]
    meta0 = metas[0]["meta"] if metas else 0.05
    graf = g.semaforo_limite(
        taxa, taxa, sup, meta0, "Taxa de falso negativo do modelo",
        f"O limite superior unilateral de 95% está abaixo da meta de {rotulo_meta.get(meta0, '5%')}: o modelo perde menos que isso das páginas sem achado",
        f"Atenção: a taxa observada de aplicações perdidas passa da meta de {rotulo_meta.get(meta0, '5%')}",
        f"Resultado inconclusivo: o limite superior de 95% fica acima da meta de {rotulo_meta.get(meta0, '5%')}. A amostra conferida ainda é pequena.",
        n=n, unilateral=True)
    texto = [f"Uma pessoa leu {fmt.numero(n)} páginas que o modelo deixou sem achado e encontrou uma aplicação de IA perdida em {fmt.numero(k)}. "
             f"A taxa verdadeira, com 95% de confiança, é no máximo {_pct_taxa(sup)} (intervalo de Wilson: {_pct_taxa(inf_w)} a {_pct_taxa(sup_w)})."]
    est_p = d.get("estimativa_paginas_perdidas")
    if est_p and universo:
        texto.append(f"Se a amostra foi sorteada, isso equivale a cerca de {fmt.numero(est_p['pontual'])} das {fmt.numero(universo)} páginas "
                     f"sem achado (entre {fmt.numero(est_p['minimo'])} e {fmt.numero(est_p['maximo'])}).")
    linhas = []
    for m in metas:
        if m["abaixo_da_meta"]:
            situ = "meta atingida"
        elif k == 0:
            situ = f"ainda não prova; faltam {fmt.numero(m['faltam_sem_erros'])} páginas sem erro"
        else:
            situ = "ainda não prova (houve aplicações perdidas)"
        linhas.append([f"Abaixo de {rotulo_meta[m['meta']]}", _pct_taxa(sup), fmt.numero(m["n_sem_erros"]), situ])
    por_tec = ", ".join(f"{_tec(x['tecnologia'])}: {x['n']}" for x in d.get("por_tecnologia") or []) or "nenhuma"
    return _bloco("auditoria_negativos",
                  f"{k} de {n} páginas sem achado conferidas tinham uma aplicação que o modelo não marcou ({_pct_taxa(taxa)})",
                  graf, f"Falso negativo = {_pct_taxa(taxa)} ({k} de {n}); limite superior unilateral de 95% (binomial exato) = {_pct_taxa(sup)}",
                  texto, pares=[("Páginas conferidas", fmt.numero(n)), ("Aplicações perdidas", fmt.numero(k)),
                                ("Páginas sem achado no banco", fmt.numero(universo)),
                                ("Ainda sem conferência", fmt.numero(d.get("n_restantes"))), ("Perdidas por tecnologia", por_tec)],
                  tabela={"cabecalho": ["Meta", "Limite superior de 95%", "Amostra com zero erros", "Situação"], "linhas": linhas})


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
                         (rotulos.MOTIVOS_DOWNLOAD["bloqueado_por_robots"], fmt.numero(d["n_robots"])),
                         ("Proibido pelo site (erro HTTP 401, 403 ou 429)", fmt.numero(d["n_http_bloqueio"])),
                         (rotulos.MOTIVOS_DOWNLOAD["robots_inacessivel"], fmt.numero(n_inacessivel)),
                         ("Outros erros (404, extração…)", fmt.numero(d["n_outros"]))],
                  motivos=[{"chave": "bloqueado_por_robots", "n": d["n_robots"]}, {"chave": "robots_inacessivel", "n": n_inacessivel}])


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


ROTULOS_NAO_VERIFICAVEIS = {
    "proibido_pelo_site": "Proibido pelo site (robots.txt lido e proíbe)",
    "nao_verificavel_robots": "Não verificável (robots.txt inacessível, falha repetida)",
    "falha_definitiva_404": "Página inexistente (erro 404 ou 410)",
    "outras_falhas": "Outras falhas (401, 403, rede, leitura…)",
}


def bloco_nao_verificaveis(d):
    """Páginas que a coleta não conseguiu ver, pela ÚLTIMA tentativa de cada URL. Separa o que o site proibiu do que apenas não
    pôde ser verificado (robots.txt ilegível), da página que não existe mais e do resto."""
    n_url = d.get("n_urls_tentadas") or 0
    classes = d.get("classes") or {}
    if not n_url:
        return _bloco("nao_verificaveis", "Sem downloads registrados", aviso="Nenhuma página foi baixada ainda.")

    def n(c):
        return (classes.get(c) or {}).get("n_paginas") or 0
    nv = n("nao_verificavel_robots")
    titulo = (f"{fmt.numero(nv)} {'página não pôde' if nv == 1 else 'páginas não puderam'} ser verificadas: o robots.txt do site "
              f"estava inacessível, mesmo depois de várias tentativas" if nv
              else "Nenhuma página ficou sem verificação por robots.txt inacessível")
    texto = ["Não verificável não é o mesmo que proibido pelo site. Nestes casos o robots.txt (o arquivo em que o site diz o que os "
             "programas podem ler) não respondeu: deu erro do servidor, demorou demais ou a rede falhou. Não sabemos o que o site decidiu.",
             "Por decisão do projeto, seguimos a regra da RFC 9309: robots.txt ilegível conta como proibido, o download é tentado de novo e "
             "só depois se desiste. Por isso essas páginas ficaram fora da coleta, e o levantamento pode ter deixado de ver conteúdo nelas."]
    if n("falha_definitiva_404"):
        texto.append(f"Já as {fmt.numero(n('falha_definitiva_404'))} páginas com erro 404 ou 410 não existem mais ou mudaram de endereço; "
                     "é uma falha da página, não do site nem da coleta.")
    top = (classes.get("nao_verificavel_robots") or {}).get("dominios") or []
    pares = [("Páginas com download tentado (última tentativa de cada uma)", fmt.numero(n_url)),
             ("Baixadas com sucesso", fmt.numero(d.get("n_ok")))]
    pares += [(ROTULOS_NAO_VERIFICAVEIS[c], fmt.numero(n(c))) for c in ROTULOS_NAO_VERIFICAVEIS]
    if top:
        pares.append(("Domínios com mais páginas não verificadas", ", ".join(f"{x['dominio']} ({fmt.numero(x['n'])})" for x in top[:5])))
    linhas = [[ROTULOS_NAO_VERIFICAVEIS[c], fmt.numero(n(c)), fmt.numero((classes.get(c) or {}).get("n_dominios")),
               fmt.numero((classes.get(c) or {}).get("n_ufs"))] for c in ROTULOS_NAO_VERIFICAVEIS]
    return _bloco("nao_verificaveis", titulo, None,
                  f"Última tentativa de download de cada uma das {fmt.numero(n_url)} páginas; "
                  "não verificável = robots.txt inacessível em 3 leituras ou em ao menos 2 tentativas",
                  texto, pares=pares, tabela={"cabecalho": ["Situação", "Páginas", "Domínios", "UFs"], "linhas": linhas},
                  link={"href": _href("/chamadas", etapa="download", resultado="robots_inacessivel"),
                        "rotulo": "Ver as chamadas de download com robots.txt inacessível"},
                  motivos=[{"chave": "bloqueado_por_robots", "n": n("proibido_pelo_site")},
                           {"chave": "robots_inacessivel", "n": nv}])
