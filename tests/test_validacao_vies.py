"""Validação humana da triagem do banco `vies` por amostra: o sorteio estratificado, a resposta da pessoa sem ver a do
modelo, a concordância, a gravação e a página do painel (só no banco `vies`)."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, triagem_escopo as TE, vocabulario as V
from config.eixos_tematicos import EIXOS_EXPLORACAO
from dominio import analises_vies as AV, validacao_vies as VV
from painel import navegacao
from painel.app import Contexto, criar_app
from test_triagem_vies import construir_vies
from test_triagem_vies_painel import _linha, _triar

EIXOS = tuple(EIXOS_EXPLORACAO)
UM_EIXO = EIXOS[0]


# ---------- alocacao ----------
@pytest.mark.parametrize("tamanhos, esperado", [
    ({"alta": 260, "media": 107, "baixa": 3, "fora_do_escopo": 25}, {"alta": 21, "media": 11, "baixa": 3, "fora_do_escopo": 5}),
    ({"alta": 10, "media": 10, "baixa": 10, "fora_do_escopo": 10}, {"alta": 10, "media": 10, "baixa": 10, "fora_do_escopo": 10}),
    ({"alta": 30, "media": 0, "baixa": 2, "fora_do_escopo": 20}, {"alta": 23, "baixa": 2, "fora_do_escopo": 15}),
    ({"alta": 5, "media": 5}, {"alta": 5, "media": 5}),                       # menos itens que a amostra: todos
    ({"alta": 41}, {"alta": 40}),
    ({"alta": 21, "media": 20}, {"alta": 20, "media": 20}),                   # maior resto vai para a media (0,52 > 0,48)
    ({"alta": 100, "media": 100, "baixa": 100, "fora_do_escopo": 1}, {"alta": 13, "media": 13, "baixa": 13, "fora_do_escopo": 1}),
    ({}, {}), ({"alta": 0}, {}),
])
def test_alocacao(tamanhos, esperado):
    assert VV.alocacao(tamanhos) == esperado
    assert sum(esperado.values()) == min(40, sum(tamanhos.values()))


# ---------- sorteio ----------
def _item(i, fonte="W", relevancia="alta", tipo="Artigo científico", pais="Brasil", eixo=UM_EIXO):
    return {"id": f"{fonte}-{i}", "relevancia": relevancia, "tipo_fonte": tipo, "pais": pais, "eixo": eixo}


def _triagens(itens):
    return {(VV.FONTES[i["id"][0]], int(i["id"][2:])): {"id": 1000 + k} for k, i in enumerate(itens)}


def test_sorteio_e_reprodutivel_estratificado_e_misturado():
    itens = ([_item(i) for i in range(1, 61)] + [_item(i, "A", "media") for i in range(1, 21)]
             + [_item(i, "W", "fora_do_escopo") for i in range(61, 64)] + [_item(i, relevancia=None) for i in range(64, 70)])
    a = VV.sortear(itens, _triagens(itens), EIXOS)
    assert a == VV.sortear(list(reversed(itens)), _triagens(itens), EIXOS)
    assert [l["ordem"] for l in a] == list(range(1, 41))
    contagem = {r: sum(1 for l in a if l["estrato"] == r) for r in ("alta", "media", "fora_do_escopo")}
    assert contagem == VV.alocacao({"alta": 60, "media": 20, "baixa": 0, "fora_do_escopo": 3})
    assert [l["estrato"] for l in a] != sorted((l["estrato"] for l in a), key=AV.RELEVANCIAS.index)  # nao vem em blocos
    assert {l["estrato_tamanho"] for l in a if l["estrato"] == "alta"} == {60}
    assert all(l["modelo_relevancia"] == l["estrato"] for l in a)


def test_sorteio_so_com_triagem_valida_tipo_de_fonte_e_linha_da_triagem():
    itens = [_item(1), _item(2, relevancia=None), _item(3), _item(4, tipo=None), _item(5, tipo="")]
    triagens = {("referencia", 1): {"id": 7}, ("referencia", 4): {"id": 8}, ("referencia", 5): {"id": 9}}
    assert [(l["fonte"], l["item_id"], l["triagem_id"]) for l in VV.sortear(itens, triagens, EIXOS)] == [("referencia", 1, 7)]
    assert VV.sortear([], {}, EIXOS) == []


@pytest.mark.parametrize("item, esperado", [
    (_item(1), {"relevancia": "alta", "grupo": AV.GRUPO_CIENTIFICA, "eixo": UM_EIXO, "pais": "brasil"}),
    (_item(1, tipo="Relatório técnico / literatura cinzenta", pais="Brasil / EUA", eixo=None),
     {"relevancia": "alta", "grupo": AV.GRUPO_CINZENTA, "eixo": "nenhum", "pais": "brasil"}),
    (_item(1, tipo="Lei / fonte primária", pais="EUA", eixo="eixo_que_nao_existe"),
     {"relevancia": "alta", "grupo": AV.GRUPO_PRIMARIA, "eixo": "nenhum", "pais": "outro"}),
    (_item(1, pais=None), {"relevancia": "alta", "grupo": AV.GRUPO_CIENTIFICA, "eixo": UM_EIXO, "pais": "indeterminado"}),
    (_item(1, pais=" indeterminado "), {"relevancia": "alta", "grupo": AV.GRUPO_CIENTIFICA, "eixo": UM_EIXO, "pais": "indeterminado"}),
])
def test_resposta_do_modelo_no_vocabulario_da_validacao(item, esperado):
    assert VV.respostas_do_modelo(item, EIXOS) == esperado


@pytest.mark.parametrize("pais, categoria", [
    ("Brasil", "brasil"), ("brasil", "brasil"), ("Brasil / São Paulo", "brasil"), ("EUA / Brasil", "brasil"), ("EUA", "outro"),
    ("Brasileiro", "outro"), ("", "indeterminado"), (None, "indeterminado"), ("Indeterminado", "indeterminado"),
    ("  INDETERMINADO ", "indeterminado"),
])
def test_categoria_do_pais(pais, categoria):
    assert AV.categoria_pais(pais) == categoria


# ---------- resposta ----------
VALIDA = {"relevancia": "media", "grupo": AV.GRUPO_CINZENTA, "eixo": "nenhum", "pais": "outro"}


@pytest.mark.parametrize("mudanca, erros", [
    ({}, []),
    ({"relevancia": " media "}, ["Opção inválida em relevância."]),         # vem de uma lista de escolha: nada e aparado
    ({"relevancia": ""}, ["Escolha a opção de relevância."]),
    ({"relevancia": "   "}, ["Escolha a opção de relevância."]),
    ({"relevancia": None}, ["Escolha a opção de relevância."]),
    ({"relevancia": ["media"]}, ["Escolha a opção de relevância."]),
    ({"relevancia": "Media"}, ["Opção inválida em relevância."]),
    ({"grupo": "outro"}, ["Opção inválida em tipo de fonte."]),
    ({"eixo": "Nenhum"}, ["Opção inválida em eixo temático."]),
    ({"pais": "Brasil"}, ["Opção inválida em país."]),
    ({"pais": "", "relevancia": "x", "eixo": ""},
     ["Opção inválida em relevância.", "Escolha a opção de eixo temático.", "Escolha a opção de país."]),
])
def test_conferir_resposta(mudanca, erros):
    limpa, achados = VV.conferir_resposta({**VALIDA, **mudanca}, EIXOS)
    assert achados == erros
    if not erros:
        assert limpa == VALIDA


def test_campo_ausente_e_obrigatorio():
    assert VV.conferir_resposta({}, EIXOS)[1] == ["Escolha a opção de relevância.", "Escolha a opção de tipo de fonte.",
                                                  "Escolha a opção de eixo temático.", "Escolha a opção de país."]


# ---------- concordancia ----------
def _resp(estrato, tamanho, modelo, pessoa):
    l = {"estrato": estrato, "estrato_tamanho": tamanho}
    l.update({f"modelo_{c}": v for c, v in zip(VV.CAMPOS, modelo)})
    l.update(dict(zip(VV.CAMPOS, pessoa)) if pessoa else {c: None for c in VV.CAMPOS})
    return l


def test_concordancia_por_campo_e_elegibilidade_pesada_pelo_estrato():
    g = AV.GRUPO_CIENTIFICA
    linhas = [_resp("alta", 90, ("alta", g, "nenhum", "brasil"), ("alta", g, "nenhum", "brasil")),
              _resp("alta", 90, ("alta", g, "nenhum", "brasil"), ("media", g, "nenhum", "outro")),
              _resp("fora_do_escopo", 10, ("fora_do_escopo", g, "nenhum", "outro"), ("alta", g, "nenhum", "outro")),
              _resp("fora_do_escopo", 10, ("fora_do_escopo", g, "nenhum", "outro"), ("fora_do_escopo", g, "nenhum", "outro")),
              _resp("alta", 90, ("alta", g, "nenhum", "brasil"), None)]                    # sem resposta: fica de fora
    r = VV.concordancia(linhas, EIXOS)
    assert (r["relevancia"]["n"], r["relevancia"]["iguais"]) == (4, 2)
    assert (r["elegivel"]["n"], r["elegivel"]["iguais"]) == (4, 3)
    assert (r["pais"]["iguais"], r["grupo"]["iguais"]) == (3, 4)
    assert r["elegivel_estimada"] == pytest.approx((90 * 1.0 + 10 * 0.5) / 100)
    assert r["grupo"]["kappa"]["kappa"] is None and r["grupo"]["faixa"] is None     # sem variacao: kappa nao definido
    assert r["pais"]["kappa"]["kappa"] == pytest.approx(0.5)


def test_estimativa_so_com_todos_os_estratos_respondidos():
    g = AV.GRUPO_CIENTIFICA
    linhas = [_resp("alta", 90, ("alta", g, "nenhum", "brasil"), ("alta", g, "nenhum", "brasil")),
              _resp("fora_do_escopo", 10, ("fora_do_escopo", g, "nenhum", "outro"), None)]
    assert VV.concordancia(linhas, EIXOS)["elegivel_estimada"] is None


def test_eixo_fora_das_opcoes_vira_categoria_propria():
    g = AV.GRUPO_CIENTIFICA
    r = VV.concordancia([_resp("alta", 9, ("alta", g, "eixo_antigo", "brasil"), ("alta", g, "nenhum", "brasil"))], EIXOS)
    assert r["eixo"]["categorias"][-1] == "eixo_antigo" and r["eixo"]["iguais"] == 0


def test_concordancia_sem_respostas():
    r = VV.concordancia([_resp("alta", 9, ("alta", AV.GRUPO_CIENTIFICA, "nenhum", "brasil"), None)], EIXOS)
    assert r["relevancia"]["n"] == 0 and r["relevancia"]["kappa"]["kappa"] is None and r["elegivel_estimada"] is None


# ---------- gravacao ----------
@pytest.fixture
def banco(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    con = sqlite3.connect(tmp_path / "busca.db")
    refs = [r[0] for r in con.execute("SELECT referencia_id FROM referencias_web ORDER BY 1")]
    arts = [r[0] for r in con.execute("SELECT artigo_id FROM artigos ORDER BY 1")]
    _triar(tmp_path / "busca.db", [_linha("referencia", i) for i in refs] + [_linha("artigo", i, status_bruto="fora_do_escopo",
                                                                                         status="excluido") for i in arts])
    return tmp_path / "busca.db"


def _amostra(banco):
    leitura = LeituraPainelSQLite(banco)
    ctx = _contexto("vies")
    from painel import visao_geral_vies
    return VV.sortear(visao_geral_vies.itens(leitura, ctx), leitura.triagens_vies(ctx.versao_triagem_vies), EIXOS)


def _gravar(banco, acao):
    repo = RepositorioSQLite(banco)
    try:
        return acao(repo)
    finally:
        repo.fechar()


def _linhas(banco):
    return sqlite3.connect(banco).execute("SELECT * FROM validacao_vies ORDER BY ordem").fetchall()


def test_sorteio_grava_uma_vez_e_nunca_troca(banco):
    amostra = _amostra(banco)
    assert len(amostra) == 5
    _gravar(banco, lambda r: r.sortear_validacao_vies(amostra))
    antes = _linhas(banco)
    with pytest.raises(SystemExit) as e:
        _gravar(banco, lambda r: r.sortear_validacao_vies(amostra))
    assert str(e.value) == "A amostra da validação já foi sorteada." and _linhas(banco) == antes


def test_sorteio_vazio_e_recusado(banco):
    with pytest.raises(SystemExit) as e:
        _gravar(banco, lambda r: r.sortear_validacao_vies([]))
    assert str(e.value) == "Nenhum item com triagem válida do modelo para sortear." and _linhas(banco) == []


def test_resposta_grava_e_a_mesma_resposta_nao_muda_nada(banco):
    _gravar(banco, lambda r: r.sortear_validacao_vies(_amostra(banco)))
    _gravar(banco, lambda r: r.responder_validacao_vies(1, VALIDA, " Ana "))
    um = sqlite3.connect(banco).execute("SELECT relevancia, grupo, eixo, pais, revisor, respondido_em FROM validacao_vies WHERE ordem=1").fetchone()
    assert um[:5] == ("media", AV.GRUPO_CINZENTA, "nenhum", "outro", "Ana") and um[5]
    _gravar(banco, lambda r: r.responder_validacao_vies(1, VALIDA, "Ana"))
    assert sqlite3.connect(banco).execute("SELECT respondido_em FROM validacao_vies WHERE ordem=1").fetchone()[0] == um[5]
    for ordem, revisor, msg in ((99, "Ana", "Item da validação inexistente: 99"), (1, "  ", "Informe o nome do revisor")):
        with pytest.raises(SystemExit) as e:
            _gravar(banco, lambda r: r.responder_validacao_vies(ordem, VALIDA, revisor))
        assert str(e.value) == msg


def test_uma_pessoa_so_responde_e_a_amostra_completa_congela(banco):
    _gravar(banco, lambda r: r.sortear_validacao_vies(_amostra(banco)))
    _gravar(banco, lambda r: r.responder_validacao_vies(2, VALIDA, "Ana"))
    with pytest.raises(SystemExit) as e:
        _gravar(banco, lambda r: r.responder_validacao_vies(1, VALIDA, "Beto"))
    assert str(e.value) == "Esta amostra já está sendo respondida por outra pessoa: só ela responde."
    for ordem in (1, 3, 4, 5):
        _gravar(banco, lambda r: r.responder_validacao_vies(ordem, VALIDA, "Ana"))
    antes = _linhas(banco)
    with pytest.raises(SystemExit) as e:
        _gravar(banco, lambda r: r.responder_validacao_vies(1, {**VALIDA, "relevancia": "alta"}, "Ana"))
    assert str(e.value) == "A validação já foi concluída: as respostas não mudam mais." and _linhas(banco) == antes


def test_titulo_da_referencia_vem_da_ocorrencia_mais_recente_pelo_horario_da_chamada(banco):
    con = sqlite3.connect(banco)
    ref = con.execute("SELECT MIN(referencia_id) FROM referencias_web").fetchone()[0]
    o = con.execute("SELECT ocorrencia_id, chamada_id FROM ocorrencias_web WHERE referencia_id=? ORDER BY ocorrencia_id", (ref,)).fetchall()
    run = con.execute("SELECT run_id FROM chamadas WHERE chamada_id=?", (o[0][1],)).fetchone()[0]
    cols = [c[1] for c in con.execute("PRAGMA table_info(chamadas)") if c[1] not in ("chamada_id", "requisitado_em", "chave_idempotencia")]
    nova = con.execute(f"INSERT INTO chamadas ({', '.join(cols)}, requisitado_em, chave_idempotencia) SELECT {', '.join(cols)}, "
                       "'1999-01-01T00:00:00', 'antiga' FROM chamadas WHERE chamada_id = ?", (o[0][1],)).lastrowid
    con.execute("INSERT INTO ocorrencias_web (chamada_id, run_id, conjunto, consulta_id, referencia_id, titulo, snippet) "
                "VALUES (?, ?, 'A', 'LA1', ?, 'Título antigo', 'trecho antigo')", (nova, run, ref))
    con.commit()
    _gravar(banco, lambda r: r.sortear_validacao_vies(_amostra(banco)))
    linha = next(l for l in LeituraPainelSQLite(banco).linhas_validacao_vies() if l["fonte"] == "referencia" and l["item_id"] == ref)
    assert linha["titulo"] != "Título antigo" and linha["trecho"] != "trecho antigo"


def test_leitura_sem_a_tabela_devolve_lista_vazia(tmp_path):
    sqlite3.connect(tmp_path / "x.db").execute("CREATE TABLE t (a)")
    assert LeituraPainelSQLite(tmp_path / "x.db").linhas_validacao_vies() == []


# ---------- painel ----------
def _contexto(nome, somente_leitura=False, tmp=None):
    return Contexto(banco=nome, nome_banco="busca.db", somente_leitura=somente_leitura, pasta_backup=(tmp or S.DATA_DIR) / "b",
                    ufs=dict(C.UFS), status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS),
                    hosts_permitidos=("testserver",), termos={t.id: t.query for t in S.termos_do_banco(nome)},
                    conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                    consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                    eixos_exploracao=dict(EIXOS_EXPLORACAO), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO)


def _cli(banco, tmp_path, nome="vies", somente_leitura=False):
    cli = TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path),
                               _contexto(nome, somente_leitura, tmp_path)))
    cli.get("/")
    return cli


def _post(cli, rota, **dados):
    return cli.post(rota, data={"csrf": cli.cookies.get("csrf"), **dados}, headers={"Origin": "http://testserver"},
                    follow_redirects=False)


def test_so_no_banco_vies_e_so_no_menu_do_vies(banco, tmp_path):
    real = _cli(banco, tmp_path, nome="real")
    assert real.get("/validacao").status_code == 404 and real.get("/validacao/1").status_code == 404
    assert _post(real, "/validacao/sortear").status_code == 404
    assert 'href="/validacao"' not in real.get("/").text
    assert 'href="/validacao"' in _cli(banco, tmp_path).get("/").text
    assert "/validacao" in navegacao.enderecos() and navegacao.SO_VIES == {"/validacao"}


def test_fluxo_completo_sem_mostrar_a_resposta_do_modelo(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    assert "Amostra ainda não sorteada" in cli.get("/validacao").text
    r = _post(cli, "/validacao/sortear")
    assert (r.status_code, r.headers["location"]) == (303, "/validacao")
    r = _post(cli, "/validacao/sortear")
    assert r.status_code == 409 and "A amostra da validação já foi sorteada." in r.text
    lista = cli.get("/validacao").text
    assert "<strong>0 de 5</strong>" in lista and "Concordância entre a pessoa e o modelo" not in lista
    for ordem in range(1, 6):
        pagina = cli.get(f"/validacao/{ordem}").text
        for segredo in ("Relatório técnico / literatura cinzenta", "trata de viés", "Brasil / SP", "Triagem de escopo pelo modelo"):
            assert segredo not in pagina, (ordem, segredo)
        r = _post(cli, f"/validacao/{ordem}/triar", revisor="Ana", **VALIDA)
        assert r.status_code == 303
        assert r.headers["location"] == (f"/validacao/{ordem + 1}" if ordem < 5 else "/validacao")
    lista = cli.get("/validacao").text
    assert "<strong>5 de 5</strong>" in lista and "Concordância entre a pessoa e o modelo" in lista
    assert re.search(r"<td>relevância</td><td class=\"num\">0 de 5</td>", lista)


def test_resposta_invalida_volta_com_os_erros_e_nao_grava(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    _post(cli, "/validacao/sortear")
    r = _post(cli, "/validacao/1/triar", revisor="", relevancia="x", grupo=AV.GRUPO_CIENTIFICA, eixo="nenhum", pais="")
    assert r.status_code == 400
    assert re.findall(r"<li>([^<]*)</li>", r.text.split('role="alert"')[1])[:3] == [
        "Opção inválida em relevância.", "Escolha a opção de país.", "Informe o nome do revisor."]
    assert sqlite3.connect(banco).execute("SELECT COUNT(*) FROM validacao_vies WHERE relevancia IS NOT NULL").fetchone()[0] == 0


@pytest.mark.parametrize("rota, titulo", [("/validacao/99", "Item não encontrado"), ("/validacao/0", "Endereço inválido"),
                                          ("/validacao/abc", "Endereço inválido"), ("/validacao/-1", "Endereço inválido"),
                                          ("/validacao/99999999999999999999", "Endereço inválido")])
def test_item_inexistente_ou_malformado(banco, tmp_path, rota, titulo):
    cli = _cli(banco, tmp_path)
    _post(cli, "/validacao/sortear")
    r = cli.get(rota)
    assert r.status_code == 404 and titulo in r.text


def test_responder_item_inexistente(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    _post(cli, "/validacao/sortear")
    assert _post(cli, "/validacao/99/triar", revisor="Ana", **VALIDA).status_code == 404


def test_somente_leitura_nao_grava(banco, tmp_path):
    cli = _cli(banco, tmp_path, somente_leitura=True)
    assert "Painel em modo somente leitura." in cli.get("/validacao").text
    assert _post(cli, "/validacao/sortear").status_code == 403
    assert sqlite3.connect(banco).execute("SELECT COUNT(*) FROM validacao_vies").fetchone()[0] == 0


def test_caminhos_pedem_a_permissao_certa():
    from dominio import autenticacao as A
    assert A.permissao_exigida("POST", "/validacao/sortear") == A.SO_ADMIN
    assert A.permissao_exigida("POST", "/validacao/3/triar") == "triar_artigos"
    assert A.permissao_exigida("GET", "/validacao") == A.permissao_exigida("GET", "/validacao/3") == "ver_painel"


@pytest.mark.parametrize("rota", ["/validacao/sortear", "/validacao/1/triar"])
def test_sem_csrf_ou_de_outra_origem_e_recusado(banco, tmp_path, rota):
    cli = _cli(banco, tmp_path)
    if rota != "/validacao/sortear":
        _post(cli, "/validacao/sortear")
    sem = cli.post(rota, data={"revisor": "Ana", **VALIDA}, headers={"Origin": "http://testserver"}, follow_redirects=False)
    outra = cli.post(rota, data={"csrf": cli.cookies.get("csrf"), "revisor": "Ana", **VALIDA},
                     headers={"Origin": "http://outro.exemplo"}, follow_redirects=False)
    assert sem.status_code == outra.status_code == 403
    assert sqlite3.connect(banco).execute("SELECT COUNT(*) FROM validacao_vies WHERE relevancia IS NOT NULL").fetchone()[0] == 0


@pytest.mark.parametrize("ordem", ["0", "-1", "abc", "99999999999999999999"])
def test_responder_numero_malformado(banco, tmp_path, ordem):
    cli = _cli(banco, tmp_path)
    _post(cli, "/validacao/sortear")
    r = _post(cli, f"/validacao/{ordem}/triar", revisor="Ana", **VALIDA)
    assert r.status_code == 404 and "Endereço inválido" in r.text


def test_fora_de_ordem_vai_ao_primeiro_pendente_e_guarda_o_revisor(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    _post(cli, "/validacao/sortear")
    r = _post(cli, "/validacao/3/triar", revisor="Ana", **VALIDA)
    assert r.headers["location"] == "/validacao/1" and cli.cookies.get("revisor") == "Ana"
    assert 'value="Ana"' in cli.get("/validacao/1").text
    r = _post(cli, "/validacao/1/triar", revisor="Beto", **VALIDA)
    assert r.status_code == 409 and "Esta amostra já está sendo respondida por outra pessoa" in r.text


def test_amostra_completa_recusa_mudanca_pelo_painel(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    _post(cli, "/validacao/sortear")
    for ordem in range(1, 6):
        _post(cli, f"/validacao/{ordem}/triar", revisor="Ana", **VALIDA)
    r = _post(cli, "/validacao/1/triar", revisor="Ana", **{**VALIDA, "relevancia": "alta"})
    assert r.status_code == 409 and "A validação já foi concluída" in r.text


@pytest.mark.postgres
def test_fluxo_no_postgres(pg_url, tmp_path):
    from adaptadores import migrador_postgres as M
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres import importador as I
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    from adaptadores.repositorio_postgres import RepositorioPostgres
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    con = sqlite3.connect(tmp_path / "busca.db")
    refs = [r[0] for r in con.execute("SELECT referencia_id FROM referencias_web ORDER BY 1")]
    con.close()
    _triar(tmp_path / "busca.db", [_linha("referencia", i) for i in refs])
    M.aplicar(pg_url)
    I.importar(tmp_path / "busca.db", pg_url)
    pool = criar_pool(pg_url)
    try:
        chaves = chaves_do_banco(pool)
        leitura = LeituraPainelPostgres(pool, chaves)
        ctx = _contexto("vies")
        from painel import visao_geral_vies
        amostra = VV.sortear(visao_geral_vies.itens(leitura, ctx), leitura.triagens_vies(ctx.versao_triagem_vies), EIXOS)
        assert len(amostra) == len(refs)

        def gravar(acao):
            repo = RepositorioPostgres(pool, chaves)
            try:
                return acao(repo)
            finally:
                repo.fechar()
        gravar(lambda r: r.sortear_validacao_vies(amostra))
        with pytest.raises(SystemExit):
            gravar(lambda r: r.sortear_validacao_vies(amostra))
        gravar(lambda r: r.responder_validacao_vies(1, VALIDA, "Ana"))
        primeira = leitura.linhas_validacao_vies()[0]
        gravar(lambda r: r.responder_validacao_vies(1, VALIDA, "Ana"))
        de_novo = leitura.linhas_validacao_vies()
        assert de_novo[0]["respondido_em"] == primeira["respondido_em"] and primeira["relevancia"] == "media"
        assert [l["ordem"] for l in de_novo] == list(range(1, len(refs) + 1)) and all(l["titulo"] for l in de_novo)
    finally:
        pool.close()
