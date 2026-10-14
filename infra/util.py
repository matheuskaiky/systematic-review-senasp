import platform
import sys
from datetime import datetime, timezone
from importlib import metadata

BIBLIOTECAS = ("requests", "pandas", "openpyxl", "python-dotenv", "trafilatura", "pypdf")


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def coletar_ambiente(extras=None):
    """Versoes do Python, do sistema e das bibliotecas, mais o que o chamador acrescentar (pausas, argumentos...)."""
    def versao(nome):
        try:
            return metadata.version(nome)
        except metadata.PackageNotFoundError:
            return None
    return {"python": sys.version.split()[0], "plataforma": platform.platform(),
            "bibliotecas": {b: versao(b) for b in BIBLIOTECAS}, **(extras or {})}
