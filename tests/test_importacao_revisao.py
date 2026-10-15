"""Importacao da revisao humana (achados e triagem): validacao antes de gravar, normalizacao, execucoes fora do relatorio,
desfazer verificacao, fila de revisao e ordem por citacoes."""
import hashlib
import logging

import pandas as pd
import pytest

from adaptadores import classificador_openai_compat as modulo_openai
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import vocabulario as V
from dados_metricas import construir_classificacao_mista, construir_web
from test_adaptadores_alternativos import _chamar, _entrada, _fix, _instr, _openai

PERMITIDOS = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def repo_achados(tmp_path, silencio):
    repo, run_id = construir_classificacao_mista(tmp_path)
    return repo, run_id


def _ids(repo):
    return [r[0] for r in repo.conn.execute("SELECT achado_id FROM achados ORDER BY achado_id")]


def _df(*linhas):
    return pd.DataFrame(linhas, columns=["achado_id", "verificado", "status_final", "verificado_por", "observacao"])


def _verificados(repo):
    return repo.conn.execute("SELECT COUNT(*) FROM achados WHERE verificado=1").fetchone()[0]


# ---------- 2. identificadores inexistentes ----------
def test_achado_inexistente_encerra_com_id_e_linha_e_nao_grava_nada(repo_achados):
    repo, _ = repo_achados
    a = _ids(repo)[0]
    df = _df((a, 1, "em_uso", "r1", None), (99999, 1, "em_uso", "r1", None))
    with pytest.raises(SystemExit) as e:
        repo.importar_verificacao_achados(df, PERMITIDOS)
    assert "Achado inexistente: 99999 (linha 3)" in str(e.value)
    assert _verificados(repo) == 0                                                    # a linha valida tambem nao entrou


def test_achado_id_que_nao_e_numero_encerra_com_linha(repo_achados):
    repo, _ = repo_achados
    with pytest.raises(SystemExit) as e:
        repo.importar_verificacao_achados(_df(("abc", 1, "em_uso", "r1", None)), PERMITIDOS)
    assert "achado_id invalido" in str(e.value) and "linha 2" in str(e.value)


def test_status_invalido_depois_de_linha_valida_nao_deixa_gravacao_parcial(repo_achados):
    repo, _ = repo_achados
    a, b = _ids(repo)[:2]
    with pytest.raises(SystemExit) as e:
        repo.importar_verificacao_achados(_df((a, 1, "em_uso", "r1", None), (b, 1, "inventado", "r1", None)), PERMITIDOS)
    assert "linha 3" in str(e.value) and "inventado" in str(e.value)
    assert _verificados(repo) == 0


def test_artigo_inexistente_na_triagem_encerra_com_id_e_linha(tmp_path, silencio):
    repo = RepositorioSQLite(tmp_path / "a.db")
    df = pd.DataFrame([{"artigo_id": 12345, "decisao": "incluir", "motivo": None, "confirmado_em_base": None,
                        "link_confirmado": None, "revisor": "r1"}])
    with pytest.raises(SystemExit) as e:
        repo.importar_triagem(df)
    assert "Artigo inexistente: 12345 (linha 2)" in str(e.value)
    assert repo.conn.execute("SELECT COUNT(*) FROM triagem").fetchone()[0] == 0


# ---------- 3. normalizacao de status_final ----------
@pytest.mark.parametrize("digitado", ["Em_Uso", "em_uso ", " EM_USO", "em_uso\n"])
def test_status_final_e_normalizado_como_a_triagem(repo_achados, digitado):
    repo, _ = repo_achados
    a = _ids(repo)[0]
    assert repo.importar_verificacao_achados(_df((a, 1, digitado, "r1", None)), PERMITIDOS) == 1
    assert repo.conn.execute("SELECT status_final FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == "em_uso"


def test_status_final_invalido_mostra_o_valor_entre_aspas(repo_achados):
    repo, _ = repo_achados
    with pytest.raises(SystemExit) as e:
        repo.importar_verificacao_achados(_df((_ids(repo)[0], 1, "inventado ", "r1", None)), PERMITIDOS)
    assert "'inventado'" in str(e.value)


def test_verificado_sem_status_final_e_recusado(repo_achados):
    repo, _ = repo_achados
    with pytest.raises(SystemExit) as e:
        repo.importar_verificacao_achados(_df((_ids(repo)[0], 1, None, "r1", None)), PERMITIDOS)
    assert "status_final" in str(e.value)


# ---------- 1. execucao fora do relatorio ----------
def test_fila_de_revisao_nao_traz_achados_de_execucao_fora_do_relatorio(tmp_path, silencio):
    repo, run1 = construir_web(tmp_path)
    _, run2 = construir_web(tmp_path, repo=repo)
    antes = repo.conn.execute("SELECT COUNT(*) FROM v_achados_revisao").fetchone()[0]
    repo.definir_no_relatorio(run2, False, "piloto")
    depois = repo.conn.execute("SELECT COUNT(*) FROM v_achados_revisao").fetchone()[0]
    assert 0 < depois < antes
    assert {r[0] for r in repo.conn.execute("SELECT run_id FROM v_achados_revisao")} == {run1}
    assert "Achados" in repo.tabelas_para_exportacao()


def test_importar_verificacao_de_execucao_fora_do_relatorio_avisa_e_grava(tmp_path, caplog):
    repo, run1 = construir_web(tmp_path)
    _, run2 = construir_web(tmp_path, repo=repo)
    repo.definir_no_relatorio(run2, False, "piloto")
    confirmadas = repo.conn.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0]
    fora = repo.conn.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                                WHERE k.run_id=?""", (run2,)).fetchone()[0]
    with caplog.at_level(logging.WARNING):
        assert repo.importar_verificacao_achados(_df((fora, 1, "em_uso", "r1", None)), PERMITIDOS) == 1
    assert any("fora do relatorio" in r.message and str(fora) in r.message for r in caplog.records)
    assert repo.conn.execute("SELECT verificado FROM achados WHERE achado_id=?", (fora,)).fetchone()[0] == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0] == confirmadas   # nao conta


# ---------- 4. desfazer a verificacao ----------
def test_linha_com_verificado_zero_na_planilha_nao_revoga(repo_achados):
    """Uma planilha exportada antes do trabalho de outro revisor traz verificado=0 e nao pode apagar o que ele fez."""
    repo, _ = repo_achados
    a = _ids(repo)[0]
    repo.importar_verificacao_achados(_df((a, 1, "em_uso", "r1", None)), PERMITIDOS)
    assert repo.importar_verificacao_achados(_df((a, 0, None, None, None)), PERMITIDOS) == 0
    assert repo.conn.execute("SELECT verificado FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == 1


def test_desverificar_achado_restaura_e_deixa_historico(repo_achados):
    repo, _ = repo_achados
    a = _ids(repo)[0]
    repo.importar_verificacao_achados(_df((a, 1, "piloto", "r1", "obs")), PERMITIDOS)
    repo.desverificar_achado(a, "r1", "verificado por engano")
    linha = dict(repo.conn.execute("SELECT verificado, status_final, verificado_por, verificado_em FROM achados WHERE achado_id=?", (a,)).fetchone())
    assert linha == {"verificado": 0, "status_final": None, "verificado_por": None, "verificado_em": None}
    ultima = dict(repo.conn.execute("SELECT * FROM achados_revisoes WHERE achado_id=? ORDER BY revisao_id DESC", (a,)).fetchone())
    assert ultima["verificado_por"] == "r1" and ultima["status_final"] is None and "desfeita" in ultima["observacao"]
    assert repo.conn.execute("SELECT COUNT(*) FROM v_secretarias_confirmadas").fetchone()[0] == 0


def test_desverificar_achado_inexistente_ou_sem_verificacao_encerra(repo_achados):
    repo, _ = repo_achados
    with pytest.raises(SystemExit):
        repo.desverificar_achado(99999, "r1", "x")
    with pytest.raises(SystemExit):
        repo.desverificar_achado(_ids(repo)[0], "r1", "x")


# ---------- citacoes nulas ----------
def test_citacoes_nulas_ordenam_como_zero_nas_abas(tmp_path, silencio):
    repo = RepositorioSQLite(tmp_path / "c.db")
    for n, cit in enumerate([None, 5, 0, None, 2]):
        repo._inserir("artigos", chave_dedup=f"k{n}", titulo=f"t{n}", citacoes=cit, primeira_vez_em="2026-01-01")
    repo.conn.commit()
    t = repo.tabelas_para_exportacao()
    # nulo e zero empatam e o desempate e o artigo_id (artigos 2 e 5 tem 5 e 2 citacoes; 1 e 4 sao nulos; 3 e zero)
    assert list(t["Triagem"]["artigo_id"]) == [2, 5, 1, 3, 4]
    assert list(t["Artigos"]["artigo_id"]) == [2, 5, 1, 3, 4]


# ---------- openai_compat: hash do prompt e content_filter ----------
def test_hash_do_sistema_e_o_do_texto_realmente_enviado(monkeypatch):
    visto = _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sintetico.json"))
    for rf in (False, True):
        c = _openai(usar_response_format=rf).classificar(_entrada(), _instr()).chamada
        enviado = visto["json_body"]["messages"][0]["content"]
        assert c.parametros["sistema_sha256"] == hashlib.sha256(enviado.encode()).hexdigest()
    assert _openai(usar_response_format=False)._corpo(_instr())["messages"][0]["content"] != "SISTEMA"


def test_finish_reason_content_filter_e_falha_com_tokens_e_custo(monkeypatch):
    import json
    raw = json.dumps({"id": "x", "model": "m", "choices": [{"finish_reason": "content_filter", "message": {"content": '{"relevante": true, "achados": []}'}}],
                      "usage": {"prompt_tokens": 100, "completion_tokens": 7}})
    _chamar(modulo_openai, monkeypatch, raw)
    res = _openai(preco_entrada_por_m=1, preco_saida_por_m=2).classificar(_entrada(), _instr())
    assert res.chamada.erro == "resposta_bloqueada: content_filter" and not res.chamada.sucesso
    assert res.chamada.extras["finish_reason"] == "content_filter" and res.chamada.tokens_saida == 7
    assert res.chamada.custo_usd == pytest.approx((100 + 14) / 1e6) and res.achados == [] and not res.json_valido
