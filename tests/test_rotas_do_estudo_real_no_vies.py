"""No banco `vies`, as telas do levantamento das secretarias (Tarefa 1) nao existem: qualquer endereco delas, de qualquer
metodo, responde como um endereco que nao existe no painel. No banco real nada muda. A busca no texto fica como esta (D147)."""
import re

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from apoio_divulgacao import gravar_politica
from painel import navegacao
from painel.app import criar_app
from test_analises_vies import _cli, banco  # noqa: F401
from test_apresentacao_publica import _nunca_abre_o_data_real  # noqa: F401

SEM_O_VIES = {"/estados", "/achados", "/revisao/achados", "/classificadores", "/execucoes/comparar", "/solucoes"}
GETS = ["/estados", "/estados/PI", "/achados", "/achados/1", "/achados/casos.xlsx", "/achados/0", "/revisao/achados",
        "/revisao/achados?fila=1", "/classificadores", "/execucoes/comparar", "/execucoes/comparar?a=1&b=2", "/solucoes",
        "/estados/", "/achados/1/", "/achados/1/sugestoes/1/x/y", "/classificadores/qualquer", "/achados/99999999999999999999999"]
POSTS = ["/achados/1/verificar", "/achados/1/desfazer", "/achados/1/revogar", "/achados/1/sugerir", "/achados/1/sugestoes/1/aceitar",
         "/achados/99999999999999999999999/verificar", "/achados/99999999999999999999999/desfazer",
         "/achados/99999999999999999999999/revogar", "/achados/99999999999999999999999/sugerir",
         "/achados/1/sugestoes/99999999999999999999999/aceitar", "/estados/PI/qualquer/coisa", "/solucoes/x"]


def test_conjunto_das_telas_que_nao_existem_no_vies():
    """O conjunto e o das telas so da Tarefa 1 do menu, menos a busca no texto (publica no vies pela D147)."""
    assert getattr(navegacao, "SO_TAREFA_1_FORA_DO_VIES", None) == SEM_O_VIES == navegacao.SO_TAREFA_1 - {"/buscar-texto"}


def _sem_token(html):
    return re.sub(r'name="csrf" value="[^"]*"', 'name="csrf" value=""', html)


def _como_inexistente(cli, metodo, rota):
    r = TestClient(cli.app, raise_server_exceptions=False).request(metodo, rota, follow_redirects=False)
    ref = TestClient(cli.app, raise_server_exceptions=False).request(metodo, "/endereco-que-nao-existe", follow_redirects=False)
    return r, ref


@pytest.mark.parametrize("rota", GETS)
def test_get_no_vies_responde_como_endereco_inexistente(banco, tmp_path, rota):  # noqa: F811
    r, ref = _como_inexistente(_cli(banco, tmp_path), "GET", rota)
    assert r.status_code == ref.status_code == 404
    assert "Página não encontrada" in r.text and "O endereço não existe neste painel." in r.text
    assert _sem_token(r.text) == _sem_token(ref.text)                       # a mesma pagina, byte a byte


@pytest.mark.parametrize("rota", POSTS)
def test_post_no_vies_responde_como_endereco_inexistente(banco, tmp_path, rota):  # noqa: F811
    r, ref = _como_inexistente(_cli(banco, tmp_path), "POST", rota)
    assert r.status_code == ref.status_code == 404 and "O endereço não existe neste painel." in r.text
    assert _sem_token(r.text) == _sem_token(ref.text)


@pytest.mark.parametrize("metodo", ["PUT", "DELETE", "PATCH"])
def test_outros_metodos_no_vies_como_endereco_inexistente(banco, tmp_path, metodo):  # noqa: F811
    r, ref = _como_inexistente(_cli(banco, tmp_path), metodo, "/estados")
    assert r.status_code == ref.status_code and _sem_token(r.text) == _sem_token(ref.text)


@pytest.mark.parametrize("rota", ["/", "/execucoes", "/literatura/artigos", "/analises", "/buscar-texto", "/estadosx"])
def test_o_resto_do_vies_nao_muda(banco, tmp_path, rota):  # noqa: F811
    """Prefixo nao e parte do nome: /execucoes (sem /comparar) e /estadosx nao sao telas da Tarefa 1."""
    cli = _cli(banco, tmp_path)
    r = TestClient(cli.app, raise_server_exceptions=False).get(rota, follow_redirects=False)
    if rota == "/estadosx":
        assert r.status_code == 404
    else:
        assert r.status_code == 200, rota


SENHA = "senha-de-teste-123"


def _vies_com_login(banco, tmp_path):  # noqa: F811
    import config.settings as S
    from config import consultas as C, triagem_escopo as TE, vocabulario as V
    from config.eixos_tematicos import EIXOS_EXPLORACAO
    from datetime import datetime, timezone
    from dominio import autenticacao as A
    from painel.app import Contexto
    contas = ContasSQLite(tmp_path / "contas.db")
    gravar_politica(contas, "vies", publica=True)
    agora = datetime.now(timezone.utc).isoformat()
    contas.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), agora)
    gid = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Revisor")
    contas.criar_usuario("ana", "Ana", gid, A.hash_senha(SENHA), agora)
    leitor = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Leitor")
    contas.criar_usuario("lia", "Lia", leitor, A.hash_senha(SENHA), agora)
    ctx = Contexto(banco="vies", nome_banco="busca.db", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   termos={t.id: t.query for t in S.termos_do_banco("vies")},
                   conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                   consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                   eixos_exploracao=dict(EIXOS_EXPLORACAO), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO, autenticacao=True)
    return criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas)


def _cliente(app, login):
    cli = TestClient(app, raise_server_exceptions=False)
    if login:
        csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get("/entrar").text).group(1)
        r = cli.post("/entrar", data={"login": login, "senha": SENHA, "proximo": "/", "csrf": csrf}, follow_redirects=False)
        assert r.status_code == 303
    return cli


@pytest.mark.parametrize("login", [None, "chefe", "ana", "lia"], ids=["anonimo", "administrador", "revisor", "leitor"])
@pytest.mark.parametrize("metodo,rota", [("GET", "/estados"), ("GET", "/achados/1"), ("GET", "/solucoes"),
                                         ("GET", "/revisao/achados"), ("GET", "/classificadores"), ("GET", "/execucoes/comparar"),
                                         ("POST", "/achados/1/verificar"), ("POST", "/achados/1/sugestoes/1/aceitar")])
def test_com_login_cada_perfil_ve_o_mesmo_que_num_endereco_inexistente(banco, tmp_path, login, metodo, rota):  # noqa: F811
    cli = _cliente(_vies_com_login(banco, tmp_path), login)
    r = cli.request(metodo, rota, follow_redirects=False)
    ref = cli.request(metodo, "/endereco-que-nao-existe", follow_redirects=False)
    from urllib.parse import quote
    assert r.status_code == ref.status_code
    esperado = (ref.headers.get("location") or "").replace(quote("/endereco-que-nao-existe", safe=""), quote(rota, safe=""))
    assert (r.headers.get("location") or "") == esperado               # o mesmo redirecionamento, com o proprio endereco
    assert _sem_token(r.text) == _sem_token(ref.text).replace("/endereco-que-nao-existe", rota) or r.text == ref.text


@pytest.mark.parametrize("com_login", [True, False])
def test_links_do_vies_nao_levam_as_telas_que_nao_existem(banco, tmp_path, com_login):  # noqa: F811
    """A regra unica de links (pode_seguir) nega essas telas no vies: a busca no texto (publica, D147) e a lista de execucoes
    nao apontam para elas, com e sem login."""
    cli = _cliente(_vies_com_login(banco, tmp_path), "chefe") if com_login else _cli(banco, tmp_path)
    for pagina in ("/buscar-texto", "/buscar-texto?q=reconhecimento", "/", "/execucoes"):
        h = cli.get(pagina).text
        for alvo in SEM_O_VIES:
            assert f'href="{alvo}"' not in h and f'href="{alvo}/' not in h and f'href="{alvo}?' not in h, (pagina, alvo)


@pytest.mark.parametrize("rota", ["/estados", "/achados", "/solucoes", "/classificadores", "/execucoes/comparar"])
def test_no_banco_real_as_telas_continuam(rota, tmp_path):
    from test_painel import _app, demo  # noqa: F401
    import shutil
    import painel_demo
    banco_demo = painel_demo.construir(tmp_path / "modelo")
    copia = tmp_path / "demo.db"
    shutil.copy(banco_demo, copia)
    app, _c = _app(copia, tmp_path / "modelo" / "raw_demo", tmp_path)
    r = TestClient(app, raise_server_exceptions=False).get(rota, follow_redirects=False)
    assert r.status_code == 200, rota


def test_a_regra_vem_de_uma_funcao_unica_da_navegacao(banco, tmp_path, monkeypatch):  # noqa: F811
    """Ancora: o painel decide pela funcao `navegacao.fora_do_vies`; trocada por outra, o comportamento segue a troca."""
    assert getattr(navegacao, "fora_do_vies", None) is not None
    assert navegacao.fora_do_vies("/estados/PI/") and navegacao.fora_do_vies("/achados")
    assert not navegacao.fora_do_vies("/estadosx") and not navegacao.fora_do_vies("/execucoes")
    monkeypatch.setattr(navegacao, "fora_do_vies", lambda caminho: caminho.startswith("/analises"))
    cli = TestClient(_cli(banco, tmp_path).app, raise_server_exceptions=False)
    assert cli.get("/analises").status_code == 404 and cli.get("/estados").status_code == 200


def test_producao_nao_usa_o_endereco_de_referencia_dos_testes():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "painel" / "app.py").read_text(encoding="utf-8")
    assert "/endereco-que-nao-existe" not in fonte
