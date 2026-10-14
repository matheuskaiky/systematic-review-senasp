import os
from functools import cached_property
from dotenv import load_dotenv

import config.settings as S
from adaptadores import REGISTROS, simulados

load_dotenv()


class Fabrica:
    def __init__(self, simulado=False):
        self.simulado = simulado

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
        env = S.SEGREDOS.get(nome)
        if env:
            chave = os.environ.get(env)
            if not chave:
                raise SystemExit(f"Set {env} in .env to use '{nome}'")
            opcoes["chave"] = chave
        return cls(**opcoes)

    # lazy creation: only requires a key for the adapters the command actually uses
    repo = cached_property(lambda self: self._criar("armazenamento"))
    bruto = cached_property(lambda self: self._criar("bruto"))
    busca_web = cached_property(lambda self: self._criar("busca_web"))
    academico = cached_property(lambda self: self._criar("academico"))
    fetcher = cached_property(lambda self: self._criar("fetcher"))
    extrator = cached_property(lambda self: self._criar("extrator"))
    classificador = cached_property(lambda self: self._criar("classificador"))
    exportador = cached_property(lambda self: self._criar("exportador"))
