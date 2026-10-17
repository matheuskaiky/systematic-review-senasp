"""Entidades de `nome_solucao` para as telas (RC23). Le os nomes brutos dos achados vigentes, resolve as entidades (dominio/entidades_solucao.py,
com a lista de solucoes conhecidas do contexto) e guarda o resultado enquanto o conjunto de nomes e a lista nao mudam. Nunca grava: o valor bruto
continua intacto no banco e as telas mostram o nome canonico com a explicacao de cada fusao."""
import threading
from urllib.parse import urlencode

from dominio.entidades_solucao import ROTULO_CAMADA, resolver_entidades


class Entidades:
    def __init__(self, leitura, contexto):
        self._leitura, self._contexto = leitura, contexto
        self._trava = threading.Lock()
        self._chave, self._resolucao = None, None

    def obter(self):
        """A `Resolucao` atual. A consulta dos nomes e pequena (um GROUP BY); a resolucao so e refeita quando o conjunto de nomes, as contagens
        ou a lista de solucoes conhecidas mudam (invalidacao pela chave)."""
        ler = getattr(self._leitura, "nomes_solucao_por_uf", None)
        contagens = ler() if ler and self._leitura.existe() else {}
        conhecidas = tuple(self._contexto.solucoes_conhecidas)
        chave = (tuple(sorted(contagens.items())), conhecidas)
        with self._trava:
            if chave != self._chave:
                self._resolucao, self._chave = resolver_entidades(contagens, conhecidas), chave
            return self._resolucao


def link_entidade(entidade):
    """Endereco da lista de achados da entidade: `solucao=<nome canonico>` (e a UF, quando a entidade e de uma UF so)."""
    q = {"solucao": entidade.canonico}
    if len(entidade.ufs) == 1 and entidade.ufs[0]:
        q["uf"] = entidade.ufs[0]
    return "/achados?" + urlencode(q)


def explicacao_da_entidade(entidade):
    """Texto curto para a dica do selo: as outras grafias que foram reunidas ("inclui: SPIA; Sistema de ..."), ou "" se nada foi unificado."""
    if not entidade or not entidade.outras_grafias:
        return ""
    return "inclui: " + "; ".join(entidade.outras_grafias)


def rotulo_da_camada(camada):
    return ROTULO_CAMADA.get(camada, "")
