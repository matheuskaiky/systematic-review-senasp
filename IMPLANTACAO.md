# Implantação do Painel na Nuvem

Como publicar o painel web fora do computador local. A coleta, a classificação, a triagem e as chaves de API continuam no computador de quem pesquisa; o uso local está no `README.md`.

## Implantação do Painel na Nuvem (Oracle Cloud)

Só o painel vai para o servidor: a coleta, a triagem e as chaves de API continuam na máquina de quem pesquisa. A primeira implantação usa o banco de demonstração, sempre com login. O painel roda atrás do Caddy, que emite e renova o certificado HTTPS do domínio.

**Na Oracle Cloud (uma vez):**

1. Crie uma instância Ubuntu 22.04 ou 24.04 (por exemplo, *VM.Standard.A1.Flex*) com IPv4 público.
2. Libere as portas 80 e 443 na *Security List* da rede (regras de entrada TCP, origem `0.0.0.0/0`) e no firewall da própria VM:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

3. No registrador do domínio, crie um registro `A` apontando o nome do painel (por exemplo, `revisao`) para o IP público da VM.

**Na VM:**

```bash
curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
sudo usermod -aG docker $USER            # saia e entre de novo na sessão
git clone <URL_DO_REPOSITORIO> painel && cd painel
cp .env.example .env                     # preencha só DOMAIN_NAME (as chaves de API ficam vazias no servidor)
docker compose up -d --build
docker compose exec app python main.py usuario-admin --login <login> --nome "<nome>" --demo
```

Se o repositório for privado, clone com uma chave de implantação (*deploy key*, só leitura) do GitHub cadastrada na VM.

O painel fica em `https://<DOMAIN_NAME>`. O banco, as decisões e as contas ficam no volume `dados` do Docker e sobrevivem a reinícios e atualizações (`git pull && docker compose up -d --build`). Para recomeçar a demonstração do zero: `docker compose exec app python main.py painel-demo && docker compose restart app`.

**Cópias de segurança:** `scripts/backup_db.sh` copia os bancos com o painel no ar (API de backup do SQLite) para `./backups` e apaga as cópias com mais de 14 dias. Para rodar todo dia às 3h, acrescente ao `crontab -e` da VM: `0 3 * * * cd ~/painel && bash scripts/backup_db.sh >> backups/backup.log 2>&1`. Guarde também cópias fora da VM.

**Concorrência:** o SQLite roda em modo WAL (quem lê não espera quem grava; um escritor por vez) com um único processo do servidor.

## Implantação do Painel no Google Cloud Run (PostgreSQL no Neon)

Só o painel vai para a nuvem: a coleta, a classificação e as chaves de API continuam no computador do pesquisador, sobre o SQLite local (o padrão de todos os comandos). Na nuvem, as decisões e as contas ficam num PostgreSQL do Neon; o Cloud Run não guarda arquivos. O banco da nuvem começa vazio: nenhum comando copia para lá o banco com dados reais.

**Antes:** um projeto no Google Cloud com faturamento ativo, o `gcloud` instalado e logado (`gcloud auth login`), o Docker local, e um projeto no Neon com PostgreSQL 16 ou 17 (de preferência na região São Paulo, `aws-sa-east-1`). O banco do Neon já vem com a ordenação `C.UTF-8`, a que o painel exige. Do Neon saem duas URLs: a do pool (com `-pooler` no host), usada pelo painel, e a direta (sem `-pooler`), usada só para migrar. As duas são segredos: nunca vão para arquivo versionado nem para o histórico do terminal (os comandos abaixo as leem do teclado com `read -rs`).

1. Variáveis do terminal e serviços do Google Cloud:
   ```bash
   export PROJETO=<id-do-projeto> REGIAO=southamerica-east1
   export NUMERO=$(gcloud projects describe "$PROJETO" --format='value(projectNumber)')
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project "$PROJETO"
   gcloud artifacts repositories create painel --repository-format=docker --location="$REGIAO" --project "$PROJETO"
   ```
2. A URL do pool como segredo, lido pelo Cloud Run:
   ```bash
   read -rs URL && printf '%s' "$URL" | gcloud secrets create painel-database-url --data-file=- --project "$PROJETO"; unset URL
   gcloud secrets add-iam-policy-binding painel-database-url --project "$PROJETO" \
     --member="serviceAccount:${NUMERO}-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
   ```
3. Tabelas e views no Neon (do computador local, com a URL direta) e o primeiro administrador (com a URL do pool):
   ```bash
   read -rs DATABASE_URL_DIRECT && export DATABASE_URL_DIRECT && python main.py pg-migrar; unset DATABASE_URL_DIRECT
   read -rs DATABASE_URL && export DATABASE_URL && DB_BACKEND=postgres python main.py usuario-admin --login <login> --nome "<nome>"; unset DATABASE_URL
   ```
4. Imagem e implantação (uma instância, que dorme sem uso):
   ```bash
   gcloud auth configure-docker "$REGIAO-docker.pkg.dev"
   export IMAGEM="$REGIAO-docker.pkg.dev/$PROJETO/painel/painel:$(git rev-parse --short HEAD)"
   docker build -f Dockerfile.cloudrun -t "$IMAGEM" . && docker push "$IMAGEM"
   gcloud run deploy painel --image "$IMAGEM" --region "$REGIAO" --project "$PROJETO" --allow-unauthenticated --timeout=900 --memory=1Gi \
     --max-instances=1 --min-instances=0 --update-secrets=DATABASE_URL=painel-database-url:latest \
     --set-env-vars=PAINEL_HOSTS=painel-${NUMERO}.${REGIAO}.run.app
   ```
   O painel fica em `https://painel-<número do projeto>.southamerica-east1.run.app`, sempre com login. `--allow-unauthenticated` só deixa a página abrir na internet; o acesso continua exigindo usuário e senha do painel.

**Enviar a coleta do computador para a nuvem:** quem tem a permissão de enviar coletas gera o token na página Minha conta do painel e o põe no `.env` local, com o endereço do painel (`PAINEL_NUVEM_URL=https://painel-<número>.southamerica-east1.run.app` e `PAINEL_TOKEN=<token>`). Depois, `python main.py enviar --run <run_id>` (repita `--run` para várias) manda só os dados da coleta daquela execução, sem os arquivos brutos e sem decisões humanas; reenviar a mesma execução só acrescenta e atualiza o que mudou. Uma execução que usa páginas baixadas noutra (`--de`) precisa que aquela seja enviada antes; a mensagem diz qual. O pacote tem uma versão (hoje a 2, que leva também a busca de literatura): ao atualizar o programa, atualize primeiro a nuvem e depois o computador local; enquanto as versões forem diferentes, a nuvem recusa o envio e diz as duas versões.

**Atualizar:** quando o código trouxer migração nova, rode antes o `pg-migrar` do passo 3 (o painel se recusa a subir com o esquema desatualizado e diz o que falta); depois repita o passo 4. **Voltar atrás:** `gcloud run services update-traffic painel --to-revisions=<revisão anterior>=100 --region "$REGIAO" --project "$PROJETO"` (as revisões aparecem em `gcloud run revisions list --service painel --region "$REGIAO" --project "$PROJETO"`). **Demonstração:** num banco do Neon vazio e migrado, `read -rs DATABASE_URL_DIRECT && export DATABASE_URL_DIRECT && python main.py pg-demo; unset DATABASE_URL_DIRECT` carrega os dados fictícios do `painel-demo`.
