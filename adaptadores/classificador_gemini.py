import hashlib
import json
from dominio.modelos import RegistroChamada, ResultadoClassificacao
from dominio.servicos import interpretar_json_classificacao
from infra.http import chamar, cota_diaria_esgotada, extras_http
from infra.util import agora

# formas de enviar o esquema da resposta (a API documenta mais de uma; so uma chamada real confirma qual o modelo aceita)
FORMATOS_ESQUEMA = ("responseSchema", "responseJsonSchema", "responseFormat")


def _para_esquema_gemini(s):
    """Converts the neutral schema to Gemini's dialect (uppercase types, supported fields only)."""
    out = {}
    if "type" in s:
        out["type"] = s["type"].upper()
    for k in ("description", "enum", "required"):
        if k in s:
            out[k] = s[k]
    if "properties" in s:
        out["properties"] = {k: _para_esquema_gemini(v) for k, v in s["properties"].items()}
    if "items" in s:
        out["items"] = _para_esquema_gemini(s["items"])
    return out


class ClassificadorGemini:
    def __init__(self, chave, modelo, temperatura=0.0, max_tokens_saida=4096,
                 preco_entrada_por_m=None, preco_saida_por_m=None, timeout=120,
                 base_url="https://generativelanguage.googleapis.com/v1beta", formato_esquema="responseSchema"):
        """`formato_esquema`: "responseSchema" (esquema com tipos em maiusculas, como na referencia REST),
        "responseJsonSchema" (JSON Schema) ou "responseFormat" (`generationConfig.responseFormat.text`, com
        `mimeType` no formato de enum da referencia REST)."""
        if formato_esquema not in FORMATOS_ESQUEMA:
            raise ValueError(f"formato_esquema deve ser um de {FORMATOS_ESQUEMA}, nao {formato_esquema!r}")
        self._chave, self._modelo, self._temp, self._max = chave, modelo, temperatura, max_tokens_saida
        self._pin, self._pout, self._timeout, self._base = preco_entrada_por_m, preco_saida_por_m, timeout, base_url
        self._formato = formato_esquema
        self.nome = f"gemini:{modelo}"

    def _config_esquema(self, esquema):
        if self._formato == "responseSchema":
            return {"responseMimeType": "application/json", "responseSchema": _para_esquema_gemini(esquema)}
        if self._formato == "responseJsonSchema":
            return {"responseMimeType": "application/json", "responseJsonSchema": esquema}
        # na referencia REST, TextResponseFormat.mimeType e um enum (APPLICATION_JSON, TEXT_PLAIN): a API real rejeitou
        # o texto "application/json" usado no exemplo do guia (HTTP 400 em 14/10/2026)
        return {"responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": esquema}}}

    def _corpo(self, instr):
        return {
            "systemInstruction": {"parts": [{"text": instr.sistema}]},
            "contents": [{"role": "user", "parts": [{"text": instr.usuario}]}],
            "generationConfig": {"temperature": self._temp, "maxOutputTokens": self._max,
                                 **self._config_esquema(instr.esquema)},
        }

    @staticmethod
    def interpretar(raw_texto):
        d = json.loads(raw_texto)
        partes = d["candidates"][0]["content"]["parts"]
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        uso = d.get("usageMetadata") or {}
        # "thinking" tokens are billed as output
        t_out = (uso.get("candidatesTokenCount") or 0) + (uso.get("thoughtsTokenCount") or 0)
        return texto, uso.get("promptTokenCount"), t_out

    @staticmethod
    def metadados(raw_texto):
        """O que a resposta diz sobre si mesma (C15): motivo do fim, bloqueio, versao do modelo. Nunca levanta."""
        try:
            d = json.loads(raw_texto)
            cands = d.get("candidates")
            cand = cands[0] if isinstance(cands, list) and cands else None
            uso = d.get("usageMetadata") or {}
            sem_conteudo = cand is not None and not ((cand.get("content") or {}).get("parts"))
            return {"finish_reason": cand.get("finishReason") if cand else None,
                    "bloqueio": (d.get("promptFeedback") or {}).get("blockReason"),
                    "modelo_versao": d.get("modelVersion"), "response_id": d.get("responseId"),
                    "tokens_raciocinio": uso.get("thoughtsTokenCount"), "tokens_cache": uso.get("cachedContentTokenCount"),
                    "tokens_entrada": uso.get("promptTokenCount"),
                    "tokens_saida": (uso.get("candidatesTokenCount") or 0) + (uso.get("thoughtsTokenCount") or 0)
                    if uso else None,
                    "service_tier": uso.get("serviceTier"),          # standard, priority ou batch: muda o preco
                    "sem_candidatos": cand is None, "sem_conteudo": sem_conteudo}
        except (ValueError, TypeError, AttributeError):
            return {}

    def _custo(self, t_in, t_out):
        if self._pin is None or self._pout is None or t_in is None:
            return None
        return (t_in * self._pin + (t_out or 0) * self._pout) / 1_000_000

    def classificar(self, entrada, instr):
        corpo = self._corpo(instr)
        r = chamar("POST", f"{self._base}/models/{self._modelo}:generateContent", json_body=corpo,
                   timeout=self._timeout,
                   headers={"x-goog-api-key": self._chave, "Content-Type": "application/json"},
                   nao_repetir=lambda resp: cota_diaria_esgotada(resp.text)[0])
        reg = RegistroChamada(
            provedor=self.nome, operacao="classificar",
            parametros={"modelo": self._modelo, "temperatura": self._temp, "max_tokens_saida": self._max,
                        "formato_esquema": self._formato, "prompt_versao": instr.versao,
                        "uf": entrada.uf, "url": entrada.url, "n_chars": len(entrada.texto),
                        "entrada_sha256": hashlib.sha256(instr.usuario.encode()).hexdigest(),
                        "sistema_sha256": hashlib.sha256(instr.sistema.encode()).hexdigest()},
            requisitado_em=agora(), http_status=r["http_status"], latencia_ms=r["latencia_ms"],
            tentativas=r["tentativas"], erro=r["erro"])
        reg.extras.update(extras_http(r))
        texto, relevante, achados, valido = "", False, [], False
        if r["resp"] is not None:
            reg.raw = r["resp"].content
            if r["http_status"] == 429:
                diaria, renova = cota_diaria_esgotada(r["resp"].text)
                if diaria:                         # a etapa para (ver aplicacao/classificacao.py); nao e falha do item
                    reg.extras["cota_diaria_esgotada"] = True
                    reg.extras["cota_renova_em_s"] = renova
            elif r["http_status"] == 402:          # saldo pre-pago esgotado: repetir nao adianta, a etapa para
                reg.extras["cota_diaria_esgotada"] = True
                reg.extras["cota_motivo"] = "saldo"
        if reg.erro is None:
            try:
                meta = self.metadados(r["resp"].text)
                reg.extras.update({k: v for k, v in meta.items()
                                   if v is not None and v is not False and k not in ("tokens_entrada", "tokens_saida")})
                reg.id_externo = meta.get("response_id")
                if meta.get("sem_candidatos") or meta.get("sem_conteudo"):
                    # C15: prompt bloqueado, resposta sem candidatos ou candidato sem texto (por exemplo, SAFETY).
                    # Os tokens da resposta ficam registrados e o custo e calculado por eles.
                    reg.tokens_entrada, reg.tokens_saida = meta.get("tokens_entrada"), meta.get("tokens_saida")
                    reg.custo_usd = self._custo(reg.tokens_entrada, reg.tokens_saida)
                    if reg.custo_usd is not None:
                        reg.extras["custo_origem"] = "calculado_por_tokens"
                    if meta.get("sem_candidatos"):
                        # TODO(verificar): se um prompt bloqueado e cobrado; o custo acima e conservador (maximo possivel)
                        reg.extras["custo_cobranca_incerta"] = True
                        reg.erro = f"sem_candidatos: {meta.get('bloqueio') or 'sem_motivo'}"
                    else:
                        reg.erro = f"sem_conteudo: {meta.get('finish_reason') or 'sem_motivo'}"
                else:
                    texto, reg.tokens_entrada, reg.tokens_saida = self.interpretar(r["resp"].text)
                    reg.custo_usd = self._custo(reg.tokens_entrada, reg.tokens_saida)
                    if reg.custo_usd is not None:
                        reg.extras["custo_origem"] = "calculado_por_tokens"
                    if meta.get("finish_reason") == "MAX_TOKENS":
                        # saida cortada (o raciocinio conta no limite): nao e uma classificacao. Fica como falha, com os
                        # tokens e o custo gravados, para nao virar um "sem achados" silencioso. O texto parcial esta no bruto.
                        reg.erro = "resposta_truncada: MAX_TOKENS"
                    else:
                        relevante, achados, valido = interpretar_json_classificacao(texto)
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                reg.erro = f"resposta_inesperada: {e!r}"
        return ResultadoClassificacao(relevante, achados, valido, texto, reg)
