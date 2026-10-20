"""Decisao humana de um achado por vez (painel): validacao, historico, desfazer, copia de seguranca."""
import json
import logging

import pytest

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from config import vocabulario as V
from dados_metricas import construir_classificacao_mista

PERMITIDOS = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)


@pytest.fixture
def repo(tmp_path):
    logging.disable(logging.CRITICAL)
    r, _ = construir_classificacao_mista(tmp_path)
    yield r
    logging.disable(logging.NOTSET)


def _ids(repo):
    return [x[0] for x in repo.conn.execute("SELECT achado_id FROM achados ORDER BY achado_id")]


def _estado(repo, i):
    return dict(repo.conn.execute("SELECT verificado, status_final, verificado_por, observacao FROM achados WHERE achado_id=?", (i,)).fetchone())


def test_verificar_normaliza_o_status_e_grava_historico(repo):
    a = _ids(repo)[0]
    repo.verificar_achado(a, " Em_Uso ", "  Ana ", " ok ", PERMITIDOS)
    assert _estado(repo, a) == {"verificado": 1, "status_final": "em_uso", "verificado_por": "Ana", "observacao": "ok"}
    h = dict(repo.conn.execute("SELECT * FROM achados_revisoes WHERE achado_id=?", (a,)).fetchone())
    assert h["verificado_por"] == "Ana" and h["status_final"] == "em_uso" and json.loads(h["anterior_json"])["verificado"] == 0


def test_verificar_exige_revisor_e_status_valido_e_achado_existente(repo):
    a = _ids(repo)[0]
    for revisor in ("", "   ", None):
        with pytest.raises(SystemExit, match="revisor"):
            repo.verificar_achado(a, "em_uso", revisor, None, PERMITIDOS)
    with pytest.raises(SystemExit, match="status_final"):
        repo.verificar_achado(a, "inventado", "Ana", None, PERMITIDOS)
    with pytest.raises(SystemExit, match="Achado inexistente"):
        repo.verificar_achado(99999, "em_uso", "Ana", None, PERMITIDOS)
    assert _estado(repo, a)["verificado"] == 0


def test_desfazer_volta_ao_estado_anterior_a_ultima_decisao(repo):
    a = _ids(repo)[0]
    repo.verificar_achado(a, "piloto", "Ana", "primeira", PERMITIDOS)
    primeira = _estado(repo, a)
    repo.verificar_achado(a, "descartado", "Bia", "mudei de ideia", PERMITIDOS)
    repo.desfazer_ultima_decisao(a)
    assert _estado(repo, a) == primeira                                   # restaura o estado da Ana, nao so limpa
    repo.desfazer_ultima_decisao(a)
    assert _estado(repo, a) == {"verificado": 0, "status_final": None, "verificado_por": None, "observacao": None}
    with pytest.raises(SystemExit, match="Nada a desfazer"):
        repo.desfazer_ultima_decisao(a)
    desfeitas = [x[0] for x in repo.conn.execute("SELECT desfeita FROM achados_revisoes WHERE achado_id=? ORDER BY revisao_id", (a,))]
    assert desfeitas == [1, 1]                                            # o historico continua la, marcado


def test_desfazer_so_atinge_decisoes_do_painel_nao_a_importacao(repo):
    import pandas as pd
    a = _ids(repo)[0]
    repo.importar_verificacao_achados(pd.DataFrame([(a, 1, "em_uso", "r1", None)], columns=["achado_id", "verificado", "status_final", "verificado_por", "observacao"]), PERMITIDOS)
    with pytest.raises(SystemExit, match="Nada a desfazer"):
        repo.desfazer_ultima_decisao(a)
    assert _estado(repo, a)["verificado"] == 1


def test_revogar_tambem_pode_ser_desfeito(repo):
    a = _ids(repo)[0]
    repo.verificar_achado(a, "em_uso", "Ana", None, PERMITIDOS)
    repo.desverificar_achado(a, "Ana", "engano")
    assert _estado(repo, a)["verificado"] == 0
    repo.desfazer_ultima_decisao(a)
    assert _estado(repo, a)["status_final"] == "em_uso"


def test_decisao_do_painel_aparece_na_secretarias_e_no_resumo_na_hora(repo):
    a = _ids(repo)[0]
    antes = repo.conn.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0]
    repo.verificar_achado(a, "piloto", "Ana", None, PERMITIDOS)
    assert repo.conn.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0] == antes + 1
    repo.verificar_achado(a, "descartado", "Ana", None, PERMITIDOS)
    assert repo.conn.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0] == antes


def test_copia_de_seguranca_e_consistente_e_guarda_so_as_ultimas(repo, tmp_path):
    a = _ids(repo)[0]
    repo.verificar_achado(a, "em_uso", "Ana", None, PERMITIDOS)
    pasta = tmp_path / "bk"
    import sqlite3
    from pathlib import Path
    copias = [repo.copia_de_seguranca(pasta, manter=2) for _ in range(4)]      # no mesmo segundo: nomes distintos
    destino = copias[-1]
    assert len(set(copias)) == 4
    assert sorted(p.name for p in pasta.glob("*.db")) == sorted(Path(c).name for c in copias[-2:])
    assert sqlite3.connect(destino).execute("SELECT verificado FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == 1


def test_copia_com_nome_antigo_em_segundos_sai_primeiro_no_rodizio(repo, tmp_path):
    """Nomes antigos (so segundos) e novos (com microssegundos) convivem: a ordem dos nomes continua a ordem das copias."""
    from pathlib import Path
    pasta = tmp_path / "bk"
    pasta.mkdir()
    nome = Path(repo.conn.execute("PRAGMA database_list").fetchone()["file"]).stem
    antiga = pasta / f"{nome}_painel_20200101_000000.db"
    antiga.write_bytes(b"")
    novas = [repo.copia_de_seguranca(pasta, manter=2) for _ in range(2)]
    assert not antiga.exists()
    assert sorted(p.name for p in pasta.glob("*.db")) == sorted(Path(c).name for c in novas)
    assert all(len(Path(c).stem.rsplit("_", 3)[-1]) == 6 for c in novas)    # microssegundos com 6 digitos


def test_migracao_acrescenta_colunas_de_desfazer_em_banco_antigo(tmp_path):
    import sqlite3
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    db = sqlite3.connect(tmp_path / "velho.db")
    db.executescript("CREATE TABLE achados_revisoes (revisao_id INTEGER PRIMARY KEY AUTOINCREMENT, achado_id INTEGER NOT NULL, "
                     "verificado_por TEXT NOT NULL, status_final TEXT, observacao TEXT, importado_em TEXT NOT NULL);")
    db.close()
    r = RepositorioSQLite(tmp_path / "velho.db")
    assert {"anterior_json", "desfeita"} <= {l["name"] for l in r.conn.execute("PRAGMA table_info(achados_revisoes)")}


# ---------- leitura do painel ----------
def test_leitura_e_somente_leitura_e_nao_cria_banco(repo, tmp_path):
    import sqlite3
    caminho = repo.conn.execute("PRAGMA database_list").fetchone()["file"]
    leitura = LeituraPainelSQLite(caminho)
    assert leitura.funil()["achados"] == len(_ids(repo))
    with pytest.raises(sqlite3.OperationalError):
        leitura._consulta("DELETE FROM achados")
    inexistente = LeituraPainelSQLite(tmp_path / "nao_existe.db")
    assert not inexistente.existe()
    with pytest.raises(sqlite3.OperationalError):
        inexistente.funil()
    assert not (tmp_path / "nao_existe.db").exists()


def test_leitura_filtros_combinam_e_paginacao_tem_teto(repo):
    caminho = repo.conn.execute("PRAGMA database_list").fetchone()["file"]
    l = LeituraPainelSQLite(caminho)
    todos = l.achados({})
    assert todos["total"] == len(_ids(repo)) and todos["por_pagina"] == 50
    assert l.achados({}, por_pagina=100000)["por_pagina"] == 200
    assert l.achados({"uf": "PI"})["total"] == todos["total"] and l.achados({"uf": "CE"})["total"] == 0
    assert l.achados({"uf": "PI", "verificacao": "confirmado"})["total"] == 0
    a = _ids(repo)[0]
    repo.verificar_achado(a, "piloto", "Ana", None, PERMITIDOS)
    assert l.achados({"verificacao": "confirmado"})["total"] == 1
    assert l.achados({"verificacao": "pendente"})["total"] == todos["total"] - 1
    assert a not in l.ids_fila_revisao({}) and len(l.ids_fila_revisao({})) == todos["total"] - 1
    assert l.achados({"q": "%"})["total"] == 0                     # curinga do LIKE e tratado como texto
    assert l.achados({"pagina": 1, "uf": "PI"}, pagina=99)["itens"] == []


def test_leitura_detalhe_do_achado(repo):
    caminho = repo.conn.execute("PRAGMA database_list").fetchone()["file"]
    l = LeituraPainelSQLite(caminho)
    a = _ids(repo)[0]
    d = l.achado(a)
    assert d["achado_id"] == a and d["url"] and d["classificador"] and d["no_relatorio"] == 1
    assert l.achado(424242) is None
    assert l.historico_achado(a) == [] and not l.tem_decisao_para_desfazer(a)
    repo.verificar_achado(a, "em_uso", "Ana", None, PERMITIDOS)
    assert l.tem_decisao_para_desfazer(a) and l.historico_achado(a)[0]["verificado_por"] == "Ana"
