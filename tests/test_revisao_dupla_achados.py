"""RG4 (a): revisao independente dos achados e concordancia entre revisores (kappa), espelhando a triagem.
Cobre a migracao de um banco antigo, `achados-importar [--independente]`, as views, a leitura do painel e o bloco."""
import sqlite3
import sys

import pandas as pd
import pytest

import main
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from dominio import estatistica as est
from painel import analises_blocos as b
from test_leitura_analises import Minimo

PERMITIDOS = {"em_uso", "piloto", "licitacao", "anunciado", "em_estudo", "apenas_citado", "descartado"}


def _linhas(repo, sql, args=()):
    return [dict(r) for r in repo.conn.execute(sql, args).fetchall()]


def _planilha(decisoes, revisor):
    """decisoes = {achado_id: status_final}; so linhas com verificado = 1 entram."""
    return pd.DataFrame([{"achado_id": a, "verificado": 1, "status_final": s, "verificado_por": revisor, "observacao": None}
                         for a, s in decisoes.items()])


@pytest.fixture
def banco(tmp_path):
    """10 achados sem verificacao, em um banco montado a mao."""
    m = Minimo(tmp_path / "achados.db")
    for i in range(10):
        m.achado("PI", "reconhecimento_facial", "em_uso")
    return RepositorioSQLite(m.caminho)


# Ana x Bia (desfecho confirmado/descartado): 4 ambos confirmam, 1 so Ana confirma, 2 so Bia confirma, 3 ambos descartam
ANA = {1: "em_uso", 2: "em_uso", 3: "piloto", 4: "em_uso", 5: "em_uso", 6: "descartado", 7: "descartado", 8: "descartado", 9: "descartado", 10: "descartado"}
BIA = {1: "em_uso", 2: "em_uso", 3: "licitacao", 4: "em_uso", 5: "descartado", 6: "em_uso", 7: "piloto", 8: "descartado", 9: "descartado", 10: "descartado"}
# ANA: confirma 1-5, descarta 6-10. BIA: confirma 1-4, 6, 7; descarta 5, 8-10.


# ============================== migracao de um banco antigo ==============================
def test_banco_antigo_recebe_a_coluna_independente_a_tabela_e_as_views_novas(tmp_path):
    antigo = tmp_path / "antigo.db"
    db = sqlite3.connect(antigo)
    db.executescript("""CREATE TABLE achados_revisoes (revisao_id INTEGER PRIMARY KEY AUTOINCREMENT, achado_id INTEGER NOT NULL,
        verificado_por TEXT NOT NULL, status_final TEXT, observacao TEXT, importado_em TEXT NOT NULL, anterior_json TEXT,
        posterior_json TEXT, desfeita INTEGER NOT NULL DEFAULT 0);
        INSERT INTO achados_revisoes (achado_id, verificado_por, status_final, importado_em) VALUES (1, 'Ana', 'em_uso', 'x');""")
    db.commit()
    db.close()
    assert not RepositorioSQLite.esquema_atualizado(antigo)
    repo = RepositorioSQLite(antigo)
    assert RepositorioSQLite.esquema_atualizado(antigo)
    assert repo.conn.execute("SELECT independente FROM achados_revisoes").fetchone()[0] == 0     # historico antigo: nao independente
    assert {"auditoria_id", "classificacao_id", "tinha_aplicacao", "tecnologia", "observacao"} <= {
        l["name"] for l in repo.conn.execute("PRAGMA table_info(auditoria_negativos)")}
    for view in ("v_concordancia_revisores_achados", "v_discordancias_achados", "v_auditoria_negativos", "v_negativos_auditaveis"):
        repo.conn.execute(f"SELECT * FROM {view}").fetchall()
    RepositorioSQLite(antigo).fechar()                                                              # abrir de novo e idempotente


# ============================== importacao com e sem --independente ==============================
def test_importacao_normal_muda_o_achado_e_a_independente_so_grava_historico(banco):
    banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS, so_historico=True)
    achado = dict(banco.conn.execute("SELECT verificado, status_final, verificado_por FROM achados WHERE achado_id=1").fetchone())
    assert achado == {"verificado": 0, "status_final": None, "verificado_por": None}               # achado intocado
    h = _linhas(banco, "SELECT achado_id, verificado_por, status_final, independente FROM achados_revisoes")
    assert h == [{"achado_id": 1, "verificado_por": "Ana", "status_final": "em_uso", "independente": 1}]
    banco.importar_verificacao_achados(_planilha({1: "piloto"}, "Ana"), PERMITIDOS)                  # normal: muda o achado
    assert tuple(banco.conn.execute("SELECT verificado, status_final FROM achados WHERE achado_id=1").fetchone()) == (1, "piloto")
    assert [x["independente"] for x in _linhas(banco, "SELECT * FROM achados_revisoes ORDER BY revisao_id")] == [1, 0]


def test_historico_independente_e_normal_deduplicam_cada_um_por_si(banco):
    for _ in range(2):
        banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS, so_historico=True)    # repetida: 1 linha
    banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS)                          # outro tipo: nova linha
    banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS)                          # repetida: sem linha
    banco.importar_verificacao_achados(_planilha({1: "piloto"}, "Ana"), PERMITIDOS, so_historico=True)       # mudou de ideia
    assert [(x["status_final"], x["independente"]) for x in _linhas(banco, "SELECT * FROM achados_revisoes ORDER BY revisao_id")] == [
        ("em_uso", 1), ("em_uso", 0), ("piloto", 1)]


def test_independente_valida_tudo_antes_de_gravar_e_nao_sofre_conflito_de_versao(banco):
    df = pd.concat([_planilha({1: "em_uso"}, "Ana"), _planilha({2: "inventado"}, "Ana")], ignore_index=True)
    with pytest.raises(SystemExit):
        banco.importar_verificacao_achados(df, PERMITIDOS, so_historico=True)
    assert banco.conn.execute("SELECT COUNT(*) FROM achados_revisoes").fetchone()[0] == 0
    banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS)                   # outra pessoa verificou antes
    df = _planilha({1: "descartado"}, "Bia")
    df["verificado_em"] = "carimbo-velho-da-planilha"                                                  # a planilha esta defasada
    banco.importar_verificacao_achados(df, PERMITIDOS, so_historico=True)
    assert banco.conflitos_importacao == []
    assert banco.conn.execute("SELECT COUNT(*) FROM achados_revisoes WHERE independente=1").fetchone()[0] == 1


def test_historico_do_painel_nao_mostra_a_revisao_independente(banco, tmp_path):
    banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS, so_historico=True)
    assert LeituraPainelSQLite(tmp_path / "achados.db").historico_achado(1) == []
    banco.importar_verificacao_achados(_planilha({1: "piloto"}, "Bia"), PERMITIDOS)
    assert [x["verificado_por"] for x in LeituraPainelSQLite(tmp_path / "achados.db").historico_achado(1)] == ["Bia"]


def test_cli_achados_importar_independente_so_grava_historico(ambiente_cli, monkeypatch, capsys):
    def rodar(*argv):
        monkeypatch.setattr(sys, "argv", ["main.py", *argv])
        main.main()
    rodar("tudo", "--simulado", "--ufs", "PI", "--paginas", "1")
    rodar("exportar", "--simulado", "--saida", str(ambiente_cli / "x.xlsx"))
    df = pd.read_excel(ambiente_cli / "x.xlsx", sheet_name="Achados").head(2)
    df["verificado"] = 1
    df["status_final"], df["verificado_por"] = "em_uso", "Ana"
    with pd.ExcelWriter(ambiente_cli / "ana.xlsx") as xw:
        df.to_excel(xw, sheet_name="Achados", index=False)
    banco = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    rodar("achados-importar", str(ambiente_cli / "ana.xlsx"), "--simulado", "--independente")
    assert banco.execute("SELECT COUNT(*) FROM achados_revisoes WHERE independente=1").fetchone()[0] == 2
    assert banco.execute("SELECT COUNT(*) FROM achados WHERE verificado=1").fetchone()[0] == 0
    rodar("achados-importar", str(ambiente_cli / "ana.xlsx"), "--simulado")
    assert banco.execute("SELECT COUNT(*) FROM achados WHERE verificado=1").fetchone()[0] == 2
    assert banco.execute("SELECT COUNT(*) FROM achados_revisoes WHERE independente=0").fetchone()[0] == 2


# ============================== views e kappa em dados montados a mao ==============================
def test_view_de_concordancia_calcula_o_kappa_a_mao(banco):
    banco.importar_verificacao_achados(_planilha(ANA, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Bia"), PERMITIDOS, so_historico=True)
    k = _linhas(banco, "SELECT * FROM v_concordancia_revisores_achados")
    assert len(k) == 1 and (k[0]["revisor_a"], k[0]["revisor_b"], k[0]["n_achados_em_comum"]) == ("Ana", "Bia", 10)
    assert (k[0]["ambos_confirmam"], k[0]["ambos_descartam"], k[0]["discordancias"]) == (4, 3, 3)
    # po = 0,7; pe = 0,5 * 0,6 + 0,5 * 0,4 = 0,5; kappa = (0,7 - 0,5) / 0,5 = 0,4
    assert k[0]["concordancia_pct"] == 70.0 and k[0]["kappa"] == 0.4
    # mesmo status final: 1, 2, 4 (em_uso), 8, 9, 10 (descartado) = 6 de 10 (3: piloto x licitacao; 7: descartado x piloto)
    assert (k[0]["n_status_iguais"], k[0]["concordancia_status_pct"]) == (6, 60.0)


def test_leitura_do_painel_usa_kappa_cohen_e_a_faixa_do_projeto(banco, tmp_path):
    banco.importar_verificacao_achados(_planilha(ANA, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Bia"), PERMITIDOS, so_historico=True)
    d = LeituraPainelSQLite(tmp_path / "achados.db").analise_concordancia_achados()
    assert d["tem_dados"] and (d["n_revisores"], d["n_achados_revisados"], d["n_pares"], d["n_discordancias"]) == (2, 10, 1, 4)
    p = d["pares"][0]
    esperado = est.kappa_cohen([[4, 1], [2, 3]])
    assert p["kappa"] == pytest.approx(0.4) == pytest.approx(esperado["kappa"])
    assert (p["ic_inferior"], p["ic_superior"]) == (esperado["ic_inferior"], esperado["ic_superior"])
    assert (p["so_a_confirma"], p["so_b_confirma"], p["interpretacao"], p["concordancia_pct"]) == (1, 2, "razoável", 70.0)
    assert p["concordancia_status_pct"] == 60.0


def test_discordancias_trazem_a_decisao_de_cada_revisor_e_a_final(banco):
    banco.importar_verificacao_achados(_planilha(ANA, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Bia"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha({3: "licitacao"}, "consenso"), PERMITIDOS)                      # decisao final do achado 3
    d = {x["achado_id"]: x for x in _linhas(banco, "SELECT * FROM v_discordancias_achados")}
    assert set(d) == {3, 5, 6, 7}                                                                      # 3 so de status; 5, 6 e 7 de desfecho
    assert (d[3]["status_a"], d[3]["status_b"], d[3]["status_final"], d[3]["tipo_discordancia"]) == ("piloto", "licitacao", "licitacao", "status_diferente")
    assert (d[5]["status_a"], d[5]["status_b"], d[5]["tipo_discordancia"], d[5]["status_final"]) == ("em_uso", "descartado", "confirmado_x_descartado", None)
    assert d[7]["tipo_discordancia"] == "confirmado_x_descartado" and d[5]["url"].startswith("https://") and d[5]["tecnologia"] == "reconhecimento_facial"
    ordem = [x["achado_id"] for x in _linhas(banco, "SELECT * FROM v_discordancias_achados")]
    assert ordem == [5, 6, 7, 3]                                                                       # desfecho primeiro


def test_consenso_e_revisao_normal_ficam_fora_do_kappa_e_tres_revisores_dao_tres_pares(banco, tmp_path):
    banco.importar_verificacao_achados(_planilha(ANA, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Bia"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha({1: "descartado", 2: "descartado"}, "consenso"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Caio"), PERMITIDOS)                                         # normal: nao e independente
    assert len(_linhas(banco, "SELECT * FROM v_concordancia_revisores_achados")) == 1
    banco.importar_verificacao_achados(_planilha({a: "em_uso" for a in range(1, 6)}, "Caio"), PERMITIDOS, so_historico=True)
    d = LeituraPainelSQLite(tmp_path / "achados.db").analise_concordancia_achados()
    assert d["n_revisores"] == 3 and d["n_pares"] == 3
    assert {(p["revisor_a"], p["revisor_b"]) for p in d["pares"]} == {("Ana", "Bia"), ("Ana", "Caio"), ("Bia", "Caio")}


def test_kappa_indefinido_quando_todos_decidem_igual(banco, tmp_path):
    banco.importar_verificacao_achados(_planilha({1: "em_uso", 2: "em_uso"}, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha({1: "em_uso", 2: "piloto"}, "Bia"), PERMITIDOS, so_historico=True)
    assert _linhas(banco, "SELECT kappa FROM v_concordancia_revisores_achados")[0]["kappa"] is None
    p = LeituraPainelSQLite(tmp_path / "achados.db").analise_concordancia_achados()["pares"][0]
    assert p["kappa"] is None and p["interpretacao"] is None and p["concordancia_pct"] == 100.0 and p["concordancia_status_pct"] == 50.0
    bl = b.bloco_concordancia_achados({"tem_dados": True, "n_revisores": 2, "n_achados_revisados": 2, "n_pares": 1, "n_discordancias": 1, "pares": [p]})
    assert "kappa não pode ser calculado" in bl["titulo"] and "menos de 30" in " ".join(bl["texto"])


# ============================== estado vazio e bloco ==============================
def test_sem_revisao_independente_a_leitura_e_o_bloco_ficam_vazios(banco, tmp_path):
    banco.importar_verificacao_achados(_planilha({1: "em_uso"}, "Ana"), PERMITIDOS)                                # so revisao normal
    d = LeituraPainelSQLite(tmp_path / "achados.db").analise_concordancia_achados()
    assert d == {"tem_dados": False, "n_revisores": 0, "n_achados_revisados": 0, "n_pares": 0, "n_discordancias": 0, "pares": []}
    bl = b.bloco_concordancia_achados(d)
    assert "Ainda não dá para medir" in bl["titulo"] and "--independente" in " ".join(bl["texto"]) and "Aguardando revisão independente" in bl["aviso"]
    assert bl["grafico"] is None and bl["tabela"] is None


def test_leitura_em_banco_antigo_sem_a_view_devolve_vazio(tmp_path):
    antigo = tmp_path / "antigo.db"
    sqlite3.connect(antigo).close()
    assert not LeituraPainelSQLite(antigo).analise_concordancia_achados()["tem_dados"]


def test_bloco_com_dados_usa_a_regua_de_kappa(banco, tmp_path):
    banco.importar_verificacao_achados(_planilha(ANA, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Bia"), PERMITIDOS, so_historico=True)
    d = LeituraPainelSQLite(tmp_path / "achados.db").analise_concordancia_achados()
    bl = b.bloco_concordancia_achados(d)
    assert "Ana e Bia concordam de forma razoável (κ = 0,40) em 10 achados" == bl["titulo"]
    assert "an-kappa" in str(bl["grafico"]) and "an-ic" in str(bl["grafico"])
    assert bl["tabela"]["linhas"][0][:5] == ["Ana × Bia", "10", "70,0%", "0,40", "razoável"] and bl["tabela"]["linhas"][0][5] == "60,0%"
    assert "menos de 30" in " ".join(bl["texto"]) and "Discordancias_achados" in " ".join(bl["texto"])


def test_exportacao_traz_as_abas_novas(banco):
    banco.importar_verificacao_achados(_planilha(ANA, "Ana"), PERMITIDOS, so_historico=True)
    banco.importar_verificacao_achados(_planilha(BIA, "Bia"), PERMITIDOS, so_historico=True)
    t = banco.tabelas_para_exportacao()
    assert {"Revisores_kappa_achados", "Discordancias_achados", "Auditoria_negativos"} <= set(t) and all(len(n) <= 31 for n in t)
    assert len(t["Revisores_kappa_achados"]) == 1 and len(t["Discordancias_achados"]) == 4
    assert t["Revisores_kappa_achados"].loc[0, "kappa"] == 0.4
