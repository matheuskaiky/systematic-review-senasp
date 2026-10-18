"""RB15 (D75): cockpit de triagem (fila lateral, leitura, decisao) para artigos e achados, sem ancoragem no modelo.

O que ja era fixado pelos testes do painel continua valendo; aqui ficam so os comportamentos novos.
"""
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from painel.rotulos_escopo import CATEGORIAS
from test_painel import _app, demo  # noqa: F401

RESUMO_APOIO = "Depois de decidir: opinião do modelo e relevância (Brasil + tema)"
CHIPS = ["fora de segurança pública", "sem IA ou tecnologia", "metodologia irrelevante", "fora do recorte temporal"]


@pytest.fixture
def cli(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, c = _app(copia, raw, tmp_path)
    c.termos = {"T01": '"reconhecimento facial"'}
    c.bases = ("IEEE", "ACM", "Scopus", "SBC OpenLib")
    return TestClient(app), copia


def _um(copia, sql):
    return sqlite3.connect(copia).execute(sql).fetchone()[0]


def _artigo_na_fila(cli, extra=""):
    c, copia = cli
    r = c.get("/literatura/triagem" + extra, follow_redirects=False)
    assert r.status_code == 303
    return c.get(r.headers["location"]).text, r.headers["location"]


def _achado_na_fila(cli, extra=""):
    c, _ = cli
    r = c.get("/revisao/achados" + extra, follow_redirects=False)
    assert r.status_code == 303
    return c.get(r.headers["location"]).text, r.headers["location"]


# ====================== artigo ======================
def test_artigo_tem_as_tres_colunas_do_cockpit(cli):
    h, _ = _artigo_na_fila(cli)
    assert 'class="triagem"' in h and 'class="fila-lateral"' in h and '<aside class="decisao"' in h
    assert h.index('class="fila-lateral"') < h.index('class="coluna-leitura"') < h.index('<aside class="decisao"')
    assert h.count('aria-current="true"') == 1


def test_sem_ancoragem_modelo_e_relevancia_so_depois_da_decisao(cli):
    h, _ = _artigo_na_fila(cli)
    m = re.search(r'<details class="cartao apoio-pos-decisao"[^>]*>', h)
    assert m and " open" not in m.group(0)
    assert f"<summary>{RESUMO_APOIO}</summary>" in h
    bloco = h[m.start():h.index("</details>", m.start())]
    assert 'id="triagem-llm"' in bloco and "explica-relevancia" in bloco
    assert h.index('id="form-decisao"') < m.start()
    assert h.count('id="triagem-llm"') == 1 and h.count("explica-relevancia") == 1


def test_botoes_de_decisao_neutros(cli):
    h, _ = _artigo_na_fila(cli)
    assert not re.search(r'class="[^"]*\bsugerido\b', h) and "sugestão do modelo" not in h


def test_chips_de_motivo_usam_as_categorias_do_sistema(cli):
    h, _ = _artigo_na_fila(cli)
    chips = re.findall(r'data-motivo="([^"]+)"', h)
    assert chips == CHIPS
    assert set(chips) <= set(CATEGORIAS.values())


def test_fila_lateral_e_formulario_preservam_os_filtros(cli):
    h, local = _artigo_na_fila(cli, "?decisao=pendente&ordem=ano")
    assert "ordem=ano" in local
    acoes = re.findall(r'<form method="post" action="(/literatura/artigos/[^"]+)"', h)
    assert acoes and all("ordem=ano" in a for a in acoes)
    links = re.findall(r'class="fila-link" href="([^"]+)"', h)
    assert links and all("ordem=ano" in l and "fila=1" in l for l in links)


def test_fora_da_fila_nao_ha_coluna_da_fila(cli):
    c, copia = cli
    i = _um(copia, "SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT 1")
    h = c.get(f"/literatura/artigos/{i}").text
    assert 'class="fila-lateral"' not in h and "fila de triagem" not in h
    assert 'class="triagem"' in h


def test_janela_da_fila_tem_no_maximo_15_itens(cli):
    h, _ = _artigo_na_fila(cli)
    assert 1 <= h.count('class="fila-link"') <= 15


# ====================== achado ======================
def test_achado_tem_o_cockpit_e_o_h1_sem_atributos(cli):
    h, _ = _achado_na_fila(cli)
    assert 'class="triagem"' in h and 'class="fila-lateral"' in h and '<aside class="decisao"' in h
    assert "<h1>" in h
    assert h.count('aria-current="true"') == 1
    assert [t for t in re.findall(r'data-tecla="(\d)"', h)] == ["1", "2", "3", "4", "5", "6"]


def test_achado_sem_status_do_modelo_nos_botoes(cli):
    h, _ = _achado_na_fila(cli)
    assert "apontado pelo modelo" not in h and not re.search(r'class="[^"]*\bsugerido\b', h)
    assert 'class="selo st-' not in h                                          # status apontado pelo modelo nao aparece


def test_achado_fila_preserva_filtros(cli):
    h, local = _achado_na_fila(cli, "?uf=SP")
    assert "uf=SP" in local
    links = re.findall(r'class="fila-link" href="([^"]+)"', h)
    assert links and all("uf=SP" in l and "fila=1" in l for l in links)
    acao = re.search(r'<form method="post" action="([^"]*/verificar[^"]*)"', h).group(1)
    assert "uf=SP" in acao


# ====================== decisoes da revisao independente (bloco C) ======================
@pytest.mark.parametrize("ids,atual,esperado", [
    ([], 1, []), ([1], 1, [1]), ([1], 2, [1]), (list(range(10)), 9, list(range(10))),
    (list(range(16)), 15, list(range(1, 16))), (list(range(30)), 15, list(range(8, 23))),
    (list(range(30)), 29, list(range(15, 30))), (list(range(30)), 99, list(range(15)))])
def test_janela_da_fila_tabela(ids, atual, esperado):
    from painel.app import _janela, JANELA_FILA
    assert JANELA_FILA == 15 and _janela(ids, atual) == esperado


def test_relevancia_so_dentro_do_bloco_pos_decisao(cli):
    h, _ = _artigo_na_fila(cli)
    m = re.search(r'<details class="cartao apoio-pos-decisao"[^>]*>', h)
    bloco = h[m.start():h.index("</details>", m.start())]
    fora = h[:m.start()] + h[h.index("</details>", m.start()):]
    assert 'class="selo rel-' in bloco and 'class="selo rel-' not in fora


def test_achado_fora_da_fila_e_com_barra_de_progresso(cli):
    c, copia = cli
    h, _ = _achado_na_fila(cli)
    assert '<progress class="progresso"' in h and "verificado</progress>" in h
    a = _um(copia, "SELECT achado_id FROM v_achados_revisao LIMIT 1")
    assert 'class="fila-lateral"' not in c.get(f"/achados/{a}").text


def test_titulo_com_script_e_escapado_na_fila(cli):
    c, copia = cli
    i = _um(copia, "SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id WHERE t.decisao IS NULL "
                   "ORDER BY a.artigo_id LIMIT 1")
    con = sqlite3.connect(copia)
    con.execute("UPDATE artigos SET titulo='<script>x</script>' WHERE artigo_id=?", (i,))
    con.commit()
    h = c.get(f"/literatura/artigos/{i}?fila=1").text           # o item aberto sempre esta na janela da fila
    fila = h[h.index('class="fila-lateral"'):h.index('class="coluna-leitura"')]
    assert "<script>x</script>" not in h and "&lt;script&gt;x&lt;/script&gt;" in fila


def test_snippet_vazio_mostra_aviso(cli):
    c, copia = cli
    i = _um(copia, "SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT 1")
    con = sqlite3.connect(copia)
    con.execute("UPDATE artigos SET snippet='   ' WHERE artigo_id=?", (i,))
    con.commit()
    h = c.get(f"/literatura/artigos/{i}").text
    assert "A fonte não trouxe trecho nem resumo para este artigo. Decida pelo título." in h


def test_item_decidido_reaberto_na_fila_sem_aria_current(cli):
    c, copia = cli
    i = _um(copia, "SELECT artigo_id FROM triagem WHERE decisao IN ('incluir','excluir') LIMIT 1")
    h = c.get(f"/literatura/artigos/{i}?fila=1").text
    assert 'class="fila-lateral"' in h and 'aria-current="true"' not in h


def test_bloco_em_duvida_removido(cli):
    h, _ = _achado_na_fila(cli)
    assert "Em dúvida sobre o critério?" not in h


# ====================== formularios por permissao, com autenticacao (D78, decisao 9) ======================
from dominio import autenticacao as A  # noqa: E402
from test_autenticacao import _criar, _csrf, _entrar, painel  # noqa: E402,F401  (fixture `painel`: autenticacao ligada)

MSG_ENTRAR = "Entre no painel com um grupo que pode decidir para registrar decisões."
MSG_GRUPO = "Seu grupo não pode registrar decisões aqui."


def _artigo_id(copia, sql="SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT 1"):
    return _um(copia, sql)


def _achado_nao_verificado(copia):
    return _um(copia, "SELECT achado_id FROM v_achados_revisao WHERE verificado=0 ORDER BY achado_id LIMIT 1")


def _verificar_como(cli, achado):
    h = cli.get(f"/achados/{achado}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    versao = re.search(r'name="versao" value="([^"]*)"', h).group(1)
    status = re.search(r'name="status_final" value="([^"]+)"', h).group(1)
    r = cli.post(f"/achados/{achado}/verificar", data={"status_final": status, "observacao": "", "versao": versao, "csrf": csrf},
                 follow_redirects=False)
    assert r.status_code == 303
    return csrf


def _sair(cli):
    cli.post("/sair", data={"csrf": _csrf(cli)})
    cli.cookies.clear()


def test_anonimo_ve_o_cockpit_sem_formularios(painel):
    cli, _, copia, _ = painel
    h = cli.get(f"/literatura/artigos/{_artigo_id(copia)}").text
    assert 'id="form-decisao"' not in h and h.count(MSG_ENTRAR) == 1
    assert 'class="cartao apoio-pos-decisao"' in h and 'action="/literatura/artigos/' not in h
    h = cli.get(f"/achados/{_achado_nao_verificado(copia)}").text
    assert 'id="form-decisao"' not in h and h.count(MSG_ENTRAR) == 1
    assert "/desfazer" not in h and "/revogar" not in h


def test_visitante_com_permissao_de_escrita_no_banco_continua_sem_formulario(painel):
    cli, _, copia, contas_db = painel
    c = sqlite3.connect(contas_db)
    c.execute("INSERT INTO grupo_permissoes SELECT grupo_id, 'verificar_achados' FROM grupos WHERE nome='Visitante'")
    c.execute("INSERT INTO grupo_permissoes SELECT grupo_id, 'triar_artigos' FROM grupos WHERE nome='Visitante'")
    c.commit()
    assert 'id="form-decisao"' not in cli.get(f"/achados/{_achado_nao_verificado(copia)}").text
    assert 'id="form-decisao"' not in cli.get(f"/literatura/artigos/{_artigo_id(copia)}").text


def test_leitor_logado_ve_a_mensagem_do_grupo(painel):
    cli, _, copia, _ = painel
    _criar(painel, "leo", "Leitor")
    _entrar(cli, "leo")
    h = cli.get(f"/literatura/artigos/{_artigo_id(copia)}").text
    assert 'id="form-decisao"' not in h and h.count(MSG_GRUPO) == 1 and MSG_ENTRAR not in h
    h = cli.get(f"/achados/{_achado_nao_verificado(copia)}").text
    assert 'id="form-decisao"' not in h and h.count(MSG_GRUPO) == 1


def test_revisor_decide_mas_nao_revoga(painel):
    cli, _, copia, _ = painel
    _criar(painel, "maria", "Revisor", nome="Maria Souza")
    _entrar(cli, "maria")
    achado = _achado_nao_verificado(copia)
    _verificar_como(cli, achado)
    h = cli.get(f"/achados/{achado}").text
    assert 'id="form-decisao"' in h and f'/achados/{achado}/revogar' not in h
    assert re.search(r'<input id="revisor" name="revisor" value="Maria Souza" readonly required autocomplete="name">', h)
    assert MSG_ENTRAR not in h and MSG_GRUPO not in h


def test_desfazer_so_aparece_para_o_autor_e_o_admin(painel):
    cli, _, copia, _ = painel
    _criar(painel, "maria", "Revisor", nome="Maria Souza")
    _criar(painel, "joao", "Revisor", nome="João Lima")
    _criar(painel, "chefe", "Administrador", nome="Chefe")
    achado = _achado_nao_verificado(copia)
    _entrar(cli, "maria")
    _verificar_como(cli, achado)
    acao = f'action="/achados/{achado}/desfazer'
    assert acao in cli.get(f"/achados/{achado}").text
    _sair(cli)
    _entrar(cli, "joao")
    h = cli.get(f"/achados/{achado}").text
    assert acao not in h and 'id="form-decisao"' in h
    _sair(cli)
    _entrar(cli, "chefe")
    h = cli.get(f"/achados/{achado}").text
    assert acao in h and f'/achados/{achado}/revogar' in h and 'id="form-decisao"' in h


def test_texto_completo_exige_as_duas_permissoes(painel):
    cli, _, copia, contas_db = painel
    i = _artigo_id(copia, "SELECT artigo_id FROM triagem WHERE decisao='incluir' ORDER BY artigo_id LIMIT 1")
    _criar(painel, "maria", "Revisor")
    _entrar(cli, "maria")
    assert "<h2>Texto completo</h2>" in cli.get(f"/literatura/artigos/{i}").text
    c = sqlite3.connect(contas_db)
    c.execute("DELETE FROM grupo_permissoes WHERE permissao='triar_texto_completo' "
              "AND grupo_id=(SELECT grupo_id FROM grupos WHERE nome='Revisor')")
    c.commit()
    h = cli.get(f"/literatura/artigos/{i}").text
    assert "<h2>Texto completo</h2>" not in h and 'id="form-decisao"' in h


def test_nomes_dos_revisores_ocultos_no_cockpit_para_anonimo(painel):
    cli, _, copia, _ = painel
    i, nome = sqlite3.connect(copia).execute(
        "SELECT artigo_id, revisor FROM triagem WHERE revisor IS NOT NULL AND TRIM(revisor) <> '' ORDER BY artigo_id LIMIT 1").fetchone()
    h = cli.get(f"/literatura/artigos/{i}").text
    assert nome not in h and "Última decisão por Revisor" in h


def test_banco_de_contas_ocupado_no_cockpit_vira_503(painel, monkeypatch):
    cli, contas, copia, _ = painel

    def ocupado(*a, **k):
        raise A.ContasOcupadas("ocupado")
    monkeypatch.setattr(contas, "permissoes_do_grupo", ocupado)
    r = cli.get(f"/literatura/artigos/{_artigo_id(copia)}")
    assert r.status_code == 503 and "O banco de contas está ocupado. Tente de novo em alguns segundos." in r.text


def test_sem_autenticacao_nao_ha_mensagem_de_permissao(cli):
    c, copia = cli
    h = c.get(f"/literatura/artigos/{_artigo_id(copia)}").text
    assert MSG_ENTRAR not in h and MSG_GRUPO not in h            # autenticacao desligada: todas as permissoes, sem mensagem
