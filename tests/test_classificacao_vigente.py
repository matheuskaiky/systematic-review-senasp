"""Classificacao vigente por pagina: r_classificacoes, r_achados e r_achados_descartados trazem UMA classificacao por (url_id, uf),
entre as execucoes do relatorio. Ordem da regra: (a) achado verificado por humano, (b) JSON valido, (c) texto da pagina sobre snippet,
(d) a mais recente. O historico continua inteiro nas tabelas e em r_*_historico."""
import logging

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada, ClassificadorSimulado, ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, classificacao, download
from config import consultas as C, vocabulario as V
from dados_metricas import _consulta_pi, _novo_run, _params
from dominio.modelos import ArquivoBaixado
from painel.app import Contexto, criar_app


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


class Banco:
    """Banco com linhas escritas direto (sem estagios), para exercitar a regra. As chaves estrangeiras ficam desligadas: o que importa
    aqui sao as colunas lidas pelas views."""

    def __init__(self, caminho):
        self.repo = RepositorioSQLite(caminho)
        self.c = self.repo.conn
        self.c.execute("PRAGMA foreign_keys = OFF")
        self._n = 0

    def execucao(self, run_id, no_relatorio=1):
        self.c.execute("INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, no_relatorio) VALUES (?, '2026-10-16', 'h', '{}', ?)",
                       (run_id, no_relatorio))

    def url(self, url_id):
        self.c.execute("INSERT OR IGNORE INTO urls (url_id, url_normalizada, url_original, dominio, fonte_oficial) VALUES (?, ?, ?, 'x.gov.br', 1)",
                       (url_id, f"https://x.gov.br/{url_id}", f"https://x.gov.br/{url_id}"))

    def classificacao(self, run_id, url_id, uf="PI", origem="pagina", valido=1, achados=1, verificado=(), prompt="v3"):
        """Devolve (classificacao_id, [achado_id]). `verificado`: posicoes (0, 1, ...) dos achados ja verificados por humano."""
        self._n += 1
        self.url(url_id)
        self.c.execute("""INSERT INTO classificacoes (chamada_id, run_id, url_id, uf, origem_texto, json_valido, relevante, n_achados,
                          prompt_versao, classificador) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'duplo')""",
                       (self._n, run_id, url_id, uf, origem, valido, int(achados > 0), achados, prompt))
        cid = self.c.execute("SELECT MAX(classificacao_id) FROM classificacoes").fetchone()[0]
        ids = []
        for i in range(achados):
            v = int(i in verificado)
            self.c.execute("""INSERT INTO achados (classificacao_id, uf, tecnologia, status_reportado, evidencia, evidencia_confere, confianca,
                              verificado, status_final) VALUES (?, ?, 'outra_ia', 'em_uso', 'x', 1, 'alta', ?, ?)""",
                           (cid, uf, v, "em_uso" if v else None))
            ids.append(self.c.execute("SELECT MAX(achado_id) FROM achados").fetchone()[0])
        self.c.commit()
        return cid, ids

    def vigentes(self):
        return [l[0] for l in self.c.execute("SELECT classificacao_id FROM r_classificacoes ORDER BY classificacao_id")]

    def r_achados(self):
        return [l[0] for l in self.c.execute("SELECT achado_id FROM r_achados ORDER BY achado_id")]


@pytest.fixture
def banco(tmp_path):
    b = Banco(tmp_path / "v.db")
    b.execucao("r1")
    b.execucao("r2")
    return b


# ---------- (d) a mais recente ----------
def test_duas_classificacoes_validas_da_pagina_valem_a_mais_recente(banco):
    velha, ach_v = banco.classificacao("r1", 1, achados=2)
    nova, ach_n = banco.classificacao("r2", 1, achados=2)
    assert banco.vigentes() == [nova] and banco.r_achados() == ach_n
    assert [l[0] for l in banco.c.execute("SELECT classificacao_id FROM r_classificacoes_historico ORDER BY 1")] == [velha, nova]
    assert banco.c.execute("SELECT COUNT(*) FROM r_achados_historico").fetchone()[0] == 4      # o historico fica inteiro


def test_pares_diferentes_nao_se_substituem(banco):
    a, _ = banco.classificacao("r1", 1)
    b, _ = banco.classificacao("r2", 2)
    c, _ = banco.classificacao("r2", 1, uf="CE")
    assert banco.vigentes() == [a, b, c]


# ---------- (b) json valido ----------
def test_json_invalido_mais_novo_nao_substitui_o_valido(banco):
    boa, ach = banco.classificacao("r1", 1)
    banco.classificacao("r2", 1, valido=0, achados=0)
    assert banco.vigentes() == [boa] and banco.r_achados() == ach


def test_json_valido_mais_novo_substitui_o_invalido(banco):
    banco.classificacao("r1", 1, valido=0, achados=0)
    boa, ach = banco.classificacao("r2", 1)
    assert banco.vigentes() == [boa]
    assert banco.c.execute("SELECT COUNT(*) FROM v_classificacoes_invalidas").fetchone()[0] == 0      # nao e mais "invalida sem alternativa"


def test_so_invalidas_vale_a_mais_recente_e_aparece_em_classificacoes_invalidas(banco):
    banco.c.execute("INSERT INTO chamadas (chamada_id, run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em) "
                    "VALUES (1, 'r1', 'classificacao', 'p', '{}', 'k1', 'x'), (2, 'r2', 'classificacao', 'p', '{}', 'k2', 'x')")
    banco.classificacao("r1", 1, valido=0, achados=0)
    nova, _ = banco.classificacao("r2", 1, valido=0, achados=0)
    assert banco.vigentes() == [nova]
    assert [l[0] for l in banco.c.execute("SELECT classificacao_id FROM v_classificacoes_invalidas")] == [nova]


# ---------- (c) texto da pagina sobre snippet ----------
def test_snippet_mais_novo_nao_substitui_o_texto_completo_antigo(banco):
    pagina, ach = banco.classificacao("r1", 1, origem="pagina")
    banco.classificacao("r2", 1, origem="snippet")
    assert banco.vigentes() == [pagina] and banco.r_achados() == ach


def test_texto_completo_mais_novo_substitui_o_snippet_antigo_sem_orfaos(banco):
    """Pagina antes bloqueada pelo robots.txt (so snippet) e baixada depois: os achados do snippet saem das contagens."""
    snippet, ach_s = banco.classificacao("r1", 1, origem="snippet", achados=2)
    pagina, ach_p = banco.classificacao("r2", 1, origem="pagina", achados=1)
    assert banco.vigentes() == [pagina] and banco.r_achados() == ach_p
    assert banco.c.execute("SELECT COUNT(*) FROM v_status_url WHERE url_id=1").fetchone()[0] == 1
    assert banco.c.execute("SELECT n_achados FROM v_status_url WHERE url_id=1").fetchone()[0] == 1


def test_valido_antigo_vence_pagina_nova_invalida_mesmo_sendo_snippet(banco):
    # (b) vem antes de (c): JSON valido de snippet vence JSON invalido de pagina
    snippet, _ = banco.classificacao("r1", 1, origem="snippet")
    banco.classificacao("r2", 1, origem="pagina", valido=0, achados=0)
    assert banco.vigentes() == [snippet]


# ---------- (a) decisao humana ----------
def test_classificacao_com_achado_verificado_nunca_e_substituida_por_uma_mais_nova(banco):
    velha, ach = banco.classificacao("r1", 1, achados=2, verificado=(0,))
    banco.classificacao("r2", 1, achados=3)
    assert banco.vigentes() == [velha] and banco.r_achados() == ach


def test_decisao_humana_vence_ate_a_pagina_completa_mais_nova(banco):
    snippet, ach = banco.classificacao("r1", 1, origem="snippet", verificado=(0,))
    banco.classificacao("r2", 1, origem="pagina")
    assert banco.vigentes() == [snippet]


def test_com_duas_verificadas_vale_a_mais_recente_delas(banco):
    banco.classificacao("r1", 1, verificado=(0,))
    nova, _ = banco.classificacao("r2", 1, verificado=(0,))
    banco.execucao("r3")
    banco.classificacao("r3", 1)                                                  # a mais nova nao tem decisao humana
    assert banco.vigentes() == [nova]


def test_verificar_um_achado_antigo_o_torna_vigente(banco):
    velha, ach_v = banco.classificacao("r1", 1)
    nova, _ = banco.classificacao("r2", 1)
    assert banco.vigentes() == [nova]
    banco.c.execute("UPDATE achados SET verificado=1, status_final='em_uso' WHERE achado_id=?", (ach_v[0],))
    assert banco.vigentes() == [velha]


# ---------- execucoes fora do relatorio ----------
def test_execucao_fora_do_relatorio_nao_entra_na_escolha(banco):
    banco.execucao("piloto", no_relatorio=0)
    do_relatorio, _ = banco.classificacao("r1", 1)
    banco.classificacao("piloto", 1, origem="pagina")                              # mais nova, mas de piloto
    assert banco.vigentes() == [do_relatorio]
    banco.c.execute("UPDATE execucoes SET no_relatorio=0 WHERE run_id='r1'")
    assert banco.vigentes() == []


# ---------- achados descartados seguem a vigente ----------
def test_achados_descartados_seguem_a_classificacao_vigente(banco):
    velha, _ = banco.classificacao("r1", 1)
    nova, _ = banco.classificacao("r2", 1)
    for cid in (velha, nova):
        banco.c.execute("INSERT INTO achados_descartados (classificacao_id, uf, tecnologia, status, motivo) VALUES (?, 'PI', 'x', 'em_uso', "
                        "'tecnologia_fora_do_vocabulario')", (cid,))
    assert [l[0] for l in banco.c.execute("SELECT classificacao_id FROM r_achados_descartados")] == [nova]
    assert banco.c.execute("SELECT SUM(n) FROM v_achados_descartados").fetchone()[0] == 1


# ---------- caso parecido com o dado real: pares duplicados ----------
def test_pares_duplicados_do_piloto_colapsam_nas_contagens(banco):
    """Cinco paginas classificadas duas vezes (prompt v3) com achados repetidos em pares, como nos pilotos do Piaui."""
    antes_depois = [(1, 1), (2, 2), (3, 3), (3, 3), (4, 3)]
    for url_id, (n_velha, n_nova) in enumerate(antes_depois, start=1):
        banco.classificacao("r1", url_id, achados=n_velha)
        banco.classificacao("r2", url_id, achados=n_nova)
    historico = sum(a + b for a, b in antes_depois)                    # 25 achados gravados
    vigentes = sum(b for _, b in antes_depois)                         # 12 contam
    assert banco.c.execute("SELECT COUNT(*) FROM achados").fetchone()[0] == historico == 25
    assert banco.c.execute("SELECT COUNT(*) FROM r_achados_historico").fetchone()[0] == 25
    assert banco.c.execute("SELECT COUNT(*) FROM r_achados").fetchone()[0] == vigentes == 12
    assert banco.c.execute("SELECT COUNT(*) FROM r_classificacoes").fetchone()[0] == 5
    assert banco.c.execute("SELECT n_achados FROM v_resumo_uf WHERE uf='PI'").fetchone()[0] == 12
    assert banco.c.execute("SELECT COUNT(*) FROM v_achados_revisao").fetchone()[0] == 12
    assert banco.c.execute("SELECT SUM(n_achados) FROM v_status_url").fetchone()[0] == 12
    leitura = LeituraPainelSQLite(banco.repo.conn.execute("PRAGMA database_list").fetchone()[2])
    assert leitura.funil()["classificacoes"] == 5 and leitura.funil()["achados"] == 12 and leitura.contagem_revisao()["total"] == 12


def test_qualidade_do_classificador_continua_contando_todas_as_chamadas(banco):
    """Desempenho e custo por versao do prompt leem o historico: a substituicao nao apaga o v3 das metricas do modelo."""
    banco.c.execute("INSERT INTO chamadas (chamada_id, run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em, sucesso, custo_usd) "
                    "VALUES (1, 'r1', 'classificacao', 'p', '{}', 'k1', 'x', 1, 0.5), (2, 'r2', 'classificacao', 'p', '{}', 'k2', 'x', 1, 0.5)")
    banco.classificacao("r1", 1, prompt="v3")
    banco.classificacao("r2", 1, prompt="v4")
    q = {l["prompt_versao"]: dict(l) for l in banco.c.execute("SELECT * FROM v_qualidade_classificacao")}
    assert set(q) == {"v3", "v4"} and q["v3"]["n_classificacoes"] == 1 and q["v3"]["custo_usd"] == 0.5
    assert banco.c.execute("SELECT COUNT(*) FROM r_classificacoes").fetchone()[0] == 1
    assert banco.c.execute("SELECT n_achados FROM v_consistencia_evidencia WHERE prompt_versao='v3'").fetchone()[0] == 1


def test_funil_por_execucao_continua_contando_o_que_cada_execucao_fez(banco):
    banco.classificacao("r1", 1, achados=2)
    banco.classificacao("r2", 1, achados=3)
    f = {l["run_id"]: dict(l) for l in banco.c.execute("SELECT * FROM v_funil")}
    assert (f["r1"]["classificacoes"], f["r1"]["achados"], f["r2"]["classificacoes"], f["r2"]["achados"]) == (1, 2, 1, 3)


# ---------- painel: achado substituido abre, com aviso ----------
def _app(banco_db, raw, tmp_path):
    ctx = Contexto(banco="demo", nome_banco=banco_db.name, somente_leitura=False, pasta_backup=tmp_path / "backups", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver", "127.0.0.1", "localhost"))
    return criar_app(LeituraPainelSQLite(banco_db), lambda: RepositorioSQLite(banco_db), BrutoLocal(raw), ctx)


def test_achado_substituido_ainda_abre_com_aviso_e_some_da_fila(tmp_path):
    b = Banco(tmp_path / "p.db")
    b.execucao("r1")
    b.execucao("r2")
    _, ach_velho = b.classificacao("r1", 1, achados=1)
    _, ach_novo = b.classificacao("r2", 1, achados=1)
    b.c.close()
    cli = TestClient(_app(tmp_path / "p.db", tmp_path / "raw", tmp_path))
    velho = cli.get(f"/achados/{ach_velho[0]}")
    assert velho.status_code == 200 and "substituído por uma classificação mais recente" in velho.text
    assert f"/achados/{ach_novo[0]}" in velho.text and 'name="status_final"' not in velho.text     # sem formulario de decisao
    novo = cli.get(f"/achados/{ach_novo[0]}")
    assert novo.status_code == 200 and "substituído por uma classificação" not in novo.text and 'name="status_final"' in novo.text
    lista = cli.get("/achados").text
    assert f"/achados/{ach_novo[0]}" in lista and f"/achados/{ach_velho[0]}" not in lista


def test_achado_verificado_continua_com_formulario_mesmo_sendo_o_antigo(tmp_path):
    b = Banco(tmp_path / "p.db")
    b.execucao("r1")
    b.execucao("r2")
    _, ach = b.classificacao("r1", 1, achados=1, verificado=(0,))
    b.classificacao("r2", 1, achados=1)
    b.c.close()
    cli = TestClient(_app(tmp_path / "p.db", tmp_path / "raw", tmp_path))
    r = cli.get(f"/achados/{ach[0]}")
    assert r.status_code == 200 and "substituído por uma classificação" not in r.text


# ---------- de ponta a ponta: snippet e depois pagina, com os estagios e adaptadores falsos ----------
class FetcherQueFalhaTudo(FetcherSimulado):
    """Simula a pagina bloqueada pelo robots.txt: nenhuma pagina baixada."""

    def baixar(self, url):
        reg = super().baixar(url).chamada
        reg.erro, reg.http_status = "bloqueado_por_robots", None
        return ArquivoBaixado(url, None, "", b"", False, reg)


def _rodar(repo, bruto, fetcher):
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, BuscaSimulada(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, fetcher, ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    return run_id


def test_snippet_e_depois_pagina_substitui_sem_orfaos_e_o_inverso_nao(tmp_path, silencio):
    repo, bruto = RepositorioSQLite(tmp_path / "e.db"), BrutoLocal(tmp_path / "raw")
    r1 = _rodar(repo, bruto, FetcherQueFalhaTudo())                            # so snippet: 3 paginas, 3 achados
    assert [tuple(l) for l in repo.conn.execute("SELECT origem_texto, COUNT(*) FROM r_classificacoes GROUP BY 1")] == [("snippet", 3)]
    assert repo.conn.execute("SELECT COUNT(*) FROM r_achados").fetchone()[0] == 3
    r2 = _rodar(repo, bruto, FetcherSimulado())                                # a pagina agora baixa: texto completo
    assert r1 != r2
    assert [tuple(l) for l in repo.conn.execute("SELECT origem_texto, COUNT(*) FROM r_classificacoes GROUP BY 1")] == [("pagina", 3)]
    assert repo.conn.execute("SELECT COUNT(*) FROM r_achados").fetchone()[0] == 3                  # 3 e nao 6: sem orfaos
    assert repo.conn.execute("SELECT COUNT(*) FROM achados").fetchone()[0] == 6                    # o historico continua
    assert repo.conn.execute("SELECT COUNT(*) FROM v_achados_revisao").fetchone()[0] == 3
    assert repo.conn.execute("SELECT n_achados FROM v_resumo_uf WHERE uf='PI'").fetchone()[0] == 3
    assert {l[0] for l in repo.conn.execute("SELECT run_id FROM r_classificacoes")} == {r2}
    # uma terceira rodada so com snippet (pagina bloqueada de novo) NAO troca o texto completo
    _rodar(repo, bruto, FetcherQueFalhaTudo())
    assert [tuple(l) for l in repo.conn.execute("SELECT origem_texto, COUNT(*) FROM r_classificacoes GROUP BY 1")] == [("pagina", 3)]
    assert {l[0] for l in repo.conn.execute("SELECT run_id FROM r_classificacoes")} == {r2}
    assert repo.conn.execute("SELECT COUNT(*) FROM r_achados").fetchone()[0] == 3
