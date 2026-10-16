"""Leituras de adaptadores/leitura_solucoes.py (busca no texto e solucoes conhecidas): bancos montados a mao com o esquema real,
arquivos de texto em um BrutoLocal temporario, banco antigo e banco sem arquivos. So le; nenhum teste chama API."""
import shutil
import sqlite3
import uuid

import pytest

from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.leitura_solucoes import LeituraSolucoes
from adaptadores.repositorio_sqlite import RepositorioSQLite
from dominio.solucoes import SolucaoConhecida, normalizar, variantes_da_solucao

assert issubclass(LeituraPainelSQLite, LeituraSolucoes)

XSS_TITULO = "<script>alert(1)</script> Beta Sistema inaugurado"
XSS_TEXTO = "<img src=x onerror=alert(2)> O aplicativo Gama App atende o cidadão. Gama Apps não é o mesmo nome."
S1 = SolucaoConhecida("Zeta Alfa", "PI")                                     # nao apareceu em lugar nenhum
S2 = SolucaoConhecida("Beta Sistema", "PI")                                   # so em resultados de busca, pagina nunca baixada
S3 = SolucaoConhecida("Gama App", "PI")                                       # no texto de pagina baixada, nenhum achado cita o nome
S4 = SolucaoConhecida("Delta Bot", "PI", apelidos=("DB Bot",))                # citada na evidencia de um achado
SOLUCOES = (S1, S2, S3, S4)


def sql(banco, comando, args=()):
    conn = sqlite3.connect(banco)
    try:
        cur = conn.execute(comando, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


class Montagem:
    """Linhas minimas, com as colunas obrigatorias do esquema real."""

    def __init__(self, banco, raiz):
        self.banco, self.bruto = banco, BrutoLocal(raiz)

    def execucao(self, run, no_relatorio=1):
        sql(self.banco, "INSERT INTO execucoes(run_id, iniciado_em, comando, config_hash, config_json, no_relatorio) VALUES (?, ?, 'x', 'h', '{}', ?)",
            (run, f"2026-10-1{no_relatorio + 4}T00:00:00", no_relatorio))

    def chamada(self, run, etapa="busca_web"):
        return sql(self.banco, """INSERT INTO chamadas(run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em, sucesso)
                                  VALUES (?, ?, 'p', '{}', ?, '2026-10-16T00:00:00', 1)""", (run, etapa, uuid.uuid4().hex))

    def url(self, url, dominio="pi.gov.br"):
        return sql(self.banco, "INSERT INTO urls(url_normalizada, url_original, dominio) VALUES (?, ?, ?)", (url + "#n", url, dominio))

    def resultado(self, run, consulta, url_id, titulo, snippet="", uf="PI", posicao=1):
        sql(self.banco, """INSERT INTO resultados_web(chamada_id, run_id, consulta_id, uf, url_id, posicao, titulo, snippet)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (self.chamada(run), run, consulta, uf, url_id, posicao, titulo, snippet))

    def selecao(self, run, url_id, uf="PI", selecionada=1):
        sql(self.banco, "INSERT INTO selecao_download(run_id, url_id, uf, selecionada) VALUES (?, ?, ?, ?)", (run, url_id, uf, selecionada))

    def pagina(self, run, url_id, texto, ok=1, escrever=True, dominio="pi.gov.br"):
        caminho = None
        if texto is not None:
            caminho, _ = self.bruto.salvar("texto", run, f"u{url_id}", texto.encode("utf-8"), "txt")
            if not escrever:
                (self.bruto.raiz / caminho).unlink()
        return sql(self.banco, """INSERT INTO paginas(run_id, url_id, chamada_id, url_final, http_status, texto_path, n_chars, extracao_ok, dominio_final)
                                  VALUES (?, ?, ?, ?, 200, ?, ?, ?, ?)""", (run, url_id, self.chamada(run, "download"), "https://" + dominio + "/final",
                                                                          caminho, len(texto or ""), ok, dominio))

    def achado(self, run, url_id, pagina_id, evidencia, tecnologia="outra_ia", status="em_uso", uf="PI", nome=None):
        cid = sql(self.banco, "INSERT INTO classificacoes(chamada_id, run_id, url_id, pagina_id, uf) VALUES (?, ?, ?, ?, ?)",
                  (self.chamada(run, "classificacao"), run, url_id, pagina_id, uf))
        aid = sql(self.banco, """INSERT INTO achados(classificacao_id, uf, tecnologia, status_reportado, evidencia, confianca)
                                 VALUES (?, ?, ?, ?, ?, 'alta')""", (cid, uf, tecnologia, status, evidencia))
        if nome is not None:
            sql(self.banco, "UPDATE achados SET nome_solucao=? WHERE achado_id=?", (nome, aid))
        return aid


def semear(banco, raiz):
    """Um cenario para cada situacao de uma solucao conhecida. Devolve os ids para as conferencias."""
    m = Montagem(banco, raiz)
    m.execucao("SOL1", 1)
    m.execucao("SOL0", 0)                                                      # piloto, fora do relatorio
    ids = {}
    # S2: o titulo cita; pagina nunca baixada (selecionada so no piloto)
    ids["u_beta"] = m.url("https://pi.gov.br/beta")
    m.resultado("SOL0", "C-PI-a", ids["u_beta"], XSS_TITULO, posicao=3)
    m.selecao("SOL0", ids["u_beta"])
    # URL perigosa: o endereco nao e http/https
    ids["u_js"] = m.url("javascript:alert(7)")
    m.resultado("SOL1", "C-PI-b", ids["u_js"], "Beta Sistema em aviso", posicao=2)
    # S3: pagina baixada cujo texto cita o nome; o achado dela descreve sem o nome
    ids["u_gama"] = m.url("https://ssp.pi.gov.br/gama", "ssp.pi.gov.br")
    m.resultado("SOL1", "C-PI-c", ids["u_gama"], "Notícia de segurança", "um aplicativo novo", posicao=5)
    m.selecao("SOL1", ids["u_gama"])
    ids["p_gama"] = m.pagina("SOL1", ids["u_gama"], XSS_TEXTO, dominio="ssp.pi.gov.br")
    ids["a_gama"] = m.achado("SOL1", ids["u_gama"], ids["p_gama"], "o aplicativo atende o cidadão pelo celular")
    # S4: pagina baixada e achado cuja evidencia cita o apelido (sem acento e em maiusculas)
    ids["u_delta"] = m.url("https://pi.gov.br/delta")
    m.selecao("SOL1", ids["u_delta"])
    ids["p_delta"] = m.pagina("SOL1", ids["u_delta"], "Texto sobre o DELTA-BOT, ou DB Bot, em uso no Piauí. Delta Bots é outro nome.")
    ids["a_delta"] = m.achado("SOL1", ids["u_delta"], ids["p_delta"], "O DB Bot atende ocorrências", tecnologia="reconhecimento_facial")
    # pagina de outra UF e pagina sem arquivo de texto (nao quebram nada)
    ids["u_ce"] = m.url("https://ce.gov.br/delta", "ce.gov.br")
    m.selecao("SOL1", ids["u_ce"], uf="CE")
    m.pagina("SOL1", ids["u_ce"], "Delta Bot no Ceará", dominio="ce.gov.br")
    ids["u_falta"] = m.url("https://pi.gov.br/falta")
    m.selecao("SOL1", ids["u_falta"])
    m.pagina("SOL1", ids["u_falta"], "Delta Bot some do disco", escrever=False)
    ids["u_vazia"] = m.url("https://pi.gov.br/vazia")
    m.selecao("SOL1", ids["u_vazia"])
    m.pagina("SOL1", ids["u_vazia"], None, ok=0)                                # extracao falhou: nao e pesquisada
    return ids


@pytest.fixture(scope="module")
def modelo(tmp_path_factory):
    """Banco e arquivos montados uma vez (criar o esquema e gravar linha a linha levam alguns segundos)."""
    pasta = tmp_path_factory.mktemp("solucoes")
    banco = pasta / "busca.db"
    RepositorioSQLite(banco).fechar()
    return banco, pasta / "raw", semear(banco, pasta / "raw")


@pytest.fixture
def cenario(modelo, tmp_path):
    banco0, raiz0, ids = modelo
    banco, raiz = tmp_path / "busca.db", tmp_path / "raw"
    shutil.copy(banco0, banco)
    shutil.copytree(raiz0, raiz)
    return LeituraPainelSQLite(banco), dict(ids), banco, raiz


def termos(s):
    return variantes_da_solucao(s)


# ---------- paginas para busca ----------
def test_paginas_para_busca_so_com_texto_extraido_e_uma_linha_por_url_e_uf(cenario):
    leitura, ids, _, _ = cenario
    linhas = leitura.paginas_para_busca_texto()
    por_url = {(l["url_id"], l["uf"]): l for l in linhas}
    assert (ids["u_vazia"], "PI") not in por_url                                 # sem texto extraido
    assert (ids["u_beta"], "PI") not in por_url                                  # nunca baixada
    assert {(ids["u_gama"], "PI"), (ids["u_delta"], "PI"), (ids["u_ce"], "CE"), (ids["u_falta"], "PI")} <= set(por_url)
    l = por_url[(ids["u_gama"], "PI")]
    assert set(l) >= {"pagina_id", "url_id", "uf", "url", "dominio_final", "texto_path", "run_id"}
    assert l["url"] == "https://ssp.pi.gov.br/gama" and l["dominio_final"] == "ssp.pi.gov.br" and l["run_id"] == "SOL1"
    assert [l["uf"] for l in leitura.paginas_para_busca_texto(["CE"])] == ["CE"]
    assert {l["uf"] for l in leitura.paginas_para_busca_texto(["PI", "CE"])} == {"PI", "CE"}
    assert leitura.paginas_para_busca_texto(["XX"]) == []


def test_url_conhecida_em_duas_ufs_gera_uma_linha_por_uf_e_vale_a_pagina_mais_nova(cenario):
    leitura, ids, banco, raiz = cenario
    m = Montagem(banco, raiz)
    m.selecao("SOL1", ids["u_gama"], uf="CE")                                     # a mesma URL tambem foi achada para o CE
    nova = m.pagina("SOL1", ids["u_gama"], "Texto novo da mesma pagina", dominio="ssp.pi.gov.br")
    linhas = [l for l in leitura.paginas_para_busca_texto() if l["url_id"] == ids["u_gama"]]
    assert sorted(l["uf"] for l in linhas) == ["CE", "PI"]
    assert {l["pagina_id"] for l in linhas} == {nova}


def test_resultado_web_tambem_define_a_uf_da_pagina(cenario):
    leitura, ids, banco, raiz = cenario
    m = Montagem(banco, raiz)
    novo = m.url("https://to.gov.br/x", "to.gov.br")
    m.resultado("SOL1", "C-TO", novo, "algo", uf="TO")                           # sem selecao_download
    m.pagina("SOL1", novo, "texto de Tocantins", dominio="to.gov.br")
    assert [l["uf"] for l in leitura.paginas_para_busca_texto(["TO"])] == ["TO"]


# ---------- resultados de busca ----------
def test_resultados_que_citam_trazem_run_consulta_posicao_e_se_a_pagina_foi_baixada(cenario):
    leitura, ids, _, _ = cenario
    r = leitura.resultados_busca_que_citam(termos(S2), "PI")
    assert [(x["run_id"], x["consulta_id"], x["posicao"]) for x in r] == [("SOL1", "C-PI-b", 2), ("SOL0", "C-PI-a", 3)]   # relatorio primeiro
    piloto = r[1]
    assert piloto["titulo"] == XSS_TITULO and piloto["url"] == "https://pi.gov.br/beta"
    assert piloto["no_relatorio"] == 0 and r[0]["no_relatorio"] == 1
    assert piloto["n_paginas"] == 0 and piloto["n_paginas_com_texto"] == 0 and piloto["selecionada"] == 1
    assert r[0]["selecionada"] == 0


def test_resultado_cita_pelo_resumo_e_baixada_conta_paginas(cenario):
    leitura, ids, _, _ = cenario
    r = leitura.resultados_busca_que_citam(termos(S3), "PI")
    assert r == [] or all(x["url_id"] == ids["u_gama"] for x in r)                  # titulo e resumo dele nao citam "Gama App"
    r = leitura.resultados_busca_que_citam([normalizar("aplicativo novo")], "PI")
    assert len(r) == 1 and r[0]["n_paginas"] == 1 and r[0]["n_paginas_com_texto"] == 1 and r[0]["selecionada"] == 1


def test_resultados_respeitam_a_uf_e_a_palavra_inteira(cenario):
    leitura, _, _, _ = cenario
    assert leitura.resultados_busca_que_citam(termos(S2), "CE") == []
    assert leitura.resultados_busca_que_citam(termos(S1), "PI") == []
    assert leitura.resultados_busca_que_citam([normalizar("sistem")], "PI") == []     # nao e palavra inteira
    assert leitura.resultados_busca_que_citam([], "PI") == []


# ---------- achados ----------
def test_achados_que_citam_pela_evidencia_com_apelido_sem_acento_e_caixa(cenario):
    leitura, ids, _, _ = cenario
    r = leitura.achados_que_citam(termos(S4), "PI")
    assert [(a["achado_id"], a["citado_em"]) for a in r] == [(ids["a_delta"], "evidencia")]
    assert r[0]["tecnologia"] == "reconhecimento_facial" and r[0]["url_id"] == ids["u_delta"] and r[0]["run_id"] == "SOL1"
    assert leitura.achados_que_citam(termos(S3), "PI") == [] and leitura.achados_que_citam(termos(S4), "CE") == []


def test_achados_da_url_e_em_lote(cenario):
    leitura, ids, _, _ = cenario
    a = leitura.achados_da_url(ids["u_gama"], "PI")
    assert [(x["achado_id"], x["tecnologia"], x["status_reportado"], x["confianca"]) for x in a] == [(ids["a_gama"], "outra_ia", "em_uso", "alta")]
    assert leitura.achados_da_url(ids["u_gama"], "CE") == [] and leitura.achados_da_url(999999, "PI") == []
    lote = leitura.achados_das_urls([(ids["u_gama"], "PI"), (ids["u_delta"], "PI"), (ids["u_beta"], "PI")])
    assert [len(lote[(ids["u_gama"], "PI")]), len(lote[(ids["u_delta"], "PI")]), len(lote[(ids["u_beta"], "PI")])] == [1, 1, 0]


def test_coluna_nome_solucao_e_usada_quando_existe(cenario):
    leitura, ids, banco, raiz = cenario
    assert "nome_solucao" not in leitura.achados_da_url(ids["u_gama"], "PI")[0]
    sql(banco, "ALTER TABLE achados ADD COLUMN nome_solucao TEXT")
    aid = Montagem(banco, raiz).achado("SOL1", ids["u_gama"], ids["p_gama"], "descricao sem o nome", nome="Gama App")
    assert any(a["achado_id"] == aid and a["nome_solucao"] == "Gama App" for a in leitura.achados_da_url(ids["u_gama"], "PI"))
    r = leitura.achados_que_citam(termos(S3), "PI")
    assert [(a["achado_id"], a["citado_em"]) for a in r] == [(aid, "nome_solucao")]


# ---------- bancos incomuns ----------
def test_banco_antigo_sem_as_tabelas_devolve_vazio(tmp_path):
    antigo = tmp_path / "antigo.db"
    sql(antigo, "CREATE TABLE urls (url_id INTEGER PRIMARY KEY, url_original TEXT)")
    leitura = LeituraPainelSQLite(antigo)
    assert leitura.paginas_para_busca_texto() == [] and leitura.paginas_para_busca_texto(["PI"]) == []
    assert leitura.resultados_busca_que_citam([" a "], "PI") == [] and leitura.achados_que_citam([" a "], "PI") == []
    assert leitura.achados_da_url(1, "PI") == [] and leitura.achados_das_urls([(1, "PI")]) == {}


def test_banco_vazio_com_o_esquema_devolve_vazio(tmp_path):
    banco = tmp_path / "vazio.db"
    RepositorioSQLite(banco).fechar()
    leitura = LeituraPainelSQLite(banco)
    assert leitura.paginas_para_busca_texto() == [] and leitura.resultados_busca_que_citam([" a "], "PI") == []
    assert leitura.achados_que_citam([" a "], "PI") == [] and leitura.achados_da_url(1, "PI") == []


def test_a_leitura_nao_grava_no_banco(cenario):
    leitura, ids, banco, _ = cenario
    antes = banco.read_bytes()
    leitura.paginas_para_busca_texto(); leitura.resultados_busca_que_citam(termos(S2), "PI"); leitura.achados_que_citam(termos(S4), "PI")
    leitura.achados_da_url(ids["u_gama"], "PI")
    assert banco.read_bytes() == antes
