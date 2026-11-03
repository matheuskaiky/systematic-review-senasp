"""Fluxo PRISMA do banco `vies` (busca de viés algorítmico): a introdução sobre o que é o PRISMA, o braço da busca na web só
na identificação e na organização (ocorrências, referências únicas, referências que repetem um artigo do Scholar e obras
distintas), os registros repetidos do Scholar separados entre outra consulta e a mesma consulta, e as bases manuais como
"não se aplica". A numeração da view `v_prisma` não muda, e a página dos outros bancos sai igual, byte a byte.
As obras nas duas fontes contam obras (não referências): a mesma conta nas Análises e na Visão Geral."""
import copy
import hashlib
import importlib
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from apoio_divulgacao import gravar_politica
from dominio import analises_vies as AV, observatorio_vies as OV
from painel import analises_blocos_vies as bv, rotulos, visao_geral as VG, visao_geral_vies
from test_analises_vies import _art, _cli, _itens, _web
from test_autenticacao import _criar, _entrar
from test_divulgacao_acesso import _painel
from test_divulgacao_prisma import AVISO, DO_MODELO, _caixas, _com_removidos_pelo_modelo
from test_painel import _app, demo  # noqa: F401
from test_triagem_vies import construir_vies
from test_visao_geral_montador import ADMIN, _bloco, _ind, _vies


def _pv():
    """O módulo novo, importado em cada teste (sem ele, cada teste falha sozinho, não a coleta inteira)."""
    return importlib.import_module("painel.prisma_vies")


def _main(html):
    return re.search(r'<main id="conteudo" tabindex="-1">(.*)</main>', html, re.S).group(1)


# ================================================================ obras por fonte (unidade: obra)
# (descrição, referências da web, artigos do Scholar,
#  (n_em_ambas_fontes, n_obras_em_ambas, n_obras_so_web, n_obras_so_scholar, n_obras))
OBRAS_CASOS = [
    ("vazio", [], [], (0, 0, 0, 0, 0)),
    ("sem junção", [_web(1)], [_art(9)], (0, 0, 1, 1, 2)),
    ("só web", [_web(1), _web(2)], [], (0, 0, 2, 0, 2)),
    ("só Scholar", [], [_art(9), _art(10)], (0, 0, 0, 2, 2)),
    ("uma pela URL", [_web(1, url_original="https://s.org/9")], [_art(9)], (1, 1, 0, 0, 1)),
    ("uma só pelo título", [_web(1, titulo="Artigo 9")], [_art(9)], (1, 1, 0, 0, 1)),
    ("URL e título do mesmo artigo contam uma vez", [_web(1, url_original="https://s.org/9", titulo="Artigo 9")], [_art(9)],
     (1, 1, 0, 0, 1)),
    ("duas referências, um artigo: 2 referências e 1 obra", [_web(1, url_original="https://s.org/9"), _web(2, titulo="Artigo 9")],
     [_art(9), _art(10)], (2, 1, 0, 1, 2)),
    ("três referências, um artigo", [_web(1, url_original="https://s.org/9"), _web(2, titulo="Artigo 9"),
                                     _web(3, url_original="https://s.org/9/")], [_art(9)], (3, 1, 0, 0, 1)),
    ("duas referências, dois artigos", [_web(1, url_original="https://s.org/9"), _web(2, titulo="Artigo 10"), _web(3)],
     [_art(9), _art(10), _art(11)], (2, 2, 1, 1, 4)),
    ("título com caixa, acento e espaços diferentes", [_web(1, titulo="  ÁRTIGO   9 ")], [_art(9, titulo="Ártigo 9")],
     (1, 1, 0, 0, 1)),
    ("ambígua: a referência casa com dois artigos e não é atribuída a nenhum",
     [_web(1, titulo="Comum")], [_art(9, titulo="Comum"), _art(10, titulo="Comum")], (1, 0, 0, 2, 2)),
    ("ambígua ao lado de uma junção ao mesmo artigo", [_web(1, titulo="Comum"), _web(2, url_original="https://s.org/9")],
     [_art(9, titulo="Comum"), _art(10, titulo="Comum")], (2, 1, 0, 1, 2)),
]


@pytest.mark.parametrize("descricao, web, arts, esperado", OBRAS_CASOS, ids=[c[0] for c in OBRAS_CASOS])
def test_resumo_conta_as_obras_por_fonte(descricao, web, arts, esperado):
    r = AV.resumo(_itens(web, arts))
    assert (r["n_em_ambas_fontes"], r.get("n_obras_em_ambas"), r.get("n_obras_so_web"), r.get("n_obras_so_scholar"),
            r["n_obras"]) == esperado
    assert (r.get("n_obras_so_web") or 0) + (r.get("n_obras_so_scholar") or 0) + (r.get("n_obras_em_ambas") or 0) == r["n_obras"]


@pytest.mark.parametrize("descricao, web, arts, esperado", OBRAS_CASOS, ids=[c[0] for c in OBRAS_CASOS])
def test_obras_por_fonte_iguais_as_do_observatorio(descricao, web, arts, esperado):
    lista = _itens(web, arts)
    r, o = AV.resumo(lista), OV.resumo(OV.projecao(lista, ["A", "B"])[0])
    assert (r.get("n_obras_so_web"), r.get("n_obras_so_scholar"), r.get("n_obras_em_ambas"), r["n_obras"]) == (
        o["so_web"], o["so_scholar"], o["ambas"], o["obras"])


def test_resumo_le_as_fontes_das_obras_com_origem(monkeypatch):
    pedidos = []
    falsas = [{"membros": [("Web", "W-1"), ("Scholar", "A-1")]}, {"membros": [("Web", "W-2"), ("Web", "W-3"), ("Scholar", "A-2")]},
              {"membros": [("Scholar", "A-3")]}, {"membros": [("Web", "W-4")]}, {"membros": [("Web", "W-5")]}]
    monkeypatch.setattr(AV, "obras_com_origem", lambda lista: pedidos.append(lista) or (falsas, []))
    lista = _itens([_web(1)], [_art(9)])
    r = AV.resumo(lista)
    assert (r.get("n_obras_em_ambas"), r.get("n_obras_so_web"), r.get("n_obras_so_scholar")) == (2, 2, 1)
    assert pedidos == [lista]
    pedidos.clear()
    assert AV.resumo([]).get("n_obras_em_ambas") == 2 and len(pedidos) == 1        # uma leitura por chamada, também no vazio


def test_resumo_nao_muda_a_entrada():
    lista = _itens([_web(1, url_original="https://s.org/9")], [_art(9)])
    antes = copy.deepcopy(lista)
    AV.resumo(lista)
    assert lista == antes


# ================================================================ Análises: sobreposição em obras
REAL = {"n_itens": 720, "n_web": 199, "n_scholar": 521, "n_obras": 696, "n_em_ambas_fontes": 24, "n_ambas_por_url": 14,
        "n_ambas_so_por_titulo": 10, "n_triados": 720, "n_alta": 542, "n_fora": 48, "n_obras_em_ambas": 23,
        "n_obras_so_web": 175, "n_obras_so_scholar": 498}
PARES_REAL = [("Itens (web + Scholar)", "720"), ("Obras distintas", "696"), ("Obras nas duas fontes", "23"),
              ("Referências da web juntadas a um artigo", "24"), ("… pela URL", "14"), ("… só pelo título", "10")]
POUCO = "As duas fontes se sobrepõem pouco: poucas obras aparecem nas duas."
SO_TITULO = ("Antes de citar a sobreposição, confira à mão os pares achados só pelo título: títulos comuns podem juntar obras "
             "diferentes.")

# (descrição, mudanças no resumo, título, barras, texto)
SOBREPOSICAO_CASOS = [
    ("cópia de 23/10: 23 obras, 24 referências", {}, "696 obras distintas: 23 aparecem nas duas fontes",
     [("Só na web", 175), ("Só no Scholar", 498), ("Nas duas fontes", 23)], [POUCO, SO_TITULO]),
    ("uma obra nas duas fontes, duas referências", dict(n_obras=10, n_em_ambas_fontes=2, n_ambas_por_url=2, n_ambas_so_por_titulo=0,
                                                       n_obras_em_ambas=1, n_obras_so_web=4, n_obras_so_scholar=5),
     "10 obras distintas: 1 aparece nas duas fontes", [("Só na web", 4), ("Só no Scholar", 5), ("Nas duas fontes", 1)], [POUCO]),
    ("o limiar conta obras, não referências", dict(n_obras=10, n_em_ambas_fontes=5, n_ambas_por_url=5, n_ambas_so_por_titulo=0,
                                                   n_obras_em_ambas=1, n_obras_so_web=4, n_obras_so_scholar=5),
     "10 obras distintas: 1 aparece nas duas fontes", [("Só na web", 4), ("Só no Scholar", 5), ("Nas duas fontes", 1)], [POUCO]),
    ("no limiar exato (2 de 10 obras = 20%): não está abaixo",
     dict(n_obras=10, n_em_ambas_fontes=2, n_ambas_por_url=2, n_ambas_so_por_titulo=0, n_obras_em_ambas=2, n_obras_so_web=3,
          n_obras_so_scholar=5),
     "10 obras distintas: 2 aparecem nas duas fontes", [("Só na web", 3), ("Só no Scholar", 5), ("Nas duas fontes", 2)], []),
    ("acima do limiar em obras", dict(n_obras=10, n_em_ambas_fontes=3, n_ambas_por_url=3, n_ambas_so_por_titulo=0,
                                      n_obras_em_ambas=3, n_obras_so_web=2, n_obras_so_scholar=5),
     "10 obras distintas: 3 aparecem nas duas fontes", [("Só na web", 2), ("Só no Scholar", 5), ("Nas duas fontes", 3)], []),
    ("nenhuma obra nas duas fontes", dict(n_obras=720, n_em_ambas_fontes=0, n_ambas_por_url=0, n_ambas_so_por_titulo=0,
                                          n_obras_em_ambas=0, n_obras_so_web=199, n_obras_so_scholar=521),
     "720 obras distintas: 0 aparecem nas duas fontes", [("Só na web", 199), ("Só no Scholar", 521), ("Nas duas fontes", 0)],
     [POUCO]),
    ("milhar", dict(n_itens=3000, n_obras=2000, n_em_ambas_fontes=1000, n_ambas_por_url=1000, n_ambas_so_por_titulo=0,
                    n_obras_em_ambas=1000, n_obras_so_web=500, n_obras_so_scholar=500),
     "2.000 obras distintas: 1.000 aparecem nas duas fontes", [("Só na web", 500), ("Só no Scholar", 500), ("Nas duas fontes", 1000)],
     []),
]


@pytest.mark.parametrize("descricao, mudancas, titulo, barras, texto", SOBREPOSICAO_CASOS, ids=[c[0] for c in SOBREPOSICAO_CASOS])
def test_sobreposicao_em_obras(monkeypatch, descricao, mudancas, titulo, barras, texto):
    pedidas = []
    original = bv.graficos.barras_horizontais
    monkeypatch.setattr(bv.graficos, "barras_horizontais", lambda itens, *a, **k: pedidas.append(list(itens)) or original(itens, *a, **k))
    b = bv.bloco_sobreposicao({**REAL, **mudancas})
    assert b["titulo"] == titulo
    assert pedidas == [barras]
    assert b["texto"] == texto
    assert b["subtitulo"] == "mesma obra: URL normalizada igual ou título normalizado igual (D104)"


def test_sobreposicao_pares_com_as_duas_unidades():
    assert bv.bloco_sobreposicao(REAL)["pares"] == PARES_REAL


def test_sobreposicao_sem_itens_nao_muda():
    vazio = {k: 0 for k in REAL}
    assert bv.bloco_sobreposicao(vazio)["titulo"] == "Ainda não há itens da busca de viés algorítmico neste banco"


# ================================================================ Visão Geral: "Nas duas fontes" em obras
def test_visao_geral_nas_duas_fontes_conta_obras():
    av = {"n_itens": 200, "n_web": 120, "n_scholar": 80, "n_obras": 190, "n_em_ambas_fontes": 10, "n_triados": 180, "n_alta": 40,
          "n_fora": 60, "n_obras_em_ambas": 9, "n_obras_so_web": 110, "n_obras_so_scholar": 71}
    i = _ind(_bloco(VG.montar(_vies(av=av), ADMIN), "cobertura"))["n_em_ambas_fontes"]
    assert (i["rotulo"], i["valor"], i["definicao"]) == ("Nas duas fontes", 9,
                                                         "Obras encontradas na web e no Scholar (mesmo endereço ou mesmo título).")


# ================================================================ repetições do Scholar na mesma consulta, por causa
def _oc(artigo, chamada, consulta="LA1", filtro="so_portugues", pagina=1):
    return {"artigo_id": artigo, "chamada_id": chamada, "consulta_id": consulta, "filtro_idioma": filtro, "pagina": pagina}


def _rep(mesma, pagina, idioma):
    return {"mesma_chamada": mesma, "outra_pagina": pagina, "outro_idioma": idioma, "total": mesma + pagina + idioma}


# (descrição, ocorrências, resultado); cada chamada é uma página de uma consulta com um filtro
REPETICOES_CASOS = [
    ("vazio", [], _rep(0, 0, 0)),
    ("sem repetição", [_oc(1, 10), _oc(2, 10), _oc(3, 11, pagina=2)], _rep(0, 0, 0)),
    ("entre consultas não conta", [_oc(1, 10), _oc(1, 20, consulta="LB1")], _rep(0, 0, 0)),
    ("mesma chamada", [_oc(1, 10), _oc(1, 10)], _rep(1, 0, 0)),
    ("outra página, mesmo filtro", [_oc(1, 10), _oc(1, 11, pagina=2)], _rep(0, 1, 0)),
    ("outro filtro", [_oc(1, 10), _oc(1, 12, filtro="sem_filtro")], _rep(0, 0, 1)),
    ("outro filtro em outra página conta como idioma", [_oc(1, 10), _oc(1, 13, filtro="sem_filtro", pagina=3)], _rep(0, 0, 1)),
    ("as três causas no mesmo artigo", [_oc(1, 10), _oc(1, 10), _oc(1, 11, pagina=2), _oc(1, 12, filtro="sem_filtro")], _rep(1, 1, 1)),
    # só os dois valores do filtro de idioma (com e sem lr=lang_pt) definem a causa; qualquer outro valor, mesmo sem repetição,
    # deixa a divisão sem cálculo (D160)
    ("filtro 'outro' em repetição", [_oc(1, 10), _oc(1, 12, filtro="outro")], None),
    ("filtro 'outro' sem repetição", [_oc(1, 10), _oc(2, 12, filtro="outro")], None),
    *[(f"filtro {v!r}", [_oc(1, 10), _oc(2, 12, filtro=v)], None) for v in (None, "", "lang_pt", "SO_PORTUGUES")],
    ("ordem das linhas não importa", [_oc(1, 12, filtro="sem_filtro"), _oc(1, 11, pagina=2), _oc(1, 10), _oc(1, 10)], _rep(1, 1, 1)),
    ("três páginas", [_oc(1, 10), _oc(1, 11, pagina=2), _oc(1, 14, pagina=3)], _rep(0, 2, 0)),
    ("entre consultas e na mesma consulta", [_oc(1, 10), _oc(1, 20, consulta="LB1"), _oc(1, 21, consulta="LB1", pagina=2)], _rep(0, 1, 0)),
    # sem garantia de que cada chamada é uma página de uma consulta com um filtro, a divisão não é calculada
    ("chamada com duas consultas", [_oc(1, 10), _oc(2, 10, consulta="LB1")], None),
    ("chamada com dois filtros", [_oc(1, 10), _oc(2, 10, filtro="sem_filtro")], None),
    ("chamada com duas páginas", [_oc(1, 10), _oc(2, 10, pagina=2)], None),
    ("a mesma página pedida em duas chamadas", [_oc(1, 10), _oc(2, 15)], None),
]


@pytest.mark.parametrize("descricao, linhas, esperado", REPETICOES_CASOS, ids=[c[0] for c in REPETICOES_CASOS])
def test_repeticoes_na_mesma_consulta(descricao, linhas, esperado):
    assert hasattr(AV, "repeticoes_na_mesma_consulta"), "falta a decomposição das repetições"
    assert AV.repeticoes_na_mesma_consulta(copy.deepcopy(linhas)) == esperado


def test_repeticoes_na_mesma_consulta_nao_muda_a_entrada():
    linhas = [_oc(1, 10), _oc(1, 10), _oc(1, 11, pagina=2)]
    antes = copy.deepcopy(linhas)
    assert hasattr(AV, "repeticoes_na_mesma_consulta")
    AV.repeticoes_na_mesma_consulta(linhas)
    assert linhas == antes


def test_repeticoes_somam_a_diferenca_entre_registros_e_pares():
    """O total é sempre registros − pares (artigo, consulta), a mesma conta da caixa dos repetidos."""
    linhas = [_oc(1, 10), _oc(1, 10), _oc(1, 11, pagina=2), _oc(1, 12, filtro="sem_filtro"), _oc(2, 12, filtro="sem_filtro"),
              _oc(2, 20, consulta="LB1"), _oc(3, 20, consulta="LB1")]
    pares = len({(l["artigo_id"], l["consulta_id"]) for l in linhas})
    assert hasattr(AV, "repeticoes_na_mesma_consulta")
    assert AV.repeticoes_na_mesma_consulta(linhas)["total"] == len(linhas) - pares


# ================================================================ PRISMA do vies: leitura dos dados
class _LeituraFalsa:
    def __init__(self):
        self.chamadas = []

    def _anota(self, nome, valor):
        self.chamadas.append(nome)
        return valor

    def prisma(self):
        return self._anota("prisma", {"caixas": [{"ordem": 1}], "motivos": [], "n_buscas_manuais": 0, "n_buscas_scholar": 3})

    def literatura(self):
        return self._anota("literatura", {"por_termo": [{"termo_id": "LA1", "n_artigos": 7}, {"termo_id": "LB1", "n_artigos": 5}],
                                          "n_artigos": 999})

    def parametros_buscas_vies(self):
        return self._anota("parametros_buscas_vies", {"web": [{"run_id": "R1"}, {"run_id": "R2"}, {"run_id": "R1"}, {"run_id": None},
                                                              {"run_id": ""}],
                                                      "scholar": [{"run_id": "S"}] * 7})

    def ocorrencias_scholar_por_chamada(self):
        return self._anota("ocorrencias_scholar_por_chamada", [{"artigo_id": 1}])

    def analise_ferramentas(self):
        return self._anota("analise_ferramentas", {
            "chamadas": [{"etapa": "busca_literatura", "provedor": "p1", "chamadas": 12, "ok": 11},
                         {"etapa": "busca_literatura", "provedor": "p2", "chamadas": 8, "ok": 8},
                         {"etapa": "busca_academica", "provedor": "s", "chamadas": 77, "ok": 77},
                         {"etapa": "triagem_escopo", "provedor": "m", "chamadas": 114, "ok": 114}],
            "resultados": {"busca_literatura": 400, "busca_academica": 1288, "busca_web": 33}, "itens": {"busca_literatura": 5},
            "creditos": {}})


def test_dados_do_prisma_vies_montados_das_leituras(monkeypatch):
    pv = _pv()
    leitura, ctx = _LeituraFalsa(), object()
    lista = [{"id": "W-1"}]
    pedidos = []
    monkeypatch.setattr(visao_geral_vies, "itens", lambda l, c: pedidos.append((l, c)) or lista)
    monkeypatch.setattr(AV, "resumo", lambda l: {"resumo_de": l})
    monkeypatch.setattr(AV, "repeticoes_na_mesma_consulta", lambda linhas: {"repeticoes_de": linhas}, raising=False)
    d = pv.dados_vies(leitura, ctx)
    assert d == {"prisma": {"caixas": [{"ordem": 1}], "motivos": [], "n_buscas_manuais": 0, "n_buscas_scholar": 3},
                 "pares_artigo_consulta": 12,
                 "web": {"chamadas": 20, "ocorrencias": 400, "execucoes": 2},
                 "scholar_chamadas": 7,
                 "repeticoes": {"repeticoes_de": [{"artigo_id": 1}]},
                 "corpus": {"resumo_de": lista}}
    assert pedidos == [(leitura, ctx)]
    assert sorted(leitura.chamadas) == ["analise_ferramentas", "literatura", "ocorrencias_scholar_por_chamada",
                                        "parametros_buscas_vies", "prisma"]


def test_dados_do_prisma_vies_sem_busca_na_web(monkeypatch):
    pv = _pv()
    leitura = _LeituraFalsa()
    leitura.analise_ferramentas = lambda: {"chamadas": [], "resultados": {}, "itens": {}, "creditos": {}}
    leitura.literatura = lambda: {"por_termo": []}
    leitura.parametros_buscas_vies = lambda: {"web": [], "scholar": []}
    leitura.ocorrencias_scholar_por_chamada = lambda: []
    monkeypatch.setattr(visao_geral_vies, "itens", lambda l, c: [])
    d = pv.dados_vies(leitura, object())
    assert (d["web"], d["pares_artigo_consulta"], d.get("scholar_chamadas")) == ({"chamadas": 0, "ocorrencias": 0, "execucoes": 0}, 0, 0)
    assert d.get("repeticoes") == {"mesma_chamada": 0, "outra_pagina": 0, "outro_idioma": 0, "total": 0}


# ================================================================ PRISMA do vies: caixas
# a view `v_prisma` da cópia do `vies` de 23/10/2026 (consultada em modo só leitura)
VPRISMA = [
    (1, "identificacao", "execucoes de busca academica", 4),
    (2, "identificacao", "Google Scholar: registros retornados", 1288),
    (3, "identificacao", "buscas manuais: registros retornados (contagem informada)", 0),
    (4, "identificacao", "Google Scholar: duplicatas entre termos removidas", 767),
    (5, "identificacao", "Google Scholar: artigos unicos", 521),
    (6, "identificacao", "buscas manuais: apos filtro da base (contagem informada)", 0),
    (7, "identificacao", "buscas manuais: selecionados (contagem informada)", 0),
    (8, "identificacao", "buscas manuais: artigos importados (por base)", 0),
    (9, "identificacao", "registros (artigo x fonte) apos remover duplicatas entre termos", 521),
    (10, "identificacao", "duplicatas entre fontes removidas", 0),
    (11, "identificacao", "removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)", 48),
    (12, "triagem", "artigos unicos para triagem", 473),
    (13, "triagem", "avaliados por titulo e resumo", 0),
    (14, "triagem", "excluidos por titulo e resumo", 0),
    (15, "triagem", "incluidos por titulo e resumo", 0),
    (16, "triagem", "pendentes de titulo e resumo", 473),
    (17, "elegibilidade", "avaliados por texto completo", 0),
    (18, "elegibilidade", "excluidos por texto completo", 0),
    (19, "elegibilidade", "aguardando texto completo", 0),
    (20, "inclusao", "incluidos no estudo (texto completo)", 0),
]
CORPUS = {"n_itens": 720, "n_web": 199, "n_scholar": 521, "n_obras": 696, "n_em_ambas_fontes": 24, "n_ambas_por_url": 14,
          "n_ambas_so_por_titulo": 10, "n_triados": 720, "n_alta": 542, "n_fora": 48, "n_obras_em_ambas": 23,
          "n_obras_so_web": 175, "n_obras_so_scholar": 498}

REPETICOES = {"mesma_chamada": 5, "outra_pagina": 133, "outro_idioma": 245, "total": 383}


def _dados(**mudancas):
    d = {"prisma": {"caixas": [{"ordem": o, "fase": f, "metrica": m, "valor": v} for o, f, m, v in VPRISMA],
                    "motivos": [], "n_buscas_manuais": 0, "n_buscas_scholar": 77},
         "pares_artigo_consulta": 905, "web": {"chamadas": 20, "ocorrencias": 400, "execucoes": 3}, "scholar_chamadas": 77,
         "repeticoes": dict(REPETICOES), "corpus": dict(CORPUS)}
    d.update(mudancas)
    return d


ORIGEM = "origem: v_prisma"
MODELO = "origem: v_prisma · triagem de escopo do modelo, só com confiança alta; decisão humana sempre vence"


def _repetidos(entre, mesmo, veja=True):
    return (f"origem: v_prisma · registros de um artigo já devolvido por outra consulta: {entre} · registros devolvidos de novo "
            f"pela mesma consulta: {mesmo}" + (" (veja abaixo do fluxo)" if veja else ""))


REPETIDOS = _repetidos("384", "383")
NOTA_TRIAGEM = ("Só os artigos do Google Scholar seguem para a triagem humana. As referências da web recebem só a triagem de escopo "
                "do modelo e não passam por triagem humana no procedimento atualmente documentado.")
DA_WEB = "origem: chamadas da busca na web"
DAS_DUAS = "origem: referências da web e artigos do Scholar"
JUNTADAS = "origem: chamadas da busca na web e referências da web"
LIMITES = "junção automática, não conferida por pessoas; os limites estão na Metodologia (Deduplicação e limites)"


def _nota_obras(itens, refs):
    return f"{DAS_DUAS} · itens das duas fontes: {itens} · referências da web juntadas a um artigo do Scholar: {refs} · {LIMITES}"


POR_CAUSA = ["na mesma consulta com a outra configuração de idioma (com e sem o parâmetro de idioma português): 245;",
             "em outra página de resultados da mesma consulta, com a mesma configuração: 133;",
             "na mesma chamada (dois resultados com o mesmo título normalizado): 5;",
             "total: 383."]


def _cx(rotulo, valor, nota=ORIGEM, especial=False, link=False):
    return {"rotulo": rotulo, "valor": valor, "especial": especial, "nota": nota, "link_triagem": link}


NA = "não se aplica"
ESCOLAR = [
    _cx("execuções de busca acadêmica", "4", "origem: v_prisma · em 77 chamadas"),
    _cx("Google Scholar: ocorrências devolvidas", "1.288"),
    _cx("buscas manuais: registros retornados (contagem informada)", NA, especial=True),
    _cx("Google Scholar: registros repetidos removidos", "767", REPETIDOS),
    _cx("Google Scholar: artigos únicos", "521"),
    _cx("buscas manuais: após filtro da base (contagem informada)", NA, especial=True),
    _cx("buscas manuais: selecionados (contagem informada)", NA, especial=True),
    _cx("buscas manuais: artigos importados (por base)", NA, especial=True),
    _cx("Google Scholar: artigos após remover todos os registros repetidos (a mesma contagem dos artigos únicos)", "521"),
    _cx("duplicatas entre o Google Scholar e as bases manuais removidas", NA, especial=True),
    _cx("removidos por ferramenta automática (triagem de escopo do modelo, sem decisão humana)", "48", MODELO, link=True),
]
WEB = [
    _cx("busca na web: chamadas", "20", f"{DA_WEB} · em 3 execuções"),
    _cx("busca na web: ocorrências devolvidas", "400", DA_WEB),
    _cx("busca na web: ocorrências repetidas juntadas", "201", JUNTADAS),
    _cx("busca na web: referências únicas (por endereço normalizado)", "199", "origem: referências da web, as mesmas da Visão Geral"),
    _cx("referências da web que repetem um artigo do Scholar", "24",
        f"{DAS_DUAS} · pelo endereço: 14 · só pelo título: 10 · obras correspondentes: 23"),
    _cx("obras distintas (artigos do Scholar e referências da web)", "696", _nota_obras("720", "24")),
]
TRIAGEM = [_cx("artigos únicos para triagem", "473"), _cx("avaliados por título e resumo", "0"),
           _cx("excluídos por título e resumo", "0"), _cx("incluídos por título e resumo", "0"),
           _cx("pendentes de título e resumo", "473")]
ELEGIBILIDADE = [_cx("avaliados por texto completo", "0"), _cx("excluídos por texto completo", "0"),
                 _cx("aguardando texto completo", "0")]
INCLUSAO = [_cx("incluídos no estudo (texto completo)", "0")]


def _fase(id_, titulo, caixas, nota=None):
    return {"id": id_, "titulo": titulo, "nota": nota, "caixas": caixas}


FASES = [_fase("identificacao", "Identificação: Google Scholar", ESCOLAR), _fase("web", "Identificação e organização: busca na web e obras", WEB),
         _fase("triagem", "Triagem (título e resumo)", TRIAGEM, NOTA_TRIAGEM),
         _fase("elegibilidade", "Elegibilidade (texto completo)", ELEGIBILIDADE), _fase("inclusao", "Inclusão", INCLUSAO)]


def _troca(fases, fase, indice, **campos):
    saida = copy.deepcopy(fases)
    alvo = next(f for f in saida if f["id"] == fase)
    alvo["caixas"][indice] = {**alvo["caixas"][indice], **campos}
    return saida


def test_prisma_vies_para_quem_entrou():
    assert _pv().montar_prisma_vies(_dados()) == {"fases": FASES, "motivos": [], "repetidos_por_causa": POR_CAUSA}


def test_prisma_vies_ocultos_padrao_vazio():
    pv = _pv()
    assert pv.montar_prisma_vies(_dados()) == pv.montar_prisma_vies(_dados(), frozenset())


def _visitante(fases):
    nd = dict(valor="não divulgado", especial=True)
    f = _troca(fases, "identificacao", 10, **nd)
    f = _troca(f, "triagem", 0, **nd)
    return _troca(f, "triagem", 4, **nd)


def _sem_scholar(fases):
    ne = dict(valor="não executado", especial=True)
    f = _troca(fases, "identificacao", 0, nota=ORIGEM, **ne)
    for i in (1, 4):
        f = _troca(f, "identificacao", i, **ne)
    return _troca(f, "identificacao", 3, nota=ORIGEM, **ne)


def _sem_web(fases):
    f = _troca(fases, "web", 0, nota=DA_WEB, valor="não executado", especial=True)
    for i in (1, 2, 3, 4):
        f = _troca(f, "web", i, valor="não executado", especial=True)
    return f


def _sem_divisao(fases):
    return _troca(fases, "identificacao", 3, nota=ORIGEM)


def _caixa_com(valores):
    return [{"ordem": o, "fase": f, "metrica": m, "valor": valores.get(o, v)} for o, f, m, v in VPRISMA]


# (descrição, dados, ocultos, fases esperadas)
CAIXAS_CASOS = [
    ("visitante: as três caixas do modelo", _dados(), frozenset(DO_MODELO), _visitante(FASES)),
    ("Scholar não executado", _dados(prisma={**_dados()["prisma"], "n_buscas_scholar": 0}), frozenset(), _sem_scholar(FASES)),
    ("visitante e Scholar não executado", _dados(prisma={**_dados()["prisma"], "n_buscas_scholar": 0}), frozenset(DO_MODELO),
     _sem_scholar(_visitante(FASES))),
    ("web não executada", _dados(web={"chamadas": 0, "ocorrencias": 0}), frozenset(), _sem_web(FASES)),
    ("web sem a chave das chamadas", _dados(web={}), frozenset(), _sem_web(FASES)),
    ("pares menores que os artigos (leituras incoerentes): sem a divisão", _dados(pares_artigo_consulta=500), frozenset(),
     _sem_divisao(FASES)),
    ("pares acima dos registros (leituras incoerentes): sem a divisão", _dados(pares_artigo_consulta=1289), frozenset(),
     _sem_divisao(FASES)),
    ("sem os pares: sem a divisão", _dados(pares_artigo_consulta=None), frozenset(), _sem_divisao(FASES)),
    ("divisão com zero de um lado", _dados(pares_artigo_consulta=521), frozenset(),
     _troca(FASES, "identificacao", 3, nota=_repetidos("0", "767", veja=False))),
    ("milhar na divisão e nas caixas",
     _dados(prisma={**_dados()["prisma"], "caixas": _caixa_com({2: 12880, 4: 11767, 5: 1113, 9: 1113})},
            pares_artigo_consulta=3113, scholar_chamadas=1500, web={"chamadas": 2000, "ocorrencias": 40000, "execucoes": 1000}),
     frozenset(),
     _troca(_troca(_troca(_troca(_troca(_troca(_troca(_troca(
         FASES, "identificacao", 1, valor="12.880"), "identificacao", 4, valor="1.113"), "identificacao", 8, valor="1.113"),
         "identificacao", 3, valor="11.767", nota=_repetidos("2.000", "9.767", veja=False)),
         "identificacao", 0, nota="origem: v_prisma · em 1.500 chamadas"),
         "web", 0, valor="2.000", nota=f"{DA_WEB} · em 1.000 execuções"), "web", 1, valor="40.000"), "web", 2, valor="39.801")),
    ("web com valores None: chamadas None vale 0 (não executada)", _dados(web={"chamadas": None, "ocorrencias": None}), frozenset(),
     _sem_web(FASES)),
    ("web com ocorrências None: juntadas não calculadas", _dados(web={"chamadas": 20, "ocorrencias": None, "execucoes": 3}), frozenset(),
     _troca(_troca(FASES, "web", 1, valor="0"), "web", 2, valor="não calculado", especial=True)),
    ("ocorrências abaixo das referências: juntadas não calculadas", _dados(web={"chamadas": 20, "ocorrencias": 198, "execucoes": 3}),
     frozenset(), _troca(_troca(FASES, "web", 1, valor="198"), "web", 2, valor="não calculado", especial=True)),
    ("ocorrências iguais às referências: nenhuma juntada", _dados(web={"chamadas": 20, "ocorrencias": 199, "execucoes": 3}),
     frozenset(), _troca(_troca(FASES, "web", 1, valor="199"), "web", 2, valor="0")),
    ("uma execução da web", _dados(web={"chamadas": 20, "ocorrencias": 400, "execucoes": 1}), frozenset(),
     _troca(FASES, "web", 0, nota=f"{DA_WEB} · em 1 execução")),
    *[(f"execuções da web {v!r}: sem a nota", _dados(web={"chamadas": 20, "ocorrencias": 400, "execucoes": v}), frozenset(),
       _troca(FASES, "web", 0, nota=DA_WEB)) for v in (0, None)],
    ("execuções da web ausentes: sem a nota", _dados(web={"chamadas": 20, "ocorrencias": 400}), frozenset(),
     _troca(FASES, "web", 0, nota=DA_WEB)),
    ("uma chamada do Scholar", _dados(scholar_chamadas=1), frozenset(),
     _troca(FASES, "identificacao", 0, nota="origem: v_prisma · em 1 chamada")),
    *[(f"chamadas do Scholar {v!r}: sem a nota", _dados(scholar_chamadas=v), frozenset(), _troca(FASES, "identificacao", 0, nota=ORIGEM))
      for v in (0, None)],
    ("repetições sem a divisão por causa", _dados(repeticoes=None), frozenset(), _troca(FASES, "identificacao", 3, nota=_repetidos("384", "383", veja=False))),
    ("divisão por causa com outro total", _dados(repeticoes={**REPETICOES, "total": 382}), frozenset(),
     _troca(FASES, "identificacao", 3, nota=_repetidos("384", "383", veja=False))),
    ("visitante vê a divisão por causa", _dados(), frozenset(DO_MODELO), _visitante(FASES)),
    ("corpus com valores None", _dados(corpus={k: None for k in CORPUS}), frozenset(),
     _troca(_troca(_troca(_troca(FASES, "web", 2, valor="400"), "web", 3, valor="0"), "web", 4, valor="0",
                   nota=f"{DAS_DUAS} · pelo endereço: 0 · só pelo título: 0 · obras correspondentes: 0"),
            "web", 5, valor="0", nota=_nota_obras("0", "0"))),
    ("corpus com algumas contagens None", _dados(corpus={**CORPUS, "n_ambas_por_url": None, "n_obras_em_ambas": None, "n_itens": None}),
     frozenset(),
     _troca(_troca(FASES, "web", 4, nota=f"{DAS_DUAS} · pelo endereço: 0 · só pelo título: 10 · obras correspondentes: 0"),
            "web", 5, nota=_nota_obras("0", "24"))),
    ("corpus vazio", _dados(corpus={}), frozenset(),
     _troca(_troca(_troca(_troca(FASES, "web", 2, valor="400"), "web", 3, valor="0"), "web", 4, valor="0",
                   nota=f"{DAS_DUAS} · pelo endereço: 0 · só pelo título: 0 · obras correspondentes: 0"),
            "web", 5, valor="0", nota=_nota_obras("0", "0"))),
]


# (descrição, dados, lista esperada das repetições por causa)
POR_CAUSA_CASOS = [
    ("igual à divisão", _dados(), POR_CAUSA),
    ("visitante igual", _dados(), POR_CAUSA),
    ("sem as repetições", _dados(repeticoes=None), None),
    ("total diferente da caixa", _dados(repeticoes={**REPETICOES, "total": 384}), None),
    ("sem a divisão da caixa", _dados(pares_artigo_consulta=None), None),
    ("Scholar não executado", _dados(prisma={**_dados()["prisma"], "n_buscas_scholar": 0}), None),
    ("nenhuma repetição na mesma consulta", _dados(prisma={**_dados()["prisma"], "caixas": _caixa_com({4: 384})}, pares_artigo_consulta=905,
                                                  repeticoes={"mesma_chamada": 0, "outra_pagina": 0, "outro_idioma": 0, "total": 0}), None),
    ("milhar", _dados(prisma={**_dados()["prisma"], "caixas": _caixa_com({2: 12880, 4: 11767, 5: 1113, 9: 1113})},
                      pares_artigo_consulta=3113, repeticoes={"mesma_chamada": 1, "outra_pagina": 2000, "outro_idioma": 7766, "total": 9767}),
     ["na mesma consulta com a outra configuração de idioma (com e sem o parâmetro de idioma português): 7.766;",
      "em outra página de resultados da mesma consulta, com a mesma configuração: 2.000;",
      "na mesma chamada (dois resultados com o mesmo título normalizado): 1;", "total: 9.767."]),
]


@pytest.mark.parametrize("descricao, dados, esperado", POR_CAUSA_CASOS, ids=[c[0] for c in POR_CAUSA_CASOS])
def test_prisma_vies_repetidos_por_causa(descricao, dados, esperado):
    ocultos = frozenset(DO_MODELO) if descricao.startswith("visitante") else frozenset()
    assert _pv().montar_prisma_vies(dados, ocultos).get("repetidos_por_causa", "ausente") == esperado


@pytest.mark.parametrize("descricao, dados, ocultos, esperado", CAIXAS_CASOS, ids=[c[0] for c in CAIXAS_CASOS])
def test_prisma_vies_caixas(descricao, dados, ocultos, esperado):
    assert _pv().montar_prisma_vies(dados, ocultos)["fases"] == esperado


def test_prisma_vies_manual_informado_continua_nao_se_aplica():
    """Mesmo com números de buscas manuais no banco, no `vies` as caixas das bases manuais dizem "não se aplica"."""
    d = _dados(prisma={**_dados()["prisma"], "caixas": _caixa_com({3: 50, 6: 40, 7: 30, 8: 20, 10: 5}), "n_buscas_manuais": 2})
    assert _pv().montar_prisma_vies(d)["fases"] == FASES


def test_prisma_vies_manual_do_visitante_nao_se_aplica():
    caixas = {c["rotulo"]: c["valor"] for f in _pv().montar_prisma_vies(_dados(), frozenset(DO_MODELO))["fases"] for c in f["caixas"]}
    assert [v for k, v in caixas.items() if k.startswith("buscas manuais")] == [NA] * 4


def test_prisma_vies_numeracao_da_view_preservada():
    """As caixas da view saem na ordem de `ordem`, com a mesma métrica: a web entra como fase própria, sem renumerar a view."""
    fases = _pv().montar_prisma_vies(_dados())["fases"]
    da_view = [c["rotulo"] for f in fases if f["id"] != "web" for c in f["caixas"]]
    rotulo = {m: rotulos.rotulo(rotulos.PRISMA, m) for _, _, m, _ in VPRISMA}
    rotulo["Google Scholar: duplicatas entre termos removidas"] = "Google Scholar: registros repetidos removidos"
    rotulo["registros (artigo x fonte) apos remover duplicatas entre termos"] = (
        "Google Scholar: artigos após remover todos os registros repetidos (a mesma contagem dos artigos únicos)")
    rotulo["duplicatas entre fontes removidas"] = "duplicatas entre o Google Scholar e as bases manuais removidas"
    rotulo["Google Scholar: registros retornados"] = "Google Scholar: ocorrências devolvidas"
    assert da_view == [rotulo[m] for _, _, m, _ in VPRISMA]


def test_prisma_vies_web_logo_depois_da_identificacao_ou_no_comeco():
    pv = _pv()
    so_triagem = _dados(prisma={**_dados()["prisma"], "caixas": [{"ordem": 12, "fase": "triagem", "metrica": "artigos unicos para triagem",
                                                                    "valor": 3}]})
    assert [f["id"] for f in pv.montar_prisma_vies(so_triagem)["fases"]] == ["web", "triagem"]
    outra = _dados(prisma={**_dados()["prisma"], "caixas": [{"ordem": 1, "fase": "outra_fase", "metrica": "x", "valor": 1},
                                                              {"ordem": 2, "fase": "identificacao", "metrica": "y", "valor": 2}]})
    fases = pv.montar_prisma_vies(outra)["fases"]
    assert [(f["id"], f["titulo"]) for f in fases] == [("outra_fase", "outra_fase"), ("identificacao", "Identificação: Google Scholar"),
                                                        ("web", "Identificação e organização: busca na web e obras")]
    assert fases[0]["caixas"] == [_cx("x", "1")]
    vazio = pv.montar_prisma_vies(_dados(prisma={**_dados()["prisma"], "caixas": []}))
    assert [f["id"] for f in vazio["fases"]] == ["web"]


def test_prisma_vies_motivos_como_lidos():
    motivos = [{"etapa": "titulo_resumo", "motivo": "fora do tema", "n": 3}]
    assert _pv().montar_prisma_vies(_dados(prisma={**_dados()["prisma"], "motivos": motivos}))["motivos"] == motivos


def test_prisma_vies_nao_muda_a_entrada():
    d = _dados()
    antes = copy.deepcopy(d)
    _pv().montar_prisma_vies(d, frozenset(DO_MODELO))
    assert d == antes


def test_prisma_vies_divisao_soma_as_duplicatas_da_view():
    """A divisão dos registros repetidos soma o número da caixa 4 da view (767 = 384 + 383)."""
    nota = _pv().montar_prisma_vies(_dados())["fases"][0]["caixas"][3]["nota"]
    entre, mesmo = (int(x.replace(".", "")) for x in re.findall(r": ([\d.]+)", nota))
    assert sum(v for k, v in REPETICOES.items() if k != "total") == REPETICOES["total"] == mesmo
    assert entre + mesmo == 767 == 1288 - 521


# ================================================================ PRISMA do vies: página
INTRO = [
    '<p><strong>O que é este fluxo.</strong> PRISMA (<em>Preferred Reporting Items for Systematic Reviews and Meta-Analyses</em>) é '
    "uma diretriz para relatar com transparência como os estudos de uma revisão foram encontrados, organizados, triados e "
    "selecionados. Não é um algoritmo de classificação nem uma garantia de qualidade científica: o fluxograma só mostra quantos "
    "registros passaram por cada etapa e quantos saíram em cada uma.</p>",
    "<p><strong>O que ele cobre aqui.</strong> Este fluxo é uma adaptação da estrutura do PRISMA a duas origens, contadas "
    "separadamente: artigos do Google Scholar e referências encontradas pela busca na web. Uma referência da web que repete um "
    "artigo do Scholar conta uma só vez como obra (uma referência que coincide com mais de um artigo não é juntada a nenhum). A pesquisa ainda não é uma revisão sistemática concluída: as referências da web "
    "não passam por triagem humana no procedimento atualmente documentado, e as etapas sem decisões registradas aparecem como tal.</p>",
    "<p><strong>Como ler os números.</strong> Cada caixa diz o que conta (ocorrência devolvida pela busca, chamada, artigo único, "
    "referência, obra) e de qual origem; números de unidades diferentes não se somam. As etapas marcadas “triagem de escopo do modelo” foram "
    "feitas por um modelo de linguagem e não são decisões de pesquisadores. Avaliados, excluídos e incluídos contam só decisões "
    "registradas por pessoas; “artigos únicos para triagem” e “pendentes” já descontam os artigos removidos pelo modelo. O que não se aplica a esta pesquisa aparece escrito assim, nunca como zero.</p>",
]
INTRO_HTML = '<section class="cartao" aria-label="Sobre este fluxo">\n' + "\n".join(INTRO) + "\n</section>"
RODAPE = ("<p><small>Removidos por ferramenta automática: artigos retirados do fluxo de triagem pela classificação automatizada de "
          "escopo, conforme as regras desta pesquisa, apresentados separadamente neste fluxograma adaptado ao PRISMA 2020. A retirada "
          "exige que o modelo ponha o artigo fora do escopo com confiança alta (veredito atual válido) e que nenhuma pessoa tenha "
          "decidido sobre ele. Nada é apagado; se uma pessoa decidir sobre um deles, ele volta ao fluxo humano e deixa de contar "
          "aqui.</small></p>")
RODAPE_ANTIGO = ("<p><small>Removidos por ferramenta automática: artigos que a triagem de escopo do modelo excluiu (veredito atual "
                 "válido) e sobre os quais nenhuma pessoa decidiu. Nada é apagado; se uma pessoa decidir sobre um deles, ele volta ao "
                 "fluxo humano e deixa de contar aqui. A triagem de escopo não é uma etapa do PRISMA por si só: ela entra como "
                 "registros removidos por ferramenta de automação, como pede o PRISMA 2020.</small></p>")
DETALHES = ('<details class="acordeao-metodologico guia-metodologico"><summary>Por que a mesma consulta devolve o mesmo artigo de '
            'novo</summary><div class="acordeao-corpo"><p>Registros que a mesma consulta devolveu de novo, por causa (as causas não '
            'se sobrepõem):</p><ul class="lista-simples">{}</ul></div></details>')


def _detalhes(itens):
    return DETALHES.format("".join(f"<li>{t}</li>" for t in itens))
FORA_DO_VIES = ["view <code>v_prisma</code>", "você informou", "Confira as buscas manuais", "O que o fluxo ainda não sabe",
                "contagem informada por você", "não informado", "Google Scholar: duplicatas entre termos removidas",
                "como pede o PRISMA 2020", "ainda não passam", "Google Scholar: registros retornados"]
TITULOS_FASES = ["Identificação: Google Scholar", "Identificação e organização: busca na web e obras", "Triagem (título e resumo)",
                 "Elegibilidade (texto completo)", "Inclusão"]


def _fases_da_pagina(main):
    return re.findall(r'<section class="cartao prisma-fase" aria-label="([^"]+)"><h2>([^<]+)</h2>', main)


@pytest.fixture
def banco_vies(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    return tmp_path / "busca.db"


def test_pagina_do_vies_com_a_introducao_e_o_braco_da_web(banco_vies, tmp_path):
    r = _cli(banco_vies, tmp_path).get("/literatura/prisma")
    assert r.status_code == 200
    main = _main(r.text)
    assert "<h1>Fluxo PRISMA</h1>\n" + INTRO_HTML in main
    assert main.index("<h1>Fluxo PRISMA</h1>") < main.index(INTRO_HTML) < main.index('<div class="prisma">')
    assert _fases_da_pagina(main) == [(t, t) for t in TITULOS_FASES]
    assert f'<p class="sub">{NOTA_TRIAGEM}</p>' in main
    assert RODAPE in main
    for trecho in FORA_DO_VIES:
        assert trecho not in main, trecho
    assert AVISO not in main


def test_pagina_do_vies_com_os_numeros_das_leituras(banco_vies, tmp_path):
    """No banco de teste: 3 chamadas da web, 6 ocorrências, 4 referências; 1 artigo do Scholar; nenhuma junção."""
    caixas = _caixas(_cli(banco_vies, tmp_path).get("/literatura/prisma").text)
    assert {k: caixas.get(k) for k in [c["rotulo"] for c in WEB]} == {
        "busca na web: chamadas": "3", "busca na web: ocorrências devolvidas": "6",
        "busca na web: ocorrências repetidas juntadas": "2",
        "busca na web: referências únicas (por endereço normalizado)": "4",
        "referências da web que repetem um artigo do Scholar": "0",
        "obras distintas (artigos do Scholar e referências da web)": "5"}
    assert [caixas[k] for k in caixas if k.startswith("buscas manuais") or k == "duplicatas entre o Google Scholar e as bases manuais removidas"] == [
        '<span class="nd">não se aplica</span>'] * 5
    assert caixas.get("Google Scholar: registros repetidos removidos") == "0"
    assert len(caixas) == 26


def test_pagina_do_vies_usa_o_mesmo_resumo_da_visao_geral(banco_vies, tmp_path, monkeypatch):
    marcado = {**CORPUS, "n_web": 4321, "n_obras": 8765, "n_em_ambas_fontes": 1234, "n_obras_em_ambas": 1111}
    monkeypatch.setattr(AV, "resumo", lambda lista: dict(marcado))
    caixas = _caixas(_cli(banco_vies, tmp_path).get("/literatura/prisma").text)
    assert (caixas.get("busca na web: referências únicas (por endereço normalizado)"),
            caixas.get("referências da web que repetem um artigo do Scholar"),
            caixas.get("obras distintas (artigos do Scholar e referências da web)")) == ("4.321", "1.234", "8.765")


def test_pagina_do_vies_setas_so_entre_etapas(banco_vies, tmp_path):
    main = _main(_cli(banco_vies, tmp_path).get("/literatura/prisma").text)
    trecho = main.split('<div class="prisma">', 1)[1].split("<p><small>Removidos", 1)[0]
    setas = ['<div class="seta-prisma" aria-hidden="true">▼</div>' in b for b in re.split(r'<section class="cartao prisma-fase"', trecho)[1:]]
    assert setas == [False, True, True, True, False]   # nenhuma entre os dois braços da identificação nem depois da inclusão
    blocos = re.split(r'<section class="cartao prisma-fase"', trecho)[1:]
    assert trecho.count(LEGENDA_SETA_WEB) == 1 and LEGENDA_SETA_WEB in blocos[1]
    assert blocos[1].index('<div class="seta-prisma" aria-hidden="true">▼</div>') < blocos[1].index(LEGENDA_SETA_WEB)


LEGENDA_SETA_WEB = ('<p class="sub">Seguem para a triagem só os artigos do Google Scholar; as referências da web ficam na '
                    'identificação e na organização.</p>')


def test_pagina_do_vies_divisao_dos_repetidos_no_banco(tmp_path):
    """Um artigo achado por duas consultas e repetido na mesma consulta: 1 entre consultas e 1 na mesma consulta."""
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    con = sqlite3.connect(tmp_path / "busca.db")
    o = con.execute("SELECT chamada_id, artigo_id, termo_id, run_id FROM ocorrencias LIMIT 1").fetchone()
    con.execute("INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?, ?, ?, ?, 2)", o)
    con.execute("INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?, ?, 'LA1', ?, 3)",
                (o[0], o[1], o[3]))
    con.commit()
    con.close()
    html = _cli(tmp_path / "busca.db", tmp_path).get("/literatura/prisma").text
    # a mesma chamada passa a ter duas consultas: a divisão por causa não é calculada
    assert f"<span>Google Scholar: registros repetidos removidos<br><small>{_repetidos('1', '1', veja=False)}</small>" in html
    assert _caixas(html).get("Google Scholar: registros repetidos removidos") == "2"
    assert "Por que a mesma consulta devolve" not in html


SCH = '{"engine": "google_scholar", "hl": "pt", "num": 20, "q": "q", "start": 0'


def _banco_com_as_tres_causas(tmp_path):
    """O artigo da única chamada do Scholar (LB1, com filtro, página 1) volta: de novo na mesma chamada, na página 2 com o
    mesmo filtro e na página 1 sem filtro; e uma execução fora do relatório traz o mesmo artigo de novo (não conta)."""
    caminho = tmp_path / "busca.db"
    construir_vies(caminho, tmp_path / "raw")
    con = sqlite3.connect(caminho)
    ch, art, termo, run = con.execute("SELECT o.chamada_id, o.artigo_id, o.termo_id, o.run_id FROM ocorrencias o "
                                      "ORDER BY o.ocorrencia_id LIMIT 1").fetchone()
    con.execute("UPDATE chamadas SET parametros_json = ? WHERE chamada_id = ?", (SCH + ', "lr": "lang_pt"}', ch))
    colunas = "run_id, etapa, provedor, alvo_tipo, alvo_id, pagina, parametros_json, chave_idempotencia, requisitado_em, sucesso"
    novas = {}
    for chave, r_, pagina, params in (("p2", run, 2, SCH + ', "lr": "lang_pt"}'), ("sem", run, 1, SCH + "}"),
                                      ("fora", "RFORA", 3, SCH + "}")):
        if r_ == "RFORA":
            con.execute("INSERT INTO execucoes (run_id, iniciado_em, comando, config_hash, config_json, status, no_relatorio) "
                        "VALUES ('RFORA', '2026-11-01T09:00:00+00:00', 'academico', 'h', '{}', 'concluida', 0)")
        cur = con.execute(f"INSERT INTO chamadas ({colunas}) VALUES (?, 'busca_academica', 'falso', 'termo', ?, ?, ?, ?, "
                          "'2026-11-01T10:00:00+00:00', 1)", (r_, termo, pagina, params, f"k-{chave}"))
        novas[chave] = cur.lastrowid
    for chamada, r_, pos in ((ch, run, 7), (novas["p2"], run, 1), (novas["sem"], run, 1), (novas["fora"], "RFORA", 1)):
        con.execute("INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?, ?, ?, ?, ?)",
                    (chamada, art, termo, r_, pos))
    con.commit()
    con.close()
    return caminho, (ch, novas, art, termo)


def test_leitura_das_ocorrencias_do_scholar_por_chamada(tmp_path):
    caminho, (ch, novas, art, termo) = _banco_com_as_tres_causas(tmp_path)
    assert hasattr(LeituraPainelSQLite, "ocorrencias_scholar_por_chamada"), "falta a leitura das ocorrências do Scholar por chamada"
    assert LeituraPainelSQLite(caminho).ocorrencias_scholar_por_chamada() == [
        {"artigo_id": art, "chamada_id": ch, "consulta_id": termo, "filtro_idioma": "so_portugues", "pagina": 1},
        {"artigo_id": art, "chamada_id": ch, "consulta_id": termo, "filtro_idioma": "so_portugues", "pagina": 1},
        {"artigo_id": art, "chamada_id": novas["p2"], "consulta_id": termo, "filtro_idioma": "so_portugues", "pagina": 2},
        {"artigo_id": art, "chamada_id": novas["sem"], "consulta_id": termo, "filtro_idioma": "sem_filtro", "pagina": 1}]


def test_leitura_das_ocorrencias_sem_as_tabelas(tmp_path):
    sqlite3.connect(tmp_path / "vazio.db").execute("CREATE TABLE x (a)")
    assert hasattr(LeituraPainelSQLite, "ocorrencias_scholar_por_chamada")
    assert LeituraPainelSQLite(tmp_path / "vazio.db").ocorrencias_scholar_por_chamada() == []


def test_leitura_das_ocorrencias_usa_o_filtro_do_adaptador(tmp_path, monkeypatch):
    import adaptadores.leitura_sqlite as LS
    caminho, _ = _banco_com_as_tres_causas(tmp_path)
    assert hasattr(LeituraPainelSQLite, "ocorrencias_scholar_por_chamada")
    monkeypatch.setattr(LS, "_idioma_da_chamada", lambda raw: "marcado")
    assert {l["filtro_idioma"] for l in LeituraPainelSQLite(caminho).ocorrencias_scholar_por_chamada()} == {"marcado"}


def test_pagina_do_vies_com_as_repeticoes_por_causa(tmp_path):
    caminho, _ = _banco_com_as_tres_causas(tmp_path)
    for cli in (_cli(caminho, tmp_path),):
        main = _main(cli.get("/literatura/prisma").text)
        assert f"<span>Google Scholar: registros repetidos removidos<br><small>{_repetidos('0', '3')}</small>" in main
        assert main.count(_detalhes(["na mesma consulta com a outra configuração de idioma (com e sem o parâmetro de idioma "
                                     "português): 1;",
                                     "em outra página de resultados da mesma consulta, com a mesma configuração: 1;",
                                     "na mesma chamada (dois resultados com o mesmo título normalizado): 1;", "total: 3."])) == 1
        assert main.index('<div class="prisma">') < main.index("<details") < main.index(RODAPE)


def test_pagina_do_vies_sem_repeticoes_sem_explicacao(banco_vies, tmp_path):
    main = _main(_cli(banco_vies, tmp_path).get("/literatura/prisma").text)
    assert "<details" not in main


def test_visitante_no_vies_com_o_braco_da_web_e_sem_os_numeros_do_modelo(demo, tmp_path):  # noqa: F811
    app, contas, contas_db, copia = _painel(demo, tmp_path, banco="vies")
    _com_removidos_pelo_modelo(copia)
    gravar_politica(contas, "vies")
    r = TestClient(app).get("/literatura/prisma", follow_redirects=False)
    assert r.status_code == 200
    main = _main(r.text)
    assert main.count(AVISO) == 1 and INTRO_HTML in main
    caixas = _caixas(r.text)
    for m in DO_MODELO:
        assert caixas[rotulos.rotulo(rotulos.PRISMA, m)] == '<span class="nd">não divulgado</span>', m
    assert all(c["rotulo"] in caixas for c in WEB)
    assert 'href="/triagem-escopo"' not in main
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    do_leitor = _caixas(leitor.get("/literatura/prisma").text)
    assert list(do_leitor) == list(caixas) and len(caixas) == 26
    assert {k: v for k, v in caixas.items() if "não divulgado" not in v} == {
        k: v for k, v in do_leitor.items() if "não divulgado" not in caixas[k]}


def test_os_links_do_prisma_vies_do_visitante_so_levam_a_paginas_abertas(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path, banco="vies")
    gravar_politica(contas, "vies")
    main = _main(TestClient(app).get("/literatura/prisma").text)
    links = {re.sub(r"[?#].*", "", x) for x in re.findall(r'href="(/[^"]*)"', main)}
    assert links <= {"/", "/sobre", "/literatura/prisma", "/metodologia", "/entrar"}, links


def test_rota_do_vies_le_num_instantaneo_e_monta_pelo_modulo(banco_vies, tmp_path, monkeypatch):
    pv = _pv()
    pedidos = []
    original_dados, original_montar = pv.dados_vies, pv.montar_prisma_vies
    monkeypatch.setattr(pv, "dados_vies", lambda l, c: pedidos.append(("dados", c.banco)) or original_dados(l, c))
    monkeypatch.setattr(pv, "montar_prisma_vies", lambda d, o: pedidos.append(("montar", o)) or original_montar(d, o))
    instantaneos = []
    original_inst = LeituraPainelSQLite.instantaneo
    monkeypatch.setattr(LeituraPainelSQLite, "instantaneo", lambda self: instantaneos.append(1) or original_inst(self))
    assert _cli(banco_vies, tmp_path).get("/literatura/prisma").status_code == 200
    assert pedidos == [("dados", "vies"), ("montar", frozenset())]
    assert instantaneos == [1]


def test_pagina_do_vies_com_referencia_ambigua(tmp_path):
    """Uma referência da web cujo título coincide com dois artigos do Scholar conta como repetida, mas não é juntada a
    nenhum: nenhuma obra nas duas fontes, e os dois artigos continuam como obras próprias."""
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    con = sqlite3.connect(tmp_path / "busca.db")
    chamada, run = con.execute("SELECT chamada_id, run_id FROM ocorrencias LIMIT 1").fetchone()
    for i, titulo in ((1, "Só LA1"), (2, "só LA1.")):
        cur = con.execute("INSERT INTO artigos (chave_dedup, titulo, link, autores_publicacao, ano) VALUES (?, ?, ?, 'A - R', 2024)",
                          (f"ambigua-{i}", titulo, f"https://ambigua.org/{i}"))
        con.execute("INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?, ?, 'LB1', ?, ?)",
                    (chamada, cur.lastrowid, run, 10 + i))
    con.commit()
    con.close()
    caixas = _caixas(_cli(tmp_path / "busca.db", tmp_path).get("/literatura/prisma").text)
    assert {k: caixas.get(k) for k in [c["rotulo"] for c in WEB]} == {
        "busca na web: chamadas": "3", "busca na web: ocorrências devolvidas": "6",
        "busca na web: ocorrências repetidas juntadas": "2",
        "busca na web: referências únicas (por endereço normalizado)": "4",
        "referências da web que repetem um artigo do Scholar": "1",
        "obras distintas (artigos do Scholar e referências da web)": "6"}
    html = _cli(tmp_path / "busca.db", tmp_path).get("/literatura/prisma").text
    assert (f"<span>referências da web que repetem um artigo do Scholar<br><small>{DAS_DUAS} · pelo endereço: 0 · só pelo título: 1 "
            "· obras correspondentes: 0</small>") in html


MOTIVOS_CARTAO = '<section class="cartao"><h2 data-ic="list-bullets" data-tom="rosa">Motivos de exclusão</h2>'


def test_pagina_do_vies_sem_motivos_sem_cartao(banco_vies, tmp_path):
    main = _main(_cli(banco_vies, tmp_path).get("/literatura/prisma").text)
    assert "Motivos de exclusão" not in main


def test_pagina_do_vies_com_motivos_mostra_o_cartao(banco_vies, tmp_path):
    con = sqlite3.connect(banco_vies)
    artigo = con.execute("SELECT artigo_id FROM artigos ORDER BY artigo_id LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO triagem (artigo_id, decisao, motivo, revisor) VALUES (?, 'excluir', 'fora do tema', 'r')", (artigo,))
    con.commit()
    con.close()
    main = _main(_cli(banco_vies, tmp_path).get("/literatura/prisma").text)
    assert main.count(MOTIVOS_CARTAO) == 1
    assert '<tr><td>Título e resumo</td><td>fora do tema</td><td class="num">1</td></tr>' in main
    assert RODAPE in main
    assert main.index('<div class="prisma">') < main.index(MOTIVOS_CARTAO) < main.index(RODAPE)


def test_pagina_do_visitante_no_vies_nao_depende_dos_numeros_do_modelo(demo, tmp_path, monkeypatch):  # noqa: F811
    """Com os números do modelo mudados (as três caixas ocultas e os números da triagem do modelo no corpus), o conteúdo da
    página do visitante sai igual, byte a byte; o de quem entrou muda."""
    pv = _pv()
    original = pv.dados_vies
    app, contas, contas_db, copia = _painel(demo, tmp_path, banco="vies")
    _com_removidos_pelo_modelo(copia)
    gravar_politica(contas, "vies")
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303

    def mudado(l, c):
        d = original(l, c)
        d["prisma"] = {**d["prisma"], "caixas": [{**x, "valor": x["valor"] + 1000} if x["metrica"] in DO_MODELO else x
                                                 for x in d["prisma"]["caixas"]]}
        d["corpus"] = {**d["corpus"], "n_triados": 4321, "n_alta": 1234, "n_fora": 987}
        return d
    paginas, do_leitor = [], []
    for dados in (original, mudado):
        monkeypatch.setattr(pv, "dados_vies", dados)
        paginas.append(_main(TestClient(app).get("/literatura/prisma", follow_redirects=False).text))
        do_leitor.append(_main(leitor.get("/literatura/prisma").text))
    assert paginas[0] == paginas[1]
    assert do_leitor[0] != do_leitor[1]


# ================================================================ os outros bancos: só a introdução, a nota e o rodapé mudam
INTRO_REAL = ('<section class="cartao" aria-label="Sobre este fluxo">\n' + INTRO[0] + "\n" +
              "<p><strong>O que ele cobre aqui.</strong> Este fluxo adapta a estrutura do PRISMA à busca de artigos acadêmicos: "
              "Google Scholar e registros de bases bibliográficas inseridos manualmente, quando existentes. O levantamento nas "
              "páginas das secretarias estaduais tem procedimento próprio, descrito na Metodologia, e não entra neste fluxo. A "
              "pesquisa ainda não é uma revisão sistemática concluída: as etapas sem decisões registradas aparecem como tal.</p>\n"
              "<p><strong>Como ler os números.</strong> Cada caixa diz o que conta (registro devolvido pela busca, artigo único, "
              "registro informado de uma base manual) e de qual origem; números de unidades diferentes não se somam. As etapas "
              "marcadas “triagem de escopo do modelo” foram feitas por um modelo de linguagem e não são decisões de pesquisadores. "
              "Avaliados, excluídos e incluídos contam só decisões registradas por pessoas; “artigos únicos para triagem” e "
              "“pendentes” já descontam os artigos removidos pelo modelo. O que não foi informado ou não foi executado aparece "
              "escrito assim, nunca como zero.</p>\n</section>")
NOTA_MODELO_ANTIGA = " · triagem de escopo do modelo; decisão humana sempre vence"
NOTA_MODELO = " · triagem de escopo do modelo, só com confiança alta; decisão humana sempre vence"


def _como_antes(main):
    """Desfaz as três mudanças de texto: o que sobra tem de ser a página de antes, byte a byte (nenhuma contagem, permissão
    ou regra de divulgação muda)."""
    assert main.count(INTRO_REAL + "\n") == 1 and main.count(RODAPE) == 1
    assert "<h1>Fluxo PRISMA</h1>\n" + INTRO_REAL + "\n" in main
    return main.replace(INTRO_REAL + "\n", "", 1).replace(RODAPE, RODAPE_ANTIGO).replace(NOTA_MODELO, NOTA_MODELO_ANTIGA)


@pytest.mark.parametrize("nome", ["real", "demo", "simulado"])
def test_prisma_dos_outros_bancos_igual_ao_de_antes(nome, demo, tmp_path):  # noqa: F811
    """O conteúdo da página (o <main>) sai igual ao de antes, byte a byte, depois de desfeitas as três mudanças de texto."""
    db, raw = demo
    r = TestClient(_app(db, raw, tmp_path, nome=nome)[0]).get("/literatura/prisma")
    main = _main(r.text)
    assert NOTA_MODELO in main and NOTA_MODELO_ANTIGA not in main
    assert hashlib.sha256(_como_antes(main).encode()).hexdigest()[:16] == "0f42d5c0730312a7"


def test_prisma_do_estudo_real_igual_para_o_visitante_e_quem_entrou(demo, tmp_path):  # noqa: F811
    app, contas, contas_db, _ = _painel(demo, tmp_path, banco="real")
    gravar_politica(contas, "real")
    visitante = TestClient(app).get("/literatura/prisma").text
    assert hashlib.sha256(_como_antes(_main(visitante)).encode()).hexdigest()[:16] == "b2020825835d938c"
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    assert hashlib.sha256(_como_antes(_main(leitor.get("/literatura/prisma").text)).encode()).hexdigest()[:16] == "0f42d5c0730312a7"


def test_introducao_do_estudo_real_sem_textos_do_vies(demo, tmp_path):  # noqa: F811
    db, raw = demo
    main = _main(TestClient(_app(db, raw, tmp_path, nome="real")[0]).get("/literatura/prisma").text)
    for trecho in ("busca na web", "referências da web", "<details", "como pede o PRISMA 2020"):
        assert trecho not in main, trecho


@pytest.mark.parametrize("nome", ["real", "demo", "simulado"])
def test_os_outros_bancos_nao_usam_o_prisma_do_vies(nome, demo, tmp_path, monkeypatch):  # noqa: F811
    pv = _pv()
    monkeypatch.setattr(pv, "dados_vies", lambda *a: pytest.fail("dados_vies fora do vies"))
    monkeypatch.setattr(pv, "montar_prisma_vies", lambda *a: pytest.fail("montar_prisma_vies fora do vies"))
    db, raw = demo
    assert TestClient(_app(db, raw, tmp_path, nome=nome)[0]).get("/literatura/prisma").status_code == 200


def test_view_v_prisma_nao_muda(banco_vies):
    """A numeração da view continua a mesma (a Metodologia e o relatório estático a leem pela coluna `ordem`)."""
    ordens = [(o, f, m) for o, f, m, _ in sqlite3.connect(banco_vies).execute("SELECT ordem, fase, metrica, valor FROM v_prisma "
                                                                                "ORDER BY ordem")]
    assert ordens == [(o, f, m) for o, f, m, _ in VPRISMA]
