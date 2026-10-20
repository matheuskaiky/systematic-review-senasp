#!/usr/bin/env bash
# Copia consistente (API de backup do SQLite, com o painel no ar) dos bancos do volume do painel para ./backups;
# apaga as copias com mais de 14 dias. Rode na pasta do docker-compose.yml, na VM.
set -euo pipefail

DATA=$(date +%Y%m%d_%H%M%S)
DESTINO="${1:-./backups}"
mkdir -p "$DESTINO"

for banco in demo.db contas_demo.db busca.db contas.db; do
  copia="/tmp/backup_${DATA}_${banco}"         # fora do volume: uma copia que falhe nao fica para tras nos dados
  set +e
  docker compose exec -T app python - "/app/data/${banco}" "$copia" <<'PY'
import os, sqlite3, sys
origem, destino = sys.argv[1], sys.argv[2]
if not os.path.exists(origem):
    sys.exit(3)
fonte, alvo = sqlite3.connect(origem), sqlite3.connect(destino)
fonte.backup(alvo)
alvo.close()
fonte.close()
PY
  situacao=$?
  set -e
  if [ "$situacao" -eq 3 ]; then
    continue                                   # este banco nao existe neste servidor (ex.: demonstracao sem o banco real)
  elif [ "$situacao" -ne 0 ]; then
    echo "falha ao copiar ${banco} (codigo ${situacao})" >&2
    exit "$situacao"
  fi
  if ! docker compose cp "app:${copia}" "${DESTINO}/${DATA}_${banco}"; then
    docker compose exec -T app rm -f "$copia"
    echo "falha ao trazer ${banco} do conteiner" >&2
    exit 1
  fi
  docker compose exec -T app rm -f "$copia"
  echo "copiado: ${DESTINO}/${DATA}_${banco}"
done

find "$DESTINO" -maxdepth 1 -type f -name '[0-9]*_*.db' -mtime +14 -delete
