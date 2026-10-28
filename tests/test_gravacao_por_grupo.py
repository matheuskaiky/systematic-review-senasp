"""Gravacao segura das permissoes de um grupo (sem tela): a revisao das diferencas, as pendencias que impedem gravar, o
registro de auditoria em JSON e a gravacao de um so grupo com a versao conferida dentro da transacao. Todos os bancos sao
temporarios; nenhum teste abre o data/ de verdade."""
import json
import sqlite3
from pathlib import Path

import pytest

from adaptadores import contas_sqlite
from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
TODAS = list(A.PERMISSOES)
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}
REVISOR = set(A.GRUPOS_PADRAO["Revisor"])
AGORA = ("chefe", "2026-10-28T12:00:00+00:00")


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


def _d(p):
    return A.PERMISSOES[p]


def _dep(p, d):
    return f"«{_d(p)}» precisa de «{_d(d)}»: marque as duas ou desmarque «{_d(p)}»."


ADMIN = "O grupo Administrador tem acesso integral e não pode ser alterado."
INCOMPLETO = "O formulário veio incompleto. Abra o grupo de novo e refaça as alterações."
CONFIRMAR = "Marque a confirmação das permissões sensíveis antes de gravar."
JUSTIFICAR = ("Escreva a justificativa: ela é obrigatória ao conceder permissões sensíveis ou retirar uma permissão de "
              "supervisão.")


def _fora(p):
    return f"«{_d(p)}» foi marcada, mas não fazia parte do formulário."


def _proibida(p):
    return f"«{_d(p)}» não pode ser dada a quem não entrou."


def _publica(p):
    return f"«{_d(p)}» não pode ser dada a quem não entrou enquanto não houver política de divulgação pública."


def _rev(grupo, atuais, marcadas, exibidas=None):
    return A.revisar_alteracao(grupo, set(atuais), list(marcadas), list(TODAS if exibidas is None else exibidas))


# ======================== revisao (funcao pura) ========================
CASOS = [
    # id, grupo, atuais, marcadas, exibidas (None = catalogo inteiro), concedidas, retiradas, sensiveis, exige, erros
    ("sem-alteracao", "Leitor", LEITOR, LEITOR, None, [], [], [], False, []),
    ("concessao-comum", "Leitor", LEITOR, LEITOR | {"triar_artigos"}, None, ["triar_artigos"], [], [], False, []),
    ("so-retirada", "Revisor", REVISOR, REVISOR - {"ver_chamadas"}, None, [], ["ver_chamadas"], [], False, []),
    ("concessao-sensivel", "Leitor", LEITOR, LEITOR | {"ver_chamadas"}, None, ["ver_chamadas"], [], ["ver_chamadas"], True, []),
    ("sensivel-e-retirada", "Leitor", LEITOR, (LEITOR | {"ver_chamadas"}) - {"ver_custos"}, None, ["ver_chamadas"],
     ["ver_custos"], ["ver_chamadas"], True, []),
    ("retira-supervisao", "Bolsistas", {"ver_painel", "verificar_achados", "revogar_verificacao"},
     {"ver_painel", "verificar_achados"}, None, [], ["revogar_verificacao"], [], True, []),
    ("retira-sensivel-nao-supervisao", "Leitor", LEITOR, LEITOR - {"ver_nomes_revisores"}, None, [], ["ver_nomes_revisores"],
     [], False, []),
    ("dependencia-ao-conceder", "Leitor", LEITOR, LEITOR | {"triar_texto_completo"}, None, ["triar_texto_completo"], [], [],
     False, [_dep("triar_texto_completo", "triar_artigos")]),
    ("dependencia-ao-retirar", "Leitor", LEITOR, LEITOR - {"ver_painel"}, None, [], ["ver_painel"], [], False,
     [_dep("ver_nomes_revisores", "ver_painel"), _dep("ver_registros_revisao", "ver_painel"), _dep("ver_custos", "ver_painel")]),
    ("inconsistencia-preexistente", "Bolsistas", {"ver_painel", "revogar_verificacao"},
     {"ver_painel", "revogar_verificacao", "triar_artigos"}, None, ["triar_artigos"], [], [], False,
     [_dep("revogar_verificacao", "verificar_achados")]),
    ("subconjunto-exibido", "Revisor", REVISOR, {"ver_painel"}, ["ver_painel", "ver_chamadas"], [], ["ver_chamadas"], [], False,
     []),
    ("visitante-proibida", "Visitante", {"ver_painel"}, {"ver_painel", "verificar_achados"}, None, ["verificar_achados"], [], [],
     False, [_proibida("verificar_achados")]),
    ("visitante-chamadas", "Visitante", {"ver_painel"}, {"ver_painel", "ver_chamadas"}, None, ["ver_chamadas"], [],
     ["ver_chamadas"], True, [_publica("ver_chamadas")]),
    ("visitante-nomes", "Visitante", {"ver_painel"}, {"ver_painel", "ver_nomes_revisores"}, None, ["ver_nomes_revisores"], [],
     ["ver_nomes_revisores"], True, [_publica("ver_nomes_revisores")]),
    ("visitante-mantem-publico-ja-autorizado", "Visitante", {"ver_painel", "ver_chamadas"}, {"ver_painel", "ver_chamadas"}, None,
     [], [], [], False, []),
    ("visitante-retira-publico", "Visitante", {"ver_painel", "ver_chamadas"}, {"ver_painel"}, None, [], ["ver_chamadas"], [],
     False, []),
]


@pytest.mark.parametrize("caso", CASOS, ids=[c[0] for c in CASOS])
def test_revisao(caso):
    _, grupo, atuais, marcadas, exibidas, conc, ret, sens, exige, erros = caso
    r = _rev(grupo, atuais, marcadas, exibidas)
    assert (r["concedidas"], r["retiradas"], r["sensiveis"], r["exige_justificativa"], r["erros"]) == (conc, ret, sens, exige, erros)
    depois = (set(atuais) - set(conc) - set(ret)) | set(conc)
    assert r["antes"] == sorted(atuais) and r["depois"] == sorted(depois)


def test_listas_na_ordem_do_catalogo():
    """Concedidas, retiradas e sensiveis seguem a ordem de PERMISSOES, nao a ordem do formulario nem a alfabetica."""
    marcadas = ["ver_custos", "triar_artigos", "ver_chamadas", "ver_painel"]
    r = _rev("Bolsistas", {"ver_nomes_revisores", "ver_estatisticas_usuarios"}, marcadas)
    assert r["concedidas"] == ["ver_painel", "ver_chamadas", "triar_artigos", "ver_custos"]
    assert r["retiradas"] == ["ver_nomes_revisores", "ver_estatisticas_usuarios"]
    assert r["sensiveis"] == ["ver_chamadas", "ver_custos"]


def test_nenhuma_dependencia_concedida_automaticamente():
    r = _rev("Leitor", LEITOR, LEITOR | {"revogar_verificacao"})
    assert "verificar_achados" not in r["depois"] and r["erros"] == [_dep("revogar_verificacao", "verificar_achados")]


def test_permissao_gravada_fora_do_catalogo_fica_intacta():
    r = _rev("Leitor", LEITOR | {"permissao_antiga"}, LEITOR - {"ver_custos"})
    assert "permissao_antiga" in r["antes"] and "permissao_antiga" in r["depois"]
    assert r["retiradas"] == ["ver_custos"] and r["erros"] == []


@pytest.mark.parametrize("extra,mensagem", [
    (["x_desconhecida"], "O formulário trouxe 1 permissão desconhecida."),
    (["x_um", "x_dois"], "O formulário trouxe 2 permissões desconhecidas."),
    (["x_um", "x_um"], "O formulário trouxe 1 permissão desconhecida."),
    ([" ver_painel"], "O formulário trouxe 1 permissão desconhecida."),
    (["VER_PAINEL"], "O formulário trouxe 1 permissão desconhecida."),
])
def test_chaves_desconhecidas_contadas_sem_ecoar(extra, mensagem):
    r = A.revisar_alteracao("Leitor", set(LEITOR), list(LEITOR) + extra, TODAS + extra)
    assert r["erros"] == [mensagem] and r["concedidas"] == [] and r["retiradas"] == []


def test_desconhecida_so_na_lista_exibida_tambem_conta():
    r = A.revisar_alteracao("Leitor", set(LEITOR), list(LEITOR), TODAS + ["x_um"])
    assert r["erros"] == ["O formulário trouxe 1 permissão desconhecida."]


def test_marcada_fora_da_lista_exibida():
    r = _rev("Leitor", LEITOR, ["ver_painel", "ver_chamadas"], ["ver_painel"])
    assert r["erros"] == [_fora("ver_chamadas")] and r["concedidas"] == []      # nao entra no estado final


CHAVES = {"antes", "depois", "concedidas", "retiradas", "sensiveis", "exige_justificativa", "erros"}


def _estrutural(r, atuais, erro):
    assert set(r) == CHAVES
    assert r == {"antes": sorted(atuais), "depois": sorted(atuais), "concedidas": [], "retiradas": [], "sensiveis": [],
                 "exige_justificativa": False, "erros": [erro]}


@pytest.mark.parametrize("marcadas,exibidas", [
    (["x_um", "ver_chamadas"], []), (["x_um", "ver_chamadas"], ["x_um"]), (["ver_chamadas"], ["", " "]),
    (["ver_chamadas"], ["ver_painel", None]), ([1], TODAS), ([["ver_chamadas"]], TODAS), (["ver_chamadas"], TODAS + [b"ver_painel"]),
    (None, TODAS), (["ver_chamadas"], None), ("ver_chamadas", TODAS), (["ver_chamadas"], {"ver_chamadas": 1}),
    ([True], TODAS), (["ver_chamadas"], TODAS + [1.5]), (["ver_chamadas"], set(TODAS)),
], ids=["vazia", "so-desconhecidas", "so-brancos", "none-na-lista", "inteiro", "lista-dentro", "bytes", "marcadas-none",
        "exibidas-none", "marcadas-texto", "exibidas-dict", "bool", "float", "exibidas-conjunto"])
def test_formulario_incompleto_ou_malformado_e_estrutural(marcadas, exibidas):
    """Lista exibida sem nenhuma chave do catalogo, ou qualquer item que nao seja texto, ou listas que nao sejam lista ou
    tupla: recusa estrutural, sem diferencas."""
    _estrutural(A.revisar_alteracao("Leitor", set(LEITOR), marcadas, exibidas), LEITOR, INCOMPLETO)


def test_tuplas_valem_como_listas():
    r = A.revisar_alteracao("Leitor", set(LEITOR), tuple(LEITOR | {"triar_artigos"}), tuple(TODAS))
    assert r["concedidas"] == ["triar_artigos"] and r["erros"] == []


@pytest.mark.parametrize("marcadas,exibidas", [(["x_um"], []), ([], TODAS), ([None], None)])
def test_administrador_nunca_e_alterado(marcadas, exibidas):
    """A recusa do Administrador vem antes de qualquer outra, mesmo com o formulario incompleto ou malformado."""
    _estrutural(A.revisar_alteracao("Administrador", set(TODAS), marcadas, exibidas), TODAS, ADMIN)


def test_resultado_tem_exatamente_as_chaves():
    assert set(_rev("Leitor", LEITOR, LEITOR | {"triar_artigos"})) == CHAVES


def test_repeticoes_no_formulario_nao_mudam_nada():
    a = _rev("Leitor", LEITOR, list(LEITOR) + ["triar_artigos", "triar_artigos"], TODAS + TODAS)
    b = _rev("Leitor", LEITOR, list(LEITOR) + ["triar_artigos"])
    assert a == b


def test_ordem_dos_erros_combinados():
    """Desconhecidas, marcadas fora da lista, recusas de quem nao entrou e dependencias, nesta ordem."""
    exibidas = [p for p in TODAS if p != "ver_custos"] + ["zzz"]
    marcadas = ["zzz", "ver_custos", "ver_chamadas", "ver_nomes_revisores"]           # ver_painel desmarcada
    r = A.revisar_alteracao("Visitante", {"ver_painel", "ver_chamadas"}, marcadas, exibidas)
    assert r["erros"] == ["O formulário trouxe 1 permissão desconhecida.", _fora("ver_custos"), _publica("ver_nomes_revisores"),
                          _dep("ver_nomes_revisores", "ver_painel"), _dep("ver_chamadas", "ver_painel")]


def test_recusas_de_quem_nao_entrou_na_ordem_do_catalogo():
    """Proibidas e sensiveis se intercalam pela ordem do catalogo, depois das desconhecidas e antes das dependencias."""
    marcadas = ["ver_painel", "triar_texto_completo", "verificar_achados", "ver_chamadas", "ver_nomes_revisores", "x_um"]
    r = A.revisar_alteracao("Visitante", {"ver_painel"}, marcadas, TODAS + ["x_um"])
    assert r["erros"] == ["O formulário trouxe 1 permissão desconhecida.", _publica("ver_nomes_revisores"), _publica("ver_chamadas"),
                          _proibida("verificar_achados"), _proibida("triar_texto_completo"),
                          _dep("triar_texto_completo", "triar_artigos")]


def test_marcada_fora_vem_antes_da_proibida():
    exibidas = [p for p in TODAS if p != "ver_custos"]
    r = A.revisar_alteracao("Visitante", {"ver_painel"}, ["ver_painel", "ver_custos", "verificar_achados"], exibidas)
    assert r["erros"] == [_fora("ver_custos"), _proibida("verificar_achados")]


def test_sensibilidade_e_dependencias_vem_do_catalogo(monkeypatch):
    """Mudar o catalogo muda a revisao: nada fica copiado em outro lugar."""
    cat = A.CATALOGO_PERMISSOES
    monkeypatch.setitem(cat, "ver_chamadas", {**cat["ver_chamadas"], "sensibilidade": None})
    r = _rev("Leitor", LEITOR, LEITOR | {"ver_chamadas"})
    assert (r["sensiveis"], r["exige_justificativa"]) == ([], False)
    monkeypatch.setitem(cat, "ver_custos", {**cat["ver_custos"], "sensibilidade": "supervisao"})
    assert _rev("Leitor", LEITOR, LEITOR - {"ver_custos"})["exige_justificativa"] is True
    monkeypatch.setitem(cat, "triar_artigos", {**cat["triar_artigos"], "depende_de": ("ver_chamadas",)})
    r = _rev("Leitor", LEITOR, LEITOR | {"triar_artigos"})
    assert r["erros"] == [_dep("triar_artigos", "ver_chamadas")]


def test_rotulo_da_sensibilidade_vem_do_catalogo(monkeypatch):
    monkeypatch.setitem(A.ROTULOS_SENSIBILIDADE, "escrita", "escrita")
    assert _rev("Leitor", LEITOR, LEITOR | {"triar_artigos"})["sensiveis"] == ["triar_artigos"]


# ======================== pendencias da gravacao ========================
def _sens():
    return _rev("Leitor", LEITOR, LEITOR | {"ver_chamadas"})


def _comum():
    return _rev("Leitor", LEITOR, LEITOR | {"triar_artigos"})


def _superv():
    return _rev("Bolsistas", {"ver_painel", "verificar_achados", "revogar_verificacao"}, {"ver_painel", "verificar_achados"})


SENS, COMUM, SUPERV = "sens", "comum", "superv"
REVISOES = {SENS: _sens, COMUM: _comum, SUPERV: _superv}


@pytest.mark.parametrize("revisao,confirmado,justificativa,esperado", [
    (SENS, False, "", [CONFIRMAR, JUSTIFICAR]),
    (SENS, True, "  \n\t", [JUSTIFICAR]),
    (SENS, True, "Pedido da coordenação", []),
    (SENS, False, "Pedido da coordenação", [CONFIRMAR]),
    (COMUM, False, "", []),
    (COMUM, False, "x" * 500, []),
    (COMUM, False, "x" * 501, ["A justificativa tem 501 caracteres; o máximo é 500."]),
    (COMUM, False, "ç" * 501, ["A justificativa tem 501 caracteres; o máximo é 500."]),
    (SUPERV, False, "", [JUSTIFICAR]),
    (SUPERV, False, " " * 600, [JUSTIFICAR, "A justificativa tem 600 caracteres; o máximo é 500."]),
], ids=["sens-nada", "sens-espacos", "sens-ok", "sens-sem-caixa", "comum", "comum-500", "comum-501", "comum-501-acentos",
        "supervisao-sem", "supervisao-espacos-longos"])
def test_pendencias(revisao, confirmado, justificativa, esperado):
    assert A.pendencias_da_gravacao(REVISOES[revisao](), confirmado, justificativa) == esperado


def test_limite_da_justificativa_e_a_constante():
    assert A.JUSTIFICATIVA_MAX == 500


# ======================== detalhe da auditoria ========================
def test_detalhe_exato():
    texto = A.detalhe_auditoria(_comum(), "Bolsista de iniciação")
    assert texto == ('{"antes": ["ver_custos", "ver_nomes_revisores", "ver_painel", "ver_registros_revisao"], '
                     '"depois": ["triar_artigos", "ver_custos", "ver_nomes_revisores", "ver_painel", "ver_registros_revisao"], '
                     '"concedidas": ["triar_artigos"], "retiradas": [], "justificativa": "Bolsista de iniciação", '
                     '"origem": "edicao"}')


@pytest.mark.parametrize("justificativa,gravada", [
    ("", ""), ("   ", ""), ("  com espaços  ", "  com espaços  "), ('aspas " e \\ barra', 'aspas " e \\ barra'),
    ("linha 1\nlinha 2", "linha 1\nlinha 2"), ("controle \x01 aqui", "controle \x01 aqui"), ("<b>&</b>", "<b>&</b>"),
])
def test_detalhe_volta_igual_pelo_json(justificativa, gravada):
    d = json.loads(A.detalhe_auditoria(_sens(), justificativa))
    assert list(d) == ["antes", "depois", "concedidas", "retiradas", "justificativa", "origem"]
    assert d["justificativa"] == gravada and d["origem"] == "edicao" and d["concedidas"] == ["ver_chamadas"]


def test_detalhe_grava_a_origem_informada():
    assert json.loads(A.detalhe_auditoria(_comum(), "", origem="referencia:Leitor"))["origem"] == "referencia:Leitor"
    assert json.loads(A.detalhe_auditoria(_comum(), ""))["origem"] == "edicao"


def test_detalhe_com_listas_ordenadas_alfabeticamente():
    r = _rev("Bolsistas", {"ver_nomes_revisores", "ver_estatisticas_usuarios"}, ["ver_custos", "ver_painel", "triar_artigos"])
    d = json.loads(A.detalhe_auditoria(r, ""))
    assert d["concedidas"] == ["triar_artigos", "ver_custos", "ver_painel"]
    assert d["retiradas"] == ["ver_estatisticas_usuarios", "ver_nomes_revisores"]


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


def _gid(c, nome):
    return next(g["grupo_id"] for g in c.grupos() if g["nome"] == nome)


def _perms(c, nome):
    return set(next(g["permissoes"] for g in c.grupos() if g["nome"] == nome))


def _auditoria(c):
    return [(l["acao"], l["alvo"], l["detalhe"]) for l in reversed(c.auditoria())]


def _versao(c, nome):
    return A.versao_permissoes({_gid(c, nome): _perms(c, nome)})


def _gravar(c, nome, marcadas, exibidas=None, versao=None, confirmado=False, justificativa=""):
    return c.definir_permissoes_do_grupo(_gid(c, nome), list(marcadas), list(TODAS if exibidas is None else exibidas),
                                         _versao(c, nome) if versao is None else versao, confirmado, justificativa, AGORA)


def test_grava_e_audita_uma_vez(contas):
    r = _gravar(contas, "Leitor", LEITOR | {"triar_artigos"}, justificativa="Bolsista de iniciação")
    assert r["concedidas"] == ["triar_artigos"] and _perms(contas, "Leitor") == LEITOR | {"triar_artigos"}
    assert _auditoria(contas) == [("salvar_permissoes", "Leitor", A.detalhe_auditoria(_comum(), "Bolsista de iniciação"))]
    assert contas.auditoria()[0]["admin_login"] == "chefe" and contas.auditoria()[0]["quando"] == AGORA[1]


def test_versao_errada_recusa_sem_gravar(contas):
    with pytest.raises(A.PermissoesAlteradas):
        _gravar(contas, "Leitor", LEITOR | {"triar_artigos"}, versao="0" * 64)
    assert _perms(contas, "Leitor") == LEITOR and _auditoria(contas) == []


@pytest.mark.parametrize("versao", ["", None])
def test_versao_ausente_recusa(contas, versao):
    with pytest.raises(A.PermissoesAlteradas):
        contas.definir_permissoes_do_grupo(_gid(contas, "Leitor"), list(LEITOR), TODAS, versao, False, "", AGORA)
    assert _auditoria(contas) == []


def test_reenvio_da_mesma_pagina_e_recusado(contas):
    v = _versao(contas, "Leitor")
    _gravar(contas, "Leitor", LEITOR | {"triar_artigos"}, versao=v)
    with pytest.raises(A.PermissoesAlteradas):
        _gravar(contas, "Leitor", LEITOR | {"triar_artigos"}, versao=v)
    assert len(_auditoria(contas)) == 1


def test_versao_e_so_do_grupo(contas):
    """Mudar outro grupo nao invalida a pagina aberta deste."""
    v = _versao(contas, "Leitor")
    _gravar(contas, "Revisor", REVISOR - {"ver_chamadas"})
    _gravar(contas, "Leitor", LEITOR | {"triar_artigos"}, versao=v)
    assert _perms(contas, "Leitor") == LEITOR | {"triar_artigos"}


def test_sem_alteracao_nada_gravado(contas):
    r = _gravar(contas, "Leitor", LEITOR)
    assert (r["concedidas"], r["retiradas"]) == ([], []) and _auditoria(contas) == []


def test_repetir_depois_de_gravar_e_idempotente(contas):
    _gravar(contas, "Leitor", LEITOR | {"triar_artigos"})
    r = _gravar(contas, "Leitor", LEITOR | {"triar_artigos"})
    assert (r["concedidas"], r["retiradas"]) == ([], []) and len(_auditoria(contas)) == 1


def test_erros_da_revisao_recusam_sem_gravar(contas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar(contas, "Leitor", LEITOR | {"triar_texto_completo"})
    assert e.value.erros == [_dep("triar_texto_completo", "triar_artigos")]
    assert _perms(contas, "Leitor") == LEITOR and _auditoria(contas) == []
    _gravar(contas, "Leitor", LEITOR | {"triar_artigos"})                       # nenhuma transacao ficou aberta
    assert _perms(contas, "Leitor") == LEITOR | {"triar_artigos"}


def test_pendencias_recusam_sem_gravar(contas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar(contas, "Leitor", LEITOR | {"ver_chamadas"})
    assert e.value.erros == [CONFIRMAR, JUSTIFICAR] and _perms(contas, "Leitor") == LEITOR and _auditoria(contas) == []
    _gravar(contas, "Leitor", LEITOR | {"ver_chamadas"}, confirmado=True, justificativa="Apoio técnico")
    assert _perms(contas, "Leitor") == LEITOR | {"ver_chamadas"}
    assert json.loads(_auditoria(contas)[0][2])["justificativa"] == "Apoio técnico"


def test_erros_da_revisao_vem_antes_das_pendencias(contas):
    """Com erro de revisao, a recusa traz so os erros da revisao (as pendencias sao conferidas depois)."""
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar(contas, "Leitor", LEITOR | {"ver_chamadas", "triar_texto_completo"})
    assert e.value.erros == [_dep("triar_texto_completo", "triar_artigos")]


def test_visitante_nao_recebe_chamadas_nem_nomes(contas):
    for p in ("ver_chamadas", "ver_nomes_revisores"):
        with pytest.raises(A.AlteracaoRecusada) as e:
            _gravar(contas, "Visitante", {"ver_painel", p}, confirmado=True, justificativa="teste")
        assert e.value.erros == [_publica(p)]
    assert _perms(contas, "Visitante") == {"ver_painel"} and _auditoria(contas) == []


def test_administrador_recusado_e_intacto(contas):
    antes = _perms(contas, "Administrador")
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar(contas, "Administrador", set())
    assert e.value.erros == [ADMIN] and _perms(contas, "Administrador") == antes and _auditoria(contas) == []


@pytest.mark.parametrize("versao", ["certa", "velha"])
def test_grupo_inexistente_antes_da_versao(contas, versao):
    v = A.versao_permissoes({99999: set()}) if versao == "certa" else "0" * 64
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(99999, ["ver_painel"], TODAS, v, False, "", AGORA)
    assert e.value.erros == ["Este grupo não existe mais."] and _auditoria(contas) == []


@pytest.mark.parametrize("gid", [0, -1, 2 ** 63, 2 ** 70, -(2 ** 63) - 1, True, "1", None, 1.0],
                         ids=["zero", "negativo", "2^63", "2^70", "menor-que-int64", "bool", "texto", "none", "float"])
def test_id_fora_do_intervalo_ou_de_outro_tipo(contas, gid):
    """Id inteiro de 1 a 9223372036854775807 (bool nao vale): fora disso, a mesma recusa, sem consultar nem gravar."""
    antes = {g["nome"]: set(g["permissoes"]) for g in contas.grupos()}
    abertas = []
    original = type(contas)._conexao

    def espiar(self, *a, **k):
        abertas.append(a)
        return original(self, *a, **k)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(type(contas), "_conexao", espiar)
        with pytest.raises(A.AlteracaoRecusada) as e:
            contas.definir_permissoes_do_grupo(gid, ["ver_painel"], TODAS, "0" * 64, False, "", AGORA)
    assert e.value.erros == ["Este grupo não existe mais."] and abertas == []          # nenhuma conexao aberta
    assert {g["nome"]: set(g["permissoes"]) for g in contas.grupos()} == antes and _auditoria(contas) == []


def test_id_no_limite_de_64_bits_e_so_inexistente(contas):
    with pytest.raises(A.AlteracaoRecusada) as e:
        contas.definir_permissoes_do_grupo(2 ** 63 - 1, ["ver_painel"], TODAS, "0" * 64, False, "", AGORA)
    assert e.value.erros == ["Este grupo não existe mais."]


def test_alvo_da_auditoria_e_o_nome_atual(contas):
    g = contas.criar_grupo("Bolsistas", AGORA[1])
    contas.renomear_grupo(g, "Bolsistas de IC")
    contas.definir_permissoes_do_grupo(g, ["ver_painel"], TODAS, A.versao_permissoes({g: set()}), False, "", AGORA)
    assert _auditoria(contas)[-1][:2] == ("salvar_permissoes", "Bolsistas de IC")


def test_usa_as_funcoes_do_dominio(contas, monkeypatch):
    """A gravacao chama a revisao, as pendencias e o detalhe do dominio (uma regra so)."""
    comum = _comum()
    monkeypatch.setattr(A, "revisar_alteracao", lambda *a, **k: {**comum, "erros": ["revisão trocada"]})
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar(contas, "Leitor", LEITOR)
    assert e.value.erros == ["revisão trocada"]
    monkeypatch.setattr(A, "revisar_alteracao", lambda *a, **k: comum)
    monkeypatch.setattr(A, "pendencias_da_gravacao", lambda *a, **k: ["pendência trocada"])
    with pytest.raises(A.AlteracaoRecusada) as e:
        _gravar(contas, "Leitor", LEITOR)
    assert e.value.erros == ["pendência trocada"]
    monkeypatch.setattr(A, "pendencias_da_gravacao", lambda *a, **k: [])
    monkeypatch.setattr(A, "detalhe_auditoria", lambda *a, **k: "detalhe trocado")
    _gravar(contas, "Leitor", LEITOR)
    assert _auditoria(contas) == [("salvar_permissoes", "Leitor", "detalhe trocado")]
    assert _perms(contas, "Leitor") == LEITOR | {"triar_artigos"}            # grava o "depois" da revisao


def test_falha_no_meio_desfaz_tudo(contas, monkeypatch):
    def falha(*a, **k):
        raise RuntimeError("falha simulada")
    original = type(contas)._gravar_auditoria
    monkeypatch.setattr(type(contas), "_gravar_auditoria", falha)
    with pytest.raises(RuntimeError, match="falha simulada"):
        _gravar(contas, "Leitor", LEITOR | {"triar_artigos"})
    monkeypatch.setattr(type(contas), "_gravar_auditoria", original)
    assert _perms(contas, "Leitor") == LEITOR and _auditoria(contas) == []


def test_permissao_antiga_gravada_entra_na_versao_e_fica(tmp_path):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    l = _gid(c, "Leitor")
    with sqlite3.connect(tmp_path / "contas.db") as conn:
        conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, 'permissao_antiga')", (l,))
    with pytest.raises(A.PermissoesAlteradas):
        c.definir_permissoes_do_grupo(l, list(LEITOR), TODAS, A.versao_permissoes({l: LEITOR}), False, "", AGORA)
    c.definir_permissoes_do_grupo(l, list(LEITOR - {"ver_custos"}), TODAS, A.versao_permissoes({l: LEITOR | {"permissao_antiga"}}),
                                  False, "", AGORA)
    assert _perms(c, "Leitor") == (LEITOR - {"ver_custos"}) | {"permissao_antiga"}


@pytest.mark.parametrize("valor", [b"ver_painel", b""], ids=["blob", "blob-vazio"])
def test_permissao_gravada_de_outro_tipo_recusa(tmp_path, valor):
    """A coluna e TEXT sem STRICT: numeros viram texto (chave desconhecida, fica intacta), mas um BLOB continua bytes e
    recusa a edicao inteira, antes da versao."""
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    l = _gid(c, "Leitor")
    with sqlite3.connect(tmp_path / "contas.db") as conn:
        conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, ?)", (l, valor))
    for versao in ("0" * 64, A.versao_permissoes({l: LEITOR})):
        with pytest.raises(A.AlteracaoRecusada) as e:
            c.definir_permissoes_do_grupo(l, list(LEITOR | {"triar_artigos"}), TODAS, versao, False, "", AGORA)
        assert e.value.erros == ["As permissões gravadas deste grupo têm um valor inválido. Nada foi alterado."]
    assert _auditoria(c) == []
    with sqlite3.connect(tmp_path / "contas.db") as conn:
        guardadas = sorted(conn.execute("SELECT permissao FROM grupo_permissoes WHERE grupo_id = ?", (l,)).fetchall(), key=repr)
    assert guardadas == sorted([(p,) for p in LEITOR] + [(valor,)], key=repr)


def test_caminho_de_sucesso_numa_conexao_so(tmp_path, monkeypatch):
    """Na gravacao bem-sucedida, tudo (leituras, escrita e auditoria) acontece numa conexao, entre BEGIN IMMEDIATE e COMMIT."""
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    l = _gid(c, "Leitor")
    v = _versao(c, "Leitor")
    conexoes, comandos = [], []
    original = contas_sqlite.sqlite3.connect

    def conectar(*a, **k):
        x = original(*a, **k)
        conexoes.append(x)
        x.set_trace_callback(lambda sql: comandos.append(" ".join(sql.split())))
        return x
    monkeypatch.setattr(contas_sqlite.sqlite3, "connect", conectar)
    c.definir_permissoes_do_grupo(l, list(LEITOR | {"triar_artigos"}), TODAS, v, False, "", AGORA)
    assert len(conexoes) == 1
    i_begin, i_fim = comandos.index("BEGIN IMMEDIATE"), comandos.index("COMMIT")
    uteis = [i for i, x in enumerate(comandos) if x.upper().startswith(("SELECT", "INSERT", "DELETE", "UPDATE"))
             and any(t in x for t in ("grupos", "grupo_permissoes", "auditoria_admin"))]
    assert uteis and i_begin < min(uteis) and max(uteis) < i_fim
    i_perm = max(i for i, x in enumerate(comandos) if x.startswith("INSERT INTO grupo_permissoes"))
    i_aud = min(i for i, x in enumerate(comandos) if x.startswith("INSERT INTO auditoria_admin"))
    assert i_perm < i_aud                                                 # a diferenca e gravada antes da auditoria


def test_reusa_aplicar_permissoes_e_versao(contas, monkeypatch):
    chamadas = []
    original = type(contas)._aplicar_permissoes

    def espiao(self, conn, gid, novas, atuais):
        chamadas.append((gid, set(novas), set(atuais)))
        return original(self, conn, gid, novas, atuais)
    monkeypatch.setattr(type(contas), "_aplicar_permissoes", espiao)
    l = _gid(contas, "Leitor")
    _gravar(contas, "Leitor", LEITOR | {"triar_artigos"})
    assert chamadas == [(l, LEITOR | {"triar_artigos"}, LEITOR)]
    monkeypatch.setattr(A, "versao_permissoes", lambda estado: "versao-trocada")
    contas.definir_permissoes_do_grupo(l, list(LEITOR), TODAS, "versao-trocada", False, "", AGORA)
    assert _perms(contas, "Leitor") == LEITOR


def test_versao_conferida_depois_do_begin_immediate_na_mesma_conexao(tmp_path, monkeypatch):
    """Ler, conferir e gravar acontecem numa conexao so, depois do BEGIN IMMEDIATE; a recusa termina em ROLLBACK sem escrita."""
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    l = _gid(c, "Leitor")
    conexoes, comandos = [], []
    original = contas_sqlite.sqlite3.connect

    def conectar(*a, **k):
        x = original(*a, **k)
        conexoes.append(x)
        x.set_trace_callback(lambda sql: comandos.append(" ".join(sql.split())))
        return x
    monkeypatch.setattr(contas_sqlite.sqlite3, "connect", conectar)
    with pytest.raises(A.PermissoesAlteradas):
        c.definir_permissoes_do_grupo(l, list(LEITOR), TODAS, "0" * 64, False, "", AGORA)
    assert len(conexoes) == 1
    i_begin = comandos.index("BEGIN IMMEDIATE")
    leituras = [i for i, x in enumerate(comandos) if x.upper().startswith("SELECT") and ("grupos" in x or "grupo_permissoes" in x)]
    assert leituras and min(leituras) > i_begin
    assert not any(x.upper().startswith(("INSERT", "DELETE", "UPDATE")) for x in comandos)
    assert comandos[-1] == "ROLLBACK"


def test_le_so_o_grupo_alterado(tmp_path, monkeypatch):
    """A gravacao filtra pelo id do grupo (nunca le a matriz inteira)."""
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    l = _gid(c, "Leitor")
    v = _versao(c, "Leitor")
    comandos = []
    original = contas_sqlite.sqlite3.connect

    def conectar(*a, **k):
        x = original(*a, **k)
        x.set_trace_callback(lambda sql: comandos.append(" ".join(sql.split())))
        return x
    monkeypatch.setattr(contas_sqlite.sqlite3, "connect", conectar)
    c.definir_permissoes_do_grupo(l, list(LEITOR | {"triar_artigos"}), TODAS, v, False, "", AGORA)
    leituras = [x for x in comandos if x.upper().startswith("SELECT") and "grupo_permissoes" in x]
    assert leituras and all("WHERE" in x.upper() and "GRUPO_ID" in x.upper() for x in leituras)


def test_banco_ocupado(tmp_path):
    """Outra gravacao segurando a trava: a resposta e "contas ocupadas" (a espera do busy_timeout) e nada muda."""
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    v = _versao(c, "Leitor")
    l = _gid(c, "Leitor")
    outro = sqlite3.connect(tmp_path / "contas.db", isolation_level=None)
    outro.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(A.ContasOcupadas):
            c.definir_permissoes_do_grupo(l, list(LEITOR | {"triar_artigos"}), TODAS, v, False, "", AGORA)
    finally:
        outro.execute("ROLLBACK")
        outro.close()
    assert _perms(c, "Leitor") == LEITOR and _auditoria(c) == []


def test_alteracao_recusada_guarda_a_lista():
    e = A.AlteracaoRecusada(["a", "b"])
    assert e.erros == ["a", "b"] and isinstance(e, Exception)
