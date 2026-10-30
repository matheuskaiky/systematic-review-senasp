"""Metodologia publica sem os numeros do modelo (D145, Q-P8-4 b): para quem nao entrou, o texto gerado nao depende de nenhum
numero que venha do modelo (achados, classificacoes, artigos removidos pela triagem de escopo, UFs so classificadas); a secao
de classificacao automatica traz so o aviso "Resultados automatizados ainda não divulgados."; quem entrou e o painel sem login
veem o texto de antes."""
import copy

import pytest
from fastapi.testclient import TestClient

from apoio_divulgacao import gravar_politica
from dominio import divulgacao
from painel import metodologia_texto as MT
from painel.metodologia_texto import gerar_metodologia, para_texto
from test_autenticacao import _criar, _entrar
from test_divulgacao_acesso import _menu, _painel
from test_metodologia_texto import _fatos
from test_painel import demo  # noqa: F401

AVISO = "Resultados automatizados ainda não divulgados."

# cada numero que vem do modelo, com um valor diferente (caminho dentro dos fatos, novo valor)
DO_MODELO = [
    ("literatura.prisma.11", 7), ("literatura.prisma.12", 993), ("literatura.prisma.16", 3),
    ("literatura.triagem.pendentes", 77), ("literatura.triagem.total", 1001), ("literatura.triagem.ocultos_llm", 9),
    ("classificacao.provedores", ["outro"]), ("classificacao.run_ids", []), ("classificacao.n_so_snippet", 4),
    ("classificacao.n_historico", 5000), ("classificacao.n_invalidas", 3), ("classificacao.n_fora_vocabulario", 0),
    ("classificacao.classificadores", []),
    ("classificacao.classificadores", [{"classificador": "x:y", "prompt_versao": None, "n_classificacoes": 9, "n_json_valido": 8,
                                        "n_achados": 7, "n_evidencia_ok": 6},
                                       {"classificador": "x:z", "prompt_versao": "v9", "n_classificacoes": 1, "n_json_valido": 1,
                                        "n_achados": 1, "n_evidencia_ok": 1}]),
    ("achados.total", 999), ("achados.total", 50), ("achados.total", 0), ("achados.evidencia_ok", 1),
    ("achados.pendentes_sem_evidencia", 0),
    ("web.funil.classificacoes", 4321), ("web.funil.relevantes", 12), ("web.funil.achados", 999),
    ("ufs.uf_so_classificado", 0), ("ufs.uf_sem_achados", 1),
    ("municipal.n_achados", 12), ("municipal.n_cidades", 4), ("municipal.cidades", ["Teresina"]),
]


def _mudar(fatos, caminho, valor):
    f = copy.deepcopy(fatos)
    *meio, ultima = caminho.split(".")
    alvo = f
    for k in meio:
        alvo = alvo[k]
    alvo[int(ultima) if ultima.isdigit() else ultima] = valor
    return f


def _todos(fatos):
    f = fatos
    for caminho, valor in DO_MODELO:
        if caminho != "achados.total" or valor == 999:
            f = _mudar(f, caminho, valor)
    return f


def _publico(fatos):
    return gerar_metodologia(fatos, None, custos=False, modelo=False)


def _secao(res, id_):
    return next(s for s in res["secoes"] if s["id"] == id_)


def _textos(blocos):
    return [para_texto(b["seg"]) if b["tipo"] == "p" else [para_texto(i) for i in b["itens"]] for b in blocos]


# ---------------- funcao pura ----------------
def _variantes():
    f = _fatos()
    return {"completo": f, "sem_achados": _mudar(_mudar(f, "achados.total", 0), "classificacao.classificadores", []),
            "vies": {**f, "banco": "vies"}, "sem_artigos": _mudar(f, "literatura.n_artigos", 0), "vazio": {}}


@pytest.mark.parametrize("variante", ["completo", "sem_achados", "vies", "sem_artigos", "vazio"])
def test_quem_entrou_ve_o_texto_de_antes(variante):
    f = _variantes()[variante]
    for custos in (True, False):
        assert gerar_metodologia(f, None, custos=custos) == gerar_metodologia(f, None, custos=custos, modelo=True)


def test_o_estado_vazio_publico_nao_depende_dos_achados():
    """Sem execucoes, artigos nem buscas manuais, o texto publico e o de "nada coletado", com ou sem achados do modelo."""
    vazio = {"execucoes": [], "literatura": {"n_artigos": 0}, "manuais": []}
    com_achados = {**vazio, "achados": {"total": 5}}
    assert _publico(com_achados) == _publico(vazio)
    assert _publico(vazio)["vazio"] is True


def test_literatura_publica_sem_artigos_nao_fala_da_triagem():
    blocos = _textos(_secao(_publico(_mudar(_fatos(), "literatura.n_artigos", 0)), "literatura")["blocos"])
    assert blocos[-1] == ("Ao todo, 0 artigos únicos foram identificados (987 do Scholar; 55 das bases manuais; os dois conjuntos "
                          "podem se sobrepor).")


@pytest.mark.parametrize("caminho,valor", DO_MODELO)
def test_o_texto_publico_nao_depende_de_numero_do_modelo(caminho, valor):
    f = _fatos()
    assert _publico(_mudar(f, caminho, valor)) == _publico(f)


def test_o_texto_publico_nao_depende_de_todos_juntos_e_o_de_quem_entrou_sim():
    f = _fatos()
    assert _publico(_todos(f)) == _publico(f)
    assert gerar_metodologia(_todos(f), None, custos=False) != gerar_metodologia(f, None, custos=False)   # o teste enxerga a mudanca


def test_secao_de_classificacao_publica_so_com_o_aviso():
    for f in (_fatos(), _mudar(_fatos(), "classificacao.classificadores", [])):
        s = _secao(_publico(f), "classificacao")
        assert s["titulo"] == "Classificação automática"
        assert s["blocos"] == [{"tipo": "p", "seg": [(AVISO, None)]}]


def test_verificacao_publica_so_com_as_contagens_humanas():
    assert _textos(_secao(_publico(_fatos()), "verificacao")["blocos"]) == [
        "50 achados foram verificados por humano (2 revisores): 40 confirmados e 10 descartados como incorretos. "
        "Entre os verificados, a taxa de confirmação foi de 80,0%.",
        "Somente achados verificados e não descartados contam como achado confirmado; o status final é o decidido pela pessoa que "
        "verificou, que pode diferir do status reportado pelo modelo.",
    ]


def test_verificacao_publica_no_singular_e_sem_verificados():
    f = _mudar(_mudar(_mudar(_mudar(_fatos(), "achados.verificados", 1), "achados.confirmados", 1), "achados.descartados", 0),
               "achados.n_revisores", 1)
    assert _textos(_secao(_publico(f), "verificacao")["blocos"])[0] == (
        "1 achado foi verificado por humano (1 revisor): 1 confirmados e 0 descartados como incorretos. "
        "Entre os verificados, a taxa de confirmação foi de 100,0%.")
    f = _mudar(_mudar(_mudar(_mudar(_fatos(), "achados.verificados", 0), "achados.confirmados", 0), "achados.descartados", 0),
               "achados.n_revisores", 0)
    assert _textos(_secao(_publico(f), "verificacao")["blocos"])[0] == (
        "0 achados foram verificados por humano: 0 confirmados e 0 descartados como incorretos.")


def test_ufs_publicas_so_com_as_confirmadas():
    publico = _textos(_secao(_publico(_fatos()), "ufs")["blocos"])
    de_quem_entrou = _textos(_secao(gerar_metodologia(_fatos(), None, custos=False), "ufs")["blocos"])
    assert publico[0] == "Considerando apenas achados confirmados por humano, 9 de 27 UFs têm ao menos um achado confirmado (PI, CE)."
    assert publico[1] == de_quem_entrou[1]                                   # confirmados por tecnologia: decisao humana
    assert publico[2] == "Escopo municipal: 0 achados confirmados em secretarias municipais."
    f = _mudar(_mudar(_mudar(_fatos(), "municipal.n_confirmados", 1), "municipal.n_achados", 5), "municipal.n_cidades", 2)
    assert _textos(_secao(_publico(f), "ufs")["blocos"])[2] == "Escopo municipal: 1 achado confirmado em secretarias municipais."
    f = _mudar(_fatos(), "ufs.confirmadas", [])
    assert _textos(_secao(_publico(_mudar(f, "ufs.uf_confirmada", 0)), "ufs")["blocos"])[0] == (
        "Considerando apenas achados confirmados por humano, 0 de 27 UFs têm ao menos um achado confirmado.")


def test_literatura_publica_sem_removidos_nem_pendentes():
    blocos = _textos(_secao(_publico(_fatos()), "literatura")["blocos"])
    de_quem_entrou = _textos(_secao(gerar_metodologia(_fatos(), None, custos=False), "literatura")["blocos"])
    assert blocos[:-1] == de_quem_entrou[:-1]                                # busca, termos e bases: coleta
    assert blocos[-1] == ("Ao todo, 1.000 artigos únicos foram identificados (987 do Scholar; 55 das bases manuais; os dois conjuntos "
                          "podem se sobrepor). Na triagem por título e resumo, 500 foram avaliados: 140 incluídos e 360 excluídos. "
                          "Incluídos no estudo após a leitura do texto completo: 33.")


def test_as_outras_secoes_nao_mudam_para_o_publico():
    publico, de_quem_entrou = _publico(_fatos()), gerar_metodologia(_fatos(), None, custos=False)
    assert [s["id"] for s in publico["secoes"]] == [s["id"] for s in de_quem_entrou["secoes"]]
    for id_ in ("web", "reprodutibilidade"):
        assert _secao(publico, id_) == _secao(de_quem_entrou, id_), id_


MARCAS_DO_MODELO = ("verificado", "Não há nenhum achado", "Nenhuma classificação", "A triagem está incompleta",
                    "combinações de classificador", "versão do prompt", "snippet", "sem JSON válido")


@pytest.mark.parametrize("variante", ["completo", "sem_verificacao", "com_tudo", "sem_achados"])
def test_ressalvas_publicas_sem_as_que_dependem_do_modelo(variante):
    f = _fatos()
    if variante == "sem_verificacao":
        f = _mudar(f, "achados.verificados", 0)
    elif variante == "com_tudo":
        f = _todos(f)
    elif variante == "sem_achados":
        f = _mudar(_mudar(f, "achados.total", 0), "classificacao.classificadores", [])
    publico = [para_texto(r) for r in _publico(f)["ressalvas"]]
    de_quem_entrou = [para_texto(r) for r in gerar_metodologia(f, None, custos=False)["ressalvas"]]
    assert publico == [r for r in de_quem_entrou if not any(m in r for m in MARCAS_DO_MODELO)]
    assert len(publico) < len(de_quem_entrou)


def test_o_texto_para_copiar_e_o_do_publico():
    res = _publico(_fatos())
    assert res["texto"] == MT._texto_puro(res["secoes"], res["ressalvas"])


# ---------------- rota ----------------
def test_metodologia_entra_na_lista_publica():
    assert "/metodologia" in divulgacao.ROTAS_PUBLICAS


def _espiar(monkeypatch):
    chamadas = []
    original = MT.gerar_metodologia

    def espia(*a, **k):
        chamadas.append(k.get("modelo", True))
        return original(*a, **k)
    monkeypatch.setattr(MT, "gerar_metodologia", espia)
    return chamadas


@pytest.mark.parametrize("banco", ["real", "vies"])
def test_visitante_recebe_o_texto_publico(demo, tmp_path, monkeypatch, banco):  # noqa: F811
    chamadas = _espiar(monkeypatch)
    app, contas, contas_db, _ = _painel(demo, tmp_path, banco=banco)
    gravar_politica(contas, banco)
    r = TestClient(app).get("/metodologia", follow_redirects=False)
    assert r.status_code == 200 and AVISO in r.text
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    assert leitor.get("/metodologia").status_code == 200
    assert chamadas == [False, True]


def test_sem_login_o_texto_e_o_de_antes(demo, tmp_path, monkeypatch):  # noqa: F811
    chamadas = _espiar(monkeypatch)
    app, _, _, _ = _painel(demo, tmp_path, autenticacao=False)
    assert TestClient(app).get("/metodologia").status_code == 200
    assert chamadas == [True]


def test_a_pagina_do_visitante_nao_depende_dos_numeros_do_modelo(demo, tmp_path, monkeypatch):  # noqa: F811
    """A pagina inteira (incluindo o texto para copiar, embutido num atributo) e a mesma com os fatos do modelo mudados."""
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    original = LeituraPainelSQLite.fatos_metodologia
    app, contas, contas_db, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    paginas, do_leitor = [], []
    for mudar in (False, True):
        monkeypatch.setattr(LeituraPainelSQLite, "fatos_metodologia",
                            (lambda self, n=27: _todos(original(self, n))) if mudar else original)
        r = TestClient(app).get("/metodologia", follow_redirects=False)
        assert r.status_code == 200
        paginas.append(r.content)
        do_leitor.append(leitor.get("/metodologia").content)
    assert paginas[0] == paginas[1]
    assert do_leitor[0] != do_leitor[1]


def test_menu_do_visitante_com_a_metodologia(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    assert "/metodologia" in _menu(TestClient(app).get("/").text)


def test_os_links_da_metodologia_do_visitante_so_levam_a_paginas_abertas(demo, tmp_path):  # noqa: F811
    import re
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    h = TestClient(app).get("/metodologia").text
    corpo = h[h.index('<main id="conteudo"'):]
    links = {re.sub(r"[?#].*", "", x) for x in re.findall(r'href="(/[^"]*)"', corpo)}
    assert links <= {"/", "/sobre", "/literatura/prisma", "/metodologia", "/entrar"}, links


@pytest.mark.parametrize("estado", [None, False])
def test_sem_divulgacao_a_metodologia_vai_para_a_entrada(demo, tmp_path, estado):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    if estado is not None:
        gravar_politica(contas, "real", publica=estado)
    r = TestClient(app).get("/metodologia", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fmetodologia"
