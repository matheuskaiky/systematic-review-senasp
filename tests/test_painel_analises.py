"""Pagina /analises: abas, blocos puros, estado sem verificacao humana, seguranca (CSP) e banco vazio."""
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

import painel_demo
from adaptadores.repositorio_sqlite import RepositorioSQLite
from painel import analises_blocos as b
from painel.rotas_extras.analises import ABAS
from test_painel import _app

SECOES = [chave for chave, _ in ABAS]


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("demo_analises")
    return painel_demo.construir(pasta), pasta / "raw_demo"


@pytest.fixture
def cliente(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path, somente_leitura=True)
    return TestClient(app)


def test_todas_as_abas_respondem_200(cliente):
    for secao in SECOES:
        r = cliente.get(f"/analises?secao={secao}")
        assert r.status_code == 200, secao
        assert "<h1>Análises</h1>" in r.text


def test_aba_padrao_e_invalida(cliente):
    assert cliente.get("/analises").status_code == 200
    assert cliente.get("/analises?secao=inexistente").status_code == 404
    assert cliente.get("/analises?secao=%3Cscript%3E").status_code == 404


def test_pagina_nao_tem_estilo_nem_script_inline_nem_evento(cliente):
    for secao in SECOES:
        html = cliente.get(f"/analises?secao={secao}").text
        assert " style=" not in html, secao
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), secao
        assert not re.search(r"\son[a-z]+=", html), secao


def test_menu_tem_o_link_e_o_css_da_pagina(cliente):
    html = cliente.get("/analises").text
    assert 'href="/analises"' in html and 'aria-current="page"' in html
    assert "/static/analises.css" in html
    assert cliente.get("/static/analises.css").status_code == 200


def test_grafico_tem_titulo_e_descricao_acessiveis(cliente):
    html = cliente.get("/analises?secao=adocao").text
    for svg in re.findall(r"<svg.*?</svg>", html, flags=re.S):
        assert 'role="img"' in svg and "<title" in svg and "<desc" in svg


def test_links_dos_graficos_sao_relativos(cliente):
    html = cliente.get("/analises?secao=adocao").text
    hrefs = re.findall(r'<a class="an-link" href="([^"]+)"', html)
    assert hrefs and all(h.startswith("/") and not h.startswith("//") for h in hrefs)


def test_banco_sem_tabelas_nao_quebra_nenhuma_aba(tmp_path):
    vazio = tmp_path / "vazio.db"
    sqlite3.connect(vazio).close()
    app, _ = _app(vazio, tmp_path / "raw", tmp_path, somente_leitura=True)
    cli = TestClient(app)
    for secao in SECOES:
        assert cli.get(f"/analises?secao={secao}").status_code in (200, 503), secao


def test_banco_com_esquema_e_sem_dados_nao_quebra(tmp_path):
    banco = tmp_path / "novo.db"
    RepositorioSQLite(banco).fechar()
    app, _ = _app(banco, tmp_path / "raw", tmp_path, somente_leitura=True)
    cli = TestClient(app)
    for secao in SECOES:
        r = cli.get(f"/analises?secao={secao}")
        assert r.status_code == 200, secao


# ---------------- blocos puros ----------------
def test_maturidade_conta_ufs_em_uso_e_avisa_quando_nao_ha_humano():
    d = {"base": "status_final_ou_reportado", "n_achados": 3, "n_verificados": 0, "n_descartados": 0, "tem_dados_humanos": False,
         "regioes": {"PI": "Nordeste", "SP": "Sudeste", "AC": "Norte"},
         "celulas": [{"uf": "PI", "regiao": "Nordeste", "tecnologia": "reconhecimento_facial", "status_max": "em_uso",
                      "peso": 5, "por_status": {"em_uso": 2}, "n_achados": 2, "n_verificados": 0},
                     {"uf": "SP", "regiao": "Sudeste", "tecnologia": "leitura_placas", "status_max": "piloto",
                      "peso": 4, "por_status": {"piloto": 1}, "n_achados": 1, "n_verificados": 0}]}
    bl = b.bloco_maturidade(d)
    assert bl["titulo"].startswith("1 de 3 UFs") and "classificadas pelo modelo" in bl["titulo"]
    assert bl["aviso"] and "<svg" in str(bl["grafico"])


def test_maturidade_sem_achados_nao_levanta():
    bl = b.bloco_maturidade({})
    assert "Ainda não há achados" in bl["titulo"]


def test_regiao_tecnologia_usa_qui_quadrado_e_selo():
    tabela = [[30, 5], [4, 31], [10, 10]]
    d = {"tem_dados_humanos": False, "contingencia_regiao_tecnologia": {
        "regioes": ["Norte", "Sul", "Sudeste"], "tecnologias": ["reconhecimento_facial", "leitura_placas"], "tabela": tabela,
        "n": 90}}
    bl = b.bloco_regiao_tecnologia(d)
    assert bl["selo"]["classe"] == "ev-forte"
    assert "muda de uma região para outra" in bl["titulo"]
    assert any("achado, não a UF" in t for t in bl["texto"])


def test_regiao_tecnologia_com_pouca_amostra_usa_monte_carlo_e_nao_afirma():
    d = {"contingencia_regiao_tecnologia": {"regioes": ["Norte", "Sul"], "tecnologias": ["reconhecimento_facial", "leitura_placas"],
                                            "tabela": [[1, 1], [1, 1]], "n": 4}}
    bl = b.bloco_regiao_tecnologia(d)
    assert "Monte Carlo" in " ".join(v for _, v in bl["pares"])
    assert "Sem evidência suficiente" in bl["titulo"]


def test_falsa_exclusao_sem_humano_nao_mostra_numero():
    bl = b.bloco_falsa_exclusao({"n_humanos": 0, "n_artigos_com_veredito": 883})
    assert bl["grafico"] is None and "Aguardando verificação humana" in bl["aviso"]


def test_falsa_exclusao_com_humano_calcula_wilson_e_binomial():
    bl = b.bloco_falsa_exclusao({"n_humanos": 200, "n_falsas_exclusoes": 1, "n_artigos_com_veredito": 883,
                                 "cruzamento": {"excluido": {"incluir": 1, "excluir": 99}, "elegivel": {"incluir": 50, "excluir": 50}},
                                 "por_categoria_falsa": {"FORA_DO_RECORTE_TEMPORAL": 1}})
    assert "1 de 200" in bl["titulo"] and bl["selo"] and "Wilson" in bl["subtitulo"]


def test_calibracao_sem_humano_e_com_humano():
    sem = b.bloco_calibracao({"tem_dados_humanos": False, "n_achados": 10,
                              "por_confianca": [{"confianca": c, "n_achados": 3, "n_verificados": 0, "n_confirmados": 0, "n_descartados": 0}
                                                for c in ("alta", "media", "baixa")]})
    assert "Ainda não dá para medir" in sem["titulo"]
    com = b.bloco_calibracao({"tem_dados_humanos": True, "n_achados": 40, "n_verificados": 40,
                              "por_confianca": [{"confianca": "alta", "n_achados": 20, "n_verificados": 20, "n_confirmados": 19, "n_descartados": 1},
                                                {"confianca": "media", "n_achados": 10, "n_verificados": 10, "n_confirmados": 6, "n_descartados": 4},
                                                {"confianca": "baixa", "n_achados": 10, "n_verificados": 10, "n_confirmados": 3, "n_descartados": 7}]})
    assert "95%" in com["titulo"] and "30%" in com["titulo"]


def test_hipoteses_dependem_de_humano_e_de_dois_buscadores():
    res = {"tem_dados_humanos_achados": False, "tem_dados_humanos_artigos": False}
    bl = b.bloco_hipoteses(res, {"provedores": [{"provedor": "x"}]})
    situacao = {l[0][:2]: l[1] for l in bl["tabela"]["linhas"]}
    assert situacao["H1"] == "pode ser feita" and situacao["H6"] == "pode ser feita"
    assert all(situacao[h].startswith("aguarda") for h in ("H2", "H3", "H4", "H5"))
    res = {"tem_dados_humanos_achados": True, "tem_dados_humanos_artigos": True}
    bl = b.bloco_hipoteses(res, {"provedores": [{"provedor": "a"}, {"provedor": "b"}]})
    assert all(l[1] == "pode ser feita" for l in bl["tabela"]["linhas"])


def test_blocos_aceitam_dicionarios_vazios():
    for f in (b.bloco_lgpd, b.bloco_fornecedores, b.bloco_funil, b.bloco_posicao_web, b.bloco_posicao_scholar, b.bloco_saturacao,
              b.bloco_temporal, b.bloco_multitermo, b.bloco_opacidade, b.bloco_tokens, b.bloco_tamanho, b.bloco_falsa_exclusao):
        bl = f({})
        assert bl["titulo"] and isinstance(bl["texto"], list)
    assert b.bloco_calibracao({"por_confianca": []})["titulo"]


def test_titulos_nao_vazam_html_dos_dados():
    d = {"top": [{"fornecedor": "<b>X</b>", "n_achados": 3, "n_ufs": 1, "n_tecnologias": 1}], "n_informado": 3, "n_nao_informado": 0,
         "share_top3": 1.0}
    bl = b.bloco_fornecedores(d)
    assert "<b>X</b>" not in str(bl["grafico"])
