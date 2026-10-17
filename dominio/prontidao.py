"""Prontidão metodológica: o que falta rotular para destravar cada análise que depende de decisão humana (funções puras, sem E/S).

Três travas, cada uma com os mínimos que o script correspondente EXIGE (os scripts de `analises/` guardam as próprias cópias
destas constantes; `tests/test_prontidao.py` confere que os números são idênticos):

- H2, regressão logística (`analises/h2_logistica.py`): MIN_VERIFICADOS e MIN_CLASSE_RARA;
- H5, bibliometria (`analises/h5_bibliometria.py`): MIN_DECISOES e MIN_POR_GRUPO;
- auditoria dos negativos do modelo: `amostra_minima_sem_erros(META_AUDITORIA)`, calculado, nunca fixo.

Cada função devolve dicionários simples (prontos para JSON): `progresso(...)` para uma condição isolada e `prontidao_*` para a
trava inteira, com a lista de condições, se está destravada e o menor número de rótulos que ainda faltam."""
from dominio.auditoria_negativos import amostra_minima_sem_erros

H2_MIN_VERIFICADOS = 200
H2_MIN_CLASSE_RARA = 40
H5_MIN_DECISOES = 50
H5_MIN_POR_GRUPO = 10
META_AUDITORIA = 0.05           # meta mínima de falso negativo (5%); a rigorosa (2%) exige mais páginas, ver `amostra_minima_sem_erros`


def progresso(n, minimo, rotulo=""):
    """Uma condição: {rotulo, n, minimo, faltam, destravado, fracao}. `fracao` vai de 0 a 1 (barra de progresso)."""
    n, minimo = max(int(n or 0), 0), max(int(minimo), 0)
    return {"rotulo": rotulo, "n": n, "minimo": minimo, "faltam": max(minimo - n, 0), "destravado": n >= minimo,
            "fracao": 1.0 if minimo == 0 else min(n / minimo, 1.0)}


def _trava(condicoes, extra=None):
    """Junta as condições. Cada rótulo novo pode cobrir ao mesmo tempo o total e a classe menor, então o mínimo de rótulos que
    ainda faltam é o MAIOR `faltam` entre as condições (não a soma)."""
    return {"condicoes": condicoes, "destravado": all(c["destravado"] for c in condicoes),
            "faltam": max(c["faltam"] for c in condicoes), **(extra or {})}


def prontidao_h2(n_confirmados, n_descartados):
    """H2: `n_confirmados` + `n_descartados` = achados verificados por pessoa (com todos os preditores). A classe minoritária
    é a MENOR das duas (a mesma regra de `analises/h2_logistica.recusa`)."""
    n_conf, n_desc = max(int(n_confirmados or 0), 0), max(int(n_descartados or 0), 0)
    total, rara = n_conf + n_desc, min(n_conf, n_desc)
    return _trava([progresso(total, H2_MIN_VERIFICADOS, "achados verificados"),
                   progresso(rara, H2_MIN_CLASSE_RARA, "classe minoritária (confirmados ou descartados, a menor)")],
                  {"n_confirmados": n_conf, "n_descartados": n_desc})


def prontidao_h5(n_incluir, n_excluir):
    """H5: decisões humanas de triagem (incluir ou excluir; pendente não conta), com mínimo em cada grupo
    (a mesma regra de `analises/h5_bibliometria.recusa`)."""
    n_inc, n_exc = max(int(n_incluir or 0), 0), max(int(n_excluir or 0), 0)
    return _trava([progresso(n_inc + n_exc, H5_MIN_DECISOES, "artigos com decisão de triagem"),
                   progresso(min(n_inc, n_exc), H5_MIN_POR_GRUPO, "menor grupo (incluídos ou excluídos)")],
                  {"n_incluir": n_inc, "n_excluir": n_exc})


def minimo_auditoria(meta=META_AUDITORIA):
    """Páginas negativas a conferir, com zero aplicações perdidas, para o limite superior de 95% ficar abaixo de `meta`."""
    return amostra_minima_sem_erros(meta)


def prontidao_auditoria(n_auditadas, n_universo, n_perdidas=0, meta=META_AUDITORIA):
    """Auditoria dos negativos: `n_auditadas` páginas conferidas de um universo de `n_universo`. O mínimo vale com ZERO
    aplicações perdidas; se a pessoa achar alguma (`n_perdidas`), a meta exige uma amostra maior (a trava só avisa)."""
    minimo = minimo_auditoria(meta)
    t = _trava([progresso(n_auditadas, minimo, "páginas negativas auditadas")],
               {"n_universo": max(int(n_universo or 0), 0), "n_perdidas": max(int(n_perdidas or 0), 0), "meta": meta})
    t["destravado"] = t["destravado"] and t["n_perdidas"] == 0
    return t
