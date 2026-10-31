"""Tela "Divulgação pública" do Administrador (D145, E7 6): so o Administrador abre e grava, inclusive por pedido direto; a
pesquisa do painel e a unica alterada; estado ausente, invalido e falha de leitura aparecem distintos (e a pesquisa segue
fechada); revisao com a frase do efeito, confirmacao obrigatoria, versao conferida e auditoria; preliminares verdadeiro nunca
gravado; falha de gravacao nunca mostra sucesso nem abre a pesquisa."""
import json
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from dominio import divulgacao as D
from painel.app import Contexto, criar_app
from test_admin import SENHA, _agora, _criar, _csrf, _entrar, adm  # noqa: F401
from test_painel import demo  # noqa: F401

AVISO_ABERTURA = ("Entendo que qualquer pessoa na internet passará a ver: a Visão Geral, Sobre os dados, o PRISMA, a "
                  "Metodologia e a busca no texto, sem resultados automatizados.")
ROTAS = [("GET", "/admin/divulgacao"), ("POST", "/admin/divulgacao/revisar"), ("POST", "/admin/divulgacao")]


def _linha(contas_db, banco="real"):
    r = sqlite3.connect(contas_db).execute("SELECT valor FROM configuracoes WHERE chave = ?", (D.chave(banco),)).fetchone()
    return r[0] if r else None


def _divulgacoes(contas_db):
    return [r for r in sqlite3.connect(contas_db).execute(
        "SELECT admin_login, alvo, detalhe FROM auditoria_admin WHERE acao = 'alterar_divulgacao' ORDER BY id")]


def _versao(cli):
    m = re.search(r'name="versao" value="([0-9a-f]{64})"', cli.get("/admin/divulgacao").text)
    assert m, "a tela de divulgacao nao trouxe a versao"
    return m.group(1)


def _revisar(cli, publica="1", versao=None, extra=None):
    dados = {"publica": publica, "versao": versao or _versao(cli), "csrf": _csrf(cli, "/admin/divulgacao")}
    dados.update(extra or {})
    return cli.post("/admin/divulgacao/revisar", data=dados, follow_redirects=False)


def _gravar(cli, publica="1", versao=None, confirmo=True, extra=None):
    dados = {"publica": publica, "versao": versao or _versao(cli), "csrf": _csrf(cli, "/admin/divulgacao")}
    if confirmo:
        dados["confirmo"] = "1"
    dados.update(extra or {})
    return cli.post("/admin/divulgacao", data=dados, follow_redirects=False)


def _conteudo(h):
    return h[h.index('<main id="conteudo"'):]


# ======================== quem pode ========================
@pytest.mark.parametrize("grupo", ["Leitor", "Revisor", "Visitante_com_tudo"])
def test_so_o_administrador_abre_e_grava(adm, grupo):  # noqa: F811
    cli, contas, contas_db, copia = adm
    if grupo == "Visitante_com_tudo":                      # um grupo com todas as permissoes do catalogo, menos ser Administrador
        gid = contas.criar_grupo("Quase", _agora())
        contas.definir_permissoes(gid, set(A.PERMISSOES))
        grupo = "Quase"
    assert _criar(cli, contas_db, login="outro", nome="Outro", grupo=grupo).status_code == 303
    versao = _versao(cli)
    csrf_adm = _csrf(cli, "/admin/divulgacao")
    outro = TestClient(cli.app)
    assert _entrar(outro, "outro").status_code == 303
    csrf = _csrf(outro, "/")
    assert outro.get("/admin/divulgacao", follow_redirects=False).status_code == 403
    for caminho in ("/admin/divulgacao/revisar", "/admin/divulgacao"):
        r = outro.post(caminho, data={"publica": "1", "versao": versao, "confirmo": "1", "csrf": csrf}, follow_redirects=False)
        assert r.status_code == 403, caminho
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []
    assert _gravar(cli, "1").status_code == 303             # o administrador, no mesmo painel, grava


@pytest.mark.parametrize("divulgada", [False, True])
def test_quem_nao_entrou_vai_para_a_entrada_e_nada_e_gravado(adm, divulgada):  # noqa: F811
    cli, contas, contas_db, _ = adm
    if divulgada:
        _gravar(cli, "1")
    antes = (_linha(contas_db), len(_divulgacoes(contas_db)))
    versao = _versao(cli)
    anonimo = TestClient(cli.app)
    r = anonimo.get("/admin/divulgacao", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fadmin%2Fdivulgacao"
    for caminho in ("/admin/divulgacao/revisar", "/admin/divulgacao"):
        r = anonimo.post(caminho, data={"publica": "0", "versao": versao, "confirmo": "1", "csrf": "x"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2F", caminho        # como nas outras telas
    assert (_linha(contas_db), len(_divulgacoes(contas_db))) == antes


@pytest.mark.parametrize("caminho", ["/admin/divulgacao/revisar", "/admin/divulgacao"])
@pytest.mark.parametrize("csrf,origem,publica", [(None, None, "1"), ("", None, "1"), ("errado", None, "1"), ("errado", None, "2"),
                                                  ("certo", "http://outro.example", "1")])
def test_token_e_origem_conferidos_antes_de_tudo(adm, caminho, csrf, origem, publica):  # noqa: F811
    cli, _, contas_db, _ = adm
    dados = {"publica": publica, "versao": _versao(cli), "confirmo": "1"}
    if csrf is not None:
        dados["csrf"] = _csrf(cli, "/admin/divulgacao") if csrf == "certo" else csrf
    r = cli.post(caminho, data=dados, headers={"origin": origem} if origem else {}, follow_redirects=False)
    assert r.status_code == 403                                        # nunca 400 nem 409: o token vem primeiro
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


@pytest.mark.parametrize("metodo,caminho", [("PUT", "/admin/divulgacao"), ("DELETE", "/admin/divulgacao"),
                                            ("PATCH", "/admin/divulgacao"), ("HEAD", "/admin/divulgacao"),
                                            ("GET", "/admin/divulgacao/revisar"), ("PUT", "/admin/divulgacao/revisar")])
def test_metodos_desconhecidos(adm, metodo, caminho):  # noqa: F811
    cli, _, contas_db, _ = adm
    assert cli.request(metodo, caminho, follow_redirects=False).status_code == 405       # como nas outras telas de administracao
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


def test_as_rotas_tem_regra_so_do_administrador():
    for metodo, caminho in ROTAS:
        assert A.regra_explicita(metodo, caminho) == (metodo, caminho, A.SO_ADMIN)


def test_sem_login_as_rotas_nao_existem(demo, tmp_path):  # noqa: F811
    from test_divulgacao_acesso import _painel
    app, _, _, _ = _painel(demo, tmp_path, autenticacao=False)
    cli = TestClient(app)
    assert cli.get("/admin/divulgacao").status_code == 404
    assert cli.get("/admin/grupos").status_code == 404                     # como as outras telas de administracao


# ======================== estado lido ========================
@pytest.mark.parametrize("bruto,texto,marcado", [
    (None, "Ainda não configurada: a pesquisa é tratada como não divulgada.", "0"),
    ("lixo", "Configuração de divulgação inválida; tratada como não divulgada.", "0"),
    ('{"publica": true, "preliminares": true}', "Configuração de divulgação inválida; tratada como não divulgada.", "0"),
    ('{"publica": false, "preliminares": false}', None, "0"),
    ('{"publica": true, "preliminares": false}', None, "1"),
])
def test_estado_na_tela(adm, bruto, texto, marcado):  # noqa: F811
    cli, contas, contas_db, _ = adm
    if bruto is not None:
        with contas._conexao(escrita=True) as conn:
            conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave("real"), bruto))
    h = _conteudo(cli.get("/admin/divulgacao").text)
    assert "<h1>Divulgação pública</h1>" in h and "Secretarias Estaduais de Segurança Pública" in h
    for t in ("Ainda não configurada: a pesquisa é tratada como não divulgada.",
              "Configuração de divulgação inválida; tratada como não divulgada."):
        assert (t in h) is (t == texto), t
    assert re.search(rf'<input type="radio" name="publica" value="{marcado}" checked', h)
    assert len(re.findall(r'<input type="radio" name="publica" value="[01]" checked', h)) == 1
    assert "<fieldset disabled>" in h
    hoje = ("Hoje quem não entrou vê: a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e a busca no texto, sem "
            "resultados automatizados.") if marcado == "1" else "Hoje quem não entrou vê: só a tela de entrada."
    assert hoje in h
    assert 'name="preliminares"' not in h and "Disponível quando o aviso de resultado preliminar estiver pronto." in h
    assert f'name="versao" value="{D.versao(bruto)}"' in h


@pytest.mark.parametrize("erro", ["ocupado", "outro"])
def test_falha_de_leitura_e_distinta_e_sem_formulario(adm, monkeypatch, erro):  # noqa: F811
    cli, contas, _, _ = adm

    def falha(banco):
        raise A.ContasOcupadas() if erro == "ocupado" else RuntimeError("disco")
    monkeypatch.setattr(contas, "estado_divulgacao", falha)
    r = cli.get("/admin/divulgacao")
    assert r.status_code == 503
    h = _conteudo(r.text)
    assert ("Não foi possível ler a configuração de divulgação agora. Para quem não entrou, a pesquisa continua fechada. "
            "Tente de novo em alguns segundos.") in h
    assert "Ainda não configurada" not in h and 'name="publica"' not in h and "disco" not in h


# ======================== alteracao ========================
def test_abrir_revisar_gravar_e_fechar(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    anonimo = TestClient(cli.app)
    assert anonimo.get("/", follow_redirects=False).status_code == 303          # fechada antes
    r = _revisar(cli, "1")
    assert r.status_code == 200
    h = _conteudo(r.text)
    assert ("Quem não entrou passará a ver a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e a busca no texto, sem "
            "resultados automatizados.") in h
    assert f'<input type="checkbox" name="confirmo" value="1" required> {AVISO_ABERTURA}' in h
    assert '<a href="/admin/divulgacao">Cancelar</a>' in h
    assert _linha(contas_db) is None                                           # revisar nunca grava
    r = _gravar(cli, "1")
    assert r.status_code == 303 and r.headers["location"] == "/admin/divulgacao?gravado=1"
    assert json.loads(_linha(contas_db)) == {"publica": True, "preliminares": False}
    assert "Alteração gravada." in cli.get("/admin/divulgacao?gravado=1").text
    assert anonimo.get("/", follow_redirects=False).status_code == 200          # a politica vale na hora
    r = _gravar(cli, "0")
    assert r.status_code == 303 and json.loads(_linha(contas_db)) == {"publica": False, "preliminares": False}
    assert anonimo.get("/", follow_redirects=False).status_code == 303
    aud = _divulgacoes(contas_db)
    assert [(l, a) for l, a, _ in aud] == [("chefe", "real"), ("chefe", "real")]
    assert [json.loads(d)["depois"]["publica"] for _, _, d in aud] == [True, False]


def test_sem_mudanca_nao_pede_confirmacao_nem_grava(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    h = _conteudo(_revisar(cli, "0").text)
    assert "Nada muda: a divulgação já está assim." in h and 'name="confirmo"' not in h and "Gravar alteração" not in h
    r = _gravar(cli, "0", confirmo=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/divulgacao?gravado=0"
    assert "Nada mudou." in cli.get("/admin/divulgacao?gravado=0").text
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


def test_sem_confirmacao_nada_e_gravado(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    r = _gravar(cli, "1", confirmo=False)
    assert r.status_code == 400 and "Marque a confirmação para gravar a alteração." in r.text
    assert 'name="confirmo"' in r.text                                         # a revisao volta, com a caixa
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


@pytest.mark.parametrize("extra,erro", [
    ({"preliminares": "1"}, "A divulgação de resultados preliminares ainda não está disponível."),
    ({"preliminares": "true"}, "Configuração de divulgação inválida."),
    ({"publica": "2"}, "Configuração de divulgação inválida."),
    ({"publica": ""}, "Configuração de divulgação inválida."),
])
@pytest.mark.parametrize("passo", ["revisar", "gravar"])
def test_formulario_manipulado_e_recusado(adm, extra, erro, passo):  # noqa: F811
    cli, _, contas_db, _ = adm
    r = (_revisar if passo == "revisar" else _gravar)(cli, extra.get("publica", "1"),
                                                      extra={k: v for k, v in extra.items() if k != "publica"})
    assert r.status_code == 400 and erro in r.text
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


def test_publica_repetida_e_recusada(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    dados = [("publica", "1"), ("publica", "1"), ("versao", _versao(cli)), ("confirmo", "1"),
             ("csrf", _csrf(cli, "/admin/divulgacao"))]
    r = cli.post("/admin/divulgacao", content="&".join(f"{k}={v}" for k, v in dados),
                 headers={"content-type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.status_code == 400 and "Configuração de divulgação inválida." in r.text
    assert _linha(contas_db) is None


def test_versao_desatualizada_e_recusada(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    versao = _versao(cli)
    with contas._conexao(escrita=True) as conn:                                # outra pessoa gravou depois
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave("real"), '{"publica": false, "preliminares": false}'))
    r = _gravar(cli, "1", versao=versao)
    assert r.status_code == 409
    assert ("A divulgação desta pesquisa mudou desde que você abriu a página. Nada foi gravado: abra a página de novo e "
            "refaça a alteração.") in r.text
    assert json.loads(_linha(contas_db)) == {"publica": False, "preliminares": False} and _divulgacoes(contas_db) == []


def test_dois_administradores_com_a_mesma_pagina(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    contas.definir_admin("chefa", "Chefa", A.hash_senha(SENHA), _agora())
    outra = TestClient(cli.app)
    assert _entrar(outra, "chefa").status_code == 303
    v1, v2 = _versao(cli), _versao(outra)
    assert v1 == v2
    assert _gravar(cli, "1", versao=v1).status_code == 303
    assert _gravar(outra, "1", versao=v2).status_code == 409
    assert [l for l, _, _ in _divulgacoes(contas_db)] == ["chefe"]


@pytest.mark.parametrize("onde", ["auditoria", "linha"])
def test_falha_de_gravacao_nao_mostra_sucesso_nem_abre(adm, monkeypatch, onde):  # noqa: F811
    cli, contas, contas_db, _ = adm
    if onde == "auditoria":
        def falha(*a, **k):
            raise RuntimeError("disco cheio")
        monkeypatch.setattr(contas, "_gravar_auditoria", falha)
    else:
        with contas._conexao(escrita=True) as conn:
            conn.execute("CREATE TRIGGER quebra BEFORE INSERT ON configuracoes BEGIN SELECT RAISE(ABORT, 'falha'); END")
    r = _gravar(cli, "1")
    assert r.status_code == 500
    h = _conteudo(r.text)
    assert "Não foi possível gravar a alteração. Nada foi gravado: a divulgação continua como estava." in h
    assert "Alteração gravada." not in h and "disco cheio" not in h and "falha" not in h
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []
    assert TestClient(cli.app).get("/", follow_redirects=False).status_code == 303


def test_banco_de_contas_ocupado_ao_gravar(adm, monkeypatch):  # noqa: F811
    cli, contas, contas_db, _ = adm
    versao = _versao(cli)

    def ocupado(*a, **k):
        raise A.ContasOcupadas()
    monkeypatch.setattr(contas, "alterar_divulgacao", ocupado)
    r = _gravar(cli, "1", versao=versao)
    assert r.status_code == 503 and "Alteração gravada." not in r.text
    assert _linha(contas_db) is None


# ======================== isolamento ========================
def test_o_painel_de_uma_pesquisa_so_altera_a_sua(demo, tmp_path):  # noqa: F811
    """O mesmo banco de contas para as duas pesquisas (como no PostgreSQL da nuvem): o painel do vies grava so divulgacao:vies."""
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    contas_db = tmp_path / "contas.db"
    contas = ContasSQLite(contas_db)
    ctx = Contexto(banco="vies", nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   autenticacao=True)
    cli = TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas))
    contas.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), _agora())
    _entrar(cli, "chefe")
    with contas._conexao(escrita=True) as conn:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave("real"), '{"publica": true, "preliminares": false}'))
    assert "Viés Algorítmico" in cli.get("/admin/divulgacao").text
    assert _gravar(cli, "1").status_code == 303
    assert json.loads(_linha(contas_db, "vies")) == {"publica": True, "preliminares": False}
    assert _gravar(cli, "0").status_code == 303
    assert json.loads(_linha(contas_db, "real")) == {"publica": True, "preliminares": False}     # a outra pesquisa intacta
    assert [a for _, a, _ in _divulgacoes(contas_db)] == ["vies", "vies"]


def test_alternar_a_divulgacao_nao_mexe_no_banco_da_pesquisa(adm):  # noqa: F811
    cli, _, _, copia = adm

    def conteudo():
        con = sqlite3.connect(copia)
        tabelas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: sorted(map(repr, con.execute(f"SELECT * FROM {t}").fetchall())) for t in tabelas}
    antes = conteudo()
    _gravar(cli, "1")
    _gravar(cli, "0")
    assert conteudo() == antes


# ======================== menu e preservacao ========================
def test_menu_da_administracao_com_a_divulgacao(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    h = cli.get("/admin/usuarios").text
    assert '<a href="/admin/divulgacao"' in h and ">Divulgação pública<" in h
    assert _criar(cli, contas_db, login="leo", nome="Leo", grupo="Leitor").status_code == 303
    leitor = TestClient(cli.app)
    assert _entrar(leitor, "leo").status_code == 303
    assert '/admin/divulgacao' not in leitor.get("/").text


def test_visao_geral_do_administrador_aponta_a_divulgacao(adm):  # noqa: F811
    cli, _, _, _ = adm
    h = cli.get("/").text
    assert "A divulgação pública dos resultados ainda não tem controle no painel" not in h
    assert "Quem não entrou só vê o que a divulgação pública desta pesquisa libera." in h
    assert '<a class="botao" href="/admin/divulgacao">Ver a divulgação pública</a>' in h


# ======================== pontos da pre-revisao ========================
def test_painel_somente_leitura_nao_chega_a_tela(demo, tmp_path):  # noqa: F811
    """Com --somente-leitura nem a entrada grava sessao: a tela fica fora de alcance e nada e escrito."""
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    contas = ContasSQLite(tmp_path / "contas.db")
    ctx = Contexto(banco="real", nome_banco=copia.name, somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   autenticacao=True)
    cli = TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas))
    contas.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), _agora())
    assert _entrar(cli, "chefe").status_code == 403
    assert cli.get("/admin/divulgacao", follow_redirects=False).status_code == 303
    for caminho in ("/admin/divulgacao/revisar", "/admin/divulgacao"):
        r = cli.post(caminho, data={"publica": "1", "versao": D.versao(None), "confirmo": "1", "csrf": "x"}, follow_redirects=False)
        assert r.status_code == 303
    assert _linha(tmp_path / "contas.db") is None


def test_revisao_mostra_hoje_e_depois_e_a_frase_de_fechar(adm):  # noqa: F811
    cli, _, _, _ = adm
    h = _conteudo(_revisar(cli, "1").text)
    assert "<p>Hoje: Não divulgada.</p>" in h and "<p>Depois da alteração: Divulgada.</p>" in h
    _gravar(cli, "1")
    h = _conteudo(_revisar(cli, "0").text)
    assert "<p>Hoje: Divulgada.</p>" in h and "<p>Depois da alteração: Não divulgada.</p>" in h
    assert "Quem não entrou passará a ser levado à tela de entrada em todas as páginas desta pesquisa." in h
    assert ('<input type="checkbox" name="confirmo" value="1" required> Entendo que quem não entrou deixará de ver as páginas '
            'desta pesquisa.') in h
    h = _conteudo(_revisar(cli, "1").text)                                    # ja divulgada: nada muda
    assert "Nada muda: a divulgação já está assim." in h and 'name="confirmo"' not in h


def test_revisao_com_versao_desatualizada_avisa_na_hora(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    versao = _versao(cli)
    with contas._conexao(escrita=True) as conn:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave("real"), '{"publica": true, "preliminares": false}'))
    r = _revisar(cli, "1", versao=versao)
    assert r.status_code == 409 and "A divulgação desta pesquisa mudou desde que você abriu a página." in r.text
    assert 'name="confirmo"' not in r.text


def test_configuracao_invalida_corrigida_sem_abrir(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    with contas._conexao(escrita=True) as conn:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave("real"), "lixo"))
    h = _conteudo(_revisar(cli, "0").text)
    assert "<p>Hoje: Configuração inválida (tratada como não divulgada).</p>" in h
    assert "A configuração inválida será trocada por «não divulgada»" in h and 'name="confirmo"' in h
    assert _gravar(cli, "0").status_code == 303
    assert json.loads(_linha(contas_db)) == {"publica": False, "preliminares": False}
    assert TestClient(cli.app).get("/", follow_redirects=False).status_code == 303          # nunca abriu
    assert "Configuração de divulgação inválida" not in cli.get("/admin/divulgacao").text


@pytest.mark.parametrize("confirmo", [["on"], ["true"], [""], ["1", "1"], ["0"]])
def test_confirmacao_so_com_o_valor_exato(adm, confirmo):  # noqa: F811
    cli, _, contas_db, _ = adm
    dados = [("publica", "1"), ("versao", _versao(cli)), ("csrf", _csrf(cli, "/admin/divulgacao"))] + [("confirmo", c) for c in confirmo]
    r = cli.post("/admin/divulgacao", content="&".join(f"{k}={v}" for k, v in dados),
                 headers={"content-type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.status_code == 400 and "Marque a confirmação para gravar a alteração." in r.text
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


@pytest.mark.parametrize("caminho", ["/admin/divulgacao/revisar", "/admin/divulgacao"])
@pytest.mark.parametrize("versoes", [[], [""], ["nao-hex"], ["V", "V"]])
def test_versao_ausente_repetida_ou_invalida(adm, caminho, versoes):  # noqa: F811
    cli, _, contas_db, _ = adm
    certa = _versao(cli)
    dados = [("publica", "1"), ("confirmo", "1"), ("csrf", _csrf(cli, "/admin/divulgacao"))] + \
            [("versao", certa if v == "V" else v) for v in versoes]
    r = cli.post(caminho, content="&".join(f"{k}={v}" for k, v in dados),
                 headers={"content-type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.status_code == 409
    assert _linha(contas_db) is None and _divulgacoes(contas_db) == []


@pytest.mark.parametrize("consulta", ["?gravado=2", "?gravado=%3Cb%3Ex%3C/b%3E", "?gravado=1&gravado=x", "?gravado="])
def test_parametro_gravado_estranho_nao_mostra_nada(adm, consulta):  # noqa: F811
    cli, _, _, _ = adm
    h = cli.get("/admin/divulgacao" + consulta).text
    assert "Alteração gravada." not in h and "Nada mudou." not in h and "<b>x</b>" not in h


def test_erro_de_formulario_nao_depende_da_leitura(adm, monkeypatch):  # noqa: F811
    cli, contas, _, _ = adm
    versao, csrf = _versao(cli), _csrf(cli, "/admin/divulgacao")

    def falha(banco):
        raise RuntimeError("disco")
    monkeypatch.setattr(contas, "estado_divulgacao", falha)
    for caminho in ("/admin/divulgacao/revisar", "/admin/divulgacao"):
        r = cli.post(caminho, data={"publica": "2", "versao": versao, "csrf": csrf}, follow_redirects=False)
        assert r.status_code == 400 and "Configuração de divulgação inválida." in r.text and "disco" not in r.text


def test_banco_ocupado_ao_gravar_sem_detalhe(adm, monkeypatch):  # noqa: F811
    cli, contas, _, _ = adm
    versao = _versao(cli)

    def ocupado(*a, **k):
        raise A.ContasOcupadas("detalhe interno")
    monkeypatch.setattr(contas, "alterar_divulgacao", ocupado)
    r = _gravar(cli, "1", versao=versao)
    assert r.status_code == 503 and "detalhe interno" not in r.text


def test_registro_de_administracao_mostra_a_alteracao_resumida(adm):  # noqa: F811
    cli, _, _, _ = adm
    _gravar(cli, "1")
    h = cli.get("/admin/auditoria").text
    assert "<td>Alteração da divulgação pública</td>" in h and "<td>real</td>" in h
    assert "<td>Não configurada → Divulgada</td>" in h and "versao_antes" not in h


# ======================== pre-revisao do formulario completo ========================
def _form(html, acao):
    """(campos ocultos e marcados, botao) do formulario com esta acao, lidos do HTML."""
    i = html.index(f'<form method="post" action="{acao}">')
    f = html[i:html.index("</form>", i)]
    campos = dict(re.findall(r'<input type="hidden" name="([a-z]+)" value="([^"]*)"', f))
    return f, campos


def test_fluxo_pelo_html_de_verdade(adm):  # noqa: F811
    cli, _, contas_db, _ = adm
    h = cli.get("/admin/divulgacao").text
    f, campos = _form(h, "/admin/divulgacao/revisar")
    assert set(campos) == {"csrf", "versao"} and '<button class="botao" type="submit">Revisar alteração</button>' in f
    assert '<input type="radio" name="publica" value="1"> Divulgada' in f and '<input type="radio" name="publica" value="0" checked> Não divulgada' in f
    r = cli.post("/admin/divulgacao/revisar", data={**campos, "publica": "1"}, follow_redirects=False)
    f2, campos2 = _form(r.text, "/admin/divulgacao")
    assert campos2 == {"csrf": campos2["csrf"], "versao": campos["versao"], "publica": "1"}           # a versao revisada, nunca relida
    assert '<button class="botao" type="submit">Gravar alteração</button>' in f2
    r = cli.post("/admin/divulgacao", data={**campos2, "confirmo": "1"}, follow_redirects=False)
    assert r.status_code == 303 and json.loads(_linha(contas_db))["publica"] is True


def test_mudanca_entre_a_revisao_e_a_gravacao(adm):  # noqa: F811
    cli, contas, contas_db, _ = adm
    _, campos = _form(cli.get("/admin/divulgacao").text, "/admin/divulgacao/revisar")
    _, campos2 = _form(cli.post("/admin/divulgacao/revisar", data={**campos, "publica": "1"}).text, "/admin/divulgacao")
    with contas._conexao(escrita=True) as conn:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave("real"), '{"publica": false, "preliminares": false}'))
    r = cli.post("/admin/divulgacao", data={**campos2, "confirmo": "1"}, follow_redirects=False)
    assert r.status_code == 409 and json.loads(_linha(contas_db))["publica"] is False and _divulgacoes(contas_db) == []


def test_recusa_volta_com_a_versao_enviada_e_falha_de_leitura_da_503(adm, monkeypatch):  # noqa: F811
    cli, contas, _, _ = adm
    versao = _versao(cli)
    r = _gravar(cli, "1", versao=versao, confirmo=False)
    _, campos = _form(r.text, "/admin/divulgacao")
    assert r.status_code == 400 and campos["versao"] == versao
    original = contas.estado_divulgacao

    def falha(banco):
        raise RuntimeError("disco")
    monkeypatch.setattr(contas, "estado_divulgacao", falha)
    r = cli.post("/admin/divulgacao", data={"publica": "1", "versao": versao, "csrf": _csrf_sem_ler(cli)}, follow_redirects=False)
    assert r.status_code == 503 and "disco" not in r.text
    monkeypatch.setattr(contas, "estado_divulgacao", original)


def _csrf_sem_ler(cli):
    return re.search(r'name="csrf" value="([^"]+)"', cli.get("/sobre").text).group(1)


def test_revisao_valida_com_falha_de_leitura_da_503(adm, monkeypatch):  # noqa: F811
    cli, contas, _, _ = adm
    versao, csrf = _versao(cli), _csrf(cli, "/admin/divulgacao")

    def falha(banco):
        raise RuntimeError("disco")
    monkeypatch.setattr(contas, "estado_divulgacao", falha)
    r = cli.post("/admin/divulgacao/revisar", data={"publica": "1", "versao": versao, "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 503 and "Não foi possível ler a configuração de divulgação agora." in r.text and "disco" not in r.text


def test_fechar_tambem_exige_confirmacao_e_falha_nao_fecha_pela_metade(adm, monkeypatch):  # noqa: F811
    cli, contas, contas_db, _ = adm
    assert _gravar(cli, "1").status_code == 303
    r = _gravar(cli, "0", confirmo=False)
    assert r.status_code == 400 and json.loads(_linha(contas_db))["publica"] is True
    for c in ("on", "0"):
        assert _gravar(cli, "0", extra={"confirmo": c}, confirmo=False).status_code == 400
    def falha(*a, **k):
        raise RuntimeError("disco cheio")
    monkeypatch.setattr(contas, "_gravar_auditoria", falha)
    r = _gravar(cli, "0")
    assert r.status_code == 500 and "Alteração gravada." not in r.text
    assert json.loads(_linha(contas_db))["publica"] is True and len(_divulgacoes(contas_db)) == 1
    assert TestClient(cli.app).get("/", follow_redirects=False).status_code == 200          # continua como estava (aberta)


def test_sem_login_nenhuma_das_rotas_existe(demo, tmp_path):  # noqa: F811
    from test_divulgacao_acesso import _painel
    app, _, _, _ = _painel(demo, tmp_path, autenticacao=False)
    cli = TestClient(app)
    for caminho in ("/admin/divulgacao", "/admin/divulgacao/revisar"):
        for metodo in ("GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            assert cli.request(metodo, caminho, follow_redirects=False).status_code == 404, (metodo, caminho)


@pytest.mark.parametrize("metodo", ["OPTIONS", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("caminho", ["/admin/divulgacao", "/admin/divulgacao/revisar"])
def test_metodos_desconhecidos_negados_a_quem_nao_e_administrador(adm, metodo, caminho):  # noqa: F811
    cli, _, contas_db, _ = adm
    assert cli.request(metodo, caminho, follow_redirects=False).status_code == 405        # o administrador: 405
    assert _criar(cli, contas_db, login="leo", nome="Leo", grupo="Leitor").status_code in (303, 400)
    leitor = TestClient(cli.app)
    assert _entrar(leitor, "leo").status_code == 303
    assert leitor.request(metodo, caminho, follow_redirects=False).status_code == 403
    assert _linha(contas_db) is None


@pytest.mark.parametrize("caminho", ["/admin/divulgacao/revisar", "/admin/divulgacao"])
@pytest.mark.parametrize("csrf,origem", [("errado", None), ("certo", "http://outro.example")])
def test_pedido_recusado_nem_le_o_estado(adm, monkeypatch, caminho, csrf, origem):  # noqa: F811
    cli, contas, _, _ = adm
    dados = {"publica": "1", "versao": _versao(cli), "confirmo": "1",
             "csrf": _csrf(cli, "/admin/divulgacao") if csrf == "certo" else csrf}
    lidas = []
    monkeypatch.setattr(contas, "estado_divulgacao", lambda banco: lidas.append(banco) or {"x": 1})
    monkeypatch.setattr(contas, "alterar_divulgacao", lambda *a, **k: lidas.append("gravar"))
    r = cli.post(caminho, data=dados, headers={"origin": origem} if origem else {}, follow_redirects=False)
    assert r.status_code == 403 and lidas == []


@pytest.mark.parametrize("caminho", ["/admin/divulgacao/revisar", "/admin/divulgacao"])
def test_versao_enviada_como_arquivo(adm, caminho):  # noqa: F811
    cli, _, contas_db, _ = adm
    csrf = _csrf(cli, "/admin/divulgacao")
    r = cli.post(caminho, data={"publica": "1", "confirmo": "1", "csrf": csrf},
                 files={"versao": ("v.txt", _versao(cli).encode(), "text/plain")}, follow_redirects=False)
    assert r.status_code == 409 and _linha(contas_db) is None and _divulgacoes(contas_db) == []


def test_textos_exatos_das_duas_paginas(adm):  # noqa: F811
    cli, _, _, _ = adm
    h = cli.get("/admin/divulgacao").text
    assert "<title>Divulgação pública" in h
    assert "Controla o que quem não entrou no painel pode ver. Não muda a validade científica de nenhum resultado." in h
    assert '<input type="radio" disabled> Mostrar com aviso' in h and '<input type="radio" disabled checked> Não mostrar' in h
    r = _revisar(cli, "1")
    assert "<title>Revisar a divulgação pública" in r.text and "<h1>Revisar a divulgação pública</h1>" in r.text
    r = _gravar(cli, "1", confirmo=False)
    assert '<ul class="aviso erro" role="alert"><li>Marque a confirmação para gravar a alteração.</li></ul>' in r.text


def test_registro_com_detalhe_malformado_nao_mostra_o_json(adm):  # noqa: F811
    cli, contas, _, _ = adm
    contas.auditar("chefe", "alterar_divulgacao", "real", '{"antes": "x", "versao_antes": "abc"}', _agora())
    h = cli.get("/admin/auditoria").text
    assert "versao_antes" not in h and "abc" not in h and "<td>—</td>" in h


def test_recusa_com_mudanca_no_meio_volta_com_a_versao_enviada(adm, monkeypatch):  # noqa: F811
    """Outro administrador grava entre a recusa (sem confirmacao) e a releitura: a pagina volta com a versao ENVIADA, para que
    a proxima gravacao responda 409, e nunca com a versao nova."""
    cli, contas, contas_db, _ = adm
    versao = _versao(cli)
    original = contas.alterar_divulgacao

    def recusa_e_outro_grava(banco, nova, v, confirmado, auditoria):
        try:
            return original(banco, nova, v, confirmado, auditoria)
        finally:
            with contas._conexao(escrita=True) as conn:
                conn.execute("DELETE FROM configuracoes WHERE chave = ?", (D.chave("real"),))
                conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)",
                             (D.chave("real"), '{"publica": false, "preliminares": false}'))
    monkeypatch.setattr(contas, "alterar_divulgacao", recusa_e_outro_grava)
    r = _gravar(cli, "1", versao=versao, confirmo=False)
    _, campos = _form(r.text, "/admin/divulgacao")
    assert r.status_code == 400 and campos["versao"] == versao
    assert campos["versao"] != D.versao('{"publica": false, "preliminares": false}')


# ======================== icones (retrabalho R1) ========================
def _hrefs_do_menu():
    from painel import navegacao
    itens = [h for _, _, links in navegacao._GRUPOS for h, _, _, _ in links]
    return itens + [h for h, _, _, _ in navegacao._ADMIN[2]]


def test_todo_item_do_menu_tem_icone_no_menu_e_no_titulo():
    """Cada endereco do menu (inclusive a Divulgacao publica) tem o seu icone no CSS do painel: no item do menu e no titulo da
    pagina atual. Sem isso o item e o titulo aparecem como quadrados vazios."""
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / "painel" / "static" / "painel.css").read_text(encoding="utf-8")
    sem_menu = [h for h in _hrefs_do_menu() if f".menu-lista a[href='{h}'] {{ --mi:" not in css]
    sem_titulo = [h for h in _hrefs_do_menu() if h != "/" and
                  f".layout:has(.menu-lista a[href='{h}'][aria-current=\"page\"]) {{ --pg-ic:" not in css]
    assert sem_menu == [] and sem_titulo == [], (sem_menu, sem_titulo)
