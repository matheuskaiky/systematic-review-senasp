"""Sessao recem-criada e relogio que recua: a sessao nunca renovada (ultimo uso igual a criacao) tolera ate 2 s de relogio
atrasado no pedido seguinte; fora disso, horario no futuro continua invalidando a sessao, e ociosidade, validade absoluta e
revogacao nao mudam. Vale no SQLite e no PostgreSQL (a mesma regra herdada)."""
from datetime import datetime, timedelta, timezone

import pytest

from dominio import autenticacao as A
from test_autenticacao import _con, _criar, _entrar, _usuario, contas, painel  # noqa: F401
from test_painel import demo  # noqa: F401

DOIS = timedelta(seconds=2)
UM_US = timedelta(microseconds=1)


def test_constante():
    assert A.TOLERANCIA_RELOGIO_NA_CRIACAO_SEGUNDOS == 2


def _sessao(c, caminho, criada, ultimo, login="maria"):
    uid = _usuario(c, caminho, login=login)
    c.abrir_sessao(uid, "h1", criada.isoformat())
    db = _con(caminho)
    db.execute("UPDATE sessoes SET criada_em=?, ultimo_uso=? WHERE token_hash='h1'", (criada.isoformat(), ultimo.isoformat()))
    db.commit()
    return uid


def _linhas(caminho):
    return _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0]


# (criada - agora, ultimo - agora, valida): a tolerancia so vale quando ultimo == criada (sessao nunca renovada)
CASOS = [
    (timedelta(0), timedelta(0), True),
    (UM_US, UM_US, True),
    (timedelta(seconds=1), timedelta(seconds=1), True),
    (DOIS, DOIS, True),                                   # a fronteira entra
    (DOIS + UM_US, DOIS + UM_US, False),                  # passou da fronteira
    (timedelta(days=30), timedelta(days=30), False),
    # sessao ja renovada (ultimo != criada): nenhuma tolerancia, como antes
    (-timedelta(hours=1), UM_US, False),
    (-timedelta(hours=1), timedelta(seconds=1), False),
    (UM_US, -timedelta(hours=1), False),                  # criacao no futuro com ultimo uso no passado
    (timedelta(seconds=1), timedelta(seconds=1, microseconds=1), False),   # diferem por 1 µs: nao e recem-criada
    (timedelta(seconds=1, microseconds=1), timedelta(seconds=1), False),
    (-timedelta(hours=1), -timedelta(minutes=5), True),
]


@pytest.mark.parametrize("criada,ultimo,valida", CASOS)
def test_tolerancia_so_na_sessao_nunca_renovada_sqlite(contas, criada, ultimo, valida):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    _sessao(c, caminho, agora + criada, agora + ultimo)
    assert (c.usuario_da_sessao("h1", agora.isoformat()) is not None) is valida
    assert _linhas(caminho) == (1 if valida else 0)


def test_sessao_tolerada_nao_e_renovada_nem_alterada(contas):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    _sessao(c, caminho, agora + timedelta(seconds=1), agora + timedelta(seconds=1))
    antes = _con(caminho).execute("SELECT criada_em, ultimo_uso FROM sessoes").fetchone()
    assert c.usuario_da_sessao("h1", agora.isoformat()) is not None
    assert _con(caminho).execute("SELECT criada_em, ultimo_uso FROM sessoes").fetchone() == antes


def test_ociosidade_validade_absoluta_e_revogacao_nao_mudam(contas):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    horas, dias = timedelta(hours=A.HORAS_DE_SESSAO), timedelta(days=A.DIAS_MAXIMOS_DE_SESSAO)
    # ociosidade: exatamente 12 h recusa; 12 h - 1 µs vale
    _sessao(c, caminho, agora - horas, agora - horas)
    assert c.usuario_da_sessao("h1", agora.isoformat()) is None
    _sessao(c, caminho, agora - horas + UM_US, agora - horas + UM_US, login="u1")
    assert c.usuario_da_sessao("h1", agora.isoformat()) is not None
    # validade absoluta: 7 dias recusa, mesmo com uso recente
    _con(caminho).execute("DELETE FROM sessoes").connection.commit()
    _sessao(c, caminho, agora - dias, agora - timedelta(minutes=1), login="u2")
    assert c.usuario_da_sessao("h1", agora.isoformat()) is None


def test_sessao_tolerada_de_usuario_inativo_ou_revogada_nao_vale(contas):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    uid = _sessao(c, caminho, agora + timedelta(seconds=1), agora + timedelta(seconds=1))
    c.fechar_sessao("h1")
    assert c.usuario_da_sessao("h1", agora.isoformat()) is None
    c.abrir_sessao(uid, "h2", (agora + timedelta(seconds=1)).isoformat())
    c.definir_ativo(uid, 0)
    assert c.usuario_da_sessao("h2", agora.isoformat()) is None


# ---------- o painel: login e um relogio que recua ----------
class _Relogio:
    """O relogio do painel: o instante real do comeco do teste mais um deslocamento que o teste muda entre pedidos."""
    base = None
    deslocamento = timedelta(0)

    @classmethod
    def now(cls, tz=None):
        return (cls.base + cls.deslocamento).astimezone(tz) if tz else (cls.base + cls.deslocamento).replace(tzinfo=None)


@pytest.fixture
def relogio(monkeypatch):
    import painel.app as PA
    _Relogio.base, _Relogio.deslocamento = datetime.now(timezone.utc), timedelta(0)
    monkeypatch.setattr(PA, "datetime", _Relogio)
    return _Relogio


@pytest.mark.parametrize("recuos, continua_logado", [
    ([timedelta(seconds=-0.6)], True),
    ([timedelta(seconds=-0.6), timedelta(seconds=-1.1)], True),        # o salto duplo medido no WSL2
    ([-DOIS], True),
    ([-DOIS - timedelta(milliseconds=1)], False),                      # alem da tolerancia: a sessao cai
    ([timedelta(seconds=-5)], False),
])
def test_relogio_que_recua_depois_do_login(painel, relogio, recuos, continua_logado):
    cli = painel[0]
    _criar(painel, "maria", "Revisor")
    assert _entrar(cli, "maria").status_code == 303
    for recuo in recuos:
        relogio.deslocamento = recuo
        r = cli.get("/conta", follow_redirects=False)
    assert (r.status_code == 200) is continua_logado
    if not continua_logado:
        assert r.status_code == 303 and r.headers["location"].startswith("/entrar")


# ---------- PostgreSQL: a mesma regra (ContasPostgres herda usuario_da_sessao) ----------
@pytest.mark.postgres
@pytest.mark.parametrize("criada,ultimo,valida", [CASOS[3], CASOS[4], CASOS[6], CASOS[8]])
def test_tolerancia_no_postgres(pg_url, criada, ultimo, valida):
    import psycopg
    from adaptadores import migrador_postgres as M
    from adaptadores.contas_postgres import ContasPostgres
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    M.aplicar(pg_url)
    pool = criar_pool(pg_url, maximo=4)
    try:
        c = ContasPostgres(pool, chaves_do_banco(pool))
        c.garantir_padrao()
        g = [x["grupo_id"] for x in c.grupos() if x["nome"] == "Revisor"][0]
        agora = datetime.now(timezone.utc)
        uid = c.criar_usuario("maria", "Maria", g, A.hash_senha("senha-de-teste-123"), agora.isoformat())
        c.abrir_sessao(uid, "h1", (agora + criada).isoformat())
        with psycopg.connect(pg_url) as con:
            con.execute("UPDATE sessoes SET criada_em=%s, ultimo_uso=%s WHERE token_hash='h1'",
                        ((agora + criada).isoformat(), (agora + ultimo).isoformat()))
        assert (c.usuario_da_sessao("h1", agora.isoformat()) is not None) is valida
    finally:
        pool.close()


# ---------- pre-revisao ----------
def test_fronteiras_de_ociosidade_e_validade_absoluta_medidas_dos_instantes_gravados(contas):
    """Para a sessao tolerada, as fronteiras de 12 h e de 7 dias continuam medidas a partir dos instantes gravados, como
    hoje: nenhuma formula muda."""
    c, caminho = contas
    gravado = datetime.now(timezone.utc) + timedelta(seconds=1)
    horas, dias = timedelta(hours=A.HORAS_DE_SESSAO), timedelta(days=A.DIAS_MAXIMOS_DE_SESSAO)
    _sessao(c, caminho, gravado, gravado, login="a")
    assert c.usuario_da_sessao("h1", (gravado + horas).isoformat()) is None and _linhas(caminho) == 0
    _sessao(c, caminho, gravado, gravado, login="b")
    assert c.usuario_da_sessao("h1", (gravado + horas - UM_US).isoformat()) is not None
    _con(caminho).execute("DELETE FROM sessoes").connection.commit()
    _sessao(c, caminho, gravado, gravado + dias - timedelta(minutes=1), login="d")
    assert c.usuario_da_sessao("h1", (gravado + dias - UM_US).isoformat()) is not None
    assert c.usuario_da_sessao("h1", (gravado + dias).isoformat()) is None and _linhas(caminho) == 0


def test_sessao_tolerada_de_usuario_marcado_inativo_e_recusada_e_apagada(contas):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    _sessao(c, caminho, agora + timedelta(seconds=1), agora + timedelta(seconds=1))
    db = _con(caminho)
    db.execute("UPDATE usuarios SET ativo=0")                    # inativo, mas com a sessao ainda gravada
    db.commit()
    assert _linhas(caminho) == 1
    assert c.usuario_da_sessao("h1", agora.isoformat()) is None and _linhas(caminho) == 0


@pytest.mark.parametrize("ultimo", ["x", "", "2026-10-20T00:00:00"])
def test_ultimo_uso_ilegivel_continua_recusado(contas, ultimo):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    _sessao(c, caminho, agora, agora)
    db = _con(caminho)
    db.execute("UPDATE sessoes SET ultimo_uso=? WHERE token_hash='h1'", (ultimo,))
    db.commit()
    assert c.usuario_da_sessao("h1", agora.isoformat()) is None and _linhas(caminho) == 0


@pytest.mark.parametrize("agora_texto", ["x", "", "2026-10-25T12:00:00"])
def test_agora_invalido_continua_recusando_sem_erro(contas, agora_texto):
    c, caminho = contas
    agora = datetime.now(timezone.utc)
    _sessao(c, caminho, agora + timedelta(seconds=1), agora + timedelta(seconds=1))
    assert c.usuario_da_sessao("h1", agora_texto) is None and _linhas(caminho) == 0
