import logging
import time
import requests

RETENTAVEIS = (429, 500, 502, 503, 504)   # retryable HTTP statuses


def chamar(metodo, url, *, params=None, json_body=None, headers=None, timeout=60,
           max_tentativas=4, espera_base=2, stream=False):
    """HTTP with retry/backoff. Never raises: returns a metrics dict."""
    latencia, ultimo_erro = None, None
    for tentativa in range(1, max_tentativas + 1):
        t0 = time.perf_counter()
        try:
            r = requests.request(metodo, url, params=params, json=json_body,
                                 headers=headers, timeout=timeout, stream=stream)
            latencia = int((time.perf_counter() - t0) * 1000)
            if r.status_code in RETENTAVEIS and tentativa < max_tentativas:
                ultimo_erro = f"HTTP {r.status_code}"
                r.close()
                logging.warning("%s (attempt %d); waiting", ultimo_erro, tentativa)
                time.sleep(espera_base ** tentativa)
                continue
            erro = None if r.ok else f"HTTP {r.status_code}" + ("" if stream else f": {r.text[:300]}")
            return {"resp": r, "http_status": r.status_code, "latencia_ms": latencia,
                    "tentativas": tentativa, "erro": erro}
        except requests.RequestException as e:
            latencia = int((time.perf_counter() - t0) * 1000)
            ultimo_erro = repr(e)
            logging.warning("Network error (attempt %d): %s", tentativa, ultimo_erro)
            if tentativa < max_tentativas:
                time.sleep(espera_base ** tentativa)
    return {"resp": None, "http_status": None, "latencia_ms": latencia,
            "tentativas": max_tentativas, "erro": ultimo_erro}
