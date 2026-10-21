import os
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path
from dotenv import load_dotenv

import config.settings as S
from config import triagem_escopo as TE
from adaptadores import REGISTROS, simulados
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite

load_dotenv()


def banco_do_ambiente():
    """'sqlite' (padrao: DB_BACKEND ausente ou vazio) ou 'postgres' (painel na nuvem, D96); qualquer outro valor encerra."""
    backend = os.environ.get("DB_BACKEND", "").strip().lower() or "sqlite"
    if backend not in ("sqlite", "postgres"):
        raise SystemExit("DB_BACKEND aceita só sqlite ou postgres.")
    return backend


_banco_em_uso = []         # o banco escolhido no comando em curso (um so de cada vez)


@contextmanager
def banco_escolhido(banco, simulado=False, demo=False):
    """Durante o comando, as pastas do banco escolhido (D111): no real, nada muda; num outro banco, os dados, os brutos,
    as contas, as copias de seguranca, as saidas e os registros vao para data/<banco>, outputs/<banco> e logs/<banco>,
    com os mesmos nomes de arquivo. Ao sair, tudo volta como estava (o mesmo processo pode rodar outro comando)."""
    if banco not in S.BANCOS:
        raise SystemExit(f"Banco desconhecido: {banco}. Use um destes: {', '.join(S.BANCOS)}.")
    if _banco_em_uso:
        raise SystemExit(f"O banco {_banco_em_uso[0]} já está escolhido neste comando: não dá para escolher outro dentro dele.")
    if banco == "real":
        _banco_em_uso.append(banco)
        try:
            yield
        finally:
            _banco_em_uso.clear()
        return
    if simulado or demo:
        raise SystemExit(f"--banco {banco} não vale com --simulado nem com --demo.")
    if banco_do_ambiente() == "postgres":
        raise SystemExit(f"--banco {banco} só vale com o banco local (SQLite): o painel na nuvem tem um banco só.")
    _banco_em_uso.append(banco)
    antes = (S.DATA_DIR, S.OUT_DIR, S.LOG_DIR, dict(S.OPCOES["sqlite"]), dict(S.OPCOES["local"]), dict(S.OPCOES["excel"]))
    dados, saidas = S.DATA_DIR / banco, S.OUT_DIR / banco
    S.DATA_DIR, S.OUT_DIR, S.LOG_DIR = dados, saidas, S.LOG_DIR / banco
    S.OPCOES["sqlite"]["caminho"] = dados / Path(antes[3]["caminho"]).name
    S.OPCOES["local"]["raiz"] = dados / Path(antes[4]["raiz"]).name
    S.OPCOES["excel"]["pasta"] = saidas
    try:
        yield
    finally:
        _banco_em_uso.clear()
        S.DATA_DIR, S.OUT_DIR, S.LOG_DIR = antes[:3]
        for nome, valor in zip(("sqlite", "local", "excel"), antes[3:]):
            S.OPCOES[nome].clear()
            S.OPCOES[nome].update(valor)


class Fabrica:
    def __init__(self, simulado=False, demo=False):
        self.simulado = simulado
        self.demo = demo                 # banco de demonstracao do painel (dados ficticios)

    @property
    def segredos(self):
        return [v for v in (os.environ.get(e) for e in set(S.SEGREDOS.values())) if v]

    def _criar(self, porta):
        nome = S.PROVEDORES[porta]
        if self.simulado and porta in simulados.POR_PORTA:
            return simulados.POR_PORTA[porta]()
        try:
            cls = REGISTROS[porta][nome]
        except KeyError:
            raise SystemExit(f"Adapter '{nome}' is not registered for port '{porta}'")
        opcoes = dict(S.OPCOES.get(nome, {}))
        if self.simulado and nome == "sqlite":
            opcoes["caminho"] = S.DATA_DIR / "simulado.db"       # simulation never pollutes the real database
        if self.simulado and nome == "local":
            opcoes["raiz"] = S.DATA_DIR / "raw_simulado"
        if self.demo and nome == "sqlite":
            opcoes["caminho"] = S.DATA_DIR / "demo.db"
        if self.demo and nome == "local":
            opcoes["raiz"] = S.DATA_DIR / "raw_demo"
        env = S.SEGREDOS.get(nome)
        if env:
            chave = os.environ.get(env)
            if not chave:
                raise SystemExit(f"Set {env} in .env to use '{nome}'")
            opcoes["chave"] = chave
        if "user_agent" in opcoes:       # e-mail de contato vem do ambiente, nao da configuracao
            email = os.environ.get(S.EMAIL_PESQUISADOR_ENV)
            if not email:
                raise SystemExit(f"Set {S.EMAIL_PESQUISADOR_ENV} in .env to use '{nome}'")
            opcoes["user_agent"] = opcoes["user_agent"].replace("{email}", email)
        return cls(**opcoes)

    def _criar_triador(self):
        """Triador de escopo: mesmas opcoes, mesmo provedor, modelo e chave do classificador configurado (nao ha porta
        propria em `config/settings.py`), com o limite de tokens de saida proprio dos lotes. Se o provedor do classificador
        nao tiver um adaptador de triagem registrado, encerra com uma mensagem clara."""
        if self.simulado:
            return simulados.POR_PORTA["triador"]()
        nome = S.PROVEDORES["classificador"]
        if nome not in REGISTROS["triador"]:
            raise SystemExit(f"Adapter '{nome}' is not registered for port 'triador'")
        opcoes = dict(S.OPCOES[nome])
        opcoes["max_tokens_saida"] = TE.MAX_TOKENS_SAIDA
        env = S.SEGREDOS[nome]
        chave = os.environ.get(env)
        if not chave:
            raise SystemExit(f"Set {env} in .env to use '{nome}'")
        opcoes["chave"] = chave
        return REGISTROS["triador"][nome](**opcoes)

    @property
    def caminho_banco(self):
        if self.demo:
            return S.DATA_DIR / "demo.db"
        return S.DATA_DIR / "simulado.db" if self.simulado else Path(S.OPCOES["sqlite"]["caminho"])

    def envio_nuvem(self):
        """O cliente que envia execucoes para o painel na nuvem (D98), com a URL e o token do .env; mensagens fixas."""
        import re
        from adaptadores.envio_nuvem import EnvioNuvem
        from dominio.autenticacao import RE_TOKEN
        url = os.environ.get("PAINEL_NUVEM_URL", "").strip()
        token = os.environ.get("PAINEL_TOKEN", "").strip()
        if not url:
            raise SystemExit("Defina PAINEL_NUVEM_URL no .env: o endereço do painel na nuvem (https://...).")
        if not re.fullmatch(r"https://[^\s/?#]+/?|http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?/?", url):
            raise SystemExit("PAINEL_NUVEM_URL precisa ser só o endereço do painel, começando com https:// (ou http://localhost para teste).")
        if not token:
            raise SystemExit("Defina PAINEL_TOKEN no .env: o token da sua página Minha conta no painel.")
        if not RE_TOKEN.fullmatch(token):
            raise SystemExit("PAINEL_TOKEN não tem o formato de um token do painel (srsp_ e mais 43 caracteres).")
        return EnvioNuvem(url, token)

    @cached_property
    def postgres(self):
        """(pool, chaves) quando DB_BACKEND=postgres (o painel na nuvem, D96); None no SQLite, o padrao. Nunca volta ao
        SQLite em silencio: sem a URL ou sem o banco, encerra com mensagem clara."""
        if banco_do_ambiente() == "sqlite":
            return None
        if self.simulado:
            raise SystemExit("--simulado usa só o SQLite: tire DB_BACKEND=postgres do ambiente.")
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            raise SystemExit("Com DB_BACKEND=postgres, defina DATABASE_URL (no Neon, a URL com -pooler).")
        from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
        try:
            pool = criar_pool(url)
        except ValueError as e:
            raise SystemExit(str(e))
        except Exception:
            raise SystemExit("A DATABASE_URL é inválida (confira o formato postgresql://usuario:senha@host/banco).")
        try:
            return pool, chaves_do_banco(pool)
        except Exception:
            pool.close()
            raise SystemExit("Não foi possível conectar ao PostgreSQL (confira a DATABASE_URL, a senha e se o banco está no ar).")

    def esquema_postgres_pendente(self):
        """Migracoes que faltam no PostgreSQL (lista vazia = em dia). So com DB_BACKEND=postgres."""
        from adaptadores import migrador_postgres
        pool, _ = self.postgres
        with pool.connection() as conn:
            pend = migrador_postgres.pendentes_na_conexao(conn)
            conn.rollback()
        return pend

    def novo_repositorio(self):
        """Uma conexao nova a cada chamada (o painel abre uma por requisicao e a fecha)."""
        if self.postgres:
            from adaptadores.repositorio_postgres import RepositorioPostgres
            return RepositorioPostgres(*self.postgres)
        return self._criar("armazenamento")

    def leitura_painel(self):
        if self.postgres:
            from adaptadores.leitura_postgres import LeituraPainelPostgres
            return LeituraPainelPostgres(*self.postgres)
        return LeituraPainelSQLite(self.caminho_banco)

    def contas(self, caminho_sqlite):
        """Contas do painel: no PostgreSQL com DB_BACKEND=postgres; senao, o arquivo SQLite indicado."""
        if self.postgres:
            from adaptadores.contas_postgres import ContasPostgres
            return ContasPostgres(*self.postgres)
        return ContasSQLite(caminho_sqlite)

    # lazy creation: only requires a key for the adapters the command actually uses
    repo = cached_property(lambda self: self._criar("armazenamento"))
    bruto = cached_property(lambda self: self._criar("bruto"))
    busca_web = cached_property(lambda self: self._criar("busca_web"))
    academico = cached_property(lambda self: self._criar("academico"))
    fetcher = cached_property(lambda self: self._criar("fetcher"))
    extrator = cached_property(lambda self: self._criar("extrator"))
    classificador = cached_property(lambda self: self._criar("classificador"))
    triador = cached_property(lambda self: self._criar_triador())
    exportador = cached_property(lambda self: self._criar("exportador"))
