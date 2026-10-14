"""Bancos sinteticos pequenos, com resultados calculaveis a mao, para testar as views de metricas.

Academico (4 termos com sobreposicao):
    T01 (pt): p1 A1..A6, p2 A7 A8      T02 (pt): A1 A2 A9
    T05 (pt): A10 A11                  T25 (en): A1 A10 A12
Triagem: incluir A1 A2 A9 A12 | excluir A3 A4 (fora do escopo) A5 A10 (sem IA) | pendente A6 | sem linha A7 A8 A11

Web (PI): M01 devolve gov/1 gov/2 gov/3; M02 devolve gov/3 e blog/4 (extracao do blog falha -> snippet).
Verificacao humana: gov/1 confirmado em_uso | gov/2 descartado | gov/3 confirmado, status mudou para piloto | blog/4 sem verificar.
"""
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
import json

from adaptadores.simulados import (BuscaSimulada, ExtratorSimulado, FetcherSimulado, ClassificadorSimulado,
                                   _reg)
from aplicacao import busca_web, classificacao, download
import config.settings as S
from config import consultas as C, vocabulario as V
from dominio.esquemas import esquema_classificacao
from dominio.modelos import (Achado, ArquivoBaixado, ArtigoAcademico, ParametrosClassificacao, RegistroChamada,
                             ResultadoClassificacao, ResultadoWeb, RespostaBusca, TextoExtraido)
from dominio.servicos import gerar_consultas_web

COMPOSTO = {"id": "T47", "query": '"reconhecimento facial" AND ("public security" OR police)', "idioma": "pt",
            "grupo": "reconhecimento_identificacao", "pai": "T01"}
TERMOS_ACADEMICOS = {"T01": '"reconhecimento facial"', "T02": '"reconhecimento facial em tempo real"',
                     "T05": '"videomonitoramento inteligente"', "T25": '"facial recognition"',
                     "T47": COMPOSTO["query"]}


def _novo_run(repo, comando, termos_extra=()):
    """Cria a execucao com o snapshot real da configuracao (mais, se pedido, termos extras no config_json)."""
    snap = S.snapshot_config()
    config_json = snap["json"]
    if termos_extra:
        d = json.loads(config_json)
        d["termos"] = d["termos"] + list(termos_extra)
        config_json = json.dumps(d, ensure_ascii=False, sort_keys=True)
    return repo.iniciar_execucao(comando, snap["hash"], config_json, None)


def _artigo(n):
    return ArtigoAcademico(f"Artigo A{n}", None, "Autor - Revista, 2023", 2023, "resumo", n, n)


def _chamada_academica(repo, run_id, termo_id, pagina, numeros, total, hl="pt"):
    reg = RegistroChamada(
        provedor="serpapi_scholar", operacao="buscar_pagina",
        parametros={"engine": "google_scholar", "q": TERMOS_ACADEMICOS[termo_id], "hl": hl, "num": 20,
                    "start": (pagina - 1) * 20, "as_ylo": 2019},
        requisitado_em=f"2026-10-14T10:0{pagina}:00+00:00", http_status=200, latencia_ms=100 * pagina)
    cid = repo.salvar_chamada(run_id=run_id, etapa="busca_academica", alvo_tipo="termo", alvo_id=termo_id,
                              chave=f"{termo_id}-{pagina}", registro=reg, raw_path="x.json", raw_sha256="y" * 64,
                              pagina=pagina)
    novos = repo.salvar_artigos(cid, run_id, termo_id, [_artigo(n) for n in numeros])
    repo.atualizar_chamada(cid, total_reportado=total, n_retornados=len(numeros), n_novos=novos)
    repo.confirmar()


def _id_artigo(repo, n):
    return repo.conn.execute("SELECT artigo_id FROM artigos WHERE titulo=?", (f"Artigo A{n}",)).fetchone()[0]


def construir_academico(caminho, composto=False):
    """composto=True acrescenta T47 (consulta combinada derivada de T01): A1 A2 A14, com A14 incluido."""
    repo = RepositorioSQLite(caminho)
    run_id = _novo_run(repo, "academico", termos_extra=[COMPOSTO] if composto else ())
    _chamada_academica(repo, run_id, "T01", 1, range(1, 7), 1500)
    _chamada_academica(repo, run_id, "T01", 2, [7, 8], 1500)
    _chamada_academica(repo, run_id, "T02", 1, [1, 2, 9], 40)
    _chamada_academica(repo, run_id, "T05", 1, [10, 11], 12)
    _chamada_academica(repo, run_id, "T25", 1, [1, 10, 12], 300, hl="en")
    triagem = [(1, "incluir", None), (2, "incluir", None), (9, "incluir", None), (12, "incluir", None),
               (3, "excluir", "fora do escopo"), (4, "excluir", "fora do escopo"),
               (5, "excluir", "sem IA"), (10, "excluir", "sem IA"), (6, "pendente", None)]
    for n, decisao, motivo in triagem:
        repo.conn.execute("INSERT INTO triagem (artigo_id, decisao, motivo) VALUES (?,?,?)",
                          (_id_artigo(repo, n), decisao, motivo))
    if composto:
        _chamada_academica(repo, run_id, "T47", 1, [1, 2, 14], 20)
        repo.conn.execute("INSERT INTO triagem (artigo_id, decisao) VALUES (?, 'incluir')", (_id_artigo(repo, 14),))
    repo.conn.executemany(
        "INSERT INTO buscas_manuais (base, termo_id, string_base, filtros, n_resultados, n_apos_filtro, "
        "n_selecionados, data_busca) VALUES (?,?,?,?,?,?,?,?)",
        [("IEEE", "T01", '"reconhecimento facial"', "2019-", 100, 40, 10, "2026-10-15"),
         ("ACM", "T25", '"facial recognition"', "2019-", 50, 20, 5, "2026-10-15")])
    repo.confirmar()
    return repo, run_id


class BuscaVariada(BuscaSimulada):
    """M01 -> gov/1, gov/2, gov/3; M02 -> gov/3 e blog/4. Cada requisicao custa US$ 0,005."""
    def buscar(self, consulta, filtros):
        if consulta.modelo_id == "M01":
            itens = [("https://exemplo.gov.br/pi/1", 1), ("https://exemplo.gov.br/pi/2", 2),
                     ("https://exemplo.gov.br/pi/3", 3)]
        else:
            itens = [("https://exemplo.gov.br/pi/3", 1), ("https://blog.exemplo.com.br/pi/4", 2)]
        res = [ResultadoWeb(u, f"Reconhecimento facial PI {u[-1]}", "câmeras com reconhecimento facial", None, p)
               for u, p in itens]
        resp = RespostaBusca(res, super().buscar(consulta, filtros).chamada)
        resp.chamada.custo_usd = 0.005
        return resp


class ExtratorQueFalhaNoBlog(ExtratorSimulado):
    def extrair(self, conteudo, content_type, url):
        if "blog" in url:
            return TextoExtraido("", "simulado", False, "texto_insuficiente")
        return super().extrair(conteudo, content_type, url)


def _params():
    return ParametrosClassificacao(
        versao_prompt="v-teste", sistema="s", usuario_template="{nome} {uf} {url} {titulo} {origem} {texto}",
        esquema=esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA),
        tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS))


def construir_web(pasta):
    repo = RepositorioSQLite(pasta / "web.db")
    bruto = BrutoLocal(pasta / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, {"PI": C.UFS["PI"]})
    busca_web.executar(repo, bruto, BuscaVariada(), run_id, consultas, C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherSimulado(), ExtratorQueFalhaNoBlog(), run_id, run_id,
                      C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    # verificacao humana
    def url_id(sufixo):
        return repo.conn.execute("SELECT url_id FROM urls WHERE url_original LIKE ?", (f"%{sufixo}",)).fetchone()[0]
    for sufixo, status in (("gov.br/pi/1", "em_uso"), ("gov.br/pi/2", "descartado"), ("gov.br/pi/3", "piloto")):
        repo.conn.execute(
            "UPDATE achados SET verificado=1, status_final=? WHERE classificacao_id IN "
            "(SELECT classificacao_id FROM classificacoes WHERE url_id=?)", (status, url_id(sufixo)))
    repo.confirmar()
    return repo, run_id


# ---------- cenarios de auditoria da coleta ----------
def _url(n, dominio="exemplo.gov.br"):
    return f"https://{dominio}/pi/{n}"


class Busca4Urls(BuscaSimulada):
    """Uma consulta devolve 4 URLs (/pi/1 a /pi/4), todas passando no pre-filtro de palavras-chave."""
    def buscar(self, consulta, filtros):
        res = [ResultadoWeb(_url(n), f"Reconhecimento facial PI {n}", "câmeras com reconhecimento facial", None, n)
               for n in range(1, 5)]
        return RespostaBusca(res, super().buscar(consulta, filtros).chamada)


class BuscaSemPalavraChave(BuscaSimulada):
    """3 URLs cujo titulo e snippet nao passam no pre-filtro."""
    def buscar(self, consulta, filtros):
        res = [ResultadoWeb(_url(n), f"Noticia generica {n}", "texto sem relacao", None, n) for n in range(1, 4)]
        return RespostaBusca(res, super().buscar(consulta, filtros).chamada)


class FetcherComFalhas(FetcherSimulado):
    """/pi/2 -> HTTP 403; /pi/3 -> bloqueado por robots; /pi/4 -> erro de rede; /pi/1 -> ok."""
    def baixar(self, url):
        base = super().baixar(url)
        reg = base.chamada
        if url.endswith("/pi/2"):
            reg.erro, reg.http_status = "HTTP 403", 403
            return ArquivoBaixado(url, 403, "", b"", False, reg)
        if url.endswith("/pi/3"):
            reg.erro, reg.http_status = "bloqueado_por_robots", None
            return ArquivoBaixado(url, None, "", b"", False, reg)
        if url.endswith("/pi/4"):
            reg.erro, reg.http_status = "ReadTimeout('lento')", None
            return ArquivoBaixado(url, None, "", b"", False, reg)
        return base


def _consulta_pi():
    return gerar_consultas_web(C.MODELOS_WEB[:1], {"reconhecimento_facial": "reconhecimento facial"}, {"PI": C.UFS["PI"]})


def construir_downloads(pasta, limite=None):
    repo = RepositorioSQLite(pasta / "dl.db")
    bruto = BrutoLocal(pasta / "raw")
    run_id = _novo_run(repo, "baixar")
    busca_web.executar(repo, bruto, Busca4Urls(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherComFalhas(), ExtratorSimulado(), run_id, run_id,
                      C.POLITICA_DOWNLOAD, [], 0, limite=limite, ufs={"PI"})
    return repo, run_id


class ClassificadorMisto:
    """Devolve, para cada item: um achado valido (confianca alta), um com tecnologia fora do vocabulario e um com
    status fora do vocabulario. Falha na chamada para a URL /pi/2."""
    nome = "misto"

    def classificar(self, entrada, instr):
        reg = _reg(self.nome, "classificar", raw=b"{}", tokens_entrada=10, tokens_saida=5, custo_usd=0.001)
        if entrada.url.endswith("/pi/2"):
            reg.erro, reg.http_status = "HTTP 500: falha", 500
            return ResultadoClassificacao(False, [], False, "", reg)
        achados = [Achado("reconhecimento_facial", "em_uso", "", True, "implantou reconhecimento facial", "alta"),
                   Achado("tecnologia_inventada", "em_uso", "", False, "trecho x", "alta"),
                   Achado("leitura_placas", "status_inventado", "", False, "trecho y", "media")]
        return ResultadoClassificacao(True, achados, True, "{}", reg)


class ExtratorQueFalhaNoTres(ExtratorSimulado):
    """A extracao falha em /pi/3 e em /pi/4 (o nome vem do primeiro caso)."""
    def extrair(self, conteudo, content_type, url):
        if url.endswith(("/pi/3", "/pi/4")):
            return TextoExtraido("", "simulado", False, "texto_insuficiente")
        return super().extrair(conteudo, content_type, url)


class BuscaSemTextoNoQuatro(BuscaSimulada):
    """/pi/1 e /pi/3 com titulo e snippet; /pi/4 sem nenhum texto (nem snippet)."""
    def buscar(self, consulta, filtros):
        res = [ResultadoWeb(_url(1), "Reconhecimento facial PI 1", "câmeras com reconhecimento facial", None, 1),
               ResultadoWeb(_url(2), "Reconhecimento facial PI 2", "câmeras com reconhecimento facial", None, 2),
               ResultadoWeb(_url(3), "Reconhecimento facial PI 3", "câmeras com reconhecimento facial", None, 3),
               ResultadoWeb(_url(4), "", "", None, 4)]
        return RespostaBusca(res, super().buscar(consulta, filtros).chamada)


def construir_classificacao_mista(pasta, usar_snippet=True):
    """/pi/1 classificado com texto da pagina; /pi/2 falha na chamada; /pi/3 so snippet (extracao falha);
    /pi/4 sem nenhum texto. Politica de download sem pre-filtro de palavras (o item 4 nao tem titulo nem snippet)."""
    from dataclasses import replace
    repo = RepositorioSQLite(pasta / "cl.db")
    bruto = BrutoLocal(pasta / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, BuscaSemTextoNoQuatro(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    politica = replace(C.POLITICA_DOWNLOAD, palavras_chave=())
    download.executar(repo, bruto, FetcherSimulado(), ExtratorQueFalhaNoTres(), run_id, run_id, politica, [], 0,
                      ufs={"PI"})
    params = replace(_params(), usar_snippet_se_falhar=usar_snippet)
    classificacao.executar(repo, bruto, ClassificadorMisto(), run_id, run_id, params, C.UFS, [], 0, ufs={"PI"})
    return repo, run_id
