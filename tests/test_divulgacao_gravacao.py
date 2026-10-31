"""Alteracao da politica de divulgacao pelo administrador (D145, E7 6): regra pura (versao do estado gravado, leitura do
formulario, revisao com a frase do efeito) e gravacao no banco de contas numa transacao, com versao conferida, confirmacao
obrigatoria, recusa de preliminares verdadeiro e auditoria `alterar_divulgacao` com o antes e o depois. SQLite e PostgreSQL."""
import json
import threading

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A
from dominio import divulgacao as D
from test_conta_token import contas  # noqa: F401

FECHADA = {"publica": False, "preliminares": False}
ABERTA = {"publica": True, "preliminares": False}
AGORA = "2026-10-30T12:00:00+00:00"
AMPLIA = ("Entendo que qualquer pessoa na internet passará a ver: a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e "
          "a busca no texto, sem resultados automatizados.")
RESTRINGE = "Entendo que quem não entrou deixará de ver as páginas desta pesquisa."
INVALIDA = "Configuração de divulgação inválida."
PRELIMINARES = "A divulgação de resultados preliminares ainda não está disponível."
SEM_CONFIRMACAO = "Marque a confirmação para gravar a alteração."


def _bruto(c, banco, valor):
    with c._conexao(escrita=True) as conn:
        conn.execute("DELETE FROM configuracoes WHERE chave = ?", (D.chave(banco),))
        if valor is not None:
            conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave(banco), valor))


def _linha(c, banco):
    with c._conexao() as conn:
        r = conn.execute("SELECT valor FROM configuracoes WHERE chave = ?", (D.chave(banco),)).fetchone()
    return r[0] if r else None


def _divulgacoes(c):
    return [a for a in c.auditoria() if a["acao"] == "alterar_divulgacao"]


# ======================== regra pura ========================
def test_versao_distingue_estados_que_se_parecem():
    estados = [None, "None", "", " ", "1", 1, True, '{"publica": true, "preliminares": false}',
               '{"preliminares": false, "publica": true}', '{"publica": true, "preliminares": false} ', b"x", "x"]
    versoes = [D.versao(v) for v in estados]
    assert len(set(versoes)) == len(estados)
    assert all(isinstance(v, str) and len(v) == 64 for v in versoes)
    assert D.versao(None) == D.versao(None)


@pytest.mark.parametrize("publica,preliminares,esperado", [
    (["1"], [], (ABERTA, [])),
    (["0"], [], (FECHADA, [])),
    (["1"], ["0"], (ABERTA, [])),
    (["1"], ["1"], (None, [PRELIMINARES])),
    (["0"], ["1"], (None, [PRELIMINARES])),
    ([], [], (None, [INVALIDA])),
    (["1", "1"], [], (None, [INVALIDA])),                         # chave repetida
    (["1", "0"], [], (None, [INVALIDA])),
    (["sim"], [], (None, [INVALIDA])),
    ([" 1"], [], (None, [INVALIDA])),
    (["true"], [], (None, [INVALIDA])),
    ([""], [], (None, [INVALIDA])),
    (["1"], ["0", "0"], (None, [INVALIDA])),
    (["1"], ["true"], (None, [INVALIDA])),
    (["1"], [""], (None, [INVALIDA])),
    ([], ["1"], (None, [INVALIDA, PRELIMINARES])),                # os dois erros, nesta ordem
    (["x"], ["x"], (None, [INVALIDA, INVALIDA])),
    ("1", [], (None, [INVALIDA])),                                # so listas
    (None, [], (None, [INVALIDA])),
    (("1",), [], (None, [INVALIDA])),
    (["1"], None, (None, [INVALIDA])),
    (["1"], "0", (None, [INVALIDA])),
])
def test_formulario(publica, preliminares, esperado):
    assert D.nova_do_formulario(publica, preliminares) == esperado


@pytest.mark.parametrize("antes,nova,muda,amplia,confirmacao", [
    (FECHADA, ABERTA, True, True, AMPLIA),
    (ABERTA, FECHADA, True, False, RESTRINGE),
    (FECHADA, FECHADA, False, False, None),
    (ABERTA, ABERTA, False, False, None),
])
def test_revisao(antes, nova, muda, amplia, confirmacao):
    r = D.revisar(antes, nova)
    assert r == {"antes": antes, "depois": nova, "muda": muda, "amplia": amplia, "confirmacao": confirmacao,
                 "frase": {(True, True): "Quem não entrou passará a ver a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e "
                                         "a busca no texto, sem resultados automatizados.",
                           (True, False): "Quem não entrou passará a ser levado à tela de entrada em todas as páginas desta "
                                          "pesquisa.",
                           (False, False): "Nada muda: a divulgação já está assim."}[(muda, amplia)]}


def test_textos_de_erro_tem_uma_copia_so(monkeypatch):
    """validar_nova e nova_do_formulario usam as mesmas constantes (trocar a constante troca as duas)."""
    monkeypatch.setattr(D, "INVALIDA", "X-INVALIDA")
    monkeypatch.setattr(D, "PRELIMINARES", "X-PRELIMINARES")
    assert D.validar_nova({}) == ["X-INVALIDA"]
    assert D.validar_nova({"publica": True, "preliminares": True}) == ["X-PRELIMINARES"]
    assert D.nova_do_formulario([], ["1"]) == (None, ["X-INVALIDA", "X-PRELIMINARES"])


def test_auditoria_conhece_a_acao():
    assert "alterar_divulgacao" in A.ACOES_AUDITORIA


# ======================== estado lido (adaptador) ========================
@pytest.mark.parametrize("bruto,situacao,politica", [
    (None, "ausente", FECHADA),
    ('{"publica": true, "preliminares": false}', "valida", ABERTA),
    ('{"publica": false, "preliminares": false}', "valida", FECHADA),
    ('{"publica": true, "preliminares": true}', "invalida", FECHADA),
    ("lixo", "invalida", FECHADA),
])
def test_estado(contas, bruto, situacao, politica):  # noqa: F811
    _bruto(contas, "real", bruto)
    assert contas.estado_divulgacao("real") == {"politica": politica, "situacao": situacao, "versao": D.versao(bruto)}


@pytest.mark.parametrize("erro", [A.ContasOcupadas, RuntimeError])
def test_estado_erro_de_leitura_propaga(contas, monkeypatch, erro):  # noqa: F811
    def falha(*a, **k):
        raise erro()
    monkeypatch.setattr(contas, "_conexao", falha)
    with pytest.raises(erro):
        contas.estado_divulgacao("real")


# ======================== gravacao ========================
def _alterar(c, nova, versao=None, confirmado=True, banco="real", login="chefe"):
    if versao is None:
        versao = c.estado_divulgacao(banco)["versao"]
    return c.alterar_divulgacao(banco, nova, versao, confirmado, (login, AGORA))


def test_ativar_e_desativar(contas):  # noqa: F811
    r = _alterar(contas, ABERTA)
    assert r["muda"] and r["amplia"]
    assert contas.politica_divulgacao("real") == (ABERTA, "valida")
    assert json.loads(_linha(contas, "real")) == ABERTA
    r = _alterar(contas, FECHADA)
    assert r["muda"] and not r["amplia"]
    assert contas.politica_divulgacao("real") == (FECHADA, "valida")
    aud = _divulgacoes(contas)
    assert [(a["admin_login"], a["alvo"], a["quando"]) for a in aud] == [("chefe", "real", AGORA)] * 2
    assert [json.loads(a["detalhe"]) for a in aud] == [                               # a mais recente primeiro
        {"antes": ABERTA, "situacao_antes": "valida", "versao_antes": D.versao(D.valor(ABERTA)), "depois": FECHADA},
        {"antes": FECHADA, "situacao_antes": "ausente", "versao_antes": D.versao(None), "depois": ABERTA}]


def test_sem_mudanca_nao_grava_nem_audita(contas):  # noqa: F811
    _alterar(contas, ABERTA)
    antes = (_linha(contas, "real"), len(contas.auditoria()))
    r = _alterar(contas, ABERTA, confirmado=False)                  # sem mudanca, nem a confirmacao e pedida
    assert not r["muda"] and (_linha(contas, "real"), len(contas.auditoria())) == antes


def test_fechar_quando_ausente_nao_muda_nada(contas):  # noqa: F811
    r = _alterar(contas, FECHADA, confirmado=False)
    assert not r["muda"] and _linha(contas, "real") is None and _divulgacoes(contas) == []


REPARO = ("A configuração inválida será trocada por «não divulgada»: quem não entrou continua sendo levado à tela de "
          "entrada.")
REPARO_CONF = "Entendo que a pesquisa continua fechada para quem não entrou."


def test_invalida_pode_ser_corrigida_sem_abrir(contas):  # noqa: F811
    """Fechar uma configuracao invalida grava a linha explicita de nao divulgada (sem passar por aberta), com confirmacao e
    auditoria; abrir a partir dela tambem e possivel."""
    _bruto(contas, "real", "lixo")
    with pytest.raises(A.AlteracaoRecusada):
        _alterar(contas, FECHADA, confirmado=False)
    assert _linha(contas, "real") == "lixo"
    r = _alterar(contas, FECHADA)
    assert (r["muda"], r["amplia"], r["frase"], r["confirmacao"]) == (True, False, REPARO, REPARO_CONF)
    assert json.loads(_linha(contas, "real")) == FECHADA
    assert json.loads(_divulgacoes(contas)[0]["detalhe"]) == {"antes": FECHADA, "situacao_antes": "invalida",
                                                              "versao_antes": D.versao("lixo"), "depois": FECHADA}
    _bruto(contas, "real", "lixo")
    _alterar(contas, ABERTA)
    assert json.loads(_divulgacoes(contas)[0]["detalhe"])["situacao_antes"] == "invalida"


def test_revisao_de_uma_configuracao_invalida():
    assert D.revisar(FECHADA, FECHADA, "invalida")["frase"] == REPARO
    assert D.revisar(FECHADA, FECHADA, "ausente")["muda"] is False                # ausente nao e invalida: nada muda
    assert D.revisar(FECHADA, ABERTA, "invalida")["amplia"] is True


@pytest.mark.parametrize("detalhe,resumo", [
    ({"antes": FECHADA, "situacao_antes": "ausente", "depois": ABERTA}, "Não configurada → Divulgada"),
    ({"antes": FECHADA, "situacao_antes": "valida", "depois": ABERTA}, "Não divulgada → Divulgada"),
    ({"antes": ABERTA, "situacao_antes": "valida", "depois": FECHADA}, "Divulgada → Não divulgada"),
    ({"antes": FECHADA, "situacao_antes": "invalida", "depois": FECHADA}, "Configuração inválida → Não divulgada"),
])
def test_resumo_da_auditoria(detalhe, resumo):
    """Le so os campos que usa (antes, depois, situacao_antes); chaves a mais e a versao nao mudam o resumo."""
    assert D.resumo_auditoria(json.dumps({**detalhe, "versao_antes": D.versao(None), "extra": 1})) == resumo


@pytest.mark.parametrize("detalhe", [None, "", "lixo", "[]", "{}", '{"antes": 1}', json.dumps({"antes": FECHADA, "depois": ABERTA}),
                                     json.dumps({"antes": FECHADA, "situacao_antes": "outra", "depois": ABERTA}), 5,
                                     json.dumps({"antes": {"publica": 1}, "situacao_antes": "valida", "depois": ABERTA}),
                                     json.dumps({"antes": FECHADA, "situacao_antes": "valida", "depois": {"publica": "true"}}),
                                     json.dumps({"antes": FECHADA, "situacao_antes": "valida", "depois": None}),
                                     '{"antes": {"publica": false, "preliminares": false}, "situacao_antes": "valida", '
                                     '"depois": {"publica": true, "preliminares": false}, "situacao_antes": "valida"}'])
def test_resumo_da_auditoria_invalido(detalhe):
    assert D.resumo_auditoria(detalhe) is None


@pytest.mark.parametrize("nova", [{"publica": True, "preliminares": True}, {"publica": False, "preliminares": True}])
def test_preliminares_verdadeiro_e_recusado(contas, nova):  # noqa: F811
    with pytest.raises(A.AlteracaoRecusada) as e:
        _alterar(contas, nova)
    assert e.value.erros == [PRELIMINARES]
    assert _linha(contas, "real") is None and _divulgacoes(contas) == []


@pytest.mark.parametrize("nova", [None, {}, {"publica": True}, {"publica": 1, "preliminares": False},
                                  {"publica": "true", "preliminares": False}, {"publica": True, "preliminares": False, "x": 1},
                                  [True, False]])
def test_nova_invalida_e_recusada(contas, nova):  # noqa: F811
    with pytest.raises(A.AlteracaoRecusada) as e:
        _alterar(contas, nova)
    assert e.value.erros == [INVALIDA]
    assert _linha(contas, "real") is None and _divulgacoes(contas) == []


@pytest.mark.parametrize("confirmado", [False, None, 0, 1, "1", "0", "on", "true", [], [True]])
def test_sem_confirmacao_nada_e_gravado(contas, confirmado):  # noqa: F811
    with pytest.raises(A.AlteracaoRecusada) as e:                  # so o booleano True confirma
        _alterar(contas, ABERTA, confirmado=confirmado)
    assert e.value.erros == [SEM_CONFIRMACAO]
    assert _linha(contas, "real") is None and _divulgacoes(contas) == []


@pytest.mark.parametrize("versao", ["", "0" * 64, "base", "base_maiuscula", "base_com_espaco", None, 1, b"x"])
def test_versao_desatualizada_ou_ausente_e_recusada(contas, versao):  # noqa: F811
    base = D.versao(None)                                          # a versao lida antes de a linha mudar
    v = {"base": base, "base_maiuscula": base.upper(), "base_com_espaco": base + " "}.get(versao, versao)
    _bruto(contas, "real", '{"publica": false, "preliminares": false}')       # a linha mudou depois da leitura de `v`
    with pytest.raises(D.DivulgacaoAlterada):
        contas.alterar_divulgacao("real", ABERTA, v, True, ("chefe", AGORA))
    assert json.loads(_linha(contas, "real")) == FECHADA and _divulgacoes(contas) == []


def test_ordem_das_conferencias(contas):  # noqa: F811
    """Formulario invalido antes da versao; versao antes da confirmacao."""
    _bruto(contas, "real", '{"publica": false, "preliminares": false}')
    with pytest.raises(A.AlteracaoRecusada):
        contas.alterar_divulgacao("real", {"publica": True, "preliminares": True}, "velha", False, ("chefe", AGORA))
    with pytest.raises(D.DivulgacaoAlterada):
        contas.alterar_divulgacao("real", ABERTA, "velha", False, ("chefe", AGORA))


def test_ordem_pesquisa_formulario_versao_sem_mudanca(contas):  # noqa: F811
    with pytest.raises(A.AlteracaoRecusada) as e:                  # pesquisa invalida antes do formulario invalido
        contas.alterar_divulgacao("foo", {"publica": True, "preliminares": True}, "velha", True, ("chefe", AGORA))
    assert e.value.erros == ["Pesquisa inválida."]
    _bruto(contas, "real", '{"publica": false, "preliminares": false}')
    with pytest.raises(D.DivulgacaoAlterada):                      # versao antes do "nada muda"
        contas.alterar_divulgacao("real", FECHADA, "velha", False, ("chefe", AGORA))


@pytest.mark.parametrize("banco,nova,auditoria,erro", [
    ("foo", ABERTA, ("chefe", AGORA), A.AlteracaoRecusada),
    ("real", {"publica": True, "preliminares": True}, ("chefe", AGORA), A.AlteracaoRecusada),
    ("real", None, ("chefe", AGORA), A.AlteracaoRecusada),
    ("real", ABERTA, ("", AGORA), ValueError),
    ("real", ABERTA, None, ValueError),
])
def test_pesquisa_formulario_e_auditoria_conferidos_antes_de_abrir_o_banco(contas, monkeypatch, banco, nova, auditoria, erro):  # noqa: F811
    def nao_abre(*a, **k):
        raise AssertionError("abriu o banco")
    monkeypatch.setattr(contas, "_conexao", nao_abre)
    with pytest.raises(erro):
        contas.alterar_divulgacao(banco, nova, "x", True, auditoria)


@pytest.mark.parametrize("auditoria", [None, (), ("chefe",), ("", AGORA), ("  ", AGORA), (1, AGORA), ("chefe", ""), ("chefe", None),
                                       ["chefe", AGORA], ("chefe", AGORA, "x")])
def test_auditoria_malformada_nada_e_gravado(contas, auditoria):  # noqa: F811
    with pytest.raises(ValueError, match="Auditoria inválida."):
        contas.alterar_divulgacao("real", ABERTA, contas.estado_divulgacao("real")["versao"], True, auditoria)
    assert _linha(contas, "real") is None and _divulgacoes(contas) == []


def test_duas_alteracoes_com_a_mesma_versao_so_uma_grava(contas):  # noqa: F811
    v = contas.estado_divulgacao("real")["versao"]
    contas.alterar_divulgacao("real", ABERTA, v, True, ("ana", AGORA))
    with pytest.raises(D.DivulgacaoAlterada):
        contas.alterar_divulgacao("real", ABERTA, v, True, ("bia", AGORA))
    assert [a["admin_login"] for a in _divulgacoes(contas)] == ["ana"]


def test_duas_alteracoes_ao_mesmo_tempo_so_uma_grava(contas, monkeypatch):  # noqa: F811
    """A segue dentro da transacao (parada em `revisar`) enquanto B comeca; so depois A grava. Com a versao conferida sob a
    mesma trava da escrita, B espera e encontra a versao nova: uma grava, a outra recebe DivulgacaoAlterada."""
    import time
    v = contas.estado_divulgacao("real")["versao"]
    dentro, solta = threading.Event(), threading.Event()
    original = D.revisar

    def revisar_lento(*a, **k):
        if threading.current_thread().name == "ana":
            dentro.set()
            solta.wait(10)
        return original(*a, **k)
    monkeypatch.setattr(D, "revisar", revisar_lento)
    b_no_banco = threading.Event()
    conexao_original = contas._conexao

    def conexao_espiada(*a, **k):
        if threading.current_thread().name == "bia" and k.get("escrita"):
            b_no_banco.set()                                       # B pede a conexao de escrita (e espera a trava de A)
        return conexao_original(*a, **k)
    monkeypatch.setattr(contas, "_conexao", conexao_espiada)
    resultados = {}

    def gravar(login):
        try:
            contas.alterar_divulgacao("real", ABERTA, v, True, (login, AGORA))
            resultados[login] = "gravou"
        except D.DivulgacaoAlterada:
            resultados[login] = "alterada"
    a = threading.Thread(target=gravar, args=("ana",), name="ana")
    a.start()
    assert dentro.wait(10)
    b = threading.Thread(target=gravar, args=("bia",), name="bia")
    b.start()
    assert b_no_banco.wait(10)                                     # B ja pediu a escrita antes de A gravar
    time.sleep(0.2)                                                # e esta parado na trava
    solta.set()
    a.join(20)
    b.join(20)
    assert resultados == {"ana": "gravou", "bia": "alterada"}
    assert [x["admin_login"] for x in _divulgacoes(contas)] == ["ana"]


def test_uma_pesquisa_nao_altera_a_outra(contas):  # noqa: F811
    _bruto(contas, "vies", '{"publica": true, "preliminares": false}')
    _alterar(contas, ABERTA, banco="real")
    _alterar(contas, FECHADA, banco="real")
    assert json.loads(_linha(contas, "vies")) == ABERTA
    _alterar(contas, FECHADA, banco="vies")
    assert json.loads(_linha(contas, "real")) == FECHADA and json.loads(_linha(contas, "vies")) == FECHADA
    assert [a["alvo"] for a in _divulgacoes(contas)] == ["vies", "real", "real"]


@pytest.mark.parametrize("banco", ["", " real", "REAL", "real ", "re al", "../real", None, 1, "foo", "real\n", "reaĺ", "r" * 5000,
                                   b"real", "Real", "vies2"])
def test_banco_invalido_e_recusado(contas, banco):  # noqa: F811
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.alterar_divulgacao(banco, ABERTA, D.versao(None), True, ("chefe", AGORA))
    assert e.value.erros == ["Pesquisa inválida."]


@pytest.mark.parametrize("banco", ["real", "vies", "demo", "simulado"])
def test_as_pesquisas_aceitas(contas, banco):  # noqa: F811
    assert _alterar(contas, ABERTA, banco=banco)["muda"] and json.loads(_linha(contas, banco)) == ABERTA


def test_falha_na_auditoria_desfaz_a_gravacao(contas, monkeypatch):  # noqa: F811
    _bruto(contas, "real", D.valor(ABERTA))

    def falha(*a, **k):
        raise RuntimeError("disco cheio")
    monkeypatch.setattr(contas, "_gravar_auditoria", falha)
    with pytest.raises(RuntimeError):
        _alterar(contas, FECHADA)
    assert json.loads(_linha(contas, "real")) == ABERTA and _divulgacoes(contas) == []


def test_falha_entre_apagar_e_inserir_desfaz_tudo(contas, monkeypatch):  # noqa: F811
    """A linha nova nunca chega a ser escrita: a antiga volta (nada se perde, nada se abre)."""
    _bruto(contas, "real", D.valor(ABERTA))

    def falha(nova):
        raise RuntimeError("falha")
    monkeypatch.setattr(D, "valor", falha)
    with pytest.raises(RuntimeError):
        _alterar(contas, FECHADA)
    monkeypatch.undo()
    assert json.loads(_linha(contas, "real")) == ABERTA and _divulgacoes(contas) == []


def test_falha_ao_gravar_a_linha_nao_audita_nem_abre(tmp_path):
    import sqlite3
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    with c._conexao(escrita=True) as conn:
        conn.execute("CREATE TRIGGER quebra BEFORE INSERT ON configuracoes BEGIN SELECT RAISE(ABORT, 'falha'); END")
    with pytest.raises(sqlite3.DatabaseError):
        _alterar(c, ABERTA)
    assert c.politica_divulgacao("real") == (FECHADA, "ausente") and _divulgacoes(c) == []


def test_nada_alem_da_linha_e_da_auditoria_e_escrito(tmp_path):
    import sqlite3
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()

    def foto():
        con = sqlite3.connect(tmp_path / "contas.db")
        tabelas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                              "ORDER BY name")]
        return {t: con.execute(f"SELECT * FROM {t}").fetchall() for t in tabelas}
    antes = foto()
    _alterar(c, ABERTA)
    depois = foto()
    mudou = {t for t in antes if antes[t] != depois[t]}
    assert mudou == {"configuracoes", "auditoria_admin"}


def test_outras_chaves_de_configuracao_ficam_intactas(contas):  # noqa: F811
    with contas._conexao(escrita=True) as conn:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES ('outra:chave', 'x')")
    _alterar(contas, ABERTA)
    _alterar(contas, FECHADA)
    with contas._conexao() as conn:
        assert conn.execute("SELECT valor FROM configuracoes WHERE chave = 'outra:chave'").fetchone()[0] == "x"
