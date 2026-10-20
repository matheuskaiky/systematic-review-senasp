# Painel na nuvem: só o painel roda aqui (coleta e chaves de API ficam fora do servidor). Imagem para amd64 e arm64.
FROM python:3.12.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_DOTENV_DISABLED=1

WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY . .
RUN useradd --create-home painel && mkdir -p /app/data && chown -R painel /app/data
USER painel

EXPOSE 8000
# Primeira etapa: banco de demonstração, criado só na primeira partida (as decisões e as contas ficam no volume /app/data).
CMD ["sh", "-c", "if [ ! -f /app/data/demo.db ]; then python main.py painel-demo || exit 1; fi; exec python main.py painel --demo --servidor --porta 8000"]
