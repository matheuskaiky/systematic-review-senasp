"""RC15: `nome_solucao` de ponta a ponta (dominio, prompt v4, antialucinacao no estagio, gravacao, views e leitura do painel).
Nenhum teste chama rede ou LLM: o classificador e um duplo."""
import logging

import pytest

import config.prompts as P
from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import (BuscaSimulada, ClassificadorSimulado, ExtratorSimulado, FetcherSimulado, NOME_SOLUCAO_DEMO,
                                   _reg)
from aplicacao import busca_web, classificacao, download
from config import consultas as C
from dados_metricas import _consulta_pi, _novo_run, _params
from dominio.modelos import Achado, ResultadoClassificacao
from dominio.servicos import evidencia_confere, interpretar_json_classificacao
from dominio.solucoes import nome_solucao_no_texto

TRECHO = "a ferramenta utiliza inteligência artificial para coletar as informações da ocorrência"
TEXTO_BO = ("Piauí investe em tecnologia. O BO Fácil é o primeiro serviço do país de registro de boletim de ocorrência pelo WhatsApp. "
            "Com o número oficial 0800, " + TRECHO + ".")


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# ---------- funcao pura ----------
@pytest.mark.parametrize("nome, texto, esperado", [
    ("BO Fácil", "o serviço BO Fácil foi lançado", True),
    ("bo facil", "o serviço BO FÁCIL foi lançado", True),                    # sem acento e sem diferenca de maiusculas
    ("BO Fácil", "o serviço BO-Fácil, lançado em 2025", True),               # pontuacao nao conta
    ("SPiA", "O SPiA identifica placas", True),
    ("SPiA", "os policiais espiando a rua", False),                          # palavra inteira: nao casa no meio de outra
    ("Sistema BO Fácil", "o serviço BO Fácil foi lançado", False),           # nome completado pelo modelo: nao esta no texto
    ("Delegacia Virtual 4.0", "A Delegacia Virtual 4.0 atende", True),
    ("", "qualquer texto", False),
    ("   ", "qualquer texto", False),
    ("BO Fácil", "", False),
    ("BO Fácil", None, False),
])
def test_nome_solucao_no_texto(nome, texto, esperado):
    assert nome_solucao_no_texto(nome, texto) is esperado


# ---------- interpretacao da resposta ----------
def test_resposta_sem_o_campo_vira_nome_vazio():
    texto = ('{"relevante": true, "achados": [{"tecnologia": "outra_ia", "status": "em_uso", "fornecedor": "", "menciona_lgpd": false, '
             '"evidencia": "x", "confianca": "alta"}]}')
    _, achados, valido = interpretar_json_classificacao(texto)
    assert valido and achados[0].nome_solucao == ""


@pytest.mark.parametrize("bruto, esperado", [('"BO Fácil"', "BO Fácil"), ('"  BO   Fácil \\n"', "BO Fácil"), ("null", ""), ('""', ""), ("7", "7")])
def test_resposta_normaliza_o_nome(bruto, esperado):
    texto = ('{"relevante": true, "achados": [{"tecnologia": "outra_ia", "status": "em_uso", "fornecedor": "", "menciona_lgpd": false, '
             '"evidencia": "x", "confianca": "alta", "nome_solucao": ' + bruto + "}]}")
    assert interpretar_json_classificacao(texto)[1][0].nome_solucao == esperado


# ---------- prompt v4 (a regra do nome continua valendo no v5, RC14) ----------
def test_prompt_v4_pede_o_nome_sem_mexer_na_evidencia():
    assert P.PROMPT_VERSAO == "v5"      # o v5 so acrescenta a categoria atendimento_virtual; a regra 7 do v4 segue igual
    s = P.SYSTEM_PROMPT
    assert "'nome_solucao'" in s and "PROPER NAME" in s and "empty string" in s and "Never invent" in s
    assert "Do NOT add the name" in s and "100% literal" in s            # a evidencia continua literal: nada de nome entre colchetes
    assert "[" not in s.split("'nome_solucao'")[1].split("8. Language")[0]
    assert "Brazilian Portuguese" in s


# ---------- estagio com duplo ----------
class FetcherComTexto(FetcherSimulado):
    def __init__(self, texto):
        self._texto = texto

    def baixar(self, url):
        reg = _reg(self.nome, "baixar", raw=self._texto.encode(), raw_ext="html")
        from dominio.modelos import ArquivoBaixado
        return ArquivoBaixado(url, 200, "text/html", self._texto.encode(), False, reg)


class ClassificadorQueDevolve:
    """Devolve sempre o mesmo achado, com o `nome_solucao` e a evidencia escolhidos pelo teste."""
    nome = "duplo"

    def __init__(self, nome_solucao, evidencia=TRECHO):
        self.nome_solucao, self.evidencia = nome_solucao, evidencia

    def classificar(self, entrada, instr):
        reg = _reg(self.nome, "classificar", raw=b"{}", tokens_entrada=10, tokens_saida=5, custo_usd=0.0)
        a = Achado("outra_ia", "em_uso", "", False, self.evidencia, "alta", nome_solucao=self.nome_solucao)
        return ResultadoClassificacao(True, [a], True, "{}", reg)


def _estagio(tmp_path, classificador, texto=TEXTO_BO):
    repo, bruto = RepositorioSQLite(tmp_path / "n.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, BuscaSimulada(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherComTexto(texto), ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    classificacao.executar(repo, bruto, classificador, run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    return repo, run_id


def _nomes(repo):
    return [l[0] for l in repo.conn.execute("SELECT nome_solucao FROM achados ORDER BY achado_id")]


def _metrica(repo, run_id):
    l = repo.conn.execute("SELECT valor FROM metricas_run WHERE run_id=? AND chave='classificacao_nome_solucao_descartado'", (run_id,)).fetchone()
    return None if l is None else l[0]


def test_nome_que_esta_no_texto_e_guardado_e_a_evidencia_continua_literal(tmp_path, silencio):
    repo, run_id = _estagio(tmp_path, ClassificadorQueDevolve("BO Fácil"))
    assert _nomes(repo) == ["BO Fácil"] * 3                           # tres paginas (a busca simulada devolve tres URLs)
    assert [l[0] for l in repo.conn.execute("SELECT evidencia FROM achados")] == [TRECHO] * 3   # sem nome dentro da evidencia
    assert [l[0] for l in repo.conn.execute("SELECT evidencia_confere FROM achados")] == [1, 1, 1]
    assert _metrica(repo, run_id) == 0


def test_nome_que_nao_esta_no_texto_e_descartado_e_contado(tmp_path, silencio):
    repo, run_id = _estagio(tmp_path, ClassificadorQueDevolve("Sistema Inventado"))
    assert _nomes(repo) == [None] * 3                                  # NULL no banco: sem nome
    assert repo.conn.execute("SELECT COUNT(*) FROM achados").fetchone()[0] == 3     # o achado em si continua
    assert _metrica(repo, run_id) == 3


def test_o_descarte_do_nome_vai_para_o_log_em_portugues(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    _estagio(tmp_path, ClassificadorQueDevolve("Sistema Inventado"))
    assert any("nome_solucao 'Sistema Inventado' descartado" in r.getMessage() and "não aparece no texto enviado" in r.getMessage()
               for r in caplog.records)


def test_nome_so_no_titulo_ou_na_url_conta_como_entrada_do_modelo(tmp_path, silencio):
    # o titulo vem da busca simulada ("Reconhecimento facial PI n"); a URL traz "exemplo.gov.br/pi/n"
    repo, run_id = _estagio(tmp_path, ClassificadorQueDevolve("Reconhecimento facial PI"), texto="texto sem o nome")
    assert _nomes(repo) == ["Reconhecimento facial PI"] * 3 and _metrica(repo, run_id) == 0
    repo2, _ = _estagio(tmp_path / "u", ClassificadorQueDevolve("exemplo gov br pi"), texto="texto sem o nome")
    assert _nomes(repo2) == ["exemplo gov br pi"] * 3


def test_nome_nunca_muda_a_checagem_da_evidencia(tmp_path, silencio):
    """A evidencia e conferida como trecho literal, com ou sem nome. Se o nome fosse colocado entre colchetes na frente do trecho
    (alternativa recusada), a checagem marcaria 'nao confere': por isso o nome fica em campo proprio."""
    comparacoes = []
    for i, nome in enumerate(("BO Fácil", "", "Sistema Inventado")):
        repo, _ = _estagio(tmp_path / f"c{i}", ClassificadorQueDevolve(nome))
        comparacoes.append([l[0] for l in repo.conn.execute("SELECT evidencia_confere FROM achados")])
    assert comparacoes == [[1, 1, 1]] * 3
    assert evidencia_confere(TRECHO, TEXTO_BO) is True
    assert evidencia_confere("[BO Fácil] " + TRECHO, TEXTO_BO) is False


def test_classificador_simulado_so_preenche_o_nome_demonstrativo_quando_o_texto_o_traz(tmp_path, silencio):
    padrao = "A Secretaria implantou reconhecimento facial nas câmeras da capital em 2024."   # sem o nome demonstrativo
    repo, run_id = _estagio(tmp_path, ClassificadorSimulado(), texto=padrao)
    assert _nomes(repo) == [None] * 3 and _metrica(repo, run_id) == 0
    texto = f"A Secretaria implantou reconhecimento facial nas câmeras com o {NOME_SOLUCAO_DEMO}."
    repo2, run2 = _estagio(tmp_path / "d", ClassificadorSimulado(), texto=texto)
    assert _nomes(repo2) == [NOME_SOLUCAO_DEMO] * 3 and _metrica(repo2, run2) == 0


# ---------- schema, views e leitura ----------
def test_banco_antigo_ganha_a_coluna_ao_abrir_e_a_view_a_expoe(tmp_path):
    import sqlite3
    repo, _ = _estagio(tmp_path, ClassificadorQueDevolve("BO Fácil"))
    repo.conn.close()
    con = sqlite3.connect(tmp_path / "n.db")                           # simula um banco anterior ao RC15
    con.execute("DROP VIEW v_achados_revisao")
    con.execute("DROP VIEW v_secretarias_confirmadas")
    con.execute("ALTER TABLE achados DROP COLUMN nome_solucao")
    con.execute("DELETE FROM meta_schema WHERE chave='assinatura'")
    con.commit()
    con.close()
    repo = RepositorioSQLite(tmp_path / "n.db")
    cols = [r[1] for r in repo.conn.execute("PRAGMA table_info(achados)")]
    assert "nome_solucao" in cols
    assert "nome_solucao" in [r[1] for r in repo.conn.execute("PRAGMA table_info(v_achados_revisao)")]
    assert "nome_solucao" in [r[1] for r in repo.conn.execute("PRAGMA table_info(v_secretarias_confirmadas)")]


def test_leitura_busca_pelo_nome_da_solucao(tmp_path, silencio):
    repo, _ = _estagio(tmp_path, ClassificadorQueDevolve("BO Fácil"))
    leitura = LeituraPainelSQLite(tmp_path / "n.db")
    assert leitura.achados({"q": "BO Fácil"})["total"] == 3
    assert leitura.achados({"q": "bo f"})["total"] == 3                  # LIKE sem diferenca de maiusculas (ASCII)
    assert leitura.achados({"q": "Inexistente"})["total"] == 0
    assert all(a["nome_solucao"] == "BO Fácil" for a in leitura.achados({})["itens"])
    ids = [a["achado_id"] for a in leitura.achados({})["itens"]]
    assert leitura.achado(ids[0])["nome_solucao"] == "BO Fácil"
    chamada_id = repo.conn.execute("SELECT chamada_id FROM classificacoes ORDER BY classificacao_id LIMIT 1").fetchone()[0]
    assert [a["nome_solucao"] for a in leitura.chamada(chamada_id)["achados"]] == ["BO Fácil"]


def test_leitura_sem_a_coluna_ignora_o_campo(tmp_path, silencio):
    import sqlite3
    repo, _ = _estagio(tmp_path, ClassificadorQueDevolve("BO Fácil"))
    repo.conn.close()
    con = sqlite3.connect(tmp_path / "n.db")
    definicao = con.execute("SELECT sql FROM sqlite_master WHERE name='v_achados_revisao'").fetchone()[0]
    assert ", a.nome_solucao" in definicao
    con.execute("DROP VIEW v_achados_revisao")
    con.execute("DROP VIEW v_secretarias_confirmadas")
    con.execute("ALTER TABLE achados DROP COLUMN nome_solucao")
    con.execute(definicao.replace(", a.nome_solucao", ""))             # a view como era antes do RC15
    con.commit()
    con.close()
    leitura = LeituraPainelSQLite(tmp_path / "n.db")
    assert leitura.achados({"q": "BO Fácil"})["total"] == 0 and leitura.achados({"q": "ferramenta"})["total"] == 3
    a = leitura.achado(leitura.achados({})["itens"][0]["achado_id"])
    assert a["nome_solucao"] is None


# ---------- telas ----------
def _cliente(tmp_path):
    from fastapi.testclient import TestClient
    from config import vocabulario as V
    from painel.app import Contexto, criar_app
    banco = tmp_path / "n.db"
    ctx = Contexto(banco="demo", nome_banco=banco.name, somente_leitura=False, pasta_backup=tmp_path / "backups", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver", "127.0.0.1", "localhost"))
    return TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path / "raw"), ctx))


def test_telas_mostram_a_solucao_escapada_e_travessao_quando_vazia(tmp_path, silencio):
    texto = TEXTO_BO.replace("BO Fácil", "<b>BO Fácil</b>")
    repo, _ = _estagio(tmp_path, ClassificadorQueDevolve("<b>BO Fácil</b>"), texto=texto)
    repo.conn.execute("UPDATE achados SET nome_solucao=NULL WHERE achado_id=3")                  # um achado sem nome
    repo.confirmar()
    repo.conn.close()
    cli = _cliente(tmp_path)
    lista = cli.get("/achados").text
    assert "<th>Solução</th>" in lista and "&lt;b&gt;BO Fácil&lt;/b&gt;" in lista and "<b>BO Fácil</b>" not in lista
    assert lista.count("<td>—</td>") == 1
    achado = cli.get("/achados/1").text
    assert "<dt>Solução</dt>" in achado and "&lt;b&gt;BO Fácil&lt;/b&gt;" in achado and "<b>BO Fácil</b>" not in achado
    assert "<dt>Solução</dt><dd>—</dd>" in cli.get("/achados/3").text
    assert "&lt;b&gt;BO Fácil&lt;/b&gt;" in cli.get("/estados/PI").text
    assert cli.get("/achados?q=" + "BO F%C3%A1cil").status_code == 200
    assert "Nenhum achado com estes filtros" not in cli.get("/achados?q=%3Cb%3EBO").text           # a busca acha pelo nome da solucao


def test_relatorio_mostra_a_solucao_dos_achados_confirmados(tmp_path, silencio):
    from painel import relatorio
    repo, _ = _estagio(tmp_path, ClassificadorQueDevolve("BO Fácil"))
    repo.conn.execute("UPDATE achados SET verificado=1, status_final='em_uso' WHERE achado_id=1")
    repo.confirmar()
    leitura = LeituraPainelSQLite(tmp_path / "n.db")
    d = relatorio.coletar_dados(leitura, dict(C.UFS), {}, [], "real", "n.db", "16/10/2026")
    assert [a["nome_solucao"] for a in d["confirmados"]] == ["BO Fácil"]
    assert "Solução: <strong>BO Fácil</strong>" in relatorio._linha_achado(d["confirmados"][0], True)[0]
