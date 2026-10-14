import logging
import time
from urllib.parse import quote, quote_plus
import requests

RETENTAVEIS = (429, 500, 502, 503, 504)   # retryable HTTP statuses

# nomes de parametro ou cabecalho cujo valor e segredo (api_key, Authorization, x-goog-api-key...)
_NOMES_SENSIVEIS = ("key", "token", "secret", "password", "passwd", "senha", "authorization", "auth", "credential",
                    "bearer", "cookie", "session", "sig", "access")


def segredos_da_chamada(params, headers):
    """Valores secretos dos parametros e cabecalhos da chamada (inclusive o que vem depois de 'Bearer ')."""
    valores = set()
    for origem in (params or {}, headers or {}):
        for nome, valor in origem.items():
            if valor and any(s in str(nome).lower() for s in _NOMES_SENSIVEIS):
                v = str(valor)
                valores.add(v)
                if v.lower().startswith("bearer "):
                    valores.add(v[7:])
    return {v for v in valores if len(v) >= 4}


def limpar_segredos(texto, segredos):
    """Troca cada segredo (e suas formas codificadas em URL) por ***. O erro do requests traz a URL completa."""
    if not texto:
        return texto
    for s in sorted(segredos, key=len, reverse=True):
        for forma in {s, quote(s, safe=""), quote_plus(s)}:
            texto = texto.replace(forma, "***")
    return texto


def chamar(metodo, url, *, params=None, json_body=None, headers=None, timeout=60,
           max_tentativas=4, espera_base=2, stream=False, allow_redirects=True, ler_corpo_erro=0):
    """HTTP with retry/backoff. Never raises: returns a metrics dict.

    Alem do contrato da especificacao, devolve `latencia_total_ms` (relogio de parede, com as esperas
    entre tentativas) e `historico` (uma entrada por tentativa). `latencia_ms` continua sendo a da ultima.
    `allow_redirects=False` deixa o chamador seguir os redirecionamentos (para checar o robots.txt de cada destino).
    Com stream=True e `ler_corpo_erro=N`, uma resposta de erro tem os primeiros N bytes do corpo devolvidos em
    `corpo_erro` antes de ser fechada (permite distinguir um bloqueio de WAF de um 403 genuino).
    """
    latencia, ultimo_erro, historico = None, None, []
    inicio = time.perf_counter()
    segredos = segredos_da_chamada(params, headers)

    def total():
        return int((time.perf_counter() - inicio) * 1000)

    for tentativa in range(1, max_tentativas + 1):
        t0 = time.perf_counter()
        try:
            r = requests.request(metodo, url, params=params, json=json_body, headers=headers,
                                 timeout=timeout, stream=stream, allow_redirects=allow_redirects)
            latencia = int((time.perf_counter() - t0) * 1000)
            if r.status_code in RETENTAVEIS and tentativa < max_tentativas:
                ultimo_erro = f"HTTP {r.status_code}"
                espera = espera_base ** tentativa
                historico.append({"tentativa": tentativa, "http_status": r.status_code,
                                  "latencia_ms": latencia, "erro": ultimo_erro, "espera_s": espera})
                r.close()
                logging.warning("%s (attempt %d); waiting", ultimo_erro, tentativa)
                time.sleep(espera)
                continue
            erro = None if r.ok else limpar_segredos(
                f"HTTP {r.status_code}" + ("" if stream else f": {r.text[:300]}"), segredos)
            corpo_erro = None
            if stream and not r.ok:
                if ler_corpo_erro:
                    partes, lidos = [], 0
                    try:
                        for bloco in r.iter_content(4096):
                            partes.append(bloco)
                            lidos += len(bloco)
                            if lidos >= ler_corpo_erro:
                                break
                    except requests.RequestException:
                        pass            # o corpo do erro e opcional: o erro HTTP ja esta registrado
                    corpo_erro = b"".join(partes)[:ler_corpo_erro]
                r.close()               # C10: resposta em streaming com erro nao pode ficar aberta
            historico.append({"tentativa": tentativa, "http_status": r.status_code,
                              "latencia_ms": latencia, "erro": erro, "espera_s": None})
            return {"resp": r, "http_status": r.status_code, "latencia_ms": latencia,
                    "tentativas": tentativa, "erro": erro, "corpo_erro": corpo_erro,
                    "latencia_total_ms": total(), "historico": historico}
        except requests.RequestException as e:
            latencia = int((time.perf_counter() - t0) * 1000)
            ultimo_erro = limpar_segredos(repr(e), segredos)      # o repr traz a URL, com a api_key da query string
            espera = espera_base ** tentativa if tentativa < max_tentativas else None
            historico.append({"tentativa": tentativa, "http_status": None, "latencia_ms": latencia,
                              "erro": ultimo_erro, "espera_s": espera})
            logging.warning("Network error (attempt %d): %s", tentativa, ultimo_erro)
            if espera is not None:
                time.sleep(espera)
    return {"resp": None, "http_status": None, "latencia_ms": latencia,
            "tentativas": max_tentativas, "erro": ultimo_erro, "corpo_erro": None,
            "latencia_total_ms": total(), "historico": historico}


def extras_http(r):
    """Campos de `chamar` que o adaptador deve guardar em RegistroChamada.extras (vao para chamadas.extras_json)."""
    return {"latencia_total_ms": r.get("latencia_total_ms"), "historico": r.get("historico", [])}
