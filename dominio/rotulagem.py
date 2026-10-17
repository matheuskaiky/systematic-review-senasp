"""Seleção do que a pessoa precisa rotular para destravar as análises (funções puras, sem E/S).

Princípios:
- reprodutível: a mesma semente sobre os mesmos candidatos dá a mesma seleção (cada sorteio usa `random.Random` com uma semente
  em texto derivada da semente do usuário, do estrato e da célula; nada de estado global);
- só o necessário: o número de linhas é o que falta para o mínimo, mais uma folga percentual;
- a amostra dos achados é ENRIQUECIDA com os que provavelmente têm erro, para que a classe minoritária da regressão (H2) seja
  alcançável; por isso NÃO serve para estimar a precisão global do modelo (use `--aleatoria`);
- os artigos que o modelo excluiu são sorteados ao acaso (sem escolher por relevância), numa ordem única: a planilha básica pega
  os primeiros e a de H4 os seguintes, de modo que, juntas, formam uma amostra aleatória simples dos excluídos (a medida de falsa
  exclusão, H4, fica sem viés)."""
import math
import random

from dominio.auditoria_negativos import amostra_minima_sem_erros
from dominio.relevancia import NIVEIS

FOLGA_PADRAO = 10                      # por cento
SEMENTE_PADRAO = "rotulagem"
FRACAO_MAX_ENRIQUECIDA = 0.7           # no máximo 70% dos achados vêm dos estratos de provável erro; o resto é sorteio do que "parece certo"
METAS_H4 = (0.05, 0.02)                # metas de falsa exclusão (as mesmas de `leitura_analises.METAS_FALSO_NEGATIVO`)

# estratos dos achados, em ordem de prioridade: cada achado entra no primeiro que casa
ESTRATOS_ACHADOS = (
    ("evidencia_nao_confere", "a evidência não confere no texto", lambda c: c.get("evidencia_confere") == 0),
    ("evidencia_nao_cita_tecnologia", "a evidência não cita a tecnologia", lambda c: c.get("evidencia_cita_tecnologia") == 0),
    ("so_snippet", "o modelo leu só o resumo do buscador", lambda c: c.get("origem_texto") != "pagina"),
    ("confianca_baixa", "confiança baixa", lambda c: c.get("confianca") == "baixa"),
)
ESTRATO_SORTEIO = ("sorteio_uf_tecnologia", "sorteio dos demais, por UF e tecnologia")
ESTRATO_ALEATORIO = ("sorteio_simples", "sorteio simples (--aleatoria)")

# composição da planilha de triagem por veredito do modelo: os elegíveis tendem a ser incluídos, os excluídos
# a ser excluídos; assim as duas decisões aparecem. `sem_veredito` (sem triagem de escopo válida) só entra para completar.
COTAS_TRIAGEM = (("elegivel", 50), ("quarentena", 20), ("excluido", 30))      # por cento das linhas
STATUS_ESCOPO = ("elegivel", "quarentena", "excluido")


def com_folga(faltam, folga_pct=FOLGA_PADRAO):
    """Linhas a pedir: o que falta mais a folga (arredondada para cima); 0 se nada falta."""
    faltam = int(faltam)
    return 0 if faltam <= 0 else faltam + math.ceil(faltam * max(float(folga_pct), 0.0) / 100.0)


def alocar_proporcional(tamanhos, n):
    """Divide `n` entre as células em proporção ao tamanho (maiores sobras primeiro, desempate pela chave). Nenhuma célula
    recebe mais que o seu tamanho; `n` >= total devolve todos os tamanhos. Chaves ordenáveis."""
    total = sum(tamanhos.values())
    if n >= total:
        return dict(tamanhos)
    if n <= 0:
        return {k: 0 for k in tamanhos}
    cotas = {k: n * t // total for k, t in tamanhos.items()}
    sobras = sorted(tamanhos, key=lambda k: (-((n * tamanhos[k]) % total), str(k)))
    for k in sobras[:n - sum(cotas.values())]:
        cotas[k] += 1
    return cotas


def sortear(itens, n, semente, chave_id):
    """`n` itens ao acaso, sem repetição, reprodutíveis; devolve ordenados por `chave_id`. `n` >= len devolve todos."""
    itens = sorted(itens, key=chave_id)
    if n >= len(itens):
        return itens
    return sorted(random.Random(semente).sample(itens, max(n, 0)), key=chave_id)


def ordem_aleatoria(itens, semente, chave_id):
    """Uma permutação reprodutível dos itens (a mesma semente dá a mesma ordem)."""
    base = sorted(itens, key=chave_id)
    random.Random(semente).shuffle(base)
    return base


def amostrar_estratificado(itens, n, chave_celula, semente, chave_id):
    """Amostra aleatória estratificada, com alocação proporcional ao tamanho de cada célula (`chave_celula(item)`)."""
    if n <= 0 or not itens:
        return []
    celulas = {}
    for i in itens:
        celulas.setdefault(chave_celula(i), []).append(i)
    cotas = alocar_proporcional({k: len(v) for k, v in celulas.items()}, n)
    saida = []
    for k in sorted(celulas, key=str):
        saida += sortear(celulas[k], cotas[k], f"{semente}|{k}", chave_id)
    return sorted(saida, key=chave_id)


def _id_achado(c):
    return c["achado_id"]


def _celula_uf_tec(c):
    return (c.get("uf") or "", c.get("tecnologia") or "")


def selecionar_achados(candidatos, n, semente=SEMENTE_PADRAO, aleatoria=False):
    """Escolhe `n` achados entre os `candidatos` (dicionários com achado_id, uf, tecnologia, evidencia_confere,
    evidencia_cita_tecnologia, origem_texto, confianca). Devolve [(achado, chave_do_estrato, descricao_do_estrato)] por achado_id.

    Padrão (enriquecido): os estratos de provável erro ocupam no máximo FRACAO_MAX_ENRIQUECIDA de `n`. Primeiro entram TODOS os
    achados cuja evidência não confere (se couberem); o orçamento que sobra é repartido, em proporção ao tamanho, entre os
    estratos "não cita a tecnologia", "só snippet" e "confiança baixa" (cada um aparece, nenhum é engolido pela prioridade). Dentro
    de um estrato que não cabe inteiro, sorteia por UF e tecnologia. O restante vem de um sorteio estratificado por UF e tecnologia dos achados que não caem
    em nenhum estrato, para que as DUAS classes (confirmado e descartado) apareçam. Se faltarem candidatos "limpos", completa
    com sobras dos estratos de erro. `aleatoria`: amostra aleatória simples (a única que serve para estimar a precisão global)."""
    n = int(n)
    if n <= 0 or not candidatos:
        return []
    if aleatoria:
        escolhidos = sortear(candidatos, n, f"{semente}|aleatoria", _id_achado)
        return [(c, ESTRATO_ALEATORIO[0], ESTRATO_ALEATORIO[1]) for c in escolhidos]
    por_estrato = {chave: [] for chave, _, _ in ESTRATOS_ACHADOS}
    limpos = []
    for c in sorted(candidatos, key=_id_achado):
        for chave, _, casa in ESTRATOS_ACHADOS:
            if casa(c):
                por_estrato[chave].append(c)
                break
        else:
            limpos.append(c)
    orcamento = min(int(n * FRACAO_MAX_ENRIQUECIDA), n)
    primeiro = ESTRATOS_ACHADOS[0][0]
    tomar = {primeiro: min(len(por_estrato[primeiro]), orcamento)}             # a evidência que não confere entra por inteiro (se couber)
    resto = [chave for chave, _, _ in ESTRATOS_ACHADOS[1:]]
    tomar.update(alocar_proporcional({k: len(por_estrato[k]) for k in resto}, orcamento - tomar[primeiro]))
    escolhidos, sobras = [], []
    for chave, descricao, _ in ESTRATOS_ACHADOS:
        itens = por_estrato[chave]
        pegos = amostrar_estratificado(itens, tomar[chave], _celula_uf_tec, f"{semente}|{chave}", _id_achado) if tomar[chave] < len(itens) else itens
        ids = {c["achado_id"] for c in pegos}
        escolhidos += [(c, chave, descricao) for c in pegos]
        sobras += [(c, chave, descricao) for c in itens if c["achado_id"] not in ids]
    falta = n - len(escolhidos)
    pegos = amostrar_estratificado(limpos, min(falta, len(limpos)), _celula_uf_tec, f"{semente}|{ESTRATO_SORTEIO[0]}", _id_achado)
    escolhidos += [(c, ESTRATO_SORTEIO[0], ESTRATO_SORTEIO[1]) for c in pegos]
    falta = n - len(escolhidos)
    if falta > 0 and sobras:                              # poucos achados "limpos": completa com sobras dos estratos de erro
        extra = sortear(sobras, falta, f"{semente}|sobras", lambda t: t[0]["achado_id"])
        escolhidos += extra
    return sorted(escolhidos, key=lambda t: t[0]["achado_id"])


def _id_artigo(a):
    return a["artigo_id"]


def status_do_modelo(artigo):
    """'elegivel' | 'quarentena' | 'excluido' (veredito válido do modelo) ou 'sem_veredito'."""
    s = artigo.get("status_escopo")
    return s if s in STATUS_ESCOPO and artigo.get("valido_escopo") in (1, True) else "sem_veredito"


def n_excluidos_checados(artigos):
    """Artigos que o modelo excluiu (veredito válido) e que uma pessoa já decidiu (incluir ou excluir)."""
    return sum(1 for a in artigos if status_do_modelo(a) == "excluido" and a.get("decisao") in ("incluir", "excluir"))


def minimo_h4(meta):
    """Artigos excluídos pelo modelo a conferir, com zero falsas exclusões, para o limite superior de 95% ficar abaixo de `meta`."""
    return amostra_minima_sem_erros(meta)


def selecionar_artigos(candidatos, n_base, n_h4=0, semente=SEMENTE_PADRAO):
    """Escolhe artigos ainda sem decisão. Devolve (base, h4): listas de (artigo, chave_do_estrato, descricao) por artigo_id.

    `base` (n_base linhas) tem COTAS_TRIAGEM por veredito do modelo; dentro de elegível e quarentena, a alocação é proporcional
    ao tamanho de cada nível de relevância (Brasil e tema, `nivel` no candidato). Se um veredito não tem artigos suficientes, a
    cota passa para os outros. Os excluídos pelo modelo são sorteados sem olhar a relevância, numa ordem única: a base pega os
    primeiros e `h4` (n_h4 linhas, só excluídos) os seguintes."""
    grupos = {s: [] for s in STATUS_ESCOPO + ("sem_veredito",)}
    for a in sorted(candidatos, key=_id_artigo):
        grupos[status_do_modelo(a)].append(a)
    ordem_exc = ordem_aleatoria(grupos["excluido"], f"{semente}|excluidos", _id_artigo)
    n_base = max(int(n_base), 0)
    alvo = {s: n_base * pct // 100 for s, pct in COTAS_TRIAGEM}
    alvo["elegivel"] += n_base - sum(alvo.values())                                                # o resto da divisão vai aos elegíveis
    disponivel = {s: len(grupos[s]) for s in STATUS_ESCOPO}
    for s in alvo:                                                                                 # cota maior que o grupo: o excesso migra
        alvo[s] = min(alvo[s], disponivel[s])
    sobra = n_base - sum(alvo.values())
    for s in STATUS_ESCOPO:
        extra = min(sobra, disponivel[s] - alvo[s])
        alvo[s] += extra
        sobra -= extra
    base = []
    for s in ("elegivel", "quarentena"):
        niveis = amostrar_estratificado(grupos[s], alvo[s], lambda a: a.get("nivel") or "baixa", f"{semente}|{s}", _id_artigo)
        base += [(a, f"modelo_{s}_relevancia_{a.get('nivel') or 'baixa'}", f"modelo: {s}; relevância {a.get('nivel') or 'baixa'}") for a in niveis]
    base += [(a, "modelo_excluido_sorteio", "modelo: excluído (sorteio simples, serve à medida de falsa exclusão)")
             for a in ordem_exc[:alvo["excluido"]]]
    falta = n_base - len(base)
    if falta > 0:                                         # ainda falta (poucos artigos com veredito): usa os sem veredito
        extra = sortear(grupos["sem_veredito"], falta, f"{semente}|sem_veredito", _id_artigo)
        base += [(a, "sem_veredito_do_modelo", "sem veredito válido do modelo") for a in extra]
    h4 = [(a, "modelo_excluido_sorteio_h4", "modelo: excluído (sorteio simples para a falsa exclusão, H4)")
          for a in ordem_exc[alvo["excluido"]:alvo["excluido"] + max(int(n_h4), 0)]]
    return sorted(base, key=lambda t: t[0]["artigo_id"]), sorted(h4, key=lambda t: t[0]["artigo_id"])


def nivel_de_relevancia(pontuacao):
    """Nível ('alta', 'media', 'baixa') de uma pontuação de `dominio.relevancia.pontuar_relevancia`; valor inválido vira 'baixa'."""
    nivel = (pontuacao or {}).get("nivel")
    return nivel if nivel in NIVEIS else "baixa"
