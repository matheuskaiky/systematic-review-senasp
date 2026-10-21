"""Rotulagem mínima: escolhe, só pelo repositório (leitura), o que a pessoa precisa rotular para destravar H2, H5 e a auditoria dos
negativos do modelo, e monta os textos que acompanham as planilhas. Não grava nada no banco nem escreve arquivos: a escrita das
planilhas fica em `aplicacao/exportacao.py` e no `main.py`.

As regras de seleção (estratos, sorteios, folga) vivem em `dominio/rotulagem.py`; os mínimos, em `dominio/prontidao.py`."""
from dominio import auditoria_negativos as AN, prontidao as P, rotulagem as R
from dominio.relevancia import pontuar_relevancia

ARQ_ACHADOS = "rotulagem_achados.xlsx"
ARQ_TRIAGEM = "rotulagem_triagem.xlsx"
ARQ_TRIAGEM_H4 = "rotulagem_triagem_h4.xlsx"
ARQ_AUDITORIA = "auditoria_negativos.csv"
ARQ_LEIAME = "LEIA-ME.txt"

# Colunas da aba Achados que a pessoa lê (na frente) e que preenche (logo depois); as demais seguem na ordem da exportação.
COLUNAS_LER_ACHADOS = ("achado_id", "estrato", "uf", "tecnologia", "status_reportado", "evidencia", "evidencia_confere", "confianca",
                       "origem_texto", "url")
COLUNAS_PREENCHER_ACHADOS = ("verificado", "status_final", "verificado_por", "observacao")
# Colunas auxiliares que não existem na exportação; os importadores ignoram colunas que não conhecem.
EXTRAS_ACHADOS = ("fonte_oficial_efetiva",)
RITMO_MIN = {"achado": 2, "artigo": 1, "pagina": 4}      # minutos por linha, SUPOSTOS só para a estimativa; ajuste ao seu ritmo


def _completo_para_h2(a):
    """Achado que a regressão consegue usar: os três preditores binários preenchidos (a mesma regra de `analises/h2_logistica.py`)."""
    return all(a.get(c) is not None for c in ("evidencia_confere", "evidencia_cita_tecnologia", "fonte_oficial_efetiva"))


def _contar_estratos(selecao):
    contagem = {}
    for _, _, descricao in selecao:
        contagem[descricao] = contagem.get(descricao, 0) + 1
    return sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0]))


def _linha_achado(a, descricao):
    linha = {k: v for k, v in a.items() if k not in EXTRAS_ACHADOS}
    linha["estrato"] = descricao
    ordem = [c for c in COLUNAS_LER_ACHADOS if c in linha] + [c for c in COLUNAS_PREENCHER_ACHADOS if c in linha]
    return {**{c: linha[c] for c in ordem}, **{c: v for c, v in linha.items() if c not in ordem}}


def _linha_artigo(a, descricao):
    linha = {"artigo_id": a["artigo_id"], "estrato": descricao, "titulo": a["titulo"], "resumo": a.get("snippet"), "ano": a.get("ano"),
             "link": a.get("link"), "citacoes": a.get("citacoes"), "triagem_llm": a.get("triagem_llm"), "decisao": "pendente",
             "motivo": a.get("motivo"), "confirmado_em_base": a.get("confirmado_em_base"), "link_confirmado": a.get("link_confirmado"),
             "revisor": a.get("revisor"), "revisado_em": a.get("revisado_em"),
             "decisao_texto_completo": a.get("decisao_texto_completo"), "motivo_texto_completo": a.get("motivo_texto_completo")}
    return linha


def _planejar_achados(repo, folga, semente, aleatoria):
    todos = repo.achados_para_rotulagem()
    completos = [a for a in todos if _completo_para_h2(a)]
    verificados = [a for a in completos if a.get("verificado") == 1]
    descartados = sum(1 for a in verificados if a.get("status_final") == "descartado")
    trava = P.prontidao_h2(len(verificados) - descartados, descartados)
    pool = [a for a in completos if a.get("verificado") != 1]
    pedir = min(R.com_folga(trava["faltam"], folga), len(pool))
    selecao = R.selecionar_achados(pool, pedir, semente, aleatoria)
    return {"trava": trava, "n_verificados": len(verificados), "n_confirmados": len(verificados) - descartados, "n_descartados": descartados,
            "n_sem_preditor": sum(1 for a in todos if not _completo_para_h2(a) and a.get("verificado") != 1),
            "pool": len(pool), "faltam": trava["faltam"], "pedir": pedir, "aleatoria": aleatoria, "estratos": _contar_estratos(selecao),
            "linhas": [_linha_achado(a, d) for a, _, d in selecao], "ids": [a["achado_id"] for a, _, _ in selecao]}


def _planejar_triagem(repo, folga, semente, h4, meta_h4):
    artigos = repo.artigos_para_rotulagem()
    decididos = [a for a in artigos if a.get("decisao") in ("incluir", "excluir")]
    n_inc = sum(1 for a in decididos if a["decisao"] == "incluir")
    trava = P.prontidao_h5(n_inc, len(decididos) - n_inc)
    pool = []
    for a in artigos:
        if a.get("decisao") not in ("incluir", "excluir"):
            pool.append({**a, "nivel": R.nivel_de_relevancia(pontuar_relevancia(a["titulo"], a.get("snippet"), a.get("autores_publicacao"), a.get("link")))})
    pedir = min(R.com_folga(trava["faltam"], folga), len(pool))
    base, _ = R.selecionar_artigos(pool, pedir, 0, semente)
    r = {"trava": trava, "n_incluir": n_inc, "n_excluir": len(decididos) - n_inc, "pool": len(pool), "faltam": trava["faltam"],
         "pedir": pedir, "estratos": _contar_estratos(base), "linhas": [_linha_artigo(a, d) for a, _, d in base], "h4": None}
    if h4:
        ja = R.n_excluidos_checados(artigos)
        minimo = R.minimo_h4(meta_h4)
        na_base = sum(1 for a, _, _ in base if R.status_do_modelo(a) == "excluido")
        faltam = max(minimo - ja - na_base, 0)
        _, extra = R.selecionar_artigos(pool, pedir, faltam, semente)
        r["h4"] = {"meta": meta_h4, "minimo": minimo, "ja_checados": ja, "na_base": na_base, "faltam": faltam, "pedir": len(extra),
                   "pool_excluidos": sum(1 for a in pool if R.status_do_modelo(a) == "excluido"), "estratos": _contar_estratos(extra),
                   "linhas": [_linha_artigo(a, d) for a, _, d in extra]}
    return r


def _planejar_auditoria(repo, semente):
    resumo = repo.resumo_auditoria_negativos()
    trava = P.prontidao_auditoria(resumo["n_auditadas"], resumo["n_universo"], resumo["n_perdidas"])
    candidatos = repo.candidatos_auditoria_negativos()
    amostra = AN.amostrar(candidatos, trava["faltam"], semente)
    return {"trava": trava, "n_auditadas": resumo["n_auditadas"], "n_perdidas": resumo["n_perdidas"], "n_universo": resumo["n_universo"],
            "minimo": trava["condicoes"][0]["minimo"], "pool": len(candidatos), "faltam": trava["faltam"], "pedir": len(amostra),
            "linhas": [{c: l.get(c) for c in AN.COLUNAS_AMOSTRA} for l in amostra]}


def planejar(repo, folga=R.FOLGA_PADRAO, semente=None, semente_auditoria=None, aleatoria=False, h4=False, meta_h4=0.05,
             pasta="outputs/rotulagem", sufixo_banco=""):
    """Plano completo, sem gravar nada: {achados, triagem, auditoria, parametros}. Cada parte traz a trava (`dominio.prontidao`),
    quanto falta, quantas linhas pedir (já com a folga), o tamanho do conjunto de onde sai a seleção (`pool`) e as `linhas`.
    Trava já destravada: `pedir` = 0 e nenhuma linha. A auditoria usa a mesma semente e a mesma função de sorteio de
    `auditoria-negativos-modelo`, sem folga (o mínimo vale com zero erros: qualquer erro exige uma amostra maior, não uma folga)."""
    semente = semente or R.SEMENTE_PADRAO
    plano = {"achados": _planejar_achados(repo, folga, semente, aleatoria),
             "triagem": _planejar_triagem(repo, folga, semente, h4, meta_h4),
             "auditoria": _planejar_auditoria(repo, semente_auditoria or AN.SEMENTE_PADRAO),
             "parametros": {"folga": folga, "semente": semente, "semente_auditoria": semente_auditoria or AN.SEMENTE_PADRAO,
                            "aleatoria": aleatoria, "h4": h4, "meta_h4": meta_h4, "pasta": str(pasta),
                            "sufixo_banco": sufixo_banco}}
    return plano


def arquivos_do_plano(plano):
    """[(nome do arquivo, número de linhas)] que o plano gera (só travas fechadas e com linhas)."""
    saida = []
    if plano["achados"]["linhas"]:
        saida.append((ARQ_ACHADOS, len(plano["achados"]["linhas"])))
    if plano["triagem"]["linhas"]:
        saida.append((ARQ_TRIAGEM, len(plano["triagem"]["linhas"])))
    if plano["triagem"]["h4"] and plano["triagem"]["h4"]["linhas"]:
        saida.append((ARQ_TRIAGEM_H4, len(plano["triagem"]["h4"]["linhas"])))
    if plano["auditoria"]["linhas"]:
        saida.append((ARQ_AUDITORIA, len(plano["auditoria"]["linhas"])))
    return saida


# ---------------------------------------------------------------- textos
def resumo_texto(plano):
    """Tabela de resumo para o terminal: uma linha por trava, com o que falta e quantas linhas serão geradas."""
    a, t, au = plano["achados"], plano["triagem"], plano["auditoria"]
    linhas = []

    def trava(nome, ja, falta, linhas_n, extra=""):
        if falta <= 0:
            return f"  {nome:<14} {ja:<48} já destravado"
        return f"  {nome:<14} {ja:<48} faltam {falta:<4} -> {linhas_n} linha(s){extra}"
    linhas.append(trava("H2 achados", f"{a['n_verificados']} verificados ({a['n_confirmados']} confirm., {a['n_descartados']} descart.)",
                        a["faltam"], a["pedir"], f"  [{'aleatória' if a['aleatoria'] else 'enriquecida'}; conjunto de {a['pool']}]"))
    linhas.append(trava("H5 triagem", f"{t['n_incluir'] + t['n_excluir']} decisões ({t['n_incluir']} incluir, {t['n_excluir']} excluir)",
                        t["faltam"], t["pedir"], f"  [conjunto de {t['pool']}]"))
    if t["h4"]:
        h = t["h4"]
        linhas.append(trava("H4 excluídos", f"{h['ja_checados']} checados + {h['na_base']} na planilha de triagem",
                            h["faltam"], h["pedir"], f"  [meta {100 * h['meta']:g}%: {h['minimo']} com zero falsas exclusões; sorteio entre {h['pool_excluidos']}]"))
    linhas.append(trava("Auditoria", f"{au['n_auditadas']} páginas auditadas de {au['minimo']} (universo {au['n_universo']})",
                        au["faltam"], au["pedir"], f"  [conjunto de {au['pool']}]"))
    return linhas


def estimativa_horas(plano):
    """Minutos totais pelo ritmo SUPOSTO de `RITMO_MIN` (só uma ordem de grandeza)."""
    a, t, au = plano["achados"], plano["triagem"], plano["auditoria"]
    n_h4 = len(t["h4"]["linhas"]) if t["h4"] else 0
    return (len(a["linhas"]) * RITMO_MIN["achado"] + (len(t["linhas"]) + n_h4) * RITMO_MIN["artigo"] + len(au["linhas"]) * RITMO_MIN["pagina"])


def leiame_achados(plano, status_validos):
    """Linhas da aba LEIA-ME da planilha de achados."""
    a = plano["achados"]
    modo = ("AMOSTRA ALEATÓRIA SIMPLES (--aleatoria): serve para estimar a precisão do modelo."
            if a["aleatoria"] else
            "AMOSTRA ENRIQUECIDA para achados com provável erro: serve à regressão logística (H2), NÃO para estimar a precisão global do modelo.")
    linhas = ["ROTULAGEM DOS ACHADOS (destrava a regressão logística, H2)", "",
              f"Linhas: {len(a['linhas'])} (faltam {a['faltam']} para o mínimo, mais a folga de {plano['parametros']['folga']:g}%).",
              f"Hoje: {a['n_verificados']} achados verificados por pessoa, {a['n_confirmados']} confirmados e {a['n_descartados']} descartados.", "", modo, ""]
    if a["aleatoria"]:
        linhas += ["Os achados já verificados ficam de fora; se a verificação anterior não foi sorteada, a amostra aleatória vale só para o que falta.", ""]
    else:
        linhas += ["Por que enriquecida: se quase todos os achados do modelo estão certos, uma amostra sorteada traria poucos descartados e a classe minoritária",
                   "da regressão nunca chegaria ao mínimo. Aqui entram os achados com evidência que não confere, que não cita a tecnologia, de texto só de",
                   "snippet e de confiança baixa (até 70% das linhas) e o resto é sorteio, por UF e tecnologia, do que parece certo.",
                   "Por isso a taxa de acerto desta planilha NÃO representa o modelo inteiro. Para a precisão global, gere uma amostra à parte com --aleatoria.", ""]
    linhas += ["COMO PREENCHER (uma linha por achado)",
               "  verificado       1 (as linhas com verificado vazio ou 0 são ignoradas na importação)",
               f"  status_final     um de: {', '.join(status_validos)}  ('descartado' = o achado está errado)",
               "  verificado_por   seu nome",
               "  observacao       opcional",
               "A coluna estrato diz por que a linha foi escolhida e é ignorada na importação. Não altere achado_id nem verificado_em.", "",
               "DEPOIS DE SALVAR", f"  python main.py achados-importar {plano['parametros']['pasta']}/{ARQ_ACHADOS}{plano['parametros']['sufixo_banco']}",
               "  (sem --independente: --independente só grava no histórico e NÃO conta para a trava)"]
    return linhas


def leiame_triagem(plano, h4=False):
    """Linhas da aba LEIA-ME da planilha de triagem (`h4=True`: a planilha extra só com excluídos pelo modelo)."""
    t = plano["triagem"]
    if h4:
        h = t["h4"]
        return ["TRIAGEM EXTRA: ARTIGOS QUE O MODELO EXCLUIU (mede a falsa exclusão, H4)", "",
                f"Linhas: {len(h['linhas'])}. Meta: limite superior de 95% abaixo de {100 * h['meta']:g}%, o que pede {h['minimo']} artigos excluídos pelo modelo "
                "conferidos por pessoa SEM nenhuma falsa exclusão (calculado por dominio.auditoria_negativos.amostra_minima_sem_erros).",
                f"Já conferidos: {h['ja_checados']}; na planilha de triagem básica: {h['na_base']}; aqui: {len(h['linhas'])}.", "",
                "Estes artigos foram sorteados ao acaso entre os excluídos pelo modelo (a mesma ordem sorteada da planilha básica, que usa os primeiros), então",
                "a taxa de falsa exclusão vale para os excluídos. Decida pelo título e resumo, SEM olhar o motivo do modelo se puder.", "",
                "COMO PREENCHER: decisao = incluir ou excluir (pendente = deixar para depois), motivo (obrigatório ao excluir), revisor = seu nome.",
                "Achando um artigo que deveria ser incluído, a meta não é provada com este tamanho: gere mais.", "",
                f"DEPOIS DE SALVAR: python main.py triagem-importar {plano['parametros']['pasta']}/{ARQ_TRIAGEM_H4}{plano['parametros']['sufixo_banco']}  (sem --independente)"]
    return ["ROTULAGEM DA TRIAGEM DE ARTIGOS (destrava a análise bibliométrica, H5)", "",
            f"Linhas: {len(t['linhas'])} (faltam {t['faltam']} para o mínimo, mais a folga de {plano['parametros']['folga']:g}%).",
            f"Hoje: {t['n_incluir']} incluídos e {t['n_excluir']} excluídos por pessoa.", "",
            "Composição: cerca de 50% elegíveis pelo modelo, 20% em quarentena e 30% excluídos pelo modelo, repartidos por relevância Brasil + tema. Assim as",
            "duas decisões (incluir e excluir) aparecem, e o mínimo de 10 de cada fica ao alcance. A coluna estrato diz por que a linha foi escolhida.",
            "Os excluídos pelo modelo entram de propósito: eles medem a falsa exclusão (H4). Foram sorteados ao acaso, sem olhar a relevância.",
            "Esta amostra NÃO é representativa de todos os artigos (a composição foi escolhida); não use as proporções dela como taxas gerais.", "",
            "COMO PREENCHER (uma linha por artigo, pelo título e resumo)",
            "  decisao   incluir ou excluir (pendente = deixar para depois; só incluir e excluir contam)",
            "  motivo    obrigatório ao excluir (entra nos motivos de exclusão do PRISMA)",
            "  revisor   seu nome", "",
            "DEPOIS DE SALVAR", f"  python main.py triagem-importar {plano['parametros']['pasta']}/{ARQ_TRIAGEM}{plano['parametros']['sufixo_banco']}  (sem --independente)"]


def leiame_pasta(plano):
    """Texto de `LEIA-ME.txt`: passo a passo com os comandos exatos e a estimativa de tempo."""
    a, t, au, par = plano["achados"], plano["triagem"], plano["auditoria"], plano["parametros"]
    pasta, sb = par["pasta"], par["sufixo_banco"]
    h = t["h4"]
    arquivos = dict(arquivos_do_plano(plano))
    L = ["ROTULAGEM MÍNIMA: só o que falta para destravar as três análises", "",
         f"Gerado com folga de {par['folga']:g}%, semente {par['semente']!r} (a mesma semente repete a mesma seleção).",
         f"Pasta: {pasta}", "", "O QUE TEM AQUI (linhas por arquivo)"]
    L += [f"  {nome:<28} {n} linha(s)" for nome, n in arquivos.items()] or ["  (nada a rotular: as três análises já estão destravadas)"]
    minutos = estimativa_horas(plano)
    if arquivos:
        L += ["", f"Tempo: ordem de grandeza de {minutos / 60:.1f} h no total, supondo {RITMO_MIN['achado']} min por achado, {RITMO_MIN['artigo']} min por "
              f"artigo e {RITMO_MIN['pagina']} min por página (ritmo SUPOSTO; ajuste ao seu)."]
    passo = 0
    L += ["", "PASSO A PASSO (da raiz do projeto)"]
    if ARQ_ACHADOS in arquivos:
        passo += 1
        L += [f"{passo}. Achados ({arquivos[ARQ_ACHADOS]} linhas). Abra {ARQ_ACHADOS} (aba Achados; a aba LEIA-ME explica). Leia a evidência, abra a url e preencha",
              "   verificado = 1, status_final, verificado_por e, se quiser, observacao. Salve e rode:",
              f"     python main.py achados-importar {pasta}/{ARQ_ACHADOS}{sb}",
              "   Não use --independente (essa opção só grava no histórico e não conta para a trava).",
              f"   Atenção: a amostra é ENRIQUECIDA em achados com provável erro: não estime a precisão global com ela. Para a precisão global use --aleatoria."]
    if ARQ_TRIAGEM in arquivos:
        passo += 1
        L += [f"{passo}. Triagem de artigos ({arquivos[ARQ_TRIAGEM]} linhas). Abra {ARQ_TRIAGEM} (aba Triagem). Decida pelo título e resumo: decisao = incluir ou excluir",
              "   (motivo obrigatório ao excluir) e revisor. Salve e rode:",
              f"     python main.py triagem-importar {pasta}/{ARQ_TRIAGEM}{sb}"]
    if ARQ_TRIAGEM_H4 in arquivos:
        passo += 1
        L += [f"{passo}. Falsa exclusão, H4 ({arquivos[ARQ_TRIAGEM_H4]} linhas, só artigos que o modelo excluiu; meta {100 * h['meta']:g}%: {h['minimo']} conferidos, zero falsas exclusões).",
              f"   Preencha {ARQ_TRIAGEM_H4} como a triagem e rode: python main.py triagem-importar {pasta}/{ARQ_TRIAGEM_H4}{sb}"]
    if ARQ_AUDITORIA in arquivos:
        passo += 1
        L += [f"{passo}. Auditoria dos negativos ({arquivos[ARQ_AUDITORIA]} páginas sem achado do modelo). Abra {ARQ_AUDITORIA}; para cada linha leia o texto em texto_path",
              "   (relativo à pasta data/raw) ou a página em url e preencha revisor, tinha_aplicacao (1 = havia uma aplicação de IA que o modelo não marcou; 0 = o modelo",
              "   acertou) e, se 1, tecnologia. Salve (CSV) e rode:",
              f"     python main.py auditoria-negativos-importar {pasta}/{ARQ_AUDITORIA}{sb}",
              f"   O mínimo de {au['minimo']} páginas vale se NENHUMA aplicação perdida for encontrada; achando alguma, a meta de 5% exige uma amostra maior."]
    passo += 1
    L += [f"{passo}. Conferir: abra o painel (python main.py painel{sb}) e veja o cartão Prontidão metodológica na página inicial e em Análises > Visão geral.",
          "   Quando uma trava abrir, rode a análise: analises/.venv/bin/python analises/h2_logistica.py (H2) ou analises/h5_bibliometria.py (H5).",
          f"   Se ainda faltar (por exemplo, poucos descartados), rode de novo com outra pasta: python main.py rotulagem-modelo --saida <outra pasta>{sb}",
          "   (os itens já rotulados saem da seleção).", "",
          "O comando não grava nada no banco; só as importações gravam. Não apaga nem sobrescreve arquivos: se a pasta já tiver estes arquivos, ele recusa."]
    return L
