import pytest

from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import (BuscaSimulada, AcademicoSimulado, FetcherSimulado, ExtratorSimulado,
                                   ClassificadorSimulado)
from aplicacao import busca_academica, busca_web, download, classificacao
from config import consultas as C, vocabulario as V
from dominio.esquemas import esquema_classificacao
from dominio.modelos import ParametrosClassificacao
from dominio.modelos import RespostaBusca
from dominio.servicos import gerar_consultas_web

UFS = ("PI", "CE")


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(tmp_path / "simulado.db")


@pytest.fixture
def bruto(tmp_path):
    return BrutoLocal(tmp_path / "raw")


def _params():
    return ParametrosClassificacao(
        versao_prompt="v-teste", sistema="sistema", usuario_template="{nome} {uf} {url} {titulo} {origem} {texto}",
        esquema=esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA),
        tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS))


def _novo_run(repo, run_origem=None):
    return repo.iniciar_execucao("teste", "h", "{}", None, run_origem=run_origem)


def _consultas():
    ufs = {k: v for k, v in C.UFS.items() if k in UFS}
    return gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, ufs)


def _web(repo, bruto, run_id):
    busca_web.executar(repo, bruto, BuscaSimulada(), run_id, _consultas(), C.PERFIS_BUSCA_WEB, [], 0)


def _baixar(repo, bruto, run_id, origem):
    download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run_id, origem,
                      C.POLITICA_DOWNLOAD, [], 0, ufs=set(UFS))


def _classificar(repo, bruto, run_id, origem):
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, origem, _params(), C.UFS, [], 0,
                           ufs=set(UFS))


def _pipeline(repo, bruto):
    run_id = _novo_run(repo)
    _web(repo, bruto, run_id)
    _baixar(repo, bruto, run_id, run_id)
    _classificar(repo, bruto, run_id, run_id)
    return run_id


def _n(repo, tabela, run_id=None):
    sql = f"SELECT COUNT(*) FROM {tabela}" + (" WHERE run_id=?" if run_id else "")
    return repo.conn.execute(sql, (run_id,) if run_id else ()).fetchone()[0]


def test_funil_e_consistente(repo, bruto):
    run_id = _pipeline(repo, bruto)
    f = dict(repo.conn.execute("SELECT * FROM v_funil WHERE run_id=?", (run_id,)).fetchone())
    assert f["consultas_web_ok"] == 20                       # 2 UFs x 5 tecnologias x 2 modelos
    assert f["resultados"] == 20 * 3
    assert f["urls_unicas"] == 3 * len(UFS)                  # 3 URLs unicas por UF
    assert f["pares_url_uf_selecionados"] == 6 and f["pares_descartados"] == 0
    assert f["paginas_baixadas"] == 6 and f["paginas_com_texto"] == 6
    assert f["classificacoes"] == 6
    assert f["achados"] == 6 and f["achados_evidencia_ok"] == 6 and f["achados_verificados"] == 0


def test_tres_urls_unicas_por_uf(repo, bruto):
    run_id = _pipeline(repo, bruto)
    linhas = repo.conn.execute(
        "SELECT uf, COUNT(DISTINCT url_id) FROM resultados_web WHERE run_id=? GROUP BY uf", (run_id,)).fetchall()
    assert {l[0]: l[1] for l in linhas} == {"PI": 3, "CE": 3}


def test_todo_achado_tem_evidencia_confere(repo, bruto):
    _pipeline(repo, bruto)
    valores = [l[0] for l in repo.conn.execute("SELECT evidencia_confere FROM achados").fetchall()]
    assert valores and all(v == 1 for v in valores)


def test_classificacoes_sao_validas_e_de_pagina(repo, bruto):
    _pipeline(repo, bruto)
    for l in repo.conn.execute("SELECT json_valido, origem_texto, relevante FROM classificacoes").fetchall():
        assert (l["json_valido"], l["origem_texto"], l["relevante"]) == (1, "pagina", 1)


def test_reexecutar_com_o_mesmo_run_id_nao_cria_chamadas(repo, bruto):
    run_id = _novo_run(repo)
    for etapa in (lambda: _web(repo, bruto, run_id),
                  lambda: _baixar(repo, bruto, run_id, run_id),
                  lambda: _classificar(repo, bruto, run_id, run_id)):
        etapa()
        antes = _n(repo, "chamadas", run_id)
        etapa()
        assert _n(repo, "chamadas", run_id) == antes


def test_reexecutar_nao_duplica_resultados_nem_achados(repo, bruto):
    run_id = _pipeline(repo, bruto)
    contagens = {t: _n(repo, t) for t in ("resultados_web", "paginas", "classificacoes", "achados", "selecao_download")}
    _web(repo, bruto, run_id)
    _baixar(repo, bruto, run_id, run_id)
    _classificar(repo, bruto, run_id, run_id)
    assert {t: _n(repo, t) for t in contagens} == contagens


def test_classificar_le_outra_execucao_por_run_origem(repo, bruto):
    origem = _novo_run(repo)
    _web(repo, bruto, origem)
    _baixar(repo, bruto, origem, origem)
    nova = _novo_run(repo, run_origem=origem)
    _classificar(repo, bruto, nova, origem)
    assert _n(repo, "classificacoes", nova) == 6
    assert _n(repo, "achados") == 6
    assert _n(repo, "classificacoes", origem) == 0
    assert repo.obter_run_origem(nova) == origem


def test_baixar_le_outra_execucao_por_run_origem(repo, bruto):
    origem = _novo_run(repo)
    _web(repo, bruto, origem)
    nova = _novo_run(repo, run_origem=origem)
    _baixar(repo, bruto, nova, origem)
    assert _n(repo, "paginas", nova) == 6 and _n(repo, "paginas", origem) == 0


def test_limite_e_classificacao_por_snippet(repo, bruto):
    """Com --limite, URLs selecionadas e nao baixadas caem no snippet, com confianca baixa."""
    run_id = _novo_run(repo)
    _web(repo, bruto, run_id)
    download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run_id, run_id,
                      C.POLITICA_DOWNLOAD, [], 0, limite=2, ufs=set(UFS))
    _classificar(repo, bruto, run_id, run_id)
    origens = [l[0] for l in repo.conn.execute("SELECT origem_texto FROM classificacoes").fetchall()]
    assert sorted(origens) == ["pagina"] * 2 + ["snippet"] * 4
    confs = {l[0] for l in repo.conn.execute(
        "SELECT confianca FROM achados a JOIN classificacoes k USING (classificacao_id) "
        "WHERE k.origem_texto='snippet'").fetchall()}
    assert confs == {"baixa"}


def test_busca_academica_simulada_grava_artigos_e_ocorrencias(repo, bruto):
    run_id = _novo_run(repo)
    busca_academica.executar(repo, bruto, AcademicoSimulado(), run_id, C.TERMOS, C.FILTROS_ACADEMICOS, 1, [], 0)
    antes = _n(repo, "chamadas", run_id)
    assert antes == len(C.TERMOS)                       # 3 < por_pagina: so a primeira pagina
    assert _n(repo, "artigos") == 3 * len(C.TERMOS) and _n(repo, "ocorrencias") == 3 * len(C.TERMOS)
    busca_academica.executar(repo, bruto, AcademicoSimulado(), run_id, C.TERMOS, C.FILTROS_ACADEMICOS, 1, [], 0)
    assert _n(repo, "chamadas", run_id) == antes


def test_raw_nao_contem_segredo(repo, bruto, tmp_path):
    """Um segredo que aparecesse no corpo bruto JSON e trocado por *** (registrar_chamada)."""
    segredo = "SEGREDO-FALSO-XYZ"
    run_id = _novo_run(repo)
    busca_web.executar(repo, bruto, _BuscaQueVazaSegredo(segredo), run_id, _consultas()[:2], C.PERFIS_BUSCA_WEB,
                       [segredo], 0)
    arquivos = [p for p in (tmp_path / "raw").rglob("*") if p.is_file()]
    assert arquivos and all(segredo.encode() not in p.read_bytes() for p in arquivos)
    assert all(b"***" in p.read_bytes() for p in arquivos)


class _BuscaQueVazaSegredo(BuscaSimulada):
    def __init__(self, segredo):
        self._segredo = segredo

    def buscar(self, consulta, filtros):
        resp = super().buscar(consulta, filtros)
        resp.chamada.raw = ('{"eco": "api_key=%s"}' % self._segredo).encode()
        return resp


# ---------- metricas: tudo o que e medido precisa chegar ao banco ----------
COLUNAS_OBRIGATORIAS = ("run_id", "etapa", "provedor", "operacao", "alvo_tipo", "alvo_id", "parametros_json",
                        "chave_idempotencia", "requisitado_em", "http_status", "sucesso", "tentativas",
                        "latencia_ms", "raw_path", "raw_sha256", "extras_json")


def test_toda_chamada_grava_as_metricas_e_o_bruto(repo, bruto, tmp_path):
    _pipeline(repo, bruto)
    linhas = repo.conn.execute("SELECT * FROM chamadas").fetchall()
    assert len(linhas) == 32                                    # 20 buscas + 6 downloads + 6 classificacoes
    for l in linhas:
        faltando = [c for c in COLUNAS_OBRIGATORIAS if l[c] is None]
        assert not faltando, f"chamada {l['chamada_id']} ({l['etapa']}) sem {faltando}"
        assert l["sucesso"] == 1 and l["erro"] is None and len(l["raw_sha256"]) == 64
        assert (tmp_path / "raw" / l["raw_path"]).is_file()


def test_busca_web_grava_contagens_e_classificacao_grava_tokens_e_custo(repo, bruto):
    _pipeline(repo, bruto)
    for l in repo.conn.execute("SELECT n_retornados, n_novos FROM chamadas WHERE etapa='busca_web'"):
        assert l["n_retornados"] == 3 and l["n_novos"] is not None
    for l in repo.conn.execute("SELECT tokens_entrada, tokens_saida, custo_usd FROM chamadas WHERE etapa='classificacao'"):
        assert (l["tokens_entrada"], l["tokens_saida"], l["custo_usd"]) == (100, 20, 0.0)


class _BuscaQueFalha(BuscaSimulada):
    def buscar(self, consulta, filtros):
        resp = super().buscar(consulta, filtros)
        c = resp.chamada
        c.erro, c.http_status, c.tentativas, c.latencia_ms, c.raw = "HTTP 500: falha", 500, 4, 1234, b"corpo do erro"
        return RespostaBusca([], c)


def test_chamada_com_falha_tambem_grava_as_metricas_e_o_bruto(repo, bruto, tmp_path):
    run_id = _novo_run(repo)
    busca_web.executar(repo, bruto, _BuscaQueFalha(), run_id, _consultas()[:1], C.PERFIS_BUSCA_WEB, [], 0)
    l = repo.conn.execute("SELECT * FROM chamadas").fetchone()
    assert (l["sucesso"], l["erro"], l["http_status"], l["tentativas"], l["latencia_ms"]) == (0, "HTTP 500: falha", 500, 4, 1234)
    assert l["n_retornados"] == 0 and l["n_novos"] == 0
    assert (tmp_path / "raw" / l["raw_path"]).read_bytes() == b"corpo do erro"
    assert repo.conn.execute("SELECT n FROM v_falhas").fetchone()[0] == 1
    assert not repo.ja_feito(run_id, l["chave_idempotencia"])        # falha nao conta como feita: sera repetida


def test_custo_da_busca_web_aparece_em_v_custos(repo, bruto):
    class _Paga(BuscaSimulada):
        def buscar(self, consulta, filtros):
            resp = super().buscar(consulta, filtros)
            resp.chamada.custo_usd = 0.005
            return resp
    run_id = _novo_run(repo)
    busca_web.executar(repo, bruto, _Paga(), run_id, _consultas()[:5], C.PERFIS_BUSCA_WEB, [], 0)
    l = repo.conn.execute("SELECT n_chamadas, n_ok, custo_usd FROM v_custos WHERE etapa='busca_web'").fetchone()
    assert (l["n_chamadas"], l["n_ok"], l["custo_usd"]) == (5, 5, 0.025)
