"""robots.txt: retentativas na leitura, validade curta de uma falha e a separacao entre proibicao do site e robots.txt inacessivel.
Nenhum teste usa a rede nem espera de verdade: `requests.get`, `chamar`, o relogio e a pausa sao trocados."""
import pytest
import requests

from adaptadores import fetcher_requests
from adaptadores.fetcher_requests import FetcherRequests, ROBOTS_ESPERAS_S, ROBOTS_TENTATIVAS, ROBOTS_TTL_FALHA_S

UA = "AcademicResearch-AIPublicSecurity/1.0 (contact: teste@exemplo.org)"
URL = "https://a.gov.br/pagina"
ROBOTS = "https://a.gov.br/robots.txt"
OUTRA = "https://b.example/final"


class R:
    def __init__(self, texto="", status=200):
        self.text, self.status_code, self.ok = texto, status, status < 400


class Pagina:
    def __init__(self, url=URL):
        self.headers, self.url, self.status_code, self.closed = {"Content-Type": "text/html"}, url, 200, False

    def iter_content(self, tamanho):
        yield b"conteudo"

    def close(self):
        self.closed = True


class Mundo:
    """Rede falsa: `roteiro[url]` e uma lista de respostas do robots.txt consumidas em ordem (a ultima se repete);
    uma excecao na lista e levantada. `lidas` conta as leituras por URL; o relogio so avanca por `avancar`."""

    def __init__(self, monkeypatch):
        self.roteiro, self.lidas, self.esperas, self.t, self.paginas = {}, [], [], 1000.0, []
        monkeypatch.setattr(fetcher_requests.requests, "get", self._get)
        monkeypatch.setattr(fetcher_requests, "chamar", self._chamar)

    def _get(self, url, **kw):
        self.lidas.append(url)
        fila = self.roteiro.get(url, [R("", 404)])
        r = fila.pop(0) if len(fila) > 1 else fila[0]
        if isinstance(r, Exception):
            raise r
        return r

    def _chamar(self, metodo, url, **kw):
        self.paginas.append(url)
        return {"resp": Pagina(url), "http_status": 200, "latencia_ms": 3, "tentativas": 1, "erro": None, "latencia_total_ms": 3,
                "historico": []}

    def fetcher(self, **kw):
        return FetcherRequests(UA, relogio=lambda: self.t, dormir=self.esperas.append, **kw)

    def avancar(self, s):
        self.t += s


@pytest.fixture
def mundo(monkeypatch):
    return Mundo(monkeypatch)


def test_as_constantes_ficam_no_adaptador_e_nao_na_configuracao():
    import config.settings as S
    assert (ROBOTS_TENTATIVAS, ROBOTS_ESPERAS_S, ROBOTS_TTL_FALHA_S) == (3, (1.0, 2.0), 300)
    assert not [k for k in S.OPCOES["requests"] if k.startswith("robots_") and k != "robots_se_inacessivel"]
    assert "ttl" not in S.snapshot_config()["json"].lower()                      # o hash da configuracao nao muda por causa delas


def test_200_permite_e_proibe_com_extras(mundo):
    mundo.roteiro[ROBOTS] = [R("User-agent: *\nDisallow: /privado")]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    ok = f.baixar(URL)
    assert ok.chamada.sucesso and ok.chamada.extras["robots_permitido"] is True
    assert (ok.chamada.extras["robots_status"], ok.chamada.extras["robots_inacessivel"], ok.chamada.extras["robots_tentativas"]) == (200, False, 1)
    proibido = f.baixar("https://a.gov.br/privado/x")
    assert proibido.chamada.erro == "bloqueado_por_robots" and not proibido.chamada.sucesso
    assert proibido.chamada.extras["robots_inacessivel"] is False and mundo.paginas == [URL]
    assert mundo.esperas == []


def test_404_permite_mesmo_com_bloquear_e_nao_e_inacessivel(mundo):
    mundo.roteiro[ROBOTS] = [R("", 404)]
    a = mundo.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.sucesso and a.chamada.extras["robots_status"] == 404 and a.chamada.extras["robots_inacessivel"] is False
    assert len(mundo.lidas) == 1 and mundo.esperas == []                       # 4xx nao e falha de leitura: nao repete


@pytest.mark.parametrize("status", [401, 403, 410, 429])
def test_4xx_permite_sem_repetir_a_leitura(mundo, status):
    mundo.roteiro[ROBOTS] = [R("User-agent: *\nDisallow: /", status)]
    a = mundo.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.sucesso and len(mundo.lidas) == 1


def test_503_persistente_bloqueia_pela_politica_depois_das_tentativas(mundo):
    mundo.roteiro[ROBOTS] = [R("fora", 503)]
    a = mundo.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.erro == "robots_inacessivel" and not a.chamada.sucesso and mundo.paginas == []
    e = a.chamada.extras
    assert (e["robots_permitido"], e["robots_status"], e["robots_inacessivel"], e["robots_tentativas"]) == (False, 503, True, 3)
    assert len(mundo.lidas) == ROBOTS_TENTATIVAS and mundo.esperas == list(ROBOTS_ESPERAS_S)


def test_falha_de_rede_persistente_tem_status_nulo(mundo):
    mundo.roteiro[ROBOTS] = [requests.ConnectTimeout("lento")]
    a = mundo.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.erro == "robots_inacessivel" and a.chamada.extras["robots_status"] is None
    assert a.chamada.extras["robots_tentativas"] == 3


def test_politica_permitir_repete_mas_libera_e_marca_inacessivel(mundo):
    mundo.roteiro[ROBOTS] = [R("fora", 500)]
    a = mundo.fetcher().baixar(URL)
    assert a.chamada.sucesso and a.chamada.extras["robots_permitido"] is True and a.chamada.extras["robots_inacessivel"] is True
    assert len(mundo.lidas) == 3


def test_timeout_passageiro_dentro_das_tentativas_nao_bloqueia(mundo):
    mundo.roteiro[ROBOTS] = [requests.ReadTimeout("lento"), R("fora", 502), R("User-agent: *\nDisallow: /privado")]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    a = f.baixar(URL)
    assert a.chamada.sucesso and a.chamada.extras["robots_status"] == 200 and a.chamada.extras["robots_inacessivel"] is False
    assert a.chamada.extras["robots_tentativas"] == 3 and mundo.esperas == list(ROBOTS_ESPERAS_S)
    assert f.baixar("https://a.gov.br/privado/x").chamada.erro == "bloqueado_por_robots"       # as regras lidas valem


def test_sucesso_logo_na_segunda_leitura(mundo):
    mundo.roteiro[ROBOTS] = [R("fora", 503), R("", 404)]
    a = mundo.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.sucesso and a.chamada.extras["robots_tentativas"] == 2 and mundo.esperas == [ROBOTS_ESPERAS_S[0]]


def test_resultado_2xx_fica_em_cache_para_sempre(mundo):
    mundo.roteiro[ROBOTS] = [R("User-agent: *\nDisallow: /privado")]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    f.baixar(URL)
    mundo.avancar(10 * ROBOTS_TTL_FALHA_S)
    f.baixar("https://a.gov.br/outra")
    assert mundo.lidas == [ROBOTS]


def test_resultado_4xx_fica_em_cache_para_sempre(mundo):
    mundo.roteiro[ROBOTS] = [R("", 404)]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    f.baixar(URL)
    mundo.avancar(10 * ROBOTS_TTL_FALHA_S)
    f.baixar("https://a.gov.br/outra")
    assert mundo.lidas == [ROBOTS]


def test_falha_vale_so_pelo_ttl_e_depois_uma_boa_leitura_libera_o_host(mundo):
    mundo.roteiro[ROBOTS] = [R("fora", 503)] * 3 + [R("User-agent: *\nDisallow: /privado")]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    primeira = f.baixar(URL)
    assert primeira.chamada.erro == "robots_inacessivel" and len(mundo.lidas) == 3
    mundo.avancar(ROBOTS_TTL_FALHA_S - 1)                                       # ainda dentro da validade: nao le de novo
    assert f.baixar("https://a.gov.br/dois").chamada.erro == "robots_inacessivel" and len(mundo.lidas) == 3
    assert f.baixar("https://a.gov.br/dois").chamada.extras["robots_tentativas"] == 3
    mundo.avancar(1)                                                            # passou o TTL: o proximo URL do host le de novo
    liberada = f.baixar("https://a.gov.br/tres")
    assert liberada.chamada.sucesso and liberada.chamada.extras["robots_inacessivel"] is False and len(mundo.lidas) == 4
    assert f.baixar("https://a.gov.br/privado/x").chamada.erro == "bloqueado_por_robots"
    mundo.avancar(10 * ROBOTS_TTL_FALHA_S)
    f.baixar("https://a.gov.br/quatro")
    assert len(mundo.lidas) == 4                                                # agora o resultado e definitivo


def test_falha_apos_o_ttl_que_continua_falhando_vale_de_novo_pelo_ttl(mundo):
    mundo.roteiro[ROBOTS] = [R("fora", 503)]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    f.baixar(URL)
    mundo.avancar(ROBOTS_TTL_FALHA_S)
    f.baixar(URL)
    assert len(mundo.lidas) == 6
    f.baixar(URL)
    assert len(mundo.lidas) == 6


def test_hosts_diferentes_tem_cache_independente(mundo):
    mundo.roteiro[ROBOTS] = [R("fora", 503)]
    mundo.roteiro["https://b.example/robots.txt"] = [R("", 404)]
    f = mundo.fetcher(robots_se_inacessivel="bloquear")
    assert f.baixar(URL).chamada.erro == "robots_inacessivel"
    assert f.baixar(OUTRA).chamada.sucesso


# ---------- redirecionamentos ----------
class Redireciona(Mundo):
    def _chamar(self, metodo, url, **kw):
        if url == URL:
            self.paginas.append(url)
            r = Pagina(url)
            r.status_code, r.headers = 302, {"Location": OUTRA}
            return {"resp": r, "http_status": 302, "latencia_ms": 3, "tentativas": 1, "erro": None, "latencia_total_ms": 3, "historico": []}
        return super()._chamar(metodo, url, **kw)


def test_destino_proibido_apos_redirecionamento(monkeypatch):
    m = Redireciona(monkeypatch)
    m.roteiro["https://b.example/robots.txt"] = [R("User-agent: *\nDisallow: /")]
    a = m.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.erro == f"bloqueado_por_robots_apos_redirecionamento: {OUTRA}"
    e = a.chamada.extras
    assert e["robots_salto_1_permitido"] is False and e["robots_salto_1_inacessivel"] is False and e["robots_salto_1_status"] == 200
    assert e["robots_inacessivel"] is False and e["redirecionamentos"] == [URL, OUTRA]


def test_destino_com_robots_inacessivel_apos_redirecionamento(monkeypatch):
    m = Redireciona(monkeypatch)
    m.roteiro["https://b.example/robots.txt"] = [R("fora", 500)]
    a = m.fetcher(robots_se_inacessivel="bloquear").baixar(URL)
    assert a.chamada.erro == f"robots_inacessivel_apos_redirecionamento: {OUTRA}" and not a.chamada.sucesso
    e = a.chamada.extras
    assert (e["robots_salto_1_status"], e["robots_salto_1_inacessivel"], e["robots_salto_1_tentativas"]) == (500, True, 3)
    assert m.paginas == [URL]                                                     # o destino nao foi requisitado
