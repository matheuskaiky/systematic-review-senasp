"""Prontidao metodologica: constantes identicas as dos scripts de `analises/`, funcoes puras, leitura contra bancos montados a mao
(zero verificados, parcial, destravado, logica da classe minoritaria), bloco do painel e cartoes na pagina inicial e em /analises."""
import ast
import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import painel_demo
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from dados_rotulagem import construir
from dominio import prontidao as P
from dominio.auditoria_negativos import amostra_minima_sem_erros
from painel import analises_blocos as b
from test_painel import _app

RAIZ = Path(__file__).resolve().parent.parent


def _constantes(script):
    """Constantes inteiras MAIUSCULAS de nivel de modulo de um script de analises/, lidas pela arvore sintatica (sem importar numpy)."""
    arvore = ast.parse((RAIZ / "analises" / script).read_text(encoding="utf-8"))
    return {n.targets[0].id: n.value.value for n in arvore.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, int) and n.targets[0].id.isupper()}


def test_constantes_sao_identicas_as_dos_scripts():
    h2, h5 = _constantes("h2_logistica.py"), _constantes("h5_bibliometria.py")
    assert (P.H2_MIN_VERIFICADOS, P.H2_MIN_CLASSE_RARA) == (h2["MIN_VERIFICADOS"], h2["MIN_CLASSE_RARA"]) == (200, 40)
    assert (P.H5_MIN_DECISOES, P.H5_MIN_POR_GRUPO) == (h5["MIN_DECISOES"], h5["MIN_POR_GRUPO"]) == (50, 10)


@pytest.mark.local          # le analises/README.md, que fica fora do git
def test_textos_dos_scripts_citam_os_mesmos_numeros():
    """As mensagens e a documentacao dos scripts dizem os numeros que o codigo usa."""
    leia = (RAIZ / "analises" / "README.md").read_text(encoding="utf-8")
    assert "menos de 200 achados verificados ou menos de 40" in leia and "menos de 50 decisões humanas" in leia
    assert re.search(r"menos de 10 em um dos grupos", leia)


def test_minimo_da_auditoria_e_calculado_nao_fixo():
    assert P.minimo_auditoria() == amostra_minima_sem_erros(P.META_AUDITORIA) == 59
    assert P.minimo_auditoria(0.02) == 149


def test_progresso():
    p = P.progresso(50, 200, "x")
    assert p == {"rotulo": "x", "n": 50, "minimo": 200, "faltam": 150, "destravado": False, "fracao": 0.25}
    assert P.progresso(250, 200)["faltam"] == 0 and P.progresso(250, 200)["fracao"] == 1.0 and P.progresso(250, 200)["destravado"]
    assert P.progresso(None, 10)["n"] == 0 and P.progresso(-3, 10)["n"] == 0


def test_h2_classe_minoritaria_e_o_menor_entre_confirmados_e_descartados():
    zero = P.prontidao_h2(0, 0)
    assert not zero["destravado"] and zero["faltam"] == 200
    assert P.prontidao_h2(190, 10)["faltam"] == 30 and not P.prontidao_h2(190, 10)["destravado"]      # total ok? 200 sim, minoritaria 10 de 40
    assert P.prontidao_h2(10, 190)["condicoes"][1]["n"] == 10                                         # simetrico
    assert P.prontidao_h2(160, 40)["destravado"] and P.prontidao_h2(160, 40)["faltam"] == 0
    assert not P.prontidao_h2(160, 39)["destravado"] and P.prontidao_h2(160, 39)["faltam"] == 1
    assert P.prontidao_h2(300, 5)["faltam"] == 35 and not P.prontidao_h2(300, 5)["destravado"]
    # um achado pode contar nas duas condicoes: faltam o MAIOR dos dois, nao a soma
    assert P.prontidao_h2(20, 20)["faltam"] == 160


def test_h5_e_auditoria():
    assert P.prontidao_h5(0, 0)["faltam"] == 50 and not P.prontidao_h5(0, 0)["destravado"]
    assert P.prontidao_h5(45, 0)["faltam"] == 10 and not P.prontidao_h5(45, 0)["destravado"]
    assert P.prontidao_h5(40, 10)["destravado"] and not P.prontidao_h5(41, 8)["destravado"]
    a = P.prontidao_auditoria(0, 316)
    assert a["condicoes"][0]["minimo"] == 59 and a["faltam"] == 59 and a["n_universo"] == 316 and not a["destravado"]
    assert P.prontidao_auditoria(59, 316)["destravado"]
    assert not P.prontidao_auditoria(80, 316, n_perdidas=1)["destravado"]                              # achou uma: a meta nao esta provada


# ============================== leitura: bancos montados a mao ==============================
def _leitura(tmp_path, **kw):
    return LeituraPainelSQLite(construir(tmp_path / "p.db", **kw)).analise_prontidao()


def test_banco_vazio_tudo_travado(tmp_path):
    r = _leitura(tmp_path)
    json.dumps(r)
    assert not r["h2"]["destravado"] and not r["h5"]["destravado"] and not r["auditoria"]["destravado"]
    assert r["h2"]["faltam"] == 200 and r["h5"]["faltam"] == 50 and r["auditoria"]["faltam"] == 59


def test_zero_verificados_com_dados(tmp_path):
    r = _leitura(tmp_path, n_achados=30, n_artigos=10, n_negativos=5)
    assert r["h2"]["condicoes"][0]["n"] == 0 and r["h5"]["condicoes"][0]["n"] == 0
    assert r["auditoria"]["n_universo"] == 5 and r["auditoria"]["condicoes"][0]["n"] == 0


def test_parcial_conta_classe_minoritaria_e_decisoes(tmp_path):
    ver = [(i, "descartado" if i < 3 else "em_uso") for i in range(30)]                          # 3 descartados, 27 confirmados
    dec = [(i, "incluir" if i < 2 else "excluir") for i in range(12)]                             # 2 incluir, 10 excluir
    r = _leitura(tmp_path, n_achados=40, n_artigos=15, verificados=ver, decisoes=dec)
    h2, h5 = r["h2"], r["h5"]
    assert (h2["n_confirmados"], h2["n_descartados"]) == (27, 3) and h2["condicoes"][0]["n"] == 30 and h2["condicoes"][1]["n"] == 3
    assert h2["faltam"] == 170 and not h2["destravado"]
    assert (h5["n_incluir"], h5["n_excluir"]) == (2, 10) and h5["condicoes"][0]["n"] == 12 and h5["condicoes"][1]["n"] == 2
    assert h5["faltam"] == 38 and not h5["destravado"]


def test_destravado_com_os_minimos_exatos(tmp_path):
    ver = [(i, "descartado" if i < 40 else "piloto") for i in range(200)]
    dec = [(i, "incluir" if i < 10 else "excluir") for i in range(50)]
    r = _leitura(tmp_path, n_achados=200, n_artigos=50, n_negativos=59, verificados=ver, decisoes=dec)
    assert r["h2"]["destravado"] and r["h5"]["destravado"] and r["h2"]["faltam"] == 0 and r["h5"]["faltam"] == 0
    assert not r["auditoria"]["destravado"] and r["auditoria"]["n_universo"] == 59


def test_um_a_menos_nao_destrava(tmp_path):
    ver = [(i, "descartado" if i < 39 else "piloto") for i in range(200)]
    dec = [(i, "incluir" if i < 9 else "excluir") for i in range(50)]
    r = _leitura(tmp_path, n_achados=200, n_artigos=50, verificados=ver, decisoes=dec)
    assert not r["h2"]["destravado"] and r["h2"]["faltam"] == 1
    assert not r["h5"]["destravado"] and r["h5"]["faltam"] == 1


def test_h2_so_conta_achados_com_os_tres_preditores(tmp_path):
    caminho = construir(tmp_path / "s.db", n_achados=10, verificados=[(i, "em_uso") for i in range(10)])
    c = sqlite3.connect(caminho)
    c.execute("UPDATE achados SET evidencia_confere = NULL WHERE achado_id IN (1, 2)")     # a regressao nao usa estes
    c.commit()
    c.close()
    h2 = LeituraPainelSQLite(caminho).analise_prontidao()["h2"]
    assert h2["n_confirmados"] == 8 and h2["n_verificados_total"] == 10 and h2["n_sem_preditor"] == 2


def test_descartado_com_texto_em_maiusculas_nao_e_confirmado(tmp_path):
    """Descartado so vale com o texto exato `descartado` (o mesmo que o script usa); o banco guarda o valor normalizado."""
    r = _leitura(tmp_path, n_achados=3, verificados=[(0, "descartado"), (1, "em_uso"), (2, "piloto")])
    assert (r["h2"]["n_confirmados"], r["h2"]["n_descartados"]) == (2, 1)


# ============================== bloco e paginas ==============================
def test_bloco_prontidao_textos_e_barras(tmp_path):
    ver = [(i, "descartado" if i < 5 else "em_uso") for i in range(20)]
    dec = [(i, "incluir" if i < 3 else "excluir") for i in range(8)]
    d = _leitura(tmp_path, n_achados=20, n_artigos=8, n_negativos=70, verificados=ver, decisoes=dec)
    bl = b.bloco_prontidao(d)
    por = {c["id"]: c for c in bl["cartoes"]}
    assert bl["titulo"] == "3 de 3 análises ainda dependem de rotulagem humana"
    assert por["h2"]["condicao"].startswith("20 achados verificados de 200 necessários; classe minoritária 5 de 40 necessários")
    assert por["h5"]["condicao"].startswith("8 artigos com decisão de triagem de 50; 3 incluídos e 5 excluídos (mínimo 10 de cada)")
    assert por["auditoria"]["condicao"] == "0 páginas negativas auditadas de 59, do universo de 70."
    assert por["h2"]["status"] == "faltam 180" and por["h2"]["href"] == "/revisao/achados"
    assert por["h5"]["href"] == "/literatura/triagem" and "auditoria-negativos-modelo" in por["auditoria"]["comando"]
    barra = str(por["h2"]["condicoes"][0]["barra"])
    assert 'class="barra-progresso"' in barra and 'role="img"' in barra and "<desc>" in barra and "20 / 200" in barra and "style=" not in barra
    assert por["h2"]["condicoes"][0]["texto"] == "20 / 200"


def test_bloco_destravado_e_aviso_de_aplicacao_perdida():
    h2, h5 = P.prontidao_h2(160, 40), P.prontidao_h5(10, 40)
    ok = b.bloco_prontidao({"h2": h2, "h5": h5, "auditoria": P.prontidao_auditoria(59, 316)})
    assert ok["titulo"].startswith("Os três mínimos") and all(c["status"] == "destravado" for c in ok["cartoes"])
    assert 'class="be-conf"' in str(ok["cartoes"][0]["condicoes"][0]["barra"])
    perdida = b.bloco_prontidao({"h2": h2, "h5": h5, "auditoria": P.prontidao_auditoria(80, 316, n_perdidas=1)})
    assert "meta não provada" in perdida["cartoes"][2]["status"]
    vazio = b.bloco_prontidao({})            # nunca levanta
    assert len(vazio["cartoes"]) == 3


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("demo_prontidao")
    return painel_demo.construir(pasta), pasta / "raw_demo"


def _cliente(banco, raw, tmp_path):
    copia = tmp_path / "d.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path, somente_leitura=True)
    return TestClient(app)


def test_cartao_na_pagina_inicial_e_primeiro_bloco_da_visao(demo, tmp_path):
    cliente = _cliente(*demo, tmp_path)
    visao = cliente.get("/analises?secao=visao")
    assert visao.status_code == 200
    html = visao.text
    assert html.index('id="prontidao"') < html.index('id="hipoteses"')
    for texto in ("H2: regressão logística", "H5: citações e posição", "Auditoria dos negativos do modelo", 'class="barra-progresso"',
                  "/revisao/achados", "/literatura/triagem", "auditoria-negativos-modelo --amostra 59"):
        assert texto in html, texto
    assert " style=" not in html
    home = cliente.get("/")
    assert home.status_code == 200 and "Prontidão metodológica" in home.text and 'class="barra-progresso"' in home.text
    assert home.text.count('class="barra-progresso"') == 5 and " style=" not in home.text


def test_pagina_inicial_com_banco_vazio_mostra_o_cartao(tmp_path):
    RepositorioSQLite(tmp_path / "v.db").fechar()
    app, _ = _app(tmp_path / "v.db", tmp_path / "raw", tmp_path, somente_leitura=True)
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "Prontidão metodológica" in r.text and "0 / 200" in r.text
