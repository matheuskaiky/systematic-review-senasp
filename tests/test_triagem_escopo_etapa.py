"""Etapa `triagem_escopo` com o triador simulado, em bancos temporarios (nenhuma chamada de rede)."""
import json

import pytest

from adaptadores.bruto_local import BrutoLocal
from adaptadores.simulados import TriadorSimulado
from aplicacao import triagem_escopo
from config.triagem_escopo import CONFIG
from dados_metricas import TERMOS_ACADEMICOS, _novo_run, construir_academico, construir_web
from dominio.erros import CotaDiariaEsgotada
from dominio.triagem_escopo import chave_item

PRECOS = {"entrada": 0.3, "saida": 2.5}
MAPAS = {"artigo": TERMOS_ACADEMICOS,
         "web": {"tecnologias": {"reconhecimento_facial": "reconhecimento facial"}, "modelos": {"M01": "Secretaria", "M02": "seguranca"}}}


@pytest.fixture
def academico(tmp_path):
    repo, run_academico = construir_academico(tmp_path / "a.db")
    run = _novo_run(repo, "triar-escopo")
    return repo, BrutoLocal(tmp_path / "raw"), run


def _exec(repo, bruto, run, triador, fonte="artigo", **kw):
    kw.setdefault("lote", 5)
    return triagem_escopo.executar(repo, bruto, triador, run, fonte, MAPAS, CONFIG, PRECOS, [], 0, **kw)


def _n(repo, sql, *a):
    return repo.conn.execute(sql, a).fetchone()[0]


def _foto(repo):
    return {t: repo.conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("triagem", "achados", "artigos", "ocorrencias")}


def test_itens_de_artigo_trazem_termos_na_ordem_em_que_apareceram(academico):
    repo, _, _ = academico
    itens = repo.itens_para_triagem_escopo("artigo")
    assert len(itens) == 12
    a1 = next(i for i in itens if i["titulo"] == "Artigo A1")
    assert a1["termos_ids"] == ["T01", "T02", "T25"] and a1["provedor"] == "serpapi_scholar" and a1["uf"] == ""
    assert (a1["ano"], a1["autores_publicacao"], a1["resumo"]) == (2023, "Autor - Revista, 2023", "resumo")
    assert next(i for i in itens if i["titulo"] == "Artigo A7")["termos_ids"] == ["T01"]


def test_artigo_so_de_busca_manual_traz_a_origem_manual(academico):
    repo, _, _ = academico
    cur = repo.conn.execute("INSERT INTO artigos (chave_dedup, titulo, link) VALUES ('k', 'Manual', 'https://ieeexplore.ieee.org/x')")
    repo.conn.execute("INSERT INTO ocorrencias_manuais (artigo_id, base, termo_id) VALUES (?, 'IEEE', 'T05')", (cur.lastrowid,))
    repo.confirmar()
    m = next(i for i in repo.itens_para_triagem_escopo("artigo") if i["titulo"] == "Manual")
    assert m["provedor"] == "manual" and m["origens_manuais"] == ["IEEE"] and m["termos_ids"] == ["T05"]
    assert m["host"] == "ieeexplore.ieee.org"


def test_itens_web_unicos_por_url_e_uf_com_decisao_de_download(tmp_path):
    repo, _ = construir_web(tmp_path)
    itens = repo.itens_para_triagem_escopo("web")
    assert len(itens) == 4 and {i["uf"] for i in itens} == {"PI"} and {i["provedor"] for i in itens} == {"simulado"}
    gov1 = next(i for i in itens if i["url"].endswith("/pi/1"))
    assert gov1["host"] == "exemplo.gov.br" and gov1["selecionado"] is True and gov1["motivo_descarte"] is None
    assert gov1["tecnologias"][0] == "reconhecimento_facial" and gov1["modelos_ids"] == ["M01"]
    gov3 = next(i for i in itens if i["url"].endswith("/pi/3"))
    assert gov3["modelos_ids"] == ["M01", "M02"]                 # achada pelos dois modelos de consulta
    assert gov3["titulo"] and gov3["resumo"]


def test_execucao_fora_do_relatorio_nao_entra_nos_itens(academico):
    repo, _, run = academico
    run_academico = repo.conn.execute("SELECT run_id FROM execucoes WHERE comando='academico'").fetchone()[0]
    repo.definir_no_relatorio(run_academico, False, "teste")
    assert repo.itens_para_triagem_escopo("artigo") == []


def test_lotes_chamadas_e_linhas(academico):
    repo, bruto, run = academico
    antes = _foto(repo)
    r = _exec(repo, bruto, run, TriadorSimulado())
    assert (r["lotes"], r["chamadas"], r["itens_triados"], r["lotes_falhos"]) == (3, 3, 12, 0)
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo' AND sucesso=1") == 3
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo WHERE run_id=?", run) == 12
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo WHERE valido=1") == 12
    linha = repo.conn.execute("SELECT * FROM triagem_escopo WHERE item_id=1").fetchone()
    assert linha["prompt_versao"] == "t1" and linha["fonte"] == "artigo" and linha["uf"] == ""
    assert json.loads(linha["termos_consulta"]) == ['"reconhecimento facial"', '"reconhecimento facial em tempo real"', '"facial recognition"']
    ch = repo.conn.execute("SELECT * FROM chamadas WHERE etapa='triagem_escopo' ORDER BY chamada_id").fetchall()
    assert [c["alvo_tipo"] for c in ch] == ["lote"] * 3 and len({c["chave_idempotencia"] for c in ch}) == 3
    assert all(c["raw_path"] for c in ch)
    assert _foto(repo) == antes                                   # triagem humana, achados e artigos intactos
    assert _n(repo, "SELECT valor FROM metricas_run WHERE run_id=? AND chave='triagem_escopo_itens_triados'", run) == 12
    assert _n(repo, "SELECT valor FROM metricas_run WHERE run_id=? AND chave='triagem_escopo_lote'", run) == 5


def test_reexecutar_a_mesma_execucao_ou_outra_nao_faz_chamadas_novas(academico):
    repo, bruto, run = academico
    _exec(repo, bruto, run, TriadorSimulado())
    t2 = TriadorSimulado()
    assert _exec(repo, bruto, run, t2)["chamadas"] == 0
    outra = _novo_run(repo, "triar-escopo")
    r = _exec(repo, bruto, outra, t2)
    assert t2.chamadas == 0 and r["a_triar"] == 0 and r["ja_triados"] == 12
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo'") == 3


def test_refazer_repete_em_nova_execucao_sem_apagar_a_anterior(academico):
    repo, bruto, run = academico
    _exec(repo, bruto, run, TriadorSimulado())
    outra = _novo_run(repo, "triar-escopo")
    r = _exec(repo, bruto, outra, TriadorSimulado(), refazer=True)
    assert r["chamadas"] == 3
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 24


def test_prompt_com_outra_versao_nao_pula_itens(academico):
    repo, bruto, run = academico
    _exec(repo, bruto, run, TriadorSimulado())
    from dataclasses import replace
    outra = _novo_run(repo, "triar-escopo")
    r = triagem_escopo.executar(repo, bruto, TriadorSimulado(), outra, "artigo", MAPAS, replace(CONFIG, versao="t2"),
                                PRECOS, [], 0, lote=5)
    assert r["chamadas"] == 3 and _n(repo, "SELECT COUNT(*) FROM triagem_escopo WHERE prompt_versao='t2'") == 12


def test_retomada_depois_de_lote_com_falha_so_repete_o_lote_que_falhou(academico):
    repo, bruto, run = academico
    r = _exec(repo, bruto, run, TriadorSimulado(falhar_chamadas={2}))
    assert (r["chamadas"], r["lotes_falhos"], r["itens_triados"]) == (3, 1, 7)          # 5 + (falha) + 2
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo' AND sucesso=0") == 1
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 7                         # nada gravado para o lote falho
    t = TriadorSimulado()
    r2 = _exec(repo, bruto, run, t)
    assert t.chamadas == 1 and r2["itens_triados"] == 5 and _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 12


def test_lote_que_falha_sempre_e_abandonado_apos_n_falhas(academico):
    repo, bruto, run = academico
    t = TriadorSimulado(falhar_chamadas={1, 2, 3, 4, 5})
    for _ in range(3):
        _exec(repo, bruto, run, t, lote=50, max_falhas_por_lote=3)
    assert t.chamadas == 3
    r = _exec(repo, bruto, run, t, lote=50, max_falhas_por_lote=3)
    assert t.chamadas == 3 and r["desistencias"] == 1 and r["chamadas"] == 0


def test_teto_de_custo_para_antes_da_chamada_que_o_estouraria(academico):
    repo, bruto, run = academico
    t = TriadorSimulado(custo_por_chamada=0.05)
    r = _exec(repo, bruto, run, t, lote=3, max_custo_usd=0.09)
    assert t.chamadas == 2 and r["parou_por_custo"] is True and r["itens_triados"] == 6
    assert r["custo_usd"] == pytest.approx(0.10)
    assert _n(repo, "SELECT valor FROM metricas_run WHERE run_id=? AND chave='triagem_escopo_parou_por_custo'", run) == 1
    assert _n(repo, "SELECT valor FROM metricas_run WHERE run_id=? AND chave='triagem_escopo_teto_custo_usd'", run) == 0.09
    assert _n(repo, "SELECT valor FROM metricas_run WHERE run_id=? AND chave='triagem_escopo_custo_estimado_proxima_chamada_usd'", run) > 0
    # o custo acumulado conta o que ja foi gasto na mesma execucao: a retomada com o mesmo teto nao chama de novo
    t2 = TriadorSimulado(custo_por_chamada=0.05)
    _exec(repo, bruto, run, t2, lote=3, max_custo_usd=0.09)
    assert t2.chamadas == 0


def test_teto_exige_precos(academico):
    repo, bruto, run = academico
    with pytest.raises(ValueError):
        triagem_escopo.executar(repo, bruto, TriadorSimulado(), run, "artigo", MAPAS, CONFIG, None, [], 0, max_custo_usd=0.1)


def test_id_ausente_gera_linha_invalida_e_o_item_pode_ser_repetido(academico):
    repo, bruto, run = academico
    itens = repo.itens_para_triagem_escopo("artigo")
    faltante = itens[2]
    r = _exec(repo, bruto, run, TriadorSimulado(omitir={chave_item(faltante)}))
    assert r["itens_sem_resposta"] == 1 and r["itens_triados"] == 11
    l = repo.conn.execute("SELECT * FROM triagem_escopo WHERE item_id=?", (faltante["item_id"],)).fetchone()
    assert (l["status"], l["status_bruto"], l["valido"]) == ("quarentena", None, 0)
    assert json.loads(l["problemas"]) == ["id_ausente_na_resposta"]
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo' AND sucesso=1") == 3
    outra = _novo_run(repo, "triar-escopo")
    t = TriadorSimulado()
    assert _exec(repo, bruto, outra, t)["itens_triados"] == 1 and t.chamadas == 1       # so o que faltou


def test_termo_fora_da_lista_fica_marcado_no_banco(academico):
    repo, bruto, run = academico
    _exec(repo, bruto, run, TriadorSimulado(termo_ruim=True))
    problemas = [json.loads(l[0]) for l in repo.conn.execute("SELECT problemas FROM triagem_escopo WHERE valido=0")]
    assert problemas and all("termo_gerador_fora_da_lista" in p for p in problemas)
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo WHERE valido=0 AND termo_gerador IS NOT NULL") == 0


@pytest.mark.parametrize("triador, erro", [
    (TriadorSimulado(json_invalido=True), "resposta_json_invalida"),
    (TriadorSimulado(truncar_chamadas={1}), "resposta_truncada: MAX_TOKENS"),
])
def test_resposta_invalida_ou_truncada_e_falha_do_lote_sem_perda_silenciosa(academico, triador, erro, caplog):
    repo, bruto, run = academico
    r = _exec(repo, bruto, run, triador, lote=50)
    assert r["lotes_falhos"] == 1 and r["itens_triados"] == 0 and _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 0
    c = repo.conn.execute("SELECT sucesso, erro, tokens_saida FROM chamadas WHERE etapa='triagem_escopo'").fetchone()
    assert c["sucesso"] == 0 and c["erro"].startswith(erro) and c["tokens_saida"] > 0
    assert "FALHA" in caplog.text


def test_amostra_e_deterministica_e_repetir_o_comando_nao_gasta_de_novo(academico):
    repo, bruto, run = academico
    r = _exec(repo, bruto, run, TriadorSimulado(), amostra=6, estratificar=True, semente="s")
    assert (r["na_amostra"], r["a_triar"], r["chamadas"]) == (6, 6, 2)
    ids = {l[0] for l in repo.conn.execute("SELECT item_id FROM triagem_escopo")}
    outra = _novo_run(repo, "triar-escopo")
    t = TriadorSimulado()
    assert _exec(repo, bruto, outra, t, amostra=6, estratificar=True, semente="s")["a_triar"] == 0 and t.chamadas == 0
    r3 = _exec(repo, bruto, outra, t, amostra=6, estratificar=True, semente="outra")        # outra semente: outra amostra
    assert r3["na_amostra"] == 6 and ids != {l[0] for l in repo.conn.execute("SELECT item_id FROM triagem_escopo WHERE run_id=?", (outra,))}


def test_limite_corta_o_numero_de_itens_enviados(academico):
    repo, bruto, run = academico
    r = _exec(repo, bruto, run, TriadorSimulado(), limite=4)
    assert r["itens_triados"] == 4 and _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 4


def test_limite_vale_para_o_conjunto_e_repetir_ou_retomar_nao_amplia_o_gasto(academico):
    repo, bruto, run = academico
    _exec(repo, bruto, run, TriadorSimulado(), limite=4)
    t = TriadorSimulado()
    assert _exec(repo, bruto, _novo_run(repo, "triar-escopo"), t, limite=4)["chamadas"] == 0 and t.chamadas == 0
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 4


def test_triagem_de_resultados_web_usa_item_e_uf(tmp_path):
    repo, _ = construir_web(tmp_path)
    run = _novo_run(repo, "triar-escopo")
    r = triagem_escopo.executar(repo, BrutoLocal(tmp_path / "raw2"), TriadorSimulado(), run, "web", MAPAS, CONFIG, PRECOS, [], 0)
    assert r["itens_triados"] == 4
    assert {(l["fonte"], l["uf"]) for l in repo.conn.execute("SELECT fonte, uf FROM triagem_escopo")} == {("web", "PI")}
    termos = json.loads(repo.conn.execute("SELECT termos_consulta FROM triagem_escopo WHERE item_id=(SELECT url_id FROM urls WHERE url_original LIKE '%/pi/3')").fetchone()[0])
    assert "Secretaria" in termos and "seguranca" in termos and "reconhecimento facial" in termos
    # nao toca nas classificacoes nem nos achados verificados pelo humano
    assert _n(repo, "SELECT COUNT(*) FROM achados WHERE verificado=1") == 3


def test_exportacao_inclui_o_veredito_do_modelo_sem_esconder_nada(academico):
    repo, bruto, run = academico
    _exec(repo, bruto, run, TriadorSimulado())
    t = repo.tabelas_para_exportacao()
    assert len(t["Triagem_escopo"]) == 12 and set(t["Triagem_escopo"]["status"]) <= {"elegivel", "quarentena", "excluido"}
    assert {"item", "categoria_motivo", "justificativa", "valido", "problemas", "prompt_versao"} <= set(t["Triagem_escopo"].columns)
    tri = t["Triagem"]
    assert "triagem_llm" in tri.columns and tri["triagem_llm"].notna().all() and len(tri) >= 12
    v = tri.set_index("artigo_id")["triagem_llm"]
    linha = repo.conn.execute("SELECT status, categoria_motivo FROM triagem_escopo WHERE item_id=1").fetchone()
    assert v[1] == linha["status"] + (f": {linha['categoria_motivo']}" if linha["categoria_motivo"] else "")
    # com mais de uma execucao, a planilha mostra so o veredito mais recente por item
    outra = _novo_run(repo, "triar-escopo")
    _exec(repo, bruto, outra, TriadorSimulado(), refazer=True)
    t = repo.tabelas_para_exportacao()
    assert len(t["Triagem_escopo"]) == 12 and set(t["Triagem_escopo"]["run_id"]) == {outra}


def test_cota_diaria_para_no_primeiro_lote_afetado_e_a_retomada_nao_repete_o_que_foi_feito(academico):
    repo, bruto, run = academico
    t = TriadorSimulado(cota_diaria_chamadas={3})
    with pytest.raises(CotaDiariaEsgotada) as e:
        _exec(repo, bruto, run, t)                                    # lotes de 5, 5 e 2 itens: o terceiro bate na cota
    assert t.chamadas == 3 and e.value.renova_em_s == 3600.0
    assert _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 10      # os lotes anteriores ficaram gravados
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo' AND sucesso=1") == 2
    falha = repo.conn.execute("SELECT sucesso, erro, extras_json FROM chamadas WHERE etapa='triagem_escopo' AND sucesso=0").fetchone()
    assert falha["erro"] == "HTTP 429" and json.loads(falha["extras_json"])["cota_diaria_esgotada"] is True   # auditoria
    assert _n(repo, "SELECT valor FROM metricas_run WHERE run_id=? AND chave='triagem_escopo_parada_cota_diaria'", run) == 1
    # "renovou": a mesma execucao termina so o lote que faltou
    t2 = TriadorSimulado()
    r = _exec(repo, bruto, run, t2)
    assert t2.chamadas == 1 and r["itens_triados"] == 2 and _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 12


def test_cota_diaria_no_primeiro_lote_nao_grava_nada_e_nao_conta_como_falha_de_lote(academico):
    repo, bruto, run = academico
    t = TriadorSimulado(cota_diaria_chamadas={1})
    with pytest.raises(CotaDiariaEsgotada):
        _exec(repo, bruto, run, t)
    assert t.chamadas == 1 and _n(repo, "SELECT COUNT(*) FROM triagem_escopo") == 0
