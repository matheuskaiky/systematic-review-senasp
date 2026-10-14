import json
from dominio.modelos import RegistroChamada, ResultadoWeb, RespostaBusca
from infra.http import chamar, extras_http
from infra.util import agora


class BuscaPerplexity:
    nome = "perplexity_search"
    URL = "https://api.perplexity.ai/search"

    def __init__(self, chave, corpo_extra=None, timeout=60, preco_por_requisicao_usd=None):
        self._chave, self._extra, self._timeout = chave, corpo_extra or {}, timeout
        self._preco = preco_por_requisicao_usd

    def _corpo(self, consulta, filtros):
        if filtros.dominios_incluir and filtros.dominios_excluir:
            raise ValueError("Perplexity Search: do not mix allowlist and denylist in the same profile")
        corpo = {"query": consulta.texto, "max_results": filtros.max_resultados}
        # Verificado em 14/10/2026 com chamada real: search_domain_filter aceita o sufixo ".gov.br"
        # (as 50 respostas do perfil oficial vieram so de dominios .gov.br).
        dominios = list(filtros.dominios_incluir) or [f"-{d}" for d in filtros.dominios_excluir]
        if dominios:
            corpo["search_domain_filter"] = dominios
        corpo.update(self._extra)
        return corpo

    @staticmethod
    def interpretar(raw_texto):
        d = json.loads(raw_texto)
        itens = d.get("results") or []
        if itens and isinstance(itens[0], list):          # batch format
            itens = itens[0]
        resultados = [ResultadoWeb(url=i["url"], titulo=i.get("title"), snippet=i.get("snippet"),
                                   data=i.get("date") or i.get("last_updated"), posicao=n + 1)
                      for n, i in enumerate(itens) if i.get("url")]
        return resultados, d.get("id")

    @staticmethod
    def extrair_uso(raw_texto):
        """Campo `usage` da resposta, se a API o devolver (pode trazer o custo cobrado). Nunca levanta."""
        try:
            uso = json.loads(raw_texto).get("usage")
        except (ValueError, AttributeError):
            return None
        return uso if isinstance(uso, dict) else None

    def buscar(self, consulta, filtros):
        corpo = self._corpo(consulta, filtros)
        r = chamar("POST", self.URL, json_body=corpo, timeout=self._timeout,
                   headers={"Authorization": f"Bearer {self._chave}", "Content-Type": "application/json"})
        reg = RegistroChamada(provedor=self.nome, operacao="buscar", parametros=corpo,
                              requisitado_em=agora(), http_status=r["http_status"],
                              latencia_ms=r["latencia_ms"], tentativas=r["tentativas"], erro=r["erro"])
        resultados = []
        reg.extras.update(extras_http(r))
        if r["resp"] is not None:
            reg.raw = r["resp"].content
        if reg.erro is None:
            # Preco: pagina de precos da Perplexity (consultada em 14/10/2026) cobra por requisicao bem-sucedida,
            # sem custo por token. Erro HTTP ou de rede nao grava custo; a retentativa bem-sucedida conta uma vez.
            reg.custo_usd = self._preco        # None se o preco nao foi configurado
            if self._preco is not None:
                reg.extras["custo_origem"] = "estimado_preco_fixo"      # nao e o valor cobrado de fato
            # A resposta real da Search API traz so `id` e `results` (verificado em 14/10/2026), sem `usage`;
            # o campo continua sendo guardado, caso a API passe a devolve-lo.
            uso = self.extrair_uso(r["resp"].text)
            if uso is not None:
                reg.extras["usage"] = uso
            try:
                resultados, reg.id_externo = self.interpretar(r["resp"].text)
            except (ValueError, KeyError, TypeError, AttributeError) as e:    # AttributeError: item que nao e objeto
                reg.erro = f"resposta_inesperada: {e!r}"
        return RespostaBusca(resultados, reg)
