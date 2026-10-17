"""Auditoria do que o modelo NAO marcou (funcoes puras, sem E/S).

O modelo pode deixar passar uma aplicacao de IA (falso negativo). Para estimar isso, uma pessoa le uma amostra sorteada
de paginas que o modelo classificou SEM achados e diz se havia uma aplicacao. Aqui ficam o sorteio reproduzivel, a
validacao das respostas e o tamanho de amostra necessario; o banco e o CSV ficam nas camadas de fora."""
import math
import random

from dominio import estatistica as est

AMOSTRA_PADRAO = 30
SEMENTE_PADRAO = "auditoria-negativos"
COLUNAS_AMOSTRA = ("classificacao_id", "uf", "url_id", "url", "texto_path", "classificador", "prompt_versao", "run_id",
                   "revisor", "tinha_aplicacao", "tecnologia", "observacao")
_SIM = {"1", "sim", "s", "yes", "y", "true"}
_NAO = {"0", "nao", "não", "n", "no", "false"}


def amostrar(candidatos, n, semente=SEMENTE_PADRAO):
    """Amostra aleatoria simples ESTRATIFICADA por UF, com alocacao proporcional ao tamanho de cada UF (cada pagina tem a
    mesma chance de entrar, entao a taxa de erro da amostra vale para o conjunto todo). Restos da divisao: maiores sobras
    primeiro, desempate pela UF. Reproduzivel: a mesma semente sobre os mesmos candidatos da a mesma amostra.

    `candidatos` = lista de dicionarios com `classificacao_id` e `uf`. Devolve a sublista, ordenada por (uf, classificacao_id).
    `n` maior que o numero de candidatos devolve todos; n <= 0, lista vazia."""
    n = int(n)
    if n <= 0 or not candidatos:
        return []
    por_uf = {}
    for c in candidatos:
        por_uf.setdefault(c["uf"], []).append(c)
    total = len(candidatos)
    if n >= total:
        return sorted(candidatos, key=lambda c: (c["uf"], c["classificacao_id"]))
    cotas = {uf: n * len(itens) // total for uf, itens in por_uf.items()}
    sobras = sorted(por_uf, key=lambda uf: (-((n * len(por_uf[uf])) % total), uf))
    for uf in sobras[:n - sum(cotas.values())]:
        cotas[uf] += 1
    saida = []
    for uf in sorted(por_uf):
        itens = sorted(por_uf[uf], key=lambda c: c["classificacao_id"])
        saida += random.Random(f"{semente}|{uf}").sample(itens, cotas[uf])
    return sorted(saida, key=lambda c: (c["uf"], c["classificacao_id"]))


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and math.isnan(valor):
        return ""
    return str(valor).strip()


def validar_respostas(linhas, tecnologias):
    """Valida as respostas da pessoa antes de gravar qualquer coisa. `linhas` = dicionarios do CSV (valores texto ou vazios);
    `tecnologias` = chaves do vocabulario. Linha sem `tinha_aplicacao` e uma pagina ainda nao conferida: e pulada.
    Regras: `revisor` obrigatorio; `tinha_aplicacao` = 1/0 (ou sim/nao); com 1, `tecnologia` obrigatoria e do vocabulario;
    com 0, `tecnologia` vazia; o mesmo (classificacao, revisor) nao pode aparecer duas vezes. Erros viram SystemExit com o
    numero da linha da planilha (cabecalho na linha 1). Devolve (registros, n_sem_resposta)."""
    registros, vistos, sem_resposta = [], set(), 0
    for pos, l in enumerate(linhas):
        linha = pos + 2
        bruto = _texto(l.get("tinha_aplicacao")).lower()
        if not bruto:
            sem_resposta += 1
            continue
        try:
            cid = int(float(_texto(l.get("classificacao_id"))))
        except ValueError:
            raise SystemExit(f"classificacao_id invalido: {l.get('classificacao_id')!r} (linha {linha})")
        if bruto in _SIM:
            tinha = 1
        elif bruto in _NAO:
            tinha = 0
        else:
            raise SystemExit(f"tinha_aplicacao invalido: {bruto!r}, use 1 ou 0 (linha {linha})")
        revisor = _texto(l.get("revisor"))
        if not revisor:
            raise SystemExit(f"Informe o revisor (linha {linha})")
        tecnologia = _texto(l.get("tecnologia")) or None
        if tinha == 1 and tecnologia is None:
            raise SystemExit(f"Informe a tecnologia da aplicação que o modelo perdeu (linha {linha})")
        if tinha == 1 and tecnologia not in tecnologias:
            raise SystemExit(f"tecnologia fora do vocabulário: {tecnologia!r} (linha {linha}); válidas: {', '.join(sorted(tecnologias))}")
        if tinha == 0 and tecnologia is not None:
            raise SystemExit(f"tecnologia só vale com tinha_aplicacao = 1 (linha {linha})")
        if (cid, revisor) in vistos:
            raise SystemExit(f"classificacao_id {cid} repetido para o revisor {revisor} (linha {linha})")
        vistos.add((cid, revisor))
        registros.append({"classificacao_id": cid, "url_id": _texto(l.get("url_id")) or None, "uf": _texto(l.get("uf")) or None,
                          "revisor": revisor, "tinha_aplicacao": tinha, "tecnologia": tecnologia,
                          "observacao": _texto(l.get("observacao")) or None, "linha": linha})
    return registros, sem_resposta


def amostra_minima_sem_erros(meta, confianca=0.95):
    """Menor n de paginas conferidas, com ZERO aplicacoes perdidas, para o limite superior unilateral (binomial exato) da taxa
    de falso negativo ficar abaixo de `meta` (0 < meta < 1). Calculado com `limite_superior_binomial_exato(0, n)`, que
    decresce com n, por busca binaria; nada fixo no codigo."""
    baixo, alto = 1, 1_000_000
    while baixo < alto:
        meio = (baixo + alto) // 2
        if est.limite_superior_binomial_exato(0, meio, confianca) < meta:
            alto = meio
        else:
            baixo = meio + 1
    return baixo
