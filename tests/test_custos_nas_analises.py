"""Custos nos blocos da pagina de analises: sem `ver_custos`, cada bloco tira os valores em dolar e o consumo de creditos das
contas dos provedores, e nada mais muda (titulos, graficos, contagens, precisoes e os creditos como contagem de paginas do
Scholar ficam iguais). Com `ver_custos` (o padrao das funcoes), a saida e a de hoje."""
import json
import re

import pytest

from apoio_divulgacao import gravar_politica
from dominio import analises_ferramentas as AF, analises_vies as AV
from painel import analises_blocos as b, analises_blocos_cobertura as bc, analises_blocos_ferramentas as bf
from painel import analises_blocos_vies as bv
from test_analises_blocos_cobertura import WEB
from test_analises_vies import LEITURA, _itens, _t, _web
from test_painel import demo  # noqa: F401

DOLAR = re.compile(r"US\$ ?\d")


def _tudo(bloco):
    return json.dumps(bloco, default=str, ensure_ascii=False)


def _sem_colunas(tabela, nomes):
    """A tabela de hoje sem as colunas `nomes` (cabecalho e celulas)."""
    fora = [i for i, c in enumerate(tabela["cabecalho"]) if c in nomes]
    assert len(fora) == len(nomes), (tabela["cabecalho"], nomes)
    return {"cabecalho": [c for i, c in enumerate(tabela["cabecalho"]) if i not in fora],
            "linhas": [[x for i, x in enumerate(l) if i not in fora] for l in tabela["linhas"]]}


def _igual_menos(com, sem, chaves_iguais):
    for k in chaves_iguais:
        assert com[k] == sem[k], k


# ---------------- ferramentas ----------------
def _linhas():
    return AF.linhas(LEITURA)


def test_ferramentas_busca_sem_custo():
    com, sem = bf.bloco_ferramentas_busca(_linhas()), bf.bloco_ferramentas_busca(_linhas(), custos=False)
    assert com == bf.bloco_ferramentas_busca(_linhas(), custos=True)
    _igual_menos(com, sem, ("id", "titulo", "grafico", "subtitulo", "pares", "aviso", "selo"))
    assert sem["tabela"] == _sem_colunas(com["tabela"], ["Custo", "Créditos", "Custo por item"])
    assert sem["texto"] == []                       # a nota sobre os creditos (saldo do provedor) sai junto
    assert DOLAR.search(_tudo(com)) or "crédito" in _tudo(com).lower()      # o caso com custo existe
    assert not DOLAR.search(_tudo(sem)) and "crédito" not in _tudo(sem).lower()


def test_custos_viram_chamadas_falhas_e_tokens():
    linhas = _linhas()
    com, sem = bf.bloco_custos(linhas), bf.bloco_custos(linhas, custos=False)
    assert com == bf.bloco_custos(linhas, custos=True)
    assert sem["id"] == "ferramentas-chamadas" and sem["titulo"] == "Chamadas, falhas e tokens por etapa e ferramenta"
    assert sem["grafico"] is None and sem["subtitulo"] == "execuções do relatório"
    assert sem["texto"] == ["Falha é a chamada sem resposta aproveitável (erro, cota, bloqueio); ela fica registrada."]
    assert sem["tabela"] == _sem_colunas(com["tabela"], ["Custo", "Créditos"])
    assert DOLAR.search(_tudo(com)) or "crédito" in _tudo(com).lower()      # o caso com custo existe
    assert not DOLAR.search(_tudo(sem)) and "custo" not in _tudo(sem).lower()
    vazio = bf.bloco_custos([], custos=False)
    assert vazio["id"] == "ferramentas-chamadas" and vazio["titulo"] == "Nenhuma chamada registrada nas execuções do relatório"


def test_relevancia_por_ferramenta_sem_custo():
    lista = _itens([_web(1)], [], {("referencia", 1): _t()})
    rel = AV.relevancia_por_ferramenta(_linhas(), lista)
    com, sem = bv.bloco_ferramentas_relevancia(rel), bv.bloco_ferramentas_relevancia(rel, custos=False)
    assert com == bv.bloco_ferramentas_relevancia(rel, custos=True)
    _igual_menos(com, sem, ("id", "titulo", "grafico", "subtitulo", "texto", "pares", "aviso"))
    assert sem["tabela"] == _sem_colunas(com["tabela"], ["Custo por item de relevância alta ou média"])
    assert DOLAR.search(_tudo(com)) or "crédito" in _tudo(com).lower()      # o caso com custo existe
    assert not DOLAR.search(_tudo(sem)) and "crédito" not in _tudo(sem).lower()


# ---------------- funil ----------------
FUNIL = {"tem_dados_humanos": True, "provedores": [
    {"provedor": "perplexity", "resultados": 100, "paginas_com_texto": 40, "classificacoes_relevantes": 12, "achados": 9,
     "confirmados": 3, "n_consultas": 20, "custo_usd": 0.4,
     "etapas": [{"chave": k, "rotulo": k, "n": n} for k, n in (("resultados", 100), ("urls_unicas", 70), ("paginas_com_texto", 40),
                                                             ("classificacoes_relevantes", 12))]}]}


def test_funil_sem_custo():
    com, sem = b.bloco_funil(FUNIL), b.bloco_funil(FUNIL, custos=False)
    assert com == b.bloco_funil(FUNIL, custos=True)
    _igual_menos(com, sem, ("id", "titulo", "grafico", "subtitulo", "texto", "aviso"))
    assert com["pares"] == [("perplexity: consultas / custo", "20 / US$ 0,40")]
    assert sem["pares"] == [("perplexity: consultas", "20")]


# ---------------- cobertura da web ----------------
def test_precisao_web_sem_custo():
    com, sem = bc.bloco_precisao_web(WEB), bc.bloco_precisao_web(WEB, custos=False)
    assert com == bc.bloco_precisao_web(WEB, custos=True)
    _igual_menos(com, sem, ("id", "titulo", "grafico", "subtitulo", "aviso"))
    assert sem["texto"][0] == com["texto"][0]
    perfis = com["texto"][1].split(". O custo é o da busca")[0]
    assert sem["texto"] == [com["texto"][0], perfis + "."]
    assert sem["tabela"] == _sem_colunas(com["tabela"], ["Custo da busca", "Elegíveis por US$"])
    assert sem["pares"] == [p for p in com["pares"] if p[0] != "Custo total das buscas"]
    assert DOLAR.search(_tudo(com)) or "crédito" in _tudo(com).lower()      # o caso com custo existe
    assert not DOLAR.search(_tudo(sem)) and "custo" not in _tudo(sem).lower()


def test_curva_web_sem_custo():
    com, sem = bc.bloco_curva_web(WEB), bc.bloco_curva_web(WEB, custos=False)
    assert com == bc.bloco_curva_web(WEB, custos=True)
    _igual_menos(com, sem, ("id", "titulo", "grafico", "subtitulo", "aviso"))
    assert sem["texto"] == [t for t in com["texto"] if not t.startswith("Esses ") or " pares custaram " not in t]
    esperados = []
    for rot, val in com["pares"]:
        if rot == "Custo total das buscas":
            continue
        if rot.startswith("Menor prefixo") and val != "não alcançado":
            n, _usd, resto = val.split(", ")
            val = f"{n}, {resto}"
        esperados.append((rot, val))
    assert sem["pares"] == esperados
    assert sem["tabela"] == _sem_colunas(com["tabela"], ["Custo acumulado"])
    assert DOLAR.search(_tudo(com)) or "crédito" in _tudo(com).lower()      # o caso com custo existe
    assert not DOLAR.search(_tudo(sem)) and "custo" not in _tudo(sem).lower()


def test_blocos_da_web_repassam_a_regra():
    com, sem = bc.blocos_cobertura_web(WEB), bc.blocos_cobertura_web(WEB, custos=False)
    assert com == bc.blocos_cobertura_web(WEB, custos=True)
    assert [x["id"] for x in com] == [x["id"] for x in sem]
    assert DOLAR.search(_tudo(com)) or "crédito" in _tudo(com).lower()      # o caso com custo existe
    assert not DOLAR.search(_tudo(sem))


# ---------------- cobertura dos termos: creditos como contagem de paginas ficam ----------------
def test_termos_nao_mudam():
    import inspect
    assert "custos" not in inspect.signature(bc.blocos_cobertura_termos).parameters    # nada a esconder nesta aba


# ---------------- a rota ----------------
def test_montar_repassa_custos(demo, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from painel.rotas_extras import analises as R
    vistos = []
    for nome in ("bloco_ferramentas_busca", "bloco_custos"):
        orig = getattr(bf, nome)
        monkeypatch.setattr(bf, nome, lambda *a, _o=orig, _n=nome, **k: vistos.append((_n, k.get("custos", True))) or _o(*a, **k))
    orig_funil = b.bloco_funil
    monkeypatch.setattr(b, "bloco_funil", lambda *a, **k: vistos.append(("bloco_funil", k.get("custos", True))) or orig_funil(*a, **k))
    R.montar(LeituraPainelSQLite(demo[0]), "busca", ferramentas=_linhas(), custos=False)
    assert ("bloco_ferramentas_busca", False) in vistos and ("bloco_custos", False) in vistos and ("bloco_funil", False) in vistos


# ---------------- a pagina, por quem ve ----------------
from test_autenticacao import painel  # noqa: E402,F401
from test_custos_nas_paginas import clis  # noqa: E402,F401
from painel.rotas_extras.analises import ABAS  # noqa: E402


def test_visitante_nao_abre_as_analises(clis):  # noqa: F811
    """As analises tem resultados do modelo: quem nao entrou vai para a entrada em toda aba (D145)."""
    for chave, _ in ABAS:
        r = clis["Visitante"].get(f"/analises?secao={chave}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/entrar"), chave


@pytest.mark.parametrize("grupo", ["Consulta", "TecnicoSemCustos"])
def test_nenhuma_aba_de_analises_mostra_dolar_sem_a_permissao(clis, grupo):  # noqa: F811
    for chave, _ in ABAS:
        r = clis[grupo].get(f"/analises?secao={chave}")
        assert r.status_code == 200 and not DOLAR.search(r.text), (grupo, chave)
    h = clis[grupo].get("/analises?secao=busca").text
    assert "Chamadas, falhas e tokens por etapa e ferramenta" in h and "Créditos são o saldo do provedor" not in h


def test_quem_ve_custos_ve_os_custos_das_analises(clis):  # noqa: F811
    h = clis["TecnicoComCustos"].get("/analises?secao=busca").text
    assert DOLAR.search(h) and "Chamadas, falhas e tokens por etapa e ferramenta" not in h


# ---------------- decisoes da pre-revisao ----------------
from dominio.cobertura_termos import CRITERIO_DESEMPATE  # noqa: E402

WEB_REAL = dict(WEB, incremental=dict(
    WEB["incremental"], criterio_desempate=CRITERIO_DESEMPATE,
    marcos=[dict(m, atingido=m["percentual"] < 95) for m in WEB["incremental"]["marcos"]]))     # 95% e 100% nao alcancados


def test_curva_web_com_marco_nao_alcancado_e_o_criterio_real():
    com, sem = bc.bloco_curva_web(WEB_REAL), bc.bloco_curva_web(WEB_REAL, custos=False)
    assert not any(" pares custaram " in t for t in com["texto"])           # sem os 95%, nem hoje ha a frase de custo
    assert sem["texto"] == com["texto"]
    assert ("Menor prefixo que alcança 95%", "não alcançado") in sem["pares"]
    assert ("Menor prefixo que alcança 80%", "2 pares, 3 páginas") in sem["pares"]
    # o criterio de desempate descreve o metodo (sem valor nenhum): fica igual, e a ordem da tabela tambem
    assert ("Critério de desempate", CRITERIO_DESEMPATE) in sem["pares"]
    assert [l[:3] for l in sem["tabela"]["linhas"]] == [l[:3] for l in com["tabela"]["linhas"]]
    assert not DOLAR.search(_tudo(sem))


def test_sobreposicao_dos_modelos_nao_muda():
    com, sem = bc.blocos_cobertura_web(WEB), bc.blocos_cobertura_web(WEB, custos=False)
    assert [x for x in com if x["id"] == "web_sobreposicao"] == [x for x in sem if x["id"] == "web_sobreposicao"]


def _espiar(monkeypatch, modulo, nomes, vistos):
    for nome in nomes:
        orig = getattr(modulo, nome)
        monkeypatch.setattr(modulo, nome, lambda *a, _o=orig, _n=nome, **k: vistos.append((_n, k.get("custos", "ausente"))) or _o(*a, **k))


def test_montar_web_e_termos(demo, monkeypatch):  # noqa: F811
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from painel.rotas_extras import analises as R
    vistos = []
    _espiar(monkeypatch, bc, ("blocos_cobertura_web", "blocos_cobertura_termos", "blocos_redundancia"), vistos)
    leitura = LeituraPainelSQLite(demo[0])
    R.montar(leitura, "web", custos=False)
    R.montar(leitura, "termos", custos=False)
    assert ("blocos_cobertura_web", False) in vistos
    assert all(k == "ausente" for n, k in vistos if n in ("blocos_cobertura_termos", "blocos_redundancia"))   # termos: nada muda


def test_montar_vies_ferramentas(monkeypatch):
    from painel.rotas_extras import analises as R
    vistos = []
    _espiar(monkeypatch, bf, ("bloco_ferramentas_busca", "bloco_custos"), vistos)
    _espiar(monkeypatch, bv, ("bloco_ferramentas_relevancia",), vistos)
    monkeypatch.setattr(R.visao_geral_vies, "itens", lambda leitura, contexto: _itens([_web(1)], [], {("referencia", 1): _t()}))

    class Ctx:
        conjunto_da_consulta, consultas_literatura, recortes_vies, eixos_exploracao = {}, {}, {}, {}
    R.montar_vies(object(), Ctx(), "ferramentas", _linhas(), custos=False)
    assert sorted(vistos) == [("bloco_custos", False), ("bloco_ferramentas_busca", False), ("bloco_ferramentas_relevancia", False)]


def test_aba_de_ferramentas_do_vies_sem_custos(banco, tmp_path):  # noqa: F811
    """No banco vies, o visitante (sem ver_custos) nao recebe valor em dolar nem o consumo de creditos na aba de ferramentas."""
    import dataclasses
    from fastapi.testclient import TestClient
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.contas_sqlite import ContasSQLite
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from painel.app import criar_app
    from test_validacao_vies import _contexto
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    contas_vies = ContasSQLite(tmp_path / "contas_vies.db")
    gravar_politica(contas_vies, "vies")
    app = criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx,
                    contas=contas_vies)
    r = TestClient(app).get("/analises?secao=ferramentas", follow_redirects=False)     # quem nao entrou: entrada (D145)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar") and not DOLAR.search(r.text)
    from test_validacao_vies import _cli as _cli_sem_login
    todas = _cli_sem_login(banco, tmp_path).get("/analises?secao=ferramentas").text      # sem login: todas as permissoes
    assert "ferramentas-custos" in todas and "ferramentas-chamadas" not in todas            # a rota repassa a permissao, nao fixa


from test_validacao_vies import banco  # noqa: E402,F401
