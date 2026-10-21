"""Envio de uma execucao do computador local para o painel na nuvem (D98, D99): POST /api/coletas com o pacote em JSON
compactado (gzip) e o token de envio do usuario. Reenviar e seguro (a nuvem so acrescenta e atualiza o que mudou), por
isso nao ha nova tentativa automatica: quem envia repete o comando. Nunca levanta erro de rede: so ErroEnvio."""
import gzip
import json

from infra.http import chamar


class ErroEnvio(Exception):
    pass


class EnvioNuvem:
    def __init__(self, url_base, token, chamar_http=chamar):
        self.url = url_base.rstrip("/") + "/api/coletas"
        self._token = token
        self._chamar = chamar_http

    def enviar(self, pacote):
        """Manda o pacote e devolve a resposta da nuvem ({run_id, tabelas}); ErroEnvio com a mensagem, se recusado."""
        corpo = gzip.compress(json.dumps(pacote, ensure_ascii=False).encode("utf-8"))
        m = self._chamar("POST", self.url, corpo=corpo, timeout=(10, 900), max_tentativas=1,
                         headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                                  "Content-Encoding": "gzip"})
        r = m["resp"]
        if r is None:
            raise ErroEnvio("Não foi possível falar com a nuvem (confira PAINEL_NUVEM_URL e a internet): " + (m["erro"] or "sem resposta"))
        try:
            dados = r.json()
        except ValueError:
            dados = None
        if r.status_code == 200 and isinstance(dados, dict) and isinstance(dados.get("tabelas"), dict):
            return dados
        motivo = dados.get("erro") if isinstance(dados, dict) and isinstance(dados.get("erro"), str) else "resposta sem mensagem"
        raise ErroEnvio(f"A nuvem recusou o envio (HTTP {r.status_code}): {motivo}")
