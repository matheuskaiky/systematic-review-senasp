"""`migrar-robots`: separa, nas chamadas de download ja gravadas, a proibicao do site do robots.txt inacessivel; e como a view, a
leitura de opacidade e o painel tratam os dois motivos. Bancos temporarios; nenhuma rede."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_leitura_analises import Minimo, _sql  # noqa: E402

import main  # noqa: E402
import config.settings as S  # noqa: E402
from adaptadores.leitura_sqlite import LeituraPainelSQLite  # noqa: E402
from adaptadores.repositorio_sqlite import RepositorioSQLite  # noqa: E402
from painel import analises_blocos as b  # noqa: E402

OUTRA = "https://b.example/final"


def _download(m, dominio, erro, extras, http=None, ok=0):
    u = m.url(dominio)
    _sql(m.caminho, "INSERT INTO selecao_download (run_id, url_id, uf, selecionada) VALUES (?,?,?,1)", (m.run, u, "PI"))
    cid = m.chamada("download", "requests", u, sucesso=ok, http=http, erro=erro)
    _sql(m.caminho, "UPDATE chamadas SET extras_json=? WHERE chamada_id=?", (json.dumps(extras) if extras is not None else None, cid))
    if ok:
        _sql(m.caminho, "INSERT INTO paginas (run_id, url_id, chamada_id, extracao_ok, dominio_final) VALUES (?,?,?,1,?)", (m.run, u, cid, dominio))
    return cid


@pytest.fixture
def banco(tmp_path):
    """Chamadas bloqueadas como o banco real as tem: robots.txt lido (200), com 5xx e sem status; mais as variantes de
    redirecionamento, uma chamada ja nova, uma 403 e um bloqueio com outro status."""
    m = Minimo(tmp_path / "data" / "busca.db")
    ids = {}
    ids["p200"] = _download(m, "a.gov.br", "bloqueado_por_robots", {"robots_permitido": False, "robots_status": 200})
    ids["s503"] = _download(m, "a.gov.br", "bloqueado_por_robots", {"robots_permitido": False, "robots_status": 503})
    ids["s500"] = _download(m, "b.gov.br", "bloqueado_por_robots", {"robots_permitido": False, "robots_status": 500, "chave_extra": "x"})
    ids["nulo"] = _download(m, "b.gov.br", "bloqueado_por_robots", {"robots_permitido": False, "robots_status": None})
    ids["sem_chave"] = _download(m, "b.gov.br", "bloqueado_por_robots", {"robots_permitido": False})
    ids["sem_extras"] = _download(m, "c.gov.br", "bloqueado_por_robots", None)
    ids["salto200"] = _download(m, "c.gov.br", f"bloqueado_por_robots_apos_redirecionamento: {OUTRA}",
                                {"robots_permitido": True, "robots_status": 404, "robots_salto_1_permitido": False,
                                 "robots_salto_1_status": 200, "redirecionamentos": ["x", OUTRA]})
    ids["salto503"] = _download(m, "c.gov.br", f"bloqueado_por_robots_apos_redirecionamento: {OUTRA}",
                                {"robots_permitido": True, "robots_status": 404, "robots_salto_1_permitido": True,
                                 "robots_salto_1_status": 404, "robots_salto_2_permitido": False, "robots_salto_2_status": 503})
    ids["salto_nulo"] = _download(m, "c.gov.br", f"bloqueado_por_robots_apos_redirecionamento: {OUTRA}",
                                  {"robots_permitido": True, "robots_salto_1_permitido": False, "robots_salto_1_status": None})
    ids["http403"] = _download(m, "d.gov.br", "HTTP 403", {"robots_permitido": True}, http=403)
    ids["ja_nova"] = _download(m, "d.gov.br", "robots_inacessivel", {"robots_inacessivel": True, "robots_status": 503})
    ids["status404"] = _download(m, "d.gov.br", "bloqueado_por_robots", {"robots_permitido": False, "robots_status": 404})
    ids["ok"] = _download(m, "d.gov.br", None, {"robots_permitido": True, "robots_status": 200}, http=200, ok=1)
    m.ids = ids
    return m


def _estado(caminho):
    conn = sqlite3.connect(caminho)
    try:
        return {r[0]: (r[1], r[2]) for r in conn.execute("SELECT chamada_id, erro, extras_json FROM chamadas")}
    finally:
        conn.close()


def _outras_tabelas(caminho):
    conn = sqlite3.connect(caminho)
    try:
        return {t: conn.execute(f"SELECT * FROM {t}").fetchall() for (t,) in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'chamadas'")}
    finally:
        conn.close()


def test_dry_run_conta_e_nao_muda_nada(banco):
    antes, tabelas = _estado(banco.caminho), _outras_tabelas(banco.caminho)
    repo = RepositorioSQLite(banco.caminho)
    r = repo.reclassificar_bloqueios_robots()
    assert r["total"] == 10 and r["atualizadas"] == 0 and r["backup"] is None
    assert r["por_classe"] == {"status_2xx": 2, "status_5xx": 3, "sem_status": 4, "outro_status": 1}
    assert (r["mantidas_proibido"], r["para_inacessivel"], r["outro_status"]) == (2, 7, 1)
    assert _estado(banco.caminho) == antes and _outras_tabelas(banco.caminho) == tabelas
    assert not (banco.caminho.parent / "backups").exists()


def test_aplicar_muda_exatamente_as_linhas_esperadas(banco):
    antes = _estado(banco.caminho)
    r = RepositorioSQLite(banco.caminho).reclassificar_bloqueios_robots(aplicar=True)
    depois = _estado(banco.caminho)
    i = banco.ids
    assert r["atualizadas"] == 7 and r["total"] == 10
    esperado = {"s503": "robots_inacessivel", "s500": "robots_inacessivel", "nulo": "robots_inacessivel",
                "sem_chave": "robots_inacessivel", "sem_extras": "robots_inacessivel",
                "salto503": f"robots_inacessivel_apos_redirecionamento: {OUTRA}",
                "salto_nulo": f"robots_inacessivel_apos_redirecionamento: {OUTRA}"}
    for nome, erro in esperado.items():
        novo_erro, extras = depois[i[nome]]
        assert novo_erro == erro, nome
        e = json.loads(extras)
        assert e["robots_inacessivel"] is True and e["erro_anterior"] == antes[i[nome]][0], nome
    assert json.loads(depois[i["s500"]][1])["chave_extra"] == "x" and json.loads(depois[i["s503"]][1])["robots_status"] == 503
    for nome in set(i) - set(esperado):                                       # as demais ficam exatamente como estavam
        assert depois[i[nome]] == antes[i[nome]], nome


def test_aplicar_faz_backup_antes_e_so_mexe_em_chamadas(banco):
    antes, tabelas = _estado(banco.caminho), _outras_tabelas(banco.caminho)
    r = RepositorioSQLite(banco.caminho).reclassificar_bloqueios_robots(aplicar=True)
    copia = Path(r["backup"])
    assert copia.parent == banco.caminho.parent / "backups" and copia.name.startswith("busca_antes_migrar_robots_") and copia.suffix == ".db"
    conn = sqlite3.connect(copia)
    assert {c: (e, x) for c, e, x in conn.execute("SELECT chamada_id, erro, extras_json FROM chamadas")} == antes     # copia = estado anterior
    conn.close()
    assert _outras_tabelas(banco.caminho) == tabelas


def test_e_idempotente(banco):
    repo = RepositorioSQLite(banco.caminho)
    repo.reclassificar_bloqueios_robots(aplicar=True)
    apos_primeira = _estado(banco.caminho)
    segunda = repo.reclassificar_bloqueios_robots(aplicar=True)
    assert segunda["atualizadas"] == 0 and segunda["backup"] is None and segunda["total"] == 3     # 2 proibidas (2xx) + 1 com outro status
    assert _estado(banco.caminho) == apos_primeira
    assert len(list((banco.caminho.parent / "backups").glob("*.db"))) == 1


def test_aplicar_numa_so_transacao_desfaz_tudo_se_falhar(banco, monkeypatch):
    repo = RepositorioSQLite(banco.caminho)
    antes = _estado(banco.caminho)
    original = repo.conn

    class Falha:
        def __getattr__(self, nome):
            return getattr(original, nome)

        def executemany(self, sql, dados):
            original.executemany(sql, list(dados)[:2])
            raise sqlite3.OperationalError("falha simulada")

    repo.conn = Falha()
    with pytest.raises(sqlite3.OperationalError):
        repo.reclassificar_bloqueios_robots(aplicar=True)
    repo.conn = original
    assert _estado(banco.caminho) == antes


def test_a_view_separa_proibicao_e_robots_inacessivel(banco):
    motivos = lambda: {c: m for c, m in _sql(banco.caminho, "SELECT chamada_id, motivo FROM v_resultado_download")}
    # antes: o valor antigo continua contando como proibicao (comportamento conservador ate migrar)
    assert sorted(set(motivos().values()), key=str) == sorted({"bloqueado_por_robots", "robots_inacessivel", "http_403", "ok"}, key=str)
    RepositorioSQLite(banco.caminho).reclassificar_bloqueios_robots(aplicar=True)
    i, m = banco.ids, motivos()
    assert m[i["s503"]] == m[i["salto503"]] == m[i["ja_nova"]] == "robots_inacessivel"
    assert m[i["p200"]] == m[i["salto200"]] == m[i["status404"]] == "bloqueado_por_robots"


def test_opacidade_conta_proibicao_real_e_robots_inacessivel_separados(banco):
    L = LeituraPainelSQLite(banco.caminho)
    antes = L.analise_opacidade_dominios()
    assert antes["n_robots"] == 10 and antes["n_robots_inacessivel"] == 1            # valor antigo: tudo como proibicao (+1 ja nova)
    RepositorioSQLite(banco.caminho).reclassificar_bloqueios_robots(aplicar=True)
    r = LeituraPainelSQLite(banco.caminho).analise_opacidade_dominios()
    assert (r["n_tentadas"], r["n_ok"], r["n_robots"], r["n_http_bloqueio"], r["n_robots_inacessivel"], r["n_outros"]) == (13, 1, 3, 1, 8, 0)
    assert r["n_tentadas"] == r["n_ok"] + r["n_robots"] + r["n_http_bloqueio"] + r["n_robots_inacessivel"] + r["n_outros"]
    assert r["pct_bloqueado"] == round(100 * 4 / 13, 1) and r["pct_inacessivel"] == round(100 * 8 / 13, 1)
    por = {d["dominio"]: d for d in r["dominios"]}
    assert por["a.gov.br"]["n_robots"] == 1 and por["a.gov.br"]["n_robots_inacessivel"] == 1
    assert por["c.gov.br"]["n_robots"] == 1 and por["c.gov.br"]["n_robots_inacessivel"] == 3
    assert {m["motivo"]: m["n"] for m in r["motivos"]}["robots_inacessivel"] == 8


def test_bloco_do_painel_separa_proibido_de_inacessivel(banco):
    RepositorioSQLite(banco.caminho).reclassificar_bloqueios_robots(aplicar=True)
    bl = b.bloco_opacidade(LeituraPainelSQLite(banco.caminho).analise_opacidade_dominios())
    assert "proibidas pelo site" in bl["titulo"] and "robots.txt do site estava inacessível" in bl["titulo"]
    assert "apagão" not in bl["titulo"].lower() and "opacidade" not in bl["titulo"].lower()
    html = str(bl["grafico"])
    assert "robots.txt inacessível (bloqueado pela política)" in html                # coluna propria na tabela
    pares = dict(bl["pares"])
    assert pares["Proibido pelo site"] == "4" and pares["robots.txt inacessível (bloqueado pela política)"] == "8"
    assert "robots.txt inacessível (bloqueado pela política)" in bl["subtitulo"]
    assert any("não é decisão do site" in t for t in bl["texto"])


def test_bloco_sem_robots_inacessivel_nao_menciona_a_coluna_nem_o_trecho(banco):
    d = {"n_tentadas": 5, "n_ok": 3, "n_robots": 1, "n_http_bloqueio": 1, "n_robots_inacessivel": 0, "n_outros": 0, "pct_bloqueado": 40.0,
         "n_dominios": 1, "dominios": [{"dominio": "a.gov.br", "n_tentadas": 5, "n_robots": 1, "n_http_bloqueio": 1, "n_robots_inacessivel": 0}]}
    bl = b.bloco_opacidade(d)
    assert "inacessível" not in bl["titulo"] and "<th scope=\"col\" class=\"num\">robots.txt inacessível" in str(bl["grafico"])    # coluna aparece (chave presente)
    assert "40% das 5 páginas tentadas foram proibidas pelo site" in bl["titulo"]


# ---------- comando de linha ----------
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.fixture
def banco_simulado(ambiente_cli):
    m = Minimo(S.DATA_DIR / "simulado.db")
    _download(m, "a.gov.br", "bloqueado_por_robots", {"robots_status": 200})
    _download(m, "b.gov.br", "bloqueado_por_robots", {"robots_status": 503})
    _download(m, "c.gov.br", "bloqueado_por_robots", None)
    return m


def test_cli_migrar_robots_so_mostra_sem_aplicar(banco_simulado, monkeypatch, capsys):
    antes = _estado(banco_simulado.caminho)
    _rodar(monkeypatch, "migrar-robots", "--simulado")
    saida = capsys.readouterr().out
    assert "Chamadas de download com 'bloqueado_por_robots': 3" in saida
    assert "(HTTP 2xx)" in saida and ": 1\n" in saida and "Nada foi alterado" in saida and "--aplicar" in saida
    assert _estado(banco_simulado.caminho) == antes


def test_cli_migrar_robots_aplicar_faz_backup_e_depois_nao_ha_o_que_fazer(banco_simulado, monkeypatch, capsys):
    _rodar(monkeypatch, "migrar-robots", "--simulado", "--aplicar")
    saida = capsys.readouterr().out
    assert "Cópia de segurança:" in saida and "Chamadas atualizadas: 2" in saida
    erros = sorted(e for e, _ in _estado(banco_simulado.caminho).values())
    assert erros == ["bloqueado_por_robots", "robots_inacessivel", "robots_inacessivel"]
    backups = list((S.DATA_DIR / "backups").glob("simulado_antes_migrar_robots_*.db"))
    assert len(backups) == 1
    _rodar(monkeypatch, "migrar-robots", "--simulado", "--aplicar")
    assert "Nada a atualizar" in capsys.readouterr().out
    assert len(list((S.DATA_DIR / "backups").glob("*.db"))) == 1
