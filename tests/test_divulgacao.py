"""Politica de divulgacao publica por pesquisa (D145): leitura fechada por padrao, a decisao do que quem nao entrou pode
abrir (lista fechada de rotas so com C1; toda rota nova fica fechada) e a leitura no banco de contas (SQLite e PostgreSQL).
Nesta fase `preliminares` verdadeiro nunca vale."""
import json

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from test_conta_token import contas  # noqa: F401

class _D:
    """Importa o modulo na hora do uso (cada teste falha sozinho enquanto o modulo nao existe)."""
    def __getattr__(self, nome):
        from dominio import divulgacao
        return getattr(divulgacao, nome)


D = _D()
FECHADA = {"publica": False, "preliminares": False}
ABERTA = {"publica": True, "preliminares": False}


# ======================== leitura do valor gravado ========================
@pytest.mark.parametrize("valor,politica,estado", [
    (None, FECHADA, "ausente"),
    ('{"publica": true, "preliminares": false}', ABERTA, "valida"),
    ('{"publica": false, "preliminares": false}', FECHADA, "valida"),
    ('  {"preliminares": false, "publica": true}\n', ABERTA, "valida"),          # espacos e ordem das chaves nao importam
    ('{"publica": true, "preliminares": true}', FECHADA, "invalida"),             # preliminares nunca valem nesta fase
    ('{"publica": false, "preliminares": true}', FECHADA, "invalida"),
    ("", FECHADA, "invalida"),
    ("   ", FECHADA, "invalida"),
    ("null", FECHADA, "invalida"),
    ("true", FECHADA, "invalida"),
    ("[]", FECHADA, "invalida"),
    ('"publica"', FECHADA, "invalida"),
    ("{}", FECHADA, "invalida"),
    ('{"publica": true}', FECHADA, "invalida"),                                   # chave faltando
    ('{"publica": true, "preliminares": false, "extra": 1}', FECHADA, "invalida"),  # chave a mais
    ('{"publica": 1, "preliminares": false}', FECHADA, "invalida"),               # numero no lugar de booleano
    ('{"publica": "true", "preliminares": false}', FECHADA, "invalida"),
    ('{"publica": null, "preliminares": false}', FECHADA, "invalida"),
    ('{"publica": true, "preliminares": 0}', FECHADA, "invalida"),
    ('{"publica": NaN, "preliminares": false}', FECHADA, "invalida"),
    ('{"publica": false, "publica": true, "preliminares": false}', FECHADA, "invalida"),  # chave repetida
    ('{"publica": true, "preliminares": false', FECHADA, "invalida"),             # JSON quebrado
    ('{"publica": true, "preliminares": false}' + " " * 960, ABERTA, "valida"),     # exatamente 1000 caracteres
    ('{"publica": true, "preliminares": false}' + " " * 961, FECHADA, "invalida"),  # 1001 caracteres
    (b'{"publica": true, "preliminares": false}', FECHADA, "invalida"),           # tipo errado vindo do banco
    (1, FECHADA, "invalida"),
    ('{"publica": true, "preliminares": false}\ud800', FECHADA, "invalida"),      # substituto solto
])
def test_ler_politica(valor, politica, estado):
    p, e = D.ler_politica(valor)
    assert (p, e) == (politica, estado)
    assert type(p["publica"]) is bool and type(p["preliminares"]) is bool


@pytest.mark.parametrize("valor", [None, "x", '{"publica": true, "preliminares": true}'])
def test_ler_politica_devolve_copia(valor):
    p, _ = D.ler_politica(valor)
    p["publica"] = True
    assert D.ler_politica(valor)[0] == FECHADA


def test_tamanho_conferido_antes_de_ler_o_json(monkeypatch):
    import json as _json
    vistos = []
    original = _json.loads
    monkeypatch.setattr(_json, "loads", lambda *a, **k: vistos.append(1) or original(*a, **k))
    assert D.ler_politica("x" * 1001) == (FECHADA, "invalida") and vistos == []


@pytest.mark.parametrize("erro", [RecursionError, ValueError, TypeError, MemoryError, RuntimeError, Exception])
def test_qualquer_erro_do_json_vale_como_invalida(monkeypatch, erro):
    import json as _json

    def falha(*a, **k):
        raise erro()
    monkeypatch.setattr(_json, "loads", falha)
    assert D.ler_politica('{"publica": true, "preliminares": false}') == (FECHADA, "invalida")


def test_chave_por_pesquisa():
    assert D.chave("real") == "divulgacao:real" and D.chave("vies") == "divulgacao:vies"


# ======================== o que quem nao entrou pode abrir ========================
PUBLICAS = ["/", "/sobre", "/literatura/prisma", "/metodologia", "/buscar-texto"]
AINDA_FECHADAS = []
METODOS = ["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
SEMPRE = ["/entrar", "/sair", "/static/painel.css", "/static/x/y.svg", "/api/coletas"]
FECHADAS_AO_PUBLICO = ["/estados", "/estados/SP", "/achados", "/achados/1", "/revisao/achados", "/analises", "/classificadores",
                       "/triagem-escopo", "/observatorio", "/observatorio/obras", "/validacao", "/validacao/3", "/literatura",
                       "/literatura/artigos", "/literatura/artigos/1", "/literatura/triagem", "/literatura/referencias",
                       "/literatura/referencias/web/1", "/literatura/referencias.xlsx", "/solucoes",
                       "/rota-nova", "/sobre/", "/literatura/prisma/", "/metodologia.xlsx", "/SOBRE", "//sobre", "/./sobre",
                       "/sobre/.", "/x/../sobre", ""] + AINDA_FECHADAS


def test_lista_de_rotas_publicas():
    assert D.ROTAS_PUBLICAS == frozenset(PUBLICAS)


@pytest.mark.parametrize("metodo", METODOS)
@pytest.mark.parametrize("caminho", PUBLICAS)
def test_publicas_abrem_so_com_a_pesquisa_divulgada_e_so_para_leitura(metodo, caminho):
    leitura = metodo in ("GET", "HEAD")
    assert D.decisao_publico(metodo, caminho, ABERTA) == ("liberada" if leitura else "entrada")
    assert D.decisao_publico(metodo, caminho, FECHADA) == "entrada"


@pytest.mark.parametrize("metodo", METODOS)
@pytest.mark.parametrize("caminho", FECHADAS_AO_PUBLICO)
def test_rota_com_c2_ou_nova_fica_fechada(caminho, metodo):
    assert D.decisao_publico(metodo, caminho, ABERTA) == "entrada"
    assert D.decisao_publico(metodo, caminho, FECHADA) == "entrada"


@pytest.mark.parametrize("politica", [FECHADA, ABERTA, None, {"publica": True, "preliminares": True}, "x"])
@pytest.mark.parametrize("metodo", METODOS)
@pytest.mark.parametrize("caminho", SEMPRE)
def test_entrada_estaticos_e_envio_nunca_dependem_da_politica(metodo, caminho, politica):
    assert D.decisao_publico(metodo, caminho, politica) == "liberada"


@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_escrita_publica_fica_fechada(metodo):
    assert D.decisao_publico(metodo, "/", ABERTA) == "entrada"


@pytest.mark.parametrize("caminho", PUBLICAS + ["/observatorio"])
def test_preliminares_gravados_nao_abrem_nada(caminho):
    assert D.decisao_publico("GET", caminho, {"publica": True, "preliminares": True}) == "entrada"


@pytest.mark.parametrize("caminho", PUBLICAS)
@pytest.mark.parametrize("politica", [None, {}, {"publica": True}, {"publica": "sim", "preliminares": False},
                                      {"publica": True, "preliminares": 0}, "x", ["publica"]])
def test_politica_malformada_vale_como_fechada(politica, caminho):
    assert D.decisao_publico("GET", caminho, politica) == "entrada"


# ======================== gravacao: o que o administrador pode pedir ========================
@pytest.mark.parametrize("nova,erros", [
    (ABERTA, []),
    (FECHADA, []),
    ({"publica": True, "preliminares": True}, ["A divulgação de resultados preliminares ainda não está disponível."]),
    ({"publica": False, "preliminares": True}, ["A divulgação de resultados preliminares ainda não está disponível."]),
    ({"publica": 1, "preliminares": False}, ["Configuração de divulgação inválida."]),
    ({"publica": True, "preliminares": 0}, ["Configuração de divulgação inválida."]),
    ({"publica": True, "preliminares": "false"}, ["Configuração de divulgação inválida."]),
    ({"publica": 1, "preliminares": True}, ["Configuração de divulgação inválida."]),          # forma errada vem antes
    ({"publica": True, "preliminares": True, "x": 1}, ["Configuração de divulgação inválida."]),
    ({"publica": True}, ["Configuração de divulgação inválida."]),
    ({"publica": True, "preliminares": False, "x": 1}, ["Configuração de divulgação inválida."]),
    (None, ["Configuração de divulgação inválida."]),
])
def test_validar_nova(nova, erros):
    assert D.validar_nova(nova) == erros


def test_valor_gravado_e_lido_de_volta():
    assert D.ler_politica(D.valor(ABERTA)) == (ABERTA, "valida")
    assert D.ler_politica(D.valor(FECHADA)) == (FECHADA, "valida")
    assert json.loads(D.valor(ABERTA)) == ABERTA


@pytest.mark.parametrize("politica", [None, {}, {"publica": True}, {"publica": True, "preliminares": True}, "x",
                                      {"publica": True, "preliminares": False, "x": 1}, {"publica": 1, "preliminares": False},
                                      {"publica": True, "preliminares": 0}])
def test_valor_recusa_politica_invalida(politica):
    with pytest.raises(ValueError):
        D.valor(politica)


def test_valor_usa_a_mesma_validacao(monkeypatch):
    from dominio import divulgacao
    monkeypatch.setattr(divulgacao, "validar_nova", lambda nova: ["recusada"])
    with pytest.raises(ValueError):
        divulgacao.valor(ABERTA)


# ======================== banco de contas (SQLite e PostgreSQL) ========================
def _gravar_bruto(c, chave, valor):
    with c._conexao(escrita=True) as conn:
        conn.execute("DELETE FROM configuracoes WHERE chave = ?", (chave,))
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, valor))


def test_contas_sem_configuracao(contas):  # noqa: F811
    assert contas.politica_divulgacao("real") == (FECHADA, "ausente")


def test_contas_com_configuracao_valida(contas):  # noqa: F811
    _gravar_bruto(contas, "divulgacao:vies", '{"publica": true, "preliminares": false}')
    assert contas.politica_divulgacao("vies") == (ABERTA, "valida")
    assert contas.politica_divulgacao("real") == (FECHADA, "ausente")              # uma pesquisa nao abre a outra


def test_contas_com_configuracao_invalida(contas):  # noqa: F811
    _gravar_bruto(contas, "divulgacao:real", '{"publica": true, "preliminares": true}')
    assert contas.politica_divulgacao("real") == (FECHADA, "invalida")


def test_contas_sqlite_com_valor_de_outro_tipo(tmp_path):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    _gravar_bruto(c, "divulgacao:real", b'{"publica": true, "preliminares": false}')   # o SQLite aceita qualquer tipo
    assert c.politica_divulgacao("real") == (FECHADA, "invalida")
    _gravar_bruto(c, "divulgacao:real", 1)
    assert c.politica_divulgacao("real") == (FECHADA, "invalida")


def test_uma_leitura_sem_escrita_e_sem_cache(tmp_path):
    import sqlite3
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    cmds = []
    original = sqlite3.connect

    def conectar(*a, **k):
        con = original(*a, **k)
        con.set_trace_callback(lambda s: cmds.append(" ".join(s.split())))
        return con
    import adaptadores.contas_sqlite as CS
    CS.sqlite3.connect, antes = conectar, CS.sqlite3.connect
    try:
        assert c.politica_divulgacao("real") == (FECHADA, "ausente")
    finally:
        CS.sqlite3.connect = antes
    assert [x for x in cmds if x.split()[0].upper() in ("SELECT", "WITH")] == [
        "SELECT valor FROM configuracoes WHERE chave = 'divulgacao:real'"]
    assert not [x for x in cmds if x.split()[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE")]
    assert c.politica_divulgacao("real") == (FECHADA, "ausente")                    # a leitura nao gravou a linha
    _gravar_bruto(c, "divulgacao:real", '{"publica": true, "preliminares": false}')
    assert c.politica_divulgacao("real") == (ABERTA, "valida")                       # sem cache


def test_outro_erro_do_banco_propaga(tmp_path, monkeypatch):
    import sqlite3
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()

    def quebrado(*a, **k):
        raise sqlite3.DatabaseError("arquivo corrompido")
    monkeypatch.setattr(c, "_conexao", quebrado)
    with pytest.raises(sqlite3.DatabaseError):
        c.politica_divulgacao("real")


def test_contas_ocupadas_propaga(tmp_path, monkeypatch):
    from dominio import autenticacao as A
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()

    def ocupado(*a, **k):
        raise A.ContasOcupadas()
    monkeypatch.setattr(c, "_conexao", ocupado)
    with pytest.raises(A.ContasOcupadas):
        c.politica_divulgacao("real")


def test_leitura_usa_a_regra_do_dominio(tmp_path, monkeypatch):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    vistos = []
    from dominio import divulgacao
    monkeypatch.setattr(divulgacao, "ler_politica", lambda v: vistos.append(v) or ({"publica": True, "preliminares": False}, "valida"))
    assert c.politica_divulgacao("real") == (ABERTA, "valida") and vistos == [None]
