"""Contas, sessoes, bloqueio de senha, administracao e auditoria no PostgreSQL (painel na nuvem): as mesmas regras do
SQLite, contra um PostgreSQL real descartavel (PG_TESTE_URL). Inclui concorrencia real (varias conexoes) e o reinicio do
servidor (um processo novo, com pool novo, encontra tudo)."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from adaptadores import migrador_postgres as M
from adaptadores.contas_postgres import ContasPostgres
from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
from dominio import autenticacao as A

pytestmark = pytest.mark.postgres
SENHA = "senha-de-teste-123"


def _agora(**d):
    return (datetime.now(timezone.utc) + timedelta(**d)).isoformat()


@pytest.fixture
def pg(pg_url):
    M.aplicar(pg_url)
    pool = criar_pool(pg_url, maximo=8)
    c = ContasPostgres(pool, chaves_do_banco(pool))
    c.garantir_padrao()
    yield c, pg_url, pool
    pool.close()


def _gid(c, nome):
    return next(g["grupo_id"] for g in c.grupos() if g["nome"] == nome)


def _usuario(c, login="maria", grupo="Revisor"):
    return c.criar_usuario(login, login.title(), _gid(c, grupo), A.hash_senha(SENHA), _agora())


def test_grupos_padrao_semeados_uma_vez(pg):
    c, _, _ = pg
    antes = {g["nome"]: c.permissoes_do_grupo(g["nome"]) for g in c.grupos()}
    c.garantir_padrao()
    c.garantir_padrao()
    depois = {g["nome"]: c.permissoes_do_grupo(g["nome"]) for g in c.grupos()}
    assert antes == depois and set(depois) == set(A.GRUPOS_PADRAO)
    assert all(depois[g] == set(p) for g, p in A.GRUPOS_PADRAO.items())


def test_criar_ler_e_listar_usuario_com_auditoria(pg):
    c, _, _ = pg
    uid = c.criar_usuario("ana", "Ana", _gid(c, "Revisor"), A.hash_senha(SENHA), _agora(),
                         auditoria=("chefe", "criar_usuario", "ana", "Revisor", _agora()))
    u = c.usuario_por_login("ana")
    assert u["usuario_id"] == uid and u["grupo"] == "Revisor" and A.conferir_senha(SENHA, u["senha_hash"])
    assert [x["login"] for x in c.listar_usuarios()] == ["ana"]
    assert [(a["acao"], a["alvo"]) for a in c.auditoria()] == [("criar_usuario", "ana")]


def test_login_repetido_e_recusado_sem_quebrar_a_transacao(pg):
    c, _, _ = pg
    _usuario(c, "ana")
    with pytest.raises(ValueError):
        _usuario(c, "ana")
    assert len(c.listar_usuarios()) == 1


def test_cinco_falhas_bloqueiam_com_prazo(pg):
    c, _, _ = pg
    _usuario(c)
    agora = datetime.now(timezone.utc)
    sit = [c.reservar_tentativa("maria", agora.isoformat())["situacao"] for _ in range(6)]
    assert sit == ["reservado"] * 5 + ["bloqueado"]
    u = c.usuario_por_login("maria")
    assert u["falhas_login"] == 5 and u["bloqueado_ate"] == (agora + timedelta(minutes=A.MINUTOS_DE_BLOQUEIO)).isoformat()
    assert c.reservar_tentativa("maria", (agora + timedelta(minutes=A.MINUTOS_DE_BLOQUEIO)).isoformat())["situacao"] == "reservado"


def test_trinta_tentativas_simultaneas_reservam_no_maximo_cinco(pg):
    c, _, _ = pg
    _usuario(c)
    agora = _agora()
    resultados, trava = [], threading.Lock()

    def tenta():
        r = c.reservar_tentativa("maria", agora)["situacao"]
        with trava:
            resultados.append(r)
    fios = [threading.Thread(target=tenta) for _ in range(30)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    assert resultados.count("reservado") == 5 and resultados.count("bloqueado") == 25


def test_sessao_abre_valida_fecha_e_sobrevive_ao_reinicio(pg):
    c, url, _ = pg
    uid = _usuario(c)
    t0 = _agora()
    assert c.abrir_sessao(uid, "hash-token", t0, senha_hash=c.usuario_por_login("maria")["senha_hash"]) is True
    assert c.usuario_da_sessao("hash-token", t0)["login"] == "maria"
    novo_pool = criar_pool(url)                                   # outro processo do Cloud Run, depois de escalar para zero
    try:
        outro = ContasPostgres(novo_pool, chaves_do_banco(novo_pool))
        assert outro.usuario_da_sessao("hash-token", _agora(minutes=2))["usuario_id"] == uid
        outro.fechar_sessao("hash-token")
    finally:
        novo_pool.close()
    assert c.usuario_da_sessao("hash-token", _agora(minutes=3)) is None


def test_sessao_ociosa_e_validade_absoluta(pg):
    c, _, _ = pg
    uid = _usuario(c)
    t0 = datetime.now(timezone.utc)
    c.abrir_sessao(uid, "h1", t0.isoformat())
    assert c.usuario_da_sessao("h1", (t0 + timedelta(hours=A.HORAS_DE_SESSAO)).isoformat()) is None
    c.abrir_sessao(uid, "h2", (t0 - timedelta(days=A.DIAS_MAXIMOS_DE_SESSAO)).isoformat())
    assert c.usuario_da_sessao("h2", t0.isoformat()) is None


def test_ultimo_administrador_nao_e_rebaixado_nem_em_corrida(pg):
    c, _, _ = pg
    a1 = _usuario(c, "chefe", "Administrador")
    a2 = _usuario(c, "vice", "Administrador")
    revisor = _gid(c, "Revisor")
    erros, trava = [], threading.Lock()

    def rebaixa(uid, login):
        try:
            c.editar_usuario(uid, login, login.title(), revisor)
        except ValueError as e:
            with trava:
                erros.append(str(e))
    fios = [threading.Thread(target=rebaixa, args=a) for a in ((a1, "chefe"), (a2, "vice"))]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    assert c.contar_admins_ativos() == 1 and erros == ["O painel precisa de pelo menos um administrador ativo."]


def test_desativar_apaga_sessoes_e_audita(pg):
    c, _, _ = pg
    _usuario(c, "chefe", "Administrador")
    uid = _usuario(c)
    c.abrir_sessao(uid, "h", _agora())
    c.definir_ativo(uid, 0, auditoria=("chefe", "desativar_usuario", "maria", None, _agora()))
    assert c.usuario_da_sessao("h", _agora()) is None and c.usuario(uid)["ativo"] == 0
    assert c.auditoria()[0]["acao"] == "desativar_usuario"


def test_permissoes_e_grupo_novo(pg):
    c, _, _ = pg
    gid = c.criar_grupo("Bolsistas", _agora(), auditoria=("chefe", "criar_grupo", "Bolsistas", None, _agora()))
    c.definir_permissoes(gid, {"ver_painel", "triar_artigos"})
    assert c.permissoes_do_grupo("Bolsistas") == {"ver_painel", "triar_artigos"}
    c.renomear_grupo(gid, "Bolsistas 2026")
    assert "Bolsistas 2026" in [g["nome"] for g in c.grupos()]


def test_banco_fora_do_ar_vira_contas_ocupadas(pg_url):
    pool = criar_pool(pg_url.replace("postgres:teste@", "postgres:SENHAERRADA@"))
    pool.timeout = 2
    try:
        with pytest.raises(A.ContasOcupadas):
            ContasPostgres(pool, ()).usuario_por_login("x")
    finally:
        pool.close()


@pytest.mark.parametrize("existente,novo,recusa", [("Édson", "ÉDSON", True), ("édson", "Édson", False), ("Ana", "ANA", True)])
def test_nome_de_grupo_repetido_como_no_sqlite(pg, tmp_path, existente, novo, recusa):
    """O SQLite compara lower(nome) so com letras ASCII: 'Édson' e 'ÉDSON' sao o mesmo grupo; 'édson' e 'Édson' nao."""
    from adaptadores.contas_sqlite import ContasSQLite
    c, _, _ = pg
    lite = ContasSQLite(tmp_path / "contas.db")
    lite.garantir_padrao()
    for contas in (c, lite):
        contas.criar_grupo(existente, _agora())
        if recusa:
            with pytest.raises(ValueError):
                contas.criar_grupo(novo, _agora())
        else:
            contas.criar_grupo(novo, _agora())

