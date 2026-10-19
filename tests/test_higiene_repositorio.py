"""Higiene do repositorio: o que e dado, log, cache ou segredo nunca entra no git (regra de versionamento do projeto)."""
import pathlib
import subprocess

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# o `.gitignore` do pesquisador tem acrescimos locais (*.zip etc.) que ficam fora do commit: aqui so se exige o que o repositorio ja tem
PADROES_OBRIGATORIOS = (".env", "data/", "outputs/", "logs/", "__pycache__/", ".venv/", ".pytest_cache/")


def _linhas_do_gitignore():
    return {l.strip() for l in (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}


def test_gitignore_cobre_dados_logs_caches_e_segredos():
    faltam = [p for p in PADROES_OBRIGATORIOS if p not in _linhas_do_gitignore()]
    assert not faltam, f"faltam no .gitignore: {faltam}"


def test_nenhum_arquivo_proibido_esta_rastreado():
    if not (RAIZ / ".git").exists():
        return                                      # exportacao sem historico: so vale a regra do .gitignore acima
    rastreados = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True).stdout.splitlines()
    proibidos = [f for f in rastreados if f == ".env" or f.endswith((".pyc", ".log", ".zip", ".db", ".xlsx"))
                 or f.split("/")[0] in ("data", "logs", "outputs", "docs", ".claude")
                 or "/__pycache__/" in f or f in ("CLAUDE.md", "DECISIONS.md", "analises/README.md")]
    assert not proibidos, f"arquivos que nao podem ser versionados: {proibidos[:10]}"


def test_logs_e_caches_sao_ignorados_pelo_git():
    if not (RAIZ / ".git").exists():
        return
    for caminho in ("logs/20261016_130958_5cb9a1.log", "painel/__pycache__/app.cpython-312.pyc", "dominio/__pycache__/x.pyc",
                    "analises/.venv/bin/python", "data/busca.db", "outputs/resultado.xlsx", ".env"):
        r = subprocess.run(["git", "check-ignore", "-q", caminho], cwd=RAIZ)
        assert r.returncode == 0, f"{caminho} deveria estar ignorado"
