import socket
import threading
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

# Leitura do robots.txt. Uma FALHA de leitura (HTTP >= 500 ou excecao do requests) e repetida de imediato, com espera
# curta, antes de concluir "inacessivel"; essa conclusao vale so por ROBOTS_TTL_FALHA_S segundos (depois o proximo URL do
# host le o robots.txt de novo). Resultados 2xx/3xx/4xx valem ate o fim do processo. Estas constantes ficam no adaptador,
# fora de `config/OPCOES`, de proposito: nao entram no hash da configuracao (nao mudam a politica, so a robustez da leitura).
ROBOTS_TENTATIVAS = 3
ROBOTS_ESPERAS_S = (1.0, 2.0)          # espera antes da 2a e da 3a leitura
ROBOTS_TTL_FALHA_S = 300


def _pausa(segundos):
    """Espera entre as leituras do robots.txt (funcao propria para os testes a trocarem sem tocar em `time.sleep`)."""
    time.sleep(segundos)


def _abortar(resp, estourou):
    """Chamado pelo temporizador quando o prazo total acaba: interrompe a leitura bloqueada do corpo.

    `iter_content` so devolve com o bloco inteiro ou no fim da conexao, entao um servidor que goteja bytes nunca
    deixaria o laco de leitura checar o prazo. O shutdown do socket usa atributos internos do urllib3 (melhor esforco);
    se falhar, o laco ainda confere `estourou` a cada bloco.
    """
    estourou.set()
    try:
        resp.raw._fp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        resp.close()
    except Exception:
        pass


class FetcherRequests:
    nome = "requests"

    def __init__(self, user_agent, timeout=30, max_bytes=8_000_000, respeitar_robots=True,
                 tempo_maximo=120, max_redirecionamentos=5, robots_se_inacessivel="permitir", relogio=None, dormir=None):
        """`timeout` vale por leitura de socket; `tempo_maximo` e o prazo total (segundos) de cada download:
        conferido antes de cada salto e durante a leitura do corpo (por um temporizador, que interrompe uma leitura
        bloqueada). As esperas entre retentativas de `chamar` e a consulta ao robots.txt (ate 10 s por host) ficam fora.

        `robots_se_inacessivel`: o que fazer quando o robots.txt responde 5xx ou nao pode ser lido.
        "permitir" segue a especificacao; "bloquear" segue a RFC 9309 (5xx ou rede = assuma proibido).
        Resposta 4xx (sem robots.txt) sempre permite.

        `relogio` e `dormir` (padrao `time.monotonic` e `time.sleep`) existem para os testes nao
        esperarem de verdade: o relogio mede a validade (TTL) de uma falha de leitura do robots.txt.
        """
        if robots_se_inacessivel not in _POLITICAS_ROBOTS:
            raise ValueError(f"robots_se_inacessivel deve ser um de {_POLITICAS_ROBOTS}, nao {robots_se_inacessivel!r}")
        self._ua, self._timeout, self._max = user_agent, timeout, max_bytes
        self._tempo_max, self._max_redir, self._politica = tempo_maximo, max_redirecionamentos, robots_se_inacessivel
        self._robots_on, self._robots = respeitar_robots, {}
        self._relogio, self._dormir = relogio, dormir

    def _agora_s(self):
        return (self._relogio or time.monotonic)()

    def _esperar(self, segundos):
        (self._dormir or _pausa)(segundos)

    @staticmethod
    def _base(url):
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def _ler_robots(self, base):
        """Le o robots.txt de `base`. Falha (HTTP >= 500 ou excecao do requests) e repetida ate ROBOTS_TENTATIVAS vezes.
        Devolve o registro de cache: {rp, status, inacessivel, tentativas, expira}; `expira` e None (vale para o processo)
        ou o instante, no relogio do fetcher, em que uma falha deixa de valer."""
        rp, status, inacessivel, tentativas = RobotFileParser(), None, True, 0
        for i in range(ROBOTS_TENTATIVAS):
            if i:
                self._esperar(ROBOTS_ESPERAS_S[min(i - 1, len(ROBOTS_ESPERAS_S) - 1)])
            tentativas += 1
            try:
                t = requests.get(base + "/robots.txt", timeout=10, headers={"User-Agent": self._ua})
            except requests.RequestException:
                status = None
                continue
            status = t.status_code
            if status >= 500:
                continue
            inacessivel = False
            rp.parse(t.text.splitlines() if t.ok else [])           # 4xx: sem robots.txt, tudo permitido
            break
        if inacessivel:
            rp.parse([])
            if self._politica == "bloquear":
                rp.disallow_all = True                               # RFC 9309: robots.txt inacessivel = assuma proibido
        return {"rp": rp, "status": status, "inacessivel": inacessivel, "tentativas": tentativas,
                "expira": self._agora_s() + ROBOTS_TTL_FALHA_S if inacessivel else None}

    def _permitido(self, url):
        """Devolve (permitido, registro do robots.txt do host). Leituras bem-sucedidas ficam em cache ate o fim do processo;
        a conclusao "inacessivel" so por ROBOTS_TTL_FALHA_S segundos, para uma queda passageira nao bloquear o host todo."""
        base = self._base(url)
        reg = self._robots.get(base)
        if reg is None or (reg["expira"] is not None and self._agora_s() >= reg["expira"]):
            reg = self._robots[base] = self._ler_robots(base)
        return reg["rp"].can_fetch(self._ua, url), reg

    def baixar(self, url):
        inicio = time.perf_counter()
        reg = RegistroChamada(provedor=self.nome, operacao="baixar", parametros={"url": url},
                              requisitado_em=agora(), raw_ext="bin")
        vazio = ArquivoBaixado(url, None, "", b"", False, reg)
        atual, visitadas, soma_ms = url, [url], 0
        for salto in range(self._max_redir + 1):
            if self._robots_on:
                permitido, info = self._permitido(atual)
                # a consulta ao robots.txt nao e uma chamada propria: o resultado fica nos extras desta chamada
                chave = "robots" if salto == 0 else f"robots_salto_{salto}"
                reg.extras[f"{chave}_permitido"] = permitido
                reg.extras[f"{chave}_status"] = info["status"]
                reg.extras[f"{chave}_inacessivel"] = info["inacessivel"]
                reg.extras[f"{chave}_tentativas"] = info["tentativas"]
                if not permitido:
                    # "bloqueado_por_robots": o robots.txt foi lido e proibe; "robots_inacessivel": nao foi possivel le-lo
                    # e a politica manda bloquear (nao e uma proibicao do site)
                    motivo = "robots_inacessivel" if info["inacessivel"] else "bloqueado_por_robots"
                    reg.erro = motivo if salto == 0 else f"{motivo}_apos_redirecionamento: {atual}"
                    if salto > 0:
                        reg.extras["redirecionamentos"] = visitadas
                    return vazio
            restante = self._tempo_max - (time.perf_counter() - inicio)
            if restante <= 0:
                reg.erro = "tempo_excedido"
                if len(visitadas) > 1:
                    reg.extras["redirecionamentos"] = visitadas
                return vazio
            # o robots.txt vale para cada destino: os redirecionamentos sao seguidos aqui, e nao pelo requests
            r = chamar("GET", atual, headers={"User-Agent": self._ua}, timeout=min(self._timeout, restante), stream=True,
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
        estourou = threading.Event()
        restante = max(self._tempo_max - (t_leitura - inicio), 0)
        temporizador = threading.Timer(restante, _abortar, args=(resp, estourou))
        temporizador.daemon = True
        temporizador.start()
        try:
            for bloco in resp.iter_content(65536):
                dados.extend(bloco)
                if len(dados) > self._max:
                    dados, truncado = dados[:self._max], True
                    break
                if estourou.is_set() or time.perf_counter() - inicio > self._tempo_max:
                    reg.erro = "tempo_excedido"
                    return vazio
            if estourou.is_set():                   # a leitura foi interrompida pelo temporizador
                reg.erro = "tempo_excedido"
                return vazio
        except (requests.RequestException, OSError, ValueError) as e:   # conexao cortada, timeout, resposta fechada no meio
            reg.erro = "tempo_excedido" if estourou.is_set() else f"erro_de_leitura: {e!r}"
            return vazio
        finally:
            temporizador.cancel()
            resp.close()
            leitura_ms = int((time.perf_counter() - t_leitura) * 1000)
            # a latencia da resposta nao inclui a leitura do corpo: o tempo de leitura e o total ficam nos extras
            reg.extras["tempo_leitura_ms"] = leitura_ms
            reg.extras["latencia_total_ms"] = soma_ms + leitura_ms
        reg.raw_ext = "pdf" if "pdf" in ctype else "html" if "html" in ctype else "bin"
        reg.raw = bytes(dados)
        reg.extras.update(content_type=ctype, truncado=truncado, n_bytes=len(dados))
        return ArquivoBaixado(resp.url, resp.status_code, ctype, bytes(dados), truncado, reg)
