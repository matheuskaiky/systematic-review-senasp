import json
import sqlite3

import pytest

from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao.comum import registrar_chamada
from dominio.modelos import RegistroChamada

TABELAS = {"execucoes", "metricas_run", "saldos", "chamadas", "artigos", "ocorrencias", "triagem",
           "buscas_manuais", "urls", "resultados_web", "selecao_download", "paginas",
           "classificacoes", "achados"}
VISOES = {"v_funil", "v_custos", "v_falhas", "v_dominios", "v_metricas_busca_web", "v_descartes",
          "v_achados_revisao", "v_resumo_uf", "v_metricas_por_termo", "v_artigos_por_ano",
          "v_artigos_multi_termo", "v_sobreposicao_termos", "v_manuais_resumo"}


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(tmp_path / "teste.db")


def _iniciar(repo, hash_="h1", **kw):
    return repo.iniciar_execucao("teste", hash_, "{}", "abc1234", **kw)


def _reg(sucesso=True, raw=None, raw_ext="json"):
    return RegistroChamada(provedor="p", operacao="op", parametros={"q": "x"}, requisitado_em="2026-01-01T00:00:00+00:00",
                           http_status=200 if sucesso else 500, latencia_ms=10,
                           erro=None if sucesso else "HTTP 500", raw=raw, raw_ext=raw_ext)


def _chamada(repo, run_id, chave="k1", sucesso=True):
    return repo.salvar_chamada(run_id=run_id, etapa="busca_web", alvo_tipo="consulta_web", alvo_id="c1",
                               chave=chave, registro=_reg(sucesso), raw_path=None, raw_sha256=None)


# ---------- schema ----------
def test_schema_cria_todas_as_tabelas_e_visoes(repo):
    nomes = lambda tipo: {l[0] for l in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type=?", (tipo,)).fetchall()}
    assert TABELAS <= nomes("table")
    assert VISOES <= nomes("view")


def test_schema_e_idempotente_ao_reabrir(tmp_path):
    RepositorioSQLite(tmp_path / "a.db")
    RepositorioSQLite(tmp_path / "a.db")


def test_visoes_executam_em_banco_vazio(repo):
    for v in VISOES:
        repo.conn.execute(f"SELECT * FROM {v}").fetchall()


# ---------- execucoes ----------
def test_iniciar_e_finalizar_execucao_guarda_metricas(repo):
    run_id = _iniciar(repo)
    _chamada(repo, run_id, "k1", True)
    _chamada(repo, run_id, "k2", False)
    repo.finalizar_execucao(run_id, "concluida")
    linha = repo.conn.execute("SELECT * FROM execucoes WHERE run_id=?", (run_id,)).fetchone()
    assert linha["status"] == "concluida" and linha["finalizado_em"]
    assert linha["config_hash"] == "h1" and linha["commit_git"] == "abc1234"
    m = json.loads(linha["metricas_json"])
    assert (m["chamadas"], m["sucesso"], m["falhas"]) == (2, 1, 1)


def test_retomar_com_mesmo_hash_devolve_o_mesmo_run_id(repo):
    run_id = _iniciar(repo)
    repo.finalizar_execucao(run_id, "interrompida")
    assert _iniciar(repo, retomar=run_id) == run_id
    status = repo.conn.execute("SELECT status FROM execucoes WHERE run_id=?", (run_id,)).fetchone()[0]
    assert status == "em_andamento"


def test_retomar_com_hash_diferente_encerra(repo):
    run_id = _iniciar(repo, "h1")
    with pytest.raises(SystemExit):
        _iniciar(repo, "h2", retomar=run_id)


def test_retomar_run_inexistente_encerra(repo):
    with pytest.raises(SystemExit):
        _iniciar(repo, retomar="nao_existe")


# ---------- C5: run_origem ----------
def test_run_origem_e_guardado(repo):
    origem = _iniciar(repo)
    run_id = _iniciar(repo, run_origem=origem)
    assert repo.obter_run_origem(run_id) == origem
    assert repo.obter_run_origem(origem) is None


def test_de_inexistente_encerra_com_mensagem(repo):
    with pytest.raises(SystemExit) as e:
        _iniciar(repo, run_origem="nao_existe")
    assert "nao_existe" in str(e.value)


def test_retomar_sem_de_preserva_run_origem_guardado(repo):
    origem = _iniciar(repo)
    run_id = _iniciar(repo, run_origem=origem)
    assert _iniciar(repo, retomar=run_id) == run_id
    assert repo.obter_run_origem(run_id) == origem


def test_retomar_com_de_novo_atualiza_run_origem(repo):
    o1, o2 = _iniciar(repo), _iniciar(repo)
    run_id = _iniciar(repo, run_origem=o1)
    _iniciar(repo, retomar=run_id, run_origem=o2)
    assert repo.obter_run_origem(run_id) == o2


# ---------- chamadas e indice de idempotencia ----------
def test_indice_aceita_falha_seguida_de_sucesso_e_rejeita_dois_sucessos(repo):
    run_id = _iniciar(repo)
    _chamada(repo, run_id, "k", sucesso=False)
    _chamada(repo, run_id, "k", sucesso=True)
    repo.confirmar()
    assert repo.ja_feito(run_id, "k")
    with pytest.raises(sqlite3.IntegrityError):
        _chamada(repo, run_id, "k", sucesso=True)


def test_ja_feito_so_considera_sucesso(repo):
    run_id = _iniciar(repo)
    _chamada(repo, run_id, "k", sucesso=False)
    assert not repo.ja_feito(run_id, "k")
    assert not repo.ja_feito("outro_run", "k")


def test_mesma_chave_em_runs_diferentes_e_permitida(repo):
    r1, r2 = _iniciar(repo), _iniciar(repo)
    _chamada(repo, r1, "k")
    _chamada(repo, r2, "k")


def test_atualizar_chamada_so_aceita_campos_permitidos(repo):
    run_id = _iniciar(repo)
    cid = _chamada(repo, run_id)
    repo.atualizar_chamada(cid, total_reportado=10, n_retornados=3, n_novos=2)
    linha = repo.conn.execute("SELECT * FROM chamadas WHERE chamada_id=?", (cid,)).fetchone()
    assert (linha["total_reportado"], linha["n_retornados"], linha["n_novos"]) == (10, 3, 2)
    with pytest.raises(AssertionError):
        repo.atualizar_chamada(cid, sucesso=0)


def test_registrar_metrica_e_saldo(repo):
    run_id = _iniciar(repo)
    repo.registrar_metrica(run_id, "x", 1)
    repo.registrar_metrica(run_id, "x", 2)
    repo.registrar_saldo(run_id, "serpapi_scholar", "inicio", 100)
    assert repo.conn.execute("SELECT valor FROM metricas_run WHERE chave='x'").fetchone()[0] == 2
    assert repo.conn.execute("SELECT valor FROM saldos").fetchone()[0] == 100


# ---------- registrar_chamada (aplicacao/comum.py) e BrutoLocal ----------
def test_registrar_chamada_troca_segredo_por_asteriscos_no_raw_json(repo, tmp_path):
    bruto = BrutoLocal(tmp_path / "raw")
    run_id = _iniciar(repo)
    segredo = "SEGREDO-FALSO-123"
    reg = _reg(raw=json.dumps({"url": f"https://x?api_key={segredo}", "ok": 1}).encode())
    cid, raw_path = registrar_chamada(repo, bruto, run_id, "busca_web", "consulta_web", "c1", "k" * 40,
                                      reg, [segredo], uf="PI")
    gravado = bruto.ler(raw_path)
    assert segredo.encode() not in gravado and b"***" in gravado
    linha = repo.conn.execute("SELECT * FROM chamadas WHERE chamada_id=?", (cid,)).fetchone()
    assert linha["raw_path"] == raw_path and linha["uf"] == "PI" and linha["sucesso"] == 1
    assert len(linha["raw_sha256"]) == 64


def test_registrar_chamada_nao_mexe_em_raw_binario(repo, tmp_path):
    bruto = BrutoLocal(tmp_path / "raw")
    run_id = _iniciar(repo)
    reg = _reg(raw=b"%PDF-SEGREDO-FALSO", raw_ext="pdf")
    _, raw_path = registrar_chamada(repo, bruto, run_id, "download", "url", "1", "k" * 40, reg, ["SEGREDO-FALSO"])
    assert bruto.ler(raw_path) == b"%PDF-SEGREDO-FALSO"


def test_registrar_chamada_sem_raw(repo, tmp_path):
    bruto = BrutoLocal(tmp_path / "raw")
    run_id = _iniciar(repo)
    cid, raw_path = registrar_chamada(repo, bruto, run_id, "download", "url", "1", "k" * 40, _reg(raw=None), [])
    assert raw_path is None
    assert repo.conn.execute("SELECT raw_path FROM chamadas WHERE chamada_id=?", (cid,)).fetchone()[0] is None


def test_bruto_local_duas_gravacoes_com_a_mesma_chave_geram_dois_arquivos(tmp_path):
    bruto = BrutoLocal(tmp_path)
    p1, sha1 = bruto.salvar("busca_web", "run1", "a" * 40, b"primeira", "json")
    p2, sha2 = bruto.salvar("busca_web", "run1", "a" * 40, b"segunda", "json")
    assert p1 != p2
    assert bruto.ler(p1) == b"primeira" and bruto.ler(p2) == b"segunda"
    assert sha1 != sha2 and len(sha1) == 64


def test_bruto_local_devolve_caminho_relativo(tmp_path):
    bruto = BrutoLocal(tmp_path)
    caminho, _ = bruto.salvar("texto", "run1", "b" * 40, "olá".encode(), "txt")
    assert not caminho.startswith(("/", str(tmp_path)))
    assert (tmp_path / caminho).exists()
