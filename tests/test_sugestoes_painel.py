"""RB17 (D78, decisao 6): sugestoes no painel. Quem tem a permissao de escrita e nao e o autor da decisao sugere; o autor da decisao
ou um administrador aceita ou descarta; quem sugeriu pode retirar. So existe com autenticacao ligada."""
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from test_autenticacao import _criar, _csrf, _entrar, painel  # noqa: F401  (fixture `painel`: autenticacao ligada)
from test_painel import _app, demo  # noqa: F401
from test_painel_acessibilidade import verificar
from dominio import autenticacao as A

CARTAO = '<div class="cartao sugestoes" id="sugestoes">'
VENCIDA_SELO = '<span class="selo neutro">feita sobre uma decisão anterior</span>'


def _um(copia, sql, *args):
    return sqlite3.connect(copia).execute(sql, args).fetchone()


def _sair(cli):
    cli.post("/sair", data={"csrf": _csrf(cli)})
    cli.cookies.clear()


def _como(painel, login):
    cli = painel[0]
    _sair(cli)
    assert _entrar(cli, login).status_code == 303
    return cli


def _achado_decidido_por(painel, login):
    """Um achado ainda nao verificado, verificado agora pelo usuario `login` com o status `em_uso`."""
    cli, _, copia, _ = painel
    a = _um(copia, "SELECT achado_id FROM v_achados_revisao WHERE verificado=0 ORDER BY achado_id LIMIT 1")[0]
    _como(painel, login)
    h = cli.get(f"/achados/{a}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    versao = re.search(r'name="versao" value="([^"]*)"', h).group(1)
    status = "em_uso"
    r = cli.post(f"/achados/{a}/verificar", data={"status_final": status, "observacao": "", "versao": versao, "csrf": csrf},
                 follow_redirects=False)
    assert r.status_code == 303
    return a, status


def _sugerir(cli, base, valor, motivo=""):
    h = cli.get(base).text
    m = re.search(r'<input type="hidden" name="estado" value="([^"]+)">', h)
    assert m, "formulário de sugestão ausente"
    estado = m.group(1)
    return cli.post(f"{base}/sugerir", data={"valor": valor, "motivo": motivo, "estado": estado, "csrf": _csrf(cli)},
                    follow_redirects=False)


def _sid(copia):
    return _um(copia, "SELECT MAX(sugestao_id) FROM sugestoes")[0]


@pytest.fixture
def equipe(painel):
    _criar(painel, "maria", "Revisor", nome="Maria Souza")
    _criar(painel, "bia", "Revisor", nome="Bia Lima")
    _criar(painel, "joao", "Revisor", nome="João Reis")
    _criar(painel, "chefe", "Administrador", nome="Chefe")
    _criar(painel, "leo", "Leitor", nome="Leo")
    return painel


def test_fluxo_sugerir_e_aceitar_no_achado(equipe):
    cli, _, copia, _ = equipe
    a, status = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    h = cli.get(f"/achados/{a}").text
    assert CARTAO in h and "<summary>Sugerir outra decisão</summary>" in h and verificar(h) == []
    opcoes = re.findall(r'<option value="([^"]*)">', h.split('id="sugestao-valor"')[1].split("</select>")[0])
    assert opcoes == ["", "piloto", "licitacao", "anunciado", "em_estudo", "apenas_citado", "descartado"]   # sem o valor atual
    r = _sugerir(cli, f"/achados/{a}", "descartado", "não é IA")
    assert r.status_code == 303 and r.headers["location"] == f"/achados/{a}"
    sid = _sid(copia)
    h = cli.get(f"/achados/{a}").text
    assert "sugerido por Bia Lima em" in h and "não é IA" in h
    assert f'action="/achados/{a}/sugestoes/{sid}/descartar"' in h and ">Retirar</button>" in h
    assert f'/sugestoes/{sid}/aceitar' not in h
    _como(equipe, "maria")
    h = cli.get(f"/achados/{a}").text
    assert f'action="/achados/{a}/sugestoes/{sid}/aceitar"' in h and ">Aceitar</button>" in h and ">Descartar</button>" in h
    assert verificar(h) == []
    assert "<summary>Sugerir outra decisão</summary>" not in h                      # autora da decisao nao sugere
    r = cli.post(f"/achados/{a}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/achados/{a}"
    assert _um(copia, "SELECT status_final, verificado_por FROM achados WHERE achado_id=?", a) == ("descartado", "Maria Souza")
    assert _um(copia, "SELECT situacao FROM sugestoes WHERE sugestao_id=?", sid) == ("aceita",)


def test_outro_revisor_nao_resolve_e_recebe_403(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    _como(equipe, "joao")
    h = cli.get(f"/achados/{a}").text
    assert f"/sugestoes/{sid}/aceitar" not in h and f"/sugestoes/{sid}/descartar" not in h
    for acao in ("aceitar", "descartar"):
        r = cli.post(f"/achados/{a}/sugestoes/{sid}/{acao}", data={"csrf": _csrf(cli)}, follow_redirects=False)
        assert r.status_code == 403 and "Só quem tomou a decisão ou um administrador resolve sugestões." in r.text
    assert _um(copia, "SELECT situacao FROM sugestoes WHERE sugestao_id=?", sid) == ("aberta",)


def test_administrador_aceita_e_quem_sugeriu_retira(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    s1 = _sid(copia)
    r = cli.post(f"/achados/{a}/sugestoes/{s1}/descartar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303 and _um(copia, "SELECT situacao, resolvido_por FROM sugestoes WHERE sugestao_id=?", s1) == ("descartada", "Bia Lima")
    _sugerir(cli, f"/achados/{a}", "descartado", "de novo")
    s2 = _sid(copia)
    _como(equipe, "chefe")
    r = cli.post(f"/achados/{a}/sugestoes/{s2}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303 and _um(copia, "SELECT verificado_por FROM achados WHERE achado_id=?", a) == ("Chefe",)


def test_sugestao_vencida_marcada_sem_aceitar_e_409(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    con = sqlite3.connect(copia)
    con.execute("UPDATE achados SET observacao='mudou' WHERE achado_id=?", (a,))                 # a decisao muda sem mudar o horario
    con.commit()
    _como(equipe, "maria")
    h = cli.get(f"/achados/{a}").text
    assert VENCIDA_SELO in h and f"/sugestoes/{sid}/aceitar" not in h and f"/sugestoes/{sid}/descartar" in h
    r = cli.post(f"/achados/{a}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 409 and "Esta sugestão foi feita sobre uma decisão que já mudou: descarte-a ou sugira de novo." in r.text


@pytest.mark.parametrize("caso,codigo,texto", [
    ("estado_antigo", 409, "A decisão deste item mudou depois que a página foi aberta: recarregue a página antes de sugerir"),
    ("valor_invalido", 400, "Valor sugerido inválido para o achado: &#39;foo&#39;."),
    ("autora_da_decisao", 400, "Quem tomou a decisão não sugere: decida de novo."),
    ("sem_csrf", 403, None),
])
def test_sugerir_recusas(equipe, caso, codigo, texto):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    if caso != "autora_da_decisao":
        _como(equipe, "bia")
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    dados = {"valor": "descartado", "motivo": "", "estado": LeituraPainelSQLite(copia).estado_decisao("achado", a), "csrf": _csrf(cli)}
    if caso == "estado_antigo":
        dados["estado"] = "ficha-antiga"
    elif caso == "valor_invalido":
        dados["valor"] = "foo"
    elif caso == "sem_csrf":
        dados["csrf"] = "errado"
    r = cli.post(f"/achados/{a}/sugerir", data=dados, follow_redirects=False)
    assert r.status_code == codigo
    if texto:
        assert texto in r.text
    assert _um(copia, "SELECT COUNT(*) FROM sugestoes")[0] == 0


def test_sugestao_de_outro_item_e_404(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    outro = _um(copia, "SELECT achado_id FROM achados WHERE achado_id<>? ORDER BY achado_id LIMIT 1", a)[0]
    _como(equipe, "maria")
    r = cli.post(f"/achados/{outro}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 404 and f"Não existe a sugestão nº {sid} neste item." in r.text


def test_leitor_e_anonimo_nao_sugerem_e_nomes_mascarados(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    _como(equipe, "leo")
    h = cli.get(f"/achados/{a}").text
    assert CARTAO in h and "<summary>Sugerir outra decisão</summary>" not in h
    r = cli.post(f"/achados/{a}/sugerir", data={"valor": "descartado", "estado": "x", "csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 403
    _sair(cli)
    r = cli.get(f"/achados/{a}", follow_redirects=False)                # quem nao entrou nem abre o achado (D145)
    assert r.status_code == 303 and "Bia Lima" not in r.text


def test_artigo_sugerir_excluir_e_aceitar(equipe):
    cli, _, copia, _ = equipe
    art = _um(copia, "SELECT artigo_id FROM r_artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM triagem) ORDER BY artigo_id LIMIT 1")[0]
    _como(equipe, "maria")
    h = cli.get(f"/literatura/artigos/{art}").text
    versao = re.search(r'name="versao" value="([^"]*)"', h).group(1)
    r = cli.post(f"/literatura/artigos/{art}/triar", data={"decisao": "incluir", "motivo": "", "versao": versao, "etapa": "titulo_resumo",
                                                           "csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303
    _como(equipe, "bia")
    r = _sugerir(cli, f"/literatura/artigos/{art}", "excluir", "fora do tema")
    assert r.status_code == 303 and r.headers["location"] == f"/literatura/artigos/{art}"
    sid = _sid(copia)
    _como(equipe, "maria")
    r = cli.post(f"/literatura/artigos/{art}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303
    assert _um(copia, "SELECT decisao, motivo, revisor FROM triagem WHERE artigo_id=?", art) == ("excluir", "fora do tema", "Maria Souza")


def test_sem_autenticacao_nao_ha_sugestoes(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    cli = TestClient(app)
    a = _um(copia, "SELECT MIN(achado_id) FROM achados")[0]
    assert CARTAO not in cli.get(f"/achados/{a}").text
    h = cli.get(f"/achados/{a}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    r = cli.post(f"/achados/{a}/sugerir", data={"valor": "descartado", "estado": "x", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 404 and "As sugestões só existem quando o painel usa login." in r.text


def test_administrador_nao_aceita_a_propria_sugestao(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "chefe")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    h = cli.get(f"/achados/{a}").text
    assert f"/sugestoes/{sid}/aceitar" not in h and ">Retirar</button>" in h


def test_retirar_so_com_permissao_de_escrita(equipe):
    cli, _, copia, contas_db = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    c = sqlite3.connect(contas_db)
    c.execute("UPDATE usuarios SET grupo_id=(SELECT grupo_id FROM grupos WHERE nome='Leitor') WHERE login='bia'")
    c.commit()
    assert ">Retirar</button>" not in cli.get(f"/achados/{a}").text


def test_artigo_outro_revisor_recebe_403_e_vencida_409(equipe):
    cli, _, copia, _ = equipe
    art = _um(copia, "SELECT artigo_id FROM r_artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM triagem) ORDER BY artigo_id LIMIT 1")[0]
    _como(equipe, "maria")
    h = cli.get(f"/literatura/artigos/{art}").text
    versao = re.search(r'name="versao" value="([^"]*)"', h).group(1)
    cli.post(f"/literatura/artigos/{art}/triar", data={"decisao": "incluir", "motivo": "", "versao": versao, "etapa": "titulo_resumo",
                                                      "csrf": _csrf(cli)}, follow_redirects=False)
    _como(equipe, "bia")
    _sugerir(cli, f"/literatura/artigos/{art}", "excluir", "fora do tema")
    sid = _sid(copia)
    _como(equipe, "joao")
    r = cli.post(f"/literatura/artigos/{art}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 403
    con = sqlite3.connect(copia)
    con.execute("UPDATE triagem SET motivo='revisto' WHERE artigo_id=?", (art,))
    con.commit()
    _como(equipe, "maria")
    assert VENCIDA_SELO in cli.get(f"/literatura/artigos/{art}").text
    r = cli.post(f"/literatura/artigos/{art}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 409


def test_redirecionamento_guarda_so_os_filtros_da_fila_e_motivo_com_crlf(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    h = cli.get(f"/achados/{a}").text
    m = re.search(r'<input type="hidden" name="estado" value="([^"]+)">', h)
    assert m, "formulário de sugestão ausente"
    estado = m.group(1)
    motivo = "x" * 1990 + "\r\n" * 10                                   # 2000 caracteres no campo, 2010 com CRLF
    r = cli.post(f"/achados/{a}/sugerir?fila=1&uf=SP&ok=5&x=1", data={"valor": "descartado", "motivo": motivo, "estado": estado,
                                                                      "csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/achados/{a}?fila=1&uf=SP"
    assert _um(copia, "SELECT motivo FROM sugestoes")[0] == "x" * 1990 + "\n" * 10


def test_clique_duplo_em_aceitar_e_409(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    _como(equipe, "maria")
    assert cli.post(f"/achados/{a}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False).status_code == 303
    r = cli.post(f"/achados/{a}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 409 and "Esta sugestão já foi resolvida." in r.text


def test_409_sem_nomes_para_quem_nao_ve_nomes(equipe):
    cli, _, copia, contas_db = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    c = sqlite3.connect(contas_db)
    c.execute("DELETE FROM grupo_permissoes WHERE permissao='ver_nomes_revisores' AND grupo_id=(SELECT grupo_id FROM grupos WHERE nome='Revisor')")
    c.commit()
    con = sqlite3.connect(copia)
    con.execute("UPDATE achados SET observacao='mudou' WHERE achado_id=?", (a,))
    con.commit()
    _como(equipe, "maria")
    r = cli.post(f"/achados/{a}/sugestoes/{sid}/aceitar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 409 and "A decisão deste item mudou depois que a página foi aberta. Recarregue a página." in r.text


def test_acao_desconhecida_e_404_para_o_administrador(equipe):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "chefe")
    r = cli.post(f"/achados/{a}/sugestoes/1/xyz", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 404


def test_artigo_com_texto_completo_pendente_gravado_recusa_com_400(equipe):
    cli, _, copia, _ = equipe
    art = _um(copia, "SELECT artigo_id FROM r_artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM triagem) ORDER BY artigo_id LIMIT 1")[0]
    con = sqlite3.connect(copia)
    con.execute("INSERT INTO triagem (artigo_id, decisao, revisor, revisado_em, decisao_texto_completo) "
                "VALUES (?, 'incluir', 'Maria Souza', '2026-10-19T00:00:00+00:00', 'pendente')", (art,))
    con.commit()
    _como(equipe, "bia")
    r = _sugerir(cli, f"/literatura/artigos/{art}", "excluir", "fora do tema")
    assert r.status_code == 400
    assert "Este artigo já tem decisão de texto completo: as sugestões valem só para a triagem por título e resumo." in r.text


def test_item_sem_decisao_e_sem_sugestoes_nao_mostra_cartao(equipe):
    cli, _, copia, _ = equipe
    a = _um(copia, "SELECT achado_id FROM v_achados_revisao WHERE verificado=0 ORDER BY achado_id LIMIT 1")[0]
    _como(equipe, "bia")
    assert CARTAO not in cli.get(f"/achados/{a}").text


def test_sem_autenticacao_resolver_tambem_e_404(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    cli = TestClient(app)
    a = _um(copia, "SELECT MIN(achado_id) FROM achados")[0]
    art = _um(copia, "SELECT MIN(artigo_id) FROM artigos")[0]
    csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get(f"/achados/{a}").text).group(1)
    for url in (f"/achados/{a}/sugestoes/1/aceitar", f"/literatura/artigos/{art}/sugerir", f"/literatura/artigos/{art}/sugestoes/1/descartar"):
        r = cli.post(url, data={"csrf": csrf}, follow_redirects=False)
        assert r.status_code == 404 and "As sugestões só existem quando o painel usa login." in r.text, url


@pytest.mark.parametrize("metodo,caminho,esperado", [
    ("POST", "/achados/1/sugerir", "verificar_achados"),
    ("POST", "/achados/1/sugestoes/2/aceitar", "verificar_achados"),
    ("POST", "/achados/1/sugestoes/2/descartar", "verificar_achados"),
    ("POST", "/literatura/artigos/1/sugerir", "triar_artigos"),
    ("POST", "/literatura/artigos/1/sugestoes/2/aceitar", "triar_artigos"),
    ("POST", "/literatura/artigos/1/sugestoes/2/descartar", "triar_artigos"),
    ("POST", "/estados/sugerir", A.SO_ADMIN),
    ("POST", "/admin/usuarios/1/aceitar", A.SO_ADMIN),
    ("GET", "/achados/1/sugerir", "ver_painel"),
])
def test_permissao_exigida_das_rotas_de_sugestao(metodo, caminho, esperado):
    assert A.permissao_exigida(metodo, caminho) == esperado


@pytest.mark.parametrize("acao", ["aceitar", "descartar"])
def test_resolver_sobre_item_inexistente_e_404_e_nada_muda(equipe, acao):
    cli, _, copia, _ = equipe
    a, _ = _achado_decidido_por(equipe, "maria")
    _como(equipe, "bia")
    _sugerir(cli, f"/achados/{a}", "descartado")
    sid = _sid(copia)
    con = sqlite3.connect(copia)
    con.execute("UPDATE sugestoes SET alvo_id=999999 WHERE sugestao_id=?", (sid,))       # sugestao de um item que nao existe
    con.commit()
    _como(equipe, "chefe")
    r = cli.post(f"/achados/999999/sugestoes/{sid}/{acao}", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 404 and "Não existe o achado nº 999999." in r.text
    assert _um(copia, "SELECT situacao FROM sugestoes WHERE sugestao_id=?", sid) == ("aberta",)


def test_sem_autenticacao_vem_antes_da_acao_invalida(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    cli = TestClient(app)
    a = _um(copia, "SELECT MIN(achado_id) FROM achados")[0]
    csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get(f"/achados/{a}").text).group(1)
    r = cli.post(f"/achados/{a}/sugestoes/1/xyz", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 404 and "As sugestões só existem quando o painel usa login." in r.text
