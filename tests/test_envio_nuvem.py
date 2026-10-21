"""Envio da coleta para o painel na nuvem (D98, D99): a rota POST /api/coletas (token, permissao, limites, respostas
JSON), o cliente do comando `enviar` e a composicao pelo .env. Sem rede: o cliente fala com o painel de teste."""
import gzip
import json
import re
import shutil
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.envio_nuvem import EnvioNuvem, ErroEnvio
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from painel.app import Contexto, criar_app
from painel.rotas_extras import api

SENHA = "senha-de-teste-123"


def _agora():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def nuvem(copiar_demo, tmp_path):
    """Painel com login sobre um banco central vazio, um usuario com token e permissao de enviar, e o banco local."""
    banco_local, raw = copiar_demo("envio_local")
    central = tmp_path / "central.db"
    RepositorioSQLite(central).fechar()
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    contas.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), _agora())
    gid = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Revisor")
    contas.definir_permissoes(gid, set(A.GRUPOS_PADRAO["Revisor"]) | {"enviar_coletas"})
    uid = contas.criar_usuario("maria", "Maria", gid, A.hash_senha(SENHA), _agora())
    token = A.gerar_token_api()
    contas.gravar_token(uid, A.hash_token(token), A.inicio_do_token(token), _agora())
    ctx = Contexto(banco="real", nome_banco="central", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver",), autenticacao=True, aceita_envios=True)
    cli = TestClient(criar_app(LeituraPainelSQLite(central), lambda: RepositorioSQLite(central), BrutoLocal(tmp_path / "vazio"),
                               ctx, contas=contas))
    local = RepositorioSQLite(banco_local)
    yield SimpleNamespace(cli=cli, contas=contas, central=central, token=token, uid=uid, gid=gid, local=local, ctx=ctx)
    local.fechar()


def _runs(local):
    todas = [r for (r,) in local.conn.execute("SELECT run_id FROM execucoes ORDER BY run_id")]
    depende = {r: {e["run_id"] for e in local.pacote_da_execucao(r)["externas"]["paginas"]} for r in todas}
    ordem = []
    while len(ordem) < len(todas):
        ordem.append(next(r for r in todas if r not in ordem and depende[r] <= set(ordem)))
    return ordem


def _post(n, corpo, token=None, gzipado=True, cabecalhos=None):
    h = {"Content-Type": "application/json"}
    if token is not False:
        h["Authorization"] = f"Bearer {token or n.token}"
    if gzipado:
        h["Content-Encoding"] = "gzip"
    h.update(cabecalhos or {})
    return n.cli.post("/api/coletas", content=gzip.compress(corpo) if gzipado else corpo, headers=h)


def _pacote_bytes(n, run):
    return json.dumps(n.local.pacote_da_execucao(run), ensure_ascii=False).encode("utf-8")


def _corpo_erro(r):
    assert r.headers.get("cache-control") == "no-store" and r.headers["content-type"].startswith("application/json")
    return r.json()["erro"]


# ---------- autenticacao e permissao ----------
@pytest.mark.parametrize("cabecalho,mensagem", [
    (None, api.SEM_TOKEN), ("Basic abc", api.SEM_TOKEN), ("Bearer", api.SEM_TOKEN), ("bearer srsp_" + "a" * 43, api.SEM_TOKEN),
    ("Bearer srsp_curto", api.TOKEN_INVALIDO), ("Bearer srsp_" + "a" * 44, api.TOKEN_INVALIDO),
    ("Bearer " + "srsp_" + "a" * 43, api.TOKEN_INVALIDO),            # formato certo, token que nao existe
])
def test_token_ausente_ou_invalido(nuvem, cabecalho, mensagem):
    h = {} if cabecalho is None else {"Authorization": cabecalho}
    r = nuvem.cli.post("/api/coletas", content=b"{}", headers=h)
    assert r.status_code == 401 and _corpo_erro(r) == mensagem


def test_sem_sessao_a_api_nao_redireciona_para_a_entrada(nuvem):
    r = nuvem.cli.post("/api/coletas", content=b"{}", follow_redirects=False)
    assert r.status_code == 401 and "location" not in r.headers


@pytest.mark.parametrize("caminho", ["/api/outra", "/api/coletas/", "/api/coletas/x", "/api", "/API/coletas"])
def test_so_o_endereco_exato_dispensa_a_sessao(nuvem, caminho):
    r = nuvem.cli.post(caminho, content=b"{}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar")


def test_token_revogado_ou_conta_desativada(nuvem):
    nuvem.contas.revogar_token(nuvem.uid)
    assert _corpo_erro(_post(nuvem, b"{}")) == api.TOKEN_INVALIDO
    novo = A.gerar_token_api()
    nuvem.contas.gravar_token(nuvem.uid, A.hash_token(novo), A.inicio_do_token(novo), _agora())
    nuvem.contas.definir_ativo(nuvem.uid, 0)
    assert _post(nuvem, b"{}", token=novo).status_code == 401


def test_grupo_sem_a_permissao(nuvem):
    nuvem.contas.definir_permissoes(nuvem.gid, set(A.GRUPOS_PADRAO["Revisor"]))
    r = _post(nuvem, _pacote_bytes(nuvem, _runs(nuvem.local)[0]))
    assert r.status_code == 403 and _corpo_erro(r) == api.SEM_PERMISSAO
    assert sqlite3.connect(nuvem.central).execute("SELECT COUNT(*) FROM execucoes").fetchone() == (0,)


def test_banco_de_contas_ocupado(nuvem, monkeypatch):
    def ocupado(*a, **k):
        raise A.ContasOcupadas("x")
    monkeypatch.setattr(type(nuvem.contas), "usuario_do_token", ocupado)
    r = _post(nuvem, b"{}")
    assert r.status_code == 503 and _corpo_erro(r) == api.CONTAS_OCUPADAS


# ---------- corpo ----------
@pytest.mark.parametrize("corpo,gzipado", [(b"nao e json", True), (b"nao e json", False), (b"\xff\xfe{}", False)])
def test_corpo_que_nao_e_json(nuvem, corpo, gzipado):
    r = _post(nuvem, corpo, gzipado=gzipado)
    assert r.status_code == 400 and _corpo_erro(r) == api.NAO_JSON


def test_gzip_quebrado(nuvem):
    r = nuvem.cli.post("/api/coletas", content=gzip.compress(b'{"a": 1}')[:-6],
                       headers={"Authorization": f"Bearer {nuvem.token}", "Content-Encoding": "gzip"})
    assert r.status_code == 400 and _corpo_erro(r) == api.NAO_JSON


def test_limites_de_tamanho(nuvem, monkeypatch):
    assert (api.MAX_CORPO, api.MAX_DESCOMPACTADO) == (16 * 1024 * 1024, 64 * 1024 * 1024)
    monkeypatch.setattr(api, "MAX_CORPO", 100)
    r = _post(nuvem, b" " * 101, gzipado=False)
    assert r.status_code == 413 and _corpo_erro(r) == api.GRANDE_DEMAIS
    assert _corpo_erro(_post(nuvem, b" " * 100, gzipado=False)) == api.NAO_JSON        # no limite: lido (e nao e JSON)
    monkeypatch.setattr(api, "MAX_CORPO", 10 ** 6)
    monkeypatch.setattr(api, "MAX_DESCOMPACTADO", 1000)
    r = _post(nuvem, b" " * 1001)
    assert r.status_code == 413 and _corpo_erro(r) == api.GRANDE_DEMAIS
    assert _corpo_erro(_post(nuvem, b" " * 1000)) == api.NAO_JSON


def test_bomba_de_gzip_nao_e_descompactada_inteira(nuvem, monkeypatch):
    """O limite vale durante a descompactacao: nunca se descompacta mais do que MAX_DESCOMPACTADO + 1 bytes."""
    import zlib
    original = zlib.decompressobj
    maximo = []

    class Espiao:
        def __init__(self, *a, **k):
            self._d = original(*a, **k)

        def decompress(self, dados, max_length=0):
            maximo.append(max_length)
            return self._d.decompress(dados, max_length)

        def __getattr__(self, nome):
            return getattr(self._d, nome)
    monkeypatch.setattr(api.zlib, "decompressobj", Espiao)
    r = _post(nuvem, b" " * (8 * 1024 * 1024))
    assert r.status_code == 200 or r.status_code == 400
    assert maximo == [api.MAX_DESCOMPACTADO + 1]


def test_gzip_com_lixo_depois_do_fim(nuvem):
    r = nuvem.cli.post("/api/coletas", content=gzip.compress(b'{"a": 1}') + b"lixo",
                       headers={"Authorization": f"Bearer {nuvem.token}", "Content-Encoding": "gzip"})
    assert r.status_code == 400 and _corpo_erro(r) == api.NAO_JSON


def test_um_envio_por_vez(nuvem):
    assert api._UM_ENVIO_POR_VEZ.acquire(blocking=False)
    try:
        r = _post(nuvem, _pacote_bytes(nuvem, _runs(nuvem.local)[0]))
        assert r.status_code == 503 and _corpo_erro(r) == api.OCUPADO
    finally:
        api._UM_ENVIO_POR_VEZ.release()
    assert sqlite3.connect(nuvem.central).execute("SELECT COUNT(*) FROM execucoes").fetchone() == (0,)
    assert _post(nuvem, _pacote_bytes(nuvem, _runs(nuvem.local)[0])).status_code == 200


def test_ultimo_uso_so_no_envio_aceito(nuvem):
    assert _post(nuvem, b"nao e json").status_code == 400
    assert nuvem.contas.token_do_usuario(nuvem.uid)["ultimo_uso"] is None
    assert _post(nuvem, _pacote_bytes(nuvem, _runs(nuvem.local)[0])).status_code == 200
    assert nuvem.contas.token_do_usuario(nuvem.uid)["ultimo_uso"] is not None


def test_pacote_invalido(nuvem):
    r = _post(nuvem, b'{"versao": 1, "run_id": "x", "tabelas": {}, "externas": {"paginas": []}}')
    assert r.status_code == 400 and _corpo_erro(r) == "Pacote recusado: Versão do pacote não suportada: 1 (esta nuvem aceita 2)."


# ---------- envio que grava ----------
def test_envio_grava_e_reenvio_nao_muda_nada(nuvem):
    run = _runs(nuvem.local)[0]
    r = _post(nuvem, _pacote_bytes(nuvem, run))
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-store"
    corpo = r.json()
    assert corpo["run_id"] == run and sum(v["novas"] for v in corpo["tabelas"].values()) > 0
    c = sqlite3.connect(nuvem.central)
    assert c.execute("SELECT run_id, usuario_id FROM envios_execucao").fetchall() == [(run, nuvem.uid)]
    assert nuvem.contas.token_do_usuario(nuvem.uid)["ultimo_uso"] is not None
    de_novo = _post(nuvem, _pacote_bytes(nuvem, run), gzipado=False).json()
    assert all(v["novas"] == 0 and v["atualizadas"] == 0 for v in de_novo["tabelas"].values())


def test_execucao_de_outro_usuario(nuvem):
    run = _runs(nuvem.local)[0]
    _post(nuvem, _pacote_bytes(nuvem, run))
    outro = nuvem.contas.criar_usuario("joao", "Joao", nuvem.gid, A.hash_senha(SENHA), _agora())
    t = A.gerar_token_api()
    nuvem.contas.gravar_token(outro, A.hash_token(t), A.inicio_do_token(t), _agora())
    r = _post(nuvem, _pacote_bytes(nuvem, run), token=t)
    assert r.status_code == 400 and _corpo_erro(r) == (
        f"A execução {run} foi enviada por outro usuário: só quem a enviou primeiro pode reenviá-la.")


@pytest.mark.parametrize("erro,mensagem", [(sqlite3.OperationalError("database is locked"), api.OCUPADO),
                                           (RuntimeError("qualquer outra"), api.FALHA)])
def test_falha_ao_gravar(nuvem, monkeypatch, erro, mensagem):
    def falha(*a, **k):
        raise erro
    monkeypatch.setattr(RepositorioSQLite, "juntar_pacote", falha)
    r = _post(nuvem, _pacote_bytes(nuvem, _runs(nuvem.local)[0]))
    assert r.status_code == 503 and _corpo_erro(r) == mensagem


@pytest.mark.parametrize("metodo", ["GET", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_outro_metodo_recebe_405_em_json(nuvem, metodo):
    r = nuvem.cli.request(metodo, "/api/coletas", follow_redirects=False)           # sem token e sem sessao
    assert r.status_code == 405 and r.headers["allow"] == "POST" and _corpo_erro(r) == api.METODO


def test_head_recebe_405_sem_corpo(nuvem):
    r = nuvem.cli.head("/api/coletas", follow_redirects=False)
    assert r.status_code == 405 and r.headers.get("allow") == "POST" and r.headers.get("cache-control") == "no-store"
    assert r.content == b""


@pytest.mark.parametrize("corpo", [
    b'{"versao": 2, "versao": 1}',                       # chave repetida no topo
    b'{"tabelas": {"chamadas": [], "chamadas": []}}',     # chave repetida dentro de um objeto
    b'[{"x": 1, "x": 1}]',                               # dentro de uma lista, mesmo valor
    b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}', b'[NaN]',
    b'{"a": "\\ud800"}', b'{"\\udfff": 1}', b'["x\\ud83d"]',      # surrogate solto: JSON valido, texto invalido
])
@pytest.mark.parametrize("gzipado", [True, False])
def test_json_com_chave_repetida_ou_constante_fora_do_padrao(nuvem, corpo, gzipado):
    r = _post(nuvem, corpo, gzipado=gzipado)
    assert r.status_code == 400 and _corpo_erro(r) == api.NAO_JSON


def test_chaves_que_diferem_so_na_caixa_nao_sao_repetidas(nuvem):
    r = _post(nuvem, b'{"a": 1, "A": 1}')
    assert r.status_code == 400 and _corpo_erro(r) != api.NAO_JSON         # e JSON; o pacote e que nao vale


def test_falha_inesperada_registra_so_a_execucao_e_o_tipo(nuvem, monkeypatch, caplog):
    def falha(*a, **k):
        raise RuntimeError("detalhe interno com dado do pacote")
    monkeypatch.setattr(RepositorioSQLite, "juntar_pacote", falha)
    run = _runs(nuvem.local)[0]
    with caplog.at_level("DEBUG"):
        r = _post(nuvem, _pacote_bytes(nuvem, run))
    assert r.status_code == 503 and _corpo_erro(r) == api.FALHA
    registros = [x for x in caplog.records if x.name == api.__name__]
    assert [(x.levelname, x.getMessage(), x.exc_info) for x in registros] == [
        ("ERROR", f"falha ao juntar o envio da execução {run}: RuntimeError", None)]
    assert "detalhe interno" not in caplog.text


@pytest.mark.parametrize("autenticacao,aceita", [(True, False), (False, True), (False, False)])
def test_api_so_no_painel_da_nuvem(nuvem, tmp_path, autenticacao, aceita):
    """No painel sobre SQLite (local ou servidor) a juntada seguraria o banco da pesquisa: a rota nao existe."""
    ctx = Contexto(banco="real", nome_banco="x", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   autenticacao=autenticacao, aceita_envios=aceita)
    cli = TestClient(criar_app(LeituraPainelSQLite(nuvem.central), lambda: RepositorioSQLite(nuvem.central), BrutoLocal(tmp_path),
                               ctx, contas=nuvem.contas if autenticacao else None))
    r = cli.post("/api/coletas", content=b"{}", headers={"Authorization": f"Bearer {nuvem.token}"}, follow_redirects=False)
    assert r.status_code in (303, 404, 405) and "application/json" not in r.headers.get("content-type", "")


def test_painel_sem_login_nao_tem_api(nuvem, tmp_path):
    ctx = Contexto(banco="demo", nome_banco="x", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   autenticacao=False)
    cli = TestClient(criar_app(LeituraPainelSQLite(nuvem.central), lambda: RepositorioSQLite(nuvem.central),
                               BrutoLocal(tmp_path), ctx))
    assert cli.post("/api/coletas", content=b"{}").status_code in (404, 405)


# ---------- o cliente do comando enviar ----------
def _chamar_no_painel(cli, registro):
    """Um chamar_http que fala com o painel de teste (sem rede), guardando o que foi enviado."""
    def chamar(metodo, url, *, corpo=None, headers=None, timeout=None, max_tentativas=None, **_):
        registro.append({"metodo": metodo, "url": url, "corpo": corpo, "headers": dict(headers), "timeout": timeout,
                         "max_tentativas": max_tentativas})
        r = cli.request(metodo, "/api/coletas", content=corpo, headers=headers)
        return {"resp": r, "http_status": r.status_code, "erro": None}
    return chamar


def test_cliente_envia_todas_as_execucoes_pelo_painel(nuvem):
    registro = []
    envio = EnvioNuvem("https://painel.exemplo/", nuvem.token, chamar_http=_chamar_no_painel(nuvem.cli, registro))
    for run in _runs(nuvem.local):
        resp = envio.enviar(nuvem.local.pacote_da_execucao(run))
        assert resp["run_id"] == run
    feito = registro[0]
    assert feito["metodo"] == "POST" and feito["url"] == "https://painel.exemplo/api/coletas" and feito["timeout"] == (10, 900)
    assert all(x["max_tentativas"] == 1 for x in registro)              # sem nova tentativa automatica
    assert feito["headers"] == {"Authorization": f"Bearer {nuvem.token}", "Content-Type": "application/json", "Content-Encoding": "gzip"}
    assert json.loads(gzip.decompress(feito["corpo"]))["versao"] == 2
    n_local = nuvem.local.conn.execute("SELECT COUNT(*) FROM chamadas").fetchone()[0]
    assert sqlite3.connect(nuvem.central).execute("SELECT COUNT(*) FROM chamadas").fetchone()[0] == n_local


@pytest.mark.parametrize("resposta,mensagem", [
    ({"resp": None, "erro": "ConnectionError(...)"},
     "Não foi possível falar com a nuvem (confira PAINEL_NUVEM_URL e a internet): ConnectionError(...)"),
    ({"resp": None, "erro": None}, "Não foi possível falar com a nuvem (confira PAINEL_NUVEM_URL e a internet): sem resposta"),
    ({"resp": SimpleNamespace(status_code=400, json=lambda: {"erro": "Pacote recusado: x."})},
     "A nuvem recusou o envio (HTTP 400): Pacote recusado: x."),
    ({"resp": SimpleNamespace(status_code=502, json=lambda: (_ for _ in ()).throw(ValueError()))},
     "A nuvem recusou o envio (HTTP 502): resposta sem mensagem"),
    ({"resp": SimpleNamespace(status_code=200, json=lambda: {"run_id": "x"})},
     "A nuvem recusou o envio (HTTP 200): resposta sem mensagem"),
])
def test_cliente_erros(resposta, mensagem):
    envio = EnvioNuvem("https://painel.exemplo", "srsp_" + "a" * 43, chamar_http=lambda *a, **k: resposta)
    with pytest.raises(ErroEnvio) as e:
        envio.enviar({"versao": 1})
    assert str(e.value) == mensagem


# ---------- composicao pelo .env ----------
TOKEN_OK = "srsp_" + "b" * 43


@pytest.mark.parametrize("url,token,mensagem", [
    (None, TOKEN_OK, "Defina PAINEL_NUVEM_URL no .env: o endereço do painel na nuvem (https://...)."),
    ("  ", TOKEN_OK, "Defina PAINEL_NUVEM_URL no .env: o endereço do painel na nuvem (https://...)."),
    ("http://painel.exemplo", TOKEN_OK,
     "PAINEL_NUVEM_URL precisa ser só o endereço do painel, começando com https:// (ou http://localhost para teste)."),
    ("https://painel.exemplo/api/coletas", TOKEN_OK,
     "PAINEL_NUVEM_URL precisa ser só o endereço do painel, começando com https:// (ou http://localhost para teste)."),
    ("https://painel.exemplo?x=1", TOKEN_OK,
     "PAINEL_NUVEM_URL precisa ser só o endereço do painel, começando com https:// (ou http://localhost para teste)."),
    ("https://painel.exemplo", None, "Defina PAINEL_TOKEN no .env: o token da sua página Minha conta no painel."),
    ("https://painel.exemplo", "srsp_curto", "PAINEL_TOKEN não tem o formato de um token do painel (srsp_ e mais 43 caracteres)."),
])
def test_envio_nuvem_recusa_configuracao(monkeypatch, url, token, mensagem):
    import composicao
    for nome, valor in (("PAINEL_NUVEM_URL", url), ("PAINEL_TOKEN", token)):
        if valor is None:
            monkeypatch.delenv(nome, raising=False)
        else:
            monkeypatch.setenv(nome, valor)
    with pytest.raises(SystemExit) as e:
        composicao.Fabrica(simulado=True).envio_nuvem()
    assert str(e.value) == mensagem


@pytest.mark.parametrize("url,esperada", [("https://painel-1.southamerica-east1.run.app", "https://painel-1.southamerica-east1.run.app/api/coletas"),
                                          ("https://painel.exemplo/", "https://painel.exemplo/api/coletas"),
                                          ("http://localhost:8765", "http://localhost:8765/api/coletas")])
def test_envio_nuvem_aceita(monkeypatch, url, esperada):
    import composicao
    monkeypatch.setenv("PAINEL_NUVEM_URL", url)
    monkeypatch.setenv("PAINEL_TOKEN", TOKEN_OK)
    assert composicao.Fabrica(simulado=True).envio_nuvem().url == esperada


def test_comando_enviar_para_no_primeiro_erro(nuvem, capsys):
    import main
    registro = []
    runs = _runs(nuvem.local)
    fab = SimpleNamespace(repo=nuvem.local,
                          envio_nuvem=lambda: EnvioNuvem("https://p.exemplo", nuvem.token, _chamar_no_painel(nuvem.cli, registro)))
    main.enviar_execucoes(SimpleNamespace(run=[runs[0], runs[0], runs[1]]), fab)
    saida = capsys.readouterr().out.strip().splitlines()
    assert len(saida) == 2 and len(registro) == 2                       # a repetida vai uma vez so
    assert re.fullmatch(rf"Execução {runs[0]} enviada: \d+ linhas novas, 0 atualizadas, 0 iguais\.", saida[0])
    with pytest.raises(SystemExit) as e:
        main.enviar_execucoes(SimpleNamespace(run=["20990101_000000_aaaaaa", runs[2]]), fab)
    assert str(e.value) == "A execução 20990101_000000_aaaaaa não existe neste banco." and len(registro) == 2


def test_comando_enviar_para_quando_a_nuvem_recusa(nuvem):
    import main
    registro = []
    runs = _runs(nuvem.local)
    nuvem.contas.definir_permissoes(nuvem.gid, set(A.GRUPOS_PADRAO["Revisor"]))
    fab = SimpleNamespace(repo=nuvem.local, envio_nuvem=lambda: EnvioNuvem("https://p.exemplo", nuvem.token, _chamar_no_painel(nuvem.cli, registro)))
    with pytest.raises(SystemExit) as e:
        main.enviar_execucoes(SimpleNamespace(run=[runs[0], runs[1]]), fab)
    assert str(e.value) == f"Execução {runs[0]}: A nuvem recusou o envio (HTTP 403): {api.SEM_PERMISSAO}" and len(registro) == 1


def test_comando_enviar_mostra_a_recusa_da_nuvem(nuvem):
    import main
    nuvem.contas.revogar_token(nuvem.uid)
    fab = SimpleNamespace(repo=nuvem.local, envio_nuvem=lambda: EnvioNuvem("https://p.exemplo", nuvem.token, _chamar_no_painel(nuvem.cli, [])))
    run = _runs(nuvem.local)[0]
    with pytest.raises(SystemExit) as e:
        main.enviar_execucoes(SimpleNamespace(run=[run]), fab)
    assert str(e.value) == f"Execução {run}: A nuvem recusou o envio (HTTP 401): {api.TOKEN_INVALIDO}"


# ---------- brutos na nuvem ----------
def test_na_nuvem_o_bruto_fica_no_computador_da_coleta(nuvem):
    run = _runs(nuvem.local)[0]
    _post(nuvem, _pacote_bytes(nuvem, run))
    cid = sqlite3.connect(nuvem.central).execute("SELECT MIN(chamada_id) FROM chamadas WHERE raw_path IS NOT NULL").fetchone()[0]
    from test_admin import _entrar
    _entrar(nuvem.cli, "chefe")
    assert "O arquivo bruto não foi encontrado em data/raw." in nuvem.cli.get(f"/chamadas/{cid}").text
    nuvem.ctx.brutos_aqui = False
    assert "O arquivo bruto fica no computador onde a coleta rodou: ele não é enviado para a nuvem." in nuvem.cli.get(f"/chamadas/{cid}").text
    r = nuvem.cli.get(f"/chamadas/{cid}/bruto")
    assert r.status_code == 404 and "ele não é enviado para a nuvem" in r.text


# ---------- PostgreSQL: trava propria dos envios ----------
@pytest.mark.postgres
def test_envio_no_postgres_nao_para_as_gravacoes_do_painel(pg_url, copiar_demo):
    import sqlite3 as s3
    import threading
    import time
    from adaptadores import migrador_postgres as M
    from adaptadores.postgres import conexao as X
    from adaptadores.repositorio_postgres import RepositorioPostgres
    M.aplicar(pg_url)
    pool = X.criar_pool(pg_url, maximo=4)
    chaves = X.chaves_do_banco(pool)
    try:
        envio = X.ConexaoPostgres(pool, chaves)
        painel = X.ConexaoPostgres(pool, chaves)
        with envio.modo_envio():
            assert (envio._chave_trava, envio._sem_savepoint) == (X.TRAVA_ENVIO, True)
            envio.execute("BEGIN IMMEDIATE")              # um envio longo segura a trava dos envios
            inicio = time.monotonic()
            painel.execute("BEGIN IMMEDIATE")             # o painel grava sem esperar
            assert time.monotonic() - inicio < 2
            painel.rollback()
            outro = X.ConexaoPostgres(pool, chaves)
            erros = []

            def segundo_envio():
                try:
                    with outro.modo_envio():
                        outro.execute("BEGIN IMMEDIATE")
                        erros.append(("travou", time.monotonic() - inicio))
                        outro.rollback()
                except s3.OperationalError as e:
                    erros.append(str(e))
            f = threading.Thread(target=segundo_envio)
            f.start()
            time.sleep(0.6)
            envio.rollback()
            f.join(10)
            assert erros and erros[0][0] == "travou" and erros[0][1] >= 0.5      # dois envios: um de cada vez
            outro.close()
        assert (envio._chave_trava, envio._sem_savepoint) == (X.TRAVA_ESCRITA, False)     # o modo termina com o bloco
        envio.close()
        painel.close()
        banco, _ = copiar_demo("envio_pg")
        local = RepositorioSQLite(banco)
        run = _runs(local)[0]
        repo = RepositorioPostgres(pool, chaves)
        try:
            rel = repo.juntar_pacote(json.loads(json.dumps(local.pacote_da_execucao(run))), 1, _agora())
            assert sum(v["novas"] for v in rel.values()) > 0
        finally:
            repo.fechar()
            local.fechar()
    finally:
        pool.close()


@pytest.mark.postgres
def test_api_inteira_sobre_postgres(pg_url, copiar_demo, tmp_path):
    """O caminho completo da nuvem: ContasPostgres (token), RepositorioPostgres (juntada em modo de envio), resposta,
    reenvio sem mudanca e falha no meio sem nada gravado e com a conexao do pool limpa."""
    import psycopg
    from adaptadores import migrador_postgres as M
    from adaptadores.contas_postgres import ContasPostgres
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    from adaptadores.repositorio_postgres import RepositorioPostgres
    M.aplicar(pg_url)
    pool = criar_pool(pg_url, maximo=4)
    chaves = chaves_do_banco(pool)
    contas = ContasPostgres(pool, chaves)
    contas.garantir_padrao()
    contas.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), _agora())
    gid = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Revisor")
    contas.definir_permissoes(gid, set(A.GRUPOS_PADRAO["Revisor"]) | {"enviar_coletas"})
    uid = contas.criar_usuario("maria", "Maria", gid, A.hash_senha(SENHA), _agora())
    token = A.gerar_token_api()
    contas.gravar_token(uid, A.hash_token(token), A.inicio_do_token(token), _agora())
    assert contas.usuario_do_token(A.hash_token(token))["usuario_id"] == uid
    ctx = Contexto(banco="real", nome_banco="PostgreSQL", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver",), autenticacao=True, aceita_envios=True, brutos_aqui=False)
    cli = TestClient(criar_app(LeituraPainelPostgres(pool, chaves), lambda: RepositorioPostgres(pool, chaves), BrutoLocal(tmp_path),
                               ctx, contas=contas))
    banco, _ = copiar_demo("api_pg")
    local = RepositorioSQLite(banco)
    try:
        run = _runs(local)[0]
        corpo = gzip.compress(json.dumps(local.pacote_da_execucao(run)).encode())
        h = {"Authorization": f"Bearer {token}", "Content-Encoding": "gzip", "Content-Type": "application/json"}
        r = cli.post("/api/coletas", content=corpo, headers=h)
        assert r.status_code == 200 and sum(v["novas"] for v in r.json()["tabelas"].values()) > 0
        de_novo = cli.post("/api/coletas", content=corpo, headers=h).json()
        assert all(v["novas"] == 0 and v["atualizadas"] == 0 for v in de_novo["tabelas"].values())
        assert contas.token_do_usuario(uid)["ultimo_uso"] is not None
        outro = _runs(local)[1]
        from adaptadores import pacote_coleta as J
        original = J._alvo_central

        def falha(etapa, alvo, mapa):
            raise RuntimeError("falhou no meio")
        J._alvo_central = falha
        try:
            r = cli.post("/api/coletas", content=gzip.compress(json.dumps(local.pacote_da_execucao(outro)).encode()), headers=h)
        finally:
            J._alvo_central = original
        assert r.status_code == 503 and r.json()["erro"] == api.FALHA
        with psycopg.connect(pg_url) as c:
            assert c.execute("SELECT COUNT(*) FROM execucoes WHERE run_id = %s", (outro,)).fetchone()[0] == 0
        assert pool.get_stats()["pool_available"] >= 1
        r = cli.post("/api/coletas", content=gzip.compress(json.dumps(local.pacote_da_execucao(outro)).encode()), headers=h)
        assert r.status_code == 200
    finally:
        local.fechar()
        pool.close()

