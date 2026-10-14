import time
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlsplit
import requests

from dominio.modelos import RegistroChamada, ArquivoBaixado
from infra.http import chamar, extras_http
from infra.util import agora

_REDIRECIONAMENTOS = (301, 302, 303, 307, 308)
_CORPO_ERRO_MAX = 16_384          # bytes do corpo de uma resposta de erro guardados (distingue WAF de 403 genuino)
_POLITICAS_ROBOTS = ("permitir", "bloquear")


class FetcherRequests:
    nome = "requests"

    def __init__(self, user_agent, timeout=30, max_bytes=8_000_000, respeitar_robots=True,
                 tempo_maximo=120, max_redirecionamentos=5, robots_se_inacessivel="permitir"):
        """`timeout` vale por leitura de socket; `tempo_maximo` e o prazo total (segundos) de cada download.

        `robots_se_inacessivel`: o que fazer quando o robots.txt responde 5xx ou nao pode ser lido.
        "permitir" segue a especificacao; "bloquear" segue a RFC 9309 (5xx ou rede = assuma proibido).
        Resposta 4xx (sem robots.txt) sempre permite.
        """
        if robots_se_inacessivel not in _POLITICAS_ROBOTS:
            raise ValueError(f"robots_se_inacessivel deve ser um de {_POLITICAS_ROBOTS}, nao {robots_se_inacessivel!r}")
        self._ua, self._timeout, self._max = user_agent, timeout, max_bytes
        self._tempo_max, self._max_redir, self._politica = tempo_maximo, max_redirecionamentos, robots_se_inacessivel
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
                inacessivel = status >= 500
                rp.parse(t.text.splitlines() if t.ok else [])
            except requests.RequestException:
                inacessivel = True
                rp.parse([])                      # no accessible robots.txt: allowed (unless the policy says otherwise)
            if inacessivel and self._politica == "bloquear":
                rp.disallow_all = True
            self._robots[base], self._robots_status[base] = rp, status
        return self._robots[base].can_fetch(self._ua, url)

    def baixar(self, url):
        inicio = time.perf_counter()
        reg = RegistroChamada(provedor=self.nome, operacao="baixar", parametros={"url": url},
                              requisitado_em=agora(), raw_ext="bin")
        vazio = ArquivoBaixado(url, None, "", b"", False, reg)
        atual, visitadas, soma_ms = url, [url], 0
        for salto in range(self._max_redir + 1):
            if self._robots_on:
                permitido = self._permitido(atual)
                # a consulta ao robots.txt nao e uma chamada propria: o resultado fica nos extras desta chamada
                chave = "robots" if salto == 0 else f"robots_salto_{salto}"
                reg.extras[f"{chave}_permitido"] = permitido
                reg.extras[f"{chave}_status"] = self._robots_status.get(self._base(atual))
                if not permitido:
                    reg.erro = "bloqueado_por_robots" if salto == 0 else f"bloqueado_por_robots_apos_redirecionamento: {atual}"
                    if salto > 0:
                        reg.extras["redirecionamentos"] = visitadas
                    return vazio
            # o robots.txt vale para cada destino: os redirecionamentos sao seguidos aqui, e nao pelo requests
            r = chamar("GET", atual, headers={"User-Agent": self._ua}, timeout=self._timeout, stream=True,
                       allow_redirects=False, ler_corpo_erro=_CORPO_ERRO_MAX)
            soma_ms += r.get("latencia_total_ms") or 0
            resp = r["resp"]
            destino = resp.headers.get("Location") if resp is not None else None
            if resp is not None and r["erro"] is None and resp.status_code in _REDIRECIONAMENTOS and destino:
                resp.close()
                atual = urljoin(atual, destino)
                visitadas.append(atual)
                continue
            break
        else:
            reg.erro = "redirecionamentos_demais"
            reg.extras["redirecionamentos"] = visitadas
            return vazio
        reg.http_status, reg.latencia_ms = r["http_status"], r["latencia_ms"]
        reg.tentativas, reg.erro = r["tentativas"], r["erro"]
        reg.extras.update(extras_http(r))
        if len(visitadas) > 1:
            reg.extras["redirecionamentos"] = visitadas
        if r["resp"] is None or reg.erro:
            if r.get("corpo_erro"):               # corpo da resposta de erro: separa bloqueio de WAF de 403 genuino
                tipo = r["resp"].headers.get("Content-Type", "").split(";")[0].strip().lower() if r["resp"] is not None else ""
                reg.raw, reg.raw_ext = r["corpo_erro"], ("html" if "html" in tipo else "bin")
                reg.extras["corpo_erro_bytes"] = len(r["corpo_erro"])
            return vazio
        resp = r["resp"]
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        dados, truncado = bytearray(), False
        t_leitura = time.perf_counter()
        try:
            for bloco in resp.iter_content(65536):
                dados.extend(bloco)
                if len(dados) > self._max:
                    dados, truncado = dados[:self._max], True
                    break
                if time.perf_counter() - inicio > self._tempo_max:
                    reg.erro = "tempo_excedido"
                    return vazio
        except requests.RequestException as e:      # a leitura do corpo tambem pode falhar (conexao cortada, timeout)
            reg.erro = f"erro_de_leitura: {e!r}"
            return vazio
        finally:
            resp.close()
            leitura_ms = int((time.perf_counter() - t_leitura) * 1000)
            # a latencia da resposta nao inclui a leitura do corpo: o tempo de leitura e o total ficam nos extras
            reg.extras["tempo_leitura_ms"] = leitura_ms
            reg.extras["latencia_total_ms"] = soma_ms + leitura_ms
        reg.raw_ext = "pdf" if "pdf" in ctype else "html" if "html" in ctype else "bin"
        reg.raw = bytes(dados)
        reg.extras.update(content_type=ctype, truncado=truncado, n_bytes=len(dados))
        return ArquivoBaixado(resp.url, resp.status_code, ctype, bytes(dados), truncado, reg)
