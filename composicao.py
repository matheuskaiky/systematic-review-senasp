import os
from functools import cached_property
from pathlib import Path
from dotenv import load_dotenv

import config.settings as S
from config import triagem_escopo as TE
from adaptadores import REGISTROS, simulados
from adaptadores.leitura_sqlite import LeituraPainelSQLite

load_dotenv()


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

    def novo_repositorio(self):
        """Uma conexao nova a cada chamada (o painel abre uma por requisicao e a fecha)."""
        return self._criar("armazenamento")

    def leitura_painel(self):
        return LeituraPainelSQLite(self.caminho_banco)

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
