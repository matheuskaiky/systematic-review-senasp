"""Texto de metodologia gerado a partir de fatos do banco. Funcao pura: recebe um dicionario simples (ver
`LeituraMetodologia.fatos_metodologia`) e devolve secoes de paragrafos. Cada paragrafo e uma lista de segmentos
`(texto, href_ou_None)`: todo numero aponta para a pagina do painel que o justifica. Nada aqui inventa numero:
o que falta nos fatos vira frase dizendo que falta e entra nas ressalvas.

Regra de integridade (secao 7.7 do plano do painel): nada que veio de um modelo e verdadeiro ate um humano verificar.
Os achados confirmados e os apenas classificados aparecem sempre separados, e so os confirmados contam como resultado."""
from datetime import datetime
from urllib.parse import quote, urlencode

from painel import formatacao as fmt, rotulos

MAX_RUNS_NO_TEXTO = 8
MAX_UFS_NO_TEXTO = 27
ETAPAS = {"busca_academica": "busca acadêmica", "busca_web": "busca web", "busca_literatura": "busca de literatura na web",
          "download": "download de páginas", "classificacao": "classificação"}
ETAPAS_COM_PRECO = ("busca_academica", "busca_web", "busca_literatura", "classificacao")   # download nao tem preco: nao conta como custo faltando
PROVA_LITERATURA = "/literatura/prisma"


# ---------------------------------------------------------------- utilidades
def _g(d, chave, padrao=0):
    """d[chave], mas None e chave ausente viram o padrao."""
    valor = (d or {}).get(chave)
    return padrao if valor is None else valor


def _url(caminho, **filtros):
    filtros = {k: v for k, v in filtros.items() if v not in (None, "")}
    return caminho + ("?" + urlencode(filtros) if filtros else "")


def _execucao(run_id):
    return "/execucoes/" + quote(str(run_id), safe="")


def _pct(parte, total):
    if not total:
        return "—"
    return f"{100 * (parte or 0) / total:.1f}%".replace(".", ",")


def _dia(iso):
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return None


def _periodo(primeira, ultima):
    a, b = _dia(primeira), _dia(ultima)
    if a is None or b is None:
        return None
    return f"em {a}" if a == b else f"entre {a} e {b}"


def _pl(n, singular, plural):
    return singular if n == 1 else plural


class _P:
    """Monta um paragrafo: t(texto), n(numero, href), l(texto, href). Todos devolvem self."""

    def __init__(self):
        self.seg = []

    def t(self, texto):
        if texto:
            self.seg.append((texto, None))
        return self

    def l(self, texto, href):
        self.seg.append((texto, href))
        return self

    def n(self, valor, href=None):
        self.seg.append((fmt.numero(valor), href))
        return self

    def v(self, texto, href=None):          # valor ja formatado (porcentagem, dinheiro, data)
        self.seg.append((texto, href))
        return self

    def runs(self, ids):
        ids = list(ids)
        for i, run in enumerate(ids[:MAX_RUNS_NO_TEXTO]):
            self.t(", " if i else "").l(run, _execucao(run))
        if len(ids) > MAX_RUNS_NO_TEXTO:
            self.t(" e mais ").n(len(ids) - MAX_RUNS_NO_TEXTO, "/execucoes").t(" " + _pl(len(ids) - MAX_RUNS_NO_TEXTO, "execução", "execuções"))
        return self

    def lista(self, itens, sep=", ", ultimo=" e "):
        for i, item in enumerate(itens):
            if i:
                self.t(ultimo if i == len(itens) - 1 else sep)
            self.t(item)
        return self


def _p(*segmentos):
    return {"tipo": "p", "seg": list(segmentos)}


def _ul(itens):
    return {"tipo": "ul", "itens": [list(i) for i in itens]}


def _bloco_p(p):
    return {"tipo": "p", "seg": p.seg}


def _secao(id_, titulo, blocos):
    return {"id": id_, "titulo": titulo, "blocos": blocos}


def para_texto(segmentos):
    return "".join(t for t, _ in segmentos)


def _texto_puro(secoes, ressalvas):
    linhas = []
    for s in secoes:
        linhas += [s["titulo"], ""]
        for b in s["blocos"]:
            if b["tipo"] == "p":
                linhas += [para_texto(b["seg"]), ""]
            else:
                linhas += ["- " + para_texto(i) for i in b["itens"]] + [""]
    if ressalvas:
        linhas += ["Ressalvas sobre os dados", ""] + ["- " + para_texto(r) for r in ressalvas] + [""]
    return "\n".join(linhas).strip() + "\n"


# ---------------------------------------------------------------- leitura dos fatos
class _Fatos:
    """Visao dos fatos com valores padrao: o resto do modulo nunca testa 'chave existe'."""

    def __init__(self, f):
        self.f = f or {}
        self.execucoes = self.f.get("execucoes") or []
        self.no_relatorio = [e for e in self.execucoes if e.get("no_relatorio")]
        self.fora = [e for e in self.execucoes if not e.get("no_relatorio")]
        self.retomadas = self.f.get("retomadas") or []
        self.ac = self.f.get("academico") or {}
        self.manuais = self.f.get("manuais") or []
        self.lit = self.f.get("literatura") or {}
        self.tri = self.lit.get("triagem") or {}
        self.prisma = {int(k): v for k, v in (self.lit.get("prisma") or {}).items()}
        self.web = self.f.get("web") or {}
        self.funil = self.web.get("funil") or {}
        self.cl = self.f.get("classificacao") or {}
        self.ach = self.f.get("achados") or {}
        self.ufs = self.f.get("ufs") or {}
        self.mun = self.f.get("municipal") or {}
        self.custos = self.f.get("custos") or {}
        self.bases_esperadas = list(self.f.get("bases_esperadas") or [])
        self.banco = self.f.get("banco")

    @property
    def vazio(self):
        return not (self.execucoes or _g(self.lit, "n_artigos") or self.manuais or _g(self.ach, "total"))


# ---------------------------------------------------------------- secoes
def _literatura(x):
    ac, blocos = x.ac, []
    n_req = _g(ac, "n_requisicoes")
    if n_req:
        p = _P()
        prov = ac.get("provedores") or []
        p.t("A busca no Google Scholar foi feita" + (f" pelo provedor {', '.join(prov)}" if prov else "") + " com ")
        p.n(_g(ac, "n_termos"), _url("/chamadas", etapa="busca_academica")).t(" " + _pl(_g(ac, "n_termos"), "termo", "termos") + " de busca, em ")
        p.n(n_req, _url("/chamadas", etapa="busca_academica")).t(" " + _pl(n_req, "requisição", "requisições") + " (")
        p.n(_g(ac, "n_ok"), _url("/chamadas", etapa="busca_academica", resultado="ok")).t(" " + _pl(_g(ac, "n_ok"), "bem-sucedida", "bem-sucedidas") + " e ")
        p.n(_g(ac, "n_falhas"), _url("/chamadas", etapa="busca_academica", resultado="falha")).t(" com falha)")
        per = _periodo(ac.get("primeira"), ac.get("ultima"))
        if per:
            p.t(", " + per)
        if ac.get("run_ids"):
            p.t(" (" + _pl(len(ac["run_ids"]), "execução", "execuções") + ": ").runs(ac["run_ids"]).t(")")
        p.t(". As requisições retornaram ").n(_g(ac, "n_retornados"), _url("/chamadas", etapa="busca_academica")).t(
            " registros, que correspondem a ").n(_g(ac, "n_artigos_scholar"), "/literatura/artigos").t(
            " artigos únicos depois de removidas as duplicatas entre termos.")
        blocos.append(_bloco_p(p))
        termos = ac.get("termos") or []
        if termos:
            itens = []
            for t in termos:
                p = _P().l(t.get("termo_id") or "?", _url("/literatura/artigos", termo=t.get("termo_id")))
                p.t(f" {t['query']}" if t.get("query") else " (texto do termo não encontrado na configuração)")
                p.t(f" [{t['idioma']}]" if t.get("idioma") else "")
                p.t(" — ").n(_g(t, "n_artigos"), _url("/literatura/artigos", termo=t.get("termo_id"))).t(
                    " " + _pl(_g(t, "n_artigos"), "artigo", "artigos") + " encontrados em ").n(_g(t, "n_requisicoes")).t(
                    " " + _pl(_g(t, "n_requisicoes"), "requisição", "requisições"))
                itens.append(p.seg)
            blocos += [_p(("Termos de busca usados:", None)), _ul(itens)]
    else:
        blocos.append(_p(("Nenhuma busca no Google Scholar consta nas execuções incluídas no relatório.", None)))

    manuais = x.manuais
    if manuais:
        itens = []
        n_buscas = sum(_g(m, "n_buscas") for m in manuais)
        for m in manuais:
            p = _P().l(m["base"], _url("/literatura/artigos", base=m["base"])).t(": ")
            if _g(m, "n_buscas"):
                p.n(m["n_buscas"], "/literatura").t(" " + _pl(m["n_buscas"], "busca", "buscas"))
                per = _periodo(m.get("primeira"), m.get("ultima"))
                p.t(f" ({per})" if per else "")
                for campo, rotulo in (("total_resultados", "resultados informados"), ("total_apos_filtro", "após o filtro da base"),
                                      ("total_selecionados", "selecionados")):
                    p.t("; ")
                    if m.get(campo) is None:
                        p.t(f"{rotulo}: contagem não informada")
                    else:
                        p.n(m[campo], "/literatura").t(" " + rotulo)
            else:
                p.t("sem contagens de busca registradas")
            p.t("; ").n(_g(m, "n_artigos_importados"), _url("/literatura/artigos", base=m["base"])).t(
                " " + _pl(_g(m, "n_artigos_importados"), "artigo importado", "artigos importados"))
            itens.append(p.seg)
        blocos += [_p(("Além do Scholar, foram registradas buscas manuais, com as contagens informadas manualmente:", None)),
                   _ul(itens)]
    else:
        base = f" ({', '.join(x.bases_esperadas)})" if x.bases_esperadas else ""
        blocos.append(_p((f"Nenhuma busca manual nas bases{base} foi importada até agora.", None)))

    n_art = _g(x.lit, "n_artigos")
    p = _P().t("Ao todo, ").n(n_art, "/literatura/artigos").t(" artigos únicos foram identificados (")
    p.n(_g(ac, "n_artigos_scholar"), "/literatura/artigos").t(" do Scholar; ").n(_g(x.lit, "n_artigos_manuais"), "/literatura/artigos").t(
        " das bases manuais; os dois conjuntos podem se sobrepor).")
    if n_art:
        # PRISMA 2020: registros removidos por ferramenta de automação antes da triagem (linhas 11 e 12 de `v_prisma`)
        removidos = x.prisma.get(11)
        if removidos:
            p.t(" Antes da triagem humana, ").n(removidos, PROVA_LITERATURA).t(
                " foram removidos por uma ferramenta automática (a triagem de escopo feita pelo modelo, sem decisão humana; os registros "
                "continuam no banco e uma decisão humana sobre eles sempre prevalece), e ").n(
                x.prisma.get(12, n_art - removidos), PROVA_LITERATURA).t(" seguiram para a triagem por título e resumo.")
        elif removidos == 0:
            p.t(" Todos seguiram para a triagem por título e resumo.")
        avaliados = _g(x.tri, "incluidos") + _g(x.tri, "excluidos")
        p.t(" Na triagem por título e resumo, ").n(avaliados, PROVA_LITERATURA).t(" foram avaliados: ")
        p.n(_g(x.tri, "incluidos"), _url("/literatura/artigos", decisao="incluir")).t(" incluídos e ")
        p.n(_g(x.tri, "excluidos"), _url("/literatura/artigos", decisao="excluir")).t(" excluídos; ")
        p.n(_g(x.tri, "pendentes"), _url("/literatura/artigos", decisao="pendente")).t(" aguardam decisão.")
        if 20 in x.prisma:
            p.t(" Incluídos no estudo após a leitura do texto completo: ").n(x.prisma[20], PROVA_LITERATURA).t(".")
    blocos.append(_bloco_p(p))
    return _secao("literatura", "Busca na literatura acadêmica", blocos)


def _web(x):
    w, fu, blocos = x.web, x.funil, []
    n_req = _g(w, "n_requisicoes")
    if not n_req:
        return _secao("web", "Levantamento nas secretarias (busca web)",
                      [_p(("Nenhuma consulta web consta nas execuções incluídas no relatório.", None))])
    p = _P().t("O levantamento nas secretarias usou busca web")
    if w.get("provedores"):
        p.t(f" (provedor {', '.join(w['provedores'])})")
    modelos = w.get("modelos_consulta") or []
    if modelos:
        p.t(" com ").n(len(modelos), _url("/chamadas", etapa="busca_web")).t(" " + _pl(len(modelos), "modelo", "modelos") + " de consulta (" + ", ".join(modelos) + ")")
    p.t(": ").n(_g(fu, "consultas_web"), _url("/chamadas", etapa="busca_web", resultado="ok")).t(
        " " + _pl(_g(fu, "consultas_web"), "consulta bem-sucedida", "consultas bem-sucedidas"))
    if _g(w, "n_falhas"):
        p.t(" e ").n(w["n_falhas"], _url("/chamadas", etapa="busca_web", resultado="falha")).t(" com falha")
    per = _periodo(w.get("primeira"), w.get("ultima"))
    if per:
        p.t(", " + per)
    if w.get("run_ids"):
        p.t(" (" + _pl(len(w["run_ids"]), "execução", "execuções") + ": ").runs(w["run_ids"]).t(")")
    p.t(". Elas devolveram ").n(_g(fu, "resultados"), "/execucoes").t(" resultados, correspondentes a ").n(_g(fu, "urls_unicas"), "/execucoes").t(
        " URLs únicas, das quais ").n(_g(w, "urls_oficiais"), "/execucoes").t(" de fonte oficial (.gov.br).")
    blocos.append(_bloco_p(p))

    p = _P().t("Dos pares URL × UF encontrados, ").n(_g(fu, "selecionadas"), "/execucoes").t(" foram selecionados para download")
    descartes = w.get("descartes") or []
    if descartes:
        p.t("; os demais foram descartados pelos motivos: ")
        p.lista([f"{rotulos.rotulo(rotulos.MOTIVOS_DESCARTE, d['motivo'])} ({fmt.numero(d['n'])})" for d in descartes])
    p.t(". Foram baixadas ").n(_g(fu, "paginas"), _url("/chamadas", etapa="download")).t(" páginas, das quais ").n(
        _g(fu, "paginas_com_texto"), _url("/chamadas", etapa="download")).t(" tiveram texto extraído e puderam ser classificadas com base no texto.")
    blocos.append(_bloco_p(p))
    robots = w.get("bloqueios_robots") or {}
    proibidas, inacessiveis = _g(robots, "bloqueado_por_robots"), _g(robots, "robots_inacessivel")
    if proibidas or inacessiveis:
        p = _P().t("O download respeita o robots.txt de cada site (RFC 9309). ")
        p.n(proibidas, _url("/chamadas", etapa="download", q="bloqueado_por_robots")).t(
            " " + _pl(proibidas, "página foi proibida pelo site (o robots.txt foi lido e a proíbe)", "páginas foram proibidas pelo site (o robots.txt foi lido e as proíbe)"))
        p.t("; outras ").n(inacessiveis, _url("/chamadas", etapa="download", q="robots_inacessivel")).t(
            " não foram baixadas porque o robots.txt do site estava inacessível (erro do servidor, tempo esgotado ou falha de rede, mesmo depois de novas tentativas): "
            "por política, a leitura impossível é tratada como proibição, mas isso não é uma decisão do site.")
        blocos.append(_bloco_p(p))
    nv = x.web.get("nao_verificaveis") or {}
    n_nv, n_404, n_prib = _g(nv, "nao_verificavel_robots"), _g(nv, "falha_definitiva_404"), _g(nv, "proibido_pelo_site")
    if n_nv or n_404:
        p = _P().t("Pela última tentativa de download de cada página")
        if n_nv:
            p.t(", ").n(n_nv, _url("/chamadas", etapa="download", q="robots_inacessivel")).t(
                " " + _pl(n_nv, "página não pôde ser verificada", "páginas não puderam ser verificadas") + " porque o robots.txt do site seguiu inacessível "
                "(três leituras seguidas ou ao menos duas tentativas), em " + fmt.numero(_g(nv, "n_dominios_nao_verificaveis"))
                + " " + _pl(_g(nv, "n_dominios_nao_verificaveis"), "domínio", "domínios") + ". Não verificável não é o mesmo que proibido pelo site: "
                "não sabemos o que o site decidiu, e por política (RFC 9309) a página ficou fora da coleta")
        if n_404:
            p.t("; " if n_nv else ", ").n(n_404, _url("/chamadas", etapa="download", q="http_404")).t(
                " " + _pl(n_404, "página deu", "páginas deram") + " erro 404 ou 410 (a página não existe mais ou mudou de endereço)")
        if n_prib:
            p.t(", e ").n(n_prib, _url("/chamadas", etapa="download", q="bloqueado_por_robots")).t(
                " " + _pl(n_prib, "foi proibida", "foram proibidas") + " pelo site (robots.txt lido)")
        p.t(". O levantamento pode, portanto, ter deixado de ver conteúdo nessas páginas.")
        blocos.append(_bloco_p(p))
    return _secao("web", "Levantamento nas secretarias (busca web)", blocos)


def _classificacao(x):
    cl, ach, blocos = x.cl, x.ach, []
    pares = cl.get("classificadores") or []
    if not pares:
        return _secao("classificacao", "Classificação automática",
                      [_p(("Nenhuma classificação consta nas execuções incluídas no relatório.", None))])
    itens = []
    for c in pares:
        p = _P().t("classificador ").t(c.get("classificador") or "não registrado")
        p.t(", prompt " + (c["prompt_versao"] if c.get("prompt_versao") else "(versão não registrada)") + ": ")
        p.n(_g(c, "n_classificacoes"), _url("/chamadas", etapa="classificacao")).t(" " + _pl(_g(c, "n_classificacoes"), "classificação", "classificações") + ", ")
        p.n(_g(c, "n_json_valido"), "/classificadores").t(" com resposta em JSON válido, ")
        p.n(_g(c, "n_achados"), "/achados").t(" " + _pl(_g(c, "n_achados"), "achado", "achados"))
        itens.append(p.seg)
    p = _P().t("Cada página foi classificada por um modelo de linguagem")
    if cl.get("provedores"):
        p.t(f" (provedor {', '.join(cl['provedores'])})")
    p.t(". ")
    if _g(cl, "n_so_snippet"):
        p.n(cl["n_so_snippet"], _url("/achados", origem="snippet")).t(" " + _pl(cl["n_so_snippet"], "classificação usou", "classificações usaram")
                                                                      + " só o trecho (snippet) do resultado da busca, não o texto da página. ")
    if _g(cl, "n_historico") > sum(_g(c, "n_classificacoes") for c in pares):
        p.t("Uma página classificada mais de uma vez conta uma só vez, pela classificação vigente (a mais recente com resposta válida "
            "e texto da página, ou a que já tem achado verificado por humano); ao todo foram feitas ").n(cl["n_historico"]).t(
            " classificações, e o histórico completo continua no banco. ")
    p.t("Cada achado traz também o nome próprio da solução (campo nome_solucao, a partir do prompt v4), copiado como está no texto; "
        "o nome só é guardado se aparece no texto enviado ao modelo, e o trecho de evidência continua sendo uma citação literal. ")
    p.t("Combinações de classificador e versão do prompt presentes no relatório (contagens das classificações vigentes):")
    blocos += [_bloco_p(p), _ul(itens)]

    total = _g(ach, "total")
    p = _P().t("Os ").n(total, "/achados").t(" achados produzidos pelo modelo são tratados como hipóteses: nenhum conta como resultado antes da verificação humana. ")
    p.t("Verificação automática da evidência: em ").n(_g(ach, "evidencia_ok"), _url("/achados", evidencia=1)).t(" de ").n(total, "/achados").t(
        " achados (" + _pct(_g(ach, "evidencia_ok"), total) + ") o trecho citado pelo modelo foi localizado literalmente no texto enviado a ele. "
        "Essa checagem só mostra que o trecho existe, não que ele sustenta o achado.")
    if _g(ach, "pendentes_sem_evidencia"):
        p.t(" Há ").n(ach["pendentes_sem_evidencia"], _url("/achados", verificacao="pendente", evidencia=0)).t(
            " achados não verificados cuja evidência não foi localizada.")
    if _g(cl, "n_fora_vocabulario"):
        p.t(" Outros ").n(cl["n_fora_vocabulario"]).t(" achados devolvidos fora do vocabulário controlado foram descartados automaticamente e ficam guardados para auditoria.")
    blocos.append(_bloco_p(p))
    return _secao("classificacao", "Classificação automática", blocos)


def _verificacao(x):
    ach = x.ach
    total = _g(ach, "total")
    if not total:
        return _secao("verificacao", "Verificação humana",
                      [_p(("Ainda não há achados para verificar nas execuções incluídas no relatório.", None))])
    ver, conf, desc = _g(ach, "verificados"), _g(ach, "confirmados"), _g(ach, "descartados")
    pend = total - ver
    p = _P().t("Dos ").n(total, "/achados").t(" achados, ").n(ver, _url("/achados")).t(" (" + _pct(ver, total) + ") foram verificados por humano")
    if _g(ach, "n_revisores"):
        p.t(" (").n(ach["n_revisores"]).t(" " + _pl(ach["n_revisores"], "revisor", "revisores") + ")")
    p.t(": ").n(conf, _url("/achados", verificacao="confirmado")).t(" confirmados e ").n(desc, _url("/achados", verificacao="descartado")).t(
        " descartados como incorretos. ")
    p.n(pend, _url("/achados", verificacao="pendente")).t(" ainda não foram verificados e, por isso, não entram nos resultados.")
    if ver:
        p.t(" Entre os verificados, a taxa de confirmação foi de " + _pct(conf, ver) + ".")
    blocos = [_bloco_p(p), _p(("Somente achados verificados e não descartados contam como achado confirmado; o status final é o decidido pela pessoa que verificou, "
                               "que pode diferir do status reportado pelo modelo.", None))]
    return _secao("verificacao", "Verificação humana", blocos)


def _ufs(x, nomes_ufs):
    u, ach, blocos = x.ufs, x.ach, []
    n_ufs = _g(u, "n_ufs", len(nomes_ufs or {}) or 27)
    conf = x.ufs.get("confirmadas") or []
    p = _P().t("Considerando apenas achados confirmados por humano, ").n(_g(u, "uf_confirmada"), "/estados").t(" de ").n(n_ufs).t(
        " UFs têm ao menos um achado confirmado")
    if conf:
        p.t(" (")
        for i, uf in enumerate(conf[:MAX_UFS_NO_TEXTO]):
            p.t(", " if i else "").l(uf, f"/estados/{quote(uf, safe='')}")
        p.t(")")
    p.t("; ").n(_g(u, "uf_so_classificado"), "/estados").t(" só têm achados classificados pelo modelo, ainda sem confirmação humana, e ").n(
        _g(u, "uf_sem_achados"), "/estados").t(" não têm nenhum achado. “Sem achados” significa que nenhum achado foi classificado, não que a UF não use a tecnologia.")
    blocos.append(_bloco_p(p))

    por_tec = ach.get("confirmados_por_tecnologia") or []
    if por_tec:
        p = _P().t("Achados confirmados por tecnologia: ")
        for i, t in enumerate(por_tec):
            p.t("; " if i else "").t(rotulos.rotulo(rotulos.TECNOLOGIAS, t["tecnologia"]) + " (").n(
                t["n"], _url("/achados", verificacao="confirmado", tecnologia=t["tecnologia"])).t(")")
        p.t(".")
        blocos.append(_bloco_p(p))

    m = x.mun
    if _g(m, "n_achados"):
        p = _P().t("Escopo municipal: ").n(m["n_achados"], _url("/achados", esfera="municipal")).t(" achados em secretarias municipais de ").n(
            _g(m, "n_cidades"), _url("/achados", esfera="municipal")).t(" " + _pl(_g(m, "n_cidades"), "cidade", "cidades") + ", dos quais ").n(
            _g(m, "n_confirmados"), _url("/achados", esfera="municipal", verificacao="confirmado")).t(" confirmados.")
    else:
        p = _P().t("Não há achados de secretarias municipais no banco; o levantamento descrito aqui cobre as secretarias estaduais.")
    blocos.append(_bloco_p(p))
    return _secao("ufs", "Resultados confirmados por UF", blocos)


def _custos(x):
    c, blocos = x.custos, []
    etapas = c.get("por_etapa") or []
    if not etapas:
        return _secao("custos", "Custos", [_p(("Nenhuma chamada externa consta nas execuções incluídas no relatório.", None))])
    total = sum(_g(e, "custo_usd", 0.0) for e in etapas)
    itens = []
    for e in etapas:
        p = _P().t(f"{ETAPAS.get(e['etapa'], e['etapa'])} ({e['provedor']}): ")
        p.n(e["n_chamadas"], _url("/chamadas", etapa=e["etapa"], provedor=e["provedor"])).t(" " + _pl(e["n_chamadas"], "chamada", "chamadas") + ", ")
        if _g(e, "n_com_custo"):
            p.v(fmt.moeda_usd(e["custo_usd"]), _url("/chamadas", etapa=e["etapa"], provedor=e["provedor"]))
        elif e["etapa"] in ETAPAS_COM_PRECO:
            p.t("custo não calculado (preço não informado)")
        else:
            p.t("sem custo associado")
        itens.append(p.seg)
    if any(_g(e, "n_com_custo") for e in etapas):
        p = _P().t("O custo registrado das chamadas externas nas execuções do relatório foi de ").v(fmt.moeda_usd(total), "/chamadas").t(
            ", somando só as chamadas com custo calculado. Por etapa e provedor:")
    else:
        p = _P().t("Nenhuma chamada das execuções do relatório tem custo calculado: o custo em dólares não pôde ser informado. Chamadas por etapa e provedor:")
    blocos += [_bloco_p(p), _ul(itens)]
    gasto = c.get("gasto_real") or []
    if gasto:
        total_geral = sum(_g(g, "custo_registrado_usd", 0.0) for g in gasto)
        fora = sum(_g(g, "custo_registrado_usd", 0.0) for g in gasto if not g.get("no_relatorio"))
        p = _P().t("Somando todas as execuções, dentro e fora do relatório, o gasto registrado foi de ").v(fmt.moeda_usd(total_geral), "/chamadas")
        if fora:
            p.t(", dos quais ").v(fmt.moeda_usd(fora), "/execucoes").t(" em execuções fora do relatório (pilotos, testes ou comparações)")
        p.t(".")
        blocos.append(_bloco_p(p))
    return _secao("custos", "Custos", blocos)


def _curto(valor, n=12):
    return str(valor)[:n] if valor else None


def _reprodutibilidade(x):
    blocos = []
    ex = x.no_relatorio
    if not ex:
        blocos.append(_p(("Nenhuma execução está incluída no relatório.", None)))
    else:
        itens = []
        for e in ex:
            p = _P().l(e["run_id"], _execucao(e["run_id"])).t(f": {e.get('comando') or 'comando não registrado'} ({e.get('status') or 'situação não registrada'}")
            p.t(", hash da configuração " + (_curto(e.get("config_hash")) or "não registrado"))
            p.t(", commit " + (e.get("commit_git") or "não registrado") + ")")
            itens.append(p.seg)
        p = _P().t("Os números acima consideram ").n(len(ex), "/execucoes").t(" " + _pl(len(ex), "execução", "execuções") + " marcadas para o relatório. ")
        hashes = sorted({e["config_hash"] for e in ex if e.get("config_hash")})
        if len(hashes) == 1:
            p.t("Todas usaram a mesma configuração (hash " + hashes[0][:12] + "), gravada integralmente no banco junto a cada execução.")
        elif hashes:
            p.t("Elas usaram ").n(len(hashes)).t(" configurações diferentes (hashes " + ", ".join(h[:12] for h in hashes) + ").")
        p.t(" Execuções, hash da configuração e commit do código:")
        blocos += [_bloco_p(p), _ul(itens)]
    if x.fora:
        p = _P().n(len(x.fora), "/execucoes").t(" " + _pl(len(x.fora), "execução está fora do relatório", "execuções estão fora do relatório")
                                                  + " (pilotos, testes ou comparações) e não " + _pl(len(x.fora), "entra", "entram") + " nos números acima: ")
        p.runs([e["run_id"] for e in x.fora]).t(".")
        blocos.append(_bloco_p(p))
    return _secao("reprodutibilidade", "Reprodutibilidade", blocos)


# ---------------------------------------------------------------- ressalvas
def _ressalvas(x):
    r = []

    def add(*segmentos):
        r.append(list(segmentos))

    if x.banco in ("demo", "simulado"):
        add(("Estes dados são " + ("fictícios (demonstração)" if x.banco == "demo" else "simulados (teste, sem chamadas reais)")
             + ": o texto não descreve uma pesquisa real e não deve ser usado em publicação.", None))
    if x.banco == "vies":
        add(("Estes dados são do banco da busca de viés algorítmico na segurança pública, separado do banco da pesquisa: "
             "os números abaixo não são os das secretarias estaduais nem os da busca de artigos.", None))
    if x.vazio:
        add(("Nada foi coletado ainda: o banco não tem execuções, artigos nem achados. Rode o pipeline (por exemplo, python main.py pipeline-uf --ufs PI --limite 5) e volte aqui.", None))
        add(("Nenhuma busca acadêmica, busca web ou classificação registrada; nenhuma verificação humana feita.", None))
        return r
    ach, total = x.ach, _g(x.ach, "total")
    ver = _g(ach, "verificados")
    if total and not ver:
        add(("Nenhum achado foi verificado por humano ainda: todos os achados são hipóteses do classificador e não podem ser apresentados como resultado. ", None),
            ("Comece a revisão.", "/revisao/achados"))
    elif total and total - ver:
        add((f"{fmt.numero(total - ver)} {_pl(total - ver, 'achado ainda não foi verificado', 'achados ainda não foram verificados')} por humano; os resultados por UF podem mudar com a revisão. ", None),
            ("Ver pendentes.", _url("/achados", verificacao="pendente")))
    if not total and (_g(x.web, "n_requisicoes") or _g(x.cl, "classificadores")):
        add(("Não há nenhum achado nas execuções do relatório.", None))
    if not x.ac.get("n_requisicoes"):
        add(("Nenhuma busca no Google Scholar nas execuções do relatório: a seção de literatura acadêmica não tem números do Scholar.", None))
    if not _g(x.web, "n_requisicoes"):
        add(("Nenhuma consulta web nas execuções do relatório: não há levantamento nas secretarias descrito.", None))
    if not x.cl.get("classificadores"):
        add(("Nenhuma classificação nas execuções do relatório.", None))
    feitas = {m["base"] for m in x.manuais if _g(m, "n_buscas")}
    if not x.manuais:
        add(("Nenhuma busca manual foi importada: as bases " + (", ".join(x.bases_esperadas) if x.bases_esperadas else "IEEE, ACM, Scopus e SBC OpenLib")
             + " não têm contagens no banco e o fluxo PRISMA mostra “não informado” nessas caixas. ", None), ("Ver o PRISMA.", PROVA_LITERATURA))
    else:
        faltam = [b for b in x.bases_esperadas if b not in feitas]
        if faltam:
            add(("Sem busca manual registrada em: " + ", ".join(faltam) + ".", None))
        incompletas = [m["base"] for m in x.manuais if _g(m, "n_buscas") and any(m.get(c) is None for c in ("total_resultados", "total_apos_filtro", "total_selecionados"))]
        if incompletas:
            add(("Contagens das buscas manuais incompletas (não informadas) em: " + ", ".join(incompletas) + ".", None))
    if _g(x.lit, "n_artigos") and _g(x.tri, "pendentes"):
        add((f"A triagem está incompleta: {fmt.numero(x.tri['pendentes'])} de {fmt.numero(x.lit['n_artigos'])} artigos aguardam decisão. ", None),
            ("Ver o PRISMA.", PROVA_LITERATURA))
    semtermo = [t["termo_id"] for t in (x.ac.get("termos") or []) if not t.get("query")]
    if semtermo:
        add(("O texto do termo não foi encontrado na configuração gravada para: " + ", ".join(semtermo) + ".", None))
    # custos
    etapas = x.custos.get("por_etapa") or []
    sem_preco = [f"{ETAPAS.get(e['etapa'], e['etapa'])} ({e['provedor']})" for e in etapas
                 if e["etapa"] in ETAPAS_COM_PRECO and _g(e, "n_ok") and not _g(e, "n_com_custo")]
    if sem_preco:
        add(("Custo não calculado: preços não informados para " + ", ".join(sem_preco) + ". O total em dólares acima não inclui essas etapas.", None))
    parcial = [f"{ETAPAS.get(e['etapa'], e['etapa'])} ({e['provedor']}): {fmt.numero(e['n_ok_sem_custo'])}" for e in etapas
               if _g(e, "n_com_custo") and _g(e, "n_ok_sem_custo")]
    if parcial:
        add(("Há chamadas bem-sucedidas sem custo gravado (" + "; ".join(parcial) + "): o custo total está subestimado.", None))
    # reprodutibilidade
    sujas = [e["run_id"] for e in x.no_relatorio if "+sujo" in (e.get("commit_git") or "")]
    if sujas:
        add(("Execuções feitas com código ainda não commitado (commit com “+sujo”): ", None), *_P().runs(sujas).seg,
            (". O commit registrado não reproduz exatamente o código que rodou.", None))
    sem_commit = [e["run_id"] for e in x.no_relatorio if not e.get("commit_git")]
    if sem_commit:
        add(("Commit do código não registrado em: " + ", ".join(sem_commit) + ".", None))
    nao_concluidas = [e for e in x.no_relatorio if e.get("status") != "concluida"]
    if nao_concluidas:
        p = _P().runs([e["run_id"] for e in nao_concluidas])
        add(("Execuções do relatório que não terminaram como concluídas: ", None), *p.seg, (". Os números podem estar parciais.", None))
    hashes = {e["config_hash"] for e in x.no_relatorio if e.get("config_hash")}
    if len(hashes) > 1:
        add((f"As execuções do relatório usaram {len(hashes)} configurações diferentes; confira as diferenças antes de descrever o método como único.", None))
    if x.retomadas:
        p = _P().runs([e["run_id"] for e in x.retomadas])
        add(("Execuções retomadas (--retomar), cujo código e ambiente podem diferir dos da execução original: ", None), *p.seg, (".", None))
    if x.fora:
        add((f"{fmt.numero(len(x.fora))} {_pl(len(x.fora), 'execução está fora', 'execuções estão fora')} do relatório e não "
             f"{_pl(len(x.fora), 'entra', 'entram')} nos números; {_pl(len(x.fora), 'seu custo entra', 'seus custos entram')} apenas no gasto real total. ", None),
            ("Ver execuções.", "/execucoes"))
    pares = x.cl.get("classificadores") or []
    if len(pares) > 1:
        add((f"Há {len(pares)} combinações de classificador e versão do prompt no relatório; os achados de modelos diferentes foram somados.", None))
    if any(not c.get("prompt_versao") for c in pares):
        add(("A versão do prompt não está registrada em parte das classificações.", None))
    if _g(x.cl, "n_so_snippet"):
        add((f"{fmt.numero(x.cl['n_so_snippet'])} {_pl(x.cl['n_so_snippet'], 'classificação usou', 'classificações usaram')} só o snippet da busca; achados assim têm menos base e merecem atenção na verificação.", None))
    n_nv = _g(x.web.get("nao_verificaveis"), "nao_verificavel_robots")
    if n_nv:
        add((f"{fmt.numero(n_nv)} {_pl(n_nv, 'página não pôde', 'páginas não puderam')} ser verificadas porque o robots.txt do site seguiu inacessível; "
             "isso não é o mesmo que o site proibir a leitura. Elas ficaram fora da coleta e o levantamento pode ter deixado de ver conteúdo nelas. ", None),
            ("Ver as chamadas.", _url("/chamadas", etapa="download", q="robots_inacessivel")))
    if _g(x.cl, "n_invalidas"):
        add((f"{fmt.numero(x.cl['n_invalidas'])} {_pl(x.cl['n_invalidas'], 'classificação', 'classificações')} sem JSON válido e sem outra válida para a mesma página: esses pares não podem ser lidos como “sem achados”. ", None),
            ("Ver classificadores.", "/classificadores"))
    return r


# ---------------------------------------------------------------- ponto de entrada
def gerar_metodologia(fatos, ufs=None):
    """Devolve {"secoes": [...], "ressalvas": [...], "vazio": bool, "texto": str}.
    secao = {"id", "titulo", "blocos": [{"tipo": "p", "seg": [(texto, href)]} | {"tipo": "ul", "itens": [[(texto, href)]]}]}.
    `ufs` (sigla -> nome) so serve para saber o total de UFs quando os fatos nao o trazem."""
    x = _Fatos(fatos)
    ressalvas = _ressalvas(x)
    if x.vazio:
        secoes = [_secao("situacao", "Situação dos dados", [_p(("Nada foi coletado ainda: não há execuções, artigos nem achados no banco, "
                                                               "então não há método a descrever.", None))])]
    else:
        secoes = [_literatura(x), _web(x), _classificacao(x), _verificacao(x), _ufs(x, ufs), _custos(x), _reprodutibilidade(x)]
    return {"secoes": secoes, "ressalvas": ressalvas, "vazio": x.vazio, "texto": _texto_puro(secoes, ressalvas)}
