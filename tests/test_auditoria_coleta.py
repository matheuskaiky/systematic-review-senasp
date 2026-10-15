"""Tudo o que a coleta mede ou decide precisa ficar no banco, inclusive o que da errado."""
import json
import logging
import subprocess
import sys

import pytest
import requests

import main
import config.settings as S
from adaptadores import busca_perplexity
from adaptadores.busca_perplexity import BuscaPerplexity
from dados_metricas import construir_classificacao_mista, construir_downloads
from dominio.modelos import ConsultaWeb, FiltrosBusca
from infra import http
from infra.util import coletar_ambiente


def _linhas(repo, view, where=""):
    return [dict(r) for r in repo.conn.execute(f"SELECT * FROM {view} {where}").fetchall()]


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# ---------- commit_git: arvore suja ----------
def _git(repo, *args):
    base = ["git", "-c", "user.name=teste", "-c", "user.email=teste@exemplo.org", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null"]
    return subprocess.run([*base, *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo_git(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    (tmp_path / "codigo.py").write_text("x = 1\n")
    (tmp_path / "DECISIONS.md").write_text("notas\n")
    (tmp_path / ".gitignore").write_text("data/\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "inicial")
    monkeypatch.setattr(S, "RAIZ", tmp_path)
    return tmp_path


def test_commit_limpo_devolve_so_o_hash_curto(repo_git):
    c = main._commit_git()
    assert c == _git(repo_git, "rev-parse", "--short", "HEAD").strip() and "+" not in c


def test_alteracao_em_arquivo_versionado_marca_sujo(repo_git):
    (repo_git / "codigo.py").write_text("x = 2\n")
    c = main._commit_git()
    base, _, marca = c.partition("+sujo:")
    assert base == _git(repo_git, "rev-parse", "--short", "HEAD").strip() and len(marca) == 8


def test_arquivo_novo_nao_versionado_marca_sujo(repo_git):
    (repo_git / "novo.py").write_text("y = 1\n")
    assert "+sujo:" in main._commit_git()


def test_o_hash_do_sujo_acompanha_o_conteudo(repo_git):
    (repo_git / "codigo.py").write_text("x = 2\n")
    a = main._commit_git()
    assert main._commit_git() == a                          # estavel
    (repo_git / "codigo.py").write_text("x = 3\n")
    assert main._commit_git() != a
    (repo_git / "novo.py").write_text("y = 1\n")
    b = main._commit_git()
    (repo_git / "novo.py").write_text("y = 2\n")
    assert main._commit_git() != b                          # conteudo de arquivo novo tambem conta


def test_decisions_e_gitignore_nao_contam_como_sujo(repo_git):
    (repo_git / "DECISIONS.md").write_text("outras notas\n")
    (repo_git / ".gitignore").write_text("data/\nlogs/\n")
    assert "+" not in main._commit_git()


def test_fora_de_repositorio_git_devolve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RAIZ", tmp_path)
    assert main._commit_git() is None


# ---------- infra.http: historico de tentativas ----------
class _Resp:
    def __init__(self, status, texto=""):
        self.status_code, self.text, self.content = status, texto, texto.encode()
        self.ok = status < 400
        self.closed = False

    def close(self):
        self.closed = True


def _sequencia(monkeypatch, itens):
    chamadas = []

    def falso(metodo, url, **kw):
        chamadas.append(1)
        item = itens[min(len(chamadas), len(itens)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http.requests, "request", falso)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def test_historico_registra_cada_tentativa_e_a_espera(monkeypatch):
    _sequencia(monkeypatch, [_Resp(429), _Resp(503), _Resp(200, "ok")])
    r = http.chamar("GET", "https://x")
    assert r["tentativas"] == 3 and r["erro"] is None
    h = r["historico"]
    assert [(x["tentativa"], x["http_status"], x["espera_s"]) for x in h] == [(1, 429, 2), (2, 503, 4), (3, 200, None)]
    assert [x["erro"] for x in h] == ["HTTP 429", "HTTP 503", None]
    assert all(isinstance(x["latencia_ms"], int) for x in h)
    assert isinstance(r["latencia_total_ms"], int) and r["latencia_total_ms"] >= r["latencia_ms"]


def test_historico_em_erro_de_rede(monkeypatch):
    _sequencia(monkeypatch, [requests.ConnectionError("sem rede")])
    r = http.chamar("GET", "https://x", max_tentativas=3)
    assert [x["http_status"] for x in r["historico"]] == [None, None, None]
    assert all("ConnectionError" in x["erro"] for x in r["historico"])
    assert [x["espera_s"] for x in r["historico"]] == [2, 4, None]


def test_latencia_total_inclui_as_esperas(monkeypatch):
    relogio = {"t": 0.0}
    monkeypatch.setattr(http.time, "perf_counter", lambda: relogio["t"])

    def dorme(s):
        relogio["t"] += s

    def falso(*a, **k):
        relogio["t"] += 0.25                      # cada tentativa leva 250 ms (valor exato em binario)
        return itens.pop(0)

    itens = [_Resp(503), _Resp(503), _Resp(200)]
    monkeypatch.setattr(http.requests, "request", falso)
    monkeypatch.setattr(http.time, "sleep", dorme)
    r = http.chamar("GET", "https://x")
    assert r["latencia_ms"] == 250                # so a ultima tentativa
    assert r["latencia_total_ms"] == 6750         # 3 x 250 ms + esperas de 2 s e 4 s


def test_extras_http_devolve_os_campos_para_o_adaptador(monkeypatch):
    _sequencia(monkeypatch, [_Resp(200)])
    e = http.extras_http(http.chamar("GET", "https://x"))
    assert set(e) == {"latencia_total_ms", "historico"} and len(e["historico"]) == 1
    assert http.extras_http({}) == {"latencia_total_ms": None, "historico": []}


def test_resposta_em_streaming_com_erro_e_fechada(monkeypatch):
    resp = _Resp(404, "x")
    _sequencia(monkeypatch, [resp])
    r = http.chamar("GET", "https://x", stream=True)
    assert r["erro"] == "HTTP 404" and resp.closed


def test_resposta_em_streaming_ok_nao_e_fechada(monkeypatch):
    resp = _Resp(200)
    _sequencia(monkeypatch, [resp])
    http.chamar("GET", "https://x", stream=True)
    assert not resp.closed


# ---------- adaptador Perplexity: extras ----------
def _consulta():
    return ConsultaWeb("M01-PI-x", "texto", "pt", "PI", "x", "M01", "oficial")


def _chamar_falso(monkeypatch, texto, **extra):
    r = {"resp": _Resp(200, texto), "http_status": 200, "latencia_ms": 12, "tentativas": 1, "erro": None, **extra}
    monkeypatch.setattr(busca_perplexity, "chamar", lambda *a, **k: r)


def test_perplexity_guarda_historico_e_latencia_total_nos_extras(monkeypatch):
    historico = [{"tentativa": 1, "http_status": 429, "latencia_ms": 5, "erro": "HTTP 429", "espera_s": 2},
                 {"tentativa": 2, "http_status": 200, "latencia_ms": 12, "erro": None, "espera_s": None}]
    _chamar_falso(monkeypatch, '{"results": []}', latencia_total_ms=2020, historico=historico)
    c = BuscaPerplexity("k", preco_por_requisicao_usd=0.005).buscar(_consulta(), FiltrosBusca()).chamada
    assert c.extras["latencia_total_ms"] == 2020 and c.extras["historico"] == historico
    assert c.extras["custo_origem"] == "estimado_preco_fixo"


def test_perplexity_guarda_usage_quando_a_api_devolve(monkeypatch):
    _chamar_falso(monkeypatch, '{"results": [], "usage": {"cost": {"total_cost": 0.005}}}')
    c = BuscaPerplexity("k").buscar(_consulta(), FiltrosBusca()).chamada
    assert c.extras["usage"] == {"cost": {"total_cost": 0.005}}
    assert "custo_origem" not in c.extras                   # sem preco configurado nao ha custo estimado


def test_perplexity_sem_usage_nao_cria_a_chave(monkeypatch):
    _chamar_falso(monkeypatch, '{"results": []}')
    assert "usage" not in BuscaPerplexity("k").buscar(_consulta(), FiltrosBusca()).chamada.extras


@pytest.mark.parametrize("texto, esperado", [('{"usage": {"a": 1}}', {"a": 1}), ('{"usage": 5}', None), ("nao e json", None),
                                             ("[1, 2]", None), ("{}", None)])
def test_extrair_uso_nunca_levanta(texto, esperado):
    assert BuscaPerplexity.extrair_uso(texto) == esperado


# ---------- ambiente da execucao ----------
def test_coletar_ambiente_traz_versoes_e_extras():
    a = coletar_ambiente({"pausas": {"download": 1.0}})
    assert a["python"].count(".") >= 1 and a["plataforma"] and a["pausas"] == {"download": 1.0}
    assert set(a["bibliotecas"]) == {"requests", "pandas", "openpyxl", "python-dotenv", "trafilatura", "pypdf"}
    assert a["bibliotecas"]["pandas"] and a["bibliotecas"]["requests"]


def test_execucao_grava_ambiente_argumentos_e_pausas(ambiente_cli, monkeypatch, silencio):
    import sqlite3
    monkeypatch.setattr(sys, "argv", ["main.py", "busca-web", "--simulado", "--ufs", "PI", "--limite", "2"])
    main.main()
    db = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    amb = json.loads(db.execute("SELECT ambiente_json FROM execucoes").fetchone()[0])
    assert amb["argumentos"]["ufs"] == ["PI"] and amb["argumentos"]["limite"] == 2 and amb["argumentos"]["cmd"] == "busca-web"
    assert amb["argumentos"]["simulado"] is True and amb["argumentos"]["auditoria"] == 0
    assert amb["pausas"] == {k: 0 for k in S.PAUSAS}                           # ambiente_cli zera as pausas
    assert amb["bibliotecas"]["pandas"] and len(amb["requirements_lock_sha256"]) == 64


def test_ambiente_nao_entra_no_hash_da_configuracao():
    a = S.snapshot_config()["hash"]
    S.PAUSAS["download"] += 1
    try:
        assert S.snapshot_config()["hash"] == a            # mudar pausas nao impede --retomar
    finally:
        S.PAUSAS["download"] -= 1


# ---------- download que falha: nada some ----------
def test_resultado_de_cada_download_inclui_as_falhas(tmp_path, silencio):
    repo, _ = construir_downloads(tmp_path)
    r = {l["url_id"]: l for l in _linhas(repo, "v_resultado_download")}
    por_motivo = {(l["resultado"], l["motivo"]) for l in r.values()}
    assert por_motivo == {("ok", "ok"), ("falha_download", "http_403"), ("falha_download", "bloqueado_por_robots"),
                          ("falha_download", "erro_de_rede")}
    falha = next(l for l in r.values() if l["motivo"] == "http_403")
    assert falha["http_status"] == 403 and falha["erro"] == "HTTP 403" and falha["pagina_id"] is None


def test_paginas_so_tem_os_downloads_bem_sucedidos_mas_a_view_mostra_todos(tmp_path, silencio):
    repo, run_id = construir_downloads(tmp_path)
    assert repo.conn.execute("SELECT COUNT(*) FROM paginas").fetchone()[0] == 1
    f = dict(repo.conn.execute("SELECT * FROM v_funil WHERE run_id=?", (run_id,)).fetchone())
    assert (f["pares_url_uf_selecionados"], f["paginas_baixadas"], f["paginas_com_texto"]) == (4, 1, 1)
    assert len(_linhas(repo, "v_resultado_download")) == 4


def test_extracao_agora_mostra_downloads_que_falharam(tmp_path, silencio):
    repo, _ = construir_downloads(tmp_path)
    e = {(l["resultado"], l["motivo"]): l for l in _linhas(repo, "v_extracao")}
    assert e[("ok", "ok")]["n_urls"] == 1 and e[("ok", "ok")]["pct"] == 25.0
    assert e[("falha_download", "http_403")]["n_urls"] == 1
    assert e[("falha_download", "erro_de_rede")]["pct"] == 25.0
    assert sum(l["n_urls"] for l in e.values()) == 4


def test_urls_selecionadas_e_nao_tentadas_por_causa_do_limite(tmp_path, silencio):
    repo, _ = construir_downloads(tmp_path, limite=1)
    r = {(l["resultado"], l["motivo"]) for l in _linhas(repo, "v_resultado_download")}
    assert r == {("ok", "ok"), ("nao_tentada", "limite_ou_interrompida")}
    assert len(_linhas(repo, "v_resultado_download", "WHERE resultado='nao_tentada'")) == 3


# ---------- classificacao: nada se perde ----------
def test_achados_fora_do_vocabulario_sao_guardados(tmp_path, silencio):
    repo, _ = construir_classificacao_mista(tmp_path)
    d = _linhas(repo, "achados_descartados", "ORDER BY descartado_id")
    assert len(d) == 4                                        # /pi/1, /pi/3 (snippet) e /pi/4 nao tem texto: 2 itens x 2 descartes
    assert {x["motivo"] for x in d} == {"tecnologia_fora_do_vocabulario", "status_fora_do_vocabulario"}
    t = next(x for x in d if x["motivo"] == "tecnologia_fora_do_vocabulario")
    assert (t["tecnologia"], t["evidencia"], t["confianca"], t["uf"]) == ("tecnologia_inventada", "trecho x", "alta", "PI")
    s = next(x for x in d if x["motivo"] == "status_fora_do_vocabulario")
    assert (s["tecnologia"], s["status"]) == ("leitura_placas", "status_inventado")
    assert repo.conn.execute("SELECT SUM(n_achados_invalidos) FROM classificacoes").fetchone()[0] == 4
    v = {(x["motivo"], x["tecnologia"]): x["n"] for x in _linhas(repo, "v_achados_descartados")}
    assert v == {("tecnologia_fora_do_vocabulario", "tecnologia_inventada"): 2, ("status_fora_do_vocabulario", "leitura_placas"): 2}


def test_confianca_original_e_guardada_quando_o_snippet_rebaixa(tmp_path, silencio):
    repo, _ = construir_classificacao_mista(tmp_path)
    por_origem = {(l["origem_texto"], l["confianca_original"], l["confianca"]): l["n"]
                  for l in _linhas(repo, "v_confianca_ajustada")}
    assert por_origem == {("pagina", "alta", "alta"): 1, ("snippet", "alta", "baixa"): 1}
    ajustada = _linhas(repo, "v_confianca_ajustada", "WHERE ajustada=1")
    assert len(ajustada) == 1 and ajustada[0]["origem_texto"] == "snippet"
    assert repo.conn.execute("SELECT COUNT(*) FROM achados WHERE confianca_original IS NULL").fetchone()[0] == 0


def test_item_sem_texto_utilizavel_fica_registrado(tmp_path, silencio):
    repo, run_id = construir_classificacao_mista(tmp_path)
    assert repo.conn.execute("SELECT valor FROM metricas_run WHERE chave='classificacao_ignorados_sem_texto'").fetchone()[0] == 1
    r = {l["url_id"]: l for l in _linhas(repo, "v_resultado_classificacao")}
    por_resultado = sorted((l["resultado"], l["motivo"]) for l in r.values())
    assert por_resultado == [("classificado", None), ("classificado", None), ("falha_chamada", "HTTP 500: falha"),
                             ("nao_classificado", "sem_texto_utilizavel")]
    sem = next(l for l in r.values() if l["resultado"] == "nao_classificado")
    assert (sem["tem_texto_de_pagina"], sem["tem_snippet"]) == (0, 0)


def test_snippet_desativado_distingue_o_motivo(tmp_path, silencio):
    repo, _ = construir_classificacao_mista(tmp_path, usar_snippet=False)
    assert repo.conn.execute("SELECT valor FROM metricas_run WHERE chave='classificacao_ignorados_sem_texto'").fetchone()[0] == 2
    motivos = sorted(l["motivo"] for l in _linhas(repo, "v_resultado_classificacao", "WHERE resultado='nao_classificado'"))
    assert motivos == ["sem_texto_de_pagina_e_snippet_nao_usado_ou_interrompida", "sem_texto_utilizavel"]


# ---------- segredos nunca chegam ao banco nem ao log ----------
SEGREDO = "SEGREDO-FALSO-ABC123"
SEGREDO_COM_SIMBOLOS = "ab/c+d=e&f"


def _porta_fechada():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


@pytest.fixture
def sem_espera(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def test_segredo_da_query_string_nao_aparece_no_erro_nem_no_historico_nem_no_log(sem_espera, caplog):
    caplog.set_level(logging.INFO)
    url = f"http://127.0.0.1:{_porta_fechada()}/search.json"
    r = http.chamar("GET", url, params={"engine": "google", "api_key": SEGREDO}, max_tentativas=2)
    assert r["resp"] is None and r["erro"]                         # a conexao realmente falhou
    assert SEGREDO not in r["erro"] and "***" in r["erro"]
    assert SEGREDO not in json.dumps(r["historico"]) and all("***" in h["erro"] for h in r["historico"])
    assert SEGREDO not in caplog.text and "Network error" in caplog.text


def test_segredo_com_simbolos_aparece_codificado_na_url_e_tambem_e_limpo(sem_espera, caplog):
    caplog.set_level(logging.INFO)
    url = f"http://127.0.0.1:{_porta_fechada()}/search.json"
    r = http.chamar("GET", url, params={"api_key": SEGREDO_COM_SIMBOLOS}, max_tentativas=1)
    from urllib.parse import quote, quote_plus
    for forma in (SEGREDO_COM_SIMBOLOS, quote(SEGREDO_COM_SIMBOLOS, safe=""), quote_plus(SEGREDO_COM_SIMBOLOS)):
        assert forma not in r["erro"] and forma not in caplog.text


def test_segredo_de_cabecalho_authorization_e_limpo(sem_espera, caplog):
    caplog.set_level(logging.INFO)
    r = http.chamar("POST", f"http://127.0.0.1:{_porta_fechada()}/x", max_tentativas=1,
                    headers={"Authorization": f"Bearer {SEGREDO}", "x-goog-api-key": "OUTRO-SEGREDO-FALSO"})
    assert SEGREDO not in r["erro"] and "OUTRO-SEGREDO-FALSO" not in r["erro"]


def test_corpo_de_erro_que_ecoa_o_segredo_e_limpo(monkeypatch):
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: _Resp(401, f"chave invalida: {SEGREDO}"))
    r = http.chamar("GET", "https://x", params={"api_key": SEGREDO})
    assert SEGREDO not in r["erro"] and r["erro"].startswith("HTTP 401: chave invalida: ***")
    assert SEGREDO not in json.dumps(r["historico"])


def test_segredos_da_chamada_so_pega_campos_sensiveis_e_valores_longos():
    s = http.segredos_da_chamada({"api_key": SEGREDO, "q": "texto livre", "token": "ab"},
                                 {"Authorization": "Bearer ABCDEF123", "Content-Type": "application/json"})
    assert s == {SEGREDO, "Bearer ABCDEF123", "ABCDEF123"}          # "ab" e curto demais; q e Content-Type nao sao sensiveis
    assert http.segredos_da_chamada(None, None) == set()


def test_limpar_segredos_sem_texto_ou_sem_segredos():
    assert http.limpar_segredos(None, {SEGREDO}) is None and http.limpar_segredos("", {SEGREDO}) == ""
    assert http.limpar_segredos("nada a limpar", set()) == "nada a limpar"


def test_registrar_chamada_limpa_erro_parametros_e_extras(tmp_path):
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from aplicacao.comum import registrar_chamada
    from dados_metricas import _novo_run
    from dominio.modelos import RegistroChamada
    repo, bruto = RepositorioSQLite(tmp_path / "s.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "t")
    reg = RegistroChamada(provedor="p", operacao="o", parametros={"q": "x", "url": f"https://x?api_key={SEGREDO}"},
                          requisitado_em="2026-01-01T00:00:00+00:00", erro=f"falhou em /s?api_key={SEGREDO}",
                          extras={"historico": [{"erro": f"ReadTimeout(url=/s?api_key={SEGREDO})"}], "aninhado": {"k": SEGREDO}})
    registrar_chamada(repo, bruto, run_id, "busca_academica", "termo", "T01", "k" * 40, reg, [SEGREDO])
    linha = repo.conn.execute("SELECT erro, parametros_json, extras_json FROM chamadas").fetchone()
    assert all(SEGREDO not in campo for campo in linha) and "***" in linha["erro"]
    assert json.loads(linha["extras_json"])["aninhado"] == {"k": "***"}
    assert json.loads(linha["parametros_json"])["q"] == "x"
    assert reg.erro and not reg.sucesso                         # continua sendo uma falha


def test_registrar_chamada_sem_segredos_nao_altera_o_registro(tmp_path):
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from aplicacao.comum import registrar_chamada
    from dados_metricas import _novo_run
    from dominio.modelos import RegistroChamada
    repo = RepositorioSQLite(tmp_path / "s.db")
    run_id = _novo_run(repo, "t")
    reg = RegistroChamada(provedor="p", operacao="o", parametros={"q": "x"}, requisitado_em="2026-01-01T00:00:00+00:00",
                          extras={"a": [1, 2]})
    registrar_chamada(repo, BrutoLocal(tmp_path / "raw"), run_id, "busca_web", "consulta_web", "c", "k" * 40, reg, [])
    assert reg.extras == {"a": [1, 2]} and reg.parametros == {"q": "x"}


# ---------- saldos e metricas por execucao ----------
def _saldo(repo, run_id, provedor, momento, valor, quando):
    repo.conn.execute("INSERT INTO saldos (run_id, provedor, momento, valor, registrado_em) VALUES (?,?,?,?,?)",
                      (run_id, provedor, momento, valor, quando))


def _chamada_ok(repo, run_id, quando, provedor="serpapi_scholar", sucesso=True):
    from dominio.modelos import RegistroChamada
    reg = RegistroChamada(provedor=provedor, operacao="o", parametros={}, requisitado_em=quando, http_status=200,
                          latencia_ms=1, tentativas=1, erro=None if sucesso else "x")
    repo.salvar_chamada(run_id=run_id, etapa="busca_academica", alvo_tipo="termo", alvo_id="T01",
                        chave=f"{quando}-{sucesso}", registro=reg, raw_path=None, raw_sha256=None)


def test_v_saldos_tem_uma_linha_por_passada_sem_cruzar_inicios_e_fins(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from dados_metricas import _novo_run
    repo = RepositorioSQLite(tmp_path / "s.db")
    run_id = _novo_run(repo, "academico")
    dia = "2026-10-14T"
    _saldo(repo, run_id, "serpapi_scholar", "inicio", 100, dia + "10:00:00+00:00")
    for m in range(1, 6):
        _chamada_ok(repo, run_id, dia + f"10:0{m}:00+00:00")
    _saldo(repo, run_id, "serpapi_scholar", "fim", 95, dia + "10:06:00+00:00")
    _saldo(repo, run_id, "serpapi_scholar", "inicio", 95, dia + "11:00:00+00:00")      # retomada
    for m in range(1, 4):
        _chamada_ok(repo, run_id, dia + f"11:0{m}:00+00:00")
    _chamada_ok(repo, run_id, dia + "11:04:00+00:00", sucesso=False)                    # falha nao conta
    _saldo(repo, run_id, "serpapi_scholar", "fim", 92, dia + "11:06:00+00:00")
    _saldo(repo, run_id, "serpapi_scholar", "inicio", 92, dia + "12:00:00+00:00")      # terceira passada, interrompida
    _chamada_ok(repo, run_id, dia + "12:01:00+00:00")
    repo.confirmar()
    v = _linhas(repo, "v_saldos", "ORDER BY passada")
    assert [(x["passada"], x["saldo_inicio"], x["saldo_fim"], x["consumo"], x["chamadas_ok"], x["diferenca"]) for x in v] == [
        (1, 100, 95, 5, 5, 0), (2, 95, 92, 3, 3, 0), (3, 92, None, None, 1, None)]


def test_v_saldos_provedor_sem_fim_e_chamadas_de_outro_provedor(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from dados_metricas import _novo_run
    repo = RepositorioSQLite(tmp_path / "s.db")
    run_id = _novo_run(repo, "academico")
    _saldo(repo, run_id, "serpapi_scholar", "inicio", 10, "2026-10-14T10:00:00+00:00")
    _saldo(repo, run_id, "serpapi_scholar", "fim", 8, "2026-10-14T10:05:00+00:00")
    _chamada_ok(repo, run_id, "2026-10-14T10:01:00+00:00")
    _chamada_ok(repo, run_id, "2026-10-14T10:02:00+00:00", provedor="outro")
    repo.confirmar()
    v = _linhas(repo, "v_saldos")
    assert len(v) == 1 and (v[0]["consumo"], v[0]["chamadas_ok"], v[0]["diferenca"]) == (2, 1, 1)   # divergencia visivel


# ---------- retomada: commit e ambiente de cada passada ----------
def test_retomar_preserva_a_execucao_original_e_registra_a_passada(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    repo = RepositorioSQLite(tmp_path / "r.db")
    rid = repo.iniciar_execucao("t", "h", "{}", "aaa1111", ambiente_json='{"v": 1}')
    assert repo.iniciar_execucao("t", "h", "{}", "bbb2222+sujo:99", retomar=rid, ambiente_json='{"v": 2}') == rid
    repo.iniciar_execucao("t", "h", "{}", "ccc3333", retomar=rid, ambiente_json='{"v": 3}')
    assert tuple(repo.conn.execute("SELECT commit_git, ambiente_json FROM execucoes").fetchone()) == ("aaa1111", '{"v": 1}')
    p = _linhas(repo, "v_passadas", "ORDER BY passada")
    assert [(x["passada"], x["tipo"], x["commit_git"], x["ambiente_json"]) for x in p] == [
        (1, "original", "aaa1111", '{"v": 1}'), (2, "retomada", "bbb2222+sujo:99", '{"v": 2}'), (3, "retomada", "ccc3333", '{"v": 3}')]
    assert all(x["inicio"] for x in p)


def test_cli_retomar_grava_o_ambiente_da_retomada(ambiente_cli, monkeypatch, silencio):
    import sqlite3
    monkeypatch.setattr(sys, "argv", ["main.py", "busca-web", "--simulado", "--ufs", "PI", "--limite", "1"])
    main.main()
    db = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    run_id = db.execute("SELECT run_id FROM execucoes").fetchone()[0]
    monkeypatch.setattr(sys, "argv", ["main.py", "busca-web", "--simulado", "--ufs", "PI", "--limite", "1", "--retomar", run_id])
    main.main()
    passadas = db.execute("SELECT tipo, ambiente_json FROM v_passadas ORDER BY passada").fetchall()
    assert [p[0] for p in passadas] == ["original", "retomada"]
    assert json.loads(passadas[0][1])["argumentos"]["retomar"] is None and json.loads(passadas[1][1])["argumentos"]["retomar"] == run_id


# ---------- datas em um unico formato (UTC, ISO 8601) ----------
def test_run_id_e_datas_das_importacoes_usam_utc_iso(tmp_path):
    import re
    from datetime import datetime
    import pandas as pd
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from dados_metricas import _id_artigo, construir_academico
    repo, run_id = construir_academico(tmp_path / "a.db")
    iniciado = repo.conn.execute("SELECT iniciado_em FROM execucoes WHERE run_id=?", (run_id,)).fetchone()[0]
    de_run_id = datetime.strptime(run_id[:15], "%Y%m%d_%H%M%S")
    de_iniciado = datetime.fromisoformat(iniciado).replace(tzinfo=None)
    assert abs((de_run_id - de_iniciado).total_seconds()) <= 2        # mesmo fuso: UTC
    repo.importar_triagem(pd.DataFrame([{"artigo_id": _id_artigo(repo, 1), "decisao": "incluir", "motivo": None,
                                         "confirmado_em_base": None, "link_confirmado": None, "revisor": "Ana"}]))
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
    assert iso.match(repo.conn.execute("SELECT revisado_em FROM triagem").fetchone()[0])
    assert iso.match(repo.conn.execute("SELECT importado_em FROM triagem_revisoes").fetchone()[0])


def test_verificado_em_usa_utc_iso(tmp_path, silencio):
    import re
    import pandas as pd
    from dados_metricas import construir_web
    repo, _ = construir_web(tmp_path)
    achado = repo.conn.execute("SELECT achado_id FROM achados WHERE verificado=0").fetchone()[0]
    repo.importar_verificacao_achados(pd.DataFrame([{"achado_id": achado, "verificado": 1, "status_final": "em_uso",
                                                     "verificado_por": "Ana", "observacao": None}]), {"em_uso"})
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$",
                    repo.conn.execute("SELECT verificado_em FROM achados WHERE achado_id=?", (achado,)).fetchone()[0])


# ---------- metrica de itens ignorados sobrevive a uma interrupcao ----------
def test_metrica_de_ignorados_e_gravada_antes_de_uma_interrupcao(tmp_path, silencio):
    from dataclasses import replace
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from adaptadores.simulados import FetcherSimulado
    from aplicacao import busca_web, classificacao, download
    from config import consultas as C
    from dados_metricas import (BuscaSemTextoNoQuatro, ExtratorSimulado, _consulta_pi, _novo_run, _params)
    import sqlite3

    class FalhaEmPi1(ExtratorSimulado):
        def extrair(self, conteudo, content_type, url):
            from dominio.modelos import TextoExtraido
            return TextoExtraido("", "x", False, "texto_insuficiente") if url.endswith("/pi/1") else super().extrair(conteudo, content_type, url)

    class Interrompe:
        nome = "interrompe"

        def classificar(self, entrada, instr):
            raise KeyboardInterrupt

    repo = RepositorioSQLite(tmp_path / "i.db")
    bruto = BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "t")
    busca_web.executar(repo, bruto, BuscaSemTextoNoQuatro(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherSimulado(), FalhaEmPi1(), run_id, run_id, replace(C.POLITICA_DOWNLOAD, palavras_chave=()), [], 0, ufs={"PI"})
    with pytest.raises(KeyboardInterrupt):
        classificacao.executar(repo, bruto, Interrompe(), run_id, run_id, replace(_params(), usar_snippet_se_falhar=False),
                               C.UFS, [], 0, ufs={"PI"})
    repo.conn.commit()                                  # o que finalizar_execucao faz ao encerrar
    outro = sqlite3.connect(tmp_path / "i.db")
    assert outro.execute("SELECT valor FROM metricas_run WHERE chave='classificacao_ignorados_sem_texto'").fetchone()[0] == 1


