"""Robustez do download e execucoes de teste fora do relatorio. Nenhum teste abre conexao: `chamar` e `requests.get` sao substituidos."""
import logging
import sqlite3
import sys
import threading
import time

import pytest
import requests

import main
from adaptadores import fetcher_requests
from adaptadores.bruto_local import BrutoLocal
from adaptadores.extrator_padrao import ExtratorPadrao
from adaptadores.fetcher_requests import FetcherRequests
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import ClassificadorSimulado, ExtratorSimulado, _TEXTO
from aplicacao import busca_web, classificacao, download
from config import consultas as C
from dados_metricas import (Busca4Urls, _chamada_academica, _consulta_pi, _novo_run, _params, construir_academico,
                            construir_web)
from dominio.modelos import RegistroChamada
from infra import http

UA = "AcademicResearch-AIPublicSecurity/1.0 (contact: teste@exemplo.org)"
A, B = "https://a.gov.br/p", "https://b.example/final"


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# ====================== fakes do fetcher ======================
class Resp:
    def __init__(self, blocos=(b"conteudo",), ctype="text/html", url=A, status=200, location=None, avanco=0.0, relogio=None):
        self.headers = {}
        if ctype:
            self.headers["Content-Type"] = ctype
        if location:
            self.headers["Location"] = location
        self.url, self.status_code, self._blocos, self.closed = url, status, list(blocos), False
        self._avanco, self._relogio = avanco, relogio

    def iter_content(self, tamanho):
        for b in self._blocos:
            if self._relogio is not None:
                self._relogio["t"] += self._avanco
            yield b

    def close(self):
        self.closed = True


class Rede:
    """Substitui `chamar` do fetcher: cada URL tem uma resposta; `pedidos` guarda o que foi requisitado."""
    def __init__(self, monkeypatch, paginas, relogio=None, avanco=0.0):
        self.paginas, self.pedidos, self._relogio, self._avanco = paginas, [], relogio, avanco
        monkeypatch.setattr(fetcher_requests, "chamar", self.chamar)

    def chamar(self, metodo, url, **kw):
        self.pedidos.append((url, kw))
        if self._relogio is not None:
            self._relogio["t"] += self._avanco                # cada requisicao "demora" este tanto
        resp, erro, status, corpo = (list(self.paginas[url]) + [None] * 4)[:4] if isinstance(self.paginas[url], tuple) else (self.paginas[url], None, 200, None)
        return {"resp": resp, "http_status": status, "latencia_ms": 10, "tentativas": 1, "erro": erro, "corpo_erro": corpo,
                "latencia_total_ms": 10, "historico": [{"tentativa": 1, "http_status": status, "latencia_ms": 10, "erro": erro, "espera_s": None}]}


class Robots:
    def __init__(self, texto="", status=200):
        self.text, self.status_code, self.ok = texto, status, status < 400


@pytest.fixture
def robots(monkeypatch):
    estado = {"respostas": {}, "padrao": Robots("", 404)}

    def falso(url, **kw):
        r = estado["respostas"].get(url, estado["padrao"])
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(fetcher_requests.requests, "get", falso)
    return estado


def _redir(destino, url=A, status=302):
    return (Resp(url=url, status=status, location=destino, blocos=()), None, status, None)


# ====================== redirecionamentos e robots.txt ======================
def test_redirecionamento_e_seguido_com_o_robots_de_cada_destino(robots, monkeypatch):
    rede = Rede(monkeypatch, {A: _redir(B), B: Resp(url=B)})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.sucesso and a.url_final == B and a.conteudo == b"conteudo"
    assert [p[0] for p in rede.pedidos] == [A, B]
    assert all(p[1]["allow_redirects"] is False and p[1]["ler_corpo_erro"] > 0 for p in rede.pedidos)   # quem segue e o fetcher
    e = a.chamada.extras
    assert e["redirecionamentos"] == [A, B] and e["robots_permitido"] is True and e["robots_salto_1_permitido"] is True
    assert e["robots_salto_1_status"] == 404


def test_destino_proibido_pelo_robots_nao_e_requisitado(robots, monkeypatch):
    robots["respostas"]["https://b.example/robots.txt"] = Robots("User-agent: *\nDisallow: /")
    rede = Rede(monkeypatch, {A: _redir(B), B: Resp(url=B, blocos=(b"SEGREDO",))})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.erro == f"bloqueado_por_robots_apos_redirecionamento: {B}" and not a.chamada.sucesso
    assert [p[0] for p in rede.pedidos] == [A]                                    # o GET no destino nem aconteceu
    assert a.conteudo == b"" and a.chamada.raw is None
    assert a.chamada.extras["robots_salto_1_permitido"] is False and a.chamada.extras["redirecionamentos"] == [A, B]


def test_location_relativo_e_resolvido_contra_a_url_atual(robots, monkeypatch):
    rede = Rede(monkeypatch, {A: _redir("/outra/pagina"), "https://a.gov.br/outra/pagina": Resp(url="https://a.gov.br/outra/pagina")})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.sucesso and [p[0] for p in rede.pedidos] == [A, "https://a.gov.br/outra/pagina"]


def test_redirecionamentos_demais_param_no_limite(robots, monkeypatch):
    rede = Rede(monkeypatch, {A: _redir(A)})                                       # A redireciona para si mesma
    a = FetcherRequests(UA, max_redirecionamentos=3).baixar(A)
    assert a.chamada.erro == "redirecionamentos_demais" and len(rede.pedidos) == 4 and a.conteudo == b""


def test_cada_resposta_de_redirecionamento_e_fechada(robots, monkeypatch):
    r1 = Resp(url=A, status=301, location=B, blocos=())
    Rede(monkeypatch, {A: (r1, None, 301, None), B: Resp(url=B)})
    FetcherRequests(UA).baixar(A)
    assert r1.closed


def test_3xx_sem_location_nao_e_redirecionamento(robots, monkeypatch):
    Rede(monkeypatch, {A: (Resp(url=A, status=304, blocos=(b"x",)), None, 304, None)})
    a = FetcherRequests(UA).baixar(A)
    assert a.http_status == 304 and a.chamada.sucesso and "redirecionamentos" not in a.chamada.extras


def test_sem_redirecionamento_nao_ha_lista_nos_extras(robots, monkeypatch):
    Rede(monkeypatch, {A: Resp()})
    assert "redirecionamentos" not in FetcherRequests(UA).baixar(A).chamada.extras


def test_robots_desligado_tambem_segue_redirecionamento_sem_consultar_robots(robots, monkeypatch):
    robots["respostas"]["https://b.example/robots.txt"] = Robots("User-agent: *\nDisallow: /")
    Rede(monkeypatch, {A: _redir(B), B: Resp(url=B)})
    a = FetcherRequests(UA, respeitar_robots=False).baixar(A)
    assert a.chamada.sucesso and a.url_final == B and "robots_permitido" not in a.chamada.extras


# ---------- politica para robots.txt inacessivel ----------
def test_robots_503_com_a_politica_padrao_permite(robots, monkeypatch):
    robots["respostas"]["https://a.gov.br/robots.txt"] = Robots("indisponivel", 503)
    Rede(monkeypatch, {A: Resp()})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.sucesso and a.chamada.extras["robots_status"] == 503 and a.chamada.extras["robots_permitido"] is True


def test_robots_503_com_a_politica_bloquear_proibe(robots, monkeypatch):
    robots["respostas"]["https://a.gov.br/robots.txt"] = Robots("indisponivel", 503)
    rede = Rede(monkeypatch, {A: Resp()})
    a = FetcherRequests(UA, robots_se_inacessivel="bloquear").baixar(A)
    assert a.chamada.erro == "bloqueado_por_robots" and rede.pedidos == [] and a.chamada.extras["robots_status"] == 503


def test_robots_ilegivel_por_erro_de_rede_com_bloquear_proibe(robots, monkeypatch):
    robots["respostas"]["https://a.gov.br/robots.txt"] = requests.ConnectionError("sem rede")
    rede = Rede(monkeypatch, {A: Resp()})
    assert FetcherRequests(UA, robots_se_inacessivel="bloquear").baixar(A).chamada.erro == "bloqueado_por_robots" and rede.pedidos == []


def test_robots_404_sempre_permite_mesmo_com_bloquear(robots, monkeypatch):
    Rede(monkeypatch, {A: Resp()})                                                 # padrao dos fakes: robots.txt 404
    assert FetcherRequests(UA, robots_se_inacessivel="bloquear").baixar(A).chamada.sucesso


def test_robots_200_normal_nao_muda_com_bloquear(robots, monkeypatch):
    robots["respostas"]["https://a.gov.br/robots.txt"] = Robots("User-agent: *\nDisallow: /privado")
    Rede(monkeypatch, {A: Resp(), "https://a.gov.br/privado/x": Resp()})
    f = FetcherRequests(UA, robots_se_inacessivel="bloquear")
    assert f.baixar(A).chamada.sucesso and f.baixar("https://a.gov.br/privado/x").chamada.erro == "bloqueado_por_robots"


def test_politica_de_robots_invalida_e_recusada():
    with pytest.raises(ValueError):
        FetcherRequests(UA, robots_se_inacessivel="talvez")


def test_a_politica_de_robots_esta_na_configuracao_e_no_hash():
    import config.settings as S
    assert S.OPCOES["requests"]["robots_se_inacessivel"] == "bloquear" and S.OPCOES["requests"]["tempo_maximo"] == 120
    antes = S.snapshot_config()["hash"]
    S.OPCOES["requests"]["robots_se_inacessivel"] = "permitir"
    try:
        assert S.snapshot_config()["hash"] != antes                                # a decisao fica registrada na execucao
    finally:
        S.OPCOES["requests"]["robots_se_inacessivel"] = "bloquear"


# ====================== prazo total e tempo de leitura ======================
@pytest.fixture
def relogio(monkeypatch):
    r = {"t": 0.0}
    monkeypatch.setattr(fetcher_requests.time, "perf_counter", lambda: r["t"])
    return r


def test_download_que_passa_do_prazo_total_e_abandonado(robots, monkeypatch, relogio):
    resp = Resp(blocos=(b"a", b"b", b"c"), avanco=6.0, relogio=relogio)
    Rede(monkeypatch, {A: resp})
    a = FetcherRequests(UA, tempo_maximo=10, respeitar_robots=False).baixar(A)
    assert a.chamada.erro == "tempo_excedido" and not a.chamada.sucesso and a.conteudo == b"" and a.chamada.raw is None
    assert resp.closed and a.chamada.extras["tempo_leitura_ms"] == 12000


def test_download_dentro_do_prazo_conclui(robots, monkeypatch, relogio):
    Rede(monkeypatch, {A: Resp(blocos=(b"a", b"b"), avanco=4.0, relogio=relogio)})
    assert FetcherRequests(UA, tempo_maximo=10, respeitar_robots=False).baixar(A).chamada.sucesso


def test_tempo_de_leitura_entra_na_latencia_total_mas_nao_na_latencia_da_resposta(robots, monkeypatch, relogio):
    Rede(monkeypatch, {A: Resp(blocos=(b"a", b"b"), avanco=0.5, relogio=relogio)})
    a = FetcherRequests(UA, respeitar_robots=False).baixar(A)
    assert a.chamada.latencia_ms == 10                                             # tempo ate os cabecalhos
    assert a.chamada.extras["tempo_leitura_ms"] == 1000 and a.chamada.extras["latencia_total_ms"] == 1010


def test_tempo_de_leitura_tambem_e_registrado_quando_a_leitura_falha(robots, monkeypatch, relogio):
    class Corta(Resp):
        def iter_content(self, n):
            relogio["t"] += 2.0
            yield b"parcial"
            raise requests.exceptions.ChunkedEncodingError("cortou")
    Rede(monkeypatch, {A: Corta()})
    a = FetcherRequests(UA, respeitar_robots=False).baixar(A)
    assert a.chamada.erro.startswith("erro_de_leitura") and a.chamada.extras["tempo_leitura_ms"] == 2000
    assert a.chamada.extras["latencia_total_ms"] == 2010


def test_latencia_total_soma_todos_os_saltos(robots, monkeypatch, relogio):
    Rede(monkeypatch, {A: _redir(B), B: Resp(url=B)})
    a = FetcherRequests(UA, respeitar_robots=False).baixar(A)
    assert a.chamada.extras["latencia_total_ms"] == 20 + a.chamada.extras["tempo_leitura_ms"]


# ====================== corpo da resposta de erro ======================
def test_corpo_de_uma_resposta_403_e_guardado(robots, monkeypatch):
    corpo = b"<html><title>Attention Required! | Cloudflare</title></html>"
    Rede(monkeypatch, {A: (Resp(url=A, status=403, ctype="text/html"), "HTTP 403", 403, corpo)})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.erro == "HTTP 403" and a.conteudo == b""
    assert (a.chamada.raw, a.chamada.raw_ext, a.chamada.extras["corpo_erro_bytes"]) == (corpo, "html", len(corpo))


def test_corpo_de_erro_que_nao_e_html_fica_como_bin(robots, monkeypatch):
    Rede(monkeypatch, {A: (Resp(url=A, status=403, ctype="application/octet-stream"), "HTTP 403", 403, b"\x00\x01")})
    assert FetcherRequests(UA).baixar(A).chamada.raw_ext == "bin"


def test_erro_sem_corpo_nao_grava_raw(robots, monkeypatch):
    Rede(monkeypatch, {A: (Resp(url=A, status=404), "HTTP 404", 404, b"")})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.raw is None and "corpo_erro_bytes" not in a.chamada.extras


def test_erro_de_rede_nao_tem_corpo(robots, monkeypatch):
    Rede(monkeypatch, {A: (None, "ConnectionError('x')", None, None)})
    assert FetcherRequests(UA).baixar(A).chamada.raw is None


def test_estagio_de_download_guarda_o_bruto_da_resposta_de_erro(tmp_path, robots, monkeypatch, silencio):
    corpo = b"<html>Acesso negado pelo WAF</html>"
    url = "https://exemplo.gov.br/pi/1"
    Rede(monkeypatch, {url: (Resp(url=url, status=403), "HTTP 403", 403, corpo)})
    repo, bruto = RepositorioSQLite(tmp_path / "d.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "baixar")
    busca_web.executar(repo, bruto, _Busca1(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherRequests(UA), ExtratorPadrao(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    c = repo.conn.execute("SELECT * FROM chamadas WHERE etapa='download'").fetchone()
    assert c["sucesso"] == 0 and c["raw_path"] and (tmp_path / "raw" / c["raw_path"]).read_bytes() == corpo
    assert repo.conn.execute("SELECT motivo FROM v_resultado_download").fetchone()[0] == "http_403"


class _Busca1(Busca4Urls):
    def buscar(self, consulta, filtros):
        resp = super().buscar(consulta, filtros)
        resp.resultados = resp.resultados[:1]
        return resp


# ====================== infra.http ======================
def test_chamar_repassa_allow_redirects(monkeypatch):
    visto = {}
    class Ok(Resp):
        ok = True
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: visto.update(k) or Ok(url=A))
    http.chamar("GET", A, allow_redirects=False)
    assert visto["allow_redirects"] is False
    http.chamar("GET", A)
    assert visto["allow_redirects"] is True


class _RespErro:
    def __init__(self, blocos, erro_na_leitura=None):
        self.status_code, self.ok, self.text, self.content = 403, False, "", b""
        self._blocos, self._erro, self.closed = blocos, erro_na_leitura, False

    def iter_content(self, n):
        yield from self._blocos
        if self._erro:
            raise self._erro

    def close(self):
        self.closed = True


def test_chamar_le_o_corpo_da_resposta_de_erro_ate_o_limite(monkeypatch):
    r = _RespErro([b"a" * 100, b"b" * 100, b"c" * 100])
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: r)
    res = http.chamar("GET", A, stream=True, ler_corpo_erro=150)
    assert res["erro"] == "HTTP 403" and res["corpo_erro"] == b"a" * 100 + b"b" * 50 and r.closed


def test_chamar_ignora_falha_ao_ler_o_corpo_do_erro(monkeypatch):
    r = _RespErro([b"parcial"], requests.exceptions.ChunkedEncodingError("cortou"))
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: r)
    res = http.chamar("GET", A, stream=True, ler_corpo_erro=100)
    assert res["erro"] == "HTTP 403" and res["corpo_erro"] == b"parcial" and r.closed


def test_chamar_sem_pedir_o_corpo_nao_o_le(monkeypatch):
    r = _RespErro([b"x"])
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: r)
    assert http.chamar("GET", A, stream=True)["corpo_erro"] is None


@pytest.mark.parametrize("nome", ["auth", "Credential", "X-Sig", "access_token", "cookie", "session_id", "passwd", "bearer"])
def test_mais_nomes_de_parametro_sao_tratados_como_segredo(nome):
    assert http.segredos_da_chamada({nome: "VALOR-SECRETO-1234"}, None) == {"VALOR-SECRETO-1234"}


# ====================== dominio final (apos redirecionamento) ======================
def _estagio_com_redirecionamento(tmp_path, monkeypatch):
    """/pi/1 (oficial) redireciona para um dominio nao oficial; /pi/2 a /pi/4 respondem direto."""
    corpo = _TEXTO.encode()
    u = {n: f"https://exemplo.gov.br/pi/{n}" for n in range(1, 5)}
    ext = "https://externo.example/materia"
    paginas = {u[1]: _redir(ext, url=u[1]), ext: Resp(blocos=(corpo,), url=ext)}
    paginas.update({u[n]: Resp(blocos=(corpo,), url=u[n]) for n in (2, 3, 4)})
    Rede(monkeypatch, paginas)
    repo, bruto = RepositorioSQLite(tmp_path / "f.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, Busca4Urls(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherRequests(UA, respeitar_robots=False), ExtratorSimulado(), run_id, run_id,
                      C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    return repo


def test_pagina_guarda_o_dominio_final_e_se_ele_e_oficial(tmp_path, monkeypatch, silencio):
    repo = _estagio_com_redirecionamento(tmp_path, monkeypatch)
    p = {r["url_id"]: dict(r) for r in repo.conn.execute("SELECT url_id, url_final, dominio_final, fonte_oficial_final FROM paginas")}
    assert (p[1]["dominio_final"], p[1]["fonte_oficial_final"]) == ("externo.example", 0)
    assert all((p[n]["dominio_final"], p[n]["fonte_oficial_final"]) == ("exemplo.gov.br", 1) for n in (2, 3, 4))


def test_resultado_de_download_aponta_o_redirecionamento_para_fora(tmp_path, monkeypatch, silencio):
    repo = _estagio_com_redirecionamento(tmp_path, monkeypatch)
    r = {x["url_id"]: dict(x) for x in repo.conn.execute("SELECT * FROM v_resultado_download")}
    assert (r[1]["fonte_oficial"], r[1]["fonte_oficial_final"], r[1]["redirecionou_de_dominio"], r[1]["dominio_final"]) == (1, 0, 1, "externo.example")
    assert all(r[n]["redirecionou_de_dominio"] == 0 for n in (2, 3, 4))
    e = {(x["resultado"], x["fonte_oficial"]): x["n_urls"] for x in repo.conn.execute("SELECT * FROM v_extracao")}
    assert e == {("ok", 1): 3, ("ok", 0): 1}                                        # a origem efetiva e a final


def test_achados_e_resumo_usam_a_origem_efetiva(tmp_path, monkeypatch, silencio):
    repo = _estagio_com_redirecionamento(tmp_path, monkeypatch)
    a = {x["url"].rsplit("/", 1)[1]: dict(x) for x in repo.conn.execute("SELECT * FROM v_achados_revisao")}
    assert (a["1"]["fonte_oficial"], a["1"]["fonte_oficial_final"], a["1"]["dominio_final"]) == (1, 0, "externo.example")
    assert a["2"]["fonte_oficial_final"] == 1
    uf = dict(repo.conn.execute("SELECT * FROM v_resumo_uf").fetchone())
    assert (uf["n_achados"], uf["n_fonte_oficial"]) == (4, 3)                       # o redirecionado nao conta como oficial
    prec = {x["fonte_oficial"]: x["n_achados"] for x in repo.conn.execute("SELECT * FROM v_precisao_llm")}
    assert prec == {0: 1, 1: 3}


def test_paginas_antigas_ganham_o_dominio_final_ao_abrir_o_banco(tmp_path):
    db = sqlite3.connect(tmp_path / "antigo.db")
    db.executescript("""CREATE TABLE paginas (pagina_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, url_id INTEGER NOT NULL,
        chamada_id INTEGER NOT NULL, url_final TEXT, http_status INTEGER, content_type TEXT, n_bytes INTEGER, truncado INTEGER,
        texto_path TEXT, n_chars INTEGER, extrator TEXT, extracao_ok INTEGER, motivo_falha TEXT);
        INSERT INTO paginas (run_id, url_id, chamada_id, url_final) VALUES ('r', 1, 1, 'https://www.ssp.pi.gov.br/a');
        INSERT INTO paginas (run_id, url_id, chamada_id, url_final) VALUES ('r', 2, 2, 'https://externo.example/b');""")
    db.commit()
    db.close()
    repo = RepositorioSQLite(tmp_path / "antigo.db")
    linhas = [tuple(r) for r in repo.conn.execute("SELECT dominio_final, fonte_oficial_final FROM paginas ORDER BY pagina_id")]
    assert linhas == [("ssp.pi.gov.br", 1), ("externo.example", 0)]


# ====================== execucoes fora do relatorio ======================
def _duas_execucoes_web(tmp_path):
    repo, run1 = construir_web(tmp_path)
    _, run2 = construir_web(tmp_path, repo=repo)
    return repo, run1, run2


def _val(repo, sql):
    return repo.conn.execute(sql).fetchone()[0]


def test_sem_excluir_as_views_agregadas_somam_as_duas_execucoes(tmp_path, silencio):
    repo, _, _ = _duas_execucoes_web(tmp_path)
    assert _val(repo, "SELECT requisicoes_busca_web FROM v_eficiencia") == 20
    assert _val(repo, "SELECT n_resultados FROM v_dominios WHERE dominio='exemplo.gov.br'") == 40


def test_execucao_fora_do_relatorio_sai_das_views_agregadas(tmp_path, silencio):
    repo, run1, run2 = _duas_execucoes_web(tmp_path)
    repo.definir_no_relatorio(run2, False, "piloto")
    assert _val(repo, "SELECT requisicoes_busca_web FROM v_eficiencia") == 10
    assert _val(repo, "SELECT custo_total_usd FROM v_eficiencia") == pytest.approx(0.05)
    assert _val(repo, "SELECT n_resultados FROM v_dominios WHERE dominio='exemplo.gov.br'") == 20
    assert _val(repo, "SELECT n_resultados FROM v_dominios WHERE dominio='blog.exemplo.com.br'") == 5
    p1 = dict(repo.conn.execute("SELECT * FROM v_rendimento_por_posicao WHERE posicao=1").fetchone())
    assert (p1["n_resultados"], p1["n_urls"], p1["n_confirmados"]) == (10, 2, 10)             # so a execucao 1: gov/1 e gov/3
    assert _val(repo, "SELECT n_achados FROM v_resumo_uf WHERE uf='PI'") == 4
    assert _val(repo, "SELECT COUNT(*) FROM v_status_url") == 4
    assert _val(repo, "SELECT SUM(n_achados) FROM v_precisao_llm") == 4
    assert _val(repo, "SELECT SUM(n_urls) FROM v_extracao") == 4
    assert _val(repo, "SELECT n_classificacoes FROM v_qualidade_classificacao WHERE origem_texto='pagina'") == 3


def test_views_por_execucao_e_logs_continuam_mostrando_a_execucao_fora(tmp_path, silencio):
    repo, run1, run2 = _duas_execucoes_web(tmp_path)
    repo.definir_no_relatorio(run2, False, "piloto")
    assert {r["run_id"] for r in repo.conn.execute("SELECT run_id FROM v_funil")} == {run1, run2}
    assert {r["run_id"] for r in repo.conn.execute("SELECT run_id FROM v_custos")} == {run1, run2}
    assert _val(repo, "SELECT COUNT(*) FROM v_achados_revisao") == 4                  # fila de revisao: so a execucao do relatorio
    assert {r[0] for r in repo.conn.execute("SELECT run_id FROM v_achados_revisao")} == {run1}
    assert _val(repo, "SELECT COUNT(*) FROM v_resultado_download WHERE no_relatorio=0") == 4


def test_gasto_real_soma_todas_as_execucoes_e_aponta_custo_nao_gravado(tmp_path):
    repo = RepositorioSQLite(tmp_path / "g.db")
    antiga, nova = _novo_run(repo, "busca-web"), _novo_run(repo, "busca-web")
    for run, custo, n in ((antiga, None, 5), (nova, 0.005, 5)):
        for i in range(n):
            reg = RegistroChamada(provedor="perplexity_search", operacao="buscar", parametros={}, requisitado_em="2026-10-14T10:00:00+00:00",
                                  http_status=200, latencia_ms=1, tentativas=1, custo_usd=custo)
            repo.salvar_chamada(run_id=run, etapa="busca_web", alvo_tipo="consulta_web", alvo_id=f"c{i}", chave=f"{run}-{i}",
                                registro=reg, raw_path=None, raw_sha256=None)
    repo.confirmar()
    repo.definir_no_relatorio(antiga, False, "codigo antigo, sem custo gravado")
    g = {r["no_relatorio"]: dict(r) for r in repo.conn.execute("SELECT * FROM v_gasto_real")}
    assert (g[1]["n_chamadas"], g[1]["custo_registrado_usd"], g[1]["n_ok_sem_custo"]) == (5, 0.025, 0)
    assert (g[0]["n_chamadas"], g[0]["custo_registrado_usd"], g[0]["n_ok_sem_custo"]) == (5, 0.0, 5)   # o gasto real foi maior
    assert _val(repo, "SELECT requisicoes_busca_web FROM v_eficiencia") == 5 and _val(repo, "SELECT custo_total_usd FROM v_eficiencia") == 0.025


def test_incluir_de_volta_restaura_as_views(tmp_path, silencio):
    repo, run1, run2 = _duas_execucoes_web(tmp_path)
    repo.definir_no_relatorio(run2, False, "piloto")
    repo.definir_no_relatorio(run2, True)
    assert _val(repo, "SELECT requisicoes_busca_web FROM v_eficiencia") == 20
    linha = repo.conn.execute("SELECT no_relatorio, motivo_exclusao, excluida_em FROM execucoes WHERE run_id=?", (run2,)).fetchone()
    assert tuple(linha) == (1, None, None)


def test_exclusao_guarda_motivo_e_data_utc(tmp_path, silencio):
    repo, _, run2 = _duas_execucoes_web(tmp_path)
    repo.definir_no_relatorio(run2, False, "piloto com --limite")
    m, quando = repo.conn.execute("SELECT motivo_exclusao, excluida_em FROM execucoes WHERE run_id=?", (run2,)).fetchone()
    assert m == "piloto com --limite" and quando.endswith("+00:00")


def test_definir_no_relatorio_de_execucao_inexistente_encerra(tmp_path):
    with pytest.raises(SystemExit) as e:
        RepositorioSQLite(tmp_path / "x.db").definir_no_relatorio("nao_existe", False)
    assert "nao_existe" in str(e.value)


def test_academico_artigo_so_de_execucao_fora_nao_conta(tmp_path):
    repo, run1 = construir_academico(tmp_path / "ac.db")
    run2 = _novo_run(repo, "academico")
    _chamada_academica(repo, run2, "T01", 1, [1, 2, 99], 1500)                     # A99 so aparece nesta execucao
    assert _val(repo, "SELECT COUNT(*) FROM v_artigos_por_ano") >= 1
    assert _val(repo, "SELECT SUM(n_artigos) FROM v_artigos_por_ano") == 13
    repo.definir_no_relatorio(run2, False, "piloto")
    assert _val(repo, "SELECT SUM(n_artigos) FROM v_artigos_por_ano") == 12
    v = {r["metrica"]: r["valor"] for r in repo.conn.execute("SELECT * FROM v_prisma")}
    assert v["Google Scholar: registros retornados"] == 16 and v["Google Scholar: artigos unicos"] == 12
    assert v["artigos unicos para triagem"] == 12 and v["execucoes de busca academica"] == 1
    assert _val(repo, "SELECT n_artigos FROM v_rendimento_termo WHERE termo_id='T01'") == 8
    assert _val(repo, "SELECT COUNT(*) FROM v_curva_descoberta") == 5
    assert _val(repo, "SELECT COUNT(*) FROM v_registro_buscas") == 8                 # o registro de buscas mostra tudo, com a marca
    assert {r[0] for r in repo.conn.execute("SELECT no_relatorio FROM v_registro_buscas")} == {0, 1}


def test_academico_manual_sempre_conta(tmp_path):
    import pandas as pd
    repo, run1 = construir_academico(tmp_path / "ac.db")
    repo.definir_no_relatorio(run1, False, "tudo fora")
    repo.importar_artigos_manuais(pd.DataFrame([{"base": "IEEE", "termo_id": "T01", "titulo": "Artigo manual", "data_busca": "2026-10-15"}]))
    assert _val(repo, "SELECT COUNT(*) FROM r_artigos") == 1                          # so o manual: os do Scholar vinham da execucao fora


def test_banco_antigo_recebe_no_relatorio_igual_a_1(tmp_path):
    db = sqlite3.connect(tmp_path / "antigo.db")
    db.executescript("""CREATE TABLE execucoes (run_id TEXT PRIMARY KEY, iniciado_em TEXT NOT NULL, finalizado_em TEXT, comando TEXT,
        config_hash TEXT NOT NULL, config_json TEXT NOT NULL, commit_git TEXT, status TEXT NOT NULL DEFAULT 'em_andamento',
        metricas_json TEXT, run_origem TEXT);
        INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json) VALUES ('r1', 'x', 'h', '{}');""")
    db.commit()
    db.close()
    repo = RepositorioSQLite(tmp_path / "antigo.db")
    assert tuple(repo.conn.execute("SELECT no_relatorio, motivo_exclusao FROM execucoes").fetchone()) == (1, None)


def test_cli_excluir_e_incluir_execucao(ambiente_cli, monkeypatch, capsys, silencio):
    monkeypatch.setattr(sys, "argv", ["main.py", "busca-web", "--simulado", "--ufs", "PI", "--limite", "2"])
    main.main()
    db = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    run_id = db.execute("SELECT run_id FROM execucoes").fetchone()[0]
    assert db.execute("SELECT requisicoes_busca_web FROM v_eficiencia").fetchone()[0] == 2
    monkeypatch.setattr(sys, "argv", ["main.py", "execucao-excluir", run_id, "--motivo", "teste do comando", "--simulado"])
    main.main()
    assert "fora do relatório" in capsys.readouterr().out
    assert db.execute("SELECT no_relatorio, motivo_exclusao FROM execucoes").fetchone()[:] == (0, "teste do comando")
    assert db.execute("SELECT requisicoes_busca_web FROM v_eficiencia").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM chamadas").fetchone()[0] == 2                 # nada foi apagado
    monkeypatch.setattr(sys, "argv", ["main.py", "execucao-incluir", run_id, "--simulado"])
    main.main()
    assert "dentro do relatório" in capsys.readouterr().out
    assert db.execute("SELECT requisicoes_busca_web FROM v_eficiencia").fetchone()[0] == 2


def test_cli_excluir_execucao_inexistente_encerra(ambiente_cli, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "execucao-excluir", "nao_existe", "--simulado"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert "nao_existe" in str(e.value)


def test_abas_novas_da_exportacao(tmp_path):
    repo, _ = construir_academico(tmp_path / "ac.db")
    t = repo.tabelas_para_exportacao()
    assert "Gasto_real" in t and {"no_relatorio", "motivo_exclusao", "excluida_em"} <= set(t["Execucoes"].columns)
    assert all(len(n) <= 31 for n in t)


def test_a_fabrica_monta_o_fetcher_com_a_politica_de_robots_da_configuracao(monkeypatch):
    from composicao import Fabrica
    monkeypatch.setenv("RESEARCHER_EMAIL", "pesquisador@exemplo.org")
    assert Fabrica().fetcher._politica == "bloquear"


# ====================== prazo total: leitura bloqueada e gotejamento ======================
class Bloqueia(Resp):
    """Corpo que bloqueia na leitura ate a resposta ser fechada (como um servidor que nao manda mais nada)."""
    def __init__(self):
        super().__init__(blocos=())
        self._evento = threading.Event()

    def iter_content(self, tamanho):
        self._evento.wait(10)
        yield from ()

    def close(self):
        self.closed = True
        self._evento.set()


def test_leitura_bloqueada_e_interrompida_pelo_temporizador_no_prazo(robots, monkeypatch):
    resp = Bloqueia()
    Rede(monkeypatch, {A: resp})
    t0 = time.perf_counter()
    a = FetcherRequests(UA, tempo_maximo=0.3, respeitar_robots=False).baixar(A)
    assert a.chamada.erro == "tempo_excedido" and not a.chamada.sucesso and a.conteudo == b"" and a.chamada.raw is None
    assert time.perf_counter() - t0 < 3 and resp.closed                          # sem o temporizador seriam 10 s


def test_abortar_nao_levanta_com_resposta_sem_os_atributos_internos():
    evento = threading.Event()
    fetcher_requests._abortar(object(), evento)
    assert evento.is_set()


def test_temporizador_e_cancelado_quando_o_download_termina(robots, monkeypatch):
    criados = []

    class TimerRastreado(threading.Timer):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            criados.append(self)

    monkeypatch.setattr(fetcher_requests.threading, "Timer", TimerRastreado)
    Rede(monkeypatch, {A: Resp()})
    for _ in range(5):
        assert FetcherRequests(UA, tempo_maximo=60, respeitar_robots=False).baixar(A).chamada.sucesso
    assert len(criados) == 5 and all(tm.finished.is_set() for tm in criados)     # cancelar marca o temporizador como encerrado


def test_temporizador_tambem_e_cancelado_quando_a_leitura_falha(robots, monkeypatch):
    criados = []

    class TimerRastreado(threading.Timer):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            criados.append(self)

    class Corta(Resp):
        def iter_content(self, n):
            raise requests.exceptions.ChunkedEncodingError("cortou")
            yield b""

    monkeypatch.setattr(fetcher_requests.threading, "Timer", TimerRastreado)
    Rede(monkeypatch, {A: Corta()})
    assert FetcherRequests(UA, tempo_maximo=60, respeitar_robots=False).baixar(A).chamada.erro.startswith("erro_de_leitura")
    assert len(criados) == 1 and criados[0].finished.is_set()


def test_prazo_total_e_conferido_antes_de_cada_salto(robots, monkeypatch, relogio):
    rede = Rede(monkeypatch, {A: _redir(B), B: Resp(url=B)}, relogio=relogio, avanco=100.0)
    a = FetcherRequests(UA, tempo_maximo=60, respeitar_robots=False).baixar(A)
    assert a.chamada.erro == "tempo_excedido" and [p[0] for p in rede.pedidos] == [A]      # o segundo salto nem comecou
    assert a.chamada.extras["redirecionamentos"] == [A, B]


def test_timeout_de_rede_nunca_passa_do_prazo_restante(robots, monkeypatch, relogio):
    rede = Rede(monkeypatch, {A: Resp()})
    FetcherRequests(UA, timeout=30, tempo_maximo=10, respeitar_robots=False).baixar(A)
    assert rede.pedidos[0][1]["timeout"] == 10
    rede2 = Rede(monkeypatch, {A: Resp()})
    FetcherRequests(UA, timeout=5, tempo_maximo=120, respeitar_robots=False).baixar(A)
    assert rede2.pedidos[0][1]["timeout"] == 5


def test_gotejamento_em_servidor_local_respeita_o_prazo_total():
    """Regressao com socket real (so loopback): 1 byte a cada 0,2 s, 40 bytes, prazo de 1 s. Antes da correcao a leitura
    so conferia o prazo a cada 64 KB e levava ate o fim da resposta."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "40")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        t0 = time.perf_counter()
        a = FetcherRequests(UA, timeout=5, tempo_maximo=1.0, respeitar_robots=False).baixar(f"http://127.0.0.1:{servidor.server_address[1]}/lento")
        duracao = time.perf_counter() - t0
    finally:
        servidor.shutdown()
        servidor.server_close()
    assert a.chamada.erro == "tempo_excedido" and a.conteudo == b"" and not a.chamada.sucesso
    assert duracao < 3.0                                                         # o servidor levaria 8 s
