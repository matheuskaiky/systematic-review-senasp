"""Relatorio estatico: UM arquivo HTML com CSS e SVG embutidos, sem nenhum script e sem recurso externo. As unicas URLs
externas sao os links das fontes dos achados e dos artigos. Tudo o que foi coletado passa por `html.escape`.

`coletar_dados` le pela leitura injetada (como as rotas do painel) e `montar_relatorio` e pura: dados -> texto HTML.
Por padrao entram so achados confirmados por humano (regra 7.7 do plano do painel); os nao verificados so aparecem com
`incluir_nao_verificados`, cada um com o aviso escrito "Nao verificado por humano"."""
import re
from html import escape

from painel import formatacao as fmt, mapa_ufs, rotulos
from painel.graficos import barra_empilhada, barras_horizontais, colunas, mapa_do_brasil, mapa_de_calor
from painel.metodologia_texto import gerar_metodologia, para_texto

AVISO_NAO_VERIFICADO = "Não verificado por humano"
POR_PAGINA = 200
ICONES_STATUS = {"em_uso": "●", "piloto": "◐", "licitacao": "▣", "anunciado": "◇", "em_estudo": "?", "apenas_citado": "…", "descartado": "✕"}
NOMES_FASES = {"identificacao": "Identificação", "triagem": "Triagem (título e resumo)",
               "elegibilidade": "Elegibilidade (texto completo)", "inclusao": "Inclusão"}


# ---------------------------------------------------------------- coleta (a unica parte que fala com a leitura)
def _todos_os_achados(leitura, verificacao):
    itens, pagina = [], 1
    while True:
        r = leitura.achados({"verificacao": verificacao}, pagina, POR_PAGINA)
        itens += r["itens"]
        if not r["itens"] or len(itens) >= r["total"]:
            return itens
        pagina += 1


def coletar_dados(leitura, ufs, termos, bases, banco, nome_banco, gerado_em, incluir_nao_verificados=False):
    """Reune, pela leitura, tudo o que o relatorio mostra. `ufs` = {sigla: nome}; `termos` = {id: consulta}."""
    fatos = leitura.fatos_metodologia(len(ufs) or 27)
    fatos["bases_esperadas"] = list(bases)
    fatos["banco"] = banco
    por_uf = {l["uf"]: l for l in leitura.resumo_ufs()}
    return {
        "banco": banco, "nome_banco": nome_banco, "gerado_em": gerado_em, "ufs": dict(ufs), "termos": dict(termos),
        "resumo": leitura.resumo_geral(), "rev": leitura.contagem_revisao(), "por_uf": por_uf,
        "confirmados": _todos_os_achados(leitura, "confirmado"),
        "nao_verificados": _todos_os_achados(leitura, "pendente") if incluir_nao_verificados else [],
        "literatura": leitura.literatura(), "triagem": leitura.contagem_triagem(), "prisma": leitura.prisma(),
        "execucoes": leitura.execucoes(), "fatos": fatos,
    }


# ---------------------------------------------------------------- pecas de HTML
def _e(valor):
    return escape("" if valor is None else str(valor))


def _link_externo(url, texto):
    """Link para a fonte original: so http(s); qualquer outra coisa (javascript:, data:) vira texto simples."""
    if str(url or "").lower().startswith(("http://", "https://")):
        return f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(texto)}</a>'
    return _e(texto)


def _sem_links_do_painel(svg):
    """O mapa de blocos liga cada UF a /estados/XX, pagina que nao existe fora do painel."""
    return re.sub(r'<a href="/estados/[A-Z]{2}">|</a>', "", svg)


def _sem_tema_escuro(css):
    """Remove os blocos @media (prefers-color-scheme: dark): o relatorio e sempre claro, na tela e na impressao."""
    saida, i = [], 0
    while True:
        j = css.find("@media (prefers-color-scheme: dark)", i)
        if j < 0:
            saida.append(css[i:])
            return "".join(saida)
        saida.append(css[i:j])
        k, nivel = css.find("{", j), 0
        for pos in range(k, len(css)):
            nivel += {"{": 1, "}": -1}.get(css[pos], 0)
            if nivel == 0:
                i = pos + 1
                break
        else:
            return "".join(saida)


def _kpi(valor, rotulo):
    return f'<div class="kpi"><span class="kpi-valor">{valor}</span><span class="kpi-rotulo">{_e(rotulo)}</span></div>'


def _selo_status(chave):
    return (f'<span class="selo st-{_e(chave)}"><span aria-hidden="true">{ICONES_STATUS.get(chave, "•")}</span> '
            f'{_e(rotulos.rotulo(rotulos.STATUS, chave))}</span>')


def _tabela(cabecalhos, linhas, classes=()):
    """cabecalhos = [texto]; linhas = [[html_da_celula]] (as celulas ja chegam escapadas); classes = classe CSS por coluna."""
    def classe(i):
        return f' class="{classes[i]}"' if i < len(classes) and classes[i] else ""
    cab = "".join(f"<th{classe(i)}>{_e(c)}</th>" for i, c in enumerate(cabecalhos))
    corpo = "".join("<tr>" + "".join(f"<td{classe(i)}>{c}</td>" for i, c in enumerate(l)) + "</tr>" for l in linhas)
    return f'<div class="tabela-rolavel"><table><thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table></div>'


def _banner(d):
    if d["banco"] == "demo":
        return '<header class="banner banner-demo"><strong>DADOS FICTÍCIOS</strong> <span>Demonstração: nada neste relatório descreve uma pesquisa real.</span></header>'
    if d["banco"] == "simulado":
        return '<header class="banner banner-simulado"><strong>SIMULADO</strong> <span>Dados de teste, sem chamadas reais e sem valor de pesquisa.</span></header>'
    return ""


# ---------------------------------------------------------------- secoes
def _visao_geral(d):
    r, rev, n_ufs = d["resumo"], d["rev"], len(d["ufs"])
    kpis = "".join([
        _kpi(fmt.numero(r["consultas_web"]), "Consultas web"), _kpi(fmt.numero(r["urls_unicas"]), "URLs únicas"),
        _kpi(fmt.numero(r["paginas_com_texto"]), "Páginas com texto"), _kpi(fmt.numero(r["classificacoes"]), "Classificações"),
        _kpi(fmt.numero(r["achados"]), "Achados (classificados pelo modelo)"),
        _kpi(fmt.pct(r["evidencia_ok"], r["achados"]), "Evidência confere"), _kpi(fmt.pct(r["verificados"], r["achados"]), "Verificados por humano"),
        _kpi(f'{fmt.numero(rev["confirmados"])}', "Achados confirmados por humano"),
        _kpi(f'{fmt.numero(r["ufs_confirmadas"])} <small>de {fmt.numero(n_ufs)}</small>', "UFs com achado confirmado"),
        _kpi(_e(fmt.moeda_usd(r["custo_total_usd"])), "Gasto real (todas as execuções)")])
    etapas = [("Consultas web", r["consultas_web"]), ("Resultados", r["resultados"]), ("URLs únicas", r["urls_unicas"]),
              ("Páginas selecionadas", r["selecionadas"]), ("Páginas com texto", r["paginas_com_texto"]),
              ("Classificações", r["classificacoes"]), ("Achados", r["achados"]), ("Achados verificados", r["verificados"]),
              ("Confirmados", r["confirmados"])]
    funil = barras_horizontais(etapas, "Funil do levantamento nas secretarias",
                               "Quantidade em cada etapa, da busca web aos achados confirmados", fmt.numero)
    pend = rev["total"] - rev["verificados"]
    barra = barra_empilhada([(rev["confirmados"], "be-conf", "Confirmados"), (rev["descartados"], "be-desc", "Descartados")], rev["total"],
                            f'{rev["confirmados"]} confirmados, {rev["descartados"]} descartados, {pend} pendentes')
    return (f'<section class="cartao" id="visao-geral"><h2>Visão geral</h2><div class="kpis">{kpis}</div>'
            f'<div class="duas-colunas funil-progresso"><div><h3>Funil</h3>{funil}</div><div><h3>Progresso da revisão</h3>{barra}'
            f'<ul class="legenda"><li><span class="selo ok">✔ Confirmados</span> {fmt.numero(rev["confirmados"])}</li>'
            f'<li><span class="selo st-descartado">✕ Descartados</span> {fmt.numero(rev["descartados"])}</li>'
            f'<li><span class="selo neutro">○ Pendentes</span> {fmt.numero(pend)}</li></ul></div></div></section>')


def _mapa(d):
    blocos = {}
    for uf in d["ufs"]:
        l = d["por_uf"].get(uf) or {}
        if l.get("n_confirmados"):
            blocos[uf] = ("confirmado", f"{l['n_confirmados']} achado(s) confirmado(s)")
        elif l.get("n_achados"):
            blocos[uf] = ("classificado", f"{l['n_achados']} achado(s), nenhum confirmado ainda")
        else:
            blocos[uf] = ("sem-achados", "nenhum achado")
    mapa = _sem_links_do_painel(mapa_do_brasil(blocos, "Situação por estado", "Mapa do Brasil: cada estado é pintado conforme tenha achado confirmado, só classificado ou nenhum"))
    return (f'<section class="cartao" id="mapa"><h2>Situação por estado</h2><div class="mapa-caixa">{mapa}</div><p class="mapa-credito">{mapa_ufs.CREDITO}</p>'
            '<ul class="legenda"><li><span class="selo ok">✔ Confirmado</span> pelo menos um achado verificado por humano</li>'
            '<li><span class="selo alerta">◐ Classificado</span> achados só do modelo, sem confirmação humana (não é resultado)</li>'
            '<li><span class="selo neutro">○ Sem achados</span> nenhum achado classificado</li></ul></section>')


def _linha_achado(a, verificado):
    tec = _e(rotulos.rotulo(rotulos.TECNOLOGIAS, a["tecnologia"]))
    if a.get("cidade"):
        tec += f'<br><small>Município: {_e(a["cidade"])}</small>'
    status = a["status_final"] if verificado else a["status_reportado"]
    oficial = a.get("fonte_oficial_final") if a.get("fonte_oficial_final") is not None else a.get("fonte_oficial")
    fonte = _link_externo(a.get("url"), a.get("dominio_final") or a.get("dominio") or a.get("url") or "fonte")
    fonte += ' <span class="selo ok"><span aria-hidden="true">◆</span> Oficial</span>' if oficial else ' <span class="selo neutro">Não oficial</span>'
    if verificado:
        quando = f' em {_e(fmt.data_hora(a["verificado_em"]))}' if a.get("verificado_em") else ""
        sit = (f'<span class="ver-ok"><span aria-hidden="true">✔</span> Verificado</span><br>'
               f'<small>por {_e(a.get("verificado_por") or "não informado")}{quando}</small>')
        if a.get("observacao"):
            sit += f'<br><small>Observação: {_e(a["observacao"])}</small>'
    else:
        sit = (f'<span class="aviso-nv"><span aria-hidden="true">⚠</span> {AVISO_NAO_VERIFICADO}</span>'
               f'<br><small>Hipótese do modelo, não é resultado. Confiança {_e(rotulos.rotulo(rotulos.CONFIANCA, a["confianca"])).lower()}; '
               + ("evidência localizada no texto." if a.get("evidencia_confere") else "evidência não localizada no texto.") + "</small>")
    evid = f'<blockquote class="trecho citado">{_e(a["evidencia"])}</blockquote>' if a.get("evidencia") else "—"
    forn = _e(a["fornecedor"]) if a.get("fornecedor") else "—"
    return [tec, _selo_status(status), forn, evid, fonte, sit]


def _achados_por_uf(d, itens, verificado, id_secao, titulo, intro):
    if not itens:
        return f'<section class="cartao" id="{id_secao}"><h2>{_e(titulo)}</h2><p class="vazio">{_e(intro[1])}</p></section>'
    por_uf = {}
    for a in sorted(itens, key=lambda x: (x["uf"], x.get("cidade") or "", x["tecnologia"] or "", x["achado_id"])):
        por_uf.setdefault(a["uf"], []).append(a)
    situacao = "Situação" if verificado else "Situação segundo o modelo"
    cabecalho = "".join(f"<th>{c}</th>" for c in ("Tecnologia", situacao, "Fornecedor", "Evidência (trecho literal)", "Fonte", "Verificação"))
    corpo = []
    for uf, linhas in por_uf.items():
        nome = d["ufs"].get(uf, "")
        corpo.append(f'<tr class="grupo-uf"><th colspan="6" scope="colgroup">{_e(uf)}{" — " + _e(nome) if nome else ""} '
                     f'<small>({fmt.numero(len(linhas))})</small></th></tr>')
        corpo += ["<tr" + ("" if verificado else ' class="nv"') + ">" + "".join(f"<td>{c}</td>" for c in _linha_achado(a, verificado)) + "</tr>"
                  for a in linhas]
    return (f'<section class="cartao" id="{id_secao}"><h2>{_e(titulo)}</h2><p>{_e(intro[0])}</p>'
            f'<div class="tabela-rolavel"><table class="achados"><thead><tr>{cabecalho}</tr></thead><tbody>{"".join(corpo)}</tbody></table></div></section>')


def _literatura(d):
    lit, tri = d["literatura"], d["triagem"]
    if not lit["n_artigos"]:
        return '<section class="cartao" id="literatura"><h2>Literatura</h2><p class="vazio">Ainda não há artigos no banco.</p></section>'
    kpis = "".join([_kpi(fmt.numero(lit["n_artigos"]), "Artigos únicos"), _kpi(fmt.numero(lit["n_multi"]), "Achados por 2 ou mais termos ou bases"),
                    _kpi(fmt.pct(tri["incluidos"] + tri["excluidos"], tri["total"]), "Triados (título e resumo)"),
                    _kpi(fmt.numero(tri["incluidos"]), "Incluídos"), _kpi(fmt.numero(tri["pendentes"]), "Pendentes")])
    anos = colunas([(str(l["ano"]), l["n_artigos"]) for l in lit["por_ano"]], "Artigos por ano",
                   "Quantidade de artigos únicos encontrados, por ano de publicação", "ano", "artigos")
    termos = [l["termo_id"] for l in lit["por_termo"]]
    valores = {(l["termo_a"], l["termo_b"]): l["n_em_comum"] for l in lit["sobreposicao"]}
    valores.update({(l["termo_id"], l["termo_id"]): l["n_artigos"] for l in lit["por_termo"]})
    calor = mapa_de_calor(termos, valores, "Artigos em comum entre termos", "Cada célula é o número de artigos encontrados pelos dois termos",
                          {t: d["termos"].get(t, "") for t in termos})
    sem_ano = f'<p><small>{fmt.numero(lit["sem_ano"])} artigo(s) sem ano identificado não aparecem no gráfico.</small></p>' if lit["sem_ano"] else ""
    manuais = (_tabela(["Base", "Buscas", "Resultados informados", "Após o filtro", "Selecionados"],
                       [[_e(m["base"]), fmt.numero(m["n_buscas"]), fmt.numero(m["total_resultados"]), fmt.numero(m["total_apos_filtro"]),
                         fmt.numero(m["total_selecionados"])] for m in lit["manuais"]], ["", "num", "num", "num", "num"])
               if lit["manuais"] else '<p class="vazio">Nenhuma busca manual importada.</p>')
    citados = "".join(f'<li>{_link_externo(a.get("link"), a["titulo"])} '
                      f'<small>({_e(a["ano"] or "s/ano")}) · {fmt.numero(a["citacoes"])} citações</small></li>' for a in lit["mais_citados"])
    return (f'<section class="cartao" id="literatura"><h2>Literatura</h2><div class="kpis">{kpis}</div>'
            f'<h3>Artigos por ano</h3>{anos}{sem_ano}<h3>Buscas manuais por base</h3>{manuais}'
            f'<h3>Artigos mais citados</h3><ol class="lista-simples numerada">{citados}</ol>'
            f'<h3>Termos em comum</h3><p class="sub">Quanto mais escura a célula, mais artigos os dois termos encontraram juntos; a diagonal é o total de cada termo.</p>'
            f'<div class="tabela-rolavel">{calor}</div></section>')


def _prisma(d):
    p = d["prisma"]
    fases = {}
    for c in p["caixas"]:
        fases.setdefault(c["fase"], []).append(c)
    partes = ['<section class="cartao" id="prisma"><h2>Fluxo PRISMA</h2><p class="sub">Contagens das buscas manuais são as que foram informadas '
              'no CSV; o que não foi informado aparece como “não informado”, nunca como zero inventado.</p><div class="prisma">']
    for i, (fase, caixas) in enumerate(fases.items()):
        itens = []
        for c in caixas:
            manual = "buscas manuais" in c["metrica"]
            scholar = "Google Scholar" in c["metrica"] or "execucoes de busca" in c["metrica"]
            if manual and p["n_buscas_manuais"] == 0:
                valor = '<span class="nd">não informado</span>'
            elif scholar and p["n_buscas_scholar"] == 0:
                valor = '<span class="nd">não executado</span>'
            else:
                valor = fmt.numero(c["valor"])
            itens.append(f'<li class="caixa-prisma"><span class="num-prisma">{valor}</span><span>{_e(c["metrica"])}</span></li>')
        partes.append(f'<section class="prisma-fase" aria-label="{_e(NOMES_FASES.get(fase, fase))}"><h3>{_e(NOMES_FASES.get(fase, fase))}</h3>'
                      f'<ul class="lista-simples">{"".join(itens)}</ul></section>')
        if i < len(fases) - 1:
            partes.append('<div class="seta-prisma" aria-hidden="true">▼</div>')
    partes.append("</div>")
    partes.append('<p class="sub">Removidos por ferramenta automática: artigos que a triagem de escopo do modelo excluiu e sobre os quais '
                  'nenhuma pessoa decidiu; nada é apagado e uma decisão humana sempre os devolve ao fluxo humano. A triagem de escopo '
                  'entra no fluxo como registros removidos por ferramenta de automação, como pede o PRISMA 2020.</p>')
    if p["motivos"]:
        partes.append("<h3>Motivos de exclusão</h3>" + _tabela(
            ["Etapa", "Motivo", "Artigos"], [[_e("Título e resumo" if m["etapa"] == "titulo_resumo" else "Texto completo"), _e(m["motivo"]),
                                              fmt.numero(m["n"])] for m in p["motivos"]], ["", "", "num"]))
    partes.append("</section>")
    return "".join(partes)


def _metodologia(m):
    partes = ['<section class="cartao" id="metodologia"><h2>Metodologia</h2><div class="metodologia">']
    for s in m["secoes"]:
        partes.append(f'<h3>{_e(s["titulo"])}</h3>')
        for b in s["blocos"]:
            if b["tipo"] == "p":
                partes.append(f'<p>{_e(para_texto(b["seg"]))}</p>')
            else:
                partes.append('<ul class="itens">' + "".join(f"<li>{_e(para_texto(i))}</li>" for i in b["itens"]) + "</ul>")
    if m["ressalvas"]:
        partes.append('<h3 id="ressalvas-dados">Ressalvas sobre os dados</h3><ul class="itens ressalvas-lista">'
                      + "".join(f"<li>{_e(para_texto(r))}</li>" for r in m["ressalvas"]) + "</ul>")
    partes.append("</div></section>")
    return "".join(partes)


def _rodape(d):
    ex = sorted((e for e in d["execucoes"] if e["no_relatorio"]), key=lambda e: (e["iniciado_em"] or "", e["run_id"]))
    fora = len(d["execucoes"]) - len(ex)
    linhas = [[f'<code>{_e(e["run_id"])}</code>', _e(e["comando"]), _e(e["status"]), _e(fmt.data_hora(e["iniciado_em"])),
               f'<code>{_e((e["config_hash"] or "—")[:12])}</code>', f'<code>{_e(e["commit_git"] or "não registrado")}</code>'] for e in ex]
    tabela = _tabela(["Execução", "Comando", "Situação", "Início", "Hash da configuração", "Commit"], linhas) if ex else \
        '<p class="vazio">Nenhuma execução incluída no relatório.</p>'
    nota_fora = (f"<p>{fmt.numero(fora)} {'execução está fora' if fora == 1 else 'execuções estão fora'} do relatório (pilotos, testes ou comparações) "
                 f"e não {'entra' if fora == 1 else 'entram'} nos números.</p>") if fora else ""
    sujas = [e["run_id"] for e in ex if "+sujo" in (e["commit_git"] or "")]
    aviso_sujo = ('<p class="aviso">Atenção: execuções com commit “+sujo” rodaram com código ainda não commitado: '
                  + _e(", ".join(sujas)) + ".</p>") if sujas else ""
    gerado = fmt.data_hora(d["gerado_em"])
    return (f'<footer class="cartao" id="rodape"><h2>Execuções, configuração e versão do código</h2>{tabela}{nota_fora}{aviso_sujo}'
            f'<p class="gerado">Relatório gerado em {_e(gerado)} a partir do banco <code>{_e(d["nome_banco"])}</code>.</p></footer>')


# ---------------------------------------------------------------- ponto de entrada
def montar_relatorio(dados, incluir_nao_verificados, css):
    """HTML completo do relatorio. `css` e o texto das folhas de estilo a embutir (o tema escuro e removido aqui)."""
    d = dados
    m = gerar_metodologia(d["fatos"], d["ufs"])
    rev = d["rev"]
    pend = rev["total"] - rev["verificados"]
    if incluir_nao_verificados:
        nota = (f'<p class="aviso aviso-forte"><strong>Atenção:</strong> este relatório inclui, em seção separada, {fmt.numero(len(d["nao_verificados"]))} '
                f'achado(s) <strong>não verificado(s) por humano</strong>. Eles são hipóteses do classificador, cada um marcado com o aviso '
                f'“{AVISO_NAO_VERIFICADO}”, e não são resultados da pesquisa.</p>')
    else:
        nota = (f'<p class="aviso ok">Este relatório inclui <strong>somente achados confirmados por humano</strong> '
                f'({fmt.numero(rev["confirmados"])}). {fmt.numero(pend)} achado(s) ainda sem verificação humana ficaram de fora.</p>')
    if m["ressalvas"]:
        nota += (f'<p class="aviso aviso-lista"><strong>{fmt.numero(len(m["ressalvas"]))} '
                 f'{"ressalva" if len(m["ressalvas"]) == 1 else "ressalvas"} sobre os dados</strong> (dados incompletos ou execuções fora do padrão): '
                 f'<a href="#ressalvas-dados">ler antes de citar estes números</a>.</p>')
    confirmados = _achados_por_uf(
        d, d["confirmados"], True, "achados-confirmados", "Achados confirmados por humano",
        ("Cada linha é um achado verificado por uma pessoa e não descartado; a situação é a decidida na verificação.",
         "Nenhum achado foi confirmado por humano ainda."))
    nao_verificados = ""
    if incluir_nao_verificados:
        nao_verificados = _achados_por_uf(
            d, d["nao_verificados"], False, "achados-nao-verificados", "Achados NÃO verificados por humano",
            (f"{AVISO_NAO_VERIFICADO}: hipóteses do classificador, ainda sem confirmação. Não as cite como resultado.",
             "Não há achados pendentes de verificação."))
    indice = ['<a href="#visao-geral">Visão geral</a>', '<a href="#mapa">Mapa</a>', '<a href="#achados-confirmados">Achados confirmados</a>']
    if incluir_nao_verificados:
        indice.append('<a href="#achados-nao-verificados">Não verificados</a>')
    indice += ['<a href="#literatura">Literatura</a>', '<a href="#prisma">PRISMA</a>', '<a href="#metodologia">Metodologia</a>',
               '<a href="#rodape">Execuções</a>']
    return (f'<!doctype html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Relatório do levantamento · IA na Segurança Pública</title>'
            f'<style>{_sem_tema_escuro(css)}</style></head>\n<body class="relatorio">{_banner(d)}<main>'
            f'<h1>Relatório do levantamento<br><small>Inteligência artificial na segurança pública</small></h1>{nota}'
            f'<nav class="indice" aria-label="Índice">{" · ".join(indice)}</nav>'
            f'{_visao_geral(d)}{_mapa(d)}{confirmados}{nao_verificados}{_literatura(d)}{_prisma(d)}{_metodologia(m)}{_rodape(d)}'
            f'</main></body></html>\n')
