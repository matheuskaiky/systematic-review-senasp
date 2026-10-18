"""Triagem curta dos artigos anteriores a 2022 (D80): so relevancia e escopo geografico, prompt `c1`, mesma tabela."""
import json
import math
import sqlite3
import sys

import pytest

import main
from adaptadores.bruto_local import BrutoLocal
from adaptadores.simulados import TriadorSimulado
from aplicacao import triagem_escopo
from config import triagem_escopo as TE
from dados_metricas import TERMOS_ACADEMICOS, _novo_run, construir_academico
from dominio import triagem_escopo as D
from dominio.triagem_escopo import (CATEGORIA_TEMPORAL, chave_item, estimar_custo, linha_do_item, montar_esquema,
                                    montar_mensagem_usuario, validar_resposta)


def _c():
    return TE.CONFIG_CURTA
PRECOS = {"entrada": 0.3, "saida": 2.5}
MAPAS = {"artigo": TERMOS_ACADEMICOS}

SISTEMA_ESPERADO = """You rate the relevance of scholarly articles published before 2022 for a systematic review on artificial intelligence (AI) in Brazilian public security.
Judge only the title and snippet. Do not invent facts.

"relevancia":
- "alta": directly about AI or automated data analysis applied to public security, policing, forensics, criminal justice
  or the penal system (Brazilian or not), or a Brazilian study clearly useful for that scope.
- "media": related to the scope but indirect, or the title and snippet are not enough to decide.
- "baixa": off-topic, generic or only tangentially related.
When in doubt between "baixa" and another level, answer "media".

"confianca": how sure you are of "relevancia": alta, media or baixa. A "baixa" relevance without "alta" confidence is kept
for human review.

"escopo_geografico": brasil, internacional or indeterminado.

INPUT: one item per line, as JSON. Return exactly one object per item, echoing its "id" unchanged.
Never skip an item and never repeat an id."""


def _artigo(n=1, ano=2015, titulo="Reconhecimento facial na Polícia Militar", resumo="Estudo de caso."):
    return {"item_id": n, "fonte": "artigo", "uf": "", "provedor": "serpapi_scholar", "titulo": titulo, "resumo": resumo,
            "autores_publicacao": "A Silva - Revista, 2015", "ano": ano, "link": "https://x.org/a", "host": "x.org",
            "termos_ids": ["T01"], "termos": ['"reconhecimento facial"']}


# ====================== configuracao ======================
def test_configuracao_curta():
    assert (_c().versao, _c().curta, _c().lote_padrao, _c().lote_maximo, _c().snippet_max_chars) == ("c1", True, 40, 100, 300)
    assert (_c().tokens_fixos_por_chamada, _c().tokens_metadados_por_item, _c().ano_minimo) == (400, 15, 2022)
    assert _c().saida_por_item == {"baixo": 15, "medio": 20, "alto": 25}
    assert _c().raciocinio_por_chamada == TE.CONFIG.raciocinio_por_chamada
    assert (_c().sistema_artigo, _c().origem_artigo, _c().usuario_template) == (SISTEMA_ESPERADO, "scholarly articles published before 2022",
                                                                       TE.USUARIO_TEMPLATE)
    assert TE.CONFIG.curta is False and TE.CONFIG.versao == "t2"


# ====================== esquema e mensagem ======================
def test_esquema_curto_exato():
    assert montar_esquema(_c(), ["1", "2"]) == {
        "type": "object", "required": ["itens"],
        "properties": {"itens": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "the item id, copied unchanged", "enum": ["1", "2"]},
                           "relevancia": {"type": "string", "enum": ["alta", "media", "baixa"]},
                           "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                           "escopo_geografico": {"type": "string", "enum": ["brasil", "internacional", "indeterminado"]}},
            "required": ["id", "relevancia", "confianca", "escopo_geografico"]}}}}


def test_linha_curta_so_titulo_resumo_cortado_e_ano():
    item = _artigo(resumo="x" * 1000)
    assert linha_do_item(item, _c()) == {"id": "1", "titulo": item["titulo"], "resumo": "x" * 300, "ano": 2015}
    assert "query_terms" in linha_do_item(_artigo(), TE.CONFIG)               # a triagem completa nao muda


def test_mensagem_curta():
    m = montar_mensagem_usuario([_artigo(1), _artigo(2)], _c())
    assert m.startswith('Screen the following 2 items (scholarly articles published before 2022). Return one object per item')
    linhas = m.split("\n")[2:]
    assert [json.loads(l)["id"] for l in linhas] == ["1", "2"]


# ====================== conferencia da resposta (tabela) ======================
# (relevancia, confianca, escopo, ano) -> (status, status_bruto, confianca gravada, categoria, escopo gravado, valido, problemas)
T = CATEGORIA_TEMPORAL
CASOS = [
    ("alta", "alta", "brasil", 2015, ("elegivel", "elegivel", "alta", None, "brasil", True, [])),
    ("alta", "baixa", "brasil", 2015, ("elegivel", "elegivel", "baixa", None, "brasil", True, [])),
    ("media", "media", "internacional", 2015, ("quarentena", "quarentena", "media", T, "internacional", True, [])),
    ("baixa", "alta", "indeterminado", 2015, ("excluido", "excluido", "alta", T, "indeterminado", True, [])),
    ("baixa", "media", "brasil", 2015, ("quarentena", "excluido", "media", T, "brasil", True, [])),
    ("baixa", "baixa", "brasil", 2015, ("quarentena", "excluido", "baixa", T, "brasil", True, [])),
    (" ALTA ", " Alta ", " Brasil ", 2021, ("elegivel", "elegivel", "alta", None, "brasil", True, [])),
    ("muito alta", "alta", "brasil", 2015, ("quarentena", "muito alta", "alta", T, "brasil", False, ["relevancia_invalida"])),
    ("média", "alta", "brasil", 2015, ("quarentena", "média", "alta", T, "brasil", False, ["relevancia_invalida"])),
    ("", "alta", "brasil", 2015, ("quarentena", None, "alta", T, "brasil", False, ["relevancia_invalida"])),
    (None, "alta", "brasil", 2015, ("quarentena", None, "alta", T, "brasil", False, ["relevancia_invalida"])),
    (3, "alta", "brasil", 2015, ("quarentena", None, "alta", T, "brasil", False, ["relevancia_invalida"])),
    ("baixa", "certa", "brasil", 2015, ("quarentena", "excluido", None, T, "brasil", False, ["confianca_invalida"])),
    ("alta", None, "brasil", 2015, ("elegivel", "elegivel", None, None, "brasil", False, ["confianca_invalida"])),
    ("alta", "alta", "europa", 2015, ("elegivel", "elegivel", "alta", None, None, False, ["escopo_geografico_invalido"])),
    ("alta", "alta", "Brasíl", 2015, ("elegivel", "elegivel", "alta", None, None, False, ["escopo_geografico_invalido"])),
    ("alta", "alta", None, 2015, ("elegivel", "elegivel", "alta", None, None, False, ["escopo_geografico_invalido"])),
    ("xx", "zz", "yy", 2015, ("quarentena", "xx", None, T, None, False,
                              ["relevancia_invalida", "confianca_invalida", "escopo_geografico_invalido"])),
    ("baixa", "alta", "brasil", 2022, ("quarentena", "excluido", "alta", None, "brasil", False, ["triagem_curta_fora_do_recorte"])),
    ("alta", "alta", "brasil", None, ("quarentena", "elegivel", "alta", None, "brasil", False, ["triagem_curta_fora_do_recorte"])),
    ("xx", "zz", "yy", 2023, ("quarentena", "xx", None, None, None, False,
                              ["relevancia_invalida", "confianca_invalida", "escopo_geografico_invalido",
                               "triagem_curta_fora_do_recorte"])),
]


@pytest.mark.parametrize("relevancia,confianca,escopo,ano,esperado", CASOS)
def test_conferencia_curta_tabela(relevancia, confianca, escopo, ano, esperado):
    item = _artigo(ano=ano)
    obj = {"id": "1", "relevancia": relevancia, "confianca": confianca, "escopo_geografico": escopo, "justificativa": "ignorado"}
    (l,), extras = validar_resposta([item], json.dumps({"itens": [obj]}), _c())
    assert (l["status"], l["status_bruto"], l["confianca"], l["categoria_motivo"], l["escopo_geografico"], l["valido"],
            l["problemas"]) == esperado
    assert all(l[k] is None for k in ("justificativa", "termo_gerador", "sinal_negativo", "dominio_tematico", "tipo_documento"))
    assert extras == {"json_valido": True, "ids_ausentes": [], "ids_duplicados": [], "ids_desconhecidos": []}



def test_id_ausente_e_json_invalido_seguem_a_regra_geral():
    a, b = _artigo(1), _artigo(2)
    linhas, extras = validar_resposta([a, b], json.dumps({"itens": [{"id": "1", "relevancia": "alta", "confianca": "alta",
                                                                      "escopo_geografico": "brasil"}]}), _c())
    assert linhas[1]["problemas"] == ["id_ausente_na_resposta"] and linhas[1]["status_bruto"] is None
    assert linhas[1]["status"] == "quarentena" and extras["ids_ausentes"] == ["2"]
    linhas, extras = validar_resposta([a], "nao e json", _c())
    assert linhas[0]["problemas"] == ["resposta_json_invalida"] and extras["json_valido"] is False


@pytest.mark.parametrize("ano,esperado", [(2021, True), ("2021", True), (" 2021 ", True), (2022, False), (2030, False),
                                          (None, False), ("", False), ("abc", False), ("2021.0", False), (1950, True),
                                          (0, True)])
def test_fora_do_recorte_temporal(ano, esperado):
    assert D.fora_do_recorte_temporal(_artigo(ano=ano), _c()) is esperado


def test_estimativa_curta_conta_so_titulo_e_resumo():
    item = _artigo(titulo="t" * 34, resumo="r" * 2000)
    est = estimar_custo([item], 40, PRECOS, _c())
    assert est["tokens_entrada"] == 400 + math.ceil((34 + 300) / 3.4) + 15
    assert est["niveis"]["alto"]["tokens_saida"] == 25 + _c().raciocinio_por_chamada["alto"]


# ====================== selecao e etapa ======================
@pytest.fixture
def academico(tmp_path):
    repo, _ = construir_academico(tmp_path / "a.db")
    anos = {1: 2015, 2: 2021, 3: 2022, 4: None}           # artigo_id -> ano; os demais ficam em 2023
    for i, ano in anos.items():
        repo.conn.execute("UPDATE artigos SET ano=? WHERE artigo_id=?", (ano, i))
    repo.confirmar()
    return repo, BrutoLocal(tmp_path / "raw"), _novo_run(repo, "triar-escopo")


def _ids(itens):
    return sorted(i["item_id"] for i in itens)


def test_selecao_separa_os_antigos(academico):
    repo, _, _ = academico
    completos, r = triagem_escopo.selecionar(repo, "artigo", MAPAS, TE.CONFIG)
    curtos, rc = triagem_escopo.selecionar(repo, "artigo", MAPAS, _c())
    assert _ids(curtos) == [1, 2] and rc == {"total": 2, "na_amostra": 2, "ja_triados": 0, "a_triar": 2}
    assert _ids(completos) == list(range(3, 13)) and r["total"] == 10


def test_selecao_curta_pula_quem_ja_tem_triagem_respondida_de_qualquer_versao(academico):
    repo, _, run = academico
    base = {"fonte": "artigo", "uf": "", "status": "quarentena", "valido": True, "problemas": []}
    repo.salvar_triagem_escopo(run, None, "t2", [{**base, "item_id": 1, "status_bruto": "quarentena"},
                                                 {**base, "item_id": 2, "status_bruto": None}])
    repo.salvar_triagem_escopo(run, None, "c1", [{**base, "item_id": 5, "status_bruto": "xx", "valido": False}])
    repo.confirmar()
    assert repo.triagem_escopo_respondida("artigo") == {(1, ""), (5, "")}
    assert _ids(triagem_escopo.selecionar(repo, "artigo", MAPAS, _c())[0]) == [2]
    assert _ids(triagem_escopo.selecionar(repo, "artigo", MAPAS, _c(), refazer=True)[0]) == [1, 2]


def test_curta_recusa_web(academico):
    repo, _, _ = academico
    with pytest.raises(ValueError, match="^A triagem curta vale só para artigos.$"):
        triagem_escopo.selecionar(repo, "web", MAPAS, _c())


def test_etapa_curta_grava_c1_e_e_idempotente(academico):
    repo, bruto, run = academico
    t = TriadorSimulado()
    r = triagem_escopo.executar(repo, bruto, t, run, "artigo", MAPAS, _c(), PRECOS, [], 0)
    assert (r["itens_triados"], r["chamadas"]) == (2, 1)
    linhas = repo.conn.execute("SELECT item_id, status, status_bruto, categoria_motivo, valido, prompt_versao, "
                               "escopo_geografico FROM triagem_escopo ORDER BY item_id").fetchall()
    assert [l[0] for l in linhas] == [1, 2] and {l[5] for l in linhas} == {"c1"} and all(l[4] == 1 for l in linhas)
    for _, status, bruto_, cat, _, _, escopo in linhas:
        assert status == bruto_ and escopo == "brasil"
        assert cat == (None if status == "elegivel" else CATEGORIA_TEMPORAL)
    r2 = triagem_escopo.executar(repo, bruto, t, _novo_run(repo, "triar-escopo"), "artigo", MAPAS, _c(), PRECOS, [], 0)
    assert (r2["itens_triados"], r2["chamadas"]) == (0, 0)


def test_simulado_responde_o_esquema_curto():
    itens = [_artigo(n) for n in range(1, 7)]
    res = TriadorSimulado().triar(itens, type("I", (), {"usuario": "x", "esquema": montar_esquema(_c(), ["1"])})())
    objs = json.loads(res.texto_resposta)["itens"]
    assert [o["id"] for o in objs] == [chave_item(i) for i in itens]
    assert all(set(o) == {"id", "relevancia", "confianca", "escopo_geografico"} and o["escopo_geografico"] == "brasil"
               and o["confianca"] == "alta" for o in objs)
    assert {o["relevancia"] for o in objs} <= {"alta", "media", "baixa"}
    for esquema in ({}, None, montar_esquema(TE.CONFIG, ["1"])):              # sem esquema curto: resposta completa
        res = TriadorSimulado().triar(itens[:1], type("I", (), {"usuario": "x", "esquema": esquema})())
        assert "status" in json.loads(res.texto_resposta)["itens"][0]


# ====================== comando ======================
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.fixture
def simulado(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T01", "--paginas", "1")
    con = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    con.execute("UPDATE artigos SET ano=2010 WHERE artigo_id IN (SELECT MIN(artigo_id) FROM artigos)")
    con.commit()
    return ambiente_cli


@pytest.mark.parametrize("extra,mensagem", [
    (["--fonte", "web"], "--curta vale só para --fonte artigos."),
    (["--fonte", "artigos", "--lote", "101"], "--lote deve estar entre 1 e 100 (recebido: 101)."),
    (["--fonte", "artigos", "--lote", "0"], "--lote deve estar entre 1 e 100 (recebido: 0)."),
    (["--fonte", "web", "--lote", "101"], "--curta vale só para --fonte artigos."),
    (["--fonte", "web", "--estimar"], "--curta vale só para --fonte artigos."),
])
def test_cli_curta_recusas(ambiente_cli, monkeypatch, extra, mensagem):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triar-escopo", "--curta", "--simulado", "--limite", "1", *extra)
    assert str(e.value) == mensagem


def test_cli_curta_estimar_e_rodar(simulado, monkeypatch, capsys):
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--curta", "--estimar", "--simulado")
    out = capsys.readouterr().out
    assert "Triagem de escopo (prompt c1) | fonte: artigos" in out
    assert "Artigos anteriores a 2022 no banco: 1 | na amostra: 1 | já triados (qualquer prompt): 0 | a triar: 1" in out
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--curta", "--limite", "5", "--simulado")
    con = sqlite3.connect(simulado / "data" / "simulado.db")
    assert con.execute("SELECT COUNT(*), MIN(prompt_versao) FROM triagem_escopo").fetchone() == (1, "c1")
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--curta", "--limite", "5", "--simulado")
    assert ("Nada a triar: todos os artigos anteriores a 2022 da seleção já têm triagem respondida "
            "(use --refazer para repetir).") in capsys.readouterr().out
    cfg = json.loads(con.execute("SELECT config_json FROM execucoes ORDER BY rowid DESC LIMIT 1").fetchone()[0])
    assert cfg["triagem_escopo"]["versao"] == "c1" and cfg["triagem_escopo"]["curta"] is True
