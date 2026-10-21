"""Paginas /solucoes (RC17) e /buscar-texto (RC16).

/buscar-texto procura um nome ou frase no TEXTO EXTRAIDO de todas as paginas baixadas (nao so na evidencia dos achados).
/solucoes confere, para cada solucao conhecida (lista do pesquisador em config/solucoes_conhecidas.py), ate onde a coleta a levou:
resultado de busca, pagina baixada, achado. So le o banco e os arquivos de texto; nunca grava.

O texto das paginas e lido por `c.bruto` e guardado em memoria (os arquivos nao mudam), com o texto normalizado ao lado, para que
a segunda busca seja quase instantanea. Ao abrir o painel, uma tarefa em segundo plano le todos os textos (aquecimento), de modo
que a PRIMEIRA busca tambem seja rapida: sem ela, ler cerca de 800 arquivos em /mnt/c leva de 6 a 11 s."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from dominio import solucoes as dom

Q_MIN, Q_MAX = 3, 80                 # tamanho da busca, em caracteres
MAX_RESULTADOS = 100                 # paginas mostradas em /buscar-texto
MAX_TRECHOS = 2                      # trechos mostrados por pagina
LARGURA_TRECHO = 160                 # caracteres de cada lado do trecho
MAX_LINKS = 5                        # links por etapa em /solucoes
LIMITE_CARACTERES_TEXTO = 3_000_000  # um texto maior que isto e cortado
ORCAMENTO_CACHE = 150_000_000        # caracteres (original + normalizado) guardados; estourou, o cache recomeca
THREADS_LEITURA = 8


class CacheDeTextos:
    """texto_path -> (original, normalizado); None quando o arquivo nao existe. Leitura em paralelo na primeira vez."""

    def __init__(self, bruto):
        self._bruto = bruto
        self._itens, self._tamanho = {}, 0
        self._trava = threading.Lock()          # o aquecimento e as requisicoes podem usar o cache ao mesmo tempo

    def _ler(self, caminho):
        try:
            original = self._bruto.ler(caminho).decode("utf-8", "replace")[:LIMITE_CARACTERES_TEXTO]
        except (OSError, ValueError):
            return None
        return original, dom.normalizar(original)

    def obter(self, caminhos):
        """{caminho: (original, normalizado) ou None} para todos os caminhos pedidos."""
        caminhos = list(dict.fromkeys(caminhos))
        with self._trava:
            saida = {p: self._itens[p] for p in caminhos if p in self._itens}
        faltam = [p for p in caminhos if p not in saida]
        if faltam:
            with ThreadPoolExecutor(THREADS_LEITURA) as pool:
                lidos = list(zip(faltam, pool.map(self._ler, faltam)))
            with self._trava:
                if self._tamanho > ORCAMENTO_CACHE:
                    self._itens, self._tamanho = {}, 0
                for p, t in lidos:
                    saida[p] = self._itens[p] = t
                    self._tamanho += 2 * len(t[0]) if t else 0
        return saida

    def tamanho(self):
        with self._trava:
            return len(self._itens)


def _so_http(url):
    return str(url or "").lower().startswith(("http://", "https://"))


def _agrupar(achados):
    """Uma pagina classificada em varias execucoes repete o mesmo trio tecnologia-status-nome da solucao: junta os iguais, com o achado
    mais novo para o link (o ultimo da lista, que vem do mais antigo ao mais novo) e `n` = quantos achados o grupo reune. Solucoes com nomes diferentes na mesma pagina ficam em grupos separados."""
    grupos = {}
    for a in achados:
        nome = (a.get("nome_solucao") or "").strip()
        g = grupos.setdefault((a["tecnologia"], a["status_reportado"], nome), {**a, "n": 0})
        g["n"] += 1
        g["achado_id"] = a["achado_id"]
    return list(grupos.values())


def _ocorrencias(norm, termo):
    """Quantas vezes o termo (ja normalizado, com ou sem espacos nas pontas) aparece no texto normalizado, sem sobreposicao."""
    return norm.count(termo)


def registrar(c):
    app, leitura = c.app, c.leitura
    cache = CacheDeTextos(c.bruto)
    ufs_validas = c.contexto.ufs

    def aquecer():
        """Le todos os textos para o cache. Qualquer falha so e registrada: o aquecimento nunca pode derrubar o painel."""
        try:
            if leitura.existe():
                cache.obter(p["texto_path"] for p in leitura.paginas_para_busca_texto(None))
        except Exception:                               # noqa: BLE001 - e so uma otimizacao
            logging.warning("[painel] aquecimento do cache de textos falhou; a primeira busca sera mais lenta", exc_info=True)

    def iniciar_aquecimento():
        t = threading.Thread(target=aquecer, name="aquecer-cache-texto", daemon=True)
        app.state.aquecimento_cache_texto = t
        t.start()

    app.state.cache_textos = cache
    # o aquecimento comeca quando o servidor sobe (ou em `with TestClient(app)`); o FastAPI atual nao tem `add_event_handler`,
    # entao o ciclo de vida existente e embrulhado
    ciclo_original = app.router.lifespan_context

    @asynccontextmanager
    async def ciclo(aplicacao):
        iniciar_aquecimento()
        async with ciclo_original(aplicacao) as estado:
            yield estado

    app.router.lifespan_context = ciclo

    @app.get("/buscar-texto", response_class=HTMLResponse)
    def buscar_texto(request: Request):
        if not leitura.existe():
            return c.sem_banco(request)
        q = (request.query_params.get("q") or "").strip()
        uf = (request.query_params.get("uf") or "").strip().upper()
        inteira = (request.query_params.get("inteira") or "") in ("1", "on", "true")
        base = {"q": q, "uf": uf, "inteira": inteira, "ufs": ufs_validas, "resultados": None, "aviso": None,
                "q_min": Q_MIN, "q_max": Q_MAX, "max_resultados": MAX_RESULTADOS}
        if uf and uf not in ufs_validas:
            return c.pagina(request, "buscar_texto.html", status=400, **{**base, "aviso": "A UF escolhida não existe. Escolha uma da lista.", "uf": ""})
        if not q:
            return c.pagina(request, "buscar_texto.html", **base)
        if not Q_MIN <= len(q) <= Q_MAX:
            return c.pagina(request, "buscar_texto.html", status=400, **{
                **base, "aviso": f"A busca precisa ter de {Q_MIN} a {Q_MAX} caracteres (a sua tem {len(q)})."})
        alvo = dom.normalizar(q)
        if not alvo.strip():
            return c.pagina(request, "buscar_texto.html", status=400, **{**base, "aviso": "A busca precisa ter letras ou números."})
        termo = alvo if inteira else alvo.strip()

        paginas = leitura.paginas_para_busca_texto([uf] if uf else None)
        textos = cache.obter(p["texto_path"] for p in paginas)
        achadas, sem_arquivo = [], 0
        for p in paginas:
            t = textos[p["texto_path"]]
            if t is None:
                sem_arquivo += 1
            elif dom.casar(t[1], termo):
                achadas.append((_ocorrencias(t[1], termo), p, t))
        achadas.sort(key=lambda x: (-x[0], x[1]["uf"], x[1]["url_id"]))
        mostradas = achadas[:MAX_RESULTADOS]
        achados = leitura.achados_das_urls({(p["url_id"], p["uf"]) for _, p, _ in mostradas})
        resultados = [{
            "uf": p["uf"], "url": p["url"], "dominio": p["dominio_final"], "run_id": p["run_id"], "n_ocorrencias": n,
            "link_externo": p["url_final"] if _so_http(p["url_final"]) else p["url"], "no_relatorio": p["no_relatorio"],
            # cada trecho vira [(pedaco, marcado)]: toda ocorrencia do termo no trecho fica marcada, nao so a primeira
            "trechos": [dom.marcar_ocorrencias(antes + achado + depois, q, inteira)
                        for antes, achado, depois in dom.trechos_ao_redor(texto[0], q, LARGURA_TRECHO, inteira, MAX_TRECHOS, texto[1])],
            "achados": _agrupar(achados.get((p["url_id"], p["uf"]), [])),
        } for n, p, texto in mostradas]
        return c.pagina(request, "buscar_texto.html", **{
            **base, "resultados": resultados, "n_achadas": len(achadas), "n_paginas": len(paginas), "sem_arquivo": sem_arquivo,
            "truncado": len(achadas) > MAX_RESULTADOS, "link_achados": "/achados?" + urlencode({"q": q}),
            "link_achados_uf": "/achados?" + urlencode({"q": q, "uf": uf}) if uf else None})

    def _conferir(s, paginas_da_uf, textos, entidade=None):
        """O que a coleta fez com a solucao `s`: resultados, paginas e achados que a citam, e o veredito. Com `entidade` (RC23), os achados
        incluem os das grafias que o modelo escreveu de outro jeito e que foram reunidas ao cadastro (nome canonico = nome oficial)."""
        termos = dom.variantes_da_solucao(s)
        resultados = leitura.resultados_busca_que_citam(termos, s.uf)
        paginas = []
        for p in paginas_da_uf.get(s.uf, []):
            t = textos.get(p["texto_path"])
            if t is not None and any(dom.casar(t[1], x) for x in termos):
                paginas.append(p)
        citam = leitura.achados_que_citam(termos, s.uf)
        das_variantes = []
        if entidade is not None:
            ja = {a["achado_id"] for a in citam}
            das_variantes = [a for a in leitura.achados_das_variantes(entidade.pares) if a["achado_id"] not in ja]
            citam = sorted(citam + das_variantes, key=lambda a: a["achado_id"])
        ids_citam = {a["achado_id"] for a in citam}
        das_paginas = leitura.achados_das_urls({(p["url_id"], p["uf"]) for p in paginas})
        paginas_ricas = [{**p, "link_externo": p["url"], "achados_sem_nome": _agrupar(
            a for a in das_paginas.get((p["url_id"], p["uf"]), []) if a["achado_id"] not in ids_citam)} for p in paginas]
        urls_sem_pagina = {r["url_id"] for r in resultados if not r["n_paginas"]}
        situacao = dom.situacao_da_solucao(len(resultados), len(paginas), len(citam))
        return {
            "solucao": s, "variantes": [v.strip() for v in termos], "situacao": situacao,
            "rotulo": dom.rotulo_da_situacao(situacao), "explicacao": dom.explicacao_da_situacao(situacao),
            "resultados": resultados, "n_urls_resultados": len({r["url_id"] for r in resultados}),
            "n_urls_nunca_baixadas": len(urls_sem_pagina), "so_fora_do_relatorio": bool(resultados) and not any(r["no_relatorio"] for r in resultados),
            "paginas": paginas_ricas, "achados": citam, "entidade": entidade, "n_das_variantes": len(das_variantes)}

    @app.get("/solucoes", response_class=HTMLResponse)
    def solucoes(request: Request):
        if not leitura.existe():
            return c.sem_banco(request)
        lista = tuple(c.contexto.solucoes_conhecidas)
        resolucao = c.entidades.obter()
        cartoes = []
        if lista:
            ufs = sorted({s.uf for s in lista})
            paginas_da_uf = {u: leitura.paginas_para_busca_texto([u]) for u in ufs}
            textos = cache.obter(p["texto_path"] for ps in paginas_da_uf.values() for p in ps)
            cartoes = [_conferir(s, paginas_da_uf, textos, resolucao.entidade_da_conhecida(s)) for s in lista]
        return c.pagina(request, "solucoes.html", cartoes=cartoes, max_links=MAX_LINKS, sem_lista=not lista,
                        entidades=resolucao.entidades, n_achados_nomeados=resolucao.n_achados,
                        ordem_situacao={s: i for i, s in enumerate(dom.SITUACOES)})   # chave de ordenação da coluna "Situação": quão longe o funil chegou
