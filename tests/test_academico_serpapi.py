"""M6: busca academica (SerpApi Scholar) e correcao C8. Nenhum teste abre conexao: `chamar` e substituido."""
import json
import logging
import pathlib
import sys

import pytest

import main
from adaptadores import academico_serpapi_scholar as modulo
from adaptadores.academico_serpapi_scholar import AcademicoSerpApiScholar
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import _reg
from aplicacao import busca_academica
from config import consultas as C
from dados_metricas import _novo_run
from dominio.modelos import ArtigoAcademico, FiltrosAcademicos, PaginaAcademica, Termo

SINT = pathlib.Path(__file__).parent / "fixtures" / "sintetico"
REAL = pathlib.Path(__file__).parent / "fixtures" / "serpapi_scholar.json"
CHAVE = "CHAVE-SERPAPI-FALSA-123456"
TERMO = Termo("T01", '"reconhecimento facial"', "pt", "reconhecimento_identificacao")
FILTROS = FiltrosAcademicos(ano_inicial=2019, ano_final=None, por_pagina=20)


def _fix(nome):
    return (SINT / nome).read_text(encoding="utf-8")


class _Resp:
    def __init__(self, texto, ok=True, json_invalido=False):
        self.text, self.content, self.ok = texto, texto.encode(), ok
        self._json_invalido = json_invalido

    def json(self):
        if self._json_invalido:
            raise ValueError("corpo nao e json")
        return json.loads(self.text)


def _chamar(monkeypatch, texto=None, erro=None, http_status=200, ok=True, json_invalido=False):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": _Resp(texto, ok, json_invalido) if texto is not None else None, "http_status": http_status,
                "latencia_ms": 900, "tentativas": 1, "erro": erro, "latencia_total_ms": 900, "historico": [], "corpo_erro": None}

    monkeypatch.setattr(modulo, "chamar", falso)
    return visto


# ====================== interpretar ======================
def test_interpretar_fixture_sintetica():
    artigos, total, id_externo, tempo, erro = AcademicoSerpApiScholar.interpretar(_fix("serpapi_scholar_sintetico.json"), 0)
    assert (total, id_externo, tempo, erro) == (1234, "sintetico-scholar-0001", 1.23, None)
    assert [a.titulo for a in artigos] == ["Reconhecimento facial na segurança pública", "Policiamento preditivo no Brasil",
                                           "Artigo sem resumo de publicacao"]              # o titulo em branco foi ignorado
    a, b, c = artigos
    assert (a.link, a.autores_publicacao, a.ano, a.citacoes, a.posicao) == ("https://exemplo.edu/a", "A Silva, B Souza - Revista X, 2019 - exemplo.edu", 2019, 42, 1)
    assert (b.ano, b.citacoes, b.posicao) == (2023, None, 2)                                  # o ultimo ano do resumo; sem cited_by
    assert (c.link, c.autores_publicacao, c.ano, c.citacoes, c.posicao) == (None, None, None, None, 4)


def test_posicao_soma_o_deslocamento_da_pagina():
    artigos, *_ = AcademicoSerpApiScholar.interpretar(_fix("serpapi_scholar_sintetico.json"), 40)
    assert [a.posicao for a in artigos] == [41, 42, 44]


def test_posicao_ausente_cai_para_o_indice():
    raw = json.dumps({"organic_results": [{"title": "A"}, {"title": "B"}]})
    artigos, *_ = AcademicoSerpApiScholar.interpretar(raw, 20)
    assert [a.posicao for a in artigos] == [20, 21]


def test_interpretar_resposta_sem_resultados():
    artigos, total, id_externo, tempo, erro = AcademicoSerpApiScholar.interpretar(_fix("serpapi_scholar_sem_resultados_sintetico.json"), 0)
    assert artigos == [] and total == 0 and erro == "Google hasn't returned any results for this query."


@pytest.mark.parametrize("raw", ["{}", '{"organic_results": null}', '{"organic_results": []}'])
def test_interpretar_respostas_vazias(raw):
    assert AcademicoSerpApiScholar.interpretar(raw, 0) == ([], None, None, None, None)


# ====================== buscar_pagina ======================
def test_buscar_pagina_monta_os_parametros_da_documentacao(monkeypatch):
    visto = _chamar(monkeypatch, _fix("serpapi_scholar_sintetico.json"))
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 20, FiltrosAcademicos(2019, 2024, 20))
    esperado = {"engine": "google_scholar", "q": '"reconhecimento facial"', "hl": "pt", "num": 20, "start": 20,
                "as_ylo": 2019, "as_yhi": 2024}
    assert pag.chamada.parametros == esperado
    assert visto["params"] == {**esperado, "api_key": CHAVE} and visto["metodo"] == "GET" and visto["url"] == AcademicoSerpApiScholar.URL


def test_filtros_de_ano_so_vao_quando_definidos(monkeypatch):
    visto = _chamar(monkeypatch, _fix("serpapi_scholar_sintetico.json"))
    AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FiltrosAcademicos(None, None, 20))
    assert "as_ylo" not in visto["params"] and "as_yhi" not in visto["params"]


def test_a_chave_vai_so_na_requisicao_nunca_no_registro(monkeypatch):
    _chamar(monkeypatch, _fix("serpapi_scholar_sintetico.json"))
    c = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS).chamada
    assert CHAVE not in json.dumps(c.parametros) and CHAVE not in json.dumps(c.extras) and "api_key" not in c.parametros


def test_buscar_pagina_com_resposta_normal(monkeypatch):
    _chamar(monkeypatch, _fix("serpapi_scholar_sintetico.json"))
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS)
    c = pag.chamada
    assert len(pag.artigos) == 3 and pag.total_reportado == 1234
    assert c.sucesso and c.provedor == "serpapi_scholar" and c.operacao == "buscar_pagina"
    assert (c.id_externo, c.http_status, c.latencia_ms) == ("sintetico-scholar-0001", 200, 900)
    assert c.extras["tempo_servidor_s"] == 1.23 and "latencia_total_ms" in c.extras and c.raw == _fix("serpapi_scholar_sintetico.json").encode()


def test_200_com_nenhum_resultado_nao_e_erro(monkeypatch):
    _chamar(monkeypatch, _fix("serpapi_scholar_sem_resultados_sintetico.json"))
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS)
    assert pag.chamada.sucesso and pag.artigos == [] and pag.total_reportado == 0


def test_200_com_outro_erro_da_api_e_registrado(monkeypatch):
    _chamar(monkeypatch, _fix("serpapi_scholar_erro_sintetico.json"))
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS)
    assert pag.chamada.erro == "Your account has run out of searches." and not pag.chamada.sucesso and pag.artigos == []


def test_erro_http_nao_levanta(monkeypatch):
    _chamar(monkeypatch, '{"error": "Invalid API key."}', erro="HTTP 401: Invalid API key.", http_status=401, ok=False)
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS)
    assert pag.chamada.erro.startswith("HTTP 401") and pag.artigos == [] and pag.chamada.raw is not None


def test_falha_de_rede_sem_resposta(monkeypatch):
    _chamar(monkeypatch, None, erro="ConnectionError('x')", http_status=None)
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS)
    assert not pag.chamada.sucesso and pag.chamada.raw is None


@pytest.mark.parametrize("texto", ["isto nao e json", '{"organic_results": [5, "x"]}', '{"search_information": 7}'])
def test_resposta_fora_do_formato_vira_resposta_inesperada(monkeypatch, texto):
    _chamar(monkeypatch, texto)
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FILTROS)
    assert pag.chamada.erro.startswith("resposta_inesperada") and pag.chamada.raw == texto.encode()


# ====================== saldo ======================
def test_saldo_devolve_as_buscas_restantes(monkeypatch):
    visto = _chamar(monkeypatch, _fix("serpapi_conta_sintetico.json"))
    assert AcademicoSerpApiScholar(CHAVE).saldo() == 5958
    assert visto["url"] == AcademicoSerpApiScholar.URL_CONTA and visto["params"] == {"api_key": CHAVE}


def test_saldo_usa_plan_searches_left_se_nao_houver_total(monkeypatch):
    _chamar(monkeypatch, '{"plan_searches_left": 120}')
    assert AcademicoSerpApiScholar(CHAVE).saldo() == 120


@pytest.mark.parametrize("kw", [dict(texto=None, erro="x", http_status=None), dict(texto="{}", ok=False, http_status=401),
                                dict(texto="nao e json", json_invalido=True), dict(texto="[1, 2]")])
def test_saldo_indisponivel_nunca_levanta(monkeypatch, kw):
    _chamar(monkeypatch, **kw)
    assert AcademicoSerpApiScholar(CHAVE).saldo() is None


# ====================== composicao, estimar e estagio ======================
def test_fabrica_monta_o_adaptador_com_a_chave_do_ambiente(monkeypatch):
    from composicao import Fabrica
    monkeypatch.setenv("SERPAPI_KEY", CHAVE)
    a = Fabrica().academico
    assert isinstance(a, AcademicoSerpApiScholar) and a.nome == "serpapi_scholar"


def test_fabrica_sem_chave_nao_cria_o_adaptador():
    from composicao import Fabrica
    with pytest.raises(SystemExit) as e:
        Fabrica().academico
    assert "SERPAPI_KEY" in str(e.value)


def test_estimar_mostra_o_saldo_real_quando_ha_chave(ambiente_cli, monkeypatch, capsys):
    monkeypatch.setenv("SERPAPI_KEY", CHAVE)
    _chamar(monkeypatch, _fix("serpapi_conta_sintetico.json"))
    monkeypatch.setattr(sys, "argv", ["main.py", "estimar"])
    main.main()
    assert "Academic provider balance: 5958" in capsys.readouterr().out


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def test_estagio_com_o_adaptador_real_grava_artigos_total_e_contagens(tmp_path, monkeypatch, silencio):
    _chamar(monkeypatch, _fix("serpapi_scholar_sintetico.json"))
    repo, bruto = RepositorioSQLite(tmp_path / "s.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "academico")
    busca_academica.executar(repo, bruto, AcademicoSerpApiScholar(CHAVE), run_id, [TERMO], FILTROS, 3, [CHAVE], 0)
    assert repo.conn.execute("SELECT COUNT(*) FROM artigos").fetchone()[0] == 3
    assert repo.conn.execute("SELECT COUNT(*) FROM ocorrencias").fetchone()[0] == 3
    c = dict(repo.conn.execute("SELECT * FROM chamadas").fetchone())
    assert (c["total_reportado"], c["n_retornados"], c["n_novos"], c["pagina"], c["alvo_id"], c["sucesso"]) == (1234, 3, 3, 1, "T01", 1)
    assert c["id_externo"] == "sintetico-scholar-0001" and CHAVE not in c["parametros_json"] + c["extras_json"]
    assert repo.conn.execute("SELECT COUNT(*) FROM chamadas").fetchone()[0] == 1                # 3 < 20: nao pede a pagina 2
    v = dict(repo.conn.execute("SELECT * FROM v_metricas_por_termo").fetchone())
    assert (v["total_reportado_aprox"], v["n_retornados"], v["n_novos_artigos"]) == (1234, 3, 3)


# ====================== C8: retomada sem gastar credito a toa ======================
class Contador:
    """Adaptador falso: devolve `tamanhos[(termo, inicio)]` artigos e guarda cada pedido recebido."""
    nome = "contador"

    def __init__(self, tamanhos, falhas=()):
        self.tamanhos, self.falhas, self.pedidos = tamanhos, set(falhas), []

    def saldo(self):
        return None

    def buscar_pagina(self, termo, inicio, filtros):
        self.pedidos.append((termo.id, inicio))
        reg = _reg(self.nome, "buscar_pagina", raw=b"{}")
        if (termo.id, inicio) in self.falhas:
            reg.erro, reg.http_status = "HTTP 500: falha", 500
            return PaginaAcademica([], None, reg)
        n = self.tamanhos.get((termo.id, inicio), 0)
        arts = [ArtigoAcademico(f"Artigo {termo.id} {inicio} {i}", None, "A - R, 2023", 2023, "r", i, inicio + i + 1) for i in range(n)]
        return PaginaAcademica(arts, 100, reg)


def _executar(repo, bruto, adaptador, run_id, termos=(TERMO,), paginas=3):
    busca_academica.executar(repo, bruto, adaptador, run_id, list(termos), FILTROS, paginas, [], 0)


@pytest.fixture
def banco(tmp_path):
    repo = RepositorioSQLite(tmp_path / "c8.db")
    return repo, BrutoLocal(tmp_path / "raw"), _novo_run(repo, "academico")


def test_resultado_chamada_so_existe_para_chamada_concluida(banco):
    repo, bruto, run_id = banco
    ad = Contador({("T01", 0): 5}, falhas=[("T02", 0)])
    _executar(repo, bruto, ad, run_id, termos=[TERMO, Termo("T02", "x", "pt", "g")])
    chaves = {r["alvo_id"]: r["chave_idempotencia"] for r in repo.conn.execute("SELECT alvo_id, chave_idempotencia FROM chamadas")}
    assert repo.resultado_chamada(run_id, chaves["T01"]) == (1, 5)
    assert repo.resultado_chamada(run_id, chaves["T02"]) is None                              # falhou: nao esta concluida
    assert repo.resultado_chamada(run_id, "chave-inexistente") is None
    assert repo.resultado_chamada("outro_run", chaves["T01"]) is None


def test_retomar_nao_pede_a_pagina_seguinte_de_uma_pagina_incompleta(banco):
    repo, bruto, run_id = banco
    ad = Contador({("T01", 0): 3})
    _executar(repo, bruto, ad, run_id)
    assert ad.pedidos == [("T01", 0)]                                  # 3 < 20: nao ha pagina 2
    _executar(repo, bruto, ad, run_id)                                 # retomada
    assert ad.pedidos == [("T01", 0)]                                  # antes da C8 pedia a pagina 2 aqui e gastava um credito
    assert repo.conn.execute("SELECT COUNT(*) FROM chamadas").fetchone()[0] == 1


def test_retomar_com_paginas_completas_nao_repete_nada(banco):
    repo, bruto, run_id = banco
    ad = Contador({("T01", 0): 20, ("T01", 20): 5})
    _executar(repo, bruto, ad, run_id)
    assert ad.pedidos == [("T01", 0), ("T01", 20)]
    _executar(repo, bruto, ad, run_id)
    assert ad.pedidos == [("T01", 0), ("T01", 20)]                     # a pagina 2 incompleta encerra o termo


def test_retomar_continua_de_onde_parou(banco):
    repo, bruto, run_id = banco
    ad = Contador({("T01", 0): 20, ("T01", 20): 20, ("T01", 40): 7})
    _executar(repo, bruto, ad, run_id, paginas=1)                      # interrompido apos a pagina 1 (completa)
    assert ad.pedidos == [("T01", 0)]
    _executar(repo, bruto, ad, run_id, paginas=3)
    assert ad.pedidos == [("T01", 0), ("T01", 20), ("T01", 40)]        # so as paginas que faltavam


def test_n_retornados_desconhecido_segue_para_a_proxima_pagina(banco):
    repo, bruto, run_id = banco
    ad = Contador({("T01", 0): 20, ("T01", 20): 4})
    _executar(repo, bruto, ad, run_id, paginas=1)
    repo.conn.execute("UPDATE chamadas SET n_retornados=NULL")         # queda entre registrar a chamada e atualizar a contagem
    repo.confirmar()
    _executar(repo, bruto, ad, run_id, paginas=3)
    assert ad.pedidos == [("T01", 0), ("T01", 20)]                     # sem a contagem nao da para concluir: segue


def test_pagina_com_falha_e_retentada_na_retomada(banco):
    repo, bruto, run_id = banco
    ad = Contador({("T01", 0): 5}, falhas=[("T01", 0)])
    _executar(repo, bruto, ad, run_id)
    assert ad.pedidos == [("T01", 0)] and repo.conn.execute("SELECT sucesso FROM chamadas").fetchone()[0] == 0
    ad.falhas.clear()
    _executar(repo, bruto, ad, run_id)
    assert ad.pedidos == [("T01", 0), ("T01", 0)]                      # a falha nao conta como feita


def test_cada_termo_tem_a_propria_regra_de_parada(banco):
    repo, bruto, run_id = banco
    t2 = Termo("T02", '"outro"', "pt", "g")
    ad = Contador({("T01", 0): 3, ("T02", 0): 20, ("T02", 20): 2})
    _executar(repo, bruto, ad, run_id, termos=[TERMO, t2])
    n_primeira = len(ad.pedidos)
    _executar(repo, bruto, ad, run_id, termos=[TERMO, t2])
    assert ad.pedidos[:n_primeira] == [("T01", 0), ("T02", 0), ("T02", 20)] and len(ad.pedidos) == n_primeira


def test_termo_sem_resultados_encerra_e_nao_pede_mais(banco):
    repo, bruto, run_id = banco
    ad = Contador({})
    _executar(repo, bruto, ad, run_id)
    _executar(repo, bruto, ad, run_id)
    assert ad.pedidos == [("T01", 0)]                                  # 0 resultados < 20 tambem encerra


# ====================== contrato real ======================
@pytest.mark.skipif(not REAL.exists(), reason="fixture real ainda nao existe (criada no M6, depois da primeira busca real)")
def test_scholar_interpreta_resposta_real():
    artigos, total, id_externo, tempo, erro = AcademicoSerpApiScholar.interpretar(REAL.read_text(encoding="utf-8"), 0)
    assert artigos and erro is None and all(a.titulo and a.posicao >= 0 for a in artigos)
