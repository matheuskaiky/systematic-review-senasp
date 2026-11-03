"""Metodologia do banco `vies` (busca de viés algorítmico): nove seções próprias (objeto, fontes, estratégia, unidades,
recuperação, deduplicação, classificação, decisões humanas e limitações), geradas a cada carga a partir do banco, e só as
ressalvas sobre as execuções. O texto do estudo das secretarias não aparece no `vies` e não muda nos outros bancos.
Quem não entrou vê a classificação só descrita, sem números do modelo."""
import copy
import hashlib
import importlib
import json
import re
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from apoio_divulgacao import gravar_politica
from dominio import analises_vies as AV, validacao_vies as VV
from painel import glossario, metodologia_texto as MT, visao_geral_vies
from test_analises_vies import _cli
from test_autenticacao import _criar, _entrar
from test_divulgacao_acesso import _painel
from test_metodologia_texto import _fatos as _fatos_reais
from test_painel import demo  # noqa: F401
from test_triagem_vies import construir_vies
from test_triagem_vies_painel import _linha, _triar


def _mv():
    """O módulo novo, importado em cada teste (sem ele, cada teste falha sozinho, não a coleta inteira)."""
    return importlib.import_module("painel.metodologia_vies")


# ---------------------------------------------------------------- fatos de exemplo
R1, R2, R3 = "20261021_213559_3526e4", "20261022_151407_ef2c8f", "20261023_193621_9a7bba"


def _exec(run, comando, dia, config, commit, **kw):
    e = {"run_id": run, "comando": comando, "status": "concluida", "iniciado_em": dia, "finalizado_em": dia,
         "config_hash": config, "commit_git": commit, "no_relatorio": 1, "motivo_exclusao": None}
    e.update(kw)
    return e


def _web(consulta, run, **kw):
    l = {"consulta_id": consulta, "run_id": run, "sucesso": 1, "max_resultados": 20, "idiomas": ["pt"], "pais": "BR",
         "n_retornados": 20}
    l.update(kw)
    return l


def _sch(consulta, run, filtro, pagina, **kw):
    l = {"consulta_id": consulta, "run_id": run, "sucesso": 1, "interface": "pt", "filtro_idioma": filtro, "por_pagina": 20,
         "pagina": pagina, "n_retornados": 20}
    l.update(kw)
    return l


def _fatos():
    """Os números da cópia do `vies` de 23/10/2026, com três execuções e três consultas (uma por conjunto)."""
    return {
        "banco": "vies",
        "execucoes": [_exec(R1, "buscar-literatura", "2026-10-21T21:35:59+00:00", "2687652782e3aaaa", "0228e5b"),
                      _exec(R2, "academico", "2026-10-22T15:14:07+00:00", "2687652782e3aaaa", "0228e5b+sujo:0d8f25ff"),
                      _exec(R3, "triar-escopo", "2026-10-23T19:36:21+00:00", "9e046089b981bbbb", "ee63a70")],
        "retomadas": [],
        "triagem_humana": {"total": 473, "incluidos": 0, "excluidos": 0, "pendentes": 473, "ocultos_llm": 48},
        "consultas": [{"id": "LA1", "conjunto": "A", "texto": "inteligência artificial segurança pública viés algorítmico"},
                      {"id": "LB1", "conjunto": "B", "texto": "viés algorítmico discriminação segurança pública"},
                      {"id": "LC1", "conjunto": "C", "texto": "inteligência artificial policiamento"}],
        "chamadas": {"web": [_web("LA1", R1), _web("LA1", "RX"), _web("LB1", "RX"), _web("LC1", "RY")],
                     "scholar": [_sch("LA1", R2, "so_portugues", 1), _sch("LA1", R2, "so_portugues", 2),
                                 _sch("LA1", R2, "so_portugues", 3), _sch("LA1", R2, "sem_filtro", 1),
                                 _sch("LB1", R2, "so_portugues", 1), _sch("LB1", R2, "sem_filtro", 1),
                                 _sch("LC1", R2, "so_portugues", 1), _sch("LC1", R2, "sem_filtro", 1),
                                 _sch("LC1", R2, "sem_filtro", 2)]},
        "ocorrencias": {"web": 400, "scholar": 1288},
        "corpus": {"n_itens": 720, "n_web": 199, "n_scholar": 521, "n_obras": 696, "n_em_ambas_fontes": 24,
                   "n_ambas_por_url": 14, "n_ambas_so_por_titulo": 10, "n_triados": 720, "n_alta": 542, "n_fora": 48},
        "relevancia": {"Web": {"alta": 173, "media": 26, "baixa": 0, "fora_do_escopo": 0, "sem triagem válida": 0},
                       "Scholar": {"alta": 369, "media": 99, "baixa": 5, "fora_do_escopo": 48, "sem triagem válida": 0}},
        "versao_triagem": "v2",
        "validacao": {"itens": 0, "respondidos": 0},
        "triagem_por_execucao": [{"run_id": R3, "versao": "v2", "provedor": "gemini:gemini-3.5-flash-lite"}],
    }


def _mudar(fatos, **mudancas):
    """Cópia dos fatos com chaves trocadas; 'a__b' troca fatos['a']['b']."""
    f = copy.deepcopy(fatos)
    for chave, valor in mudancas.items():
        alvo, *resto = chave.split("__")
        if resto:
            f[alvo] = dict(f.get(alvo) or {})
            f[alvo][resto[0]] = valor
        else:
            f[alvo] = valor
    return f


def _gerar(fatos, custos=True, modelo=True):
    return _mv().gerar_metodologia_vies(fatos, custos=custos, modelo=modelo)


def _textos(m):
    """[(id, titulo, [texto do parágrafo | [textos dos itens]])] de cada seção."""
    return [(s["id"], s["titulo"], [MT.para_texto(b["seg"]) if b["tipo"] == "p" else [MT.para_texto(i) for i in b["itens"]]
                                    for b in s["blocos"]]) for s in m["secoes"]]


def _secao(m, id_):
    return next(b for i, _, b in _textos(m) if i == id_)


# ---------------------------------------------------------------- textos esperados
OBJETO = ("Levantamento da literatura científica e cinzenta sobre inteligência artificial na segurança pública, com dois ângulos: "
          "o viés algorítmico (discriminação, ética, direitos e governança) e as aplicações tecnológicas. A página descreve o que as "
          "buscas recuperaram e como os itens foram organizados e classificados. Não é uma revisão sistemática concluída.")
FONTES_INTRO = ["Duas fontes, contadas separadamente:",
                ["o Google Scholar, consultado por meio do serviço SerpApi;", "a busca na web, feita pelo serviço Perplexity."]]
CADA_EXECUCAO = " Cada execução aparece com o seu identificador, o comando, a situação, o hash da configuração e o commit do código."
ITENS_EXECUCOES = [f"{R1}: buscar-literatura (concluida, hash da configuração 2687652782e3, commit 0228e5b)",
                   f"{R2}: academico (concluida, hash da configuração 2687652782e3, commit 0228e5b+sujo:0d8f25ff)",
                   f"{R3}: triar-escopo (concluida, hash da configuração 9e046089b981, commit ee63a70)"]
ESTRATEGIA_INTRO = [
    "Foram usadas quinze consultas, escritas em português, em três conjuntos de cinco:",
    ["o conjunto A combina termos de inteligência artificial, segurança pública, viés algorítmico e investigação criminal;",
     "o B, de inteligência artificial, segurança pública, viés algorítmico, discriminação e ética;",
     "o C trata das aplicações da inteligência artificial na segurança pública."]]
MESMAS = "As mesmas consultas foram usadas nas duas fontes."
DIFERENTES = "As consultas usadas não foram as mesmas nas duas fontes; cada chamada registra a sua."
CONSULTAS = ["LA1 (conjunto A): inteligência artificial segurança pública viés algorítmico",
             "LB1 (conjunto B): viés algorítmico discriminação segurança pública",
             "LC1 (conjunto C): inteligência artificial policiamento"]
WEB_PADRAO = ("Busca na web: cada consulta foi enviada numa chamada própria, pedindo até 20 resultados, com os parâmetros de "
              "idioma português e de país Brasil.")
WEB_OUTROS = ("Busca na web: cada consulta foi enviada numa chamada própria; os parâmetros não foram os mesmos em todas as "
              "chamadas e estão registrados em cada uma.")
WEB_NADA = "Busca na web: nenhuma chamada consta nas execuções do relatório."
CONJUNTOS = " O conjunto A foi consultado em 2 execuções; o B, em 1; o C, em 1."
SCHOLAR_PADRAO = ("Google Scholar: cada consulta foi feita duas vezes, com a interface em português: uma vez com o parâmetro de "
                  "idioma português e outra sem parâmetro de idioma. Cada vez pediu 20 resultados por página, em até 3 páginas; a "
                  "paginação parava na primeira página com menos de 20 resultados ou com falha na chamada.")
SCHOLAR_OUTROS = ("Google Scholar: as chamadas não usaram os mesmos parâmetros em todas as consultas; eles estão registrados em "
                  "cada chamada.")
SCHOLAR_NADA = "Google Scholar: nenhuma chamada consta nas execuções do relatório."
REPETE_A = " O conjunto A foi consultado em 2 execuções na web; 20 dessas ocorrências vêm da segunda execução."
RECUPERACAO = ("Na busca na web, 400 ocorrências devolvidas em 4 chamadas resultaram em 199 referências únicas (por endereço "
               "normalizado)." + REPETE_A + " No Google Scholar, 1.288 ocorrências devolvidas em 9 chamadas resultaram em 521 artigos únicos (por "
               "título normalizado). Ao todo, são 720 itens, porque cada artigo e cada referência conta como um item: 521 artigos e 199 referências.")
DEDUP_1 = ("Dentro de cada fonte, as ocorrências repetidas foram juntadas automaticamente: na web, pelo endereço normalizado; no "
           "Scholar, pelo título normalizado.")
DEDUP_ENTRE = ("Entre as fontes, uma referência da web e um artigo do Scholar contam como a mesma obra quando têm o mesmo endereço "
               "normalizado ou o mesmo título normalizado. ")
DEDUP_FIM = ["A junção é um procedimento operacional automático, não uma identificação bibliográfica conferida por pessoas:",
             ["títulos escritos de forma diferente não são reconhecidos como a mesma obra;",
              "artigos do Scholar diferentes com o mesmo endereço continuam separados;",
              "possíveis duplicatas que restam ainda não foram examinadas."]]
CLASSIFICA_MEIO = [["relevância (alta, média, baixa ou fora do escopo), com uma confiança (alta, média ou baixa) e uma justificativa;", "ângulo, tipo de fonte, país ou escopo, tópicos e eixo."],
                   "Ele é instruído a julgar só pelo que o item mostra.", "Resultado da triagem:"]
NAO_DECISAO = "São classificações automatizadas, não decisões de pesquisadores."
OCULTOS_48 = ("Os 48 artigos que o modelo pôs fora do escopo com confiança alta ficam ocultos das listas de artigos até uma "
              "decisão humana. Nada é apagado. " + NAO_DECISAO)
VISITANTE = ("Os itens são classificados por um modelo de linguagem, registrado nas chamadas como gemini-3.5-flash-lite, com as "
             "instruções da versão v2, quanto à relevância, ao ângulo, ao tipo de fonte, "
             "ao país ou escopo, aos tópicos e ao eixo. Os artigos que o modelo põe fora do escopo com confiança alta ficam ocultos "
             "das listas até uma decisão humana. Os resultados automatizados ainda não são divulgados.")
DECISOES_INICIO = ("Até a data desta página, 0 artigos do Scholar têm decisão de triagem registrada por uma pessoa (0 incluídos e "
                   "0 excluídos). As referências da web não passam por triagem humana no procedimento atualmente documentado. ")
NAO_SORTEADA = "A amostra de validação humana da triagem ainda não foi sorteada."
LIM_BASE = ("Cada consulta trouxe só os primeiros resultados de cada fonte: na web, até {n} por chamada; no Google Scholar, até {m} "
            "de {p} em cada variante de filtro, e a paginação parava na primeira página com menos de {p} resultados ou com falha na "
            "chamada.")
PEDIDA_DIFERE = " A profundidade pedida difere entre as fontes."
VARIOU_WEB = " Na web, a profundidade efetiva variou entre as consultas."
VARIOU_SCHOLAR = " No Google Scholar, a profundidade efetiva variou entre as consultas."
VARIOU_DUAS = " A profundidade efetiva variou entre as consultas nas duas fontes."
VARIOU = VARIOU_WEB
VARIOU_E_DIFERE = VARIOU_SCHOLAR + PEDIDA_DIFERE
LIM_PROFUNDIDADE = LIM_BASE.format(n=20, m="3 páginas", p=20) + PEDIDA_DIFERE
LIM_PROFUNDIDADE_OUTROS = ("Cada consulta trouxe só os primeiros resultados de cada fonte; a profundidade pedida está registrada "
                           "em cada chamada.")
LIM_IDIOMA = ("As consultas foram escritas em português. Na web, com os parâmetros de idioma português e de país Brasil; no "
              "Scholar, com e sem o parâmetro de idioma português. Isso descreve os parâmetros enviados ao provedor, não o idioma dos "
              "itens recuperados, que não foi medido.")
LIM_IDIOMA_OUTROS = ("As consultas foram escritas em português. Os parâmetros de idioma e de país estão registrados em cada "
                     "chamada. Isso descreve os parâmetros enviados ao provedor, não o idioma dos itens recuperados, que não foi medido.")
LIM_NAO_CONFERIDA = "A classificação do modelo ainda não foi conferida por pessoas."
LIM_FIM = ["A deduplicação é automática e pode deixar duplicatas.",
           "Buscas manuais em bases bibliográficas não fazem parte deste levantamento."]
RESSALVA_SUJO = (f"Execuções feitas com código ainda não commitado (commit com “+sujo”): {R2}. O commit registrado não reproduz "
                 "exatamente o código que rodou.")
RESSALVA_CONFIGS = ("As execuções do relatório usaram 2 configurações diferentes; confira as diferenças antes de descrever o método "
                    "como único.")
SUBTITULO = ("Esta página descreve os procedimentos de busca, organização e classificação registrados na pesquisa, com suas "
             "fontes e limitações. Informações não disponíveis são identificadas ao longo do texto.")
MODELO_V2 = "Os itens são classificados por um modelo de linguagem, registrado nas chamadas como gemini-3.5-flash-lite, com as instruções da versão v2. O modelo atribui:"
VAZIO = "Nada foi coletado ainda: não há execuções nem itens da busca no banco, então não há método a descrever."
TITULOS = [("objeto", "Objeto e finalidade"), ("fontes", "Fontes"), ("estrategia", "Estratégia de busca"),
           ("unidades", "Unidades de análise"), ("recuperacao", "Recuperação e organização"),
           ("deduplicacao", "Deduplicação e limites"), ("classificacao", "Classificação automatizada"),
           ("decisoes", "Decisões humanas registradas"), ("limitacoes", "Limitações")]


def _unidades():
    s = next(s for s in glossario.SECOES_VIES if s["id"] == "unidades")
    return [s["intro"], [f"{e['termo']}: {e['texto']}" for e in s["entradas"]]]


def _esperado(modelo=True):
    classificacao = ([MODELO_V2,
                      *CLASSIFICA_MEIO,
                      ["artigos do Scholar: 369 de relevância alta, 99 média, 5 baixa e 48 fora do escopo;",
                       "referências da web: 173 alta, 26 média, 0 baixa e 0 fora do escopo;", "0 itens sem triagem válida."],
                      OCULTOS_48] if modelo else [VISITANTE])
    blocos = {
        "objeto": [OBJETO],
        "fontes": FONTES_INTRO + ["O levantamento usou 3 execuções, entre 21/10/2026 e 23/10/2026: 2 de busca (1 na web e 1 no "
                                  "Google Scholar) e 1 de triagem pelo modelo." + CADA_EXECUCAO, ITENS_EXECUCOES],
        "estrategia": ESTRATEGIA_INTRO + [MESMAS, CONSULTAS, [WEB_PADRAO + CONJUNTOS, SCHOLAR_PADRAO]],
        "unidades": _unidades(),
        "recuperacao": [RECUPERACAO],
        "deduplicacao": [DEDUP_1, DEDUP_ENTRE + "Assim, 24 referências da web repetem um artigo do Scholar (14 pelo endereço e 10 só "
                         "pelo título), e o total é de 696 obras distintas.", *DEDUP_FIM],
        "classificacao": classificacao,
        "decisoes": [DECISOES_INICIO + NAO_SORTEADA],
        "limitacoes": [[LIM_PROFUNDIDADE, LIM_IDIOMA, LIM_NAO_CONFERIDA, *LIM_FIM]],
    }
    return [(i, t, blocos[i]) for i, t in TITULOS]


# ---------------------------------------------------------------- estrutura completa
@pytest.mark.parametrize("modelo", [True, False])
@pytest.mark.parametrize("custos", [True, False])
def test_nove_secoes_com_os_textos_exatos(custos, modelo):
    m = _gerar(_fatos(), custos=custos, modelo=modelo)
    assert _textos(m) == _esperado(modelo)
    assert [[MT.para_texto(r)] for r in m["ressalvas"]] == [[RESSALVA_SUJO], [RESSALVA_CONFIGS]]
    assert m["vazio"] is False
    assert m["texto"] == MT._texto_puro(m["secoes"], m["ressalvas"])
    assert set(m) == {"secoes", "ressalvas", "vazio", "texto", "subtitulo"}
    assert m.get("subtitulo") == SUBTITULO


def test_so_os_identificadores_das_execucoes_tem_link():
    m = _gerar(_fatos())
    links = [(t, h) for s in m["secoes"] for b in s["blocos"]
             for seg in ([b["seg"]] if b["tipo"] == "p" else b["itens"]) for t, h in seg if h]
    assert links == [(R1, f"/execucoes/{R1}"), (R2, f"/execucoes/{R2}"), (R3, f"/execucoes/{R3}")]
    assert [h for r in m["ressalvas"] for _, h in r if h] == [f"/execucoes/{R2}"]


# texto do outro estudo e palavras que nao cabem no vies: nada disso aparece na pagina do vies
PROIBIDOS = ["secretaria", "Secretaria", "UFs", "UF ", "achado", "Achado", "PRISMA", "pipeline", "Custos", "US$",
             "Nenhuma consulta web", "bases manuais", "IEEE", "Verificação humana", "Classificação automática",
             "Levantamento nas secretarias", "Resultados confirmados", "predominantemente", "revisão sistemática foi concluída",
             "Estes dados são do banco da busca de viés"]


# os textos das secoes e ressalvas do estudo das secretarias (as execucoes da demonstracao trazem comandos como pipeline-uf)
DO_OUTRO_ESTUDO = ["Levantamento nas secretarias", "Classificação automática", "Verificação humana", "Resultados confirmados",
                   "Nenhuma consulta web", "bases manuais", "Nenhuma busca manual", "Estes dados são do banco da busca de viés",
                   "Custos", "UFs"]


@pytest.mark.parametrize("trecho", PROIBIDOS)
@pytest.mark.parametrize("modelo", [True, False])
def test_sem_textos_do_estudo_das_secretarias(trecho, modelo):
    retomada = _mudar(_fatos(), retomadas=[{"run_id": R1, "n": 1}])
    retomada["execucoes"].append(_exec("RFORA", "academico", "2026-10-24T10:00:00+00:00", "c", "d", no_relatorio=0))
    for custos in (True, False):
        assert trecho not in _gerar(retomada, custos=custos, modelo=modelo)["texto"]


# ---------------------------------------------------------------- tabela: uma linha por caso
# (descricao, mudancas nos fatos, id da secao, blocos esperados da secao)
FONTES_CASOS = [
    ("uma execucao, um dia", dict(execucoes=[_exec(R1, "buscar-literatura", "2026-10-21T21:35:59+00:00", "h", "c")]), "fontes",
     FONTES_INTRO + ["O levantamento usou 1 execução, em 21/10/2026: 1 de busca na web." + CADA_EXECUCAO,
                     [f"{R1}: buscar-literatura (concluida, hash da configuração h, commit c)"]]),
    ("nenhuma no relatorio", dict(execucoes=[_exec(R1, "academico", "2026-10-21T10:00:00", "h", "c", no_relatorio=0)]), "fontes",
     FONTES_INTRO + ["Nenhuma execução está incluída no relatório."]),
    ("data da primeira ilegivel", dict(execucoes=[_exec(R1, "academico", None, "h", "c"),
                                                  _exec(R2, "academico", "2026-10-22T10:00:00", "h", "c")]), "fontes",
     FONTES_INTRO + ["O levantamento usou 2 execuções: 2 de busca no Google Scholar." + CADA_EXECUCAO,
                     [f"{R1}: academico (concluida, hash da configuração h, commit c)",
                      f"{R2}: academico (concluida, hash da configuração h, commit c)"]]),
    ("so a primeira e a ultima do relatorio dao o periodo",
     dict(execucoes=[_exec(R1, "a", "2026-10-21T10:00:00", "h", "c"), _exec("RF", "a", "2026-10-01T10:00:00", "h", "c", no_relatorio=0),
                     _exec(R2, "a", "2026-10-25T10:00:00", "h", "c")]), "fontes",
     FONTES_INTRO + ["O levantamento usou 2 execuções, entre 21/10/2026 e 25/10/2026: 2 de outros comandos." + CADA_EXECUCAO,
                     [f"{R1}: a (concluida, hash da configuração h, commit c)", f"{R2}: a (concluida, hash da configuração h, commit c)"]]),
]

# composicao das execucoes do relatorio por comando, e as triagens feitas com outra versao das instrucoes
D1, D2, D3 = "2026-10-21T10:00:00", "2026-10-22T10:00:00", "2026-10-23T10:00:00"
T1, T2, T3 = "T1", "T2", "T3"


def _tri(run, versao, provedor="gemini:gemini-3.5-flash-lite"):
    return {"run_id": run, "versao": versao, "provedor": provedor}


def _fontes_frase(execucoes, triagens=None, versao="v2"):
    f = _mudar(_fatos(), execucoes=execucoes, triagem_por_execucao=triagens, versao_triagem=versao)
    return _secao(_gerar(f), "fontes")[2]


FIM = CADA_EXECUCAO
COMPOSICAO_CASOS = [
    ("tres grupos e outro comando", [_exec("W", "buscar-literatura", D1, "h", "c"), _exec("S", "academico", D2, "h", "c"),
                                     _exec(T1, "triar-escopo", D3, "h", "c"), _exec("X", "exportar", D3, "h", "c")], None, "v2",
     "O levantamento usou 4 execuções, entre 21/10/2026 e 23/10/2026: 2 de busca (1 na web e 1 no Google Scholar), 1 de triagem "
     "pelo modelo e 1 de outro comando." + FIM),
    ("so triagem", [_exec(T1, "triar-escopo", D1, "h", "c"), _exec(T2, "triar-escopo", D1, "h", "c")],
     [_tri(T1, "v2"), _tri(T2, "v2")], "v2",
     "O levantamento usou 2 execuções, em 21/10/2026: 2 de triagem pelo modelo." + FIM),
    ("busca e outros comandos", [_exec("W", "buscar-literatura", D1, "h", "c"), _exec("X", "a", D1, "h", "c"),
                                 _exec("Y", "b", D1, "h", "c")], None, "v2",
     "O levantamento usou 3 execuções, em 21/10/2026: 1 de busca na web e 2 de outros comandos." + FIM),
    ("execucao fora do relatorio nao entra", [_exec("W", "buscar-literatura", D1, "h", "c"),
                                              _exec(T1, "triar-escopo", D1, "h", "c", no_relatorio=0)],
     [_tri(T1, "v1")], "v2",
     "O levantamento usou 1 execução, em 21/10/2026: 1 de busca na web." + FIM),
    ("uma triagem com a versao anterior", [_exec(T1, "triar-escopo", D1, "h", "c"), _exec(T2, "triar-escopo", D2, "h", "c")],
     [_tri(T1, "v1"), _tri(T2, "v2")], "v2",
     "O levantamento usou 2 execuções, entre 21/10/2026 e 22/10/2026: 2 de triagem pelo modelo. 1 das triagens usou a versão v1 "
     "das instruções, substituída pela v2; a contagem por relevância da seção Classificação automatizada usa só a v2." + FIM),
    ("duas triagens com a versao anterior", [_exec(T1, "triar-escopo", D1, "h", "c"), _exec(T2, "triar-escopo", D1, "h", "c"),
                                             _exec(T3, "triar-escopo", D2, "h", "c")],
     [_tri(T1, "v1"), _tri(T2, "v1"), _tri(T3, "v2")], "v2",
     "O levantamento usou 3 execuções, entre 21/10/2026 e 22/10/2026: 3 de triagem pelo modelo. 2 das triagens usaram a versão v1 "
     "das instruções, substituída pela v2; a contagem por relevância da seção Classificação automatizada usa só a v2." + FIM),
    ("duas versoes anteriores em ordem", [_exec(T1, "triar-escopo", D1, "h", "c"), _exec(T2, "triar-escopo", D1, "h", "c")],
     [_tri(T1, "v1"), _tri(T2, "v0")], "v2",
     "O levantamento usou 2 execuções, em 21/10/2026: 2 de triagem pelo modelo. 2 das triagens usaram as versões v0 e v1 das "
     "instruções, substituídas pela v2; a contagem por relevância da seção Classificação automatizada usa só a v2." + FIM),
    ("execucao com as duas versoes conta", [_exec(T1, "triar-escopo", D1, "h", "c")], [_tri(T1, "v1"), _tri(T1, "v2")], "v2",
     "O levantamento usou 1 execução, em 21/10/2026: 1 de triagem pelo modelo. 1 das triagens usou a versão v1 das instruções, "
     "substituída pela v2; a contagem por relevância da seção Classificação automatizada usa só a v2." + FIM),
    ("versao nao registrada", [_exec(T1, "triar-escopo", D1, "h", "c")], [_tri(T1, None)], "v2",
     "O levantamento usou 1 execução, em 21/10/2026: 1 de triagem pelo modelo. 1 das triagens usou instruções sem versão "
     "registrada; a contagem por relevância da seção Classificação automatizada usa só a v2." + FIM),
    ("versao nao registrada e versao anterior", [_exec(T1, "triar-escopo", D1, "h", "c"), _exec(T2, "triar-escopo", D1, "h", "c")],
     [_tri(T1, None), _tri(T2, "v1")], "v2",
     "O levantamento usou 2 execuções, em 21/10/2026: 2 de triagem pelo modelo. 2 das triagens usaram a versão v1 das instruções, "
     "substituída pela v2; a contagem por relevância da seção Classificação automatizada usa só a v2." + FIM),
    ("sem versao vigente nao ha frase", [_exec(T1, "triar-escopo", D1, "h", "c")], [_tri(T1, "v1")], None,
     "O levantamento usou 1 execução, em 21/10/2026: 1 de triagem pelo modelo." + FIM),
    ("versao vigente vazia nao ha frase", [_exec(T1, "triar-escopo", D1, "h", "c")], [_tri(T1, "v1")], "",
     "O levantamento usou 1 execução, em 21/10/2026: 1 de triagem pelo modelo." + FIM),
    ("versao de execucao que nao e triagem nao conta", [_exec("W", "buscar-literatura", D1, "h", "c"),
                                                        _exec(T1, "triar-escopo", D1, "h", "c")],
     [_tri("W", "v1"), _tri(T1, "v2")], "v2",
     "O levantamento usou 2 execuções, em 21/10/2026: 1 de busca na web e 1 de triagem pelo modelo." + FIM),
    ("triagem sem linhas nao conta", [_exec(T1, "triar-escopo", D1, "h", "c")], [], "v2",
     "O levantamento usou 1 execução, em 21/10/2026: 1 de triagem pelo modelo." + FIM),
    ("linhas de triagem nulas", [_exec(T1, "triar-escopo", D1, "h", "c")], None, "v2",
     "O levantamento usou 1 execução, em 21/10/2026: 1 de triagem pelo modelo." + FIM),
    ("milhar", [_exec(f"W{i}", "buscar-literatura", D1, "h", "c") for i in range(1000)]
     + [_exec(f"S{i}", "academico", D1, "h", "c") for i in range(2)], None, "v2",
     "O levantamento usou 1.002 execuções, em 21/10/2026: 1.002 de busca (1.000 na web e 2 no Google Scholar)." + FIM),
]


@pytest.mark.parametrize("descricao, execucoes, triagens, versao, esperado", COMPOSICAO_CASOS, ids=[c[0] for c in COMPOSICAO_CASOS])
def test_composicao_das_execucoes(descricao, execucoes, triagens, versao, esperado):
    assert _fontes_frase(execucoes, triagens, versao) == esperado


CONTAGEM_V2 = "; a contagem por relevância da seção Classificação automatizada usa só a v2."


@pytest.mark.parametrize("descricao, execucoes, triagens, versao, esperado", COMPOSICAO_CASOS, ids=[c[0] for c in COMPOSICAO_CASOS])
def test_composicao_para_o_visitante_nao_cita_a_contagem_que_ele_nao_ve(descricao, execucoes, triagens, versao, esperado):
    """A seção 7 do visitante não tem a contagem por relevância: a frase das versões termina na substituição."""
    f = _mudar(_fatos(), execucoes=execucoes, triagem_por_execucao=triagens, versao_triagem=versao)
    assert _secao(_gerar(f, modelo=False), "fontes")[2] == esperado.replace(CONTAGEM_V2, ".")


WEB_ROWS = _fatos()["chamadas"]["web"]
SCH_ROWS = _fatos()["chamadas"]["scholar"]


def _ch(web=None, scholar=None):
    return {"web": WEB_ROWS if web is None else web, "scholar": SCH_ROWS if scholar is None else scholar}


def _est(web, scholar=SCHOLAR_PADRAO, consultas=CONSULTAS, mesmas=MESMAS):
    return ESTRATEGIA_INTRO + ([mesmas] if mesmas else []) + ([consultas] if consultas else []) + [[web, scholar]]


ESTRATEGIA_CASOS = [
    ("web vazia", dict(chamadas=_ch(web=[])), _est(WEB_NADA, mesmas=None)),
    ("web chamadas null", dict(chamadas={"web": None, "scholar": SCH_ROWS}), _est(WEB_NADA, mesmas=None)),
    ("web com outro maximo", dict(chamadas=_ch(web=WEB_ROWS[:3] + [_web("LC1", "RY", max_resultados=10)])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web maximo booleano", dict(chamadas=_ch(web=[_web("LA1", R1, max_resultados=True)] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web maximo zero", dict(chamadas=_ch(web=[_web("LA1", R1, max_resultados=0)] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web maximo texto", dict(chamadas=_ch(web=[_web("LA1", R1, max_resultados="20")] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web maximo nulo", dict(chamadas=_ch(web=[_web("LA1", R1, max_resultados=None)] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web dois idiomas", dict(chamadas=_ch(web=[_web("LA1", R1, idiomas=["pt", "en"])] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web idioma texto", dict(chamadas=_ch(web=[_web("LA1", R1, idiomas="pt")] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web idioma nulo", dict(chamadas=_ch(web=[_web("LA1", R1, idiomas=None)] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web idioma ingles", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], idiomas=["en"]) for c in WEB_ROWS])),
     _est(WEB_OUTROS + CONJUNTOS)),
    ("web outro pais", dict(chamadas=_ch(web=[_web("LA1", R1, pais="PT")] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web pais nulo", dict(chamadas=_ch(web=[_web("LA1", R1, pais=None)] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web pais minusculo", dict(chamadas=_ch(web=[_web("LA1", R1, pais="br")] + WEB_ROWS[1:])), _est(WEB_OUTROS + CONJUNTOS)),
    ("web maximo mil", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], max_resultados=1000) for c in WEB_ROWS])),
     _est(WEB_PADRAO.replace("até 20", "até 1.000") + CONJUNTOS)),
    ("um conjunto, uma execucao", dict(consultas=_fatos()["consultas"][:1], chamadas=_ch(web=[_web("LA1", R1)])),
     _est(WEB_PADRAO + " O conjunto A foi consultado em 1 execução.", consultas=CONSULTAS[:1], mesmas=DIFERENTES)),
    ("conjuntos sem chamada contam zero", dict(chamadas=_ch(web=WEB_ROWS[:2])),
     _est(WEB_PADRAO + " O conjunto A foi consultado em 2 execuções; o B, em 0; o C, em 0.", mesmas=DIFERENTES)),
    ("primeiro conjunto com zero", dict(chamadas=_ch(web=[_web("LB1", R1)])),
     _est(WEB_PADRAO + " O conjunto A foi consultado em 0 execuções; o B, em 1; o C, em 0.", mesmas=DIFERENTES)),
    ("consulta fora da configuracao", dict(chamadas=_ch(web=WEB_ROWS + [_web("ZZ9", "RZ")])),
     _est(WEB_PADRAO + CONJUNTOS, mesmas=DIFERENTES)),
    ("mesma execucao duas vezes conta uma", dict(chamadas=_ch(web=WEB_ROWS + [_web("LA1", R1)])), _est(WEB_PADRAO + CONJUNTOS)),
    ("chamada com falha conta", dict(chamadas=_ch(web=WEB_ROWS[:3] + [_web("LC1", "RY", sucesso=0)])), _est(WEB_PADRAO + CONJUNTOS)),
    ("sem consultas configuradas", dict(consultas=[]), _est(WEB_PADRAO, consultas=None)),
    ("consultas null", dict(consultas=None), _est(WEB_PADRAO, consultas=None)),
    ("consulta sem texto", dict(consultas=[{"id": "LA1", "conjunto": "A", "texto": None}, *_fatos()["consultas"][1:]]),
     _est(WEB_PADRAO + CONJUNTOS, consultas=["LA1 (conjunto A): texto da consulta não encontrado na configuração", *CONSULTAS[1:]])),
    ("consulta com texto vazio", dict(consultas=[{"id": "LA1", "conjunto": "A", "texto": ""}, *_fatos()["consultas"][1:]]),
     _est(WEB_PADRAO + CONJUNTOS, consultas=["LA1 (conjunto A): texto da consulta não encontrado na configuração", *CONSULTAS[1:]])),
    ("scholar vazio", dict(chamadas=_ch(scholar=[])), _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_NADA, mesmas=None)),
    ("scholar so com filtro numa consulta", dict(chamadas=_ch(scholar=[r for r in SCH_ROWS if not (r["consulta_id"] == "LB1"
                                                                                                and r["filtro_idioma"] == "sem_filtro")])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar filtro outro", dict(chamadas=_ch(scholar=SCH_ROWS + [_sch("LA1", R2, "outro", 1)])), _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar interface ingles", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", 1, interface="en")] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar interface nula", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", 1, interface=None)] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar por pagina diferente", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", 1, por_pagina=10)] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar por pagina booleano", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", 1, por_pagina=True)] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar por pagina texto", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", 1, por_pagina="20")] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar pagina nula", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", None)] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar pagina zero", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "so_portugues", 0)] + SCH_ROWS[1:])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("scholar so primeira pagina", dict(chamadas=_ch(scholar=[r for r in SCH_ROWS if r["pagina"] == 1])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_PADRAO.replace("em até 3 páginas", "em até 1 página"))),
    ("uma consulta so no scholar", dict(chamadas=_ch(scholar=SCH_ROWS + [_sch("LB2", R2, "so_portugues", 1),
                                                                         _sch("LB2", R2, "sem_filtro", 1)])),
     _est(WEB_PADRAO + CONJUNTOS, mesmas=DIFERENTES)),
    ("consulta sem identificador numa fonte", dict(chamadas=_ch(web=WEB_ROWS + [_web(None, "RZ")])),
     _est(WEB_PADRAO + CONJUNTOS, mesmas=DIFERENTES)),
    ("scholar com falha conta", dict(chamadas=_ch(scholar=SCH_ROWS + [_sch("LA1", R2, "sem_filtro", 2, sucesso=0)])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_PADRAO)),
    ("scholar pagina repetida em outra execucao", dict(chamadas=_ch(scholar=SCH_ROWS + [_sch("LA1", "R9", "so_portugues", 1)])),
     _est(WEB_PADRAO + CONJUNTOS, SCHOLAR_OUTROS)),
    ("conjuntos na ordem da configuracao, nao em ordem alfabetica",
     dict(consultas=[_fatos()["consultas"][2], _fatos()["consultas"][0], _fatos()["consultas"][1]]),
     _est(WEB_PADRAO + " O conjunto C foi consultado em 1 execução; o A, em 2; o B, em 1.",
          consultas=[CONSULTAS[2], CONSULTAS[0], CONSULTAS[1]])),
]

RECUPERACAO_CASOS = [
    ("singular", dict(chamadas=_ch(web=[_web("LA1", R1)], scholar=[_sch("LA1", R2, "so_portugues", 1)]),
                      ocorrencias={"web": 1, "scholar": 1}, corpus={"n_itens": 2, "n_web": 1, "n_scholar": 1}),
     ["Na busca na web, 1 ocorrência devolvida em 1 chamada resultou em 1 referência única (por endereço normalizado). No Google "
      "Scholar, 1 ocorrência devolvida em 1 chamada resultou em 1 artigo único (por título normalizado). Ao todo, são 2 itens, porque cada artigo e cada referência conta como um item: "
      "1 artigo e 1 referência."]),
    ("um item", dict(corpus={"n_itens": 1, "n_web": 0, "n_scholar": 1}),
     ["Na busca na web, 400 ocorrências devolvidas em 4 chamadas resultaram em 0 referências únicas (por endereço normalizado)." + REPETE_A + " "
      "No Google Scholar, 1.288 ocorrências devolvidas em 9 chamadas resultaram em 1 artigo único (por título normalizado). "
      "Ao todo, é 1 item, porque cada artigo e cada referência conta como um item: 1 artigo e 0 referências."]),
    ("sem chamadas web", dict(chamadas=_ch(web=[])),
     ["Na busca na web, nenhuma chamada consta nas execuções do relatório. No Google Scholar, 1.288 ocorrências devolvidas em 9 "
      "chamadas resultaram em 521 artigos únicos (por título normalizado). Ao todo, são 720 itens, porque cada artigo e cada referência conta como um item: 521 artigos e 199 referências."]),
    ("sem chamadas scholar", dict(chamadas=_ch(scholar=[])),
     ["Na busca na web, 400 ocorrências devolvidas em 4 chamadas resultaram em 199 referências únicas (por endereço normalizado)." + REPETE_A + " "
      "No Google Scholar, nenhuma chamada consta nas execuções do relatório. Ao todo, são 720 itens, porque cada artigo e cada referência conta como um item: 521 artigos e 199 referências."]),
    ("zero ocorrencias", dict(ocorrencias={"web": 0, "scholar": None}, corpus={"n_itens": 0}),
     ["Na busca na web, 0 ocorrências devolvidas em 4 chamadas resultaram em 0 referências únicas (por endereço normalizado)." + REPETE_A + " No "
      "Google Scholar, 0 ocorrências devolvidas em 9 chamadas resultaram em 0 artigos únicos (por título normalizado). Ao todo, "
      "são 0 itens, porque cada artigo e cada referência conta como um item: 0 artigos e 0 referências."]),
    ("ocorrencias ausentes", dict(ocorrencias=None),
     ["Na busca na web, 0 ocorrências devolvidas em 4 chamadas resultaram em 199 referências únicas (por endereço normalizado)." + REPETE_A + " "
      "No Google Scholar, 0 ocorrências devolvidas em 9 chamadas resultaram em 521 artigos únicos (por título normalizado). "
      "Ao todo, são 720 itens, porque cada artigo e cada referência conta como um item: 521 artigos e 199 referências."]),
]

# a frase da repeticao de um conjunto na web: so a parte da web, entre a frase da web e a do Scholar
WEB_FRASE = ("Na busca na web, 400 ocorrências devolvidas em {n} chamadas resultaram em 199 referências únicas (por endereço "
             "normalizado).")


def _web_parte(web, consultas=None):
    f = _mudar(_fatos(), chamadas=_ch(web=web), **({} if consultas is None else {"consultas": consultas}))
    texto = _secao(_gerar(f), "recuperacao")[0]
    return texto[:texto.index(" No Google Scholar")]


REPETICAO_CASOS = [
    ("sem repeticao", [_web("LA1", R1), _web("LB1", R1), _web("LC1", R1)], WEB_FRASE.format(n=3)),
    ("tres execucoes", [_web("LA1", R1), _web("LA1", "RX", n_retornados=7), _web("LA1", "RY", n_retornados=3)],
     WEB_FRASE.format(n=3) + " O conjunto A foi consultado em 3 execuções na web; 10 dessas ocorrências vêm das execuções depois "
                             "da primeira."),
    ("uma ocorrencia", [_web("LA1", R1), _web("LA1", "RX", n_retornados=1)],
     WEB_FRASE.format(n=2) + " O conjunto A foi consultado em 2 execuções na web; 1 dessas ocorrências vem da segunda execução."),
    ("zero ocorrencias", [_web("LA1", R1), _web("LA1", "RX", n_retornados=0)],
     WEB_FRASE.format(n=2) + " O conjunto A foi consultado em 2 execuções na web; 0 dessas ocorrências vêm da segunda execução."),
    ("primeira execucao e a menor em ordem, nao a primeira da lista", [_web("LA1", "RX", n_retornados=5), _web("LA1", R1, n_retornados=9)],
     WEB_FRASE.format(n=2) + " O conjunto A foi consultado em 2 execuções na web; 5 dessas ocorrências vêm da segunda execução."),
    ("duas consultas do conjunto na segunda execucao", [_web("LA1", R1), _web("LA1", "RX", n_retornados=4), _web("LA2", "RX", n_retornados=6)],
     WEB_FRASE.format(n=3) + " O conjunto A foi consultado em 2 execuções na web; 10 dessas ocorrências vêm da segunda execução.",
     [{"id": "LA1", "conjunto": "A", "texto": "a"}, {"id": "LA2", "conjunto": "A", "texto": "b"}]),
    ("dois conjuntos repetidos na ordem da configuracao", [_web("LA1", R1), _web("LA1", "RX", n_retornados=2), _web("LC1", R1),
                                                          _web("LC1", "RX", n_retornados=3)],
     WEB_FRASE.format(n=4) + " O conjunto C foi consultado em 2 execuções na web; 3 dessas ocorrências vêm da segunda execução."
     " O conjunto A foi consultado em 2 execuções na web; 2 dessas ocorrências vêm da segunda execução.",
     [_fatos()["consultas"][2], _fatos()["consultas"][0], _fatos()["consultas"][1]]),
    ("retornados invalido conta zero", [_web("LA1", R1), _web("LA1", "RX", n_retornados=None), _web("LA1", "RY", n_retornados="4"),
                                       _web("LA1", "RZ", n_retornados=True), _web("LA1", "RW", n_retornados=-2),
                                       _web("LA1", "RV", n_retornados=2.0)],
     WEB_FRASE.format(n=6) + " O conjunto A foi consultado em 6 execuções na web; 0 dessas ocorrências vêm das execuções depois "
                             "da primeira."),
    ("sem identificador de execucao nao conta", [_web("LA1", R1), _web("LA1", None, n_retornados=5), _web("LA1", "", n_retornados=5)],
     WEB_FRASE.format(n=3)),
    ("consulta fora da configuracao nao conta", [_web("LA1", R1), _web("ZZ9", "RX", n_retornados=5)], WEB_FRASE.format(n=2)),
    ("chamada com falha conta", [_web("LA1", R1), _web("LA1", "RX", sucesso=0, n_retornados=0)],
     WEB_FRASE.format(n=2) + " O conjunto A foi consultado em 2 execuções na web; 0 dessas ocorrências vêm da segunda execução."),
    ("milhar", [_web("LA1", R1), _web("LA1", "RX", n_retornados=1500)],
     WEB_FRASE.format(n=2) + " O conjunto A foi consultado em 2 execuções na web; 1.500 dessas ocorrências vêm da segunda execução."),
    ("sem consultas configuradas", [_web("LA1", R1), _web("LA1", "RX")], WEB_FRASE.format(n=2), []),
]


@pytest.mark.parametrize("caso", REPETICAO_CASOS, ids=[c[0] for c in REPETICAO_CASOS])
def test_repeticao_de_um_conjunto_na_web(caso):
    _, web, esperado, *consultas = caso
    assert _web_parte(web, consultas[0] if consultas else None) == esperado


DEDUP_CASOS = [
    ("nenhuma repetida", dict(corpus__n_em_ambas_fontes=0, corpus__n_ambas_por_url=0, corpus__n_ambas_so_por_titulo=0,
                              corpus__n_obras=720),
     DEDUP_ENTRE + "Assim, nenhuma referência da web repete um artigo do Scholar, e o total é de 720 obras distintas."),
    ("uma repetida, uma obra", dict(corpus__n_em_ambas_fontes=1, corpus__n_ambas_por_url=1, corpus__n_ambas_so_por_titulo=0,
                                    corpus__n_obras=1),
     DEDUP_ENTRE + "Assim, 1 referência da web repete um artigo do Scholar (1 pelo endereço e 0 só pelo título), e o total é de 1 "
                   "obra distinta."),
    ("milhar", dict(corpus__n_em_ambas_fontes=1200, corpus__n_ambas_por_url=1000, corpus__n_ambas_so_por_titulo=200,
                    corpus__n_obras=2500),
     DEDUP_ENTRE + "Assim, 1.200 referências da web repetem um artigo do Scholar (1.000 pelo endereço e 200 só pelo título), e o "
                   "total é de 2.500 obras distintas."),
]

CLASSIFICACAO_CASOS = [
    ("nenhum oculto", dict(triagem_humana__ocultos_llm=0), 5,
     "Nenhum artigo está oculto das listas de artigos pela triagem do modelo. " + NAO_DECISAO),
    ("um oculto", dict(triagem_humana__ocultos_llm=1), 5,
     "1 artigo que o modelo pôs fora do escopo com confiança alta fica oculto das listas de artigos até uma decisão humana. "
     "Nada é apagado. " + NAO_DECISAO),
    ("ocultos com milhar", dict(triagem_humana__ocultos_llm=1288), 5,
     "Os 1.288 artigos que o modelo pôs fora do escopo com confiança alta ficam ocultos das listas de artigos até uma decisão "
     "humana. Nada é apagado. " + NAO_DECISAO),
    ("ocultos ausentes", dict(triagem_humana=None), 5,
     "Nenhum artigo está oculto das listas de artigos pela triagem do modelo. " + NAO_DECISAO),
    ("sem versao", dict(versao_triagem=""), 0, "Os itens são classificados por um modelo de linguagem. O modelo atribui:"),
    ("versao nula", dict(versao_triagem=None), 0, "Os itens são classificados por um modelo de linguagem. O modelo atribui:"),
    ("abertura com itens sem triagem", dict(relevancia={"Web": {"sem triagem válida": 2}, "Scholar": {"sem triagem válida": 3}}), 0,
     MODELO_V2),
    ("um sem triagem", dict(relevancia={"Web": {"sem triagem válida": 1}, "Scholar": {"alta": 1288}}), 4,
     ["artigos do Scholar: 1.288 de relevância alta, 0 média, 0 baixa e 0 fora do escopo;",
      "referências da web: 0 alta, 0 média, 0 baixa e 0 fora do escopo;", "1 item sem triagem válida."]),
    ("sem triagem nas duas fontes", dict(relevancia={"Web": {"sem triagem válida": 2}, "Scholar": {"sem triagem válida": 3}}), 4,
     ["artigos do Scholar: 0 de relevância alta, 0 média, 0 baixa e 0 fora do escopo;",
      "referências da web: 0 alta, 0 média, 0 baixa e 0 fora do escopo;", "5 itens sem triagem válida."]),
    ("relevancia ausente", dict(relevancia=None), 4,
     ["artigos do Scholar: 0 de relevância alta, 0 média, 0 baixa e 0 fora do escopo;",
      "referências da web: 0 alta, 0 média, 0 baixa e 0 fora do escopo;", "0 itens sem triagem válida."]),
]

# o modelo registrado nas chamadas da versao vigente das instrucoes
def _abertura(triagens, versao="v2", modelo=True):
    f = _mudar(_fatos(), triagem_por_execucao=triagens, versao_triagem=versao)
    return _secao(_gerar(f, modelo=modelo), "classificacao")[0]


ABRE = "Os itens são classificados por um modelo de linguagem{}. O modelo atribui:"
MODELO_CASOS = [
    ("um modelo", [_tri(T1, "v2")], "v2", ABRE.format(", registrado nas chamadas como gemini-3.5-flash-lite, com as instruções da versão v2")),
    ("modelo so na versao anterior", [_tri(T1, "v1")], "v2", ABRE.format(", com as instruções da versão v2")),
    ("dois modelos em ordem", [_tri(T1, "v2", "gemini:gemini-b"), _tri(T2, "v2", "openai:gpt-a"), _tri(T3, "v1", "x:y")], "v2",
     ABRE.format(", registrado nas chamadas como gemini-b e gpt-a, conforme a execução, com as instruções da versão v2")),
    ("tres modelos", [_tri(T1, "v2", "a:m1"), _tri(T2, "v2", "a:m3"), _tri(T3, "v2", "a:m2")], "v2",
     ABRE.format(", registrado nas chamadas como m1, m2 e m3, conforme a execução, com as instruções da versão v2")),
    ("mesmo nome de dois provedores conta uma vez", [_tri(T1, "v2", "a:m"), _tri(T2, "v2", "b:m")], "v2",
     ABRE.format(", registrado nas chamadas como m, com as instruções da versão v2")),
    ("sem dois pontos vale o texto inteiro", [_tri(T1, "v2", "modelox")], "v2",
     ABRE.format(", registrado nas chamadas como modelox, com as instruções da versão v2")),
    ("nada depois dos dois pontos vale o texto inteiro", [_tri(T1, "v2", "gemini:")], "v2",
     ABRE.format(", registrado nas chamadas como gemini:, com as instruções da versão v2")),
    ("so o primeiro dois pontos separa", [_tri(T1, "v2", "a:b:c")], "v2",
     ABRE.format(", registrado nas chamadas como b:c, com as instruções da versão v2")),
    *[(f"provedor invalido {v!r}", [_tri(T1, "v2", v)], "v2", ABRE.format(", com as instruções da versão v2"))
      for v in (None, "", "   ", 7, True, ["a:b"])],
    ("linhas nulas", None, "v2", ABRE.format(", com as instruções da versão v2")),
    ("sem versao vigente", [_tri(T1, "v2")], None, ABRE.format("")),
    ("versao vigente vazia", [_tri(T1, "v2")], "", ABRE.format("")),
]


@pytest.mark.parametrize("descricao, triagens, versao, esperado", MODELO_CASOS, ids=[c[0] for c in MODELO_CASOS])
def test_modelo_registrado_nas_chamadas(descricao, triagens, versao, esperado):
    assert _abertura(triagens, versao) == esperado


@pytest.mark.parametrize("descricao, triagens, versao, esperado", MODELO_CASOS, ids=[c[0] for c in MODELO_CASOS])
def test_modelo_registrado_nas_chamadas_para_o_visitante(descricao, triagens, versao, esperado):
    meio = esperado[len("Os itens são classificados por um modelo de linguagem"):-len(". O modelo atribui:")]
    if meio.startswith(", registrado"):
        inicio = "Os itens são classificados por um modelo de linguagem" + meio + ", quanto à relevância"
    elif versao:
        inicio = f"Os itens são classificados por um modelo de linguagem (versão {versao}) quanto à relevância"
    else:
        inicio = "Os itens são classificados por um modelo de linguagem quanto à relevância"
    texto = _abertura(triagens, versao, modelo=False)
    assert texto.startswith(inicio + ", ao ângulo, ao tipo de fonte, ao país ou escopo, aos tópicos e ao eixo. Os artigos que o "
                                     "modelo põe fora do escopo com confiança alta ficam ocultos das listas até uma decisão humana. "
                                     "Os resultados automatizados ainda não são divulgados.")
    assert texto.endswith("Os resultados automatizados ainda não são divulgados.")


DECISOES_CASOS = [
    ("um incluido", dict(triagem_humana__incluidos=1),
     "Até a data desta página, 1 artigo do Scholar tem decisão de triagem registrada por uma pessoa (1 incluído e 0 excluídos). "
     "As referências da web não passam por triagem humana no procedimento atualmente documentado. " + NAO_SORTEADA),
    ("um excluido", dict(triagem_humana__excluidos=1),
     "Até a data desta página, 1 artigo do Scholar tem decisão de triagem registrada por uma pessoa (0 incluídos e 1 excluído). "
     "As referências da web não passam por triagem humana no procedimento atualmente documentado. " + NAO_SORTEADA),
    ("varios", dict(triagem_humana__incluidos=1000, triagem_humana__excluidos=2),
     "Até a data desta página, 1.002 artigos do Scholar têm decisão de triagem registrada por uma pessoa (1.000 incluídos e 2 "
     "excluídos). As referências da web não passam por triagem humana no procedimento atualmente documentado. " + NAO_SORTEADA),
    ("amostra sorteada sem resposta", dict(validacao={"itens": 40, "respondidos": 0}),
     DECISOES_INICIO + "A amostra de validação humana da triagem foi sorteada: 0 de 40 itens respondidos."),
    ("amostra em andamento", dict(validacao={"itens": 40, "respondidos": 12}),
     DECISOES_INICIO + "A amostra de validação humana da triagem foi sorteada: 12 de 40 itens respondidos."),
    ("amostra de um item", dict(validacao={"itens": 1, "respondidos": 0}),
     DECISOES_INICIO + "A amostra de validação humana da triagem foi sorteada: 0 de 1 item respondido."),
    ("validacao ausente", dict(validacao=None), DECISOES_INICIO + NAO_SORTEADA),
]

LIMITACOES_CASOS = [
    ("web fora do padrao", dict(chamadas=_ch(web=[_web("LA1", R1, max_resultados=10)] + WEB_ROWS[1:])),
     [LIM_PROFUNDIDADE_OUTROS, LIM_IDIOMA_OUTROS, LIM_NAO_CONFERIDA]),
    ("scholar fora do padrao", dict(chamadas=_ch(scholar=[_sch("LA1", R2, "outro", 1)] + SCH_ROWS[1:])),
     [LIM_PROFUNDIDADE_OUTROS, LIM_IDIOMA_OUTROS, LIM_NAO_CONFERIDA]),
    ("sem scholar", dict(chamadas=_ch(scholar=[])), [LIM_PROFUNDIDADE_OUTROS, LIM_IDIOMA_OUTROS, LIM_NAO_CONFERIDA]),
    ("sem web", dict(chamadas=_ch(web=[])), [LIM_PROFUNDIDADE_OUTROS, LIM_IDIOMA_OUTROS, LIM_NAO_CONFERIDA]),
    ("uma pagina de mil", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], max_resultados=1000, n_retornados=1000) for c in WEB_ROWS],
                                            scholar=[r for r in SCH_ROWS if r["pagina"] == 1])),
     [LIM_BASE.format(n="1.000", m="1 página", p=20) + PEDIDA_DIFERE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("sorteada sem resposta", dict(validacao={"itens": 40, "respondidos": 0}), [LIM_PROFUNDIDADE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("em andamento", dict(validacao={"itens": 40, "respondidos": 12}),
     [LIM_PROFUNDIDADE, LIM_IDIOMA, "A classificação do modelo está sendo conferida numa amostra de 40 itens (12 respondidos)."]),
    ("um respondido", dict(validacao={"itens": 40, "respondidos": 1}),
     [LIM_PROFUNDIDADE, LIM_IDIOMA, "A classificação do modelo está sendo conferida numa amostra de 40 itens (1 respondido)."]),
    ("completa", dict(validacao={"itens": 40, "respondidos": 40}),
     [LIM_PROFUNDIDADE, LIM_IDIOMA, "A classificação do modelo foi conferida numa amostra de 40 itens."]),
    ("completa com um item", dict(validacao={"itens": 1, "respondidos": 1}),
     [LIM_PROFUNDIDADE, LIM_IDIOMA, "A classificação do modelo foi conferida numa amostra de 1 item."]),
    ("scholar com pagina repetida", dict(chamadas=_ch(scholar=SCH_ROWS + [_sch("LA1", "R9", "so_portugues", 1)])),
     [LIM_PROFUNDIDADE_OUTROS, LIM_IDIOMA_OUTROS, LIM_NAO_CONFERIDA]),
    # a profundidade pedida a cada consulta no Scholar e 2 variantes x M paginas x P resultados
    ("mesma profundidade nas duas fontes", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], max_resultados=40, n_retornados=40)
                                                                  for c in WEB_ROWS],
                                                             scholar=[r for r in SCH_ROWS if r["pagina"] == 1])),
     [LIM_BASE.format(n=40, m="1 página", p=20), LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("mesma profundidade com tres paginas", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], max_resultados=120, n_retornados=120)
                                                               for c in WEB_ROWS])),
     [LIM_BASE.format(n=120, m="3 páginas", p=20), LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("web 60 nao e a profundidade de tres paginas", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], max_resultados=60, n_retornados=60)
                                                                          for c in WEB_ROWS])),
     [LIM_BASE.format(n=60, m="3 páginas", p=20) + PEDIDA_DIFERE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("pagina do scholar com menos resultados", dict(chamadas=_ch(scholar=SCH_ROWS[:-1] + [_sch("LC1", R2, "sem_filtro", 2, n_retornados=5)])),
     [LIM_BASE.format(n=20, m="3 páginas", p=20) + VARIOU_E_DIFERE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("chamada da web com menos resultados e mesma profundidade",
     dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], max_resultados=120, n_retornados=120) for c in WEB_ROWS[:3]]
                       + [_web("LC1", "RY", max_resultados=120, n_retornados=119)])),
     [LIM_BASE.format(n=120, m="3 páginas", p=20) + VARIOU, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("as duas fontes com menos resultados",
     dict(chamadas=_ch(web=WEB_ROWS[:3] + [_web("LC1", "RY", n_retornados=19)],
                       scholar=SCH_ROWS[:-1] + [_sch("LC1", R2, "sem_filtro", 2, n_retornados=5)])),
     [LIM_BASE.format(n=20, m="3 páginas", p=20) + VARIOU_DUAS + PEDIDA_DIFERE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("so a web com menos resultados e profundidade diferente", dict(chamadas=_ch(web=WEB_ROWS[:3] + [_web("LC1", "RY", n_retornados=19)])),
     [LIM_BASE.format(n=20, m="3 páginas", p=20) + VARIOU_WEB + PEDIDA_DIFERE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("zero resultados conta como menos", dict(chamadas=_ch(scholar=SCH_ROWS[:-1] + [_sch("LC1", R2, "sem_filtro", 2, n_retornados=0)])),
     [LIM_BASE.format(n=20, m="3 páginas", p=20) + VARIOU_E_DIFERE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    ("resultados exatamente no pedido nao variam", dict(chamadas=_ch(web=[_web(c["consulta_id"], c["run_id"], n_retornados=20)
                                                                         for c in WEB_ROWS])),
     [LIM_PROFUNDIDADE, LIM_IDIOMA, LIM_NAO_CONFERIDA]),
    # n_retornados que nao e inteiro >= 0 nao conta (nulo, texto, booleano, negativo, decimal)
    *[(f"retornados invalido {v!r}", dict(chamadas=_ch(scholar=SCH_ROWS[:-1] + [_sch("LC1", R2, "sem_filtro", 2, n_retornados=v)])),
       [LIM_PROFUNDIDADE, LIM_IDIOMA, LIM_NAO_CONFERIDA]) for v in (None, "5", True, False, -1, 5.0)],
]


@pytest.mark.parametrize("descricao, mudancas, secao, esperado", FONTES_CASOS, ids=[c[0] for c in FONTES_CASOS])
def test_secao_fontes(descricao, mudancas, secao, esperado):
    assert _secao(_gerar(_mudar(_fatos(), **mudancas)), secao) == esperado


@pytest.mark.parametrize("descricao, mudancas, esperado", ESTRATEGIA_CASOS, ids=[c[0] for c in ESTRATEGIA_CASOS])
def test_secao_estrategia(descricao, mudancas, esperado):
    f = _mudar(_fatos(), **mudancas)
    assert _secao(_gerar(f), "estrategia") == esperado
    assert _secao(_gerar(f, modelo=False), "estrategia") == esperado


@pytest.mark.parametrize("descricao, mudancas, esperado", RECUPERACAO_CASOS, ids=[c[0] for c in RECUPERACAO_CASOS])
def test_secao_recuperacao(descricao, mudancas, esperado):
    assert _secao(_gerar(_mudar(_fatos(), **mudancas)), "recuperacao") == esperado


@pytest.mark.parametrize("descricao, mudancas, esperado", DEDUP_CASOS, ids=[c[0] for c in DEDUP_CASOS])
def test_secao_deduplicacao(descricao, mudancas, esperado):
    assert _secao(_gerar(_mudar(_fatos(), **mudancas)), "deduplicacao") == [DEDUP_1, esperado, *DEDUP_FIM]


@pytest.mark.parametrize("descricao, mudancas, bloco, esperado", CLASSIFICACAO_CASOS, ids=[c[0] for c in CLASSIFICACAO_CASOS])
def test_secao_classificacao_para_quem_entrou(descricao, mudancas, bloco, esperado):
    assert _secao(_gerar(_mudar(_fatos(), **mudancas)), "classificacao")[bloco] == esperado


VISITANTE_SEM_MODELO = VISITANTE.replace(", registrado nas chamadas como gemini-3.5-flash-lite, com as instruções da versão v2,",
                                         " (versão v2)")


@pytest.mark.parametrize("versao, esperado", [
    ("v2", VISITANTE), ("v3", VISITANTE_SEM_MODELO.replace("(versão v2)", "(versão v3)")),
    ("", VISITANTE_SEM_MODELO.replace(" (versão v2)", "")), (None, VISITANTE_SEM_MODELO.replace(" (versão v2)", "")),
])
def test_secao_classificacao_do_visitante(versao, esperado):
    assert _secao(_gerar(_mudar(_fatos(), versao_triagem=versao), modelo=False), "classificacao") == [esperado]


def test_visitante_com_itens_sem_triagem_ve_o_mesmo_texto():
    f = _mudar(_fatos(), relevancia={"Web": {"sem triagem válida": 2}, "Scholar": {"sem triagem válida": 3}})
    assert _secao(_gerar(f, modelo=False), "classificacao") == [VISITANTE]


@pytest.mark.parametrize("descricao, mudancas, esperado", DECISOES_CASOS, ids=[c[0] for c in DECISOES_CASOS])
def test_secao_decisoes_igual_para_todos(descricao, mudancas, esperado):
    f = _mudar(_fatos(), **mudancas)
    assert _secao(_gerar(f), "decisoes") == [esperado] == _secao(_gerar(f, modelo=False), "decisoes")


@pytest.mark.parametrize("descricao, mudancas, esperado", LIMITACOES_CASOS, ids=[c[0] for c in LIMITACOES_CASOS])
def test_secao_limitacoes_igual_para_todos(descricao, mudancas, esperado):
    f = _mudar(_fatos(), **mudancas)
    assert _secao(_gerar(f), "limitacoes") == [esperado + LIM_FIM] == _secao(_gerar(f, modelo=False), "limitacoes")


# ---------------------------------------------------------------- vazio e chaves ausentes
@pytest.mark.parametrize("fatos", [{}, None, {"execucoes": [], "corpus": {"n_itens": 0}}, {"execucoes": None, "corpus": None},
                                   _mudar(_fatos(), execucoes=[], corpus={"n_itens": 0})],
                         ids=["vazio", "nulo", "zeros", "nulos", "so_chamadas"])
@pytest.mark.parametrize("modelo", [True, False])
def test_banco_vazio(fatos, modelo):
    m = _gerar(fatos, modelo=modelo)
    assert _textos(m) == [("situacao", "Situação dos dados", [VAZIO])]
    assert m["ressalvas"] == [] and m["vazio"] is True and m["texto"] == "Situação dos dados\n\n" + VAZIO + "\n"


@pytest.mark.parametrize("fatos", [{"execucoes": [], "corpus": {"n_itens": 5}},
                                   {"execucoes": [_exec(R1, "a", "2026-10-21T10:00:00", "h", "c", no_relatorio=0)]}],
                         ids=["itens_sem_execucao", "so_execucao_fora"])
def test_nao_esta_vazio_com_itens_ou_com_alguma_execucao(fatos):
    m = _gerar(fatos)
    assert m["vazio"] is False and [i for i, _, _ in _textos(m)] == [i for i, _ in TITULOS]


def test_so_com_execucoes_os_numeros_ausentes_valem_zero():
    m = _gerar({"execucoes": [_exec(R1, "a", "2026-10-21T10:00:00", "h", "c")]})
    assert _secao(m, "estrategia")[-1] == [WEB_NADA, SCHOLAR_NADA]
    assert _secao(m, "recuperacao") == [
        "Na busca na web, nenhuma chamada consta nas execuções do relatório. No Google Scholar, nenhuma chamada consta nas "
        "execuções do relatório. Ao todo, são 0 itens, porque cada artigo e cada referência conta como um item: 0 artigos e 0 referências."]
    assert _secao(m, "deduplicacao")[1] == (DEDUP_ENTRE + "Assim, nenhuma referência da web repete um artigo do Scholar, e o total "
                                                          "é de 0 obras distintas.")
    assert _secao(m, "classificacao")[0] == "Os itens são classificados por um modelo de linguagem. O modelo atribui:"
    assert _secao(m, "decisoes") == [DECISOES_INICIO + NAO_SORTEADA]


# ---------------------------------------------------------------- ressalvas: so as das execucoes
def test_ressalvas_so_sobre_as_execucoes_na_ordem():
    f = _fatos()
    f["execucoes"] = [_exec(R1, "a", "2026-10-21T10:00:00", "h1", "x+sujo:1"), _exec(R2, "a", "2026-10-22T10:00:00", "h2", None,
                                                                                      status="interrompida"),
                      _exec("RFORA", "a", "2026-10-23T10:00:00", "h3", "y", no_relatorio=0)]
    f["retomadas"] = [{"run_id": R1, "n": 1}]
    esperado = [f"Execuções feitas com código ainda não commitado (commit com “+sujo”): {R1}. O commit registrado não reproduz "
                "exatamente o código que rodou.",
                f"Commit do código não registrado em: {R2}.",
                f"Execuções do relatório que não terminaram como concluídas: {R2}. Os números podem estar parciais.",
                "As execuções do relatório usaram 2 configurações diferentes; confira as diferenças antes de descrever o método "
                "como único.",
                f"Execuções retomadas (--retomar), cujo código e ambiente podem diferir dos da execução original: {R1}."]
    fora_custos = "1 execução está fora do relatório e não entra nos números; seu custo entra apenas no gasto real total. Ver execuções."
    fora_sem = "1 execução está fora do relatório e não entra nos números. Ver execuções."
    for modelo in (True, False):
        assert [MT.para_texto(r) for r in _gerar(f, custos=True, modelo=modelo)["ressalvas"]] == esperado + [fora_custos]
        assert [MT.para_texto(r) for r in _gerar(f, custos=False, modelo=modelo)["ressalvas"]] == esperado + [fora_sem]


def test_sem_ressalva_quando_as_execucoes_estao_em_ordem():
    f = _mudar(_fatos(), execucoes=[_exec(R1, "a", "2026-10-21T10:00:00", "h", "c")])
    assert _gerar(f)["ressalvas"] == [] and _gerar(f, custos=False, modelo=False)["ressalvas"] == []


@pytest.mark.parametrize("modelo", [True, False])
def test_custos_so_mudam_a_ressalva_das_execucoes_fora(modelo):
    f = _fatos()
    f["execucoes"].append(_exec("RFORA", "a", "2026-10-24T10:00:00", "h", "c", no_relatorio=0))
    com, sem = _gerar(f, custos=True, modelo=modelo), _gerar(f, custos=False, modelo=modelo)
    assert com["secoes"] == sem["secoes"] and com["ressalvas"][:-1] == sem["ressalvas"][:-1]
    assert com["ressalvas"][-1] != sem["ressalvas"][-1]


# ---------------------------------------------------------------- visitante: nada do modelo
DO_MODELO = [dict(relevancia={"Web": {"alta": 1}, "Scholar": {"fora_do_escopo": 9, "sem triagem válida": 4}}),
             dict(relevancia=None), dict(triagem_humana__ocultos_llm=0), dict(triagem_humana__ocultos_llm=1),
             dict(triagem_humana__pendentes=5), dict(triagem_humana__total=9),
             dict(corpus__n_triados=1), dict(corpus__n_alta=7), dict(corpus__n_fora=3)]


@pytest.mark.parametrize("mudancas", DO_MODELO)
def test_texto_do_visitante_nao_depende_de_numero_do_modelo(mudancas):
    f = _fatos()
    assert _gerar(_mudar(f, **mudancas), modelo=False) == _gerar(f, modelo=False)
    assert _gerar(_mudar(f, **mudancas), modelo=False, custos=False) == _gerar(f, modelo=False, custos=False)


def test_o_teste_do_visitante_enxerga_mudanca():
    f = _fatos()
    assert _gerar(_mudar(f, relevancia=None)) != _gerar(f)
    assert _gerar(_mudar(f, triagem_humana__ocultos_llm=1)) != _gerar(f)
    assert _gerar(_mudar(f, triagem_humana__incluidos=1), modelo=False) != _gerar(f, modelo=False)


def test_fatos_de_entrada_nao_mudam():
    f = _fatos()
    antes = copy.deepcopy(f)
    _gerar(f)
    _gerar(f, custos=False, modelo=False)
    assert f == antes


# ---------------------------------------------------------------- fonte unica
def test_unidades_vem_do_glossario_na_hora(monkeypatch):
    mv = _mv()
    trocado = [{"id": "unidades", "titulo": "x", "intro": "Intro trocada.",
                "entradas": [{"id": "a", "termo": "Termo A", "texto": "Texto A."}, {"id": "b", "termo": "Termo B", "texto": "Texto B."}]}]
    monkeypatch.setattr(glossario, "SECOES_VIES", trocado)
    assert _secao(mv.gerar_metodologia_vies(_fatos()), "unidades") == ["Intro trocada.", ["Termo A: Texto A.", "Termo B: Texto B."]]


def test_lista_das_execucoes_vem_do_mesmo_ajudante_da_reprodutibilidade(monkeypatch):
    mv = _mv()
    assert hasattr(MT, "_itens_execucoes")
    vistos = []

    def falso(execucoes):
        vistos.append([e["run_id"] for e in execucoes])
        return [[("item trocado", None)]]
    monkeypatch.setattr(MT, "_itens_execucoes", falso)
    f = _fatos()
    f["execucoes"].append(_exec("RFORA", "a", "2026-10-24T10:00:00", "h", "c", no_relatorio=0))
    assert _secao(mv.gerar_metodologia_vies(f), "fontes")[-1] == ["item trocado"]
    assert vistos == [[R1, R2, R3]]
    vistos.clear()
    real = MT.gerar_metodologia(_fatos_reais())
    assert next(b for i, _, b in _textos(real) if i == "reprodutibilidade")[1] == ["item trocado"]
    assert vistos == [["RUN_A", "RUN_B"]]


def test_ressalvas_vem_do_mesmo_ajudante_do_estudo_real(monkeypatch):
    mv = _mv()
    assert hasattr(MT, "_ressalvas_execucoes")
    vistos = []

    def falso(x, custos=True):
        vistos.append(custos)
        return [[("ressalva trocada", None)]]
    monkeypatch.setattr(MT, "_ressalvas_execucoes", falso)
    assert mv.gerar_metodologia_vies(_fatos(), custos=False)["ressalvas"] == [[("ressalva trocada", None)]]
    assert mv.gerar_metodologia_vies(_fatos(), custos=True, modelo=False)["ressalvas"] == [[("ressalva trocada", None)]]
    assert vistos == [False, True]
    vistos.clear()
    assert [("ressalva trocada", None)] in MT.gerar_metodologia(_fatos_reais(), custos=False)["ressalvas"]
    assert vistos == [False]


def test_texto_para_copiar_vem_do_mesmo_ajudante(monkeypatch):
    mv = _mv()
    monkeypatch.setattr(MT, "_texto_puro", lambda secoes, ressalvas: f"{len(secoes)} seções e {len(ressalvas)} ressalvas")
    assert mv.gerar_metodologia_vies(_fatos())["texto"] == "9 seções e 2 ressalvas"
    assert mv.gerar_metodologia_vies({})["texto"] == "1 seções e 0 ressalvas"


def test_periodo_vem_do_ajudante_do_estudo_real(monkeypatch):
    mv = _mv()
    vistos = []
    monkeypatch.setattr(MT, "_periodo", lambda a, b: vistos.append((a, b)) or "no período trocado")
    assert _secao(mv.gerar_metodologia_vies(_fatos()), "fontes")[2] == "O levantamento usou 3 execuções, no período trocado: 2 de busca (1 na web e 1 no Google Scholar) e 1 de triagem pelo modelo." + CADA_EXECUCAO
    assert vistos == [("2026-10-21T21:35:59+00:00", "2026-10-23T19:36:21+00:00")]


def test_singular_e_plural_vem_do_ajudante_do_estudo_real(monkeypatch):
    mv = _mv()
    monkeypatch.setattr(MT, "_pl", lambda n, singular, plural: plural.upper())
    assert _secao(mv.gerar_metodologia_vies(_fatos()), "recuperacao")[0].endswith(
        "Ao todo, SÃO 720 ITENS, porque cada artigo e cada referência conta como um item: 521 ARTIGOS e 199 REFERÊNCIAS.")


def test_filtro_de_idioma_vem_do_ajudante_do_adaptador(tmp_path, monkeypatch):
    import adaptadores.leitura_sqlite as LS
    caminho, _ = _banco_parametros(tmp_path)
    vistos = []
    monkeypatch.setattr(LS, "_idioma_da_chamada", lambda p: vistos.append(p) or "trocado")
    sch = _parametros(caminho)["scholar"]
    assert [r["filtro_idioma"] for r in sch] == ["trocado", "trocado"] and len(vistos) == 2


# ---------------------------------------------------------------- o estudo real nao muda
def _real_com_ressalvas():
    f = _fatos_reais()
    f["execucoes"][0]["commit_git"] = "deadbeef+sujo:1"
    f["execucoes"][1].update(status="interrompida", config_hash="zzzzyyyyxxxx", commit_git=None)
    f["retomadas"] = [{"run_id": "RUN_A", "n": 1}]
    return f


def test_metodologia_do_estudo_real_nao_mudou():
    """A saída de gerar_metodologia (seções, ressalvas e texto) fica como estava antes da metodologia do vies."""
    saidas = []
    for f in (_fatos_reais(), _real_com_ressalvas(), {}, {**_fatos_reais(), "banco": "vies"}):
        for custos in (True, False):
            for modelo in (True, False):
                saidas.append(repr(MT.gerar_metodologia(f, None, custos=custos, modelo=modelo)))
    assert hashlib.sha256("\n".join(saidas).encode()).hexdigest()[:16] == "f64ecda89dba85e8"


def test_respondidas_da_validacao():
    assert hasattr(VV, "respondidas")
    assert VV.respondidas([]) == 0
    assert VV.respondidas([{"relevancia": "alta"}, {"relevancia": None}, {"relevancia": ""}, {"relevancia": "baixa"}, {}]) == 2
    assert VV.respondidas([{}]) == 0


# ---------------------------------------------------------------- textos fixos presos a configuracao
def test_texto_fixo_dos_conjuntos_segue_a_configuracao():
    """As frases fixas "quinze consultas ... em três conjuntos de cinco" e as descrições de A, B e C valem para a configuração de
    hoje; se ela mudar, este teste falha e o texto precisa ser revisto."""
    from config.consultas import CONJUNTOS_LITERATURA
    assert list(CONJUNTOS_LITERATURA) == ["A", "B", "C"]
    assert [len(v) for v in CONJUNTOS_LITERATURA.values()] == [5, 5, 5]
    assert all(t.id.startswith("L" + c) for c, v in CONJUNTOS_LITERATURA.items() for t in v)


# ---------------------------------------------------------------- montagem dos fatos (leituras)
class _LeituraFalsa:
    def __init__(self):
        self.chamadas = []

    def _anota(self, nome, valor):
        self.chamadas.append(nome)
        return valor

    def fatos_metodologia(self, *a, **k):
        return self._anota("fatos_metodologia", {
            "execucoes": [{"run_id": "E1"}], "retomadas": [{"run_id": "E1", "n": 2}],
            "literatura": {"triagem": {"total": 9, "incluidos": 1, "excluidos": 2, "pendentes": 6, "ocultos_llm": 3}},
            "web": {"n_requisicoes": 999}, "achados": {"total": 5}})

    def analise_ferramentas(self):
        return self._anota("analise_ferramentas", {"chamadas": [], "resultados": {"busca_literatura": 11, "busca_academica": 22,
                                                                                 "busca_web": 33}, "itens": {}, "creditos": {}})

    def parametros_buscas_vies(self):
        return self._anota("parametros_buscas_vies", {"web": [{"consulta_id": "LA1"}], "scholar": []})

    def linhas_validacao_vies(self):
        return self._anota("linhas_validacao_vies", [{"relevancia": "alta"}, {"relevancia": None}, {"relevancia": "media"}])

    def triagem_vies_por_execucao(self):
        return self._anota("triagem_vies_por_execucao", [{"run_id": "E1", "versao": "v9", "provedor": "p:m"}])


def _contexto():
    return SimpleNamespace(banco="vies", conjunto_da_consulta={"LB2": "B", "LA1": "A", "LZ": "Z"},
                           consultas_literatura={"LA1": "texto a", "LB2": "texto b"}, versao_triagem_vies="v9")


def test_fatos_do_vies_montados_das_leituras(monkeypatch):
    mv = _mv()
    leitura, ctx = _LeituraFalsa(), _contexto()
    lista = [{"id": "W-1"}]
    pedidos = []
    monkeypatch.setattr(visao_geral_vies, "itens", lambda l, c: pedidos.append((l, c)) or lista)
    monkeypatch.setattr(AV, "resumo", lambda l: {"resumo_de": l})
    monkeypatch.setattr(AV, "relevancia_por_fonte", lambda l: {"relevancia_de": l})
    monkeypatch.setattr(VV, "respondidas", lambda linhas: 77)
    f = mv.fatos_vies(leitura, ctx)
    assert f == {
        "banco": "vies",
        "execucoes": [{"run_id": "E1"}], "retomadas": [{"run_id": "E1", "n": 2}],
        "triagem_humana": {"total": 9, "incluidos": 1, "excluidos": 2, "pendentes": 6, "ocultos_llm": 3},
        "consultas": [{"id": "LB2", "conjunto": "B", "texto": "texto b"}, {"id": "LA1", "conjunto": "A", "texto": "texto a"},
                      {"id": "LZ", "conjunto": "Z", "texto": None}],
        "chamadas": {"web": [{"consulta_id": "LA1"}], "scholar": []},
        "ocorrencias": {"web": 11, "scholar": 22},
        "corpus": {"resumo_de": lista}, "relevancia": {"relevancia_de": lista},
        "versao_triagem": "v9",
        "validacao": {"itens": 3, "respondidos": 77},
        "triagem_por_execucao": [{"run_id": "E1", "versao": "v9", "provedor": "p:m"}],
    }
    assert pedidos == [(leitura, ctx)]
    assert sorted(leitura.chamadas) == ["analise_ferramentas", "fatos_metodologia", "linhas_validacao_vies", "parametros_buscas_vies",
                                        "triagem_vies_por_execucao"]


def test_fatos_do_vies_sem_resultados_das_buscas(monkeypatch):
    mv = _mv()
    leitura = _LeituraFalsa()
    leitura.analise_ferramentas = lambda: {"chamadas": [], "resultados": {}, "itens": {}, "creditos": {}}
    monkeypatch.setattr(visao_geral_vies, "itens", lambda l, c: [])
    assert mv.fatos_vies(leitura, _contexto())["ocorrencias"] == {"web": 0, "scholar": 0}


# ---------------------------------------------------------------- leitura dos parametros das chamadas
def _parametros(caminho):
    assert hasattr(LeituraPainelSQLite, "parametros_buscas_vies"), "falta a leitura dos parametros das buscas do vies"
    return LeituraPainelSQLite(caminho).parametros_buscas_vies()


WEB_OK = json.dumps({"country": "BR", "max_results": 20, "query": "q", "search_language_filter": ["pt"]})


def _banco_parametros(tmp_path):
    """O banco de teste do vies com parametros de verdade: tres chamadas da web (LA1, LA2, LB1) e duas do Scholar (LB1 com e
    sem o filtro de idioma), uma execucao fora do relatorio e uma chamada da triagem."""
    caminho = tmp_path / "busca.db"
    construir_vies(caminho, tmp_path / "raw")
    con = sqlite3.connect(caminho)
    run = con.execute("SELECT run_id FROM execucoes").fetchone()[0]
    con.execute("UPDATE chamadas SET parametros_json = ? WHERE etapa = 'busca_literatura'", (WEB_OK,))
    con.execute("UPDATE chamadas SET parametros_json = ? WHERE etapa = 'busca_academica'",
                (json.dumps({"engine": "google_scholar", "hl": "pt", "lr": "lang_pt", "num": 20, "q": "q", "start": 0}),))
    colunas = "run_id, etapa, provedor, alvo_tipo, alvo_id, pagina, parametros_json, chave_idempotencia, requisitado_em, sucesso"
    con.execute(f"INSERT INTO chamadas ({colunas}) VALUES (?, 'busca_academica', 'falso', 'termo', 'LB1', 1, ?, 'k-sem', "
                "'2026-11-01T10:00:00+00:00', 1)", (run, json.dumps({"engine": "google_scholar", "hl": "pt", "num": 20, "q": "q",
                                                                     "start": 0})))
    con.execute("INSERT INTO execucoes (run_id, iniciado_em, comando, config_hash, config_json, status, no_relatorio) "
                "VALUES ('RFORA', '2026-11-01T09:00:00+00:00', 'academico', 'h', '{}', 'concluida', 0)")
    con.execute(f"INSERT INTO chamadas ({colunas}) VALUES ('RFORA', 'busca_academica', 'falso', 'termo', 'LA1', 1, ?, 'k-fora', "
                "'2026-11-01T10:00:00+00:00', 1)", (json.dumps({"hl": "pt", "num": 20}),))
    con.execute(f"INSERT INTO chamadas ({colunas}) VALUES (?, 'triagem_escopo', 'falso', 'lote', 'x', NULL, '{{}}', 'k-tri', "
                "'2026-11-01T10:00:00+00:00', 1)", (run,))
    con.commit()
    con.close()
    return caminho, run


def test_parametros_das_buscas_do_relatorio(tmp_path):
    caminho, run = _banco_parametros(tmp_path)
    web = {"run_id": run, "sucesso": 1, "max_resultados": 20, "idiomas": ["pt"], "pais": "BR", "n_retornados": 2}
    sch = {"run_id": run, "sucesso": 1, "interface": "pt", "por_pagina": 20, "pagina": 1}
    assert _parametros(caminho) == {
        "web": [{"consulta_id": "LA1", **web}, {"consulta_id": "LA2", **web}, {"consulta_id": "LB1", **web}],
        "scholar": [{"consulta_id": "LB1", **sch, "filtro_idioma": "so_portugues", "n_retornados": 1},
                    {"consulta_id": "LB1", **sch, "filtro_idioma": "sem_filtro", "n_retornados": None}]}


@pytest.mark.parametrize("valor", [None, 0, 7, -3, "x", 2.5])
def test_retornados_como_gravados(tmp_path, valor):
    caminho, run = _banco_parametros(tmp_path)
    con = sqlite3.connect(caminho)
    con.execute("UPDATE chamadas SET n_retornados = ? WHERE alvo_id = 'LA2'", (valor,))
    con.execute("UPDATE chamadas SET n_retornados = ? WHERE chave_idempotencia = 'k-sem'", (valor,))
    con.commit()
    con.close()
    p = _parametros(caminho)
    lidos = [p["web"][1].get("n_retornados", "ausente"), p["scholar"][1].get("n_retornados", "ausente"),
             p["web"][0].get("n_retornados", "ausente"), p["scholar"][0].get("n_retornados", "ausente")]
    assert lidos == [valor, valor, 2, 1]


# (parametros gravados, linha esperada da web sem consulta, execucao e sucesso)
PARAMETROS_WEB = [
    ("{}", {"max_resultados": None, "idiomas": None, "pais": None}),
    ("nao e json", {"max_resultados": None, "idiomas": None, "pais": None}),
    ("[1, 2]", {"max_resultados": None, "idiomas": None, "pais": None}),
    ("null", {"max_resultados": None, "idiomas": None, "pais": None}),
    ('"texto"', {"max_resultados": None, "idiomas": None, "pais": None}),
    ('{"max_results": "20", "search_language_filter": "pt", "country": null}', {"max_resultados": "20", "idiomas": "pt", "pais": None}),
    ('{"max_results": 10, "search_language_filter": ["pt", "en"], "country": "PT"}',
     {"max_resultados": 10, "idiomas": ["pt", "en"], "pais": "PT"}),
    ('{"max_results": true, "search_language_filter": [], "country": {"a": 1}}', {"max_resultados": True, "idiomas": [], "pais": {"a": 1}}),
]


@pytest.mark.parametrize("parametros, esperado", PARAMETROS_WEB)
def test_parametros_da_web_como_gravados(tmp_path, parametros, esperado):
    caminho, run = _banco_parametros(tmp_path)
    con = sqlite3.connect(caminho)
    con.execute("UPDATE chamadas SET parametros_json = ? WHERE etapa = 'busca_literatura' AND alvo_id = 'LA2'", (parametros,))
    con.commit()
    con.close()
    web = _parametros(caminho)["web"]
    assert web[1] == {"consulta_id": "LA2", "run_id": run, "sucesso": 1, "n_retornados": 2, **esperado}
    assert web[0]["max_resultados"] == 20 and web[2]["max_resultados"] == 20


PARAMETROS_SCHOLAR = [
    ('{"hl": "pt", "lr": "lang_pt", "num": 20}', {"interface": "pt", "filtro_idioma": "so_portugues", "por_pagina": 20}),
    ('{"hl": "pt", "lr": null, "num": 20}', {"interface": "pt", "filtro_idioma": "sem_filtro", "por_pagina": 20}),
    ('{"hl": "en", "lr": "lang_en", "num": "20"}', {"interface": "en", "filtro_idioma": "outro", "por_pagina": "20"}),
    ('{"lr": ""}', {"interface": None, "filtro_idioma": "outro", "por_pagina": None}),
    ("{}", {"interface": None, "filtro_idioma": "sem_filtro", "por_pagina": None}),
    ("nao e json", {"interface": None, "filtro_idioma": "outro", "por_pagina": None}),
    ("[1]", {"interface": None, "filtro_idioma": "outro", "por_pagina": None}),
]


@pytest.mark.parametrize("parametros, esperado", PARAMETROS_SCHOLAR)
def test_parametros_do_scholar_como_gravados(tmp_path, parametros, esperado):
    caminho, run = _banco_parametros(tmp_path)
    con = sqlite3.connect(caminho)
    con.execute("UPDATE chamadas SET parametros_json = ?, pagina = 3, sucesso = 0 WHERE alvo_id = 'LB1' AND chave_idempotencia = 'k-sem'",
                (parametros,))
    con.commit()
    con.close()
    sch = _parametros(caminho)["scholar"]
    assert sch[1] == {"consulta_id": "LB1", "run_id": run, "sucesso": 0, "pagina": 3, "n_retornados": None, **esperado}


# ---------------------------------------------------------------- leitura das versoes e dos modelos da triagem
def _triagens(caminho):
    assert hasattr(LeituraPainelSQLite, "triagem_vies_por_execucao"), "falta a leitura das versoes e modelos da triagem do vies"
    return sorted(LeituraPainelSQLite(caminho).triagem_vies_por_execucao(),
                  key=lambda l: (str(l["run_id"]), str(l["versao"]), str(l["provedor"])))


def _banco_triagens(tmp_path):
    """Triagens em tres execucoes: a do relatorio (v2 pela chamada 'k-tri', v1 sem chamada, e duas linhas repetidas), uma fora
    do relatorio e uma chamada de outro modelo."""
    caminho, run = _banco_parametros(tmp_path)
    con = sqlite3.connect(caminho)
    tri = con.execute("SELECT chamada_id FROM chamadas WHERE chave_idempotencia = 'k-tri'").fetchone()[0]
    con.execute("INSERT INTO chamadas (run_id, etapa, provedor, alvo_tipo, alvo_id, parametros_json, chave_idempotencia, "
                "requisitado_em, sucesso) VALUES ('RFORA', 'triagem_escopo', 'outro:m2', 'lote', 'y', '{}', 'k-tri-fora', "
                "'2026-11-01T10:00:00+00:00', 1)")
    fora = con.execute("SELECT chamada_id FROM chamadas WHERE chave_idempotencia = 'k-tri-fora'").fetchone()[0]
    con.execute("UPDATE chamadas SET provedor = 'gemini:gemini-x' WHERE chamada_id = ?", (tri,))
    linhas = [(run, tri, 1, "v2"), (run, tri, 2, "v2"), (run, None, 3, "v1"), (run, tri, 4, None), ("RFORA", fora, 1, "v2")]
    for r_, ch, item, versao in linhas:
        con.execute("INSERT INTO triagem_escopo (run_id, chamada_id, fonte, item_id, status, prompt_versao, criado_em) "
                    "VALUES (?, ?, 'artigo', ?, 'elegivel', ?, '2026-11-01T10:00:00+00:00')", (r_, ch, item, versao))
    con.commit()
    con.close()
    return caminho, run


def test_triagem_por_execucao_so_do_relatorio_e_sem_repeticao(tmp_path):
    caminho, run = _banco_triagens(tmp_path)
    assert _triagens(caminho) == sorted([
        {"run_id": run, "versao": "v1", "provedor": None},
        {"run_id": run, "versao": "v2", "provedor": "gemini:gemini-x"},
        {"run_id": run, "versao": None, "provedor": "gemini:gemini-x"},
    ], key=lambda l: (str(l["run_id"]), str(l["versao"]), str(l["provedor"])))


def test_triagem_por_execucao_sem_as_tabelas(tmp_path):
    sqlite3.connect(tmp_path / "vazio.db").execute("CREATE TABLE x (a)")
    assert _triagens(tmp_path / "vazio.db") == []


def test_triagem_por_execucao_sem_triagens(tmp_path):
    caminho, _ = _banco_parametros(tmp_path)
    assert _triagens(caminho) == []


def test_parametros_sem_as_tabelas(tmp_path):
    sqlite3.connect(tmp_path / "vazio.db").execute("CREATE TABLE x (a)")
    assert _parametros(tmp_path / "vazio.db") == {"web": [], "scholar": []}


def test_parametros_sem_chamadas(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    con = sqlite3.connect(tmp_path / "busca.db")
    con.execute("DELETE FROM chamadas")
    con.commit()
    con.close()
    assert _parametros(tmp_path / "busca.db") == {"web": [], "scholar": []}


# ---------------------------------------------------------------- pagina
def _main(html):
    return re.search(r'<main id="conteudo" tabindex="-1">(.*)</main>', html, re.S).group(1)


@pytest.fixture
def banco_vies(tmp_path):
    caminho, _ = _banco_parametros(tmp_path)
    con = sqlite3.connect(caminho)
    refs = [r[0] for r in con.execute("SELECT referencia_id FROM referencias_web ORDER BY 1")]
    arts = [r[0] for r in con.execute("SELECT artigo_id FROM artigos ORDER BY 1")]
    con.close()
    _triar(caminho, [_linha("referencia", i) for i in refs] + [_linha("artigo", i, status_bruto="fora_do_escopo", status="excluido")
                                                                for i in arts])
    return caminho


def test_pagina_do_vies_com_as_nove_secoes(banco_vies, tmp_path):
    r = _cli(banco_vies, tmp_path).get("/metodologia")
    assert r.status_code == 200
    main = _main(r.text)
    assert re.findall(r'<section class="cartao" id="([a-z]+)"><h2>([^<]+)</h2>', main) == TITULOS
    for trecho in PROIBIDOS:
        assert trecho not in main, trecho
    for esperado in ("Busca na web: cada consulta foi enviada numa chamada própria, pedindo até 20 resultados, com os parâmetros de "
                     "idioma português e de país Brasil. O conjunto A foi consultado em 1 execução; o B, em 1; o C, em 0.",
                     "Google Scholar: cada consulta foi feita duas vezes, com a interface em português: uma vez com o parâmetro de "
                     "idioma português e outra sem parâmetro de idioma. Cada vez pediu 20 resultados por página, em até 1 página; a "
                     "paginação parava na primeira página com menos de 20 resultados ou com falha na chamada.",
                     "Resultado da triagem:",
                     "1 artigo que o modelo pôs fora do escopo com confiança alta fica oculto das listas de artigos até uma "
                     "decisão humana.",
                     NAO_SORTEADA):
        assert esperado in main, esperado


SUB_ANTIGO = ('<p class="sub">Texto gerado a partir do banco, pronto para adaptar à seção de método. Os números com link levam à '
              'página do painel que os justifica. Nada aqui é inventado: o que falta nos dados aparece como ressalva.</p>')
AVISO_VIES = ('<strong class="em-linha">Ressalvas sobre os dados</strong>: {n} {r}. <a href="#ressalvas">Ler as ressalvas</a>.')


def _aviso_vies(main):
    m = re.search(r'<section class="aviso aviso-lista" aria-label="Ressalvas">\s*(.*?)\s*</section>', main, re.S)
    return m and m.group(1)


@pytest.mark.parametrize("entrou", [True, False])
def test_subtitulo_e_aviso_do_vies(banco_vies, tmp_path, entrou, monkeypatch):
    mv = _mv()
    original = mv.gerar_metodologia_vies
    for n, ressalvas in ((0, []), (1, [[("uma", None)]]), (2, [[("uma", None)], [("outra", None)]])):
        monkeypatch.setattr(mv, "gerar_metodologia_vies", lambda *a, _r=ressalvas, **k: {**original(*a, **k), "ressalvas": _r})
        cli = _cli(banco_vies, tmp_path)
        main = _main(cli.get("/metodologia").text)
        assert f'<p class="sub">{SUBTITULO}</p>' in main
        for velho in ("pronto para adaptar", "Nada aqui é inventado", "Antes de usar este texto", "Os números com link"):
            assert velho not in main, velho
        if n:
            assert _aviso_vies(main) == AVISO_VIES.format(n=n, r="ressalva" if n == 1 else "ressalvas")
        else:
            assert _aviso_vies(main) is None


def test_subtitulo_vazio_no_vies_sem_dados():
    m = _gerar({})
    assert m["vazio"] is True and m.get("subtitulo") == SUBTITULO


def test_pagina_do_vies_com_a_amostra_sorteada(banco_vies, tmp_path):
    from test_validacao_vies import _amostra, _gravar
    amostra = _amostra(banco_vies)
    _gravar(banco_vies, lambda r: r.sortear_validacao_vies(amostra))
    main = _main(_cli(banco_vies, tmp_path).get("/metodologia").text)
    assert (f"A amostra de validação humana da triagem foi sorteada: 0 de {len(amostra)} itens respondidos.") in main
    assert LIM_NAO_CONFERIDA in main


def test_validacao_usa_o_mesmo_contador_de_respostas(banco_vies, tmp_path, monkeypatch):
    from test_validacao_vies import _amostra, _cli as _cli_validacao, _gravar
    assert hasattr(VV, "respondidas")
    amostra = _amostra(banco_vies)
    _gravar(banco_vies, lambda r: r.sortear_validacao_vies(amostra))
    monkeypatch.setattr(VV, "respondidas", lambda linhas: 7)
    assert f"<strong>7 de {len(amostra)}</strong>" in _cli_validacao(banco_vies, tmp_path).get("/validacao").text


def _espiar(monkeypatch):
    mv = _mv()
    chamadas = {"vies": [], "real": []}
    original_vies, original_real = mv.gerar_metodologia_vies, MT.gerar_metodologia

    def espia_vies(*a, **k):
        chamadas["vies"].append((k.get("custos"), k.get("modelo")))
        return original_vies(*a, **k)

    def espia_real(*a, **k):
        chamadas["real"].append(k.get("modelo", True))
        return original_real(*a, **k)
    monkeypatch.setattr(mv, "gerar_metodologia_vies", espia_vies)
    monkeypatch.setattr(MT, "gerar_metodologia", espia_real)
    return chamadas


def test_no_vies_o_visitante_e_quem_entrou_recebem_o_texto_do_vies(demo, tmp_path, monkeypatch):  # noqa: F811
    chamadas = _espiar(monkeypatch)
    app, contas, contas_db, _ = _painel(demo, tmp_path, banco="vies")
    gravar_politica(contas, "vies")
    visitante = TestClient(app).get("/metodologia", follow_redirects=False)
    assert visitante.status_code == 200
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    r = leitor.get("/metodologia")
    assert r.status_code == 200
    assert chamadas == {"vies": [(False, False), (True, True)], "real": []}
    assert "Os resultados automatizados ainda não são divulgados." in visitante.text
    assert "Resultado da triagem:" not in visitante.text and "Resultado da triagem:" in r.text
    for trecho in DO_OUTRO_ESTUDO:
        assert trecho not in _main(visitante.text) and trecho not in _main(r.text), trecho


@pytest.mark.parametrize("nome", ["real", "demo", "simulado"])
def test_nos_outros_bancos_a_metodologia_de_antes(nome, demo, tmp_path, monkeypatch):  # noqa: F811
    from test_painel import _app
    chamadas = _espiar(monkeypatch)
    db, raw = demo
    r = TestClient(_app(db, raw, tmp_path, nome=nome)[0]).get("/metodologia")
    assert r.status_code == 200
    assert chamadas == {"vies": [], "real": [True]}
    assert "Objeto e finalidade" not in r.text
    assert SUB_ANTIGO in r.text and SUBTITULO not in r.text


def test_pagina_do_visitante_no_vies_nao_depende_dos_numeros_do_modelo(demo, tmp_path, monkeypatch):  # noqa: F811
    mv = _mv()
    original = mv.fatos_vies
    app, contas, contas_db, _ = _painel(demo, tmp_path, banco="vies")
    gravar_politica(contas, "vies")
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303

    def mudado(l, c):
        f = original(l, c)
        f["relevancia"] = {"Web": {"alta": 4321}, "Scholar": {"fora_do_escopo": 1234}}
        f["triagem_humana"] = {**(f.get("triagem_humana") or {}), "ocultos_llm": 987}
        return f
    paginas, do_leitor = [], []
    for fatos in (original, mudado):
        monkeypatch.setattr(mv, "fatos_vies", fatos)
        paginas.append(TestClient(app).get("/metodologia", follow_redirects=False).content)
        do_leitor.append(leitor.get("/metodologia").content)
    assert paginas[0] == paginas[1]
    assert do_leitor[0] != do_leitor[1]


# ---------------------------------------------------------------- PostgreSQL (o vies roda no PostgreSQL na nuvem)
@pytest.mark.postgres
def test_parametros_e_pagina_iguais_no_postgres(pg_url, tmp_path, monkeypatch):
    from adaptadores import migrador_postgres as M
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres import importador as I
    from composicao import Fabrica, banco_escolhido
    caminho, _ = _banco_parametros(tmp_path)
    con = sqlite3.connect(caminho)
    refs = [r[0] for r in con.execute("SELECT referencia_id FROM referencias_web ORDER BY 1")]
    arts = [r[0] for r in con.execute("SELECT artigo_id FROM artigos ORDER BY 1")]
    con.close()
    _triar(caminho, [_linha("referencia", i) for i in refs] + [_linha("artigo", i, status_bruto="fora_do_escopo", status="excluido")
                                                                for i in arts])
    esperado = _parametros(caminho)
    esperado_triagens = _triagens(caminho)
    no_sqlite = _main(_cli(caminho, tmp_path).get("/metodologia").text)
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    I.importar(caminho, pg_url, esquema="vies")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    import test_analises_vies as TAV
    with banco_escolhido("vies"):
        fab = Fabrica()
        leitura = fab.leitura_painel()
        assert isinstance(leitura, LeituraPainelPostgres)
        assert leitura.parametros_buscas_vies() == esperado
        assert sorted(leitura.triagem_vies_por_execucao(), key=lambda l: (str(l["run_id"]), str(l["versao"]), str(l["provedor"]))) == \
            esperado_triagens
        monkeypatch.setattr(TAV, "LeituraPainelSQLite", lambda _: leitura)
        no_postgres = _main(TAV._cli(caminho, tmp_path).get("/metodologia").text)
    fab.postgres[0].close()
    assert "Objeto e finalidade" in no_postgres
    assert no_postgres == no_sqlite
