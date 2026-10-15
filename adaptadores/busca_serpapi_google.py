import json
from dominio.modelos import RegistroChamada, ResultadoWeb, RespostaBusca
from infra.http import chamar, extras_http
from infra.util import agora


class BuscaSerpApiGoogle:
    nome = "serpapi_google"
    URL = "https://serpapi.com/search.json"

    def __init__(self, chave, pais="br", timeout=60):
        self._chave, self._pais, self._timeout = chave, pais, timeout

    def _params(self, consulta, filtros):
        q = consulta.texto
        if filtros.dominios_incluir:        # translation of the neutral filter into Google operators
            q += " (" + " OR ".join(f"site:{d.lstrip('.')}" for d in filtros.dominios_incluir) + ")"
        for d in filtros.dominios_excluir:
            q += f" -site:{d}"
        # TODO(verificar): se a SerpApi respeita `num` na busca do Google (a pagina de documentacao nao descreve o
        # parametro) e qual o maximo de resultados por pagina; `n_retornados` mostra quantos vieram de fato
        return {"engine": "google", "q": q, "num": min(filtros.max_resultados, 100),
                "hl": consulta.idioma, "gl": self._pais}

    @staticmethod
    def interpretar(raw_texto):
        d = json.loads(raw_texto)
        itens = d.get("organic_results") or []
        resultados = [ResultadoWeb(url=i["link"], titulo=i.get("title"), snippet=i.get("snippet"),
                                   data=i.get("date"), posicao=i.get("position", n + 1))
                      for n, i in enumerate(itens) if i.get("link")]
        return resultados, (d.get("search_metadata") or {}).get("id"), d.get("error")

    def buscar(self, consulta, filtros):
        params = self._params(consulta, filtros)
        r = chamar("GET", self.URL, params={**params, "api_key": self._chave}, timeout=self._timeout)
        reg = RegistroChamada(provedor=self.nome, operacao="buscar", parametros=params,
                              requisitado_em=agora(), http_status=r["http_status"],
                              latencia_ms=r["latencia_ms"], tentativas=r["tentativas"], erro=r["erro"])
        reg.extras.update(extras_http(r))
        resultados = []
        if r["resp"] is not None:
            reg.raw = r["resp"].content
        if reg.erro is None:
            try:
                resultados, reg.id_externo, erro_api = self.interpretar(r["resp"].text)
                # TODO(verificar): texto e status de uma busca sem resultados (a documentacao nao traz exemplo)
                if erro_api and "hasn't returned any results" not in erro_api:
                    reg.erro = erro_api
            except (ValueError, KeyError, TypeError, AttributeError) as e:     # AttributeError: item que nao e objeto
                reg.erro = f"resposta_inesperada: {e!r}"
        return RespostaBusca(resultados, reg)
