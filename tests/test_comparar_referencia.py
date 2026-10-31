"""Comparar um grupo com uma referencia e levar a revisao so as diferencas marcadas uma a uma. A pagina de comparacao
nao marca nada; a revisao e a gravacao sao as da edicao por grupo (confirmacao, justificativa, versao, auditoria), e o
servidor recalcula as escolhas sobre o estado gravado, sem confiar nas listas que o formulario traz. A auditoria registra a
origem e as escolhas enviadas. Todos os bancos sao temporarios."""
import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A
from test_admin import _auditoria, _criar, _csrf, _gid, adm  # noqa: F401
from test_edicao_por_grupo import _erros, _form, _post
from test_painel import demo  # noqa: F401

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
TODAS = list(A.PERMISSOES)
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}
AGORA = ("chefe", "2026-10-31T12:00:00+00:00")
ADMIN = "O grupo Administrador tem acesso integral e não pode ser alterado."
INCOMPLETO = "O formulário veio incompleto. Abra o grupo de novo e refaça as alterações."
ESCOLHA = "Escolha um dos perfis de referência da lista."
SO_PUBLICO = "O grupo Visitante só pode ser comparado com a referência do Público."
NADA = "Marque ao menos uma diferença para revisar."
CONFIRMAR = "Marque a confirmação das permissões sensíveis antes de gravar."
INTRO = ("<p>Nada vem marcado. Marque uma a uma as diferenças que quer levar para a revisão; as não marcadas ficam como "
         "estão.</p>")


def _d(p):
    return A.PERMISSOES[p]


def _nao_dif(p):
    return f"«{_d(p)}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo."


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


# ======================== auditoria (funcoes puras) ========================

def _rev(grupo, atuais, marcadas, exibidas):
    return A.revisar_alteracao(grupo, set(atuais), list(marcadas), list(exibidas))


def test_detalhe_com_escolhas():
    r = _rev("Leitor", LEITOR, ["triar_artigos"], ["triar_artigos", "ver_custos"])
    d = json.loads(A.detalhe_auditoria(r, "x", origem="referencia:estudante_direito",
                                       escolhidas=["triar_artigos", "ver_custos"]))
    assert list(d) == ["antes", "depois", "concedidas", "retiradas", "justificativa", "origem", "escolhidas"]
    assert d["origem"] == "referencia:estudante_direito" and d["escolhidas"] == ["triar_artigos", "ver_custos"]
    assert d["concedidas"] == ["triar_artigos"] and d["retiradas"] == ["ver_custos"]


def test_detalhe_da_edicao_nao_muda():
    r = _rev("Leitor", LEITOR, sorted(LEITOR | {"triar_artigos"}), TODAS)
    assert list(json.loads(A.detalhe_auditoria(r, ""))) == ["antes", "depois", "concedidas", "retiradas", "justificativa",
                                                             "origem"]
    assert A.detalhe_auditoria(r, "") == A.detalhe_auditoria(r, "", origem="edicao", escolhidas=None)


def _det(origem="edicao", escolhidas=None, justificativa=""):
    dados = {"antes": [], "depois": ["triar_artigos"], "concedidas": ["triar_artigos"], "retiradas": [],
             "justificativa": justificativa, "origem": origem}
    if escolhidas is not None:
        dados["escolhidas"] = escolhidas
    return json.dumps(dados, ensure_ascii=False)


@pytest.mark.parametrize("texto,esperado", [
    (_det(), "Concedidas: triar_artigos. Retiradas: nenhuma."),
    (_det(justificativa="j"), "Concedidas: triar_artigos. Retiradas: nenhuma. Justificativa: j"),
    (_det("referencia:estudante_direito", ["triar_artigos"]),
     "Concedidas: triar_artigos. Retiradas: nenhuma. Origem: comparação com a referência de Estudante de Direito."),
    (_det("referencia:publico", ["triar_artigos"], "j"),
     "Concedidas: triar_artigos. Retiradas: nenhuma. Origem: comparação com a referência de Público. Justificativa: j"),
    (_det("referencia:x", ["triar_artigos"]), "Concedidas: triar_artigos. Retiradas: nenhuma."),
    (_det("referencia:Publico", ["triar_artigos"]), "Concedidas: triar_artigos. Retiradas: nenhuma."),
    (_det("edicao", ["triar_artigos"]), "Concedidas: triar_artigos. Retiradas: nenhuma."),
    (_det("referencia:publico", []), "Concedidas: triar_artigos. Retiradas: nenhuma. Origem: comparação com a referência "
                                     "de Público."),
    (_det("referencia:publico", "triar_artigos"), None),
    (_det("referencia:publico", [1]), None),
    (_det("referencia:publico", None).replace('"origem"', '"escolhidas": null, "origem"'), None),
])
def test_resumo_com_origem(texto, esperado):
    assert A.resumo_detalhe_auditoria(texto) == esperado


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


def _aud(c):
    return [(l["acao"], l["alvo"], l["detalhe"]) for l in reversed(c.auditoria())]


def _gravar_ref(c, nome, perfil, escolhidas, marcadas=None, exibidas=None, confirmado=False, justificativa="",
                versao=None):
    m = A.montar_escolhas_da_referencia(nome, _p(c, nome), perfil, list(escolhidas))
    return c.definir_permissoes_do_grupo(
        _g(c, nome), m["marcadas"] if marcadas is None else list(marcadas),
        m["exibidas"] if exibidas is None else list(exibidas), _v(c, nome) if versao is None else versao,
        confirmado, justificativa, AGORA, referencia=(perfil, list(escolhidas)))


def test_grava_so_o_escolhido_e_audita_origem_e_escolhas(contas):
    r = _gravar_ref(contas, "Leitor", "estudante_direito", ["triar_artigos", "ver_custos"], justificativa="ok")
    assert r["concedidas"] == ["triar_artigos"] and r["retiradas"] == ["ver_custos"]
    assert _p(contas, "Leitor") == (LEITOR | {"triar_artigos"}) - {"ver_custos"}
    rev = _rev("Leitor", LEITOR, ["triar_artigos"], ["triar_artigos", "ver_custos"])
    assert _aud(contas) == [("salvar_permissoes", "Leitor",
                             A.detalhe_auditoria(rev, "ok", origem="referencia:estudante_direito",
                                                 escolhidas=["triar_artigos", "ver_custos"]))]


def test_edicao_sem_referencia_continua_igual(contas):
    contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), sorted(LEITOR | {"triar_artigos"}), TODAS, _v(contas, "Leitor"),
                                       False, "", AGORA)
    assert json.loads(_aud(contas)[0][2])["origem"] == "edicao" and "escolhidas" not in json.loads(_aud(contas)[0][2])


@pytest.mark.parametrize("marcadas,exibidas", [
    (["triar_artigos", "verificar_achados"], ["triar_artigos", "verificar_achados"]),      # concessao a mais
    ([], ["triar_artigos"]),                                                              # concessao a menos
    (["triar_artigos"], ["triar_artigos", "ver_nomes_revisores"]),                        # retirada a mais
    (sorted(LEITOR | {"triar_artigos"}), TODAS),                                          # o formulario da edicao
])
def test_listas_que_nao_batem_com_as_escolhas_sao_recusadas(contas, marcadas, exibidas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar_ref(contas, "Leitor", "estudante_direito", ["triar_artigos"], marcadas=marcadas, exibidas=exibidas)
    assert e.value.erros == [INCOMPLETO]
    assert _p(contas, "Leitor") == LEITOR and _aud(contas) == []


@pytest.mark.parametrize("referencia", ["publico", ("publico",), ("publico", ["ver_painel"], 1), ["publico", []],
                                        (1, ["triar_artigos"]), ("estudante_direito", "triar_artigos"), (None, None)])
def test_referencia_malformada_e_recusada(contas, referencia):
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), ["triar_artigos"], ["triar_artigos"],
                                           _v(contas, "Leitor"), False, "", AGORA, referencia=referencia)
    assert e.value.erros in ([INCOMPLETO], [ESCOLHA])
    assert _p(contas, "Leitor") == LEITOR and _aud(contas) == []


def test_escolha_que_deixou_de_ser_diferenca(contas):
    """A versao confere o estado; mesmo com a versao certa, a escolha e conferida contra o estado gravado."""
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), [], ["ver_painel"], _v(contas, "Leitor"), False, "", AGORA,
                                           referencia=("estudante_direito", ["ver_painel"]))
    assert e.value.erros == [_nao_dif("ver_painel")] and _aud(contas) == []


def test_versao_antiga_recusa_antes_das_escolhas(contas):
    v = _v(contas, "Leitor")
    contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), sorted(LEITOR | {"triar_artigos"}), TODAS, v, False, "", AGORA)
    with pytest.raises(A.PermissoesAlteradas):
        _gravar_ref(contas, "Leitor", "estudante_direito", ["verificar_achados"], marcadas=["verificar_achados"],
                    exibidas=["verificar_achados"], versao=v)
    assert len(_aud(contas)) == 1


def test_sensivel_escolhida_exige_confirmacao(contas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar_ref(contas, "Leitor", "professor_computacao", ["ver_chamadas"], justificativa="j")
    assert e.value.erros == [CONFIRMAR] and _aud(contas) == []
    _gravar_ref(contas, "Leitor", "professor_computacao", ["ver_chamadas"], confirmado=True, justificativa="j")
    assert "ver_chamadas" in _p(contas, "Leitor")


def test_visitante_so_com_o_publico_no_adaptador(contas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Visitante"), ["triar_artigos"], ["triar_artigos"],
                                           _v(contas, "Visitante"), True, "j", AGORA,
                                           referencia=("estudante_direito", ["triar_artigos"]))
    assert e.value.erros == [SO_PUBLICO] and _p(contas, "Visitante") == {"ver_painel"}


def test_adaptador_usa_a_montagem_do_dominio(contas, monkeypatch):
    def falsa(grupo, atuais, perfil, escolhidas):
        return {"exibidas": [], "marcadas": [], "escolhidas": [], "erros": ["Erro de teste."]}
    monkeypatch.setattr(A, "montar_escolhas_da_referencia", falsa)
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar_ref(contas, "Leitor", "estudante_direito", ["triar_artigos"], marcadas=["triar_artigos"],
                    exibidas=["triar_artigos"])
    assert e.value.erros == ["Erro de teste."]


# ======================== telas ========================

def _comparar(cli, gid, **params):
    r = cli.get(f"/admin/grupos/{gid}/comparar", params=params)
    assert r.status_code == 200
    return r.text


def _caixas(h):
    return re.findall(r'<input type="checkbox" id="e-([a-z_]+)" name="escolhida" value="\1"( checked)?>', h)


def test_regra_da_rota():
    assert A.regra_explicita("GET", "/admin/grupos/3/comparar") == ("GET", "/admin/grupos/{grupo_id}/comparar", A.SO_ADMIN)


def test_link_na_pagina_do_grupo(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}").text
    assert (f'<p><a class="botao" href="/admin/grupos/{gid}/editar">Editar permissões</a> '
            f'<a class="botao" href="/admin/grupos/{gid}/comparar">Comparar com uma referência</a></p>') in h
    aid = _gid(contas_db, "Administrador")
    assert f"/admin/grupos/{aid}/comparar" not in cli.get(f"/admin/grupos/{aid}").text


def test_primeira_abertura_sem_referencia_e_sem_caixas(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _comparar(cli, gid)
    assert "<h1>Comparar com uma referência: Leitor</h1>" in h
    form = h[h.index('<form class="perm-filtros" method="get">'):]
    form = form[:form.index("</form>")]
    assert '<label for="perm-perfil">Referência</label>' in form
    opcoes = re.findall(r'<option value="([a-z_]*)"( selected)?>([^<]+)</option>', form)
    assert opcoes == [("", " selected", "Nenhuma")] + [(p, "", A.ROTULOS_PERFIL_REFERENCIA[p]) for p in A.PERFIS_REFERENCIA]
    assert '<button class="botao" type="submit">Comparar</button>' in form
    assert _caixas(h) == [] and f'action="/admin/grupos/{gid}/revisar"' not in h
    assert ESCOLHA not in h and f'<p><a href="/admin/grupos/{gid}">Voltar ao grupo</a></p>' in h


def test_nenhuma_diferenca_vem_marcada(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _comparar(cli, gid, perfil="professor_computacao")
    comp = A.comparar_com_referencia("Leitor", LEITOR, "professor_computacao")
    assert _caixas(h) == [(i["permissao"], "") for i in comp["conceder"] + comp["retirar"]]
    assert " checked" not in h.split("<main", 1)[1]
    assert h.count(INTRO) == 1
    n_c, n_r = len(comp["conceder"]), len(comp["retirar"])
    assert f"<h2>A referência tem e o grupo não ({n_c})</h2>" in h
    assert n_r == 0 and "O grupo tem e a referência não" not in h


def test_lista_dos_dois_lados_com_sensibilidade(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _comparar(cli, gid, perfil="estudante_direito")
    assert "<h2>A referência tem e o grupo não (3)</h2>" in h and "<h2>O grupo tem e a referência não (2)</h2>" in h
    assert h.index("A referência tem e o grupo não") < h.index("O grupo tem e a referência não")
    assert [c for c, _ in _caixas(h)] == ["verificar_achados", "triar_artigos", "triar_texto_completo",
                                          "ver_nomes_revisores", "ver_custos"]
    assert (f'<li><input type="checkbox" id="e-ver_custos" name="escolhida" value="ver_custos"> <label for="e-ver_custos">'
            f'{_d("ver_custos")}</label> <span class="perm-sensivel">◆ financeira</span></li>') in h
    assert (f'<li><input type="checkbox" id="e-triar_artigos" name="escolhida" value="triar_artigos"> '
            f'<label for="e-triar_artigos">{_d("triar_artigos")}</label></li>') in h
    pares = _form(h, f"/admin/grupos/{gid}/revisar")
    assert [k for k, _ in pares] == ["csrf", "versao", "perfil"]
    assert dict(pares)["perfil"] == "estudante_direito"
    assert dict(pares)["versao"] == A.versao_permissoes({gid: LEITOR})
    assert '<button class="botao" type="submit">Revisar as escolhidas</button>' in h


def test_grupo_igual_a_referencia(adm):
    cli, _, contas_db, _ = adm
    h = _comparar(cli, _gid(contas_db, "Visitante"), perfil="publico")
    assert '<p class="vazio">Este grupo já está igual à referência de Público.</p>' in h
    assert _caixas(h) == [] and "/revisar" not in h


@pytest.mark.parametrize("perfil", ["x", " publico", "Publico", "<b>zzq9</b>", "zzq9"])
def test_perfil_invalido(adm, perfil):
    cli, _, contas_db, _ = adm
    h = _comparar(cli, _gid(contas_db, "Leitor"), perfil=perfil)
    assert h.count(f'<p class="aviso" role="status">{ESCOLHA}</p>') == 1
    assert _caixas(h) == [] and "zzq9" not in h


def test_visitante_so_o_publico(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Visitante")
    h = _comparar(cli, gid)
    assert re.findall(r'<option value="([a-z_]*)"', h.split('id="perm-perfil"', 1)[1].split("</select>")[0]) == ["", "publico"]
    h = _comparar(cli, gid, perfil="professor_direito")
    assert f'<p class="aviso" role="status">{ESCOLHA}</p>' in h and _caixas(h) == [] and SO_PUBLICO not in h


def test_administrador_nao_compara(adm):
    cli, _, contas_db, _ = adm
    h = _comparar(cli, _gid(contas_db, "Administrador"), perfil="publico")
    assert f"<p>{ADMIN}</p>" in h and _caixas(h) == [] and 'id="perm-perfil"' not in h


def test_nome_do_grupo_nunca_escolhe_a_referencia(adm):
    cli, contas, contas_db, _ = adm
    gid = contas.criar_grupo("Estudante de Direito", "2026-10-31T00:00:00+00:00")
    h = _comparar(cli, gid)
    assert _caixas(h) == [] and '<option value="" selected>Nenhuma</option>' in h


def test_so_o_administrador_abre(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    r = TestClient(cli.app).get(f"/admin/grupos/{gid}/comparar", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar")


@pytest.mark.parametrize("caminho,status", [("/admin/grupos/999/comparar", 404), ("/admin/grupos/x/comparar", 404)])
def test_grupo_inexistente(adm, caminho, status):
    cli, _, _, _ = adm
    assert cli.get(caminho).status_code == status


def test_comparacao_nao_grava(adm):
    cli, _, contas_db, _ = adm
    con = sqlite3.connect(contas_db)
    antes = (sorted(con.execute("SELECT * FROM grupo_permissoes").fetchall()),
             con.execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0])
    _comparar(cli, _gid(contas_db, "Leitor"), perfil="administrador")
    con = sqlite3.connect(contas_db)
    assert (sorted(con.execute("SELECT * FROM grupo_permissoes").fetchall()),
            con.execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0]) == antes


# ---------- revisao vinda da comparacao ----------

def _revisar_ref(cli, gid, perfil, escolhidas, extra=()):
    h = _comparar(cli, gid, perfil=perfil)
    pares = _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", p) for p in escolhidas] + list(extra)
    return _post(cli, f"/admin/grupos/{gid}/revisar", pares)


def test_revisao_so_com_o_marcado(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar_ref(cli, gid, "estudante_direito", ["triar_artigos"]).text
    assert "<h2>Serão concedidas (1)</h2>" in h and "Serão retiradas" not in h
    assert f"<li>{_d('triar_artigos')}</li>" in h and _d("verificar_achados") not in h.split("Serão concedidas")[1]
    assert "<p>Origem: comparação com a referência de Estudante de Direito. Só as diferenças marcadas estão abaixo.</p>" in h
    pares = _form(h, f"/admin/grupos/{gid}/permissoes")
    assert [k for k, _ in pares if k in ("marcada", "exibida")] == []          # o servidor recalcula a partir das escolhas
    assert [p for k, p in pares if k == "perfil"] == ["estudante_direito"]
    assert [p for k, p in pares if k == "escolhida"] == ["triar_artigos"]


def test_revisao_sem_nada_marcado(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar_ref(cli, gid, "estudante_direito", []).text
    assert _erros(h) == [NADA] and f'action="/admin/grupos/{gid}/permissoes"' not in h


@pytest.mark.parametrize("extra", [[("marcada", "triar_artigos")], [("exibida", "triar_artigos")],
                                   [("perfil", "publico")], [("marcada", "ver_painel"), ("exibida", "ver_painel")]])
def test_revisao_misturada_com_a_edicao_e_recusada(adm, extra):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar_ref(cli, gid, "estudante_direito", ["triar_artigos"], extra=extra).text
    assert _erros(h) == [INCOMPLETO] and f'action="/admin/grupos/{gid}/permissoes"' not in h


def test_revisao_com_escolha_que_nao_e_diferenca(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar_ref(cli, gid, "estudante_direito", ["ver_painel", "zzq9"]).text
    assert _erros(h) == ["O formulário trouxe 1 permissão desconhecida.", _nao_dif("ver_painel")]
    assert "zzq9" not in h


def _gravar_tela(cli, gid, perfil, escolhidas, confirmo=False, justificativa="", mexer=None):
    h = _revisar_ref(cli, gid, perfil, escolhidas).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{gid}/permissoes") if k != "confirmo"]
    if mexer:
        pares = mexer(pares)
    if confirmo:
        pares.append(("confirmo", "1"))
    pares.append(("justificativa", justificativa))
    return _post(cli, f"/admin/grupos/{gid}/permissoes", pares)


def test_grava_pela_tela_e_audita(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    r = _gravar_tela(cli, gid, "estudante_direito", ["triar_artigos", "ver_custos"])
    assert r.status_code == 303 and r.headers["location"] == f"/admin/grupos/{gid}?gravado=1"
    perms = {p for (p,) in sqlite3.connect(contas_db).execute("SELECT permissao FROM grupo_permissoes WHERE grupo_id=?",
                                                              (gid,))}
    assert perms == (LEITOR | {"triar_artigos"}) - {"ver_custos"}
    linha = sqlite3.connect(contas_db).execute(
        "SELECT acao, alvo, detalhe FROM auditoria_admin ORDER BY id DESC LIMIT 1").fetchone()
    assert linha[0] == "salvar_permissoes" and linha[1] == "Leitor"
    d = json.loads(linha[2])
    assert d["origem"] == "referencia:estudante_direito" and d["escolhidas"] == ["triar_artigos", "ver_custos"]


@pytest.mark.parametrize("mexer", [
    lambda ps: ps + [("escolhida", "ver_painel")],                                        # nao e diferenca
    lambda ps: [(k, v) for k, v in ps if k != "escolhida"],                               # sem as escolhas
    lambda ps: ps + [("marcada", "verificar_achados"), ("exibida", "verificar_achados")],  # concessao enfiada
    lambda ps: [(k, "publico" if k == "perfil" else v) for k, v in ps],                  # outro perfil
    lambda ps: ps + [("perfil", "estudante_direito")],                                    # perfil repetido
])
def test_formulario_adulterado_na_gravacao_nao_grava(adm, mexer):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    antes = sorted(sqlite3.connect(contas_db).execute("SELECT * FROM grupo_permissoes").fetchall())
    n = sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0]
    r = _gravar_tela(cli, gid, "estudante_direito", ["triar_artigos"], mexer=mexer)
    assert r.status_code == 400 and _erros(r.text)
    assert sorted(sqlite3.connect(contas_db).execute("SELECT * FROM grupo_permissoes").fetchall()) == antes
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0] == n


def test_versao_errada_na_gravacao(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    r = _gravar_tela(cli, gid, "estudante_direito", ["triar_artigos"],
                     mexer=lambda ps: [(k, "x" if k == "versao" else v) for k, v in ps])
    assert r.status_code == 409
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin WHERE acao='salvar_permissoes'").fetchone()[0] == 0


def test_sensivel_pela_tela_volta_a_revisao_com_as_escolhas(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    r = _gravar_tela(cli, gid, "professor_computacao", ["ver_chamadas"], justificativa="j")
    assert r.status_code == 400 and _erros(r.text) == [CONFIRMAR]
    pares = _form(r.text, f"/admin/grupos/{gid}/permissoes")
    assert [p for k, p in pares if k == "perfil"] == ["professor_computacao"]
    assert [p for k, p in pares if k == "escolhida"] == ["ver_chamadas"]
    assert "<p>Origem: comparação com a referência de Professor de Computação. Só as diferenças marcadas estão abaixo.</p>" \
        in r.text
    pares = [(k, v) for k, v in pares if k not in ("confirmo", "justificativa")] + [("confirmo", "1"), ("justificativa", "j")]
    assert _post(cli, f"/admin/grupos/{gid}/permissoes", pares).status_code == 303


def test_edicao_comum_nao_mostra_origem(adm):
    from test_edicao_por_grupo import _revisar
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar(cli, gid, sorted(LEITOR | {"triar_artigos"})).text
    assert "Origem: comparação" not in h
    pares = _form(h, f"/admin/grupos/{gid}/permissoes")
    assert not [k for k, _ in pares if k in ("perfil", "escolhida")]


def test_rotas_usam_um_so_leitor_do_formulario(adm, monkeypatch):
    """Revisao e gravacao leem o modo de referencia pelo mesmo ajudante do modulo."""
    from painel.rotas_extras import admin as R
    vistos = []
    original = R._revisao_do_formulario

    def espiao(*a, **k):
        vistos.append(1)
        return original(*a, **k)
    monkeypatch.setattr(R, "_revisao_do_formulario", espiao)
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    _gravar_tela(cli, gid, "professor_computacao", ["ver_chamadas"], justificativa="j")
    assert len(vistos) == 2


def test_perfil_repetido_na_comparacao(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{gid}/comparar?perfil=publico&perfil=estudante_direito").text
    assert h.count(f'<p class="aviso" role="status">{ESCOLHA}</p>') == 1 and _caixas(h) == []
    assert '<option value="" selected>Nenhuma</option>' in h


def test_escolhas_auditadas_na_ordem_do_catalogo(contas):
    _gravar_ref(contas, "Leitor", "estudante_direito", ["ver_custos", "triar_artigos"])
    assert json.loads(_aud(contas)[0][2])["escolhidas"] == ["triar_artigos", "ver_custos"]


@pytest.mark.parametrize("marcadas,exibidas", [(None, ["triar_artigos"]), (["triar_artigos"], None), (1, 1),
                                               (["triar_artigos", 1], ["triar_artigos"]), ("triar_artigos", "triar_artigos")])
def test_listas_de_tipo_errado_com_referencia(contas, marcadas, exibidas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(_g(contas, "Leitor"), marcadas, exibidas, _v(contas, "Leitor"), False, "", AGORA,
                                           referencia=("estudante_direito", ["triar_artigos"]))
    assert e.value.erros == [INCOMPLETO] and _aud(contas) == [] and _p(contas, "Leitor") == LEITOR


def test_pagina_de_comparacao_segue_o_dominio(adm, monkeypatch):
    cli, _, contas_db, _ = adm

    def falsa(grupo, atuais, perfil):
        if perfil == "publico":
            return {"perfil": perfil, "rotulo": "R", "erros": [], "retirar": [],
                    "conceder": [{"permissao": "enviar_coletas", "descricao": "Descrição falsa", "sensivel": False,
                                  "marcada": False}]}
        return {"perfil": None, "rotulo": None, "conceder": [], "retirar": [], "erros": ["Aviso falso."]}
    monkeypatch.setattr(A, "comparar_com_referencia", falsa)
    gid = _gid(contas_db, "Leitor")
    h = _comparar(cli, gid, perfil="publico")
    assert _caixas(h) == [("enviar_coletas", "")] and "Descrição falsa" in h
    assert '<p class="aviso" role="status">Aviso falso.</p>' in _comparar(cli, gid, perfil="x")


def test_revisao_segue_a_montagem_do_dominio(adm, monkeypatch):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _comparar(cli, gid, perfil="estudante_direito")
    pares = _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_artigos")]
    monkeypatch.setattr(A, "montar_escolhas_da_referencia",
                        lambda g, a, p, e: {"exibidas": [], "marcadas": [], "escolhidas": [], "erros": ["Erro falso."]})
    assert _erros(_post(cli, f"/admin/grupos/{gid}/revisar", pares).text) == ["Erro falso."]


def test_gravacao_recusada_conta_as_revisoes(adm, monkeypatch):
    """Na recusa, a pagina volta com a revisao do ajudante: uma revisao na rota e uma no adaptador, nenhuma a mais."""
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar_ref(cli, gid, "professor_computacao", ["ver_chamadas"]).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{gid}/permissoes") if k != "confirmo"] + [("justificativa", "j")]
    chamadas = []
    original = A.revisar_alteracao

    def contar(*a, **k):
        chamadas.append(1)
        return original(*a, **k)
    monkeypatch.setattr(A, "revisar_alteracao", contar)
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text) == [CONFIRMAR] and len(chamadas) == 2
    assert '<section class="perm-previa"' in r.text                  # a previa volta, do "depois" da revisao do ajudante


def test_comparacao_com_contas_ocupadas_ou_permissoes_invalidas(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    with sqlite3.connect(contas_db) as con:
        con.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, ?)", (gid, b"ver_painel"))
    r = cli.get(f"/admin/grupos/{gid}/comparar")
    assert r.status_code == 409 and "Permissões gravadas inválidas" in r.text
    with sqlite3.connect(contas_db) as con:
        con.execute("DELETE FROM grupo_permissoes WHERE typeof(permissao) = 'blob'")

    def ocupado(self):
        raise A.ContasOcupadas()
    monkeypatch.setattr(type(contas), "grupos", ocupado)
    assert cli.get(f"/admin/grupos/{gid}/comparar").status_code == 503


def _pares_ref(cli, gid, perfil, escolhidas):
    return [("csrf", _csrf(cli, "/admin/grupos")), ("versao", "x"), ("perfil", perfil)] + [("escolhida", p) for p in escolhidas]


def test_administrador_no_modo_referencia(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    aid = _gid(contas_db, "Administrador")
    assert _erros(_post(cli, f"/admin/grupos/{aid}/revisar", _pares_ref(cli, aid, "publico", ["ver_painel"])).text) == [ADMIN]
    chamadas = []
    monkeypatch.setattr(type(contas), "definir_permissoes_do_grupo", lambda *a, **k: chamadas.append(1))
    r = _post(cli, f"/admin/grupos/{aid}/permissoes", _pares_ref(cli, aid, "publico", ["ver_painel"]))
    assert r.status_code == 400 and _erros(r.text) == [ADMIN] and chamadas == []


def test_visitante_com_outra_referencia_no_post(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    vid = _gid(contas_db, "Visitante")
    pares = _pares_ref(cli, vid, "estudante_direito", ["triar_artigos"])
    assert _erros(_post(cli, f"/admin/grupos/{vid}/revisar", pares).text) == [SO_PUBLICO]
    chamadas = []
    monkeypatch.setattr(type(contas), "definir_permissoes_do_grupo", lambda *a, **k: chamadas.append(1))
    r = _post(cli, f"/admin/grupos/{vid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text) == [SO_PUBLICO] and chamadas == []


def test_escolha_invalida_vence_a_versao_errada(adm):
    """No modo de referencia, os erros das escolhas (400) vem antes da conferencia da versao no adaptador (409)."""
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", _pares_ref(cli, gid, "estudante_direito", ["ver_painel"]))
    assert r.status_code == 400 and _erros(r.text) == [_nao_dif("ver_painel")]


def test_voltar_a_comparacao(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _revisar_ref(cli, gid, "estudante_direito", ["triar_artigos"]).text
    assert f'<p><a href="/admin/grupos/{gid}/comparar?perfil=estudante_direito">Voltar à comparação</a></p>' in h
    assert "Voltar e editar" not in h
    h = _revisar_ref(cli, gid, "estudante_direito", ["triar_texto_completo"]).text   # escolha valida, dependencia faltando
    assert _erros(h) and f'<p><a href="/admin/grupos/{gid}/comparar?perfil=estudante_direito">Voltar à comparação</a></p>' in h
    assert "Voltar e editar" not in h
    h = _revisar_ref(cli, gid, "estudante_direito", []).text                      # erro: volta a edicao, como hoje
    assert f'<p><a href="/admin/grupos/{gid}/editar">Voltar e editar</a></p>' in h and "Voltar à comparação" not in h


def test_escolhida_sem_perfil_e_ignorada(adm):
    from test_edicao_por_grupo import _revisar
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    marcadas = sorted(LEITOR | {"triar_artigos"})
    sem = _revisar(cli, gid, marcadas).text
    com = _revisar(cli, gid, marcadas, extra=[("escolhida", "verificar_achados")]).text
    tira = lambda h: re.sub(r'name="csrf" value="[^"]*"', "", h)            # noqa: E731
    assert tira(com) == tira(sem)


def test_gravacao_com_dependencia_faltando_volta_a_comparacao(adm):
    """Escolha valida com dependencia faltando, enviada direto a gravacao: 400 sem gravar e o link de volta a comparacao."""
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _comparar(cli, gid, perfil="estudante_direito")
    pares = _form(h, f"/admin/grupos/{gid}/revisar") + [("escolhida", "triar_texto_completo"), ("justificativa", "")]
    n = sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0]
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text)
    assert f'<p><a href="/admin/grupos/{gid}/comparar?perfil=estudante_direito">Voltar à comparação</a></p>' in r.text
    assert "Voltar e editar" not in r.text
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0] == n
