# infra/log.py  (receives the directory as a parameter: infra does not read config)
import logging
import sys
from pathlib import Path


def iniciar_log(run_id, log_dir):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    # C13: console do Windows pode falhar com acentos
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    # C13: chamar duas vezes nao pode duplicar handlers
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()
    for h in (logging.FileHandler(log_dir / f"{run_id}.log", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        raiz.addHandler(h)
