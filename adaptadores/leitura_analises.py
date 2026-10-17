"""Leituras da pagina /analises (plano de analise de dados e de visualizacao). Mistura em LeituraPainelSQLite: usa
self._consulta(sql, args) e self._um(sql, args). So le; nunca grava. Cada metodo devolve dicionarios e listas simples
(prontos para JSON) com as contagens explicitas, para a pagina mostrar o n de cada grafico.

Regras comuns:
- os numeros vem das views `r_*` (execucoes marcadas para o relatorio) e das views `v_*` ja existentes;
- toda leitura e defensiva: em um banco antigo, sem a tabela ou a view, o metodo devolve o resultado vazio (zeros, listas
  vazias) em vez de falhar;
- proporcoes nunca dividem por zero: sem denominador, o valor e None;
- o que depende de decisao humana traz tambem quantas linhas tem decisao humana (`n_verificados` para achados, `n_humanos`
  para artigos), para a pagina avisar "aguardando verificacao humana" quando for 0."""
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from itertools import combinations

from dominio import estatistica as est
from dominio.auditoria_negativos import amostra_minima_sem_erros
from dominio.concordancia import interpretar_kappa
from dominio.prontidao import prontidao_auditoria, prontidao_h2, prontidao_h5

# ---------- constantes ----------
# Pontuacao ordinal do ciclo de adocao (plano de analise, secao 3.1). `descartado` fica de fora.
PESO_STATUS = {"em_uso": 5, "piloto": 4, "licitacao": 3, "anunciado": 2, "em_estudo": 1, "apenas_citado": 0}

REGIOES = ("Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul")
REGIAO_DA_UF = {
    "AC": "Norte", "AM": "Norte", "AP": "Norte", "PA": "Norte", "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste", "PB": "Nordeste", "PE": "Nordeste",
    "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MS": "Centro-Oeste", "MT": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}

NIVEIS_CONFIANCA = ("alta", "media", "baixa")
FAIXAS_TEXTO = (("<5k", 0, 5000), ("5-20k", 5000, 20000), ("20-60k", 20000, 60000), (">=60k", 60000, None))
_NAO_INFORMADO = {"", "null", "none", "nan", "-", "n/a", "n/d", "nao informado", "não informado", "nao identificado",
                  "não identificado"}
_HTTP_BLOQUEIO = ("http_401", "http_403", "http_429")

# Metas de falso negativo da auditoria dos negativos do modelo (decisao do pesquisador): 5% (meta minima) e 2% (meta rigorosa).
METAS_FALSO_NEGATIVO = (0.05, 0.02)
# Um robots.txt inacessivel so conta como "nao verificavel" se a falha persistiu: 3 leituras na mesma tentativa (o fetcher le ate 3
# vezes antes de concluir) ou ao menos 2 tentativas de download com essa falha (em execucoes ou retomadas diferentes).
LEITURAS_ROBOTS_PERSISTENTE = 3
TENTATIVAS_ROBOTS_PERSISTENTE = 2
CLASSES_NAO_VERIFICAVEIS = ("proibido_pelo_site", "nao_verificavel_robots", "falha_definitiva_404", "outras_falhas")

# Veredito atual (a linha de maior id) de cada item da fonte `?` em triagem_escopo; sempre com um unico argumento.
_TE_ATUAL = ("SELECT te.* FROM triagem_escopo te WHERE te.fonte = ? AND te.id IN "
             "(SELECT MAX(id) FROM triagem_escopo WHERE fonte = ? GROUP BY item_id, uf)")


def _pct(parte, total):
    """Percentual (0 a 100, uma casa) ou None sem denominador."""
    return round(100.0 * parte / total, 1) if total else None


def _taxa(parte, total):
    """Fracao (0 a 1, quatro casas) ou None sem denominador."""
    return round(parte / total, 4) if total else None


def _i(valor):
    return int(valor) if valor is not None else 0


def _chave_fornecedor(texto):
    """Normalizacao leve: espacos colapsados e caixa dobrada. Nao junta grafias diferentes ('Axis' e 'Axis Communications')."""
    return " ".join(str(texto or "").split()).casefold()


def _faixa_texto(n):
    if n is None:
        return "sem_tamanho"
    for nome, ini, fim in FAIXAS_TEXTO:
        if n >= ini and (fim is None or n < fim):
            return nome
    return "sem_tamanho"


class LeituraAnalises:
    """Leituras da pagina /analises. Mistura em LeituraPainelSQLite (usa self._consulta e self._um)."""

    # ---------- infraestrutura ----------
    def _ler(self, sql, args=(), padrao=None):
        """Consulta defensiva: se a tabela ou a view nao existe (banco antigo) ou o banco nao abre, devolve `padrao` ([] se None)."""
        try:
            return self._consulta(sql, args)
        except sqlite3.Error:
            return [] if padrao is None else padrao

    def _ler_um(self, sql, args=(), padrao=None):
        linhas = self._ler(sql, args)
        return linhas[0] if linhas else padrao

    def _tem_triagem_escopo(self):
        return bool(self._ler("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name='triagem_escopo'"))

    # ---------- 1. maturidade UF x tecnologia ----------
    def analise_maturidade_uf_tecnologia(self, somente_confirmados=False):
        """Estagio mais avancado por (uf, tecnologia), contagem por status e tabela regiao x tecnologia (qui-quadrado).

        `somente_confirmados`: so achados `verificado = 1` e `status_final <> 'descartado'` (base `confirmados`, com o status
        final). Senao entram todos os achados nao descartados pela pessoa e vale `status_final` quando verificado, ou
        `status_reportado` (base `status_final_ou_reportado`). `descartado` nunca entra. Achados sem tecnologia ou com status
        fora da escala saem da conta (contados em `n_ignorados`).

        Devolve {base, pesos, n_achados, n_verificados, n_descartados, n_ignorados, n_sem_regiao, tem_dados_humanos,
        regioes: {uf: regiao}, celulas: [{uf, regiao, tecnologia, status_max, peso, por_status, n_achados, n_verificados}],
        contingencia_regiao_tecnologia: {regioes, tecnologias, tabela, n}}."""
        base = "confirmados" if somente_confirmados else "status_final_ou_reportado"
        linhas = self._ler("SELECT uf, tecnologia, status_reportado, status_final, COALESCE(verificado, 0) AS verificado FROM r_achados")
        celulas, n_ign, n_desc, n_total, n_verif = {}, 0, 0, 0, 0
        for l in linhas:
            verificado = _i(l["verificado"]) == 1
            descartado = verificado and l["status_final"] == "descartado"
            if descartado:
                n_desc += 1
                continue
            if somente_confirmados and not verificado:
                continue
            status = (l["status_final"] or l["status_reportado"]) if verificado else l["status_reportado"]
            if not l["tecnologia"] or not l["uf"] or status not in PESO_STATUS:
                n_ign += 1
                continue
            n_total += 1
            n_verif += 1 if verificado else 0
            c = celulas.setdefault((l["uf"], l["tecnologia"]), {"por_status": Counter(), "n_verificados": 0})
            c["por_status"][status] += 1
            c["n_verificados"] += 1 if verificado else 0
        lista = []
        for (uf, tec), c in sorted(celulas.items()):
            top = max(c["por_status"], key=lambda s: PESO_STATUS[s])
            lista.append({"uf": uf, "regiao": REGIAO_DA_UF.get(uf), "tecnologia": tec, "status_max": top, "peso": PESO_STATUS[top],
                          "por_status": {s: c["por_status"].get(s, 0) for s in PESO_STATUS},
                          "n_achados": sum(c["por_status"].values()), "n_verificados": c["n_verificados"]})
        tecnologias = sorted({c["tecnologia"] for c in lista})
        tabela = [[0] * len(tecnologias) for _ in REGIOES]
        n_sem_regiao = 0
        for c in lista:
            if c["regiao"] is None:
                n_sem_regiao += c["n_achados"]
                continue
            tabela[REGIOES.index(c["regiao"])][tecnologias.index(c["tecnologia"])] += c["n_achados"]
        return {"base": base, "pesos": dict(PESO_STATUS), "n_achados": n_total, "n_verificados": n_verif, "n_descartados": n_desc,
                "n_ignorados": n_ign, "n_sem_regiao": n_sem_regiao, "tem_dados_humanos": n_verif > 0,
                "regioes": dict(REGIAO_DA_UF), "celulas": lista,
                "contingencia_regiao_tecnologia": {"regioes": list(REGIOES), "tecnologias": tecnologias, "tabela": tabela,
                                                   "n": sum(sum(l) for l in tabela)}}

    # ---------- 2. LGPD por tecnologia ----------
    def analise_lgpd_por_tecnologia(self):
        """Por tecnologia: achados, quantos tem `evidencia_cita_lgpd = 1` (o trecho literal cita LGPD: o confiavel) e quantos
        tem `menciona_lgpd = 1` (declarado pelo modelo). Achados descartados pela pessoa ficam de fora.

        Devolve {n_achados, n_verificados, n_cita_lgpd, n_menciona_lgpd, tem_dados_humanos, por_tecnologia: [{tecnologia,
        n_achados, n_cita_lgpd, n_menciona_lgpd, pct_cita_lgpd, pct_menciona_lgpd, n_verificados}]}."""
        linhas = self._ler("""
            SELECT COALESCE(tecnologia, '(sem tecnologia)') AS tecnologia, COUNT(*) AS n_achados,
                   COALESCE(SUM(evidencia_cita_lgpd = 1), 0) AS n_cita_lgpd, COALESCE(SUM(menciona_lgpd = 1), 0) AS n_menciona_lgpd,
                   COALESCE(SUM(verificado = 1), 0) AS n_verificados
            FROM r_achados WHERE NOT (verificado = 1 AND status_final = 'descartado')
            GROUP BY COALESCE(tecnologia, '(sem tecnologia)') ORDER BY n_achados DESC, tecnologia""")
        for l in linhas:
            l["pct_cita_lgpd"] = _pct(l["n_cita_lgpd"], l["n_achados"])
            l["pct_menciona_lgpd"] = _pct(l["n_menciona_lgpd"], l["n_achados"])
        return {"n_achados": sum(l["n_achados"] for l in linhas), "n_verificados": sum(l["n_verificados"] for l in linhas),
                "n_cita_lgpd": sum(l["n_cita_lgpd"] for l in linhas), "n_menciona_lgpd": sum(l["n_menciona_lgpd"] for l in linhas),
                "tem_dados_humanos": any(l["n_verificados"] for l in linhas), "por_tecnologia": linhas}

    # ---------- 3. fornecedores ----------
    def analise_fornecedores(self, limite=30):
        """Concentracao de fornecedores. Chave de agrupamento: espacos colapsados e caixa dobrada (nome mostrado: a grafia mais
        frequente). Fornecedor vazio entra em `n_nao_informado`, a parte. Achados descartados pela pessoa ficam de fora.

        Devolve {n_achados, n_informado, n_nao_informado, n_fornecedores, n_verificados, tem_dados_humanos, share_top3 (fracao
        dos achados com fornecedor informado nos 3 maiores, ou None), top: [{fornecedor, chave, n_achados, n_ufs, ufs,
        n_tecnologias, por_tecnologia, pct_do_informado}], por_uf: [{uf, fornecedor, n}] (so os do top)}."""
        limite = min(max(int(limite), 1), 200)
        linhas = self._ler("""SELECT uf, tecnologia, fornecedor, COALESCE(verificado, 0) AS verificado FROM r_achados
                              WHERE NOT (verificado = 1 AND status_final = 'descartado')""")
        grupos, formas, n_nao, n_verif = {}, defaultdict(Counter), 0, 0
        for l in linhas:
            n_verif += _i(l["verificado"])
            chave = _chave_fornecedor(l["fornecedor"])
            if chave in _NAO_INFORMADO:
                n_nao += 1
                continue
            g = grupos.setdefault(chave, {"ufs": Counter(), "tecnologias": Counter(), "n": 0})
            g["n"] += 1
            g["ufs"][l["uf"]] += 1
            g["tecnologias"][l["tecnologia"] or "(sem tecnologia)"] += 1
            formas[chave][" ".join(str(l["fornecedor"]).split())] += 1
        n_inf = sum(g["n"] for g in grupos.values())
        ordem = sorted(grupos.items(), key=lambda kv: (-kv[1]["n"], -len(kv[1]["ufs"]), kv[0]))
        top = [{"fornecedor": sorted(formas[k].items(), key=lambda kv: (-kv[1], kv[0]))[0][0], "chave": k, "n_achados": g["n"],
                "n_ufs": len(g["ufs"]), "ufs": sorted(g["ufs"]), "n_tecnologias": len(g["tecnologias"]),
                "por_tecnologia": dict(sorted(g["tecnologias"].items(), key=lambda kv: (-kv[1], kv[0]))),
                "pct_do_informado": _pct(g["n"], n_inf)} for k, g in ordem[:limite]]
        por_uf = [{"uf": uf, "fornecedor": t["fornecedor"], "n": n}
                  for t, (k, g) in zip(top, ordem) for uf, n in sorted(g["ufs"].items(), key=lambda kv: (-kv[1], kv[0]))]
        return {"n_achados": len(linhas), "n_informado": n_inf, "n_nao_informado": n_nao, "n_fornecedores": len(grupos),
                "n_verificados": n_verif, "tem_dados_humanos": n_verif > 0,
                "share_top3": _taxa(sum(g["n"] for _, g in ordem[:3]), n_inf), "top": top, "por_uf": por_uf}

    # ---------- 4. funil por provedor de busca web ----------
    def analise_funil_por_provedor(self):
        """Degraus do funil por provedor de busca web (so os que tem dados; nunca assume dois): resultados, URLs unicas,
        paginas com texto, classificacoes relevantes, achados e confirmados (verificado e nao descartado). Uma URL achada por
        mais de um provedor conta para cada um. O custo e o das chamadas de busca do provedor.

        Devolve {n_provedores, n_verificados, tem_dados_humanos, provedores: [{provedor, n_consultas, custo_usd, resultados,
        urls_unicas, paginas_com_texto, classificacoes_relevantes, achados, achados_verificados, confirmados, etapas:
        [{chave, rotulo, n}]}]}."""
        # poucas consultas, agregadas em Python: cada varredura de resultados_web/chamadas custa caro em disco lento
        consultas = {}                                # chamada_id -> provedor; custo e contagem por provedor
        base = {}
        for c in self._ler("SELECT chamada_id, provedor, custo_usd FROM r_chamadas WHERE etapa = 'busca_web' AND sucesso = 1"):
            consultas[c["chamada_id"]] = c["provedor"]
            b = base.setdefault(c["provedor"], {"provedor": c["provedor"], "n_consultas": 0, "custo_usd": 0.0})
            b["n_consultas"] += 1
            b["custo_usd"] += c["custo_usd"] or 0.0
        base = [base[k] for k in sorted(base)]
        achados_por_par = {(l["url_id"], l["uf"]): l for l in self._ler("""
            SELECT k.url_id, k.uf, MAX(COALESCE(k.relevante, 0)) AS relevante, COUNT(a.achado_id) AS achados,
                   COALESCE(SUM(a.verificado = 1), 0) AS verificados,
                   COALESCE(SUM(a.verificado = 1 AND COALESCE(a.status_final, '') <> 'descartado'), 0) AS confirmados
            FROM r_classificacoes k LEFT JOIN r_achados a ON a.classificacao_id = k.classificacao_id GROUP BY k.url_id, k.uf""")}
        com_texto = {l["url_id"] for l in self._ler("SELECT DISTINCT url_id FROM r_paginas WHERE extracao_ok = 1")}
        acum = {}
        pares = Counter((consultas[r["chamada_id"]], r["url_id"], r["uf"]) for r in self._ler(
            "SELECT chamada_id, url_id, uf FROM r_resultados_web") if r["chamada_id"] in consultas)
        for (provedor, url_id, uf), n in pares.items():
            a = acum.setdefault(provedor, {"resultados": 0, "urls": set(), "texto": set(), "rel": 0, "ach": 0, "ver": 0, "conf": 0})
            a["resultados"] += n
            a["urls"].add(url_id)
            if url_id in com_texto:
                a["texto"].add(url_id)
            k = achados_por_par.get((url_id, uf))
            if k:
                a["rel"] += 1 if _i(k["relevante"]) else 0
                a["ach"] += k["achados"]
                a["ver"] += k["verificados"]
                a["conf"] += k["confirmados"]
        provedores = []
        for b in base:
            a = acum.get(b["provedor"]) or {"resultados": 0, "urls": set(), "texto": set(), "rel": 0, "ach": 0, "ver": 0, "conf": 0}
            d = {"provedor": b["provedor"], "n_consultas": b["n_consultas"], "custo_usd": round(b["custo_usd"], 6), "resultados": a["resultados"],
                 "urls_unicas": len(a["urls"]), "paginas_com_texto": len(a["texto"]), "classificacoes_relevantes": a["rel"],
                 "achados": a["ach"], "achados_verificados": a["ver"], "confirmados": a["conf"]}
            d["etapas"] = [{"chave": k, "rotulo": r, "n": d[k]} for k, r in (
                ("resultados", "Resultados"), ("urls_unicas", "URLs únicas"), ("paginas_com_texto", "Páginas com texto"),
                ("classificacoes_relevantes", "Classificações relevantes"), ("achados", "Achados"), ("confirmados", "Confirmados"))]
            provedores.append(d)
        n_verif = sum(p["achados_verificados"] for p in provedores)
        return {"n_provedores": len(provedores), "n_verificados": n_verif, "tem_dados_humanos": n_verif > 0, "provedores": provedores}

    # ---------- 5. retorno por posicao ----------
    def analise_retorno_por_posicao(self, fonte):
        """Retorno por posicao no ranking. `fonte`: 'web' (uma linha por posicao 1..10) ou 'scholar' (faixas de 10 posicoes).

        web: n_resultados, n_selecionados (marcados para download), n_com_achados, n_confirmados (verificados e nao
        descartados), n_triados (veredito valido de `triagem_escopo`), n_elegiveis. scholar: n_ocorrencias, n_artigos, n_triados,
        n_elegiveis, n_humanos (decisao diferente de pendente) e n_incluidos (incluir). Sem `triagem_escopo` os campos de escopo
        vem 0. Devolve {fonte, agrupamento, n_total, n_verificados (web) ou n_humanos (scholar), tem_dados_humanos, linhas}."""
        if fonte == "web":
            return self._retorno_web()
        if fonte == "scholar":
            return self._retorno_scholar()
        raise ValueError("fonte deve ser 'web' ou 'scholar'")

    def _retorno_web(self):
        selecionados = {(l["url_id"], l["uf"]) for l in self._ler(
            "SELECT DISTINCT url_id, uf FROM r_selecao_download WHERE selecionada = 1")}
        status = {(l["url_id"], l["uf"]): l for l in self._ler("SELECT url_id, uf, n_achados, confirmado FROM v_status_url")}
        escopo = {}
        if self._tem_triagem_escopo():
            escopo = {(l["item_id"], l["uf"]): l for l in self._ler(
                "SELECT item_id, uf, status, valido FROM (" + _TE_ATUAL + ")", ("web", "web"))}
        por_pos = {}
        for r in self._ler("SELECT posicao, url_id, uf FROM r_resultados_web WHERE posicao IS NOT NULL"):
            chave = (r["url_id"], r["uf"])
            p = por_pos.setdefault(r["posicao"], {"posicao": r["posicao"], "n_resultados": 0, "n_selecionados": 0, "n_com_achados": 0,
                                                  "n_confirmados": 0, "n_triados": 0, "n_elegiveis": 0})
            s, e = status.get(chave), escopo.get(chave)
            p["n_resultados"] += 1
            p["n_selecionados"] += 1 if chave in selecionados else 0
            p["n_com_achados"] += 1 if s and _i(s["n_achados"]) > 0 else 0
            p["n_confirmados"] += 1 if s and _i(s["confirmado"]) == 1 else 0
            if e and _i(e["valido"]) == 1:
                p["n_triados"] += 1
                p["n_elegiveis"] += 1 if e["status"] == "elegivel" else 0
        linhas = [por_pos[k] for k in sorted(por_pos)]
        for l in linhas:
            l["pct_com_achados"] = _pct(l["n_com_achados"], l["n_resultados"])
            l["pct_elegiveis"] = _pct(l["n_elegiveis"], l["n_triados"])
        n_verif = _i((self._ler_um("SELECT COALESCE(SUM(verificado), 0) AS n FROM r_achados") or {}).get("n"))
        return {"fonte": "web", "agrupamento": "posicao", "n_total": sum(l["n_resultados"] for l in linhas), "n_verificados": n_verif,
                "tem_dados_humanos": n_verif > 0, "linhas": linhas}

    def _escopo_artigos(self):
        """{artigo_id: (status, valido)} do veredito atual de cada artigo na triagem de escopo ({} sem a tabela)."""
        if not self._tem_triagem_escopo():
            return {}
        return {l["item_id"]: (l["status"], _i(l["valido"])) for l in self._ler(
            "SELECT item_id, status, valido FROM (" + _TE_ATUAL + ") WHERE uf = ''", ("artigo", "artigo"))}

    def _decisoes_humanas(self):
        """{artigo_id: decisao} da triagem humana por titulo e resumo (so incluir ou excluir; pendente nao entra)."""
        return {l["artigo_id"]: l["decisao"] for l in self._ler(
            "SELECT artigo_id, decisao FROM triagem WHERE decisao IN ('incluir', 'excluir')")}

    def _retorno_scholar(self):
        escopo, humanos = self._escopo_artigos(), self._decisoes_humanas()
        faixas = {}
        for o in self._ler("SELECT artigo_id, posicao FROM r_ocorrencias WHERE posicao >= 1"):
            f = faixas.setdefault((o["posicao"] - 1) // 10, {"n_ocorrencias": 0, "artigos": set()})
            f["n_ocorrencias"] += 1
            f["artigos"].add(o["artigo_id"])
        linhas = []
        for k in sorted(faixas):
            arts = faixas[k]["artigos"]
            validos = [escopo[a] for a in arts if a in escopo and escopo[a][1] == 1]
            l = {"n_ocorrencias": faixas[k]["n_ocorrencias"], "n_artigos": len(arts),
                 "n_humanos": sum(1 for a in arts if a in humanos), "n_incluidos": sum(1 for a in arts if humanos.get(a) == "incluir"),
                 "n_triados": len(validos), "n_elegiveis": sum(1 for v in validos if v[0] == "elegivel"),
                 "posicao_de": k * 10 + 1, "posicao_ate": k * 10 + 10}
            l["rotulo"] = f"{l['posicao_de']}-{l['posicao_ate']}"
            l["pct_elegiveis"] = _pct(l["n_elegiveis"], l["n_triados"])
            l["pct_incluidos"] = _pct(l["n_incluidos"], l["n_humanos"])
            linhas.append(l)
        return {"fonte": "scholar", "agrupamento": "faixa_10", "n_total": sum(l["n_ocorrencias"] for l in linhas),
                "n_humanos": len(humanos), "tem_dados_humanos": bool(humanos), "linhas": linhas}

    # ---------- 6. literatura ----------
    def analise_literatura_temporal(self):
        """Artigos por ano x grupo de termo (`v_termos.grupo`). Um artigo conta uma vez em cada grupo que o achou (e uma vez
        por ano em `por_ano`). Elegivel: veredito atual valido da `triagem_escopo`; incluido: `triagem.decisao = 'incluir'`.
        Ano ausente vira None; artigo sem termo conhecido, grupo `sem_grupo`.

        Devolve {n_artigos, n_humanos, n_triagem_escopo, tem_dados_humanos, anos, grupos, celulas: [{ano, grupo, n_artigos,
        n_elegiveis, n_incluidos, n_humanos}], por_ano: [{ano, n_artigos, n_elegiveis, n_incluidos, n_humanos}]}."""
        escopo, humanos = self._escopo_artigos(), self._decisoes_humanas()
        grupos_do_artigo = defaultdict(set)
        for l in self._ler("""SELECT DISTINCT o.artigo_id, tm.grupo FROM v_ocorrencias_fonte o
                              LEFT JOIN v_termos tm ON tm.termo_id = o.termo_id"""):
            grupos_do_artigo[l["artigo_id"]].add(l["grupo"] or "sem_grupo")
        artigos = self._ler("SELECT artigo_id, ano FROM r_artigos")
        celulas, por_ano = {}, {}
        for a in artigos:
            ident = a["artigo_id"]
            m = (1 if ident in escopo and escopo[ident][1] == 1 and escopo[ident][0] == "elegivel" else 0,
                 1 if humanos.get(ident) == "incluir" else 0, 1 if ident in humanos else 0)
            for destino, chave in [(por_ano, (a["ano"], None))] + [(celulas, (a["ano"], g)) for g in grupos_do_artigo.get(ident) or {"sem_grupo"}]:
                c = destino.setdefault(chave, [0, 0, 0, 0])
                c[0] += 1
                c[1] += m[0]
                c[2] += m[1]
                c[3] += m[2]

        def linha(chave, c, com_grupo):
            d = {"ano": chave[0]}
            if com_grupo:
                d["grupo"] = chave[1]
            d.update({"n_artigos": c[0], "n_elegiveis": c[1], "n_incluidos": c[2], "n_humanos": c[3]})
            return d

        ordem = lambda kv: (kv[0][0] is None, kv[0][0] or 0, str(kv[0][1]))
        return {"n_artigos": len(artigos), "n_humanos": sum(1 for a in artigos if a["artigo_id"] in humanos),
                "n_triagem_escopo": len(escopo), "tem_dados_humanos": bool(humanos),
                "anos": sorted({k[0] for k in celulas if k[0] is not None}), "grupos": sorted({k[1] for k in celulas}),
                "celulas": [linha(k, c, True) for k, c in sorted(celulas.items(), key=ordem)],
                "por_ano": [linha(k, c, False) for k, c in sorted(por_ano.items(), key=ordem)]}

    def analise_multitermo(self):
        """Artigos por numero de termos distintos que o devolveram (1, 2, 3, 4 ou mais; `v_artigos_multi_termo`, so buscas
        do Google Scholar): n_artigos, quantos foram triados pelo escopo e quantos elegiveis, e a taxa de inclusao humana.

        Devolve {n_artigos, n_humanos, tem_dados_humanos, faixas: [{faixa ('1','2','3','4+'), n_termos_min, n_artigos,
        n_triados, n_elegiveis, pct_elegiveis, n_humanos, n_incluidos, pct_incluidos, citacoes_media}]}."""
        escopo, humanos = self._escopo_artigos(), self._decisoes_humanas()
        grupos = {}
        for m in self._ler("SELECT artigo_id, n_termos, citacoes FROM v_artigos_multi_termo"):
            g = grupos.setdefault(min(m["n_termos"], 4), {"ids": [], "cit": []})
            g["ids"].append(m["artigo_id"])
            if m["citacoes"] is not None:
                g["cit"].append(m["citacoes"])
        faixas = []
        for k in sorted(grupos):
            ids = grupos[k]["ids"]
            validos = [escopo[a] for a in ids if a in escopo and escopo[a][1] == 1]
            f = {"faixa": "4+" if k >= 4 else str(k), "n_termos_min": k, "n_artigos": len(ids), "n_triados": len(validos),
                 "n_elegiveis": sum(1 for v in validos if v[0] == "elegivel"), "n_humanos": sum(1 for a in ids if a in humanos),
                 "n_incluidos": sum(1 for a in ids if humanos.get(a) == "incluir"),
                 "citacoes_media": round(sum(grupos[k]["cit"]) / len(grupos[k]["cit"]), 1) if grupos[k]["cit"] else None}
            f["pct_elegiveis"] = _pct(f["n_elegiveis"], f["n_triados"])
            f["pct_incluidos"] = _pct(f["n_incluidos"], f["n_humanos"])
            faixas.append(f)
        n_hum = sum(f["n_humanos"] for f in faixas)
        return {"n_artigos": sum(f["n_artigos"] for f in faixas), "n_humanos": n_hum, "tem_dados_humanos": n_hum > 0, "faixas": faixas}

    # ---------- 7. calibracao da confianca ----------
    def analise_calibracao_confianca(self):
        """Por nivel de confianca (alta, media, baixa): achados, verificados, confirmados (verificado e `status_final <>
        'descartado'`) e descartados; taxa de confirmacao sobre os verificados (None sem verificados). `ajuste` compara
        `confianca_original` com `confianca` (rebaixamento automatico quando o texto e so snippet).

        Devolve {n_achados, n_verificados, tem_dados_humanos, por_confianca: [{confianca, n_achados, n_verificados, n_confirmados,
        n_descartados, taxa_confirmacao}], ajuste: {n_com_original, n_rebaixados, matriz: [{original, final, n, n_verificados,
        n_confirmados, n_descartados}], rebaixados: {n, n_verificados, n_confirmados, n_descartados}}}."""
        def soma(prefixo=""):
            return (f"COUNT(*) AS n_achados, COALESCE(SUM({prefixo}verificado = 1), 0) AS n_verificados, "
                    f"COALESCE(SUM({prefixo}verificado = 1 AND COALESCE({prefixo}status_final, '') <> 'descartado'), 0) AS n_confirmados, "
                    f"COALESCE(SUM({prefixo}verificado = 1 AND {prefixo}status_final = 'descartado'), 0) AS n_descartados")
        linhas = self._ler(f"SELECT COALESCE(confianca, '(sem)') AS confianca, {soma()} FROM r_achados GROUP BY COALESCE(confianca, '(sem)')")
        ordem = {n: i for i, n in enumerate(NIVEIS_CONFIANCA)}
        linhas.sort(key=lambda l: (ordem.get(l["confianca"], 99), l["confianca"]))
        for l in linhas:
            l["taxa_confirmacao"] = _taxa(l["n_confirmados"], l["n_verificados"])
        matriz = self._ler(f"""SELECT confianca_original AS original, confianca AS final, {soma()} FROM r_achados
                               WHERE confianca_original IS NOT NULL GROUP BY confianca_original, confianca
                               ORDER BY confianca_original, confianca""")
        for m in matriz:
            m["n"] = m.pop("n_achados")
        reb = [m for m in matriz if m["original"] != m["final"]]
        n_verif = sum(l["n_verificados"] for l in linhas)
        return {"n_achados": sum(l["n_achados"] for l in linhas), "n_verificados": n_verif, "tem_dados_humanos": n_verif > 0,
                "por_confianca": linhas,
                "ajuste": {"n_com_original": sum(m["n"] for m in matriz), "n_rebaixados": sum(m["n"] for m in reb), "matriz": matriz,
                           "rebaixados": {k: sum(m[k] for m in reb) for k in ("n", "n_verificados", "n_confirmados", "n_descartados")}}}

    # ---------- 8. falsa exclusao ----------
    def analise_falsa_exclusao(self):
        """Tabela status do modelo (`triagem_escopo`, veredito atual valido de cada artigo) x decisao humana (`triagem.decisao`:
        incluir, excluir, pendente). Falsa exclusao = o modelo excluiu e a pessoa quis incluir.

        A taxa de falsa exclusao e sobre os artigos que o MODELO EXCLUIU e que uma pessoa CONFERIU (`n_excluidos_checados`),
        nao sobre todos os artigos triados por humano: o painel esconde por padrao os itens excluidos pelo modelo, entao uma
        fila humana feita so de elegiveis e quarentena daria zero falsas exclusoes por construcao e nao mediria nada.
        Sem excluidos conferidos, a taxa e None.

        Devolve {n_artigos_com_veredito, n_invalidos, n_humanos (artigos com veredito e decisao incluir ou excluir, de
        qualquer status; mantido por compatibilidade), n_excluidos (veredito valido atual 'excluido'), n_excluidos_checados
        (desses, com decisao humana incluir ou excluir), n_falsas_exclusoes, taxa_falsa_exclusao (n_falsas_exclusoes /
        n_excluidos_checados, ou None), tem_dados_humanos (n_humanos > 0), tem_excluidos_checados (n_excluidos_checados > 0),
        cruzamento: {status: {incluir, excluir, pendente}}, por_categoria_falsa: {categoria: n},
        falsas_exclusoes: [{artigo_id, categoria_motivo, titulo, ano}]}."""
        status = ("elegivel", "quarentena", "excluido")
        decisoes = ("incluir", "excluir", "pendente")
        cruz = {s: {d: 0 for d in decisoes} for s in status}
        vazio = {"n_artigos_com_veredito": 0, "n_invalidos": 0, "n_humanos": 0, "n_excluidos": 0, "n_excluidos_checados": 0,
                 "n_falsas_exclusoes": 0, "taxa_falsa_exclusao": None, "tem_dados_humanos": False, "tem_excluidos_checados": False,
                 "cruzamento": cruz, "por_categoria_falsa": {}, "falsas_exclusoes": []}
        if not self._tem_triagem_escopo():
            return vazio
        linhas = self._ler(f"""
            SELECT te.item_id AS artigo_id, te.status, te.valido, te.categoria_motivo, COALESCE(t.decisao, 'pendente') AS decisao,
                   a.titulo, a.ano
            FROM ({_TE_ATUAL}) te LEFT JOIN triagem t ON t.artigo_id = te.item_id LEFT JOIN artigos a ON a.artigo_id = te.item_id
            ORDER BY te.item_id""", ("artigo", "artigo"))
        n_inval, n_hum, falsas = 0, 0, []
        for l in linhas:
            if _i(l["valido"]) != 1:
                n_inval += 1
                continue
            if l["status"] not in cruz:
                continue
            d = l["decisao"] if l["decisao"] in decisoes else "pendente"
            cruz[l["status"]][d] += 1
            n_hum += 1 if d in ("incluir", "excluir") else 0
            if l["status"] == "excluido" and d == "incluir":
                falsas.append({"artigo_id": l["artigo_id"], "categoria_motivo": l["categoria_motivo"], "titulo": l["titulo"], "ano": l["ano"]})
        n_exc = sum(cruz["excluido"].values())
        n_exc_chec = cruz["excluido"]["incluir"] + cruz["excluido"]["excluir"]
        por_cat = Counter(f["categoria_motivo"] or "(sem motivo)" for f in falsas)
        return {"n_artigos_com_veredito": len(linhas) - n_inval, "n_invalidos": n_inval, "n_humanos": n_hum,
                "n_excluidos": n_exc, "n_excluidos_checados": n_exc_chec,
                "n_falsas_exclusoes": len(falsas), "taxa_falsa_exclusao": _taxa(len(falsas), n_exc_chec), "tem_dados_humanos": n_hum > 0,
                "tem_excluidos_checados": n_exc_chec > 0,
                "cruzamento": cruz, "por_categoria_falsa": dict(sorted(por_cat.items(), key=lambda kv: (-kv[1], kv[0]))),
                "falsas_exclusoes": falsas}

    # ---------- 9. opacidade dos dominios ----------
    def analise_opacidade_dominios(self, limite=40):
        """Resultado do download por dominio final (`v_resultado_download`, execucoes do relatorio; uma pagina = uma URL por
        execucao): tentadas, ok, proibidas pelo robots.txt (lido e proibindo), proibidas por HTTP 401/403/429, com robots.txt
        inacessivel (bloqueadas pela politica da RFC 9309, nao e proibicao do site) e outros erros (inclui falha de extracao
        e 404). `pct_bloqueado` = (robots + HTTP de bloqueio) sobre as tentadas: so a proibicao real; `pct_inacessivel` conta
        as de robots.txt inacessivel. O valor antigo `bloqueado_por_robots` (antes de `migrar-robots`) conta como proibicao.

        Devolve {n_tentadas, n_ok, n_robots, n_http_bloqueio, n_robots_inacessivel, n_outros, pct_bloqueado, pct_inacessivel,
        motivos: [{motivo, n}], dominios: [{dominio, n_tentadas, n_ok, n_robots, n_http_bloqueio, n_robots_inacessivel,
        n_outros, pct_bloqueado, pct_inacessivel, fonte_oficial, n_ufs}] (os com mais proibicoes primeiro, ate `limite`),
        n_dominios, por_uf: [{uf, n_tentadas, ...}]}."""
        limite = min(max(int(limite), 1), 500)

        # uma unica leitura da view (cara em disco lento); a agregacao por dominio, por UF e por motivo e feita aqui
        linhas = self._ler("""
            SELECT run_id, url_id, uf, COALESCE(dominio_final, dominio, '(sem dominio)') AS dominio,
                   COALESCE(fonte_oficial_final, fonte_oficial) AS fonte_oficial, resultado, motivo
            FROM v_resultado_download WHERE no_relatorio = 1 AND resultado <> 'nao_tentada'""")

        def novo():
            return {"paginas": set(), "ok": set(), "robots": set(), "http": set(), "inacessivel": set(), "ufs": set(), "oficial": None}

        por_dominio, por_uf, motivos = {}, {}, Counter()
        for l in linhas:
            pagina = (l["run_id"], l["url_id"])
            motivos[l["motivo"]] += 1
            for tabela, chave in ((por_dominio, l["dominio"]), (por_uf, l["uf"])):
                a = tabela.setdefault(chave, novo())
                a["paginas"].add(pagina)
                a["ufs"].add(l["uf"])
                if l["fonte_oficial"] is not None:
                    a["oficial"] = max(a["oficial"] or 0, _i(l["fonte_oficial"]))
                if l["resultado"] == "ok":
                    a["ok"].add(pagina)
                if l["motivo"] == "bloqueado_por_robots":
                    a["robots"].add(pagina)
                elif l["motivo"] == "robots_inacessivel":
                    a["inacessivel"].add(pagina)
                elif l["motivo"] in _HTTP_BLOQUEIO:
                    a["http"].add(pagina)

        def fechar(a, **extra):
            d = dict(extra, n_tentadas=len(a["paginas"]), n_ok=len(a["ok"]), n_robots=len(a["robots"]), n_http_bloqueio=len(a["http"]),
                     n_robots_inacessivel=len(a["inacessivel"]))
            d["n_outros"] = max(d["n_tentadas"] - d["n_ok"] - d["n_robots"] - d["n_http_bloqueio"] - d["n_robots_inacessivel"], 0)
            d["pct_bloqueado"] = _pct(d["n_robots"] + d["n_http_bloqueio"], d["n_tentadas"])
            d["pct_inacessivel"] = _pct(d["n_robots_inacessivel"], d["n_tentadas"])
            return d

        dominios = [fechar(a, dominio=k, fonte_oficial=a["oficial"], n_ufs=len(a["ufs"])) for k, a in por_dominio.items()]
        dominios.sort(key=lambda d: (-(d["n_robots"] + d["n_http_bloqueio"]), -d["n_tentadas"], d["dominio"]))
        total = fechar({"paginas": {p for a in por_dominio.values() for p in a["paginas"]},
                        "ok": {p for a in por_dominio.values() for p in a["ok"]},
                        "robots": {p for a in por_dominio.values() for p in a["robots"]},
                        "http": {p for a in por_dominio.values() for p in a["http"]},
                        "inacessivel": {p for a in por_dominio.values() for p in a["inacessivel"]}})
        total.update({"motivos": [{"motivo": m, "n": n} for m, n in sorted(motivos.items(), key=lambda kv: (-kv[1], str(kv[0])))],
                      "n_dominios": len(dominios), "dominios": dominios[:limite],
                      "por_uf": [fechar(a, uf=k) for k, a in sorted(por_uf.items())]})
        return total

    # ---------- 10. saturacao ----------
    def analise_saturacao(self):
        """Curva de descoberta de artigos na ordem das chamadas (`v_curva_descoberta`): em cada chamada bem-sucedida da busca
        academica, quantos artigos eram novos e o acumulado. Devolve {n_chamadas, n_novos_total, pct_novos_ultimas_5 (media
        dos ultimos 5 `pct_novos` conhecidos, ou None), curva: [{ordem, chamada_id, termo_id, pagina, n_retornados, n_novos,
        novos_acumulado, pct_novos}]}."""
        linhas = self._ler("SELECT chamada_id, termo_id, pagina, n_retornados, n_novos, pct_novos, novos_acumulado FROM v_curva_descoberta ORDER BY chamada_id")
        curva, acum = [], 0
        for i, l in enumerate(linhas, 1):
            acum = l["novos_acumulado"] if l["novos_acumulado"] is not None else acum + _i(l["n_novos"])
            curva.append({"ordem": i, "chamada_id": l["chamada_id"], "termo_id": l["termo_id"], "pagina": l["pagina"],
                          "n_retornados": l["n_retornados"], "n_novos": l["n_novos"], "novos_acumulado": acum, "pct_novos": l["pct_novos"]})
        ultimos = [c["pct_novos"] for c in curva if c["pct_novos"] is not None][-5:]
        return {"n_chamadas": len(curva), "n_novos_total": acum if curva else 0,
                "pct_novos_ultimas_5": round(sum(ultimos) / len(ultimos), 1) if ultimos else None, "curva": curva}

    # ---------- 11. calibracao de tokens ----------
    def analise_calibracao_tokens(self):
        """Caracteres enviados x `tokens_entrada` em cada chamada de classificacao (checagem do 3,4 caracteres por token).
        A razao chars/tokens inclui o texto do prompt nos tokens, entao e menor que a do texto sozinho; `regressao` ajusta
        tokens = intercepto + inclinacao x chars, e `chars_por_token_marginal` (1 / inclinacao) descarta o prompt fixo.

        Devolve {n, razao_mediana, razao_media, regressao: {intercepto, inclinacao, chars_por_token_marginal, r2} ou None,
        por_classificador: [{classificador, n, razao_mediana}], pares: [[n_chars_enviados, tokens_entrada], ...]}."""
        # historico (toda chamada feita), nao so a classificacao vigente: a calibracao e sobre as chamadas
        linhas = self._ler("""
            SELECT k.n_chars_enviados AS chars, c.tokens_entrada AS tokens, k.classificador
            FROM r_classificacoes_historico k JOIN r_chamadas c ON c.chamada_id = k.chamada_id
            WHERE c.etapa = 'classificacao' AND k.n_chars_enviados > 0 AND c.tokens_entrada > 0 ORDER BY k.classificacao_id""")
        razoes = [l["chars"] / l["tokens"] for l in linhas]
        reg = None
        n = len(linhas)
        if n >= 3:
            mx, my = sum(l["chars"] for l in linhas) / n, sum(l["tokens"] for l in linhas) / n
            sxx = sum((l["chars"] - mx) ** 2 for l in linhas)
            sxy = sum((l["chars"] - mx) * (l["tokens"] - my) for l in linhas)
            syy = sum((l["tokens"] - my) ** 2 for l in linhas)
            if sxx > 0:
                b = sxy / sxx
                reg = {"intercepto": round(my - b * mx, 2), "inclinacao": round(b, 6),
                       "chars_por_token_marginal": round(1 / b, 3) if b > 0 else None, "r2": round(sxy * sxy / (sxx * syy), 4) if syy > 0 else None}
        por = defaultdict(list)
        for l, r in zip(linhas, razoes):
            por[l["classificador"] or "(sem)"].append(r)
        return {"n": n, "razao_mediana": round(statistics.median(razoes), 3) if razoes else None,
                "razao_media": round(sum(razoes) / n, 3) if razoes else None, "regressao": reg,
                "por_classificador": [{"classificador": k, "n": len(v), "razao_mediana": round(statistics.median(v), 3)} for k, v in sorted(por.items())],
                "pares": [[l["chars"], l["tokens"]] for l in linhas]}

    # ---------- 12. tamanho do texto x achados ----------
    def analise_tamanho_texto_achados(self, origem_texto=None):
        """Hipotese H6: por classificacao, texto enviado x JSON valido x achados. Faixas de caracteres enviados: <5k, 5-20k,
        20-60k, >=60k (o texto e truncado em 60 mil). `origem_texto` ('pagina' ou 'snippet') filtra; sem filtro entram todas.
        `achados_por_mil_chars` = soma dos achados / soma dos caracteres x 1000, so nas classificacoes com JSON valido.

        Devolve {n, n_json_invalido, n_truncados, truncamento: {truncados, integros} cada um com {n, n_json_invalido,
        taxa_json_invalido}, faixas: [{faixa, n, n_json_invalido, taxa_json_invalido, n_truncados, n_achados,
        achados_por_classificacao, achados_por_mil_chars}], pares: [[n_chars_enviados, n_achados, json_valido], ...]}."""
        onde, args = ("WHERE origem_texto = ?", (origem_texto,)) if origem_texto else ("", ())
        # historico: a hipotese e sobre o comportamento do modelo por tamanho de texto, em cada chamada feita
        linhas = self._ler(f"""SELECT n_chars_enviados AS chars, COALESCE(texto_truncado, 0) AS truncado, json_valido,
                                      COALESCE(n_achados, 0) AS n_achados
                               FROM r_classificacoes_historico {onde} ORDER BY classificacao_id""", args)
        acum = {}
        for nome, _, _ in FAIXAS_TEXTO:
            acum[nome] = {"n": 0, "inval": 0, "trunc": 0, "ach": 0, "ach_ok": 0, "chars_ok": 0, "n_ok": 0}
        acum["sem_tamanho"] = dict(acum[FAIXAS_TEXTO[0][0]])
        trunc = {1: [0, 0], 0: [0, 0]}
        for l in linhas:
            a = acum[_faixa_texto(l["chars"])]
            invalido = _i(l["json_valido"]) != 1
            a["n"] += 1
            a["inval"] += 1 if invalido else 0
            a["trunc"] += 1 if _i(l["truncado"]) else 0
            a["ach"] += l["n_achados"]
            if not invalido and l["chars"]:
                a["ach_ok"] += l["n_achados"]
                a["chars_ok"] += l["chars"]
                a["n_ok"] += 1
            t = trunc[1 if _i(l["truncado"]) else 0]
            t[0] += 1
            t[1] += 1 if invalido else 0
        faixas = [{"faixa": k, "n": a["n"], "n_json_invalido": a["inval"], "taxa_json_invalido": _taxa(a["inval"], a["n"]),
                   "n_truncados": a["trunc"], "n_achados": a["ach"], "achados_por_classificacao": round(a["ach"] / a["n"], 3) if a["n"] else None,
                   "achados_por_mil_chars": round(1000.0 * a["ach_ok"] / a["chars_ok"], 4) if a["chars_ok"] else None}
                  for k, a in acum.items() if a["n"] or k != "sem_tamanho"]
        def resumo(t):
            return {"n": t[0], "n_json_invalido": t[1], "taxa_json_invalido": _taxa(t[1], t[0])}
        return {"n": len(linhas), "n_json_invalido": sum(a["inval"] for a in acum.values()),
                "n_truncados": trunc[1][0], "truncamento": {"truncados": resumo(trunc[1]), "integros": resumo(trunc[0])},
                "faixas": faixas, "pares": [[l["chars"], l["n_achados"], _i(l["json_valido"])] for l in linhas]}

    # ---------- 13. termos da triagem de escopo ----------
    def analise_termos_triagem_escopo(self, fonte="artigo"):
        """Ficha de ruido por termo de busca, reaproveitando `dominio.refinamento_busca.ficha_por_termo` sobre os vereditos
        atuais (so artigos tem termo cadastrado em `v_termos`: as consultas web tem outro texto, entao ficam sem `termo_id`).
        Cada ficha ganha `termo_id` e `grupo` quando o texto da consulta e o de um termo conhecido.

        Devolve {fonte, n_itens, n_termos, termos: [ficha de ficha_por_termo + termo_id + grupo]}."""
        from dominio.refinamento_busca import ficha_por_termo
        if fonte not in ("artigo", "web") or not self._tem_triagem_escopo():
            return {"fonte": fonte, "n_itens": 0, "n_termos": 0, "termos": []}
        linhas = self._ler(f"SELECT item_id, uf, status, valido, termos_consulta, categoria_motivo, termo_gerador, sinal_negativo, "
                           f"dominio_tematico, escopo_geografico FROM ({_TE_ATUAL})", (fonte, fonte))
        ids = {" ".join(str(l["query"] or "").split()): l for l in self._ler("SELECT termo_id, query, grupo FROM v_termos")}
        fichas = ficha_por_termo(linhas)
        for f in fichas:
            t = ids.get(" ".join(f["termo"].split()))
            f["termo_id"], f["grupo"] = (t["termo_id"], t["grupo"]) if t else (None, None)
        return {"fonte": fonte, "n_itens": len(linhas), "n_termos": len(fichas), "termos": fichas}

    # ---------- 14. resumo ----------
    def analise_resumo(self):
        """Disponibilidade dos dados para a pagina: contagens e se ha decisao humana.

        Devolve {n_achados, n_verificados, n_confirmados, n_artigos, n_triagem_humana, n_triagem_texto_completo,
        n_classificacoes, n_paginas_baixadas, n_chamadas_busca_web, n_chamadas_busca_academica, n_triagem_escopo: {fonte: itens com
        veredito atual}, provedores: {busca_web, busca_academica, classificacao, triagem_escopo: [..]}, tem_dados_humanos_achados,
        tem_dados_humanos_artigos, tem_dados_humanos}."""
        def n(sql):
            return _i((self._ler_um(sql) or {}).get("n"))

        a = self._ler_um("""SELECT COUNT(*) AS n, COALESCE(SUM(verificado = 1), 0) AS verificados,
                                   COALESCE(SUM(verificado = 1 AND COALESCE(status_final, '') <> 'descartado'), 0) AS confirmados
                            FROM r_achados""") or {}
        provedores = {"busca_web": [], "busca_academica": [], "classificacao": [], "triagem_escopo": []}
        n_chamadas = {"busca_web": 0, "busca_academica": 0}
        for l in self._ler("SELECT etapa, provedor, COALESCE(SUM(sucesso), 0) AS ok FROM r_chamadas GROUP BY etapa, provedor ORDER BY provedor"):
            if l["etapa"] in provedores:
                provedores[l["etapa"]].append(l["provedor"])
            if l["etapa"] in n_chamadas:
                n_chamadas[l["etapa"]] += l["ok"]
        te = {}
        if self._tem_triagem_escopo():
            for l in self._ler("""SELECT fonte, provedor, COUNT(*) AS n FROM triagem_escopo WHERE id IN
                                  (SELECT MAX(id) FROM triagem_escopo GROUP BY fonte, item_id, uf) GROUP BY fonte, provedor"""):
                te[l["fonte"]] = te.get(l["fonte"], 0) + l["n"]
                if l["provedor"] and l["provedor"] not in provedores["triagem_escopo"]:
                    provedores["triagem_escopo"].append(l["provedor"])
            provedores["triagem_escopo"].sort()
        n_hum = n("SELECT COUNT(*) AS n FROM triagem WHERE decisao IN ('incluir', 'excluir')")
        n_ver = _i(a.get("verificados"))
        return {"n_achados": _i(a.get("n")), "n_verificados": n_ver, "n_confirmados": _i(a.get("confirmados")),
                "n_artigos": n("SELECT COUNT(*) AS n FROM r_artigos"), "n_triagem_humana": n_hum,
                "n_triagem_texto_completo": n("SELECT COUNT(*) AS n FROM triagem WHERE decisao_texto_completo IN ('incluir', 'excluir')"),
                "n_classificacoes": n("SELECT COUNT(*) AS n FROM r_classificacoes"),
                "n_paginas_baixadas": n("SELECT COUNT(*) AS n FROM r_paginas"),
                "n_chamadas_busca_web": n_chamadas["busca_web"], "n_chamadas_busca_academica": n_chamadas["busca_academica"],
                "n_triagem_escopo": te, "provedores": provedores, "tem_dados_humanos_achados": n_ver > 0,
                "tem_dados_humanos_artigos": n_hum > 0, "tem_dados_humanos": n_ver > 0 or n_hum > 0}

    # ---------- 15. revisao independente dos achados (kappa entre pessoas) ----------
    def analise_concordancia_achados(self):
        """Concordancia entre revisores humanos nos achados que dois deles revisaram de forma independente
        (`achados-importar --independente`; `v_ultima_revisao_achados`: ultima decisao de cada revisor, sem o 'consenso').
        Desfecho = confirmado (qualquer status_final diferente de 'descartado') x descartado; kappa de Cohen sem peso
        (`dominio.estatistica.kappa_cohen`, matriz [[confirmam, A confirma e B descarta], [A descarta e B confirma, descartam]])
        por par de revisores, com a faixa de `dominio.concordancia.interpretar_kappa`. Em `concordancia_status_pct`, a parte em
        que os dois deram exatamente o mesmo status_final. Kappa None = indefinido (um so desfecho em todos os achados do par).

        Devolve {tem_dados, n_revisores, n_achados_revisados, n_pares, n_discordancias, pares: [{revisor_a, revisor_b, n,
        ambos_confirmam, ambos_descartam, so_a_confirma, so_b_confirma, discordancias, concordancia_pct, kappa, ic_inferior,
        ic_superior, interpretacao, n_status_iguais, concordancia_status_pct}]}; vazio quando nao ha revisao independente."""
        linhas = self._ler("SELECT achado_id, revisor, status_final, desfecho FROM v_ultima_revisao_achados")
        por_achado, revisores = defaultdict(dict), set()
        for l in linhas:
            por_achado[l["achado_id"]][l["revisor"]] = (l["desfecho"], l["status_final"])
            revisores.add(l["revisor"])
        pares = []
        for a, b in combinations(sorted(revisores), 2):
            comuns = [(d[a], d[b]) for d in por_achado.values() if a in d and b in d]
            if not comuns:
                continue
            n11 = sum(1 for x, y in comuns if x[0] == "confirmado" and y[0] == "confirmado")
            n10 = sum(1 for x, y in comuns if x[0] == "confirmado" and y[0] == "descartado")
            n01 = sum(1 for x, y in comuns if x[0] == "descartado" and y[0] == "confirmado")
            n00 = sum(1 for x, y in comuns if x[0] == "descartado" and y[0] == "descartado")
            k = est.kappa_cohen([[n11, n10], [n01, n00]])
            iguais = sum(1 for x, y in comuns if x[1] == y[1])
            pares.append({"revisor_a": a, "revisor_b": b, "n": len(comuns), "ambos_confirmam": n11, "ambos_descartam": n00,
                          "so_a_confirma": n10, "so_b_confirma": n01, "discordancias": n10 + n01,
                          "concordancia_pct": _pct(n11 + n00, len(comuns)), "kappa": k["kappa"], "ic_inferior": k["ic_inferior"],
                          "ic_superior": k["ic_superior"], "interpretacao": interpretar_kappa(k["kappa"]),
                          "n_status_iguais": iguais, "concordancia_status_pct": _pct(iguais, len(comuns))})
        pares.sort(key=lambda p: (-p["n"], p["revisor_a"], p["revisor_b"]))
        n_disc = _i((self._ler_um("SELECT COUNT(*) AS n FROM v_discordancias_achados") or {}).get("n"))
        return {"tem_dados": bool(pares), "n_revisores": len(revisores), "n_achados_revisados": len(por_achado), "n_pares": len(pares),
                "n_discordancias": n_disc, "pares": pares}

    # ---------- 16. auditoria dos negativos do modelo (falsos negativos) ----------
    def analise_auditoria_negativos(self):
        """Falsos negativos do modelo: de uma amostra de paginas que ele classificou SEM achado, quantas tinham uma aplicacao
        de IA segundo uma pessoa (`auditoria_negativos`, via `v_auditoria_negativos`; unidade = classificacao).

        Com k aplicacoes perdidas em n conferidas: taxa k/n, intervalo de Wilson de 95% (`intervalo_wilson`) e limite superior
        unilateral exato de 95% (`limite_superior_binomial_exato`). Para cada meta de `METAS_FALSO_NEGATIVO`, `n_sem_erros` e o
        tamanho de amostra com ZERO erros que provaria a meta (`amostra_minima_sem_erros`) e `abaixo_da_meta` diz se o limite
        superior ja esta abaixo dela (None sem conferencia). `n_universo` = paginas sem achado auditaveis (`v_negativos_auditaveis`,
        classificacao vigente sobre o texto da pagina) e `estimativa_paginas_perdidas` = taxa x universo, so valendo se a amostra
        foi sorteada (o comando `auditoria-negativos-modelo` sorteia).

        Devolve {n_auditadas, n_perdidas, taxa, ic_wilson: (inf, sup) ou None, limite_superior, tem_dados, n_universo, n_restantes,
        por_tecnologia: [{tecnologia, n}], metas: [{meta, n_sem_erros, abaixo_da_meta, faltam_sem_erros}],
        estimativa_paginas_perdidas: {pontual, minimo, maximo} ou None}."""
        total = self._ler_um("SELECT n_auditadas, n_com_aplicacao_perdida FROM v_auditoria_negativos WHERE grupo = 'total'") or {}
        n, k = _i(total.get("n_auditadas")), _i(total.get("n_com_aplicacao_perdida"))
        por_tec = [{"tecnologia": l["tecnologia"], "n": l["n_com_aplicacao_perdida"]} for l in self._ler(
            """SELECT tecnologia, n_com_aplicacao_perdida FROM v_auditoria_negativos WHERE grupo = 'tecnologia'
               ORDER BY n_com_aplicacao_perdida DESC, tecnologia""")]
        universo = _i((self._ler_um("SELECT COUNT(*) AS n FROM v_negativos_auditaveis") or {}).get("n"))
        restantes = _i((self._ler_um(
            """SELECT COUNT(*) AS n FROM v_negativos_auditaveis v
               WHERE NOT EXISTS (SELECT 1 FROM auditoria_negativos a WHERE a.classificacao_id = v.classificacao_id)""") or {}).get("n"))
        ic = est.intervalo_wilson(k, n) if n else None
        sup = est.limite_superior_binomial_exato(k, n) if n else None
        metas = []
        for meta in METAS_FALSO_NEGATIVO:
            n_zero = amostra_minima_sem_erros(meta)
            metas.append({"meta": meta, "n_sem_erros": n_zero, "abaixo_da_meta": None if sup is None else sup < meta,
                          "faltam_sem_erros": max(n_zero - n, 0) if k == 0 else None})
        estimativa = None
        if n and universo:
            estimativa = {"pontual": round(universo * k / n), "minimo": round(universo * ic[0]), "maximo": round(universo * ic[1])}
        return {"n_auditadas": n, "n_perdidas": k, "taxa": _taxa(k, n), "ic_wilson": ic, "limite_superior": sup, "tem_dados": n > 0,
                "n_universo": universo, "n_restantes": restantes, "por_tecnologia": por_tec, "metas": metas,
                "estimativa_paginas_perdidas": estimativa}

    # ---------- 18. prontidao metodologica (o que falta rotular para destravar H2, H5 e a auditoria) ----------
    def analise_prontidao(self):
        """Progresso dos tres mínimos de rotulagem humana (`dominio.prontidao`; os numeros sao os dos scripts de `analises/`):

        - h2: achados verificados (de `r_achados`, com os tres preditores preenchidos, como `h2_logistica.py` conta) e a classe
          menos frequente entre confirmados e descartados;
        - h5: artigos com decisao humana de triagem incluir ou excluir (`r_artigos`, como `h5_bibliometria.py`) e o menor grupo;
        - auditoria: paginas negativas conferidas (`v_auditoria_negativos`) do universo de `v_negativos_auditaveis`.

        Devolve {h2, h5, auditoria}, cada um com {condicoes: [{rotulo, n, minimo, faltam, destravado, fracao}], destravado,
        faltam, ...}; h2 traz tambem `n_verificados_total` e `n_sem_preditor`."""
        a = self._ler_um("""
            SELECT COALESCE(SUM(a.verificado = 1), 0) AS verificados,
                   COALESCE(SUM(a.verificado = 1 AND a.evidencia_confere IS NOT NULL AND a.evidencia_cita_tecnologia IS NOT NULL
                                AND f.fonte_oficial_efetiva IS NOT NULL AND COALESCE(a.status_final, '') <> 'descartado'), 0) AS confirmados,
                   COALESCE(SUM(a.verificado = 1 AND a.evidencia_confere IS NOT NULL AND a.evidencia_cita_tecnologia IS NOT NULL
                                AND f.fonte_oficial_efetiva IS NOT NULL AND a.status_final = 'descartado'), 0) AS descartados
            FROM r_achados a LEFT JOIN v_fonte_da_classificacao f ON f.classificacao_id = a.classificacao_id""") or {}
        h2 = prontidao_h2(_i(a.get("confirmados")), _i(a.get("descartados")))
        h2["n_verificados_total"] = _i(a.get("verificados"))
        h2["n_sem_preditor"] = h2["n_verificados_total"] - h2["n_confirmados"] - h2["n_descartados"]
        t = {l["decisao"]: l["n"] for l in self._ler(
            """SELECT t.decisao, COUNT(*) AS n FROM r_artigos a JOIN triagem t ON t.artigo_id = a.artigo_id
               WHERE t.decisao IN ('incluir', 'excluir') GROUP BY t.decisao""")}
        h5 = prontidao_h5(t.get("incluir", 0), t.get("excluir", 0))
        aud = self.analise_auditoria_negativos()
        return {"h2": h2, "h5": h5, "auditoria": prontidao_auditoria(aud["n_auditadas"], aud["n_universo"], aud["n_perdidas"])}

    # ---------- 17. paginas que a coleta nao conseguiu verificar (RC22) ----------
    def analise_nao_verificaveis(self, limite=10):
        """Honestidade sobre o que a coleta NAO conseguiu ver. Para cada URL, vale a ULTIMA tentativa de download entre as
        execucoes do relatorio (`chamadas`, etapa download). Se ela falhou, a URL cai em uma classe:
          - `proibido_pelo_site`: o robots.txt foi lido e proibe (`bloqueado_por_robots`);
          - `nao_verificavel_robots`: o robots.txt estava inacessivel (5xx, tempo esgotado, rede) e a falha PERSISTIU: 3 leituras
            na mesma tentativa (`extras_json.robots_tentativas`) ou ao menos 2 tentativas de download com essa falha. NAO e
            proibicao do site: pela RFC 9309 o sistema trata como proibido, mas nao sabemos o que o site decidiu;
          - `falha_definitiva_404`: HTTP 404 ou 410 na ultima tentativa (a pagina nao existe mais ou mudou de endereco);
          - `outras_falhas`: o resto (HTTP 401/403/429, erro de leitura ou de rede, robots.txt inacessivel sem confirmacao...).
        Tentativa que baixou (mesmo sem texto extraido) nao entra: so conta falha de download. A politica de bloquear robots.txt
        ilegivel nao e alterada aqui.

        Devolve {n_urls_tentadas, n_ok, n_falhas, classes: {classe: {n_paginas, n_dominios, n_ufs, ufs: [..],
        dominios: [{dominio, n}] (os `limite` com mais paginas), motivos: [{motivo, n}]}}, n_nao_verificaveis,
        n_dominios_nao_verificaveis}."""
        limite = min(max(int(limite), 1), 100)
        vazio_classe = lambda: {"n_paginas": 0, "n_dominios": 0, "n_ufs": 0, "ufs": [], "dominios": [], "motivos": []}
        saida = {"n_urls_tentadas": 0, "n_ok": 0, "n_falhas": 0, "classes": {c: vazio_classe() for c in CLASSES_NAO_VERIFICAVEIS},
                 "n_nao_verificaveis": 0, "n_dominios_nao_verificaveis": 0}
        ultimas = self._ler("""
            SELECT url_id, sucesso, erro, http_status, extras FROM (
                SELECT CAST(c.alvo_id AS INTEGER) AS url_id, c.sucesso, c.erro, c.http_status,
                       CASE WHEN c.erro LIKE 'robots_inacessivel%' THEN c.extras_json END AS extras,
                       ROW_NUMBER() OVER (PARTITION BY c.alvo_id ORDER BY c.chamada_id DESC) AS pos
                FROM chamadas c JOIN execucoes e ON e.run_id = c.run_id
                WHERE c.etapa = 'download' AND e.no_relatorio = 1) WHERE pos = 1""")
        if not ultimas:
            return saida
        falhas_robots = {l["url_id"]: l["n"] for l in self._ler("""
            SELECT CAST(c.alvo_id AS INTEGER) AS url_id, COUNT(*) AS n FROM chamadas c JOIN execucoes e ON e.run_id = c.run_id
            WHERE c.etapa = 'download' AND e.no_relatorio = 1 AND c.erro LIKE 'robots_inacessivel%' GROUP BY c.alvo_id""")}
        dominios = {l["url_id"]: l["dominio"] for l in self._ler("SELECT url_id, dominio FROM urls")}
        ufs = defaultdict(set)
        for l in self._ler("""SELECT DISTINCT s.url_id, s.uf FROM selecao_download s JOIN execucoes e ON e.run_id = s.run_id
                              WHERE e.no_relatorio = 1 AND (s.selecionada = 1 OR s.auditoria = 1)"""):
            ufs[l["url_id"]].add(l["uf"])
        grupos = {c: [] for c in CLASSES_NAO_VERIFICAVEIS}
        saida["n_urls_tentadas"] = len(ultimas)
        for l in ultimas:
            if _i(l["sucesso"]) == 1:
                saida["n_ok"] += 1
                continue
            erro = str(l["erro"] or "")
            if erro.startswith("bloqueado_por_robots"):
                classe, motivo = "proibido_pelo_site", "bloqueado_por_robots"
            elif erro.startswith("robots_inacessivel"):
                leituras = 0
                try:
                    extras = json.loads(l["extras"] or "{}")
                    leituras = max([v for k, v in extras.items() if k.endswith("tentativas") and isinstance(v, int)] or [0])
                except (TypeError, ValueError, AttributeError):
                    pass
                if leituras >= LEITURAS_ROBOTS_PERSISTENTE or falhas_robots.get(l["url_id"], 0) >= TENTATIVAS_ROBOTS_PERSISTENTE:
                    classe, motivo = "nao_verificavel_robots", "robots_inacessivel"
                else:
                    classe, motivo = "outras_falhas", "robots_inacessivel_sem_confirmacao"
            elif l["http_status"] in (404, 410):
                classe, motivo = "falha_definitiva_404", f"http_{l['http_status']}"
            else:
                classe = "outras_falhas"
                motivo = (f"http_{l['http_status']}" if l["http_status"] else (erro.split(":")[0].split("(")[0].strip() or "sem_motivo"))
            grupos[classe].append((l["url_id"], motivo))
        saida["n_falhas"] = sum(len(g) for g in grupos.values())
        for classe, itens in grupos.items():
            doms = Counter(dominios.get(u) or "(sem domínio)" for u, _ in itens)
            ufs_classe = sorted({uf for u, _ in itens for uf in ufs.get(u, ())})
            saida["classes"][classe] = {
                "n_paginas": len(itens), "n_dominios": len(doms), "n_ufs": len(ufs_classe), "ufs": ufs_classe,
                "dominios": [{"dominio": d, "n": n} for d, n in sorted(doms.items(), key=lambda kv: (-kv[1], kv[0]))[:limite]],
                "motivos": [{"motivo": m, "n": n} for m, n in sorted(Counter(m for _, m in itens).items(), key=lambda kv: (-kv[1], kv[0]))]}
        saida["n_nao_verificaveis"] = saida["classes"]["nao_verificavel_robots"]["n_paginas"]
        saida["n_dominios_nao_verificaveis"] = saida["classes"]["nao_verificavel_robots"]["n_dominios"]
        return saida
