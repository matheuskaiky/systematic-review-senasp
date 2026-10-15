import json
from dominio.modelos import RegistroChamada, ArtigoAcademico, PaginaAcademica
from dominio.servicos import ano_do_resumo
from infra.http import chamar, extras_http
from infra.util import agora


class AcademicoSerpApiScholar:
    nome = "serpapi_scholar"
    URL = "https://serpapi.com/search.json"
    URL_CONTA = "https://serpapi.com/account"

    def __init__(self, chave, timeout=60):
        self._chave, self._timeout = chave, timeout

    def saldo(self):
        """Buscas restantes. O endpoint de conta e gratuito e nao conta na cota (documentacao da SerpApi, 14/10/2026).
        Nunca levanta: sem resposta, com erro ou com corpo ilegivel, devolve None."""
        r = chamar("GET", self.URL_CONTA, params={"api_key": self._chave}, timeout=self._timeout)
        if r["resp"] is None or not r["resp"].ok:
            return None
        try:
            d = r["resp"].json()
            # TODO(verificar): diferenca entre total_searches_left e plan_searches_left (a documentacao so mostra valores iguais)
            return d.get("total_searches_left", d.get("plan_searches_left"))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def interpretar(raw_texto, inicio):
        d = json.loads(raw_texto)
        artigos = []
        for i, item in enumerate(d.get("organic_results") or []):
            titulo = (item.get("title") or "").strip()
            if not titulo:
                continue
            pub = item.get("publication_info") or {}
            citado = (item.get("inline_links") or {}).get("cited_by") or {}
            # TODO(verificar): a documentacao mostra position com base 1 (primeiro resultado = 1); aqui ele e somado ao
            # deslocamento da pagina, o que da a posicao global. Conferir com a primeira resposta real.
            artigos.append(ArtigoAcademico(
                titulo=titulo, link=item.get("link"), autores_publicacao=pub.get("summary"),
                ano=ano_do_resumo(pub.get("summary")), snippet=item.get("snippet"),
                citacoes=citado.get("total"), posicao=inicio + int(item.get("position", i) or 0)))
        # TODO(verificar): campos de search_metadata (a pagina de documentacao nao os mostra no exemplo)
        meta, info = d.get("search_metadata") or {}, d.get("search_information") or {}
        return artigos, info.get("total_results"), meta.get("id"), meta.get("total_time_taken"), d.get("error")

    def buscar_pagina(self, termo, inicio, filtros):
        params = {"engine": "google_scholar", "q": termo.query, "hl": termo.idioma,
                  "num": filtros.por_pagina, "start": inicio}
        if filtros.ano_inicial:
            params["as_ylo"] = filtros.ano_inicial
        if filtros.ano_final:
            params["as_yhi"] = filtros.ano_final
        r = chamar("GET", self.URL, params={**params, "api_key": self._chave}, timeout=self._timeout)
        reg = RegistroChamada(provedor=self.nome, operacao="buscar_pagina", parametros=params,
                              requisitado_em=agora(), http_status=r["http_status"],
                              latencia_ms=r["latencia_ms"], tentativas=r["tentativas"], erro=r["erro"])
        reg.extras.update(extras_http(r))
        artigos, total = [], None
        if r["resp"] is not None:
            reg.raw = r["resp"].content
        if reg.erro is None:
            try:
                artigos, total, reg.id_externo, tempo, erro_api = self.interpretar(r["resp"].text, inicio)
                reg.extras["tempo_servidor_s"] = tempo
                # SerpApi may return 200 + "error" when there are no results
                # TODO(verificar): o texto exato dessa mensagem e o status HTTP (a documentacao nao traz exemplo de busca vazia)
                if erro_api and "hasn't returned any results" not in erro_api:
                    reg.erro = erro_api
            except (ValueError, KeyError, TypeError, AttributeError) as e:     # AttributeError: item que nao e objeto
                reg.erro = f"resposta_inesperada: {e!r}"
        return PaginaAcademica(artigos, total, reg)
