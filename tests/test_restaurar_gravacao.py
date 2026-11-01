"""Restaurar escolhendo uma a uma as diferencas para o estado anterior a uma alteracao do historico. A pagina nao marca
nada; so as diferencas marcadas seguem para a revisao e a gravacao da edicao (confirmacao, justificativa, versao,
auditoria), e o servidor recalcula as escolhas sobre o estado gravado e o historico, na revisao e de novo dentro da
transacao de gravacao. A auditoria registra a origem restauracao:<registro> e as escolhas. Todos os bancos sao temporarios."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A
from test_admin import _gid, adm  # noqa: F401
from test_edicao_por_grupo import _erros, _post
from test_edicao_por_grupo import _form as _form_da_pagina
from test_painel import demo  # noqa: F401
from test_painel_acessibilidade import verificar

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}
AGORA = ("chefe", "2026-10-31T12:00:00+00:00")
INCOMPLETO = "O formulário veio incompleto. Abra o grupo de novo e refaça as alterações."
NADA = "Marque ao menos uma diferença para revisar."
FORA = "Esta alteração não está no histórico deste grupo."
SEM_ANTES = "Esta alteração foi registrada sem o estado anterior completo; não há o que restaurar."
CONFIRMAR = "Marque a confirmação das permissões sensíveis antes de gravar."
OCUPADO = "O banco de contas está ocupado. Tente de novo em alguns segundos."
INTRO = ("<p>Nada vem marcado. Marque uma a uma as diferenças que quer levar para a revisão; as não marcadas ficam como "
         "estão.</p>")


def _form(h, acao):
    """Os pares do formulario de `acao`; falha como assercao quando a pagina nao tem esse formulario."""
    assert f'<form method="post" action="{acao}"' in h, f"a pagina nao tem o formulario {acao}"
    return _form_da_pagina(h, acao)


def _d(p):
    return A.PERMISSOES[p]


def _nao_dif(p):
    return f"«{_d(p)}» não é uma diferença entre o grupo e o estado anterior escolhido. Compare de novo."


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


def _det(antes, concedidas=(), retiradas=(), origem="edicao", escolhidas=None, justificativa=""):
    d = {"antes": sorted(antes), "depois": sorted((set(antes) | set(concedidas)) - set(retiradas)),
         "concedidas": list(concedidas), "retiradas": list(retiradas), "justificativa": justificativa, "origem": origem}
    if escolhidas is not None:
        d["escolhidas"] = list(escolhidas)
    return json.dumps(d, ensure_ascii=False)


def _entrada(antes, i=7):
    return {"id": i, "quando": "2026-10-05T12:00:00+00:00", "admin_login": "ana", "nome": "Leitor",
            "detalhe": json.loads(_det(antes)), "texto": None}


# ======================== rotulo_origem ========================

@pytest.mark.parametrize("origem,esperado", [
    ("edicao", None),
    ("referencia:publico", "comparação com a referência de Público"),
    ("referencia:estudante_direito", "comparação com a referência de Estudante de Direito"),
    ("referencia:x", None), ("referencia:Publico", None), ("referencia:", None),
    ("restauracao:12", "restauração do estado anterior à alteração nº 12"),
    ("restauracao:1", "restauração do estado anterior à alteração nº 1"),
    ("restauracao:9223372036854775807", "restauração do estado anterior à alteração nº 9223372036854775807"),
    ("restauracao:9223372036854775808", None), ("restauracao:0", None), ("restauracao:012", None),
    ("restauracao:", None), ("restauracao:1a", None), ("restauracao:-1", None), ("restauracao: 1", None),
    ("restauracao:٣", None), ("restauracao:1\n", None), ("Restauracao:1", None), ("", None),
    (None, None), (7, None), (["restauracao:1"], None),
])
def test_rotulo_origem(origem, esperado):
    assert A.rotulo_origem(origem) == esperado


@pytest.mark.parametrize("origem,fim", [
    ("restauracao:12", " Origem: restauração do estado anterior à alteração nº 12."),
    ("referencia:publico", " Origem: comparação com a referência de Público."),
    ("restauracao:012", ""), ("edicao", ""),
])
def test_resumo_com_a_origem(origem, fim):
    texto = _det(["ver_painel"], ["triar_artigos"], origem=origem, escolhidas=["triar_artigos"])
    assert A.resumo_detalhe_auditoria(texto) == "Concedidas: triar_artigos. Retiradas: nenhuma." + fim


def test_resumo_usa_o_rotulo(monkeypatch):
    vistos = []
    monkeypatch.setattr(A, "rotulo_origem", lambda o: vistos.append(o) or "ORIGEM X")
    texto = _det(["ver_painel"], ["triar_artigos"], origem="edicao")
    assert A.resumo_detalhe_auditoria(texto) == "Concedidas: triar_artigos. Retiradas: nenhuma. Origem: ORIGEM X."
    assert vistos == ["edicao"]


# ======================== montar_escolhas_da_restauracao ========================

def _montar(atuais, antes, escolhidas, grupo="Leitor", entrada=...):
    e = _entrada(antes) if entrada is ... else entrada
    return A.montar_escolhas_da_restauracao(grupo, set(atuais), e, escolhidas)


def test_monta_as_listas_da_revisao():
    m = _montar(LEITOR, {"ver_painel", "triar_artigos"}, ["ver_custos", "triar_artigos"])
    assert m == {"exibidas": ["triar_artigos", "ver_custos"], "marcadas": ["triar_artigos"],
                 "escolhidas": ["triar_artigos", "ver_custos"], "erros": []}


@pytest.mark.parametrize("escolhidas,erros", [
    ([], [NADA]),
    ("triar_artigos", [INCOMPLETO]), ([1], [INCOMPLETO]), (None, [INCOMPLETO]),
    (["zz"], ["O formulário trouxe 1 permissão desconhecida."]),
    (["zz", "yy", "zz"], ["O formulário trouxe 2 permissões desconhecidas."]),
    (["ver_painel"], [_nao_dif("ver_painel")]),
    (["triar_artigos", "triar_artigos"], [f"«{_d('triar_artigos')}» foi escolhida mais de uma vez."]),
    (["zz", "ver_painel", "triar_artigos", "triar_artigos"],
     ["O formulário trouxe 1 permissão desconhecida.", _nao_dif("ver_painel"),
      f"«{_d('triar_artigos')}» foi escolhida mais de uma vez."]),
])
def test_escolhas_invalidas(escolhidas, erros):
    m = _montar(LEITOR, {"ver_painel", "triar_artigos"}, escolhidas)
    assert m == {"exibidas": [], "marcadas": [], "escolhidas": [], "erros": erros}


@pytest.mark.parametrize("grupo,entrada,erro", [
    ("Administrador", _entrada(["ver_painel"]), "O grupo Administrador tem acesso integral e não pode ser alterado."),
    ("Leitor", None, FORA),
    ("Leitor", {**_entrada([]), "detalhe": None, "texto": "x"}, SEM_ANTES),
])
def test_erros_da_comparacao_vencem(grupo, entrada, erro):
    m = _montar(LEITOR, set(), ["triar_artigos", "zz"], grupo=grupo, entrada=entrada)
    assert m == {"exibidas": [], "marcadas": [], "escolhidas": [], "erros": [erro]}


def test_montagem_usa_a_comparacao(monkeypatch):
    vistos = []
    falso = {"registro": 7, "conceder": [{"permissao": "ver_chamadas", "descricao": "x", "sensivel": True, "marcada": False}],
             "retirar": [], "erros": []}
    monkeypatch.setattr(A, "comparar_com_alteracao", lambda g, atuais, e: vistos.append((g, e["id"])) or falso)
    m = _montar(LEITOR, {"ver_painel"}, ["ver_chamadas"])
    assert vistos == [("Leitor", 7)]
    assert m == {"exibidas": ["ver_chamadas"], "marcadas": ["ver_chamadas"], "escolhidas": ["ver_chamadas"], "erros": []}


def test_referencia_continua_com_o_seu_texto():
    m = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["ver_painel"])
    assert m["erros"] == [f"«{_d('ver_painel')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo."]


# ======================== gravacao no adaptador ========================

@pytest.fixture(params=["sqlite", "postgres"])
def contas(request, tmp_path):
    if request.param == "sqlite":
        c = ContasSQLite(tmp_path / "contas.db")
        c.garantir_padrao()
        yield c
        return
    from adaptadores import migrador_postgres as M
    from adaptadores.contas_postgres import ContasPostgres
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    url = request.getfixturevalue("pg_url")
    M.aplicar(url)
    pool = criar_pool(url, maximo=8)
    c = ContasPostgres(pool, chaves_do_banco(pool))
    c.garantir_padrao()
    yield c
    pool.close()


def _g(c, nome):
    return next(g["grupo_id"] for g in c.grupos() if g["nome"] == nome)


def _p(c, nome):
    return set(next(g["permissoes"] for g in c.grupos() if g["nome"] == nome))


def _v(c, nome):
    return A.versao_permissoes({_g(c, nome): _p(c, nome)})


def _alteracao(c, nome, antes, quando="2026-10-05T12:00:00+00:00"):
    """Registra uma alteracao de `nome` cujo estado anterior era `antes`; devolve o id do registro."""
    c.auditar("ana", "salvar_permissoes", nome, _det(antes), quando)
    return c.registros_de_permissoes()[0]["id"]


def _gravar_res(c, nome, registro, escolhidas, marcadas=None, exibidas=None, confirmado=False, justificativa="",
                versao=None):
    entrada = next((h for h in A.historico_do_grupo(nome, c.registros_de_permissoes()) if h["id"] == registro), None)
    m = A.montar_escolhas_da_restauracao(nome, _p(c, nome), entrada, list(escolhidas))
    return c.definir_permissoes_do_grupo(
        _g(c, nome), m["marcadas"] if marcadas is None else list(marcadas),
        m["exibidas"] if exibidas is None else list(exibidas), _v(c, nome) if versao is None else versao,
        confirmado, justificativa, AGORA, restauracao=(registro, list(escolhidas)))


def _ultimo(c):
    return [(l["acao"], l["alvo"], l["detalhe"]) for l in c.auditoria()][0]


def test_grava_so_o_escolhido_e_audita(contas):
    i = _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    r = _gravar_res(contas, "Leitor", i, ["triar_artigos", "ver_custos"], justificativa="ok")
    assert r["concedidas"] == ["triar_artigos"] and r["retiradas"] == ["ver_custos"]
    assert _p(contas, "Leitor") == (LEITOR | {"triar_artigos"}) - {"ver_custos"}
    rev = A.revisar_alteracao("Leitor", LEITOR, ["triar_artigos"], ["triar_artigos", "ver_custos"])
    assert _ultimo(contas) == ("salvar_permissoes", "Leitor",
                               A.detalhe_auditoria(rev, "ok", origem=f"restauracao:{i}",
                                                   escolhidas=["triar_artigos", "ver_custos"]))


@pytest.mark.parametrize("marcadas,exibidas", [
    ([], ["triar_artigos"]), (["triar_artigos"], ["triar_artigos", "ver_custos"]),
    (["triar_artigos", "verificar_achados"], ["triar_artigos", "verificar_achados"]), ("triar_artigos", ["triar_artigos"]),
])
def test_listas_que_nao_batem_com_as_escolhas(contas, marcadas, exibidas):
    i = _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    n = len(contas.auditoria())
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar_res(contas, "Leitor", i, ["triar_artigos"], marcadas=marcadas, exibidas=exibidas)
    assert e.value.erros == [INCOMPLETO] and _p(contas, "Leitor") == LEITOR and len(contas.auditoria()) == n


@pytest.mark.parametrize("restauracao", [("1", ["triar_artigos"]), (1,), [1, ["triar_artigos"]], "x", (True, ["x"]),
                                         (1, ["triar_artigos"], 2)])
def test_restauracao_malformada(contas, restauracao):
    _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), ["triar_artigos"], ["triar_artigos"], _v(contas, "Leitor"),
                                           False, "", AGORA, restauracao=restauracao)
    assert e.value.erros == [INCOMPLETO] and _p(contas, "Leitor") == LEITOR


def test_referencia_e_restauracao_juntas(contas):
    i = _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), ["triar_artigos"], ["triar_artigos"], _v(contas, "Leitor"),
                                           False, "", AGORA, referencia=("estudante_direito", ["triar_artigos"]),
                                           restauracao=(i, ["triar_artigos"]))
    assert e.value.erros == [INCOMPLETO] and _p(contas, "Leitor") == LEITOR


def test_registro_de_outro_grupo_na_gravacao(contas):
    i = _alteracao(contas, "Revisor", {"ver_painel", "triar_artigos"})
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), ["triar_artigos"], ["triar_artigos"], _v(contas, "Leitor"),
                                           False, "", AGORA, restauracao=(i, ["triar_artigos"]))
    assert e.value.erros == [FORA] and _p(contas, "Leitor") == LEITOR


def test_versao_antiga_recusa_antes_das_escolhas(contas):
    i = _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    with pytest.raises(A.PermissoesAlteradas):
        _gravar_res(contas, "Leitor", i, ["ver_painel"], marcadas=[], exibidas=["ver_painel"], versao="x")


def test_sensivel_exige_confirmacao(contas):
    i = _alteracao(contas, "Leitor", {"ver_painel", "ver_chamadas"})
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar_res(contas, "Leitor", i, ["ver_chamadas"], justificativa="j")
    assert e.value.erros == [CONFIRMAR] and _p(contas, "Leitor") == LEITOR
    _gravar_res(contas, "Leitor", i, ["ver_chamadas"], confirmado=True, justificativa="j")
    assert "ver_chamadas" in _p(contas, "Leitor")


def test_visitante_proibida_recusada(contas):
    i = _alteracao(contas, "Visitante", {"ver_painel", "ver_custos"})
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar_res(contas, "Visitante", i, ["ver_custos"], confirmado=True, justificativa="j")
    assert e.value.erros == [f"«{_d('ver_custos')}» não pode ser dada a quem não entrou."]


def test_adaptador_usa_o_historico_e_a_montagem(contas, monkeypatch):
    i = _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    vistos = []
    hist, montar = A.historico_do_grupo, A.montar_escolhas_da_restauracao
    monkeypatch.setattr(A, "historico_do_grupo", lambda nome, regs: vistos.append(("h", nome, regs[0]["id"])) or hist(nome, regs))
    monkeypatch.setattr(A, "montar_escolhas_da_restauracao",
                        lambda g, atuais, e, esc: vistos.append(("m", g, e["id"], list(esc))) or montar(g, atuais, e, esc))
    contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), ["triar_artigos"], ["triar_artigos"], _v(contas, "Leitor"),
                                       False, "", AGORA, restauracao=(i, ["triar_artigos"]))
    assert vistos == [("h", "Leitor", i), ("m", "Leitor", i, ["triar_artigos"])]


def test_historico_lido_dentro_da_transacao(contas, monkeypatch):
    """A gravacao le o historico na sua propria conexao de escrita, nunca por outra leitura do repositorio."""
    i = _alteracao(contas, "Leitor", {"ver_painel", "triar_artigos"})
    monkeypatch.setattr(contas, "registros_de_permissoes", lambda: (_ for _ in ()).throw(AssertionError("leitura fora")))
    original = type(contas)._conexao
    modos = []

    def contar(self, *a, **k):
        modos.append(k.get("escrita", a[0] if a else False))
        return original(self, *a, **k)
    monkeypatch.setattr(type(contas), "_conexao", contar)
    contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), ["triar_artigos"], ["triar_artigos"],
                                       A.versao_permissoes({_g(contas, "Leitor"): LEITOR}), False, "", AGORA,
                                       restauracao=(i, ["triar_artigos"]))
    assert modos.count(True) == 1 and "triar_artigos" in _p(contas, "Leitor")


# ======================== tela ========================

def _restaurar(cli, gid, registro):
    return cli.get(f"/admin/grupos/{gid}/restaurar?registro={registro}").text


def _ultimo_id(contas_db):
    return sqlite3.connect(contas_db).execute("SELECT max(id) FROM auditoria_admin").fetchone()[0]


def _hist(contas, contas_db, nome="Leitor", antes=("ver_painel", "triar_artigos")):
    contas.auditar("ana", "salvar_permissoes", nome, _det(set(antes)), "2026-10-05T12:00:00+00:00")
    return _ultimo_id(contas_db)


def _caixas(h):
    return re.findall(r'<input type="checkbox" id="e-([a-z_]+)" name="escolhida" value="([a-z_]+)">', h)


def test_pagina_de_restauracao_e_um_formulario_sem_nada_marcado(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    h = _restaurar(cli, gid, i)
    assert "<form" in h and f'<form method="post" action="/admin/grupos/{gid}/revisar">' in h
    pares = _form(h, f"/admin/grupos/{gid}/revisar")
    assert [k for k, _ in pares] == ["csrf", "versao", "registro"]
    assert dict(pares)["registro"] == str(i) and dict(pares)["versao"] == A.versao_permissoes({gid: LEITOR})
    assert " checked" not in h and INTRO in h
    assert [c for c, _ in _caixas(h)] == ["triar_artigos", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"]
    for c, v in _caixas(h):
        assert c == v and f'<label for="e-{c}">{_d(c)}</label>' in h
    assert '<button class="botao" type="submit">Revisar as escolhidas</button>' in h
    assert "Esta página só mostra; nada é alterado aqui." not in h
    assert verificar(h) == []


def test_sem_diferenca_ou_sem_estado_anterior_nao_tem_formulario(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db, antes=LEITOR)
    assert "<form" not in _restaurar(cli, gid, i)[_restaurar(cli, gid, i).index("<main"):]
    contas.auditar("ana", "salvar_permissoes", "Leitor", "+x", "2026-10-05T12:00:00+00:00")
    h = _restaurar(cli, gid, _ultimo_id(contas_db))
    assert SEM_ANTES in h and "<form" not in h[h.index("<main"):]


def _revisar_res(cli, gid, registro, escolhidas, extra=()):
    h = _restaurar(cli, gid, registro)
    pares = _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", p) for p in escolhidas] + list(extra)
    return _post(cli, f"/admin/grupos/{gid}/revisar", pares)


def test_revisao_so_com_o_marcado(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    h = _revisar_res(cli, gid, i, ["triar_artigos"]).text
    assert "<h2>Serão concedidas (1)</h2>" in h and "Serão retiradas" not in h
    assert f"<p>Origem: restauração do estado anterior à alteração nº {i}. Só as diferenças marcadas estão abaixo.</p>" in h
    pares = _form(h, f"/admin/grupos/{gid}/permissoes")
    assert [k for k, _ in pares if k in ("marcada", "exibida", "perfil")] == []
    assert [p for k, p in pares if k == "registro"] == [str(i)] and [p for k, p in pares if k == "escolhida"] == ["triar_artigos"]
    assert f'<p><a href="/admin/grupos/{gid}/restaurar?registro={i}">Voltar à restauração</a></p>' in h
    assert "Voltar e editar" not in h and "Voltar à comparação" not in h


def test_revisao_da_referencia_continua_com_o_seu_texto(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}/comparar?perfil=estudante_direito").text
    pares = _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_artigos")]
    h = _post(cli, f"/admin/grupos/{gid}/revisar", pares).text
    assert "<p>Origem: comparação com a referência de Estudante de Direito. Só as diferenças marcadas estão abaixo.</p>" in h


@pytest.mark.parametrize("escolhidas,extra,erros", [
    ([], [], [NADA]),
    (["triar_artigos"], [("marcada", "triar_artigos")], [INCOMPLETO]),
    (["triar_artigos"], [("exibida", "triar_artigos")], [INCOMPLETO]),
    (["triar_artigos"], [("perfil", "publico")], [INCOMPLETO]),
    (["ver_painel"], [], [_nao_dif("ver_painel")]),
])
def test_revisao_com_erro_de_escolha(adm, escolhidas, extra, erros):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    h = _revisar_res(cli, gid, i, escolhidas, extra).text
    assert _erros(h) == erros and f'action="/admin/grupos/{gid}/permissoes"' not in h
    assert f'<p><a href="/admin/grupos/{gid}/editar">Voltar e editar</a></p>' in h and "Voltar à restauração" not in h


@pytest.mark.parametrize("registro", ["", "abc", "0", "-1", "99999", " ", "1.5"])
def test_revisao_com_registro_invalido_ou_fora(adm, registro):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    h = _restaurar(cli, gid, i)
    pares = [(k, registro if k == "registro" else v) for k, v in _form(h, f"/admin/grupos/{gid}/revisar")]
    h = _post(cli, f"/admin/grupos/{gid}/revisar", pares + [("escolhida", "triar_artigos")]).text
    esperado = [FORA] if registro in ("0", "99999") else [INCOMPLETO]
    assert _erros(h) == esperado and f'action="/admin/grupos/{gid}/permissoes"' not in h


def test_revisao_com_registro_repetido_ou_de_outro_grupo(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    h = _revisar_res(cli, gid, i, ["triar_artigos"], extra=[("registro", str(i))]).text
    assert _erros(h) == [INCOMPLETO]
    j = _hist(contas, contas_db, nome="Revisor")
    pares = [(k, str(j) if k == "registro" else v) for k, v in _form(_restaurar(cli, gid, i), f"/admin/grupos/{gid}/revisar")]
    h = _post(cli, f"/admin/grupos/{gid}/revisar", pares + [("escolhida", "triar_artigos")]).text
    assert _erros(h) == [FORA]


def test_revisao_com_dependencia_faltando_volta_a_restauracao(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db, antes=("ver_painel", "triar_artigos", "triar_texto_completo"))
    h = _revisar_res(cli, gid, i, ["triar_texto_completo"]).text
    assert _erros(h) and f'<p><a href="/admin/grupos/{gid}/restaurar?registro={i}">Voltar à restauração</a></p>' in h
    assert f'action="/admin/grupos/{gid}/permissoes"' not in h and "Origem:" not in h
    assert "<form" not in h[h.index("<main"):h.index("</main>")]


def test_revisao_le_o_historico_uma_vez_so_no_modo_restauracao(adm, monkeypatch):
    from test_edicao_por_grupo import _revisar
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    h = _restaurar(cli, gid, i)
    leituras = []
    original = contas.registros_de_permissoes
    monkeypatch.setattr(contas, "registros_de_permissoes", lambda: leituras.append(1) or original())
    _post(cli, f"/admin/grupos/{gid}/revisar", _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_artigos")])
    assert leituras == [1]
    _revisar(cli, gid, sorted(LEITOR | {"triar_artigos"}))
    assert leituras == [1]


def _gravar_tela(cli, gid, registro, escolhidas, confirmo=False, justificativa="", mexer=None):
    h = _revisar_res(cli, gid, registro, escolhidas).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{gid}/permissoes") if k != "confirmo"]
    if mexer:
        pares = mexer(pares)
    if confirmo:
        pares.append(("confirmo", "1"))
    pares.append(("justificativa", justificativa))
    return _post(cli, f"/admin/grupos/{gid}/permissoes", pares)


def test_grava_pela_tela_e_mostra_a_origem(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    r = _gravar_tela(cli, gid, i, ["triar_artigos", "ver_custos"])
    assert r.status_code == 303 and r.headers["location"] == f"/admin/grupos/{gid}?gravado=1"
    linha = sqlite3.connect(contas_db).execute(
        "SELECT acao, alvo, detalhe FROM auditoria_admin ORDER BY id DESC LIMIT 1").fetchone()
    d = json.loads(linha[2])
    assert linha[:2] == ("salvar_permissoes", "Leitor") and d["origem"] == f"restauracao:{i}"
    assert d["escolhidas"] == ["triar_artigos", "ver_custos"]
    h = cli.get(f"/admin/grupos/{gid}").text
    assert f"<p>Origem: restauração do estado anterior à alteração nº {i}.</p>" in h
    assert f"Origem: restauração do estado anterior à alteração nº {i}." in cli.get("/admin/auditoria").text


def test_historico_usa_o_rotulo(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    contas.auditar("ana", "salvar_permissoes", "Leitor", _det({"ver_painel"}, ["triar_artigos"], origem="qualquer"),
                   "2026-10-05T12:00:00+00:00")
    monkeypatch.setattr(A, "rotulo_origem", lambda o: f"ROTULO {o}")
    assert "<p>Origem: ROTULO qualquer.</p>" in cli.get(f"/admin/grupos/{gid}").text


@pytest.mark.parametrize("mexer", [
    lambda ps: ps + [("escolhida", "ver_painel")],
    lambda ps: [(k, v) for k, v in ps if k != "escolhida"],
    lambda ps: ps + [("marcada", "verificar_achados"), ("exibida", "verificar_achados")],
    lambda ps: [(k, "99999" if k == "registro" else v) for k, v in ps],
    lambda ps: ps + [("perfil", "estudante_direito")],
    lambda ps: ps + [("registro", "1")],
])
def test_formulario_adulterado_na_gravacao_nao_grava(adm, mexer):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    antes = sorted(sqlite3.connect(contas_db).execute("SELECT * FROM grupo_permissoes").fetchall())
    n = sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0]
    r = _gravar_tela(cli, gid, i, ["triar_artigos"], mexer=mexer)
    assert r.status_code == 400 and _erros(r.text)
    assert f'<p><a href="/admin/grupos/{gid}/editar">Voltar e editar</a></p>' in r.text
    assert "Voltar à restauração" not in r.text and f'action="/admin/grupos/{gid}/permissoes"' not in r.text
    assert sorted(sqlite3.connect(contas_db).execute("SELECT * FROM grupo_permissoes").fetchall()) == antes
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0] == n


def test_versao_errada_na_gravacao(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    r = _gravar_tela(cli, gid, i, ["triar_artigos"], mexer=lambda ps: [(k, "x" if k == "versao" else v) for k, v in ps])
    assert r.status_code == 409


def test_sensivel_pela_tela_volta_a_revisao_com_a_restauracao(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db, antes=("ver_painel", "ver_chamadas"))
    r = _gravar_tela(cli, gid, i, ["ver_chamadas"], justificativa="j")
    assert r.status_code == 400 and _erros(r.text) == [CONFIRMAR]
    pares = _form(r.text, f"/admin/grupos/{gid}/permissoes")
    assert [p for k, p in pares if k == "registro"] == [str(i)] and [p for k, p in pares if k == "escolhida"] == ["ver_chamadas"]
    assert f"<p>Origem: restauração do estado anterior à alteração nº {i}. Só as diferenças marcadas estão abaixo.</p>" in r.text
    assert f'<p><a href="/admin/grupos/{gid}/restaurar?registro={i}">Voltar à restauração</a></p>' in r.text
    pares = [(k, v) for k, v in pares if k not in ("confirmo", "justificativa")] + [("confirmo", "1"), ("justificativa", "j")]
    assert _post(cli, f"/admin/grupos/{gid}/permissoes", pares).status_code == 303


def test_gravacao_com_dependencia_faltando_volta_a_restauracao(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db, antes=("ver_painel", "triar_artigos", "triar_texto_completo"))
    pares = _form(_restaurar(cli, gid, i), f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_texto_completo"),
                                                                              ("justificativa", "")]
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text)
    assert f'<p><a href="/admin/grupos/{gid}/restaurar?registro={i}">Voltar à restauração</a></p>' in r.text


def test_gravacao_com_erro_de_escolha_volta_a_edicao(adm):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    pares = _form(_restaurar(cli, gid, i), f"/admin/grupos/{gid}/revisar") + [("justificativa", "")]
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text) == [NADA]
    assert f'<p><a href="/admin/grupos/{gid}/editar">Voltar e editar</a></p>' in r.text


@pytest.mark.parametrize("caminho", ["revisar", "permissoes"])
def test_contas_ocupadas_ao_ler_o_historico(adm, monkeypatch, caminho):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    i = _hist(contas, contas_db)
    pares = _form(_restaurar(cli, gid, i), f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_artigos")]

    def ocupado():
        raise A.ContasOcupadas("x")
    monkeypatch.setattr(contas, "registros_de_permissoes", ocupado)
    r = _post(cli, f"/admin/grupos/{gid}/{caminho}", pares)
    assert r.status_code == 503 and OCUPADO in r.text


def test_edicao_e_referencia_nao_leem_o_historico(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}/comparar?perfil=estudante_direito").text

    def nunca():
        raise AssertionError("historico lido fora do modo de restauracao")
    monkeypatch.setattr(contas, "registros_de_permissoes", nunca)
    pares = _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_artigos")]
    assert _post(cli, f"/admin/grupos/{gid}/revisar", pares).status_code == 200
