"""Login seguro para a internet: o bloqueio por senha errada vale mesmo com pedidos simultaneos, o tempo de resposta nao
revela quais logins existem, a sessao tem validade absoluta e o painel nunca fica sem administrador ativo."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from dominio import autenticacao as A
from test_autenticacao import SENHA, _con, _criar, _csrf, _usuario, contas, painel  # noqa: F401
from test_painel import demo  # noqa: F401


def _agora(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _estado(caminho, login="maria"):
    return tuple(_con(caminho).execute("SELECT falhas_login, bloqueado_ate FROM usuarios WHERE login=?", (login,)).fetchone())


# ====================== reserva da tentativa (adaptador) ======================
def test_a_quinta_reserva_ja_grava_o_bloqueio_e_a_contagem_nao_zera(contas):
    c, caminho = contas
    uid = _usuario(c, caminho)
    for i in range(1, 6):
        r = c.reservar_tentativa("maria", _agora())
        assert r["situacao"] == "reservado" and r["usuario"]["usuario_id"] == uid
        falhas, bloq = _estado(caminho)
        assert falhas == i and (bloq is None) is (i < 5)
    assert c.reservar_tentativa("maria", _agora()) == {"situacao": "bloqueado", "usuario": None}
    assert _estado(caminho)[0] == 5                                        # tentativa barrada nao conta


def test_contagem_cheia_sem_bloqueio_gravado_bloqueia_com_prazo(contas):
    c, caminho = contas
    _usuario(c, caminho)
    db = _con(caminho)
    db.execute("UPDATE usuarios SET falhas_login=5, bloqueado_ate=NULL WHERE login='maria'")
    db.commit()
    assert c.reservar_tentativa("maria", _agora())["situacao"] == "bloqueado"
    falhas, bloq = _estado(caminho)
    assert falhas == 5 and bloq is not None
    assert c.reservar_tentativa("maria", _agora(minutes=6))["situacao"] == "reservado"   # o prazo vence sozinho


def test_bloqueio_vencido_recomeca_a_contagem(contas):
    c, caminho = contas
    _usuario(c, caminho)
    db = _con(caminho)
    db.execute("UPDATE usuarios SET falhas_login=5, bloqueado_ate=? WHERE login='maria'", (_agora(minutes=-1),))
    db.commit()
    assert c.reservar_tentativa("maria", _agora())["situacao"] == "reservado"
    assert _estado(caminho) == (1, None)


def test_tentativas_ainda_em_conferencia_ocupam_as_vagas_ate_o_prazo(contas):
    c, caminho = contas
    _usuario(c, caminho)
    situacoes = [c.reservar_tentativa("maria", _agora())["situacao"] for _ in range(7)]  # nenhuma conferida ainda
    assert situacoes == ["reservado"] * 5 + ["bloqueado"] * 2
    assert c.reservar_tentativa("maria", _agora(minutes=6))["situacao"] == "reservado"
    assert _estado(caminho) == (1, None)


@pytest.mark.parametrize("guardado", ["corrompido", -1, -1000000, 2.5, b"\x00"],
                         ids=["texto", "menos_um", "menos_um_milhao", "fracao", "blob"])
def test_contagem_que_o_painel_nao_gravaria_conta_como_cheia(contas, guardado):
    """Contagem gravada fora do que o painel escreve (nao inteira ou negativa): bloqueia ja, com prazo; ao vencer, recomeca."""
    c, caminho = contas
    _usuario(c, caminho)
    db = _con(caminho)
    db.execute("UPDATE usuarios SET falhas_login=?, bloqueado_ate=NULL WHERE login='maria'", (guardado,))
    db.commit()
    agora = datetime.now(timezone.utc)
    assert c.reservar_tentativa("maria", agora.isoformat()) == {"situacao": "bloqueado", "usuario": None}
    assert _estado(caminho)[1] == (agora + timedelta(minutes=5)).isoformat()
    assert c.reservar_tentativa("maria", (agora + timedelta(minutes=5)).isoformat())["situacao"] == "reservado"
    assert _estado(caminho) == (1, None)


def test_contagem_em_texto_que_o_sqlite_converte_em_inteiro_vale(contas):
    c, caminho = contas
    _usuario(c, caminho)
    db = _con(caminho)
    db.execute("UPDATE usuarios SET falhas_login='3', bloqueado_ate=NULL WHERE login='maria'")
    db.commit()
    assert c.reservar_tentativa("maria", _agora())["situacao"] == "reservado"
    assert _estado(caminho) == (4, None)


def test_bloqueio_gravado_alem_do_prazo_continua_valendo(contas):
    c, caminho = contas
    _usuario(c, caminho)
    db = _con(caminho)
    db.execute("UPDATE usuarios SET falhas_login=0, bloqueado_ate=? WHERE login='maria'", (_agora(days=30),))
    db.commit()
    assert c.reservar_tentativa("maria", _agora())["situacao"] == "bloqueado"


@pytest.mark.parametrize("caso", ["inexistente", "inativo"])
def test_login_inexistente_ou_inativo_nao_reserva(contas, caso):
    c, caminho = contas
    uid = _usuario(c, caminho)
    if caso == "inativo":
        c.definir_ativo(uid, 0)
    login = "ninguem" if caso == "inexistente" else "maria"
    assert c.reservar_tentativa(login, _agora()) == {"situacao": "inexistente", "usuario": None}
    assert _estado(caminho) == (0, None)


def test_acerto_na_quinta_tentativa_abre_a_sessao_e_zera(contas):
    c, caminho = contas
    uid = _usuario(c, caminho)
    for _ in range(5):
        r = c.reservar_tentativa("maria", _agora())
    assert r["situacao"] == "reservado" and _estado(caminho)[1] is not None
    assert c.abrir_sessao(uid, "h1", _agora(), senha_hash=r["usuario"]["senha_hash"]) is True
    assert _estado(caminho) == (0, None)


def test_senha_redefinida_durante_o_login_nao_abre_sessao_com_a_antiga(contas):
    c, caminho = contas
    uid = _usuario(c, caminho)
    r = c.reservar_tentativa("maria", _agora())
    c.redefinir_senha(uid, A.hash_senha("outra-senha-boa-123"))
    assert c.abrir_sessao(uid, "h1", _agora(), senha_hash=r["usuario"]["senha_hash"]) is False
    assert _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == 0
    c.definir_ativo(uid, 0)
    novo = _con(caminho).execute("SELECT senha_hash FROM usuarios").fetchone()[0]
    assert c.abrir_sessao(uid, "h2", _agora(), senha_hash=novo) is False                  # inativo tambem nao


# ====================== pela rota ======================
def test_contagem_corrompida_pela_rota_responde_bloqueado_e_nao_erro(painel):
    cli, _, _, contas_db = painel
    _criar(painel, "maria", "Revisor")
    db = sqlite3.connect(contas_db)
    db.execute("UPDATE usuarios SET falhas_login='corrompido' WHERE login='maria'")
    db.commit()
    db.close()
    r = cli.post("/entrar", data={"login": "maria", "senha": SENHA, "proximo": "/", "csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 429


def test_trinta_tentativas_simultaneas_conferem_no_maximo_cinco_senhas(painel, monkeypatch):
    cli, _, _, contas_db = painel
    _criar(painel, "maria", "Revisor")
    token, cookies = _csrf(cli), dict(cli.cookies)
    conferidas, trava = [], threading.Lock()
    original = A.conferir_senha

    def conferir(senha, guardado):
        with trava:
            conferidas.append(guardado == A.hash_ficticio())
        return original(senha, guardado)
    monkeypatch.setattr(A, "conferir_senha", conferir)

    def tenta(i):
        c = TestClient(cli.app)
        c.cookies.update(cookies)
        return c.post("/entrar", data={"login": "maria", "senha": f"errada-{i:02d}-xxxx", "proximo": "/", "csrf": token},
                      follow_redirects=False).status_code
    with ThreadPoolExecutor(30) as p:
        st = list(p.map(tenta, range(30)))
    assert st.count(400) == 5 and st.count(429) == 25
    assert conferidas == [False] * 5                                        # so as 5 reservadas conferem a senha
    falhas, bloq = sqlite3.connect(contas_db).execute("SELECT falhas_login, bloqueado_ate FROM usuarios WHERE login='maria'").fetchone()
    assert falhas == 5 and bloq is not None


def test_login_inexistente_e_inativo_conferem_contra_o_hash_ficticio(painel, monkeypatch):
    cli, contas, _, _ = painel
    uid = _criar(painel, "maria", "Revisor")
    contas.definir_ativo(uid, 0)
    chamadas = []
    original = A.conferir_senha
    monkeypatch.setattr(A, "conferir_senha", lambda s, g: (chamadas.append(g), original(s, g))[1])
    for login in ("ninguem", "maria"):
        r = cli.post("/entrar", data={"login": login, "senha": "errada-errada", "proximo": "/", "csrf": _csrf(cli)},
                     follow_redirects=False)
        assert r.status_code == 400 and "Login ou senha incorretos." in r.text
    assert chamadas == [A.hash_ficticio(), A.hash_ficticio()]


def test_hash_ficticio_e_fixo_e_nunca_confere_uma_senha_comum():
    assert A.hash_ficticio() == A.hash_senha("tempo-de-resposta-constante", sal=bytes(16))
    assert not A.conferir_senha(SENHA, A.hash_ficticio())


def test_no_maximo_quatro_conferencias_de_senha_ao_mesmo_tempo(painel, monkeypatch):
    import time
    cli, _, _, _ = painel
    token, cookies = _csrf(cli), dict(cli.cookies)
    agora, maximo, trava = [0], [0], threading.Lock()
    original = A.conferir_senha

    def lenta(senha, guardado):
        with trava:
            agora[0] += 1
            maximo[0] = max(maximo[0], agora[0])
        time.sleep(0.3)
        with trava:
            agora[0] -= 1
        return original(senha, guardado)
    monkeypatch.setattr(A, "conferir_senha", lenta)

    def tenta(i):
        c = TestClient(cli.app)
        c.cookies.update(cookies)
        return c.post("/entrar", data={"login": f"ninguem{i:02d}", "senha": "errada-errada", "proximo": "/", "csrf": token},
                      follow_redirects=False).status_code
    with ThreadPoolExecutor(12) as p:
        st = list(p.map(tenta, range(12)))
    assert st == [400] * 12 and 2 <= maximo[0] <= 4


# ====================== validade absoluta da sessao ======================
@pytest.mark.parametrize("decorrido,valida", [(timedelta(days=7) - timedelta(microseconds=1), True), (timedelta(days=7), False),
                                               (timedelta(days=8), False)])
def test_sessao_em_uso_continuo_expira_em_sete_dias(contas, decorrido, valida):
    c, caminho = contas
    uid = _usuario(c, caminho)
    criada = datetime.now(timezone.utc) - timedelta(days=9)
    c.abrir_sessao(uid, "h1", criada.isoformat())
    momento = criada + decorrido
    db = _con(caminho)
    db.execute("UPDATE sessoes SET ultimo_uso=? WHERE token_hash='h1'", ((momento - timedelta(minutes=5)).isoformat(),))
    db.commit()
    assert (c.usuario_da_sessao("h1", momento.isoformat()) is not None) is valida
    assert _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == (1 if valida else 0)


@pytest.mark.parametrize("criada_em", ["2026-10-20T00:00:00", "x", ""])
def test_sessao_com_data_de_criacao_ilegivel_nao_vale(contas, criada_em):
    c, caminho = contas
    uid = _usuario(c, caminho)
    c.abrir_sessao(uid, "h1", _agora())
    db = _con(caminho)
    db.execute("UPDATE sessoes SET criada_em=? WHERE token_hash='h1'", (criada_em,))
    db.commit()
    assert c.usuario_da_sessao("h1", _agora()) is None
    assert _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == 0


@pytest.mark.parametrize("coluna,adiante,valida", [("criada_em", timedelta(0), True), ("criada_em", timedelta(microseconds=1), False),
                                                   ("criada_em", timedelta(days=30), False), ("ultimo_uso", timedelta(0), True),
                                                   ("ultimo_uso", timedelta(microseconds=1), False)])
def test_sessao_com_instante_no_futuro_nao_vale(contas, coluna, adiante, valida):
    c, caminho = contas
    uid = _usuario(c, caminho)
    agora = datetime.now(timezone.utc)
    c.abrir_sessao(uid, "h1", (agora - timedelta(hours=1)).isoformat())
    db = _con(caminho)
    db.execute(f"UPDATE sessoes SET {coluna}=? WHERE token_hash='h1'", ((agora + adiante).isoformat(),))
    db.commit()
    assert (c.usuario_da_sessao("h1", agora.isoformat()) is not None) is valida
    assert _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == (1 if valida else 0)


# ====================== ultimo administrador ======================
def _admin(c, caminho, login, nome):
    g = _con(caminho).execute("SELECT grupo_id FROM grupos WHERE nome='Administrador'").fetchone()[0]
    return c.criar_usuario(login, nome, g, A.hash_senha(SENHA), _agora())


def test_rebaixar_ou_desativar_o_ultimo_administrador_e_recusado_na_transacao(contas):
    c, caminho = contas
    uid = _admin(c, caminho, "chefe", "Chefe")
    revisor = _con(caminho).execute("SELECT grupo_id FROM grupos WHERE nome='Revisor'").fetchone()[0]
    with pytest.raises(ValueError, match="^O painel precisa de pelo menos um administrador ativo.$"):
        c.editar_usuario(uid, "chefe", "Chefe", revisor)
    with pytest.raises(ValueError, match="^O painel precisa de pelo menos um administrador ativo.$"):
        c.definir_ativo(uid, 0)
    assert c.contar_admins_ativos() == 1
    assert _con(caminho).execute("SELECT grupo_id, ativo FROM usuarios WHERE usuario_id=?", (uid,)).fetchone() != (revisor, 0)


@pytest.mark.parametrize("acao", ["rebaixar", "desativar"])
def test_mudanca_que_espera_outra_transacao_ve_o_estado_depois_dela(contas, acao):
    """A rebaixa B numa transacao ainda aberta; a mudanca de B sobre A espera o busy_timeout, ve o estado depois do
    commit e e desfeita: sempre sobra um administrador ativo."""
    c, caminho = contas
    a = _admin(c, caminho, "chefe", "Chefe")
    b = _admin(c, caminho, "vice", "Vice")
    revisor = _con(caminho).execute("SELECT grupo_id FROM grupos WHERE nome='Revisor'").fetchone()[0]
    externa = sqlite3.connect(caminho, isolation_level=None)
    externa.execute("BEGIN IMMEDIATE")
    externa.execute("UPDATE usuarios SET grupo_id=? WHERE usuario_id=?", (revisor, b))
    resultado = []

    def muda():
        try:
            if acao == "rebaixar":
                c.editar_usuario(a, "chefe", "Chefe", revisor)
            else:
                c.definir_ativo(a, 0)
            resultado.append("ok")
        except ValueError as e:
            resultado.append(str(e))
    t = threading.Thread(target=muda)
    t.start()
    t.join(0.5)
    assert t.is_alive()                                                  # esperando a transacao externa
    externa.execute("COMMIT")
    t.join(10)
    assert resultado == ["O painel precisa de pelo menos um administrador ativo."]
    assert c.contar_admins_ativos() == 1
