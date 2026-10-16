import hashlib
from dominio.modelos import RegistroChamada, ResultadoTriagemLote
from dominio.triagem_escopo import chave_item
from adaptadores.classificador_gemini import ClassificadorGemini
from infra.http import chamar, cota_diaria_esgotada, extras_http
from infra.util import agora


class TriadorEscopoGemini(ClassificadorGemini):
    """Triagem de escopo em lote pela API `generateContent` do Gemini. Reaproveita do classificador o formato do esquema,
    o corpo da requisicao, a leitura da resposta (tokens de raciocinio contam como saida) e o calculo do custo.

    Devolve o TEXTO do modelo e o registro da chamada; a conferencia da resposta e do dominio (`validar_resposta`).
    `max_tokens_saida` tem padrao maior que o do classificador: um lote de 10 itens precisa de ~2.000 tokens de saida,
    mais o raciocinio, que conta no mesmo limite."""

    def __init__(self, chave, modelo, temperatura=0.0, max_tokens_saida=8192, preco_entrada_por_m=None,
                 preco_saida_por_m=None, timeout=180, base_url="https://generativelanguage.googleapis.com/v1beta",
                 formato_esquema="responseSchema"):
        super().__init__(chave, modelo, temperatura=temperatura, max_tokens_saida=max_tokens_saida,
                         preco_entrada_por_m=preco_entrada_por_m, preco_saida_por_m=preco_saida_por_m,
                         timeout=timeout, base_url=base_url, formato_esquema=formato_esquema)

    def triar(self, itens, instr):
        corpo = self._corpo(instr)
        r = chamar("POST", f"{self._base}/models/{self._modelo}:generateContent", json_body=corpo,
                   timeout=self._timeout,
                   headers={"x-goog-api-key": self._chave, "Content-Type": "application/json"},
                   nao_repetir=lambda resp: cota_diaria_esgotada(resp.text)[0])
        reg = RegistroChamada(
            provedor=self.nome, operacao="triar_escopo",
            parametros={"modelo": self._modelo, "temperatura": self._temp, "max_tokens_saida": self._max,
                        "formato_esquema": self._formato, "prompt_versao": instr.versao,
                        "n_itens": len(itens), "itens": [chave_item(i) for i in itens],
                        "entrada_sha256": hashlib.sha256(instr.usuario.encode()).hexdigest(),
                        "sistema_sha256": hashlib.sha256(instr.sistema.encode()).hexdigest()},
            requisitado_em=agora(), http_status=r["http_status"], latencia_ms=r["latencia_ms"],
            tentativas=r["tentativas"], erro=r["erro"])
        reg.extras.update(extras_http(r))
        texto = ""
        if r["resp"] is not None:
            reg.raw = r["resp"].content
            if r["http_status"] == 429:
                diaria, renova = cota_diaria_esgotada(r["resp"].text)
                if diaria:                         # a etapa para (ver aplicacao/triagem_escopo.py); nao e falha do lote
                    reg.extras["cota_diaria_esgotada"] = True
                    reg.extras["cota_renova_em_s"] = renova
        if reg.erro is None:
            try:
                meta = self.metadados(r["resp"].text)
                reg.extras.update({k: v for k, v in meta.items()
                                   if v is not None and v is not False and k not in ("tokens_entrada", "tokens_saida")})
                reg.id_externo = meta.get("response_id")
                if meta.get("sem_candidatos") or meta.get("sem_conteudo"):
                    # prompt bloqueado ou candidato sem texto: tokens e custo ficam registrados
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
                        # lote cortado (o raciocinio conta no limite): FALHA, nunca uma resposta parcial aproveitada.
                        # Tokens e custo ficam gravados; o texto parcial esta no bruto.
                        reg.erro = "resposta_truncada: MAX_TOKENS"
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                reg.erro = f"resposta_inesperada: {e!r}"
        return ResultadoTriagemLote(texto, reg)
