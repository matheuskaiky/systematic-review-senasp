"""Estado inicial da politica de divulgacao (D145, Q-P8-2 a): um comando com previa grava `divulgada` so quando a pesquisa ainda
nao tem configuracao e o grupo Visitante das contas ve o painel (preserva o acesso de hoje); nunca muda uma configuracao que
existe, nunca grava resultados preliminares e nunca roda na partida do painel. Grava pela mesma alteracao da tela, com a
auditoria `alterar_divulgacao` em nome de `linha-de-comando`."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from aplicacao import divulgacao_inicial as DI
from dominio import autenticacao as A
from dominio import divulgacao as D
from test_conta_token import contas  # noqa: F401

ABERTA = {"publica": True, "preliminares": False}
FECHADA = {"publica": False, "preliminares": False}
AGORA = "2026-10-31T10:00:00+00:00"
CAB = "Estado inicial da divulgação pública da pesquisa {banco}."
CONFIGURADA = ("A divulgação desta pesquisa já está configurada ({situacao}): este comando nunca muda uma configuração que "
               "existe. Para alterá-la, use a tela Divulgação pública do painel. Nada a gravar.")
FECHADA_TXT = ("O grupo Visitante não vê o painel nas contas desta pesquisa: ela continua não divulgada, como hoje. "
               "Nada a gravar.")
PROPOSTA = ("O grupo Visitante vê o painel nas contas desta pesquisa. Para preservar o acesso de hoje, a proposta é gravar "
            "«divulgada», sem resultados preliminares.")
EFEITO = ("Efeito: quem não entrou passará a ver a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e a busca no texto, sem "
          "resultados automatizados.")
GRAVADO = "Gravado: divulgada, sem resultados preliminares. A alteração está no registro de administração."


DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()


@pytest.fixture(autouse=True)
def _nunca_abre_o_data_real(monkeypatch):
    """Todo teste deste arquivo falha se algo tentar abrir um arquivo SQLite dentro do data/ de verdade (contas reais)."""
    import sqlite3
    original = sqlite3.connect

    def conectar(caminho, *a, **k):
        alvo = Path(str(caminho)).resolve() if str(caminho) != ":memory:" and not str(caminho).startswith("file:") else None
        if alvo is not None and (alvo == DADOS_REAIS or DADOS_REAIS in alvo.parents):
            raise AssertionError(f"teste tentou abrir {alvo}")
        return original(caminho, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", conectar)


def _codigo(banco, versao, publica=True):
    return hashlib.sha256(f"divulgacao-inicial|{banco}|{versao}|{int(publica)}".encode("utf-8")).hexdigest()[:12]


def _visitante(c, ve):
    gid = next(g["grupo_id"] for g in c.grupos() if g["nome"] == A.GRUPO_VISITANTE)
    c.definir_permissoes(gid, {"ver_painel"} if ve else set())


def _bruto(c, banco, valor):
    with c._conexao(escrita=True) as conn:
        conn.execute("DELETE FROM configuracoes WHERE chave = ?", (D.chave(banco),))
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (D.chave(banco), valor))


def _linha(c, banco="real"):
    with c._conexao() as conn:
        r = conn.execute("SELECT valor FROM configuracoes WHERE chave = ?", (D.chave(banco),)).fetchone()
    return r[0] if r else None


def _tudo(c):
    """Todo o estado das contas que um erro nunca pode mudar: configuracoes e registro de administracao."""
    with c._conexao() as conn:
        return (sorted(map(tuple, conn.execute("SELECT chave, valor FROM configuracoes").fetchall())),
                sorted(map(tuple, conn.execute("SELECT quando, admin_login, acao, alvo, detalhe FROM auditoria_admin").fetchall())))


def _auditoria(c):
    return [a for a in c.auditoria() if a["acao"] == "alterar_divulgacao"]


# ======================== regra pura ========================
@pytest.mark.parametrize("situacao,ve,esperado", [
    ("ausente", True, ("gravar", "proposta")),
    ("ausente", False, ("nada", "fechada")),
    ("valida", True, ("nada", "configurada")),
    ("valida", False, ("nada", "configurada")),
    ("invalida", True, ("nada", "configurada")),
    ("invalida", False, ("nada", "configurada")),
])
def test_plano_inicial(situacao, ve, esperado):
    estado = {"politica": FECHADA, "situacao": situacao, "versao": D.versao(None if situacao == "ausente" else "x")}
    p = D.plano_inicial("real", estado, ve)
    assert (p["acao"], p["motivo"]) == esperado
    assert p["nova"] == (ABERTA if esperado[0] == "gravar" else None)
    assert p["codigo"] == (_codigo("real", estado["versao"]) if esperado[0] == "gravar" else None)


def test_codigo_muda_com_a_pesquisa_e_com_a_versao():
    e = {"politica": FECHADA, "situacao": "ausente", "versao": D.versao(None)}
    assert D.plano_inicial("real", e, True)["codigo"] != D.plano_inicial("vies", e, True)["codigo"]
    e2 = {**e, "versao": "0" * 64}
    assert D.plano_inicial("real", e, True)["codigo"] != D.plano_inicial("real", e2, True)["codigo"]
    assert len(D.plano_inicial("real", e, True)["codigo"]) == 12


# ======================== previa e confirmacao ========================
def test_previa_propoe_divulgar_e_nao_grava(contas):  # noqa: F811
    _visitante(contas, True)
    antes = (_linha(contas), len(contas.auditoria()))
    linhas = DI.prever(contas, "real")
    assert linhas == [CAB.format(banco="real"), PROPOSTA, EFEITO,
                      f"Nada foi gravado. Código desta prévia: {_codigo('real', D.versao(None))}"]
    assert (_linha(contas), len(contas.auditoria())) == antes


@pytest.mark.parametrize("bruto,situacao", [('{"publica": false, "preliminares": false}', "válida"),
                                            ('{"publica": true, "preliminares": false}', "válida"),
                                            ("lixo", "inválida")])
def test_configuracao_existente_nunca_e_mudada(contas, bruto, situacao):  # noqa: F811
    _visitante(contas, True)
    _bruto(contas, "real", bruto)
    assert DI.prever(contas, "real") == [CAB.format(banco="real"), CONFIGURADA.format(situacao=situacao)]
    assert DI.confirmar(contas, "real", "qualquer", AGORA) == [CAB.format(banco="real"), CONFIGURADA.format(situacao=situacao)]
    assert _linha(contas) == bruto and _auditoria(contas) == []


def test_visitante_sem_painel_fica_fechada_sem_gravar(contas):  # noqa: F811
    _visitante(contas, False)
    assert DI.prever(contas, "real") == [CAB.format(banco="real"), FECHADA_TXT]
    assert DI.confirmar(contas, "real", None, AGORA) == [CAB.format(banco="real"), FECHADA_TXT]
    assert _linha(contas) is None and _auditoria(contas) == []


def test_confirmar_grava_a_previa_e_audita(contas):  # noqa: F811
    _visitante(contas, True)
    codigo = _codigo("real", D.versao(None))
    assert DI.confirmar(contas, "real", codigo, AGORA) == [CAB.format(banco="real"), GRAVADO]
    assert json.loads(_linha(contas)) == ABERTA
    aud = _auditoria(contas)
    assert [(a["admin_login"], a["alvo"], a["quando"]) for a in aud] == [("linha-de-comando", "real", AGORA)]
    assert json.loads(aud[0]["detalhe"]) == {"antes": FECHADA, "situacao_antes": "ausente", "versao_antes": D.versao(None),
                                             "depois": ABERTA}
    assert DI.confirmar(contas, "real", codigo, AGORA) == [CAB.format(banco="real"), CONFIGURADA.format(situacao="válida")]
    assert len(_auditoria(contas)) == 1                                           # rodar de novo nao grava


@pytest.mark.parametrize("codigo", [None, "", "000000000000", "X" * 12])
def test_codigo_errado_nao_grava(contas, codigo):  # noqa: F811
    _visitante(contas, True)
    antes = _tudo(contas)
    with pytest.raises(ValueError) as e:
        DI.confirmar(contas, "real", codigo, AGORA)
    assert str(e.value) == (f"A situação mudou desde a prévia (código atual: {_codigo('real', D.versao(None))}). "
                            "Rode a prévia de novo.")
    assert _tudo(contas) == antes


def test_codigo_de_outra_pesquisa_nao_vale(contas):  # noqa: F811
    _visitante(contas, True)
    antes = _tudo(contas)
    with pytest.raises(ValueError):
        DI.confirmar(contas, "vies", _codigo("real", D.versao(None)), AGORA)
    assert _tudo(contas) == antes


def test_visitante_perde_o_painel_depois_da_previa(contas):  # noqa: F811
    """A previa foi feita com o Visitante vendo o painel; ele perde a permissao antes da confirmacao: nada e gravado."""
    _visitante(contas, True)
    codigo = _codigo("real", D.versao(None))
    _visitante(contas, False)
    assert DI.confirmar(contas, "real", codigo, AGORA) == [CAB.format(banco="real"), FECHADA_TXT]
    assert _linha(contas) is None and _auditoria(contas) == []


def test_mudanca_durante_a_gravacao_e_recusada(contas, monkeypatch):  # noqa: F811
    """Outra pessoa grava entre a leitura do estado e a gravacao: a versao conferida recusa, nada e gravado pelo comando."""
    _visitante(contas, True)
    codigo = _codigo("real", D.versao(None))
    original = contas.alterar_divulgacao

    depois_do_outro = []

    def antes_outro_grava(banco, nova, versao, confirmado, auditoria):
        _bruto(contas, "real", '{"publica": false, "preliminares": false}')
        depois_do_outro.append(_tudo(contas))
        return original(banco, nova, versao, confirmado, auditoria)
    monkeypatch.setattr(contas, "alterar_divulgacao", antes_outro_grava)
    with pytest.raises(ValueError) as e:
        DI.confirmar(contas, "real", codigo, AGORA)
    assert str(e.value) == ("A configuração desta pesquisa mudou durante a gravação: nada foi gravado por este comando. "
                            "Rode a prévia de novo.")
    assert json.loads(_linha(contas)) == FECHADA and _auditoria(contas) == []
    assert _tudo(contas) == depois_do_outro[0]                       # o comando nao escreveu mais nada


def test_banco_ocupado_na_gravacao(contas, monkeypatch):  # noqa: F811
    _visitante(contas, True)
    antes = _tudo(contas)

    def ocupado(*a, **k):
        raise A.ContasOcupadas()
    monkeypatch.setattr(contas, "alterar_divulgacao", ocupado)
    with pytest.raises(ValueError) as e:
        DI.confirmar(contas, "real", _codigo("real", D.versao(None)), AGORA)
    assert str(e.value) == "O banco de contas está ocupado. Tente de novo em alguns segundos."
    monkeypatch.undo()
    assert _tudo(contas) == antes


def test_uma_pesquisa_nao_mexe_na_outra(contas):  # noqa: F811
    _visitante(contas, True)
    _bruto(contas, "vies", "lixo")
    DI.confirmar(contas, "real", _codigo("real", D.versao(None)), AGORA)
    assert _linha(contas, "vies") == "lixo" and json.loads(_linha(contas, "real")) == ABERTA


@pytest.mark.parametrize("banco", ["foo", "", None, "REAL", 1, ["real"], {"real": 1}, b"real"])
@pytest.mark.parametrize("funcao", ["prever", "confirmar"])
def test_pesquisa_invalida_antes_de_qualquer_leitura(contas, monkeypatch, banco, funcao):  # noqa: F811
    def nao_le(*a, **k):
        raise AssertionError("leu as contas")
    monkeypatch.setattr(contas, "estado_divulgacao", nao_le)
    monkeypatch.setattr(contas, "permissoes_do_grupo", nao_le)
    with pytest.raises(ValueError) as e:
        DI.prever(contas, banco) if funcao == "prever" else DI.confirmar(contas, banco, "x", AGORA)
    assert str(e.value) == "Pesquisa inválida."


@pytest.mark.parametrize("onde", ["estado_divulgacao", "permissoes_do_grupo"])
def test_banco_de_contas_ocupado(contas, monkeypatch, onde):  # noqa: F811
    _visitante(contas, True)
    antes = _tudo(contas)

    def ocupado(*a, **k):
        raise A.ContasOcupadas()
    monkeypatch.setattr(contas, onde, ocupado)
    for f in (lambda: DI.prever(contas, "real"), lambda: DI.confirmar(contas, "real", _codigo("real", D.versao(None)), AGORA)):
        with pytest.raises(ValueError) as e:
            f()
        assert str(e.value) == "O banco de contas está ocupado. Tente de novo em alguns segundos."
    monkeypatch.undo()
    assert _tudo(contas) == antes


def test_nunca_roda_na_partida_do_painel():
    """Nenhum caminho do painel nem da composicao importa ou chama o comando."""
    raiz = Path(__file__).resolve().parents[1]
    for arq in list((raiz / "painel").rglob("*.py")) + [raiz / "composicao.py"]:
        texto = arq.read_text(encoding="utf-8")
        assert "divulgacao_inicial" not in texto and "plano_inicial" not in texto, arq


# ======================== linha de comando ========================
def _main(monkeypatch, *args):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "divulgacao-inicial", *args])
    main.main()


def _contas_cli(ambiente_cli, nome="contas_simulado.db", ve=True):
    (ambiente_cli / "data").mkdir(parents=True, exist_ok=True)
    c = ContasSQLite(ambiente_cli / "data" / nome)
    c.garantir_padrao()
    _visitante(c, ve)
    return c


@pytest.mark.parametrize("args,arquivo", [(["--simulado"], "contas_simulado.db"), (["--demo"], "contas_demo.db"), ([], "contas.db")])
def test_cli_sem_banco_de_contas_nao_cria_nada(ambiente_cli, monkeypatch, args, arquivo):
    import config.settings as S
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", ambiente_cli / "data" / "busca.db")   # nunca o data/ de verdade
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, *args)
    assert str(e.value) == f"O banco de contas {arquivo} ainda não existe: não há política a gravar."
    assert not list((ambiente_cli / "data").rglob(arquivo)) if (ambiente_cli / "data").exists() else True


def test_cli_previa_confirmacao_e_reexecucao(ambiente_cli, monkeypatch, capsys):
    c = _contas_cli(ambiente_cli)
    _main(monkeypatch, "--simulado")
    saida = capsys.readouterr().out.splitlines()
    codigo = _codigo("simulado", D.versao(None))
    assert saida == [CAB.format(banco="simulado"), PROPOSTA, EFEITO, f"Nada foi gravado. Código desta prévia: {codigo}",
                     f"Para gravar exatamente isto: python main.py divulgacao-inicial --confirmar {codigo} --simulado"]
    _main(monkeypatch, "--simulado", "--confirmar", codigo)
    assert capsys.readouterr().out.splitlines() == [CAB.format(banco="simulado"), GRAVADO]
    assert json.loads(_linha(c, "simulado")) == ABERTA
    _main(monkeypatch, "--simulado")
    assert capsys.readouterr().out.splitlines()[-1] == CONFIGURADA.format(situacao="válida")


def test_cli_codigo_errado_diz_que_nada_foi_gravado(ambiente_cli, monkeypatch):
    c = _contas_cli(ambiente_cli)
    antes = _tudo(c)
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "--simulado", "--confirmar", "000000000000")
    assert str(e.value) == ("Nada foi gravado.\nA situação mudou desde a prévia (código atual: "
                            f"{_codigo('simulado', D.versao(None))}). Rode a prévia de novo.")
    assert _tudo(c) == antes


@pytest.mark.parametrize("extra", [["--simulado"], ["--demo"]])
def test_cli_banco_vies_com_simulacao_cai_na_regra_comum(ambiente_cli, monkeypatch, extra):
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "--banco", "vies", *extra)
    assert str(e.value) == "--banco vies não vale com --simulado nem com --demo."


def test_cli_ajuda_com_os_textos(ambiente_cli, monkeypatch, capsys):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "--help"])
    with pytest.raises(SystemExit):
        main.main()
    geral = " ".join(capsys.readouterr().out.split())
    assert ("grava o estado inicial da divulgação pública só quando ainda não existe; sem --confirmar só mostra a prévia"
            in geral)
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--help")
    ajuda = " ".join(capsys.readouterr().out.split())
    for texto in ("grava o estado previsto com o código informado", "fake adapters, no cost", "banco de demonstração"):
        assert texto in ajuda, texto


def test_comando_vale_no_postgres_com_banco_vies(ambiente_cli, monkeypatch):
    """No PostgreSQL o comando roda e aceita --banco vies (a chave e por pesquisa mesmo com as contas no esquema comum)."""
    import main
    assert "divulgacao-inicial" in main.COMANDOS_NO_POSTGRES
    chamados = []
    monkeypatch.setattr(main, "banco_do_ambiente", lambda: "postgres")
    monkeypatch.setattr(main, "divulgacao_inicial", lambda a: chamados.append((a.banco, a.confirmar)))
    import composicao
    monkeypatch.setattr(main, "banco_escolhido", lambda *a, **k: __import__("contextlib").nullcontext())
    _main(monkeypatch, "--banco", "vies")
    assert chamados == [("vies", None)]


def test_cli_simulado_e_demo_juntos(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "--simulado", "--demo")
    assert str(e.value) == "Use --simulado ou --demo, não os dois."


def test_cli_banco_vies_grava_so_a_chave_do_vies(ambiente_cli, monkeypatch, capsys):
    """--banco vies abre as contas do banco vies e grava divulgacao:vies."""
    import config.settings as S
    pasta = S.DATA_DIR / "vies"
    pasta.mkdir(parents=True, exist_ok=True)
    c = ContasSQLite(pasta / "contas.db")
    c.garantir_padrao()
    _visitante(c, True)
    _main(monkeypatch, "--banco", "vies")
    saida = capsys.readouterr().out.splitlines()
    codigo = _codigo("vies", D.versao(None))
    assert saida[0] == CAB.format(banco="vies")
    assert saida[-1] == f"Para gravar exatamente isto: python main.py divulgacao-inicial --confirmar {codigo} --banco vies"
    assert _linha(c, "vies") is None
    _main(monkeypatch, "--banco", "vies", "--confirmar", codigo)
    assert capsys.readouterr().out.splitlines() == [CAB.format(banco="vies"), GRAVADO]
    assert json.loads(_linha(c, "vies")) == ABERTA and _linha(c, "real") is None
