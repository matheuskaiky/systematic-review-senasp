import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _fontes(pasta):
    return [(p, p.read_text(encoding="utf-8")) for p in (RAIZ / pasta).rglob("*.py")]


def _viola(padrao, pastas):
    rx = re.compile(padrao, re.M)
    return [str(p) for pasta in pastas for p, src in _fontes(pasta) if rx.search(src)]


def test_dominio_e_aplicacao_nao_conhecem_adaptadores_config_ou_infra():
    assert not _viola(r"^\s*(from|import)\s+(adaptadores|config|composicao|infra)\b", ["dominio", "aplicacao"])


def test_bibliotecas_de_io_ficam_nos_adaptadores():
    assert not _viola(r"^\s*(from|import)\s+(sqlite3|requests|trafilatura|pypdf|openpyxl)\b", ["dominio", "aplicacao"])


def test_adaptadores_nao_conhecem_aplicacao_nem_composicao():
    assert not _viola(r"^\s*(from|import)\s+(aplicacao|composicao)\b", ["adaptadores", "infra"])


def test_adaptadores_e_infra_nao_importam_config():
    assert not _viola(r"^\s*(from|import)\s+config\b", ["adaptadores", "infra", "dominio", "aplicacao"])


def test_adaptadores_nao_leem_ambiente():
    assert not _viola(r"os\.environ|getenv", ["adaptadores", "dominio", "aplicacao", "infra"])
