"""Configuracoes de referencia dos seis perfis e comparacao de um grupo com uma delas. A referencia so sugere: a comparacao
lista as diferencas, nenhuma marcada, e a montagem das escolhas leva para a revisao existente so o que foi escolhido, uma
permissao por vez. Regra pura, sem banco."""
from itertools import combinations

import pytest

from dominio import autenticacao as A

TODAS = list(A.PERMISSOES)
ADMIN = "O grupo Administrador tem acesso integral e não pode ser alterado."
INCOMPLETO = "O formulário veio incompleto. Abra o grupo de novo e refaça as alterações."
PERFIL_INVALIDO = "Escolha um dos perfis de referência da lista."
SO_PUBLICO = "O grupo Visitante só pode ser comparado com a referência do Público."
NADA = "Marque ao menos uma diferença para revisar."
REVISOR = {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "verificar_achados", "triar_artigos", "triar_texto_completo",
           "ver_registros_revisao", "ver_custos"}
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}

ESPERADAS = {
    "administrador": set(TODAS),
    "professor_direito": {"ver_painel", "ver_registros_revisao", "triar_artigos", "triar_texto_completo",
                          "verificar_achados", "revogar_verificacao", "ver_nomes_revisores", "ver_estatisticas_usuarios"},
    "professor_computacao": {"ver_painel", "ver_registros_revisao", "triar_artigos", "triar_texto_completo",
                             "verificar_achados", "revogar_verificacao", "ver_nomes_revisores",
                             "ver_estatisticas_usuarios", "ver_chamadas", "ver_custos"},
    "estudante_direito": {"ver_painel", "ver_registros_revisao", "triar_artigos", "triar_texto_completo",
                          "verificar_achados"},
    "estudante_computacao": {"ver_painel", "ver_registros_revisao", "triar_artigos", "triar_texto_completo",
                             "verificar_achados"},
    "publico": {"ver_painel"},
}


def _desc(p):
    return A.PERMISSOES[p]


# ---------- as constantes ----------

def test_seis_perfis_na_ordem_e_com_rotulos():
    assert A.PERFIS_REFERENCIA == ("administrador", "professor_direito", "professor_computacao", "estudante_direito",
                                   "estudante_computacao", "publico")
    assert A.ROTULOS_PERFIL_REFERENCIA == {
        "administrador": "Administrador",
        "professor_direito": "Professor de Direito",
        "professor_computacao": "Professor de Computação",
        "estudante_direito": "Estudante de Direito",
        "estudante_computacao": "Estudante de Computação",
        "publico": "Público",
    }
    assert list(A.ROTULOS_PERFIL_REFERENCIA) == list(A.PERFIS_REFERENCIA)
    assert list(A.REFERENCIAS_PERFIS) == list(A.PERFIS_REFERENCIA)


@pytest.mark.parametrize("perfil", list(ESPERADAS))
def test_valores_aprovados_de_cada_referencia(perfil):
    """Matriz do E4 sem gerir_validacao, com as tres retiradas da decisao do pesquisador nos estudantes."""
    valor = A.REFERENCIAS_PERFIS[perfil]
    assert type(valor) is frozenset
    assert set(valor) == ESPERADAS[perfil]


def test_retiradas_aprovadas_nos_estudantes():
    assert "ver_nomes_revisores" not in A.REFERENCIAS_PERFIS["estudante_direito"]
    assert "ver_nomes_revisores" not in A.REFERENCIAS_PERFIS["estudante_computacao"]
    assert "ver_chamadas" not in A.REFERENCIAS_PERFIS["estudante_computacao"]


@pytest.mark.parametrize("perfil", list(ESPERADAS))
def test_referencia_so_tem_permissoes_do_catalogo_e_respeita_dependencias(perfil):
    valor = A.REFERENCIAS_PERFIS[perfil]
    assert valor <= set(A.CATALOGO_PERMISSOES)
    assert "gerir_validacao" not in valor
    for p in valor:
        for d in A.CATALOGO_PERMISSOES[p]["depende_de"]:
            assert d in valor, (perfil, p, d)


def test_publico_so_ver_painel_e_nada_proibido_ou_sensivel():
    pub = A.REFERENCIAS_PERFIS["publico"]
    assert pub == frozenset({"ver_painel"})
    assert not (pub & A.PERMISSOES_PROIBIDAS_VISITANTE)
    assert not any(A.CATALOGO_PERMISSOES[p]["sensibilidade"] in A.ROTULOS_SENSIBILIDADE for p in pub)


# ---------- comparar_com_referencia ----------

def _chaves(itens):
    return [i["permissao"] for i in itens]


def test_comparacao_exemplo_literal():
    r = A.comparar_com_referencia("Leitor", LEITOR, "estudante_direito")
    assert r == {
        "perfil": "estudante_direito",
        "rotulo": "Estudante de Direito",
        "conceder": [
            {"permissao": "verificar_achados", "descricao": _desc("verificar_achados"), "sensivel": False,
             "marcada": False},
            {"permissao": "triar_artigos", "descricao": _desc("triar_artigos"), "sensivel": False, "marcada": False},
            {"permissao": "triar_texto_completo", "descricao": _desc("triar_texto_completo"), "sensivel": False,
             "marcada": False},
        ],
        "retirar": [
            {"permissao": "ver_nomes_revisores", "descricao": _desc("ver_nomes_revisores"), "sensivel": True,
             "marcada": False},
            {"permissao": "ver_custos", "descricao": _desc("ver_custos"), "sensivel": True, "marcada": False},
        ],
        "erros": [],
    }


GRUPOS_FIXTURE = [
    ("Leitor", LEITOR),
    ("Revisor", REVISOR),
    ("Professor de Direito", set()),
    ("Estudante de Computação", set(TODAS)),
    ("Outro", {"ver_painel", "enviar_coletas"}),
]


@pytest.mark.parametrize("perfil", list(ESPERADAS))
@pytest.mark.parametrize("grupo,atuais", GRUPOS_FIXTURE)
def test_diferencas_exatas_ordem_do_catalogo_e_nenhuma_marcada(grupo, atuais, perfil):
    r = A.comparar_com_referencia(grupo, atuais, perfil)
    ref = ESPERADAS[perfil]
    assert r["erros"] == []
    assert _chaves(r["conceder"]) == [p for p in TODAS if p in ref and p not in atuais]
    assert _chaves(r["retirar"]) == [p for p in TODAS if p in atuais and p not in ref]
    for item in r["conceder"] + r["retirar"]:
        assert item["marcada"] is False
        assert item["descricao"] == A.PERMISSOES[item["permissao"]]
        assert item["sensivel"] is (A.CATALOGO_PERMISSOES[item["permissao"]]["sensibilidade"]
                                    in A.ROTULOS_SENSIBILIDADE)


def test_ordem_e_a_do_catalogo_nao_a_alfabetica():
    r = A.comparar_com_referencia("Vazio", set(), "administrador")
    assert _chaves(r["conceder"]) == TODAS
    assert TODAS != sorted(TODAS)


def test_grupo_igual_a_referencia_nao_tem_diferencas():
    r = A.comparar_com_referencia("Professor de Direito", set(ESPERADAS["professor_direito"]), "professor_direito")
    assert r["conceder"] == [] and r["retirar"] == [] and r["erros"] == []


def test_permissao_gravada_desconhecida_nunca_aparece_nas_diferencas():
    r = A.comparar_com_referencia("Antigo", {"ver_painel", "gerir_validacao", "x"}, "publico")
    assert r["conceder"] == [] and r["retirar"] == [] and r["erros"] == []


@pytest.mark.parametrize("atuais", [set(), [], (), frozenset(), ["ver_painel"], ("ver_painel",)])
def test_atuais_em_qualquer_colecao(atuais):
    r = A.comparar_com_referencia("G", atuais, "publico")
    assert _chaves(r["conceder"]) == ([] if "ver_painel" in atuais else ["ver_painel"])


def test_sem_nome_do_grupo_puxando_referencia():
    """O perfil vem sempre do argumento: um grupo chamado como um perfil nao muda nada."""
    a = A.comparar_com_referencia("Professor de Computação", set(), "publico")
    b = A.comparar_com_referencia("Qualquer", set(), "publico")
    assert a == b
    assert _chaves(a["conceder"]) == ["ver_painel"]


def _vazio(erro, perfil=None, rotulo=None):
    return {"perfil": perfil, "rotulo": rotulo, "conceder": [], "retirar": [], "erros": [erro]}


@pytest.mark.parametrize("perfil", [None, "", " ", " publico", "publico ", "Publico", "PUBLICO", "público", "Público",
                                    "professor-direito", "gerir_validacao", 1, 0, True, ["publico"], ("publico",),
                                    {"publico": 1}, b"publico", 1.5])
def test_perfil_fora_da_lista_e_recusado_sem_normalizar(perfil):
    assert A.comparar_com_referencia("Leitor", LEITOR, perfil) == _vazio(PERFIL_INVALIDO)


@pytest.mark.parametrize("perfil", [p for p in ESPERADAS] + [None, "x"])
def test_grupo_administrador_nunca_compara(perfil):
    assert A.comparar_com_referencia(A.GRUPO_ADMIN, set(TODAS), perfil) == _vazio(ADMIN)


@pytest.mark.parametrize("perfil", [p for p in ESPERADAS if p != "publico"])
def test_visitante_so_com_o_publico(perfil):
    assert A.comparar_com_referencia(A.GRUPO_VISITANTE, {"ver_painel"}, perfil) == _vazio(SO_PUBLICO)


def test_visitante_com_perfil_invalido_recebe_erro_do_perfil():
    assert A.comparar_com_referencia(A.GRUPO_VISITANTE, set(), "x") == _vazio(PERFIL_INVALIDO)


@pytest.mark.parametrize("atuais", [set(), {"ver_painel"}, {"ver_painel", "ver_nomes_revisores"}, set(TODAS)])
def test_visitante_com_o_publico(atuais):
    r = A.comparar_com_referencia(A.GRUPO_VISITANTE, atuais, "publico")
    assert r["erros"] == []
    assert set(_chaves(r["conceder"])) <= {"ver_painel"}
    assert _chaves(r["retirar"]) == [p for p in TODAS if p in atuais and p != "ver_painel"]


def test_resultado_novo_a_cada_chamada():
    """Mexer no resultado nunca altera a referencia nem a proxima comparacao."""
    r = A.comparar_com_referencia("G", set(), "publico")
    r["conceder"][0]["marcada"] = True
    r["conceder"].append({"permissao": "ver_custos"})
    assert A.comparar_com_referencia("G", set(), "publico")["conceder"] == [
        {"permissao": "ver_painel", "descricao": _desc("ver_painel"), "sensivel": False, "marcada": False}]
    assert A.REFERENCIAS_PERFIS["publico"] == frozenset({"ver_painel"})


def test_comparacao_segue_o_catalogo_de_sensibilidade(monkeypatch):
    catalogo = {k: dict(v) for k, v in A.CATALOGO_PERMISSOES.items()}
    catalogo["ver_painel"]["sensibilidade"] = "financeira"
    monkeypatch.setattr(A, "CATALOGO_PERMISSOES", catalogo)
    r = A.comparar_com_referencia("G", set(), "publico")
    assert r["conceder"][0]["sensivel"] is True


def test_comparacao_segue_as_referencias_do_modulo(monkeypatch):
    refs = dict(A.REFERENCIAS_PERFIS)
    refs["publico"] = frozenset({"ver_painel", "ver_custos"})
    monkeypatch.setattr(A, "REFERENCIAS_PERFIS", refs)
    assert _chaves(A.comparar_com_referencia("G", set(), "publico")["conceder"]) == ["ver_painel", "ver_custos"]


# ---------- montar_escolhas_da_referencia ----------

def _sem(erros):
    return {"exibidas": [], "marcadas": [], "escolhidas": [], "erros": erros}


def test_montagem_exemplo_literal():
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["ver_custos", "triar_artigos"])
    assert r == {
        "exibidas": ["triar_artigos", "ver_custos"],
        "marcadas": ["triar_artigos"],
        "escolhidas": ["triar_artigos", "ver_custos"],
        "erros": [],
    }


def test_nenhuma_escolha_nada_segue():
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", []) == _sem([NADA])
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ()) == _sem([NADA])


@pytest.mark.parametrize("escolhidas", [None, "ver_custos", b"ver_custos", 1, {"ver_custos": 1}, {"ver_custos"},
                                        ["ver_custos", 1], [None], [["ver_custos"]], [b"ver_custos"]])
def test_escolhas_de_tipo_errado(escolhidas):
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", escolhidas) == _sem([INCOMPLETO])


def test_erro_da_comparacao_vem_primeiro_e_sozinho():
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "x", None) == _sem([PERFIL_INVALIDO])
    assert A.montar_escolhas_da_referencia(A.GRUPO_ADMIN, set(TODAS), "publico", ["ver_painel"]) == _sem([ADMIN])
    assert A.montar_escolhas_da_referencia(A.GRUPO_VISITANTE, set(), "professor_direito",
                                           ["ver_painel"]) == _sem([SO_PUBLICO])


def test_desconhecidas_contadas_sem_ecoar():
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["<b>x</b>"])
    assert r == _sem(["O formulário trouxe 1 permissão desconhecida."])
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["a", "b", "a", "gerir_validacao"])
    assert r == _sem(["O formulário trouxe 3 permissões desconhecidas."])
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", [" triar_artigos", "TRIAR_ARTIGOS"])
    assert r == _sem(["O formulário trouxe 2 permissões desconhecidas."])


def test_permissao_que_nao_e_diferenca_e_recusada_na_ordem_de_entrada():
    """ver_painel ja esta no grupo e na referencia; enviar_coletas nao esta em nenhum dos dois."""
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito",
                                        ["enviar_coletas", "triar_artigos", "ver_painel", "enviar_coletas"])
    assert r == _sem([
        f"«{_desc('enviar_coletas')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo.",
        f"«{_desc('ver_painel')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo.",
    ])


def test_repetidas_por_primeira_aparicao_e_depois_das_outras():
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito",
                                        ["ver_custos", "triar_artigos", "triar_artigos", "ver_custos", "ver_custos"])
    assert r == _sem([
        f"«{_desc('ver_custos')}» foi escolhida mais de uma vez.",
        f"«{_desc('triar_artigos')}» foi escolhida mais de uma vez.",
    ])


def test_todos_os_erros_juntos_na_ordem():
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito",
                                        ["triar_artigos", "x", "ver_painel", "triar_artigos", "y", "enviar_coletas"])
    assert r == _sem([
        "O formulário trouxe 2 permissões desconhecidas.",
        f"«{_desc('ver_painel')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo.",
        f"«{_desc('enviar_coletas')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo.",
        f"«{_desc('triar_artigos')}» foi escolhida mais de uma vez.",
    ])


def test_saida_na_ordem_do_catalogo():
    r = A.montar_escolhas_da_referencia("Vazio", set(), "administrador", ["enviar_coletas", "ver_custos", "ver_painel"])
    assert r["escolhidas"] == ["ver_painel", "enviar_coletas", "ver_custos"]
    assert r["exibidas"] == ["ver_painel", "enviar_coletas", "ver_custos"]
    assert r["marcadas"] == ["ver_painel", "enviar_coletas", "ver_custos"]


def test_montagem_segue_a_comparacao(monkeypatch):
    """A montagem confere as escolhas contra a comparacao recalculada no servidor, nunca contra uma lista propria."""
    def falsa(grupo, atuais, perfil):
        return {"perfil": perfil, "rotulo": "R", "erros": [],
                "conceder": [{"permissao": "enviar_coletas", "descricao": "d", "sensivel": True, "marcada": False}],
                "retirar": []}
    monkeypatch.setattr(A, "comparar_com_referencia", falsa)
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["enviar_coletas"])
    assert r == {"exibidas": ["enviar_coletas"], "marcadas": ["enviar_coletas"], "escolhidas": ["enviar_coletas"],
                 "erros": []}
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["triar_artigos"])
    assert r["erros"] == [
        f"«{_desc('triar_artigos')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo."]


def test_estado_atual_mudou_desde_a_comparacao():
    """O grupo ganhou triar_artigos depois que a pagina foi aberta: a escolha deixou de ser diferenca e e recusada."""
    r = A.montar_escolhas_da_referencia("Leitor", LEITOR | {"triar_artigos"}, "estudante_direito", ["triar_artigos"])
    assert r["erros"] == [
        f"«{_desc('triar_artigos')}» não é uma diferença entre o grupo e a referência escolhida. Compare de novo."]


# ---------- a garantia: so o escolhido muda, pela revisao existente ----------

ESTADOS = [set(), {"ver_painel"}, LEITOR, REVISOR, set(TODAS), {"ver_painel", "enviar_coletas", "revogar_verificacao",
                                                               "verificar_achados"}]


@pytest.mark.parametrize("perfil", [p for p in ESPERADAS])
@pytest.mark.parametrize("atuais", ESTADOS)
def test_revisao_muda_exatamente_as_diferencas_escolhidas(atuais, perfil):
    comp = A.comparar_com_referencia("Grupo", atuais, perfil)
    conceder = {i["permissao"] for i in comp["conceder"]}
    retirar = {i["permissao"] for i in comp["retirar"]}
    difs = [i["permissao"] for i in comp["conceder"] + comp["retirar"]]
    tamanhos = range(len(difs) + 1) if len(difs) <= 8 else (1, 2, len(difs) - 1, len(difs))
    for n in tamanhos:
        for escolha in combinations(difs, n):
            m = A.montar_escolhas_da_referencia("Grupo", atuais, perfil, list(escolha))
            if not escolha:
                assert m == _sem([NADA])
                continue
            assert m["erros"] == []
            rev = A.revisar_alteracao("Grupo", atuais, m["marcadas"], m["exibidas"])
            esperado = (set(atuais) | (set(escolha) & conceder)) - (set(escolha) & retirar)
            assert set(rev["depois"]) == esperado, (perfil, sorted(atuais), escolha)
            assert set(rev["concedidas"]) == set(escolha) & conceder
            assert set(rev["retiradas"]) == set(escolha) & retirar


def test_concessao_desmarcada_nao_entra_e_retirada_desmarcada_nao_sai():
    m = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["triar_artigos"])
    rev = A.revisar_alteracao("Leitor", LEITOR, m["marcadas"], m["exibidas"])
    assert rev["concedidas"] == ["triar_artigos"] and rev["retiradas"] == []
    assert "ver_custos" in rev["depois"] and "ver_nomes_revisores" in rev["depois"]
    assert "verificar_achados" not in rev["depois"]
    m = A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["ver_custos"])
    rev = A.revisar_alteracao("Leitor", LEITOR, m["marcadas"], m["exibidas"])
    assert rev["concedidas"] == [] and rev["retiradas"] == ["ver_custos"]
    assert "ver_nomes_revisores" in rev["depois"]


def test_dependencia_faltando_continua_recusada_pela_revisao():
    m = A.montar_escolhas_da_referencia("Vazio", {"ver_painel"}, "estudante_direito", ["triar_texto_completo"])
    assert m["erros"] == []
    rev = A.revisar_alteracao("Vazio", {"ver_painel"}, m["marcadas"], m["exibidas"])
    assert rev["erros"] == [f"«{_desc('triar_texto_completo')}» precisa de «{_desc('triar_artigos')}»: marque as duas "
                            f"ou desmarque «{_desc('triar_texto_completo')}»."]


def test_sensivel_escolhida_continua_exigindo_confirmacao_e_justificativa():
    m = A.montar_escolhas_da_referencia("Leitor", LEITOR, "professor_computacao", ["ver_chamadas"])
    rev = A.revisar_alteracao("Leitor", LEITOR, m["marcadas"], m["exibidas"])
    assert rev["sensiveis"] == ["ver_chamadas"] and rev["exige_justificativa"] is True
    assert A.pendencias_da_gravacao(rev, False, "") == [
        "Marque a confirmação das permissões sensíveis antes de gravar.",
        "Escreva a justificativa: ela é obrigatória ao conceder permissões sensíveis ou retirar uma permissão de "
        "supervisão."]


@pytest.mark.parametrize("perfil", [p for p in ESPERADAS])
@pytest.mark.parametrize("atuais", ESTADOS)
def test_visitante_nunca_recebe_mais_que_ver_painel_por_referencia(atuais, perfil):
    comp = A.comparar_com_referencia(A.GRUPO_VISITANTE, atuais, perfil)
    assert {i["permissao"] for i in comp["conceder"]} <= {"ver_painel"}
    for p in TODAS:
        m = A.montar_escolhas_da_referencia(A.GRUPO_VISITANTE, atuais, perfil, [p])
        assert not (set(m["marcadas"]) - {"ver_painel"})


# ---------- fontes lidas na hora e resultados novos ----------

def test_comparacao_le_descricoes_e_ordem_do_catalogo_na_hora(monkeypatch):
    perms = {"ver_custos": "Custos (outro texto)", **{k: v for k, v in A.PERMISSOES.items() if k != "ver_custos"}}
    monkeypatch.setattr(A, "PERMISSOES", perms)
    r = A.comparar_com_referencia("Vazio", set(), "administrador")
    assert _chaves(r["conceder"])[0] == "ver_custos" and r["conceder"][0]["descricao"] == "Custos (outro texto)"
    m = A.montar_escolhas_da_referencia("Vazio", set(), "administrador", ["ver_painel", "ver_custos"])
    assert m["escolhidas"] == ["ver_custos", "ver_painel"]


def test_comparacao_le_as_categorias_sensiveis_na_hora(monkeypatch):
    monkeypatch.setattr(A, "ROTULOS_SENSIBILIDADE", {"financeira": "financeira"})
    r = A.comparar_com_referencia("Vazio", set(), "professor_computacao")
    assert [i["permissao"] for i in r["conceder"] if i["sensivel"]] == ["ver_custos"]


def test_tupla_nao_vazia_vale_como_lista():
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ("ver_custos", "triar_artigos")) == \
        A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ["ver_custos", "triar_artigos"])
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito",
                                           ("triar_artigos", "x", "triar_artigos")) == _sem([
        "O formulário trouxe 1 permissão desconhecida.",
        f"«{_desc('triar_artigos')}» foi escolhida mais de uma vez."])
    assert A.montar_escolhas_da_referencia("Leitor", LEITOR, "estudante_direito", ("triar_artigos", 1)) == _sem([INCOMPLETO])


def test_montagem_devolve_resultado_novo_a_cada_chamada():
    args = ("Leitor", LEITOR, "estudante_direito", ["ver_custos", "triar_artigos"])
    r = A.montar_escolhas_da_referencia(*args)
    for chave in ("exibidas", "marcadas", "escolhidas", "erros"):
        r[chave].append("enviar_coletas")
    r["novo"] = 1
    assert A.montar_escolhas_da_referencia(*args) == {"exibidas": ["triar_artigos", "ver_custos"],
                                                      "marcadas": ["triar_artigos"],
                                                      "escolhidas": ["triar_artigos", "ver_custos"], "erros": []}
    for args_erro, erro in [(("Leitor", LEITOR, "x", []), PERFIL_INVALIDO), (("Leitor", LEITOR, "publico", []), NADA),
                            ((A.GRUPO_ADMIN, set(), "publico", ["ver_painel"]), ADMIN)]:
        e = A.montar_escolhas_da_referencia(*args_erro)
        for chave in ("exibidas", "marcadas", "escolhidas", "erros"):
            e[chave].append("ver_custos")
        assert A.montar_escolhas_da_referencia(*args_erro) == _sem([erro])
    c = A.comparar_com_referencia("Leitor", LEITOR, "x")
    c["erros"].append("y")
    assert A.comparar_com_referencia("Leitor", LEITOR, "x") == _vazio(PERFIL_INVALIDO)
