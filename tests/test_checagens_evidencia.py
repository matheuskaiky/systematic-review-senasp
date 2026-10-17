"""Checagens determinísticas da evidencia (sem LLM) e limite de retentativas por item."""
import json
import logging
import pathlib
import sqlite3

import pytest

import config.settings as S
import main
from adaptadores import classificador_gemini
from adaptadores.bruto_local import BrutoLocal
from adaptadores.classificador_gemini import ClassificadorGemini
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada, ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, classificacao, download
from config import consultas as C, vocabulario as V
from dados_metricas import _consulta_pi, _novo_run, _params
from dominio.servicos import evidencia_cita_lgpd, evidencia_cita_termo, palavras_chave_tecnologia

FIX = pathlib.Path(__file__).parent / "fixtures"
REAL = FIX / "gemini_generate_content.json"
CHAVE = "CHAVE-GEMINI-FALSA-123456"

# evidencia real do achado 1 da primeira classificacao (execucao 20261015_000030_28053b): o trecho existe no texto, mas
# nao menciona reconhecimento facial; o termo da tecnologia so aparece na frase seguinte
EVIDENCIA_FORA_DO_TEMA = ("Já o Face PI está em fase de estudos, pois existe um limite entre o combate a crimes e o direito à "
                          "privacidade. Para a tecnologia, o Núcleo de Estudos Avançados em Segurança Pública do Piauí (DataSSP) "
                          "desenvolveu um algoritmo próprio e eficiente")


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# ====================== palavras_chave_tecnologia ======================
@pytest.mark.parametrize("chave, esperado", [
    ("reconhecimento_facial", {"reconhecimento", "facial"}),
    ("leitura_placas", {"leitura", "placa", "veiculo"}),
    ("videomonitoramento_inteligente", {"videomonitoramento", "inteligente", "camera"}),
    ("analise_preditiva", {"analise", "preditiva", "preditivo", "policiamento"}),
    ("outra_ia", {"inteligencia", "artificial"}),
    ("atendimento_virtual", {"atendimento", "virtual", "boletim", "ocorrencia", "online", "chatbot", "whatsapp"}),
])
def test_palavras_vem_do_rotulo_da_tecnologia(chave, esperado):
    assert palavras_chave_tecnologia(V.TECNOLOGIAS[chave]) == esperado


def test_palavras_ignoram_vazias_curtas_e_tiram_o_plural():
    assert palavras_chave_tecnologia("leitura de placas para o uso de IA em câmeras") == {"leitura", "placa", "camera"}
    assert palavras_chave_tecnologia("") == set()


# ====================== evidencia_cita_termo ======================
def test_evidencia_que_cita_a_tecnologia():
    p = palavras_chave_tecnologia(V.TECNOLOGIAS["reconhecimento_facial"])
    assert evidencia_cita_termo("A tecnologia de RECONHECIMENTO FACIAL foi implantada.", p)
    assert evidencia_cita_termo("sistema de reconhecimento biométrico", p)                 # aceita qualquer palavra do rotulo
    assert evidencia_cita_termo("Câmeras com leitura de placas", palavras_chave_tecnologia(V.TECNOLOGIAS["leitura_placas"]))


def test_evidencia_real_fora_do_tema_nao_cita_a_tecnologia():
    assert not evidencia_cita_termo(EVIDENCIA_FORA_DO_TEMA, palavras_chave_tecnologia(V.TECNOLOGIAS["reconhecimento_facial"]))


@pytest.mark.parametrize("evidencia, palavras", [("", {"facial"}), (None, {"facial"}), ("texto qualquer", set()), ("texto sem o termo", {"facial"})])
def test_evidencia_vazia_ou_sem_palavras_nao_cita(evidencia, palavras):
    assert not evidencia_cita_termo(evidencia, palavras)


# ====================== evidencia_cita_lgpd ======================
@pytest.mark.parametrize("texto", ["respeitando a Lei Geral de Proteção de Dados (LGPD)", "conforme a LGPD", "a lgpd exige",
                                   "ações de proteção de dados", "tratamento de dados pessoais dos cidadãos", "LEI GERAL DE PROTECAO DE DADOS"])
def test_evidencia_que_cita_lgpd(texto):
    assert evidencia_cita_lgpd(texto)


@pytest.mark.parametrize("texto", ["respeitando a privacidade", "o workshop sobre segurança pública", "lgpdx", "", None, "dados abertos do estado"])
def test_evidencia_que_nao_cita_lgpd(texto):
    assert not evidencia_cita_lgpd(texto)


# ====================== no estagio, com a resposta real do Gemini ======================
class _Resp:
    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()


def _chamar(monkeypatch, texto, erro=None, http_status=200):
    monkeypatch.setattr(classificador_gemini, "chamar", lambda *a, **k: {
        "resp": _Resp(texto), "http_status": http_status, "latencia_ms": 5, "tentativas": 1, "erro": erro,
        "latencia_total_ms": 5, "historico": [], "corpo_erro": None})


def _gemini():
    return ClassificadorGemini(CHAVE, "gemini-3.5-flash-lite", preco_entrada_por_m=0.3, preco_saida_por_m=2.5)


def _params_com_palavras():
    from dataclasses import replace
    return replace(_params(), palavras_tecnologia={k: tuple(sorted(palavras_chave_tecnologia(v))) for k, v in V.TECNOLOGIAS.items()})


def _estagio(tmp_path):
    repo, bruto = RepositorioSQLite(tmp_path / "e.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, BuscaSimulada(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    return repo, bruto, run_id


@pytest.mark.skipif(not REAL.exists(), reason="fixture real do Gemini ainda nao existe")
def test_achados_guardam_as_checagens_calculadas_na_classificacao(tmp_path, monkeypatch, silencio):
    _chamar(monkeypatch, REAL.read_text(encoding="utf-8"))
    repo, bruto, run_id = _estagio(tmp_path)
    classificacao.executar(repo, bruto, _gemini(), run_id, run_id, _params_com_palavras(), C.UFS, [CHAVE], 0, ufs={"PI"})
    linhas = [dict(r) for r in repo.conn.execute("SELECT * FROM achados ORDER BY achado_id")]
    assert len(linhas) == 9                                                              # 3 paginas x 3 achados da resposta real
    assert {l["evidencia_cita_tecnologia"] for l in linhas} == {1} and {l["evidencia_cita_lgpd"] for l in linhas} == {0}
    assert sum(l["menciona_lgpd"] for l in linhas) == 3                                  # o modelo marcou LGPD sem respaldo no trecho
    v = dict(repo.conn.execute("SELECT * FROM v_consistencia_evidencia").fetchone())
    assert (v["n_achados"], v["pct_evidencia_cita_tecnologia"]) == (9, 100.0)
    assert (v["n_lgpd_modelo"], v["n_lgpd_modelo_com_respaldo"], v["n_lgpd_modelo_sem_respaldo"], v["n_lgpd_no_trecho_sem_flag"]) == (3, 0, 3, 0)
    assert v["classificador"] == "gemini:gemini-3.5-flash-lite"


def test_estagio_sem_palavras_na_configuracao_deixa_a_checagem_de_tecnologia_vazia(tmp_path, silencio):
    from adaptadores.simulados import ClassificadorSimulado
    repo, bruto, run_id = _estagio(tmp_path)
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    a = repo.conn.execute("SELECT evidencia_cita_tecnologia, evidencia_cita_lgpd FROM achados").fetchone()
    assert tuple(a) == (None, 0)


def test_estagio_com_o_simulado_e_as_palavras_da_configuracao(tmp_path, silencio):
    from adaptadores.simulados import ClassificadorSimulado
    repo, bruto, run_id = _estagio(tmp_path)
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params_com_palavras(), C.UFS, [], 0, ufs={"PI"})
    assert {tuple(r) for r in repo.conn.execute("SELECT evidencia_cita_tecnologia, evidencia_cita_lgpd FROM achados")} == {(1, 0)}


def test_a_fila_de_revisao_poe_a_evidencia_fora_do_tema_primeiro(tmp_path, silencio):
    from adaptadores.simulados import ClassificadorSimulado
    repo, bruto, run_id = _estagio(tmp_path)
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params_com_palavras(), C.UFS, [], 0, ufs={"PI"})
    repo.conn.execute("UPDATE achados SET evidencia_cita_tecnologia=0 WHERE achado_id=3")
    repo.confirmar()
    fila = [dict(r) for r in repo.conn.execute("SELECT achado_id, evidencia_cita_tecnologia, evidencia_cita_lgpd FROM v_achados_revisao")]
    assert fila[0]["achado_id"] == 3 and fila[0]["evidencia_cita_tecnologia"] == 0 and "evidencia_cita_lgpd" in fila[0]


def test_configuracao_traz_as_palavras_e_o_limite_de_falhas():
    p = main._params_classificacao()
    assert set(p.palavras_tecnologia) == set(V.TECNOLOGIAS) and "facial" in p.palavras_tecnologia["reconhecimento_facial"]
    assert S.CLASSIFICACAO["max_falhas_por_item"] == 3


# ====================== nome_solucao (RC15) nao mexe na checagem literal da evidencia ======================
class _ClassificadorComNome:
    nome = "duplo"

    def __init__(self, nome_solucao):
        self.nome_solucao = nome_solucao

    def classificar(self, entrada, instr):
        from adaptadores.simulados import _reg
        from dominio.modelos import Achado, ResultadoClassificacao
        reg = _reg(self.nome, "classificar", raw=b"{}", tokens_entrada=10, tokens_saida=5, custo_usd=0.0)
        a = Achado("reconhecimento_facial", "em_uso", "", False, "implantou reconhecimento facial nas câmeras da capital", "alta",
                   nome_solucao=self.nome_solucao)
        return ResultadoClassificacao(True, [a], True, "{}", reg)


def test_nome_solucao_nunca_muda_a_checagem_literal_e_nome_ausente_do_texto_e_descartado(tmp_path, silencio):
    resultados = {}
    for i, nome in enumerate(("", "Nome Que Nao Esta No Texto")):
        repo, bruto, run_id = _estagio(tmp_path / str(i))
        classificacao.executar(repo, bruto, _ClassificadorComNome(nome), run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
        resultados[nome] = [tuple(l) for l in repo.conn.execute("SELECT evidencia_confere, nome_solucao FROM achados")]
        assert repo.conn.execute("SELECT valor FROM metricas_run WHERE chave='classificacao_nome_solucao_descartado'").fetchone()[0] == (3 if nome else 0)
    assert resultados[""] == resultados["Nome Que Nao Esta No Texto"] == [(1, None)] * 3     # nome inventado: descartado; evidencia: intacta


# ====================== achados antigos ganham as checagens ao abrir o banco ======================
def test_achados_antigos_sao_preenchidos_a_partir_da_evidencia_e_do_vocabulario_da_execucao(tmp_path):
    db = sqlite3.connect(tmp_path / "antigo.db")
    db.executescript("""
        CREATE TABLE execucoes (run_id TEXT PRIMARY KEY, iniciado_em TEXT NOT NULL, config_hash TEXT NOT NULL, config_json TEXT NOT NULL);
        CREATE TABLE classificacoes (classificacao_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, url_id INTEGER, uf TEXT);
        CREATE TABLE achados (achado_id INTEGER PRIMARY KEY AUTOINCREMENT, classificacao_id INTEGER NOT NULL, uf TEXT NOT NULL,
            tecnologia TEXT, status_reportado TEXT, fornecedor TEXT, menciona_lgpd INTEGER, evidencia TEXT, evidencia_confere INTEGER,
            confianca TEXT, verificado INTEGER NOT NULL DEFAULT 0, status_final TEXT, verificado_por TEXT, verificado_em TEXT, observacao TEXT);
        INSERT INTO classificacoes (run_id, url_id, uf) VALUES ('r1', 1, 'PI');
    """)
    db.execute("INSERT INTO execucoes VALUES ('r1', 'x', 'h', ?)", (json.dumps({"tecnologias": {"reconhecimento_facial": "reconhecimento facial"}}),))
    for tec, ev in (("reconhecimento_facial", "implantou reconhecimento facial"), ("reconhecimento_facial", EVIDENCIA_FORA_DO_TEMA),
                    ("tecnologia_removida", "trecho sobre a LGPD")):
        db.execute("INSERT INTO achados (classificacao_id, uf, tecnologia, evidencia) VALUES (1, 'PI', ?, ?)", (tec, ev))
    db.commit()
    db.close()
    repo = RepositorioSQLite(tmp_path / "antigo.db")
    r = [tuple(x) for x in repo.conn.execute("SELECT evidencia_cita_tecnologia, evidencia_cita_lgpd FROM achados ORDER BY achado_id")]
    assert r == [(1, 0), (0, 0), (None, 1)]                          # tecnologia fora do vocabulario da execucao: fica sem checagem
    RepositorioSQLite(tmp_path / "antigo.db")                         # reabrir nao muda nada
    assert [tuple(x) for x in repo.conn.execute("SELECT evidencia_cita_tecnologia FROM achados ORDER BY achado_id")] == [(1,), (0,), (None,)]


# ====================== limite de retentativas por item ======================
def _truncada():
    return (FIX / "sintetico" / "gemini_max_tokens_sintetico.json").read_text(encoding="utf-8")


def _n_chamadas(repo):
    return repo.conn.execute("SELECT COUNT(*) FROM chamadas WHERE etapa='classificacao'").fetchone()[0]


def _classificar(repo, bruto, run_id, **kw):
    classificacao.executar(repo, bruto, _gemini(), run_id, run_id, _params(), C.UFS, [CHAVE], 0, ufs={"PI"}, **kw)


def test_item_que_falha_sempre_igual_e_abandonado_apos_o_limite(tmp_path, monkeypatch, caplog):
    _chamar(monkeypatch, _truncada())
    caplog.set_level(logging.INFO)
    repo, bruto, run_id = _estagio(tmp_path)
    _classificar(repo, bruto, run_id, max_falhas_por_item=2)
    assert _n_chamadas(repo) == 3                                       # 1a tentativa de cada um dos 3 itens
    _classificar(repo, bruto, run_id, max_falhas_por_item=2)            # --retomar: 2a tentativa
    assert _n_chamadas(repo) == 6
    _classificar(repo, bruto, run_id, max_falhas_por_item=2)            # --retomar: limite atingido
    assert _n_chamadas(repo) == 6                                       # nada novo foi pago
    assert repo.conn.execute("SELECT valor FROM metricas_run WHERE chave='classificacao_desistencias'").fetchone()[0] == 3
    assert "item abandonado" in caplog.text and "max_tokens_saida" in caplog.text


def test_sem_limite_a_retentativa_continua_como_antes(tmp_path, monkeypatch, silencio):
    _chamar(monkeypatch, _truncada())
    repo, bruto, run_id = _estagio(tmp_path)
    for _ in range(4):
        _classificar(repo, bruto, run_id)
    assert _n_chamadas(repo) == 12


def test_o_limite_conta_so_as_falhas_do_mesmo_item_e_da_mesma_execucao(tmp_path, monkeypatch, silencio):
    _chamar(monkeypatch, _truncada())
    repo, bruto, run_id = _estagio(tmp_path)
    _classificar(repo, bruto, run_id, max_falhas_por_item=1)
    _classificar(repo, bruto, run_id, max_falhas_por_item=1)
    assert _n_chamadas(repo) == 3                                       # cada item falhou uma vez: todos abandonados
    outra = _novo_run(repo, "classificar")
    classificacao.executar(repo, bruto, _gemini(), outra, run_id, _params(), C.UFS, [CHAVE], 0, ufs={"PI"}, max_falhas_por_item=1)
    assert _n_chamadas(repo) == 6                                       # a execucao nova tem a propria contagem


def test_aviso_de_truncamento_no_log(tmp_path, monkeypatch, caplog):
    _chamar(monkeypatch, _truncada())
    caplog.set_level(logging.INFO)
    repo, bruto, run_id = _estagio(tmp_path)
    _classificar(repo, bruto, run_id)
    assert "resposta truncada" in caplog.text and "aumente max_tokens_saida" in caplog.text


def test_item_abandonado_continua_visivel_como_falha_na_view(tmp_path, monkeypatch, silencio):
    _chamar(monkeypatch, _truncada())
    repo, bruto, run_id = _estagio(tmp_path)
    for _ in range(3):
        _classificar(repo, bruto, run_id, max_falhas_por_item=1)
    r = {tuple(x) for x in repo.conn.execute("SELECT resultado, motivo FROM v_resultado_classificacao")}
    assert r == {("falha_chamada", "resposta_truncada: MAX_TOKENS")}


def test_contar_falhas_so_conta_sucesso_zero(tmp_path, monkeypatch, silencio):
    repo, bruto, run_id = _estagio(tmp_path)
    assert repo.contar_falhas(run_id, "qualquer") == 0
    _chamar(monkeypatch, _truncada())
    _classificar(repo, bruto, run_id)
    chave = repo.conn.execute("SELECT chave_idempotencia FROM chamadas WHERE etapa='classificacao' LIMIT 1").fetchone()[0]
    assert repo.contar_falhas(run_id, chave) == 1 and repo.contar_falhas("outro", chave) == 0
