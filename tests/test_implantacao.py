"""Arquivos da implantacao do painel na nuvem (Docker + Caddy): o que vai para o servidor, o que nunca vai (chaves de API,
dados, documentos internos) e a copia de seguranca. A subida real (imagem + Caddy + HTTPS) roda no CI, job `imagem`."""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CHAVES = ("SERPAPI_KEY", "PERPLEXITY_API_KEY", "GEMINI_API_KEY", "LLM_API_KEY", "SESSION_SECRET")


def _ler(nome):
    return (RAIZ / nome).read_text(encoding="utf-8")


def test_dockerfile():
    d = _ler("Dockerfile")
    for trecho in ("FROM python:3.12.15-slim", "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "PYTHON_DOTENV_DISABLED=1",
                   "WORKDIR /app", "COPY requirements.lock.txt ./", "RUN pip install --no-cache-dir -r requirements.lock.txt",
                   "RUN useradd --create-home painel && mkdir -p /app/data && chown -R painel /app/data", "USER painel",
                   "EXPOSE 8000",
                   'CMD ["sh", "-c", "if [ ! -f /app/data/demo.db ]; then python main.py painel-demo || exit 1; fi; '
                   'exec python main.py painel --demo --servidor --porta 8000"]'):
        assert trecho in d, trecho
    assert not any(c in d for c in CHAVES)


def test_dockerignore_e_lista_do_que_entra_na_imagem():
    linhas = [l for l in _ler(".dockerignore").splitlines() if l.strip() and not l.startswith("#")]
    assert linhas == ["*", "!main.py", "!composicao.py", "!painel_demo.py", "!requirements.lock.txt", "!adaptadores",
                      "!aplicacao", "!dominio", "!infra", "!config", "!painel", "**/__pycache__"]


def test_compose_sem_chaves_de_api_e_so_o_caddy_exposto():
    c = _ler("docker-compose.yml")
    assert not any(ch in c for ch in CHAVES)
    assert "PAINEL_HOSTS: ${DOMAIN_NAME:?defina DOMAIN_NAME no .env}" in c and "image: caddy:2.11.7" in c
    app = c[c.index("  app:"):c.index("  caddy:")]
    assert "ports:" not in app and 'expose:\n      - "8000"' in app and "dados:/app/data" in app
    for trecho in ("init: true", 'PAINEL_PROXY_IPS: "*"', "no-new-privileges:true", "cap_drop:\n      - ALL", 'max-size: "10m"'):
        assert trecho in app, trecho
    assert c.count('max-size: "10m"') == 2 and c.count('max-file: "5"') == 2
    assert '- "80:80"' in c and '- "443:443"' in c and "./Caddyfile:/etc/caddy/Caddyfile:ro" in c


def test_caddyfile():
    linhas = [l.strip() for l in _ler("Caddyfile").splitlines() if l.strip() and not l.strip().startswith("#")]
    assert linhas == ["{$DOMAIN_NAME} {", 'header Strict-Transport-Security "max-age=31536000"', "log",
                      "reverse_proxy app:8000", "}"]


def test_env_example_tem_o_dominio_e_nenhum_valor_preenchido():
    linhas = [l for l in _ler(".env.example").splitlines() if l.strip() and not l.startswith("#")]
    assert "DOMAIN_NAME=" in linhas
    assert all(re.fullmatch(r"[A-Z_]+=", l) for l in linhas), linhas


def test_script_de_copia_executavel_valido_e_pela_api_de_backup():
    caminho = RAIZ / "scripts" / "backup_db.sh"
    assert os.stat(caminho).st_mode & stat.S_IXUSR
    if (RAIZ / ".git").exists():                     # o modo gravado no git e o que a VM recebe ao clonar
        modo = subprocess.run(["git", "ls-files", "-s", "scripts/backup_db.sh"], cwd=RAIZ, capture_output=True, text=True).stdout
        assert modo == "" or modo.startswith("100755 "), modo
    assert subprocess.run(["bash", "-n", str(caminho)]).returncode == 0
    s = caminho.read_text(encoding="utf-8")
    for trecho in ("set -euo pipefail", "fonte.backup(alvo)", "for banco in demo.db contas_demo.db busca.db contas.db; do",
                   'if [ "$situacao" -eq 3 ]; then', 'echo "falha ao copiar ${banco} (codigo ${situacao})" >&2',
                   'copia="/tmp/backup_${DATA}_${banco}"', 'echo "falha ao trazer ${banco} do conteiner" >&2',
                   "find \"$DESTINO\" -maxdepth 1 -type f -name '[0-9]*_*.db' -mtime +14 -delete"):
        assert trecho in s, trecho


def test_readme_fica_so_com_o_uso_local():
    r = _ler("README.md")
    for trecho in ("## Implantação", "docker compose", "gcloud", "Oracle Cloud", "Cloud Run", "Caddy"):
        assert trecho not in r, trecho
    assert "`IMPLANTACAO.md`" in r


def test_guia_de_implantacao_explica_a_oracle():
    r = _ler("IMPLANTACAO.md")
    assert "## Implantação do Painel na Nuvem (Oracle Cloud)" in r
    for trecho in ("docker compose up -d --build",
                   'docker compose exec app python main.py usuario-admin --login <login> --nome "<nome>" --demo',
                   "preencha só DOMAIN_NAME", "chave de implantação (*deploy key*, só leitura)",
                   "docker compose exec app python main.py painel-demo && docker compose restart app",
                   "0 3 * * * cd ~/painel && bash scripts/backup_db.sh >> backups/backup.log 2>&1"):
        assert trecho in r, trecho


def test_ci_sobe_a_imagem_atras_do_caddy():
    w = _ler(".github/workflows/testes.yml")
    assert "  imagem:" in w and "DOMAIN_NAME: localhost" in w and "run: docker compose up -d --build" in w
    assert "grep -qi '^strict-transport-security: max-age=31536000' cabecalhos.txt" in w
    assert "grep -qiE '^set-cookie: __session=[^;]+;.*secure' cabecalhos.txt" in w
    assert 'codigo=$(envio https://localhost)\n          [ "$codigo" = "400" ]' in w
    assert 'codigo=$(envio https://outro-site.example)\n          [ "$codigo" = "403" ]' in w
    assert '[ "$codigo" = "200" ] || { echo "o painel nao respondeu (ultimo codigo: $codigo)"; exit 1; }' in w


def test_dockerfile_do_cloud_run():
    assert (RAIZ / "Dockerfile.cloudrun").is_file()
    d = _ler("Dockerfile.cloudrun")
    for trecho in ("FROM python:3.12.15-slim", "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "PYTHON_DOTENV_DISABLED=1",
                   "DB_BACKEND=postgres", 'PAINEL_PROXY_IPS="*"', "WORKDIR /app", "COPY requirements.lock.txt ./",
                   "RUN pip install --no-cache-dir -r requirements.lock.txt",
                   "RUN useradd --create-home painel && mkdir -p /app/data && chown -R painel /app/data", "USER painel",
                   'CMD ["sh", "-c", "exec python main.py painel --servidor --porta \\"${PORT:-8080}\\""]'):
        assert trecho in d, trecho
    assert not any(c in d for c in CHAVES + ("DATABASE_URL=", "postgresql://"))
    assert "--demo" not in d and "VOLUME" not in d and "painel-demo" not in d


def test_env_example_tem_as_variaveis_do_postgres_vazias():
    linhas = [l for l in _ler(".env.example").splitlines() if l.strip() and not l.startswith("#")]
    assert {"DB_BACKEND=", "DATABASE_URL=", "DATABASE_URL_DIRECT="} <= set(linhas)


def test_guia_de_implantacao_explica_o_cloud_run():
    r = _ler("IMPLANTACAO.md")
    assert "## Implantação do Painel no Google Cloud Run (PostgreSQL no Neon)" in r
    for trecho in ('read -rs URL && printf \'%s\' "$URL" | gcloud secrets create painel-database-url --data-file=- --project "$PROJETO"; unset URL',
                   "--role=roles/secretmanager.secretAccessor",
                   "read -rs DATABASE_URL_DIRECT && export DATABASE_URL_DIRECT && python main.py pg-migrar; unset DATABASE_URL_DIRECT",
                   'DB_BACKEND=postgres python main.py usuario-admin --login <login> --nome "<nome>"; unset DATABASE_URL',
                   'docker build -f Dockerfile.cloudrun -t "$IMAGEM" . && docker push "$IMAGEM"',
                   "--max-instances=1 --min-instances=0 --update-secrets=DATABASE_URL=painel-database-url:latest",
                   "--set-env-vars=PAINEL_HOSTS=painel-${NUMERO}.${REGIAO}.run.app",
                   "gcloud run services update-traffic painel --to-revisions=<revisão anterior>=100"):
        assert trecho in r, trecho
    assert "pg-importar" not in r and "postgresql://" not in r


def test_ci_sobe_a_imagem_do_cloud_run():
    w = _ler(".github/workflows/testes.yml")
    assert "\n  imagem-cloudrun:\n" in w
    job = w[w.index("  imagem-cloudrun:"):]
    for trecho in ("POSTGRES_INITDB_ARGS: --locale-provider=libc --locale=C.UTF-8",
                   "run: docker build -f Dockerfile.cloudrun -t painel-cloudrun .",
                   "painel-cloudrun python main.py pg-migrar", "-e PORT=8080",
                   "grep -qiE '^set-cookie: __session=[^;]+;.*secure' cabecalhos.txt",
                   'codigo=$(envio https://localhost)\n          [ "$codigo" = "400" ]',
                   'codigo=$(envio https://outro-site.example)\n          [ "$codigo" = "403" ]'):
        assert trecho in job, trecho
