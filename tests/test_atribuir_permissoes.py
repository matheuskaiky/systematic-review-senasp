"""Comando que da as permissoes novas (ver_registros_revisao, ver_custos) aos grupos que ja viam esses dados com ver_painel.
Sem --confirmar so mostra a previa e nao grava nada; com --confirmar <codigo da previa> grava exatamente o que a previa mostrou,
numa transacao que recusa se as permissoes mudaram, e registra na auditoria. Leitor e Revisor (os grupos do projeto) recebem por
equivalencia; qualquer outro grupo so com aprovacao individual (--grupo NOME); o Visitante nunca."""
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from aplicacao import atribuicao_permissoes as AP
from dominio import autenticacao as A
from test_contas_postgres import pg  # noqa: F401

NOVAS = ("ver_registros_revisao", "ver_custos")
DADOS_REAIS = (Path(__file__).resolve().parent.parent / "data").resolve()


@pytest.fixture(autouse=True)
def _nunca_abre_o_data_real(monkeypatch):
    """Todo teste deste arquivo falha se algo tentar abrir um arquivo SQLite dentro do data/ de verdade (contas reais)."""
    original = sqlite3.connect

    def conectar(caminho, *a, **k):
        alvo = Path(str(caminho)).resolve() if str(caminho) != ":memory:" else None
        if alvo is not None and (alvo == DADOS_REAIS or DADOS_REAIS in alvo.parents):
            raise AssertionError(f"teste tentou abrir {alvo}")
        return original(caminho, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", conectar)
CABECALHO = ("Permissões novas: ver_registros_revisao (Ver observações e motivos das decisões) e ver_custos "
             "(Ver custos das execuções).")
NADA = "Nada a gravar: nenhum grupo precisa das permissões novas."


def _g(gid, nome, *perms):
    return {"grupo_id": gid, "nome": nome, "permissoes": set(perms)}


GRUPOS = [
    _g(1, "Administrador"), _g(2, "Visitante", "ver_painel"),
    _g(3, "Bolsistas", "ver_painel", "ver_custos"),           # outro grupo com ver_painel: incerto
    _g(4, "Convidados", "ver_nomes_revisores"),               # sem ver_painel
    _g(5, "Leitor", "ver_painel", "ver_nomes_revisores"),
    _g(6, "Revisor", "ver_painel", "ver_chamadas", "ver_registros_revisao", "ver_custos"),   # ja completo
]


def _codigo(conceder):
    linhas = [f"{c['grupo_id']}\t{c['nome']}\t{','.join(c['atuais'])}\t{','.join(c['adicionar'])}" for c in conceder]
    return hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()[:12]


# ---------------- dominio: o plano ----------------
def test_constantes():
    assert A.PERMISSOES_NOVAS == NOVAS and A.GRUPOS_EQUIVALENTES == ("Leitor", "Revisor")


def test_plano_sem_aprovacao():
    p = A.plano_permissoes_novas(GRUPOS)
    assert list(p) == ["conceder", "incertos", "completos", "fora", "codigo"]
    assert p["conceder"] == [{"grupo_id": 5, "nome": "Leitor", "atuais": ["ver_nomes_revisores", "ver_painel"],
                              "adicionar": ["ver_registros_revisao", "ver_custos"], "motivo": "equivalente"}]
    assert p["incertos"] == [{"grupo_id": 3, "nome": "Bolsistas", "adicionar": ["ver_registros_revisao"]}]
    assert p["completos"] == ["Revisor"]
    assert p["fora"] == [("Administrador", "tem todas pelo nome"), ("Visitante", "proibidas ao visitante"),
                         ("Convidados", "sem ver_painel")]
    assert p["codigo"] == _codigo(p["conceder"]) and len(p["codigo"]) == 12


def test_plano_com_aprovacao_individual():
    p = A.plano_permissoes_novas(GRUPOS, ["Bolsistas"])
    assert [c["nome"] for c in p["conceder"]] == ["Bolsistas", "Leitor"]                # na ordem dos grupos
    assert p["conceder"][0] == {"grupo_id": 3, "nome": "Bolsistas", "atuais": ["ver_custos", "ver_painel"],
                                "adicionar": ["ver_registros_revisao"], "motivo": "aprovado"}
    assert p["incertos"] == [] and p["codigo"] == _codigo(p["conceder"])
    assert A.plano_permissoes_novas(GRUPOS, ["Leitor", "Revisor"]) == A.plano_permissoes_novas(GRUPOS)   # redundantes: nada muda


@pytest.mark.parametrize("aprovados,mensagem", [
    (["Ninguem"], "Grupo não encontrado: Ninguem"),
    (["bolsistas"], "Grupo não encontrado: bolsistas"),                                  # o nome exato
    (["Administrador"], "O grupo Administrador não recebe permissões por este comando."),
    (["Visitante"], "O grupo Visitante não recebe permissões por este comando."),
    (["Convidados"], "O grupo Convidados não tem ver_painel: não via esses dados e não recebe as permissões novas."),
    (["Bolsistas", "Ninguem", "Visitante"], "Grupo não encontrado: Ninguem"),            # o primeiro erro, na ordem dada
])
def test_aprovacao_recusada(aprovados, mensagem):
    with pytest.raises(ValueError) as e:
        A.plano_permissoes_novas(GRUPOS, aprovados)
    assert str(e.value) == mensagem


@pytest.mark.parametrize("grupo,lista,item", [
    (_g(5, "Leitor", "ver_nomes_revisores"), "fora", ("Leitor", "sem ver_painel")),           # sem ver_painel vence a equivalencia
    (_g(6, "Revisor", "ver_painel", "ver_registros_revisao"), "conceder",
     {"grupo_id": 6, "nome": "Revisor", "atuais": ["ver_painel", "ver_registros_revisao"], "adicionar": ["ver_custos"],
      "motivo": "equivalente"}),
    (_g(7, "Estudantes", "ver_painel"), "incertos",
     {"grupo_id": 7, "nome": "Estudantes", "adicionar": ["ver_registros_revisao", "ver_custos"]}),
    (_g(8, "Professores", "ver_painel", *NOVAS), "completos", "Professores"),
])
def test_cada_ramo_da_classificacao(grupo, lista, item):
    p = A.plano_permissoes_novas([grupo])
    assert p[lista] == [item]
    assert sum(len(p[k]) for k in ("conceder", "incertos", "completos", "fora")) == 1


@pytest.mark.parametrize("perms,mensagem", [
    ({"ver_painel", "permissao_antiga"}, "O grupo Leitor tem permissões desconhecidas gravadas (permissao_antiga): corrija antes de atribuir."),
    ({"ver_painel", "zzz", "aaa"}, "O grupo Leitor tem permissões desconhecidas gravadas (aaa, zzz): corrija antes de atribuir."),
])
def test_quem_recebe_nao_pode_ter_permissao_desconhecida(perms, mensagem):
    with pytest.raises(ValueError) as e:
        A.plano_permissoes_novas([_g(5, "Leitor", *perms)])
    assert str(e.value) == mensagem
    p = A.plano_permissoes_novas([_g(7, "Estudantes", *perms)])          # quem nao recebe nada nao e recusado
    assert [c["nome"] for c in p["incertos"]] == ["Estudantes"]


def test_codigo_muda_com_o_estado_de_quem_recebe():
    base = A.plano_permissoes_novas(GRUPOS)["codigo"]
    outro_leitor = [dict(g, permissoes=g["permissoes"] | {"ver_chamadas"}) if g["nome"] == "Leitor" else g for g in GRUPOS]
    assert A.plano_permissoes_novas(outro_leitor)["codigo"] != base
    outro_convidado = [dict(g, permissoes={"ver_estatisticas_usuarios"}) if g["nome"] == "Convidados" else g for g in GRUPOS]
    assert A.plano_permissoes_novas(outro_convidado)["codigo"] == base                  # so quem recebe entra no codigo


def test_nada_a_conceder_sem_codigo():
    p = A.plano_permissoes_novas([_g(1, "Administrador"), _g(6, "Revisor", "ver_painel", *NOVAS)])
    assert p["conceder"] == [] and p["codigo"] is None and p["completos"] == ["Revisor"]


# ---------------- aplicacao: previa e confirmacao sobre as contas ----------------
@pytest.fixture
def contas(tmp_path):
    """Um banco de contas "antigo": Leitor e Revisor como antes das permissoes novas, um grupo criado a mao e usuarios ativos."""
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    gid = {g["nome"]: g["grupo_id"] for g in c.grupos()}
    c.definir_permissoes(gid["Leitor"], {"ver_painel", "ver_nomes_revisores"})
    c.definir_permissoes(gid["Revisor"], set(A.GRUPOS_PADRAO["Revisor"]) - set(NOVAS))
    b = c.criar_grupo("Bolsistas", "2026-10-27T00:00:00+00:00")
    c.definir_permissoes(b, {"ver_painel"})
    for login, grupo, ativo in (("ana", "Leitor", 1), ("bia", "Leitor", 1), ("cid", "Leitor", 0), ("dani", "Revisor", 1),
                                ("eva", "Bolsistas", 1)):
        uid = c.criar_usuario(login, login.title(), gid.get(grupo, b), A.hash_senha("senha-de-teste-123"), "2026-10-27T00:00:00+00:00")
        if not ativo:
            c.definir_ativo(uid, 0)
    return c, tmp_path / "contas.db"


def _estado(caminho):
    con = sqlite3.connect(caminho)
    perms = sorted(con.execute("SELECT g.nome, p.permissao FROM grupo_permissoes p JOIN grupos g USING (grupo_id)").fetchall())
    aud = con.execute("SELECT admin_login, acao, alvo, detalhe FROM auditoria_admin ORDER BY rowid").fetchall()
    return perms, aud


def test_previa_exata_e_nao_grava(contas):
    c, caminho = contas
    antes = _estado(caminho)
    linhas = AP.prever(c, [])
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    assert linhas == [
        CABECALHO,
        "Recebem com --confirmar:",
        "  Leitor: + ver_registros_revisao, ver_custos (2 usuário(s) ativo(s); acesso equivalente ao de hoje)",
        "  Revisor: + ver_registros_revisao, ver_custos (1 usuário(s) ativo(s); acesso equivalente ao de hoje)",
        "Precisam de aprovação individual (acrescente --grupo NOME para incluir):",
        "  Bolsistas: + ver_registros_revisao, ver_custos (1 usuário(s) ativo(s))",
        "Não recebem: Administrador (tem todas pelo nome), Visitante (proibidas ao visitante)",
        f"Nada foi gravado. Código desta prévia: {codigo}",
    ]
    assert _estado(caminho) == antes


def test_previa_com_aprovacao_e_secoes_vazias_omitidas(contas):
    c, _ = contas
    linhas = AP.prever(c, ["Bolsistas"])
    assert "  Bolsistas: + ver_registros_revisao, ver_custos (1 usuário(s) ativo(s); aprovado com --grupo)" in linhas
    assert not any(l.startswith("Precisam de aprovação") for l in linhas)
    assert not any(l.startswith("Já têm") for l in linhas)


def test_confirmar_grava_exatamente_a_previa_e_audita(contas):
    c, caminho = contas
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    linhas = AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")
    assert linhas == ["Gravado:", "  Leitor: + ver_registros_revisao, ver_custos", "  Revisor: + ver_registros_revisao, ver_custos",
                      "Registrado na auditoria (salvar_permissoes, por linha-de-comando)."]
    perms = {g["nome"]: g["permissoes"] for g in c.grupos()}
    assert perms["Leitor"] == {"ver_painel", "ver_nomes_revisores", *NOVAS}
    assert perms["Revisor"] == set(A.GRUPOS_PADRAO["Revisor"]) and perms["Bolsistas"] == {"ver_painel"}
    assert set(NOVAS).isdisjoint(perms["Visitante"])
    aud = _estado(caminho)[1]
    revisor_antes = sorted(set(A.GRUPOS_PADRAO["Revisor"]) - set(NOVAS))
    assert aud[-2:] == [
        ("linha-de-comando", "salvar_permissoes", "Leitor",
         "antes: ver_nomes_revisores, ver_painel; depois: ver_custos, ver_nomes_revisores, ver_painel, ver_registros_revisao"),
        ("linha-de-comando", "salvar_permissoes", "Revisor",
         f"antes: {', '.join(revisor_antes)}; depois: {', '.join(sorted(A.GRUPOS_PADRAO['Revisor']))}")]
    # segunda vez: nada a fazer, nada gravado
    antes = _estado(caminho)
    assert AP.confirmar(c, [], codigo, "2026-10-28T10:01:00+00:00") == [NADA]
    assert AP.prever(c, [])[-1] == "Nada foi gravado: só há grupos que precisam de aprovação individual."    # sobra Bolsistas
    assert _estado(caminho) == antes


@pytest.mark.parametrize("codigo", ["", "000000000000", "abc", None])
def test_codigo_errado_nao_grava(contas, codigo):
    c, caminho = contas
    antes = _estado(caminho)
    atual = A.plano_permissoes_novas(c.grupos())["codigo"]
    with pytest.raises(ValueError) as e:
        AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")
    assert str(e.value) == f"A situação mudou desde a prévia (código atual: {atual}). Rode a prévia de novo."
    assert _estado(caminho) == antes


def test_codigo_de_uma_previa_antiga_nao_vale(contas):
    c, caminho = contas
    antigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    gid = {g["nome"]: g["grupo_id"] for g in c.grupos()}
    c.definir_permissoes(gid["Leitor"], {"ver_painel", "ver_nomes_revisores", "ver_chamadas"})     # mudou depois da previa
    antes = _estado(caminho)
    atual = A.plano_permissoes_novas(c.grupos())["codigo"]
    assert atual != antigo
    with pytest.raises(ValueError) as e:
        AP.confirmar(c, [], antigo, "2026-10-28T10:00:00+00:00")
    assert str(e.value) == f"A situação mudou desde a prévia (código atual: {atual}). Rode a prévia de novo."
    assert _estado(caminho) == antes


def test_codigo_de_outra_aprovacao_nao_vale(contas):
    c, caminho = contas
    sem = A.plano_permissoes_novas(c.grupos())["codigo"]
    antes = _estado(caminho)
    with pytest.raises(ValueError):
        AP.confirmar(c, ["Bolsistas"], sem, "2026-10-28T10:00:00+00:00")       # a previa vista nao incluia Bolsistas
    assert _estado(caminho) == antes


def test_mudanca_durante_a_gravacao_e_recusada(contas, monkeypatch):
    c, caminho = contas
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    original = ContasSQLite.definir_matriz

    def outro_admin_mexe_antes(self, *a, **k):
        sqlite3.connect(caminho).execute(
            "INSERT INTO grupo_permissoes (grupo_id, permissao) SELECT grupo_id, 'ver_chamadas' FROM grupos WHERE nome='Leitor'"
        ).connection.commit()
        return original(self, *a, **k)
    monkeypatch.setattr(ContasSQLite, "definir_matriz", outro_admin_mexe_antes)
    with pytest.raises(ValueError) as e:
        AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")
    assert str(e.value) == "As permissões mudaram durante a gravação. Rode a prévia de novo."
    perms = {g["nome"]: g["permissoes"] for g in c.grupos()}
    assert perms["Leitor"] == {"ver_painel", "ver_nomes_revisores", "ver_chamadas"} and set(NOVAS).isdisjoint(perms["Revisor"])


def test_nome_com_caractere_de_controle_aparece_substituido(contas):
    c, _ = contas
    g = c.criar_grupo("Bols\nistas\x1b[2J", "2026-10-27T00:00:00+00:00")
    c.definir_permissoes(g, {"ver_painel"})
    linhas = AP.prever(c, [])
    assert "  Bols\ufffdistas\ufffd[2J: + ver_registros_revisao, ver_custos (0 usuário(s) ativo(s))" in linhas
    assert all("\n" not in l and "\x1b" not in l for l in linhas)
    assert AP.nome_exibido("A\tB\u200bC\x7f") == "A\ufffdB\ufffdC\ufffd" and AP.nome_exibido("Ação") == "Ação"


def test_erro_de_aprovacao_chega_como_valueerror(contas):
    c, _ = contas
    with pytest.raises(ValueError) as e:
        AP.prever(c, ["Visitante"])
    assert str(e.value) == "O grupo Visitante não recebe permissões por este comando."


# ---------------- PostgreSQL: as mesmas regras ----------------
@pytest.mark.postgres
def test_previa_e_confirmacao_no_postgres(pg):  # noqa: F811
    c, _, _ = pg
    gid = {g["nome"]: g["grupo_id"] for g in c.grupos()}
    c.definir_permissoes(gid["Leitor"], {"ver_painel", "ver_nomes_revisores"})
    antes = {g["nome"]: set(g["permissoes"]) for g in c.grupos()}
    linhas = AP.prever(c, [])
    assert linhas[0] == CABECALHO and {g["nome"]: set(g["permissoes"]) for g in c.grupos()} == antes
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    assert AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")[0] == "Gravado:"
    assert {g["nome"]: set(g["permissoes"]) for g in c.grupos()}["Leitor"] == {"ver_painel", "ver_nomes_revisores", *NOVAS}
    assert AP.confirmar(c, [], codigo, "2026-10-28T10:01:00+00:00") == [NADA]


# ---------------- linha de comando ----------------
def _main(monkeypatch, *args):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "atribuir-permissoes", "--simulado", *args])
    main.main()


def test_cli_sem_banco_de_contas_nao_cria_nada(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch)
    assert str(e.value) == "O banco de contas contas_simulado.db ainda não existe: não há grupos para atualizar."
    assert not (ambiente_cli / "data" / "contas_simulado.db").exists()


def _contas_cli(ambiente_cli):
    (ambiente_cli / "data").mkdir(parents=True, exist_ok=True)
    c = ContasSQLite(ambiente_cli / "data" / "contas_simulado.db")
    c.garantir_padrao()
    gid = {g["nome"]: g["grupo_id"] for g in c.grupos()}
    c.definir_permissoes(gid["Leitor"], {"ver_painel"})
    b = c.criar_grupo("Bolsas e estágios", "2026-10-27T00:00:00+00:00")
    c.definir_permissoes(b, {"ver_painel"})
    return c


def test_cli_previa_confirmacao_e_reexecucao(ambiente_cli, monkeypatch, capsys):
    c = _contas_cli(ambiente_cli)
    _main(monkeypatch)
    saida = capsys.readouterr().out.splitlines()
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    assert saida[0] == CABECALHO and saida[-2] == f"Nada foi gravado. Código desta prévia: {codigo}"
    assert saida[-1] == f"Para gravar exatamente isto: python main.py atribuir-permissoes --confirmar {codigo} --simulado"
    _main(monkeypatch, "--grupo", "Bolsas e estágios")
    saida = capsys.readouterr().out.splitlines()
    codigo2 = A.plano_permissoes_novas(c.grupos(), ["Bolsas e estágios"])["codigo"]
    assert saida[-1] == ("Para gravar exatamente isto: python main.py atribuir-permissoes --confirmar "
                         f"{codigo2} --grupo 'Bolsas e estágios' --simulado")
    _main(monkeypatch, "--confirmar", codigo2, "--grupo", "Bolsas e estágios")
    saida = capsys.readouterr().out.splitlines()
    assert saida[0] == "Gravado:" and "  Bolsas e estágios: + ver_registros_revisao, ver_custos" in saida
    _main(monkeypatch)
    assert capsys.readouterr().out.splitlines()[-1] == NADA


@pytest.mark.parametrize("args,mensagem", [
    (["--grupo", "Visitante"], "Nada foi gravado.\nO grupo Visitante não recebe permissões por este comando."),
    (["--confirmar", "000000000000"], None),           # a mensagem traz o codigo atual: conferida abaixo
])
def test_cli_erros_dizem_que_nada_foi_gravado(ambiente_cli, monkeypatch, args, mensagem):
    c = _contas_cli(ambiente_cli)
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, *args)
    if mensagem is None:
        atual = A.plano_permissoes_novas(c.grupos())["codigo"]
        mensagem = f"Nada foi gravado.\nA situação mudou desde a prévia (código atual: {atual}). Rode a prévia de novo."
    assert str(e.value) == mensagem


def test_cli_simulado_e_demo_juntos(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "--demo")
    assert str(e.value) == "Use --simulado ou --demo, não os dois."


def test_cli_no_postgres_nao_usa_banco(monkeypatch):
    import main
    monkeypatch.setattr(main, "banco_do_ambiente", lambda: "postgres")
    monkeypatch.setattr(sys, "argv", ["main.py", "atribuir-permissoes", "--banco", "vies"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert str(e.value) == ("atribuir-permissoes no PostgreSQL não usa --banco: as contas são as mesmas nos dois bancos "
                            "(esquema public).")
    assert "atribuir-permissoes" in main.COMANDOS_NO_POSTGRES


def test_previa_so_com_incertos_mostra_os_incertos(contas):
    c, caminho = contas
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")           # Leitor e Revisor ja recebem; sobra Bolsistas
    antes = _estado(caminho)
    assert AP.prever(c, []) == [
        CABECALHO,
        "Precisam de aprovação individual (acrescente --grupo NOME para incluir):",
        "  Bolsistas: + ver_registros_revisao, ver_custos (1 usuário(s) ativo(s))",
        "Já têm as permissões novas: Leitor, Revisor",
        "Não recebem: Administrador (tem todas pelo nome), Visitante (proibidas ao visitante)",
        "Nada foi gravado: só há grupos que precisam de aprovação individual.",
    ]
    assert AP.confirmar(c, [], "qualquer", "2026-10-28T10:02:00+00:00") == [NADA] and _estado(caminho) == antes


def test_cli_previa_nao_grava(ambiente_cli, monkeypatch, capsys):
    _contas_cli(ambiente_cli)
    caminho = ambiente_cli / "data" / "contas_simulado.db"
    antes = _estado(caminho)
    _main(monkeypatch)
    capsys.readouterr()
    assert _estado(caminho) == antes


def _isolar_banco_padrao(ambiente_cli, monkeypatch):
    """Sem --simulado nem --demo as contas ficam ao lado do banco da pesquisa (S.OPCOES["sqlite"]): aponta-o para a pasta
    temporaria, para o teste nunca abrir o data/ de verdade."""
    from config import settings as S
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", ambiente_cli / "data" / "busca.db")


@pytest.mark.parametrize("args,arquivo", [([], "contas.db"), (["--demo"], "contas_demo.db")])
def test_cli_caminhos_sem_simulado(ambiente_cli, monkeypatch, args, arquivo):
    import main
    _isolar_banco_padrao(ambiente_cli, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["main.py", "atribuir-permissoes", *args])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert str(e.value) == f"O banco de contas {arquivo} ainda não existe: não há grupos para atualizar."
    assert not list(ambiente_cli.rglob(arquivo))


def test_cli_caminho_padrao_com_banco_de_contas(ambiente_cli, monkeypatch, capsys):
    import main
    _isolar_banco_padrao(ambiente_cli, monkeypatch)
    (ambiente_cli / "data").mkdir(parents=True, exist_ok=True)
    c = ContasSQLite(ambiente_cli / "data" / "contas.db")
    c.garantir_padrao()
    c.definir_permissoes(next(g["grupo_id"] for g in c.grupos() if g["nome"] == "Leitor"), {"ver_painel"})
    monkeypatch.setattr(sys, "argv", ["main.py", "atribuir-permissoes"])
    main.main()
    saida = capsys.readouterr().out.splitlines()
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    assert saida[-1] == f"Para gravar exatamente isto: python main.py atribuir-permissoes --confirmar {codigo}"


def test_cli_varios_grupos_na_ordem_e_com_aspas(ambiente_cli, monkeypatch, capsys):
    c = _contas_cli(ambiente_cli)
    g = c.criar_grupo("D'Avila", "2026-10-27T00:00:00+00:00")
    c.definir_permissoes(g, {"ver_painel"})
    nomes = ["D'Avila", "Bolsas e estágios", "D'Avila"]
    _main(monkeypatch, *[x for n in nomes for x in ("--grupo", n)])
    saida = capsys.readouterr().out.splitlines()
    codigo = A.plano_permissoes_novas(c.grupos(), nomes)["codigo"]
    assert saida[-1] == ("Para gravar exatamente isto: python main.py atribuir-permissoes --confirmar "
                         f"{codigo} --grupo 'D'\"'\"'Avila' --grupo 'Bolsas e estágios' --grupo 'D'\"'\"'Avila' --simulado")


def test_cli_ajuda(monkeypatch, capsys):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "--help"])
    with pytest.raises(SystemExit):
        main.main()
    texto = " ".join(capsys.readouterr().out.split())
    assert ("dá ver_registros_revisao e ver_custos aos grupos que já viam esses dados; sem --confirmar só mostra a prévia" in texto)


def test_cli_banco_com_simulado_e_demo_cai_na_regra_comum(ambiente_cli, monkeypatch):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "atribuir-permissoes", "--banco", "vies", "--simulado", "--demo"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert str(e.value) == "--banco vies não vale com --simulado nem com --demo."


def test_cli_erro_com_nome_de_grupo_com_controle_e_substituido(ambiente_cli, monkeypatch):
    _contas_cli(ambiente_cli)
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "--grupo", "X\nY\x1b[2J")
    assert str(e.value) == "Nada foi gravado.\nGrupo não encontrado: X�Y�[2J"


# ---------------- casos pedidos na ordem de 28/10: grupo criado depois, falha no meio, permissoes alheias, adaptador ----------------
def _mapa(c):
    return {g["nome"]: set(g["permissoes"]) for g in c.grupos()}


def test_grupo_criado_depois_da_previa_nao_e_tocado(contas):
    c, caminho = contas
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    novo = c.criar_grupo("Criado depois", "2026-10-28T09:00:00+00:00")
    c.definir_permissoes(novo, {"ver_painel"})
    AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")             # o codigo so cobre quem recebe: continua valido
    m = _mapa(c)
    assert m["Criado depois"] == {"ver_painel"} and NOVAS[0] in m["Leitor"]
    assert all(r[2] != "Criado depois" for r in _estado(caminho)[1])


def test_permissoes_alheias_e_atuais_ficam(contas):
    c, _ = contas
    antes = _mapa(c)
    plano = A.plano_permissoes_novas(c.grupos())
    AP.confirmar(c, [], plano["codigo"], "2026-10-28T10:00:00+00:00")
    depois = _mapa(c)
    recebem = {x["nome"] for x in plano["conceder"]}
    assert {k: v for k, v in depois.items() if k not in recebem} == {k: v for k, v in antes.items() if k not in recebem}
    for nome in recebem:
        assert depois[nome] == antes[nome] | set(NOVAS)


def test_falha_no_meio_da_gravacao_nao_deixa_nada(contas, monkeypatch):
    c, caminho = contas
    antes = _estado(caminho)
    codigo = A.plano_permissoes_novas(c.grupos())["codigo"]
    original = ContasSQLite._aplicar_permissoes
    chamadas = []

    def falha_no_segundo(self, *a, **k):
        chamadas.append(1)
        if len(chamadas) == 2:
            raise RuntimeError("disco cheio")
        return original(self, *a, **k)
    monkeypatch.setattr(ContasSQLite, "_aplicar_permissoes", falha_no_segundo)
    with pytest.raises(RuntimeError):
        AP.confirmar(c, [], codigo, "2026-10-28T10:00:00+00:00")
    assert len(chamadas) == 2 and _estado(caminho) == antes                # o primeiro grupo tambem voltou atras
    monkeypatch.setattr(ContasSQLite, "_aplicar_permissoes", original)
    assert AP.confirmar(c, [], codigo, "2026-10-28T10:01:00+00:00")[0] == "Gravado:"     # a conexao ficou livre


def test_adaptador_detalhe_proprio_so_quando_pedido(contas):
    c, caminho = contas
    gid = {g["nome"]: g["grupo_id"] for g in c.grupos()}
    l, b = gid["Leitor"], gid["Bolsistas"]
    assert c.definir_matriz({l: {"ver_painel"}}, ("adm", "2026-10-28T10:00:00+00:00")) == 1           # sem detalhes: como antes
    assert _estado(caminho)[1][-1] == ("adm", "salvar_permissoes", "Leitor", "-ver_nomes_revisores")
    n = c.definir_matriz({l: {"ver_painel", "ver_custos"}, b: {"ver_painel"}}, ("adm", "2026-10-28T10:01:00+00:00"),
                         detalhes={l: "texto escolhido", b: "nao usado: o grupo nao mudou"})
    assert n == 1 and _estado(caminho)[1][-1] == ("adm", "salvar_permissoes", "Leitor", "texto escolhido")
    assert len([x for x in _estado(caminho)[1] if x[2] == "Bolsistas"]) == 0


def test_cli_confirmar_vazio_e_uma_confirmacao_recusada(ambiente_cli, monkeypatch):
    """`--confirmar ""` foi dado: e uma confirmacao (com codigo errado), nunca a previa."""
    c = _contas_cli(ambiente_cli)
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "--confirmar", "")
    atual = A.plano_permissoes_novas(c.grupos())["codigo"]
    assert str(e.value) == f"Nada foi gravado.\nA situação mudou desde a prévia (código atual: {atual}). Rode a prévia de novo."
