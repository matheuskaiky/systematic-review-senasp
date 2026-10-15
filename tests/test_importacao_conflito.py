"""Planilha exportada antes de uma decisao do painel (ou de outra planilha) nao pode sobrescrever essa decisao."""
import logging
import sys

import pandas as pd
import pytest

import main
from config import vocabulario as V
from dados_metricas import construir_classificacao_mista

PERMITIDOS = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
COLS = ["achado_id", "verificado", "status_final", "verificado_por", "observacao", "verificado_em"]


@pytest.fixture
def repo(tmp_path):
    logging.disable(logging.CRITICAL)
    r, _ = construir_classificacao_mista(tmp_path)
    yield r
    logging.disable(logging.NOTSET)


def _ids(repo):
    return [x[0] for x in repo.conn.execute("SELECT achado_id FROM achados ORDER BY achado_id")]


def _linha(achado_id, status, por, carimbo=None):
    return (achado_id, 1, status, por, None, carimbo)


def _estado(repo, i):
    return tuple(repo.conn.execute("SELECT verificado, status_final, verificado_por FROM achados WHERE achado_id=?", (i,)).fetchone())


def test_exportacao_traz_os_carimbos_de_tempo(repo):
    t = repo.tabelas_para_exportacao()
    assert "verificado_em" in t["Achados"].columns and "revisado_em" in t["Triagem"].columns


def test_planilha_sem_conflito_importa_normalmente(repo):
    a = _ids(repo)[0]
    df = pd.DataFrame([_linha(a, "em_uso", "Ana", None)], columns=COLS)
    assert repo.importar_verificacao_achados(df, PERMITIDOS) == 1 and repo.conflitos_importacao == []
    # reimportar com o carimbo certo (revisor muda o status na planilha exportada depois)
    carimbo = repo.conn.execute("SELECT verificado_em FROM achados WHERE achado_id=?", (a,)).fetchone()[0]
    assert repo.importar_verificacao_achados(pd.DataFrame([_linha(a, "piloto", "Ana", carimbo)], columns=COLS), PERMITIDOS) == 1
    assert _estado(repo, a) == (1, "piloto", "Ana")


def test_achado_verificado_no_painel_depois_da_exportacao_nao_e_sobrescrito(repo):
    a, b = _ids(repo)[:2]
    planilha = pd.DataFrame([_linha(a, "descartado", "Bia", None), _linha(b, "em_uso", "Bia", None)], columns=COLS)   # exportada com os dois pendentes
    repo.verificar_achado(a, "piloto", "Ana", None, PERMITIDOS)                                                   # Ana decide o primeiro no painel
    assert repo.importar_verificacao_achados(planilha, PERMITIDOS) == 1                                           # so o segundo entra
    assert repo.conflitos_importacao == [(a, 2)]                                                                  # linha 2 da planilha
    assert _estado(repo, a) == (1, "piloto", "Ana") and _estado(repo, b) == (1, "em_uso", "Bia")


def test_planilha_antiga_depois_de_outra_planilha_tambem_conflita(repo):
    a = _ids(repo)[0]
    antiga = pd.DataFrame([_linha(a, "descartado", "Bia", None)], columns=COLS)
    repo.importar_verificacao_achados(pd.DataFrame([_linha(a, "em_uso", "Ana", None)], columns=COLS), PERMITIDOS)
    assert repo.importar_verificacao_achados(antiga, PERMITIDOS) == 0 and repo.conflitos_importacao == [(a, 2)]
    assert _estado(repo, a) == (1, "em_uso", "Ana")


def test_planilha_sem_coluna_de_carimbo_continua_funcionando(repo):
    a = _ids(repo)[0]
    df = pd.DataFrame([(a, 1, "em_uso", "Ana", None)], columns=COLS[:5])
    assert repo.importar_verificacao_achados(df, PERMITIDOS) == 1 and repo.conflitos_importacao == []


def test_conflito_nao_impede_validacao_de_id_nem_deixa_lote_pela_metade(repo):
    a = _ids(repo)[0]
    df = pd.DataFrame([_linha(a, "em_uso", "Ana", None), _linha(99999, "em_uso", "Ana", None)], columns=COLS)
    with pytest.raises(SystemExit, match="Achado inexistente: 99999"):
        repo.importar_verificacao_achados(df, PERMITIDOS)
    assert _estado(repo, a)[0] == 0


def _tri(artigo_id, decisao, revisado_em=None, revisor="Bia"):
    return {"artigo_id": artigo_id, "decisao": decisao, "motivo": "m" if decisao == "excluir" else None, "confirmado_em_base": None,
            "link_confirmado": None, "revisor": revisor, "revisado_em": revisado_em}


def test_triagem_decidida_no_painel_depois_da_exportacao_nao_e_sobrescrita(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    r = RepositorioSQLite(tmp_path / "t.db")
    for n in (1, 2):
        r._inserir("artigos", chave_dedup=f"k{n}", titulo=f"t{n}", primeira_vez_em="2026-01-01")
        r._inserir("ocorrencias_manuais", artigo_id=n, base="IEEE", termo_id="T01", data_busca="", posicao=1)
    r.conn.commit()
    exportada = pd.DataFrame([_tri(1, "excluir"), _tri(2, "incluir")])           # os dois pendentes quando exportada
    r.registrar_triagem(1, "incluir", "Ana")                                       # Ana decide o primeiro no painel
    assert r.importar_triagem(exportada) == 1 and r.conflitos_importacao == [(1, 2)]
    d = dict(r.conn.execute("SELECT artigo_id, decisao FROM triagem").fetchall())
    assert d == {1: "incluir", 2: "incluir"}
    # com o carimbo exato nao ha conflito
    carimbo = r.conn.execute("SELECT revisado_em FROM triagem WHERE artigo_id=1").fetchone()[0]
    assert r.importar_triagem(pd.DataFrame([_tri(1, "excluir", carimbo)])) == 1 and r.conflitos_importacao == []


def test_revisao_independente_nao_sofre_conflito(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    r = RepositorioSQLite(tmp_path / "t.db")
    r._inserir("artigos", chave_dedup="k", titulo="t", primeira_vez_em="2026-01-01")
    r._inserir("ocorrencias_manuais", artigo_id=1, base="IEEE", termo_id="T01", data_busca="", posicao=1)
    r.conn.commit()
    r.registrar_triagem(1, "incluir", "Ana")
    assert r.importar_triagem(pd.DataFrame([_tri(1, "excluir", None, "Bia")]), so_historico=True) == 1 and r.conflitos_importacao == []


def test_linha_de_comando_avisa_os_conflitos(tmp_path, monkeypatch, capsys):
    import config.settings as S
    monkeypatch.setattr(S, "DATA_DIR", tmp_path / "data"); monkeypatch.setattr(S, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(S, "OUT_DIR", tmp_path / "outputs"); monkeypatch.setitem(S.OPCOES["excel"], "pasta", tmp_path / "outputs")
    monkeypatch.setattr(S, "PAUSAS", {k: 0 for k in S.PAUSAS})
    rodar = lambda *argv: (monkeypatch.setattr(sys, "argv", ["main.py", *argv]), main.main())
    rodar("tudo", "--simulado", "--ufs", "PI", "--paginas", "1")
    rodar("exportar", "--simulado", "--saida", str(tmp_path / "x.xlsx"))
    df = pd.read_excel(tmp_path / "x.xlsx", sheet_name="Achados")
    i = int(df.loc[0, "achado_id"])
    for col in ("status_final", "verificado_por"):
        df[col] = df[col].astype(object)
    df.loc[0, ["verificado", "status_final", "verificado_por"]] = [1, "descartado", "Bia"]
    with pd.ExcelWriter(tmp_path / "editada.xlsx") as xw:
        df.to_excel(xw, sheet_name="Achados", index=False)
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    r = RepositorioSQLite(tmp_path / "data" / "simulado.db")
    r.verificar_achado(i, "em_uso", "Ana", None, PERMITIDOS)                       # Ana decide antes de a planilha da Bia chegar
    r.fechar()
    capsys.readouterr()
    rodar("achados-importar", str(tmp_path / "editada.xlsx"), "--simulado")
    saida = capsys.readouterr().out
    assert "CONFLITOS: 1 linha(s) ignorada(s)" in saida and f"{i} (linha 2)" in saida and "Findings verified: 0" in saida
