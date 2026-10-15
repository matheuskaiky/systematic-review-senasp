import hashlib
import json
from dominio.modelos import RegistroChamada, ResultadoClassificacao
from dominio.servicos import interpretar_json_classificacao
from infra.http import chamar, extras_http
from infra.util import agora


class ClassificadorOpenAICompat:
    def __init__(self, chave, url, modelo, temperatura=0.0, max_tokens=4096,
                 usar_response_format=False, preco_entrada_por_m=None, preco_saida_por_m=None, timeout=120,
                 campo_max_tokens="max_tokens"):
        """C14: alguns modelos rejeitam `max_tokens` (esperam `max_completion_tokens`) ou qualquer `temperature`.
        `campo_max_tokens` escolhe o nome do campo e `temperatura=None` omite a temperatura.
        TODO(verificar): o que cada provedor aceita (campo do limite de saida, temperatura, response_format)."""
        self._chave, self._url, self._modelo = chave, url, modelo
        self._temp, self._max, self._rf = temperatura, max_tokens, usar_response_format
        self._pin, self._pout, self._timeout = preco_entrada_por_m, preco_saida_por_m, timeout
        self._campo_max = campo_max_tokens
        self.nome = f"openai_compat:{modelo}"

    def _corpo(self, instr):
        sistema = instr.sistema
        corpo = {"model": self._modelo, self._campo_max: self._max}
        if self._temp is not None:
            corpo["temperature"] = self._temp
        if self._rf:
            corpo["response_format"] = {"type": "json_schema",
                                        "json_schema": {"name": "classificacao", "schema": instr.esquema}}
        else:   # no native structured output: the schema goes in the prompt
            sistema += "\nRespond ONLY with valid JSON, following this schema:\n" + json.dumps(instr.esquema, ensure_ascii=False)
        corpo["messages"] = [{"role": "system", "content": sistema}, {"role": "user", "content": instr.usuario}]
        return corpo

    @staticmethod
    def interpretar(raw_texto):
        d = json.loads(raw_texto)
        texto = d["choices"][0]["message"]["content"]
        uso = d.get("usage") or {}
        custo = uso.get("cost")
        if isinstance(custo, dict):
            custo = custo.get("total_cost")
        return texto, uso.get("prompt_tokens"), uso.get("completion_tokens"), custo, d.get("id")

    @staticmethod
    def metadados(raw_texto):
        """O que a resposta diz sobre si mesma: motivo do fim, modelo devolvido, escolhas. Nunca levanta."""
        try:
            d = json.loads(raw_texto)
            escolhas = d.get("choices")
            escolha = escolhas[0] if isinstance(escolhas, list) and escolhas else None
            uso = d.get("usage") or {}
            return {"finish_reason": escolha.get("finish_reason") if escolha else None, "modelo_versao": d.get("model"),
                    "response_id": d.get("id"), "tokens_entrada": uso.get("prompt_tokens"),
                    "tokens_saida": uso.get("completion_tokens"), "sem_escolhas": escolha is None}
        except (ValueError, TypeError, AttributeError):
            return {}

    def _custo_por_tokens(self, t_in, t_out):
        if self._pin is None or self._pout is None or t_in is None:
            return None
        return (t_in * self._pin + (t_out or 0) * self._pout) / 1_000_000

    def classificar(self, entrada, instr):
        corpo = self._corpo(instr)
        r = chamar("POST", self._url, json_body=corpo, timeout=self._timeout,
                   headers={"Authorization": f"Bearer {self._chave}", "Content-Type": "application/json"})
        reg = RegistroChamada(
            provedor=self.nome, operacao="classificar",
            parametros={"modelo": self._modelo, "temperatura": self._temp, self._campo_max: self._max,
                        "usar_response_format": self._rf, "prompt_versao": instr.versao,
                        "uf": entrada.uf, "url": entrada.url, "n_chars": len(entrada.texto),
                        "entrada_sha256": hashlib.sha256(instr.usuario.encode()).hexdigest(),
                        "sistema_sha256": hashlib.sha256(instr.sistema.encode()).hexdigest()},
            requisitado_em=agora(), http_status=r["http_status"], latencia_ms=r["latencia_ms"],
            tentativas=r["tentativas"], erro=r["erro"])
        reg.extras.update(extras_http(r))
        texto, relevante, achados, valido = "", False, [], False
        if r["resp"] is not None:
            reg.raw = r["resp"].content
        if reg.erro is None:
            try:
                meta = self.metadados(r["resp"].text)
                reg.extras.update({k: v for k, v in meta.items()
                                   if v is not None and v is not False and k not in ("tokens_entrada", "tokens_saida")})
                reg.id_externo = meta.get("response_id")
                if meta.get("sem_escolhas"):
                    # resposta sem `choices`: os tokens ficam registrados, como no Gemini
                    reg.tokens_entrada, reg.tokens_saida = meta.get("tokens_entrada"), meta.get("tokens_saida")
                    reg.custo_usd = self._custo_por_tokens(reg.tokens_entrada, reg.tokens_saida)
                    reg.erro = "sem_escolhas: resposta sem choices"
                else:
                    texto, reg.tokens_entrada, reg.tokens_saida, custo, reg.id_externo = self.interpretar(r["resp"].text)
                    if custo is None:
                        custo = self._custo_por_tokens(reg.tokens_entrada, reg.tokens_saida)
                        origem = "calculado_por_tokens"
                    else:
                        origem = "informado_pelo_provedor"
                    reg.custo_usd = custo
                    if custo is not None:
                        reg.extras["custo_origem"] = origem
                    if meta.get("finish_reason") == "length":
                        # saida cortada pelo limite de tokens: falha visivel, com tokens e custo gravados (como no Gemini)
                        reg.erro = "resposta_truncada: length"
                    else:
                        relevante, achados, valido = interpretar_json_classificacao(texto)
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                reg.erro = f"resposta_inesperada: {e!r}"
        return ResultadoClassificacao(relevante, achados, valido, texto, reg)
