from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit
import requests

from dominio.modelos import RegistroChamada, ArquivoBaixado
from infra.http import chamar, extras_http
from infra.util import agora


class FetcherRequests:
    nome = "requests"

    def __init__(self, user_agent, timeout=30, max_bytes=8_000_000, respeitar_robots=True):
        self._ua, self._timeout, self._max = user_agent, timeout, max_bytes
        self._robots_on, self._robots, self._robots_status = respeitar_robots, {}, {}

    @staticmethod
    def _base(url):
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def _permitido(self, url):
        base = self._base(url)
        if base not in self._robots:
            rp = RobotFileParser()
            status = None
            try:
                t = requests.get(base + "/robots.txt", timeout=10, headers={"User-Agent": self._ua})
                status = t.status_code
                rp.parse(t.text.splitlines() if t.ok else [])
            except requests.RequestException:
                rp.parse([])                      # no accessible robots.txt: allowed
            self._robots[base], self._robots_status[base] = rp, status
        return self._robots[base].can_fetch(self._ua, url)

    def baixar(self, url):
        reg = RegistroChamada(provedor=self.nome, operacao="baixar", parametros={"url": url},
                              requisitado_em=agora(), raw_ext="bin")
        vazio = ArquivoBaixado(url, None, "", b"", False, reg)
        if self._robots_on:
            permitido = self._permitido(url)
            # a consulta ao robots.txt nao e uma chamada propria: o resultado fica nos extras desta chamada
            reg.extras.update(robots_permitido=permitido, robots_status=self._robots_status.get(self._base(url)))
            if not permitido:
                reg.erro = "bloqueado_por_robots"
                return vazio
        r = chamar("GET", url, headers={"User-Agent": self._ua}, timeout=self._timeout, stream=True)
        reg.http_status, reg.latencia_ms = r["http_status"], r["latencia_ms"]
        reg.tentativas, reg.erro = r["tentativas"], r["erro"]
        reg.extras.update(extras_http(r))
        if r["resp"] is None or reg.erro:
            return vazio
        resp = r["resp"]
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        dados, truncado = bytearray(), False
        try:
            for bloco in resp.iter_content(65536):
                dados.extend(bloco)
                if len(dados) > self._max:
                    truncado = True
                    break
        except requests.RequestException as e:      # a leitura do corpo tambem pode falhar (conexao cortada, timeout)
            reg.erro = f"erro_de_leitura: {e!r}"
            return vazio
        finally:
            resp.close()
        reg.raw_ext = "pdf" if "pdf" in ctype else "html" if "html" in ctype else "bin"
        reg.raw = bytes(dados)
        reg.extras.update(content_type=ctype, truncado=truncado, n_bytes=len(dados))
        return ArquivoBaixado(resp.url, resp.status_code, ctype, bytes(dados), truncado, reg)
