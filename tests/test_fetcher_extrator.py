"""M4: download e extracao. Nenhum teste abre conexao: `requests.get` e `chamar` sao substituidos."""
import logging

import pytest
import requests

from adaptadores import fetcher_requests
from adaptadores.bruto_local import BrutoLocal
from adaptadores.extrator_padrao import ExtratorPadrao
from adaptadores.fetcher_requests import FetcherRequests
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_web, download
from config import consultas as C
from dados_metricas import Busca4Urls, _consulta_pi, _novo_run

UA = "AcademicResearch-AIPublicSecurity/1.0 (contact: teste@exemplo.org)"


# ====================== extrator ======================
HTML = ("<html><head><title>Videomonitoramento em Teresina</title></head><body><nav>Menu Inicio Contato</nav><article>"
        "<h1>Secretaria amplia videomonitoramento inteligente</h1>"
        "<p>A Secretaria de Seguranca Publica do Piaui ampliou o sistema de videomonitoramento inteligente com cameras "
        "capazes de ler placas de veiculos e reconhecer rostos em tempo real, conforme o edital publicado neste ano.</p>"
        "<p>O contrato preve a instalacao de quinhentas cameras em Teresina e em outras cidades do estado, com "
        "treinamento das equipes e atendimento as exigencias da LGPD sobre protecao de dados pessoais.</p>"
        "</article><footer>Todos os direitos reservados</footer></body></html>").encode()


def _pdf_com_texto(texto):
    """PDF minimo, valido, com uma pagina e o texto dado (so ASCII, sem parenteses)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    saida, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(saida))
        saida += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    saida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    saida += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return saida


TEXTO_PDF = "Contrato de videomonitoramento inteligente com reconhecimento facial em Teresina " * 3


def test_html_com_texto_suficiente():
    t = ExtratorPadrao().extrair(HTML, "text/html", "https://x.gov.br/a")
    assert t.ok and t.extrator == "trafilatura" and t.motivo_falha is None
    assert "videomonitoramento" in t.texto and len(t.texto) >= 200
    assert "Menu Inicio" not in t.texto                                  # o boilerplate sai


def test_html_sem_tipo_e_tratado_como_html():
    assert ExtratorPadrao().extrair(HTML, "", "https://x.gov.br/a").ok


def test_html_com_texto_curto_e_texto_insuficiente():
    t = ExtratorPadrao().extrair(b"<html><body><p>Pagina quase vazia.</p></body></html>", "text/html", "https://x")
    assert not t.ok and t.motivo_falha == "texto_insuficiente" and t.extrator == "trafilatura"


def test_html_vazio_e_texto_insuficiente():
    t = ExtratorPadrao().extrair(b"", "text/html", "https://x")
    assert (t.ok, t.motivo_falha, t.texto) == (False, "texto_insuficiente", "")


def test_min_chars_e_configuravel():
    assert ExtratorPadrao(min_chars=20).extrair(b"<html><body><article><p>Texto com mais de vinte caracteres.</p></article></body></html>",
                                               "text/html", "https://x").ok


def test_pdf_valido_com_texto():
    t = ExtratorPadrao().extrair(_pdf_com_texto(TEXTO_PDF), "application/pdf", "https://x/a.pdf")
    assert t.ok and t.extrator == "pypdf" and "videomonitoramento" in t.texto


def test_pdf_com_texto_curto_e_texto_insuficiente():
    t = ExtratorPadrao().extrair(_pdf_com_texto("Pagina curta"), "application/pdf", "https://x/a.pdf")
    assert not t.ok and t.motivo_falha == "texto_insuficiente" and t.texto == "Pagina curta"


def test_pdf_invalido_vira_erro_registrado_e_nao_levanta():
    t = ExtratorPadrao().extrair(b"%PDF-1.4 isto nao e um pdf de verdade", "application/pdf", "https://x/a.pdf")
    assert not t.ok and t.extrator == "pypdf" and t.motivo_falha.startswith("erro:")


@pytest.mark.parametrize("tipo", ["application/octet-stream", "", "binary/octet-stream"])
def test_pdf_servido_com_tipo_generico_e_reconhecido_pelo_cabecalho(tipo):
    t = ExtratorPadrao().extrair(_pdf_com_texto(TEXTO_PDF), tipo, "https://x/download?id=7")
    assert t.ok and t.extrator == "pypdf"


def test_cabecalho_pdf_invalido_sob_tipo_generico_tambem_e_tratado_como_pdf():
    t = ExtratorPadrao().extrair(b"%PDF- lixo", "application/octet-stream", "https://x/download")
    assert not t.ok and t.extrator == "pypdf" and t.motivo_falha.startswith("erro:")


def test_pdf_reconhecido_pela_extensao_da_url():
    t = ExtratorPadrao().extrair(b"nao e pdf", "", "https://x/doc.PDF?v=2")
    assert t.extrator == "pypdf" and not t.ok


@pytest.mark.parametrize("tipo", ["application/zip", "image/png", "application/json"])
def test_tipo_nao_suportado(tipo):
    t = ExtratorPadrao().extrair(b"PK\x03\x04", tipo, "https://x/a")
    assert (t.ok, t.extrator, t.motivo_falha) == (False, "nenhum", f"tipo_nao_suportado:{tipo}")


# ====================== fetcher ======================
class _Robots:
    def __init__(self, texto=None, status=200):
        self.text, self.status_code, self.ok = texto or "", status, status < 400


@pytest.fixture
def robots(monkeypatch):
    """Substitui requests.get (so usado para o robots.txt); `chamadas` guarda o que foi pedido."""
    estado = {"respostas": {}, "chamadas": [], "padrao": _Robots("", 404)}

    def falso(url, **kw):
        estado["chamadas"].append((url, kw))
        r = estado["respostas"].get(url, estado["padrao"])
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(fetcher_requests.requests, "get", falso)
    return estado


class _Resp:
    def __init__(self, blocos=(b"conteudo",), ctype="text/html; charset=utf-8", url="https://x.gov.br/a", status=200, erro_leitura=None):
        self.headers, self.url, self.status_code = ({"Content-Type": ctype} if ctype is not None else {}), url, status
        self._blocos, self._erro, self.closed = list(blocos), erro_leitura, False

    def iter_content(self, tamanho):
        yield from self._blocos
        if self._erro:
            raise self._erro

    def close(self):
        self.closed = True


def _chamar(monkeypatch, resp=None, erro=None, http_status=200, tentativas=1):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": resp, "http_status": http_status, "latencia_ms": 7, "tentativas": tentativas, "erro": erro,
                "latencia_total_ms": 9, "historico": [{"tentativa": 1, "http_status": http_status, "latencia_ms": 7, "erro": erro, "espera_s": None}]}

    monkeypatch.setattr(fetcher_requests, "chamar", falso)
    return visto


def test_robots_bloqueia_e_a_pagina_nem_e_requisitada(robots, monkeypatch):
    robots["respostas"]["https://x.gov.br/robots.txt"] = _Robots("User-agent: *\nDisallow: /privado")
    visto = _chamar(monkeypatch, _Resp())
    a = FetcherRequests(UA).baixar("https://x.gov.br/privado/doc")
    assert a.chamada.erro == "bloqueado_por_robots" and not a.chamada.sucesso
    assert (a.conteudo, a.http_status, a.truncado) == (b"", None, False) and visto == {}
    assert a.chamada.extras == {"robots_permitido": False, "robots_status": 200}


def test_robots_permite_outros_caminhos_e_consulta_uma_vez_por_host(robots, monkeypatch):
    robots["respostas"]["https://x.gov.br/robots.txt"] = _Robots("User-agent: *\nDisallow: /privado")
    _chamar(monkeypatch, _Resp())
    f = FetcherRequests(UA)
    assert f.baixar("https://x.gov.br/publico/a").chamada.sucesso and f.baixar("https://x.gov.br/publico/b").chamada.sucesso
    assert [c[0] for c in robots["chamadas"]] == ["https://x.gov.br/robots.txt"]                  # cache por host
    f.baixar("https://y.gov.br/a")
    assert [c[0] for c in robots["chamadas"]][-1] == "https://y.gov.br/robots.txt" and len(robots["chamadas"]) == 2
    assert robots["chamadas"][0][1]["headers"] == {"User-Agent": UA} and robots["chamadas"][0][1]["timeout"] == 10


def test_robots_ausente_ou_inacessivel_permite(robots, monkeypatch):
    _chamar(monkeypatch, _Resp())
    a = FetcherRequests(UA).baixar("https://x.gov.br/a")                                          # robots.txt 404
    assert a.chamada.sucesso and a.chamada.extras["robots_permitido"] is True and a.chamada.extras["robots_status"] == 404
    robots["respostas"]["https://z.gov.br/robots.txt"] = requests.ConnectionError("sem rede")
    b = FetcherRequests(UA).baixar("https://z.gov.br/a")
    assert b.chamada.sucesso and b.chamada.extras["robots_permitido"] is True and b.chamada.extras["robots_status"] is None


def test_sem_respeitar_robots_nao_consulta_o_robots(robots, monkeypatch):
    _chamar(monkeypatch, _Resp())
    a = FetcherRequests(UA, respeitar_robots=False).baixar("https://x.gov.br/privado")
    assert a.chamada.sucesso and robots["chamadas"] == [] and "robots_permitido" not in a.chamada.extras


def test_download_com_sucesso_preenche_o_arquivo_e_o_registro(robots, monkeypatch):
    visto = _chamar(monkeypatch, _Resp([b"<html>", b"corpo</html>"], url="https://x.gov.br/final"))
    a = FetcherRequests(UA, timeout=12).baixar("https://x.gov.br/a")
    assert (a.url_final, a.http_status, a.content_type, a.conteudo, a.truncado) == ("https://x.gov.br/final", 200, "text/html", b"<html>corpo</html>", False)
    c = a.chamada
    assert c.sucesso and c.provedor == "requests" and c.operacao == "baixar" and c.parametros == {"url": "https://x.gov.br/a"}
    assert (c.http_status, c.latencia_ms, c.tentativas, c.raw_ext, c.raw) == (200, 7, 1, "html", b"<html>corpo</html>")
    assert c.extras["content_type"] == "text/html" and c.extras["n_bytes"] == 18 and c.extras["truncado"] is False
    assert c.extras["latencia_total_ms"] == 9 and len(c.extras["historico"]) == 1
    assert visto["headers"] == {"User-Agent": UA} and visto["timeout"] == 12 and visto["stream"] is True and visto["metodo"] == "GET"


def test_resposta_e_sempre_fechada(robots, monkeypatch):
    r = _Resp()
    _chamar(monkeypatch, r)
    FetcherRequests(UA).baixar("https://x.gov.br/a")
    assert r.closed


@pytest.mark.parametrize("tipo, ext", [("application/pdf", "pdf"), ("application/octet-stream", "bin"),
                                       ("text/html; charset=iso-8859-1", "html"), (None, "bin")])
def test_extensao_do_bruto_segue_o_tipo(robots, monkeypatch, tipo, ext):
    _chamar(monkeypatch, _Resp(ctype=tipo))
    a = FetcherRequests(UA).baixar("https://x.gov.br/a")
    assert a.chamada.raw_ext == ext and a.content_type == ((tipo or "").split(";")[0].strip().lower())


def test_arquivo_maior_que_o_limite_e_truncado(robots, monkeypatch):
    r = _Resp([b"a" * 8, b"b" * 8, b"c" * 8])
    _chamar(monkeypatch, r)
    a = FetcherRequests(UA, max_bytes=10).baixar("https://x.gov.br/a")
    assert a.truncado and a.chamada.extras["truncado"] is True and len(a.conteudo) == 16 and r.closed   # para ao passar do limite


def test_erro_http_devolve_arquivo_vazio_com_o_erro(robots, monkeypatch):
    _chamar(monkeypatch, _Resp(status=404), erro="HTTP 404", http_status=404, tentativas=1)
    a = FetcherRequests(UA).baixar("https://x.gov.br/a")
    assert a.conteudo == b"" and not a.chamada.sucesso and a.chamada.erro == "HTTP 404" and a.chamada.http_status == 404
    assert a.chamada.raw is None and a.chamada.extras["historico"]


def test_falha_de_rede_sem_resposta(robots, monkeypatch):
    _chamar(monkeypatch, None, erro="ConnectionError('x')", http_status=None, tentativas=4)
    a = FetcherRequests(UA).baixar("https://x.gov.br/a")
    assert not a.chamada.sucesso and a.chamada.tentativas == 4 and a.conteudo == b""


def test_falha_durante_a_leitura_do_corpo_nao_levanta(robots, monkeypatch):
    r = _Resp([b"parcial"], erro_leitura=requests.exceptions.ChunkedEncodingError("conexao cortada"))
    _chamar(monkeypatch, r)
    a = FetcherRequests(UA).baixar("https://x.gov.br/a")
    assert not a.chamada.sucesso and a.chamada.erro.startswith("erro_de_leitura: ChunkedEncodingError")
    assert a.conteudo == b"" and a.chamada.raw is None and r.closed


def test_timeout_na_leitura_tambem_e_tratado(robots, monkeypatch):
    _chamar(monkeypatch, _Resp(erro_leitura=requests.exceptions.ReadTimeout("lento")))
    assert FetcherRequests(UA).baixar("https://x.gov.br/a").chamada.erro.startswith("erro_de_leitura: ReadTimeout")


# ====================== composicao e estagio de download ======================
def test_fabrica_monta_o_fetcher_real_com_o_email_do_ambiente(monkeypatch):
    from composicao import Fabrica
    monkeypatch.setenv("RESEARCHER_EMAIL", "pesquisador@exemplo.org")
    f = Fabrica().fetcher
    assert isinstance(f, FetcherRequests) and "contact: pesquisador@exemplo.org" in f._ua
    assert (f._timeout, f._max, f._robots_on) == (30, 8_000_000, True)
    assert isinstance(Fabrica().extrator, ExtratorPadrao) and Fabrica().extrator._min == 200


def test_fabrica_sem_email_nao_cria_o_fetcher_real():
    from composicao import Fabrica
    with pytest.raises(SystemExit) as e:
        Fabrica().fetcher
    assert "RESEARCHER_EMAIL" in str(e.value)


def _pagina(url, tipo, corpo, status=200, **kw):
    return _Resp([corpo], ctype=tipo, url=url, status=status, **kw)


@pytest.fixture
def estagio(tmp_path, robots, monkeypatch):
    """Estagio de download com o fetcher e o extrator reais e a rede simulada: /pi/1 ok, /pi/2 404, /pi/3 conexao
    cortada na leitura, /pi/4 PDF invalido sob tipo generico."""
    logging.disable(logging.CRITICAL)
    respostas = {
        "https://exemplo.gov.br/pi/1": lambda: (_pagina("https://exemplo.gov.br/pi/1", "text/html", HTML), None, 200),
        "https://exemplo.gov.br/pi/2": lambda: (_pagina("https://exemplo.gov.br/pi/2", "text/html", b"", 404), "HTTP 404", 404),
        "https://exemplo.gov.br/pi/3": lambda: (_pagina("https://exemplo.gov.br/pi/3", "text/html", b"x",
                                                         erro_leitura=requests.exceptions.ChunkedEncodingError("cortou")), None, 200),
        "https://exemplo.gov.br/pi/4": lambda: (_pagina("https://exemplo.gov.br/pi/4", "application/octet-stream", b"%PDF-1.4 invalido"), None, 200),
    }

    def falso(metodo, url, **kw):
        resp, erro, status = respostas[url]()
        return {"resp": resp, "http_status": status, "latencia_ms": 5, "tentativas": 1, "erro": erro,
                "latencia_total_ms": 5, "historico": []}

    monkeypatch.setattr(fetcher_requests, "chamar", falso)
    repo, bruto = RepositorioSQLite(tmp_path / "e.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "baixar")
    busca_web.executar(repo, bruto, Busca4Urls(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherRequests(UA), ExtratorPadrao(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    yield repo, run_id, tmp_path
    logging.disable(logging.NOTSET)


def test_estagio_com_adaptadores_reais_registra_o_destino_de_cada_url(estagio):
    repo, run_id, _ = estagio
    r = {l["url_id"]: dict(l) for l in repo.conn.execute("SELECT * FROM v_resultado_download")}
    destino = sorted((x["resultado"], x["motivo"].split(":")[0]) for x in r.values())
    assert destino == [("falha_download", "erro_de_leitura"), ("falha_download", "http_404"),
                       ("falha_extracao", "erro"), ("ok", "ok")]
    pdf = next(x for x in r.values() if x["resultado"] == "falha_extracao")
    assert "(" not in pdf["motivo"] and pdf["motivo"].startswith("erro:") and pdf["content_type"] == "application/octet-stream"


def test_estagio_grava_pagina_so_para_os_downloads_bem_sucedidos(estagio):
    repo, run_id, tmp_path = estagio
    paginas = repo.conn.execute("SELECT * FROM paginas").fetchall()
    assert len(paginas) == 2                                              # o HTML e o PDF invalido; 404 e leitura cortada nao
    ok = next(p for p in paginas if p["extracao_ok"] == 1)
    assert (ok["content_type"], ok["extrator"], ok["motivo_falha"]) == ("text/html", "trafilatura", None) and ok["n_chars"] >= 200
    assert (tmp_path / "raw" / ok["texto_path"]).read_text(encoding="utf-8").count("videomonitoramento") >= 1
    falha = next(p for p in paginas if p["extracao_ok"] == 0)
    assert falha["extrator"] == "pypdf" and falha["motivo_falha"].startswith("erro:") and falha["texto_path"] is None


def test_estagio_guarda_o_bruto_extras_e_a_resposta_de_robots(estagio):
    repo, run_id, tmp_path = estagio
    c = {l["alvo_id"]: l for l in repo.conn.execute("SELECT * FROM chamadas WHERE etapa='download'")}
    assert len(c) == 4 and sum(l["sucesso"] for l in c.values()) == 2
    import json
    ok = next(l for l in c.values() if l["sucesso"] and "html" in l["raw_path"])
    extras = json.loads(ok["extras_json"])
    assert extras["content_type"] == "text/html" and extras["robots_permitido"] is True and "historico" in extras
    assert (tmp_path / "raw" / ok["raw_path"]).read_bytes() == HTML
    falha404 = next(l for l in c.values() if l["erro"] == "HTTP 404")
    assert falha404["http_status"] == 404 and falha404["raw_path"] is None


def test_estagio_extracao_agrupada_por_classe_de_erro(estagio):
    repo, _, _ = estagio
    e = {(l["resultado"], l["motivo"]): l["n_urls"] for l in repo.conn.execute("SELECT * FROM v_extracao")}
    assert e[("ok", "ok")] == 1 and e[("falha_download", "http_404")] == 1 and e[("falha_download", "erro_de_leitura")] == 1
    assert sum(1 for k in e if k[0] == "falha_extracao") == 1 and all("(" not in k[1] for k in e)
