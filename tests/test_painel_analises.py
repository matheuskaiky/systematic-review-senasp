"""Pagina /analises: abas, blocos puros, estado sem verificacao humana, seguranca (CSP) e banco vazio."""
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

import painel_demo
from adaptadores.repositorio_sqlite import RepositorioSQLite
from dominio import estatistica as est
from painel import analises_blocos as b
from painel.rotas_extras.analises import ABAS
from test_painel import _app

SECOES = [chave for chave, _ in ABAS]


@pytest.fixture(scope="module")
def demo(copiar_demo):
    return copiar_demo("demo_analises")


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


def test_falsa_exclusao_com_humano_usa_so_os_excluidos_conferidos_e_o_limite_superior_exato():
    # mudança deliberada: n vem de n_excluidos_checados (antes n_humanos), e o critério é o limite superior unilateral exato
    bl = b.bloco_falsa_exclusao({"n_humanos": 500, "n_excluidos": 435, "n_excluidos_checados": 200, "n_falsas_exclusoes": 1,
                                 "n_artigos_com_veredito": 883,
                                 "cruzamento": {"excluido": {"incluir": 1, "excluir": 199, "pendente": 235},
                                                "elegivel": {"incluir": 50, "excluir": 50, "pendente": 100}},
                                 "por_categoria_falsa": {"FORA_DO_RECORTE_TEMPORAL": 1}})
    assert "1 de 200" in bl["titulo"] and bl["selo"]
    assert "limite superior unilateral de 95% (binomial exato)" in bl["subtitulo"] and "Wilson" not in bl["subtitulo"]
    assert "meta de 2% definida para este projeto" in str(bl["grafico"])
    assert "limite internacional" not in str(bl) and "internacional" not in str(bl["grafico"])
    assert "só os artigos que uma pessoa triou" in str(bl["grafico"])           # legenda do fluxo
    assert "Pendente" not in str(bl["grafico"])                                   # sem triagem humana não entra no fluxo


def test_falsa_exclusao_sem_excluidos_conferidos_avisa_e_nao_desenha():
    # humanos triaram só elegíveis/quarentena: há dados humanos, mas nenhum excluído conferido
    bl = b.bloco_falsa_exclusao({"n_humanos": 120, "tem_dados_humanos": True, "n_excluidos": 435, "n_excluidos_checados": 0,
                                 "n_falsas_exclusoes": 0, "n_artigos_com_veredito": 883})
    assert bl["grafico"] is None and bl["selo"] is None
    assert bl["aviso"] == ("O modelo excluiu 435 artigos e nenhum foi conferido por uma pessoa; a triagem automática só pode ser "
                           "considerada segura depois de conferir uma amostra aleatória dos excluídos.")
    n_zero = next(n for n in range(1, 10_000) if est.limite_superior_binomial_exato(0, n) < b.LIMITE_FALSA_EXCLUSAO)
    assert n_zero == 149
    texto = " ".join(bl["texto"])
    assert f"cerca de {n_zero} artigos excluídos conferidos" in texto
    sup30 = est.limite_superior_binomial_exato(0, 30)
    assert "amostra de 30" in texto and "só descarta falhas grosseiras" in texto
    assert f"{100 * sup30:.2f}".replace(".", ",") + "%" in texto                   # 9,50%
    assert "meta de 2% definida para este projeto" in texto
    assert dict(bl["pares"])["Excluídos conferidos por uma pessoa"] == "0"


def test_n_minimo_sem_erros_e_calculado_nao_fixo():
    assert b._n_minimo_sem_erros(0.02) == 149
    assert b._n_minimo_sem_erros(0.05) == 59
    assert b._n_minimo_sem_erros(0.01) > b._n_minimo_sem_erros(0.02)


def _veredito_do_grafico(bl):
    m = re.search(r"an-veredito-(ok|incerto|acima)", str(bl["grafico"]))
    return m.group(1)


def test_veredito_selo_e_limite_nunca_discordam_numa_grade_de_k_e_n():
    """'ok' <=> limite superior exato < meta <=> p-valor binomial < 0,05 <=> selo forte ou moderado."""
    for n in (1, 5, 10, 20, 30, 59, 60, 100, 149, 150, 200, 400):
        for k in sorted({0, 1, 2, 3, 4, 5, 8, 10, 20, n} & set(range(n + 1))):
            bl = b.bloco_falsa_exclusao({"n_excluidos": n + 10, "n_excluidos_checados": n, "n_falsas_exclusoes": k,
                                         "cruzamento": {"excluido": {"incluir": k, "excluir": n - k, "pendente": 10}}})
            sup = est.limite_superior_binomial_exato(k, n)
            p = est.teste_binomial_exato_unilateral(k, n, b.LIMITE_FALSA_EXCLUSAO, "menor")["p_valor"]
            seguro = sup < b.LIMITE_FALSA_EXCLUSAO
            assert seguro == (p < 0.05), (k, n)
            assert (_veredito_do_grafico(bl) == "ok") == seguro, (k, n, sup, p)
            assert (bl["selo"]["classe"] in ("ev-forte", "ev-moderada")) == seguro, (k, n)
            if k / n > b.LIMITE_FALSA_EXCLUSAO:
                assert _veredito_do_grafico(bl) in ("acima", "incerto")


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
    so_elegiveis = b.bloco_hipoteses(res, {"provedores": []}, {"tem_excluidos_checados": False})
    assert {l[0][:2]: l[1] for l in so_elegiveis["tabela"]["linhas"]}["H4"].startswith("aguarda")
    bl = b.bloco_hipoteses(res, {"provedores": [{"provedor": "a"}, {"provedor": "b"}]}, {"tem_excluidos_checados": True})
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


def test_opacidade_chama_de_proibido_so_a_proibicao_real_e_mostra_o_robots_inacessivel_a_parte():
    d = {"n_tentadas": 100, "n_ok": 40, "n_robots": 10, "n_http_bloqueio": 5, "n_robots_inacessivel": 30, "n_outros": 15, "pct_bloqueado": 15.0,
         "pct_inacessivel": 30.0, "n_dominios": 2,
         "dominios": [{"dominio": "ssp.xx.gov.br", "n_tentadas": 50, "n_robots": 10, "n_http_bloqueio": 5, "n_robots_inacessivel": 30}]}
    bl = b.bloco_opacidade(d)
    assert bl["titulo"].startswith("15% das 100 páginas tentadas foram proibidas pelo site")
    assert "outras 30 não puderam ser baixadas porque o robots.txt do site estava inacessível" in bl["titulo"]
    pares = dict(bl["pares"])
    # etapa 2: o motivo "Disallow" (10) deixou de ser somado aos erros HTTP 401/403/429 (5), que ganharam linha própria
    assert pares["Proibido pelo site (diretiva Disallow do robots.txt)"] == "10" and pares["Proibido pelo site (erro HTTP 401, 403 ou 429)"] == "5"
    assert pares["Bloqueio preventivo (RFC 9309): robots.txt do site indisponível"] == "30"
    assert "30 páginas" in bl["subtitulo"] and "Bloqueio preventivo (RFC 9309)" in str(bl["grafico"]) and "robots.txt do site indisponível" in str(bl["grafico"])


# ---------------- RC22: paginas que a coleta nao conseguiu verificar ----------------
def _nv(nv=37, prib=19, n404=28, outras=23, ok=842):
    def c(n, dominios=(), ufs=()):
        return {"n_paginas": n, "n_dominios": len(dominios), "n_ufs": len(ufs), "ufs": list(ufs),
                "dominios": [{"dominio": d, "n": k} for d, k in dominios], "motivos": []}
    return {"n_urls_tentadas": ok + prib + nv + n404 + outras, "n_ok": ok, "n_falhas": prib + nv + n404 + outras,
            "classes": {"proibido_pelo_site": c(prib, [("p.gov.br", prib)], ["MA"]),
                        "nao_verificavel_robots": c(nv, [("agencia.ac.gov.br", 17), ("sspds.ce.gov.br", 9)], ["AC", "CE"]),
                        "falha_definitiva_404": c(n404, [("x.gov.br", n404)], ["PI"]), "outras_falhas": c(outras)},
            "n_nao_verificaveis": nv, "n_dominios_nao_verificaveis": 2}


def test_nao_verificaveis_titulo_em_portugues_e_nao_confunde_com_proibido():
    bl = b.bloco_nao_verificaveis(_nv())
    assert bl["titulo"] == ("37 páginas não puderam ser verificadas: o robots.txt do site estava inacessível, mesmo depois de várias tentativas")
    texto = " ".join(bl["texto"])
    assert "Não verificável não é o mesmo que proibido pelo site" in texto and "RFC 9309" in texto and "28 páginas com erro 404 ou 410" in texto
    assert "pode ter deixado de ver conteúdo" in texto
    pares = dict(bl["pares"])
    assert pares["Não verificável (robots.txt inacessível, falha repetida)"] == "37" and pares["Proibido pelo site (robots.txt lido e proíbe)"] == "19"
    assert "agencia.ac.gov.br (17)" in pares["Domínios com mais páginas não verificadas"]
    assert bl["tabela"]["linhas"][1] == ["Não verificável (robots.txt inacessível, falha repetida)", "37", "2", "2"]
    assert bl["link"]["href"] == "/chamadas?etapa=download&resultado=robots_inacessivel"      # etapa 2: filtro próprio do motivo (era q=)


def test_nao_verificaveis_singular_nenhuma_e_sem_downloads():
    assert b.bloco_nao_verificaveis(_nv(nv=1))["titulo"].startswith("1 página não pôde ser verificada")
    assert b.bloco_nao_verificaveis(_nv(nv=0))["titulo"] == "Nenhuma página ficou sem verificação por robots.txt inacessível"
    vazio = b.bloco_nao_verificaveis({"n_urls_tentadas": 0, "classes": {}})
    assert vazio["titulo"] == "Sem downloads registrados" and vazio["aviso"]
    assert b.bloco_nao_verificaveis({})["titulo"] == "Sem downloads registrados"


def test_nao_verificaveis_nao_vaza_html_dos_dominios():
    d = _nv()
    d["classes"]["nao_verificavel_robots"]["dominios"] = [{"dominio": "<b>x</b>", "n": 3}]
    bl = b.bloco_nao_verificaveis(d)
    assert "<b>x</b>" in dict(bl["pares"])["Domínios com mais páginas não verificadas"]        # texto puro: o Jinja escapa na pagina


def test_aba_operacao_mostra_o_bloco_de_paginas_nao_verificadas(cliente):
    html = cliente.get("/analises?secao=operacao").text
    assert 'id="nao_verificaveis"' in html and "não puderam ser verificadas" in html
    assert "Não verificável não é o mesmo que proibido pelo site" in html


# ---------------- RG4: blocos da aba Confianca na IA ----------------
def test_aba_confianca_na_ia_mostra_os_blocos_novos_em_estado_de_espera(cliente):
    html = cliente.get("/analises?secao=auditoria").text
    assert 'id="auditoria_negativos"' in html and 'id="concordancia_achados"' in html
    assert "aguardando conferência humana" in html.lower() and "Aguardando revisão independente" in html
    assert "--independente" in html          # os tamanhos de amostra (59 e 149) sao testados no bloco puro, com paginas sem achado

