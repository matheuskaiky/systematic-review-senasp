"""Tela de edicao das permissoes de um grupo: formulario com o catalogo inteiro, pagina de revisao que nao grava, gravacao
de um so grupo pelo adaptador (versao, revalidacao, confirmacao e justificativa no servidor), matriz so de leitura (o
envio antigo deixou de existir) e auditoria legivel. Todos os bancos sao temporarios."""
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dominio import autenticacao as A
from test_admin import _auditoria, _criar, _csrf, _gid, adm  # noqa: F401
from test_painel import demo  # noqa: F401

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
TODAS = list(A.PERMISSOES)
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}
ORDEM_DA_PAGINA = [p for m in A.MODULOS_PERMISSAO for p in TODAS if A.CATALOGO_PERMISSOES[p]["modulo"] == m]   # modulo, depois catalogo
ADMIN = "O grupo Administrador tem acesso integral e não pode ser alterado."
INCOMPLETO = "O formulário veio incompleto. Abra o grupo de novo e refaça as alterações."
CONFIRMAR = "Marque a confirmação das permissões sensíveis antes de gravar."
JUSTIFICAR = ("Escreva a justificativa: ela é obrigatória ao conceder permissões sensíveis ou retirar uma permissão de "
              "supervisão.")
ALTERADAS = ("As permissões deste grupo mudaram desde que você abriu a página. Nada foi gravado: abra o grupo de novo e "
             "refaça as alterações.")


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


def _publica(p):
    return f"«{_d(p)}» não pode ser dada a quem não entrou enquanto não houver política de divulgação pública."


def _perms(contas_db, nome):
    return {p for (p,) in sqlite3.connect(contas_db).execute(
        "SELECT gp.permissao FROM grupo_permissoes gp JOIN grupos g USING (grupo_id) WHERE g.nome = ?", (nome,))}


def _erros(h):
    i = h.index('<ul class="aviso erro" role="alert">')
    return re.findall(r"<li>([^<]+)</li>", h[i:h.index("</ul>", i)])


def _form(h, acao):
    """O formulario de `acao` como lista de pares (campos ocultos e caixas marcadas), na ordem da pagina."""
    i = h.index(f'<form method="post" action="{acao}"')
    f = h[i:h.index("</form>", i)]
    pares = []
    for tag in re.findall(r"<input [^>]*>", f):
        nome = re.search(r'name="([^"]+)"', tag).group(1)
        valor = re.search(r'value="([^"]*)"', tag).group(1)
        if 'type="checkbox"' in tag and " checked" not in tag:
            continue
        pares.append((nome, valor))
    return pares


def _post(cli, caminho, pares):
    corpo = {}
    for k, v in pares:
        corpo.setdefault(k, []).append(v)
    return cli.post(caminho, data=corpo, follow_redirects=False)


def _editar(cli, gid):
    return cli.get(f"/admin/grupos/{gid}/editar").text


def _revisar(cli, gid, marcadas, exibidas=None, versao=None, extra=()):
    """Envia a revisao como a pagina de edicao faria, com as `marcadas` no lugar das caixas da pagina."""
    base = _form(_editar(cli, gid), f"/admin/grupos/{gid}/revisar")
    pares = [(k, v) for k, v in base if k not in ("marcada", "exibida", "versao")]
    pares += [("versao", versao if versao is not None else dict(base)["versao"])]
    pares += [("exibida", p) for p in (exibidas if exibidas is not None else [v for k, v in base if k == "exibida"])]
    pares += [("marcada", p) for p in marcadas]
    return _post(cli, f"/admin/grupos/{gid}/revisar", pares + list(extra))


def _gravar(cli, gid, marcadas, confirmo=False, justificativa="", versao=None):
    """Revisa e envia o formulario de confirmacao da pagina de revisao."""
    h = _revisar(cli, gid, marcadas, versao=versao).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{gid}/permissoes") if k != "confirmo"]
    if confirmo:
        pares.append(("confirmo", "1"))
    pares.append(("justificativa", justificativa))
    return _post(cli, f"/admin/grupos/{gid}/permissoes", pares)


def _itens(h):
    return dict(re.findall(r'<li class="perm" data-chave="([a-z_]+)">(.*?)</li>', h, re.S))


# ======================== pagina de edicao ========================
def test_edicao_traz_o_catalogo_inteiro_marcado_como_esta(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _editar(cli, l)
    assert "<title>Editar permissões — Leitor" in h and "<h1>Editar permissões: Leitor</h1>" in h
    pares = _form(h, f"/admin/grupos/{l}/revisar")
    assert [v for k, v in pares if k == "exibida"] == ORDEM_DA_PAGINA               # catalogo inteiro, na ordem da pagina
    assert {v for k, v in pares if k == "marcada"} == LEITOR
    assert dict(pares)["versao"] == A.versao_permissoes({l: LEITOR})
    assert '<button class="botao" type="submit">Revisar alterações</button>' in h
    assert f'<a href="/admin/grupos/{l}">Voltar ao grupo</a>' in h


def test_edicao_sem_filtro_mesmo_com_parametros(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = cli.get(f"/admin/grupos/{l}/editar?q=nada&filtro=habilitadas&modulo=tecnico").text
    assert [v for k, v in _form(h, f"/admin/grupos/{l}/revisar") if k == "exibida"] == ORDEM_DA_PAGINA


def test_cada_permissao_com_rotulo_marca_e_dependencia(adm):
    cli, _, contas_db, _ = adm
    itens = _itens(_editar(cli, _gid(contas_db, "Leitor")))
    assert list(itens) == ORDEM_DA_PAGINA
    for p, corpo in itens.items():
        meta = A.CATALOGO_PERMISSOES[p]
        assert f'<input type="checkbox" id="p-{p}" name="marcada" value="{p}"' in corpo, p
        assert f'<label for="p-{p}">{_d(p)}</label>' in corpo, p
        rotulo = A.ROTULOS_SENSIBILIDADE.get(meta["sensibilidade"])
        assert (f'<span class="perm-sensivel">◆ {rotulo}</span>' in corpo) == bool(rotulo), p
        assert re.findall(r'<span class="perm-depende">precisa de: ([^<]+)</span>', corpo) == [_d(d) for d in meta["depende_de"]], p


def test_modulos_em_fieldset_na_ordem(adm):
    cli, _, contas_db, _ = adm
    h = _editar(cli, _gid(contas_db, "Leitor"))
    assert re.findall(r'<fieldset class="modulo"><legend>([^<]+)</legend>', h) == list(A.MODULOS_PERMISSAO.values())


def test_visitante_sem_caixa_para_o_que_nao_pode_receber(adm):
    cli, contas, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    h = _editar(cli, v)
    itens = _itens(h)
    pares = _form(h, f"/admin/grupos/{v}/revisar")
    editaveis = [p for p in TODAS if p not in A.PERMISSOES_PROIBIDAS_VISITANTE and
                 A.CATALOGO_PERMISSOES[p]["sensibilidade"] not in A.ROTULOS_SENSIBILIDADE]
    assert [x for k, x in pares if k == "exibida"] == editaveis == ["ver_painel"]
    for p in A.PERMISSOES_PROIBIDAS_VISITANTE:
        assert 'type="checkbox"' not in itens[p] and '<span class="perm-estado">Não permitida a quem não entrou</span>' in itens[p]
    for p in ("ver_chamadas", "ver_nomes_revisores"):
        assert 'type="checkbox"' not in itens[p]
        assert '<span class="perm-estado">Só com a política de divulgação pública</span>' in itens[p]


def test_visitante_que_ja_tem_permissao_publica_pode_retira_la(adm):
    cli, contas, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    contas.definir_permissoes(v, {"ver_painel", "ver_chamadas"})
    pares = _form(_editar(cli, v), f"/admin/grupos/{v}/revisar")
    assert [x for k, x in pares if k == "exibida"] == ["ver_painel", "ver_chamadas"]
    assert {x for k, x in pares if k == "marcada"} == {"ver_painel", "ver_chamadas"}


def test_visitante_com_permissao_proibida_gravada_pode_retira_la(adm):
    """Estado antigo: uma permissao proibida ja gravada para o Visitante aparece marcada e pode ser retirada."""
    cli, contas, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    with sqlite3.connect(contas_db) as conn:
        conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, 'verificar_achados')", (v,))
    h = _editar(cli, v)
    pares = _form(h, f"/admin/grupos/{v}/revisar")
    assert [x for k, x in pares if k == "exibida"] == ["ver_painel", "verificar_achados"]
    assert {x for k, x in pares if k == "marcada"} == {"ver_painel", "verificar_achados"}
    r = _gravar(cli, v, ["ver_painel"])
    assert r.status_code == 303 and _perms(contas_db, "Visitante") == {"ver_painel"}


def test_administrador_nao_tem_formulario(adm):
    cli, _, contas_db, _ = adm
    a = _gid(contas_db, "Administrador")
    h = _editar(cli, a)
    assert f"<p>{ADMIN}</p>" in h and f'action="/admin/grupos/{a}/revisar"' not in h and 'name="marcada"' not in h


@pytest.mark.parametrize("caminho,titulo,texto", [
    ("999999", "Grupo não encontrado", "Não existe o grupo nº 999999."),
    ("abc", "Endereço inválido", "Algum número ou parâmetro do endereço não é válido."),
    ("0" * 30, "Grupo não encontrado", "Não existe o grupo nº 0."),
    ("9" * 30, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido."),
])
def test_edicao_de_grupo_inexistente_ou_invalido(adm, caminho, titulo, texto):
    cli = adm[0]
    r = cli.get(f"/admin/grupos/{caminho}/editar")
    assert r.status_code == 404 and titulo in r.text and texto in r.text


def test_id_com_zeros_a_esquerda_abre_o_mesmo_grupo(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    assert "<h1>Editar permissões: Leitor</h1>" in cli.get(f"/admin/grupos/000{l}/editar").text


@pytest.mark.parametrize("rota", ["editar", "revisar", "permissoes"])
def test_as_rotas_usam_o_conversor_do_painel(adm, monkeypatch, rota):
    from painel.rotas_extras import admin
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    monkeypatch.setattr(admin, "_converter_id", lambda texto: None)
    if rota == "editar":
        r = cli.get(f"/admin/grupos/{l}/editar")
    else:
        r = _post(cli, f"/admin/grupos/{l}/{rota}", [("csrf", _csrf(cli, "/admin/grupos")), ("versao", "x")])
    assert r.status_code == 404 and "Algum número ou parâmetro do endereço não é válido." in r.text


def test_algarismos_nao_ascii_no_endereco(adm):
    cli = adm[0]
    r = cli.get("/admin/grupos/\u0661/editar")
    assert r.status_code == 404 and "Algum número ou parâmetro do endereço não é válido." in r.text


def test_pagina_do_grupo_tem_o_botao_de_editar(adm):
    cli, _, contas_db, _ = adm
    l, a = _gid(contas_db, "Leitor"), _gid(contas_db, "Administrador")
    assert f'<a class="botao" href="/admin/grupos/{l}/editar">Editar permissões</a>' in cli.get(f"/admin/grupos/{l}").text
    assert "/editar" not in cli.get(f"/admin/grupos/{a}").text


def test_nome_do_grupo_escapado(adm):
    cli, contas, contas_db, _ = adm
    g = contas.criar_grupo('A<b>&"c', "2026-10-28T00:00:00+00:00")
    h = _editar(cli, g)
    assert "<h1>Editar permissões: A&lt;b&gt;&amp;&#34;c</h1>" in h and 'A<b>&"c' not in h
    h = _revisar(cli, g, ["ver_painel"]).text
    assert "<h1>Revisar alterações: A&lt;b&gt;&amp;&#34;c</h1>" in h and 'A<b>&"c' not in h


# ======================== revisao ========================
def test_revisao_de_concessao_comum(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    r = _revisar(cli, l, sorted(LEITOR | {"triar_artigos"}))
    h = r.text
    assert r.status_code == 200 and "<title>Revisar alterações — Leitor" in h and "<h1>Revisar alterações: Leitor</h1>" in h
    assert f"<h2>Serão concedidas (1)</h2>\n<ul>\n<li>{_d('triar_artigos')}</li>\n</ul>" in h
    assert "Serão retiradas" not in h and 'name="confirmo"' not in h
    assert '<label for="justificativa">Justificativa (opcional)</label>' in h
    assert '<textarea id="justificativa" name="justificativa" maxlength="500"></textarea>' in h
    assert '<button class="botao" type="submit">Confirmar</button>' in h
    assert f'<a href="/admin/grupos/{l}/editar">Voltar e editar</a>' in h
    assert _perms(contas_db, "Leitor") == LEITOR and _auditoria(contas_db) == []            # revisar nao grava


def test_revisao_repassa_o_formulario_como_veio(adm):
    """Os campos ocultos da confirmacao repetem o que foi enviado (ordem e repeticoes), e a versao recebida."""
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    marcadas = ["triar_artigos", "ver_painel", "ver_custos", "ver_painel", "ver_nomes_revisores", "ver_registros_revisao"]
    exibidas = TODAS + ["ver_custos"]
    h = _revisar(cli, l, marcadas, exibidas=exibidas, versao=A.versao_permissoes({l: LEITOR})).text
    pares = _form(h, f"/admin/grupos/{l}/permissoes")
    assert [v for k, v in pares if k == "marcada"] == marcadas
    assert [v for k, v in pares if k == "exibida"] == exibidas
    assert [v for k, v in pares if k == "versao"] == [A.versao_permissoes({l: LEITOR})]


def test_revisao_de_concessao_sensivel_pede_caixa_e_justificativa(adm):
    cli, _, contas_db, _ = adm
    h = _revisar(cli, _gid(contas_db, "Leitor"), sorted(LEITOR | {"ver_chamadas"})).text
    assert f'<li>{_d("ver_chamadas")} <span class="perm-sensivel">◆ técnica restrita</span></li>' in h
    assert '<input type="checkbox" id="confirmo" name="confirmo" value="1">' in h
    assert '<label for="confirmo">Confirmo a concessão de 1 permissão sensível a este grupo.</label>' in h
    assert '<label for="justificativa">Justificativa (obrigatória)</label>' in h


def test_duas_sensiveis_no_plural(adm):
    cli, _, contas_db, _ = adm
    h = _revisar(cli, _gid(contas_db, "Leitor"), sorted(LEITOR | {"ver_chamadas", "ver_estatisticas_usuarios"})).text
    assert '<label for="confirmo">Confirmo a concessão de 2 permissões sensíveis a este grupo.</label>' in h


def test_revisao_de_retirada(adm):
    cli, _, contas_db, _ = adm
    h = _revisar(cli, _gid(contas_db, "Leitor"), sorted(LEITOR - {"ver_custos"})).text
    assert f"<h2>Serão retiradas (1)</h2>\n<ul>\n<li>{_d('ver_custos')}</li>\n</ul>" in h and "Serão concedidas" not in h
    assert '<label for="justificativa">Justificativa (opcional)</label>' in h and 'name="confirmo"' not in h


def test_retirar_supervisao_exige_justificativa(adm):
    cli, contas, contas_db, _ = adm
    g = contas.criar_grupo("Supervisores", "2026-10-28T00:00:00+00:00")
    contas.definir_permissoes(g, {"ver_painel", "verificar_achados", "revogar_verificacao"})
    h = _revisar(cli, g, ["ver_painel", "verificar_achados"]).text
    assert '<label for="justificativa">Justificativa (obrigatória)</label>' in h and 'name="confirmo"' not in h


def test_revisao_sem_alteracao(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _revisar(cli, l, sorted(LEITOR)).text
    assert '<p class="aviso" role="status">Nenhuma alteração.</p>' in h
    assert f'action="/admin/grupos/{l}/permissoes"' not in h and f'<a href="/admin/grupos/{l}/editar">Voltar e editar</a>' in h


def test_revisao_com_erros_nao_oferece_confirmar(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _revisar(cli, l, sorted(LEITOR | {"triar_texto_completo"})).text
    assert _erros(h) == [_dep("triar_texto_completo", "triar_artigos")]
    assert f'action="/admin/grupos/{l}/permissoes"' not in h and "Serão concedidas" not in h


def test_revisao_do_visitante_recusa_sensivel(adm):
    cli, _, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    h = _revisar(cli, v, ["ver_painel", "ver_chamadas"], exibidas=["ver_painel", "ver_chamadas"]).text
    assert _erros(h) == [_publica("ver_chamadas")] and f'action="/admin/grupos/{v}/permissoes"' not in h


def test_revisao_do_administrador(adm):
    cli, _, contas_db, _ = adm
    a = _gid(contas_db, "Administrador")
    r = _post(cli, f"/admin/grupos/{a}/revisar", [("csrf", _csrf(cli, "/admin/grupos")), ("versao", ""), ("exibida", "ver_painel")])
    assert _erros(r.text) == [ADMIN] and f'action="/admin/grupos/{a}/permissoes"' not in r.text


@pytest.mark.parametrize("n,frase", [
    (0, "Efeito imediato: este grupo não tem usuários ativos agora; a mudança vale para quem entrar nele."),
    (1, "Efeito imediato: vale a partir do próximo pedido do 1 usuário ativo deste grupo."),
    (2, "Efeito imediato: vale a partir do próximo pedido dos 2 usuários ativos deste grupo."),
])
def test_frase_de_efeito(adm, n, frase):
    cli, _, contas_db, _ = adm
    for i in range(n):
        assert _criar(cli, contas_db, login=f"leitor{i}", nome=f"Leitor {i}", grupo="Leitor").status_code == 303
    assert _criar(cli, contas_db, login="inativo", nome="Inativo", grupo="Leitor").status_code == 303
    assert _criar(cli, contas_db, login="revisor0", nome="Revisor", grupo="Revisor").status_code == 303   # outro grupo
    with sqlite3.connect(contas_db) as conn:
        conn.execute("UPDATE usuarios SET ativo = 0 WHERE login = 'inativo'")
    h = _revisar(cli, _gid(contas_db, "Leitor"), sorted(LEITOR | {"triar_artigos"})).text
    assert f'<p class="perm-efeito">{frase}</p>' in h


def test_frase_de_efeito_do_visitante(adm):
    cli, _, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    h = _revisar(cli, v, [], exibidas=["ver_painel"]).text                    # retirar ver_painel do Visitante
    assert "<h2>Serão retiradas (1)</h2>" in h
    assert '<p class="perm-efeito">Efeito imediato: vale para qualquer pessoa que abrir o painel sem entrar.</p>' in h


def test_revisar_sem_csrf_e_recusado(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    r = _post(cli, f"/admin/grupos/{l}/revisar", [("exibida", p) for p in TODAS])
    assert r.status_code == 403


# ======================== gravacao ========================
def test_grava_e_volta_ao_grupo(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    r = _gravar(cli, l, sorted(LEITOR | {"triar_artigos"}), justificativa="Bolsista de iniciação")
    assert r.status_code == 303 and r.headers["location"] == f"/admin/grupos/{l}?gravado=1"
    assert _perms(contas_db, "Leitor") == LEITOR | {"triar_artigos"}
    (acao, alvo, detalhe), = _auditoria(contas_db)
    assert (acao, alvo) == ("salvar_permissoes", "Leitor")
    assert json.loads(detalhe)["justificativa"] == "Bolsista de iniciação" and json.loads(detalhe)["origem"] == "edicao"
    assert '<p class="aviso ok" role="status">Permissões gravadas.</p>' in cli.get(r.headers["location"]).text


def test_reenvio_da_confirmacao_e_recusado(adm):
    """Um segundo clique em Confirmar leva a versao antiga: e recusado, mesmo que o estado ja seja o pedido."""
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _revisar(cli, l, sorted(LEITOR | {"triar_artigos"})).text
    pares = _form(h, f"/admin/grupos/{l}/permissoes") + [("justificativa", "")]
    assert _post(cli, f"/admin/grupos/{l}/permissoes", pares).status_code == 303
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares)
    assert r.status_code == 409 and ALTERADAS in r.text and len(_auditoria(contas_db)) == 1


def test_desmarcar_tudo_esvazia_o_grupo(adm):
    cli, contas, contas_db, _ = adm
    g = contas.criar_grupo("Bolsistas", "2026-10-28T00:00:00+00:00")
    contas.definir_permissoes(g, {"ver_painel", "triar_artigos"})
    r = _gravar(cli, g, [])
    assert r.status_code == 303 and r.headers["location"] == f"/admin/grupos/{g}?gravado=1"
    assert _perms(contas_db, "Bolsistas") == set() and len(_auditoria(contas_db)) == 1


def test_sem_alteracao_volta_sem_gravar(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    pares = _form(_editar(cli, l), f"/admin/grupos/{l}/revisar")
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares + [("justificativa", "")])
    assert r.status_code == 303 and r.headers["location"] == f"/admin/grupos/{l}?gravado=0"
    assert _auditoria(contas_db) == []
    assert '<p class="aviso" role="status">Nenhuma alteração.</p>' in cli.get(r.headers["location"]).text


@pytest.mark.parametrize("valor", ["2", "", "abc"])
def test_outros_valores_de_gravado_nao_mostram_aviso(adm, valor):
    cli, _, contas_db, _ = adm
    h = cli.get(f"/admin/grupos/{_gid(contas_db, 'Leitor')}?gravado={valor}").text
    assert "Permissões gravadas." not in h and "Nenhuma alteração." not in h


def test_sensivel_sem_confirmacao_volta_a_revisao(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    r = _gravar(cli, l, sorted(LEITOR | {"ver_chamadas"}), justificativa="Apoio <técnico>")
    assert r.status_code == 400 and _erros(r.text) == [CONFIRMAR]
    assert f'action="/admin/grupos/{l}/permissoes"' in r.text                          # pode marcar a caixa e confirmar
    assert '<textarea id="justificativa" name="justificativa" maxlength="500">Apoio &lt;técnico&gt;</textarea>' in r.text
    assert _perms(contas_db, "Leitor") == LEITOR and _auditoria(contas_db) == []


def test_sensivel_sem_nada_lista_as_duas_pendencias(adm):
    cli, _, contas_db, _ = adm
    r = _gravar(cli, _gid(contas_db, "Leitor"), sorted(LEITOR | {"ver_chamadas"}))
    assert r.status_code == 400 and _erros(r.text) == [CONFIRMAR, JUSTIFICAR]


def test_sensivel_confirmada_e_justificada_grava(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    r = _gravar(cli, l, sorted(LEITOR | {"ver_chamadas"}), confirmo=True, justificativa="Apoio técnico")
    assert r.status_code == 303 and _perms(contas_db, "Leitor") == LEITOR | {"ver_chamadas"}


@pytest.mark.parametrize("valor", ["on", "true", "0", ""])
def test_so_o_valor_1_confirma(adm, valor):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _revisar(cli, l, sorted(LEITOR | {"ver_chamadas"})).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{l}/permissoes") if k != "confirmo"]
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares + [("confirmo", valor), ("justificativa", "x")])
    assert r.status_code == 400 and _erros(r.text) == [CONFIRMAR]


def test_justificativa_longa_recusada(adm):
    cli, _, contas_db, _ = adm
    r = _gravar(cli, _gid(contas_db, "Leitor"), sorted(LEITOR | {"triar_artigos"}), justificativa="x" * 501)
    assert r.status_code == 400 and _erros(r.text) == ["A justificativa tem 501 caracteres; o máximo é 500."]


def test_versao_velha_recusa_com_409(adm):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _revisar(cli, l, sorted(LEITOR | {"triar_artigos"})).text
    contas.definir_permissoes(l, LEITOR - {"ver_custos"})                       # outra pessoa mudou no meio
    pares = _form(h, f"/admin/grupos/{l}/permissoes")
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares + [("justificativa", "")])
    assert r.status_code == 409 and ALTERADAS in r.text
    assert _perms(contas_db, "Leitor") == LEITOR - {"ver_custos"}


@pytest.mark.parametrize("versoes", [[], [""], ["0" * 64]], ids=["ausente", "vazia", "errada"])
def test_versao_ausente_ou_errada(adm, versoes):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    pares = [(k, v) for k, v in _form(_editar(cli, l), f"/admin/grupos/{l}/revisar") if k != "versao"]
    pares = [p for p in pares if p[0] != "marcada"] + [("marcada", p) for p in sorted(LEITOR | {"triar_artigos"})]
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares + [("versao", v) for v in versoes])
    assert r.status_code == 409 and _perms(contas_db, "Leitor") == LEITOR


def test_versao_repetida_vale_a_primeira(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    certa = A.versao_permissoes({l: LEITOR})
    base = [(k, v) for k, v in _form(_editar(cli, l), f"/admin/grupos/{l}/revisar") if k not in ("versao", "marcada")]
    marc = [("marcada", p) for p in sorted(LEITOR | {"triar_artigos"})]
    assert _post(cli, f"/admin/grupos/{l}/permissoes", base + marc + [("versao", "0" * 64), ("versao", certa)]).status_code == 409
    assert _post(cli, f"/admin/grupos/{l}/permissoes", base + marc + [("versao", certa), ("versao", "0" * 64)]).status_code == 303


def test_visitante_nao_recebe_sensivel_pela_gravacao(adm):
    cli, _, contas_db, _ = adm
    v = _gid(contas_db, "Visitante")
    pares = [("csrf", _csrf(cli, "/admin/grupos")), ("versao", A.versao_permissoes({v: {"ver_painel"}})),
             ("exibida", "ver_painel"), ("exibida", "ver_chamadas"), ("marcada", "ver_painel"), ("marcada", "ver_chamadas"),
             ("confirmo", "1"), ("justificativa", "teste")]
    r = _post(cli, f"/admin/grupos/{v}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text) == [_publica("ver_chamadas")]
    assert f'action="/admin/grupos/{v}/permissoes"' not in r.text
    assert _perms(contas_db, "Visitante") == {"ver_painel"} and _auditoria(contas_db) == []


def test_administrador_recusado_na_gravacao(adm):
    cli, _, contas_db, _ = adm
    a = _gid(contas_db, "Administrador")
    antes = _perms(contas_db, "Administrador")
    r = _post(cli, f"/admin/grupos/{a}/permissoes", [("csrf", _csrf(cli, "/admin/grupos")),
                                                     ("versao", A.versao_permissoes({a: antes})), ("exibida", "ver_painel")])
    assert r.status_code == 400 and _erros(r.text) == [ADMIN]
    assert f'action="/admin/grupos/{a}/permissoes"' not in r.text
    assert _perms(contas_db, "Administrador") == antes and _auditoria(contas_db) == []


@pytest.mark.parametrize("campo", ["marcada", "exibida"])
def test_arquivo_no_lugar_de_permissao_e_formulario_incompleto(adm, campo):
    """Um valor que nao e texto (arquivo enviado) chega ao adaptador como veio e cai na recusa estrutural."""
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    dados = {"csrf": _csrf(cli, "/admin/grupos"), "versao": A.versao_permissoes({l: LEITOR}),
             "exibida": TODAS if campo == "marcada" else [], "marcada": sorted(LEITOR) if campo == "exibida" else []}
    r = cli.post(f"/admin/grupos/{l}/permissoes", data=dados, files={campo: ("x.txt", b"ver_painel", "text/plain")},
                 follow_redirects=False)
    assert r.status_code == 400 and _erros(r.text) == [INCOMPLETO] and _perms(contas_db, "Leitor") == LEITOR


@pytest.mark.parametrize("campo", ["versao", "justificativa"])
def test_arquivo_no_lugar_de_versao_ou_justificativa_vale_vazio(adm, campo):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    dados = {"csrf": _csrf(cli, "/admin/grupos"), "exibida": TODAS, "marcada": sorted(LEITOR | {"ver_chamadas"}), "confirmo": "1",
             "versao": A.versao_permissoes({l: LEITOR}), "justificativa": "Apoio"}
    del dados[campo]
    r = cli.post(f"/admin/grupos/{l}/permissoes", data=dados, files={campo: ("x.txt", b"conteudo", "text/plain")},
                 follow_redirects=False)
    if campo == "versao":
        assert r.status_code == 409
    else:
        assert r.status_code == 400 and _erros(r.text) == [JUSTIFICAR]
    assert _perms(contas_db, "Leitor") == LEITOR


@pytest.mark.parametrize("campo", ["marcada", "exibida"])
def test_revisao_com_arquivo_no_lugar_de_permissao(adm, campo):
    """A revisao sempre responde 200: mostra a recusa estrutural e nao oferece confirmar."""
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    dados = {"csrf": _csrf(cli, "/admin/grupos"), "versao": "v", "exibida": TODAS if campo == "marcada" else [],
             "marcada": sorted(LEITOR) if campo == "exibida" else []}
    r = cli.post(f"/admin/grupos/{l}/revisar", data=dados, files={campo: ("x.txt", b"ver_painel", "text/plain")},
                 follow_redirects=False)
    assert r.status_code == 200 and _erros(r.text) == [INCOMPLETO] and f'action="/admin/grupos/{l}/permissoes"' not in r.text


def test_revisao_com_arquivo_na_versao_e_na_justificativa_vale_vazio(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    dados = {"csrf": _csrf(cli, "/admin/grupos"), "exibida": TODAS, "marcada": sorted(LEITOR | {"triar_artigos"})}
    r = cli.post(f"/admin/grupos/{l}/revisar", data=dados,
                 files=[("versao", ("v.txt", b"abc", "text/plain")), ("justificativa", ("j.txt", b"texto", "text/plain"))],
                 follow_redirects=False)
    assert r.status_code == 200
    assert [v for k, v in _form(r.text, f"/admin/grupos/{l}/permissoes") if k == "versao"] == [""]
    assert '<textarea id="justificativa" name="justificativa" maxlength="500"></textarea>' in r.text


@pytest.mark.parametrize("rota", ["revisar", "permissoes"])
@pytest.mark.parametrize("caminho", ["999999", "abc"])
def test_csrf_conferido_antes_do_grupo(adm, rota, caminho):
    r = _post(adm[0], f"/admin/grupos/{caminho}/{rota}", [("versao", "x")])
    assert r.status_code == 403


def test_gravar_sem_csrf_e_recusado(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    pares = [(k, v) for k, v in _form(_revisar(cli, l, sorted(LEITOR | {"triar_artigos"})).text, f"/admin/grupos/{l}/permissoes")
             if k != "csrf"]
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares)
    assert r.status_code == 403 and _perms(contas_db, "Leitor") == LEITOR


@pytest.mark.parametrize("caminho,status", [("999999", 404), ("abc", 404)])
def test_gravar_em_grupo_inexistente(adm, caminho, status):
    cli = adm[0]
    r = _post(cli, f"/admin/grupos/{caminho}/permissoes", [("csrf", _csrf(cli, "/admin/grupos")), ("versao", "x")])
    assert r.status_code == status


def test_rota_chama_o_adaptador_com_o_formulario(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    chamadas = []

    def espiao(self, gid, marcadas, exibidas, versao, confirmado, justificativa, auditoria):
        chamadas.append((gid, marcadas, exibidas, versao, confirmado, justificativa, auditoria[0]))
        quando.append(auditoria[1])
        return {"concedidas": [], "retiradas": []}
    quando = []
    monkeypatch.setattr(type(contas), "definir_permissoes_do_grupo", espiao)
    pares = [("csrf", _csrf(cli, "/admin/grupos")), ("versao", "v1"), ("versao", "v2"), ("exibida", "b"), ("exibida", "a"),
             ("marcada", "a"), ("marcada", "c"), ("marcada", "a"), ("confirmo", "on"), ("confirmo", "1"),
             ("justificativa", "  j  "), ("justificativa", "outra")]
    antes = datetime.now(timezone.utc)
    r = _post(cli, f"/admin/grupos/{l}/permissoes", pares)
    assert r.status_code == 303 and chamadas == [(l, ["a", "c", "a"], ["b", "a"], "v1", True, "  j  ", "chefe")]
    t = datetime.fromisoformat(quando[0])
    assert t.utcoffset() == timedelta(0) and antes <= t <= datetime.now(timezone.utc)


def test_banco_de_contas_ocupado(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    h = _revisar(cli, l, sorted(LEITOR | {"triar_artigos"})).text

    def ocupado(*a, **k):
        raise A.ContasOcupadas("travado")
    monkeypatch.setattr(type(contas), "definir_permissoes_do_grupo", ocupado)
    r = _post(cli, f"/admin/grupos/{l}/permissoes", _form(h, f"/admin/grupos/{l}/permissoes") + [("justificativa", "")])
    assert r.status_code == 503 and "O banco de contas está ocupado." in r.text and "travado" not in r.text


@pytest.mark.parametrize("rota", ["editar", "revisar", "permissoes"])
def test_banco_ocupado_ao_achar_o_grupo(adm, monkeypatch, rota):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    csrf = _csrf(cli, "/admin/grupos")

    def ocupado(*a, **k):
        raise A.ContasOcupadas("travado")
    monkeypatch.setattr(type(contas), "grupos", ocupado)
    r = cli.get(f"/admin/grupos/{l}/editar") if rota == "editar" else _post(cli, f"/admin/grupos/{l}/{rota}", [("csrf", csrf)])
    assert r.status_code == 503 and "O banco de contas está ocupado." in r.text and "travado" not in r.text


@pytest.mark.parametrize("rota", ["editar", "revisar", "permissoes"])
@pytest.mark.parametrize("caminho", ["999999", "abc"])
def test_banco_ocupado_vem_antes_do_id(adm, monkeypatch, rota, caminho):
    cli, contas, _, _ = adm
    csrf = _csrf(cli, "/admin/grupos")

    def ocupado(*a, **k):
        raise A.ContasOcupadas("travado")
    monkeypatch.setattr(type(contas), "grupos", ocupado)
    r = (cli.get(f"/admin/grupos/{caminho}/editar") if rota == "editar"
         else _post(cli, f"/admin/grupos/{caminho}/{rota}", [("csrf", csrf)]))
    assert r.status_code == 503 and "O banco de contas está ocupado." in r.text


@pytest.mark.parametrize("caso", ["revisao", "recusa"])
def test_banco_ocupado_ao_contar_usuarios(adm, monkeypatch, caso):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    marcadas = sorted(LEITOR | {"ver_chamadas"})
    pares = _form(_revisar(cli, l, marcadas).text, f"/admin/grupos/{l}/permissoes")

    def ocupado(*a, **k):
        raise A.ContasOcupadas("travado")
    monkeypatch.setattr(type(contas), "listar_usuarios", ocupado)
    if caso == "revisao":
        r = _revisar(cli, l, marcadas)
    else:
        r = _post(cli, f"/admin/grupos/{l}/permissoes", pares + [("justificativa", "")])
    assert r.status_code == 503 and "O banco de contas está ocupado." in r.text and _perms(contas_db, "Leitor") == LEITOR


# ======================== matriz so de leitura ========================
def test_envio_antigo_da_matriz_nao_existe_mais(adm):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    antes = {g["nome"]: set(g["permissoes"]) for g in contas.grupos()}
    r = cli.post("/admin/grupos", data={"csrf": _csrf(cli, "/admin/grupos"), "grupos": str(l), "versao": "x",
                                        f"p-{l}-triar_artigos": "on"}, follow_redirects=False)
    assert r.status_code == 405
    assert {g["nome"]: set(g["permissoes"]) for g in contas.grupos()} == antes and _auditoria(contas_db) == []


def test_matriz_so_de_leitura(adm):
    cli, contas, contas_db, _ = adm
    h = cli.get("/admin/grupos").text
    assert '<form method="post" action="/admin/grupos">' not in h and 'type="checkbox"' not in h
    assert "Salvar permissões" not in h and "Alteração gravada." not in h and 'name="versao"' not in h
    assert "<p>Para alterar as permissões de um grupo, abra o grupo e use «Editar permissões».</p>" in h
    grupos = contas.grupos()
    for p in TODAS:
        i = h.index(f'<th scope="row">{_d(p)}</th>')
        celulas = re.findall(r"<td>([^<]*)</td>", h[i:h.index("</tr>", i)])
        esperado = ["Sim" if g["nome"] == "Administrador" else
                    "Não permitida" if g["nome"] == "Visitante" and p in A.PERMISSOES_PROIBIDAS_VISITANTE else
                    "Sim" if p in g["permissoes"] else "Não" for g in grupos]
        assert celulas == esperado, p


def test_matriz_mantem_os_formularios_de_grupo(adm):
    cli, _, contas_db, _ = adm
    h = cli.get("/admin/grupos").text
    assert '<form method="post" action="/admin/grupos/novo" class="form-admin">' in h


# ======================== auditoria ========================
def _detalhe(**k):
    d = {"antes": ["ver_painel"], "depois": ["triar_artigos", "ver_painel"], "concedidas": ["triar_artigos"], "retiradas": [],
         "justificativa": "Bolsista", "origem": "edicao"}
    d.update(k)
    return json.dumps(d, ensure_ascii=False)


@pytest.mark.parametrize("texto,esperado", [
    (_detalhe(), "Concedidas: triar_artigos. Retiradas: nenhuma. Justificativa: Bolsista"),
    (_detalhe(justificativa=""), "Concedidas: triar_artigos. Retiradas: nenhuma."),
    (_detalhe(concedidas=[], retiradas=["ver_custos", "ver_chamadas"]), "Concedidas: nenhuma. Retiradas: ver_custos, ver_chamadas. "
                                                                         "Justificativa: Bolsista"),
    (_detalhe(origem="referencia:Leitor"), "Concedidas: triar_artigos. Retiradas: nenhuma. Justificativa: Bolsista"),
    (None, None), ("", None), ("+ver_painel, -ver_custos", None), ("antes: ver_painel; depois: ver_custos, ver_painel", None),
    ("[1, 2]", None), ('"texto"', None), ("{", None), ("null", None),
    (json.dumps({"concedidas": [], "retiradas": []}), None),
    (_detalhe()[:-1] + ', "extra": 1}', None),
    (_detalhe(concedidas="triar_artigos"), None), (_detalhe(retiradas=[1]), None), (_detalhe(justificativa=None), None),
    (_detalhe(concedidas=[None]), None), (_detalhe(origem=7), None), (_detalhe(antes="x"), None),
    (_detalhe(antes=[1]), None), (_detalhe(depois="x"), None), (_detalhe(depois=[None]), None), (_detalhe(retiradas="x"), None),
    ("[" * 100000 + "]" * 100000, None), (b"{}", None),
], ids=["completo", "sem-justificativa", "so-retiradas", "outra-origem", "none", "vazio", "texto-antigo", "texto-comando",
        "lista", "string", "quebrado", "null", "chaves-faltando", "chave-a-mais", "concedidas-texto", "retirada-numero",
        "justificativa-null", "concedida-null", "origem-numero", "antes-texto", "antes-numero", "depois-texto",
        "depois-null", "retiradas-texto", "aninhado-demais", "bytes"])
def test_resumo_do_detalhe(texto, esperado):
    assert A.resumo_detalhe_auditoria(texto) == esperado


def test_auditoria_mostra_o_resumo_e_mantem_o_antigo(adm):
    cli, contas, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    _gravar(cli, l, sorted(LEITOR | {"triar_artigos"}), justificativa="<script>x</script>")
    contas.auditar("chefe", "salvar_permissoes", "Revisor", "+ver_painel, -ver_custos", "2026-10-28T00:00:00+00:00")
    contas.auditar("chefe", "salvar_permissoes", "Bolsistas", "{quebrado", "2026-10-28T00:00:01+00:00")
    contas.auditar("chefe", "criar_grupo", "X", _detalhe(), "2026-10-28T00:00:02+00:00")
    h = cli.get("/admin/auditoria").text
    assert "<td>Concedidas: triar_artigos. Retiradas: nenhuma. Justificativa: &lt;script&gt;x&lt;/script&gt;</td>" in h
    assert "<td>+ver_painel, -ver_custos</td>" in h and "<td>{quebrado</td>" in h
    assert "&#34;antes&#34;" in h                                    # JSON de outra acao aparece como esta, escapado
    assert "<script>x</script>" not in h


# ======================== regras de rota ========================
def test_rotas_novas_so_do_administrador():
    for metodo, caminho in (("GET", "/admin/grupos/5/editar"), ("POST", "/admin/grupos/5/revisar"),
                            ("POST", "/admin/grupos/5/permissoes")):
        assert A.regra_explicita(metodo, caminho)[2] == A.SO_ADMIN
    assert A.regra_explicita("POST", "/admin/grupos") is None


# ======================== retrabalho: valor gravado invalido e resolvedor unico ========================
INVALIDA = "As permissões gravadas deste grupo têm um valor inválido. Nada foi alterado."


def _blob_no_leitor(contas_db):
    with sqlite3.connect(contas_db) as conn:
        conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES ((SELECT grupo_id FROM grupos WHERE nome = 'Leitor'), ?)",
                     (b"ver_painel",))


@pytest.mark.parametrize("rota", ["editar", "revisar", "permissoes"])
def test_permissao_gravada_invalida_recusa_as_rotas_de_edicao(adm, rota):
    """Um BLOB gravado (o SQLite aceita qualquer tipo) recusa a edicao com 409 e o texto da F119, sem quebrar a pagina."""
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    csrf = _csrf(cli, "/admin/grupos")
    _blob_no_leitor(contas_db)
    if rota == "editar":
        r = cli.get(f"/admin/grupos/{l}/editar")
    else:
        r = _post(cli, f"/admin/grupos/{l}/{rota}", [("csrf", csrf), ("versao", "x")] + [("exibida", p) for p in TODAS] +
                  [("marcada", p) for p in sorted(LEITOR)] + [("justificativa", "")])
    assert r.status_code == 409 and "Permissões gravadas inválidas" in r.text and INVALIDA in r.text
    assert _auditoria(contas_db) == []


def test_permissao_gravada_invalida_nao_quebra_a_pagina_de_leitura(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    _blob_no_leitor(contas_db)
    r = cli.get(f"/admin/grupos/{l}")
    assert r.status_code == 200 and "<h1>Leitor</h1>" in r.text


def test_permissao_invalida_depois_do_csrf_e_do_id(adm):
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    _blob_no_leitor(contas_db)
    assert _post(cli, f"/admin/grupos/{l}/permissoes", [("versao", "x")]).status_code == 403


@pytest.mark.parametrize("rota", ["grupo", "editar", "revisar", "permissoes"])
def test_todas_as_rotas_usam_o_resolvedor_unico(adm, monkeypatch, rota):
    """A pagina do grupo e as tres rotas de edicao resolvem o grupo pela mesma funcao do modulo (nenhuma copia)."""
    from fastapi.responses import PlainTextResponse
    from painel.rotas_extras import admin
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    csrf = _csrf(cli, "/admin/grupos")
    chamadas = []

    def falso(c, request, grupo_id, edicao=False):
        chamadas.append((grupo_id, edicao))
        return None, PlainTextResponse("resolvedor trocado", status_code=418)
    monkeypatch.setattr(admin, "_resolver_grupo", falso)
    if rota == "grupo":
        r = cli.get(f"/admin/grupos/{l}")
    elif rota == "editar":
        r = cli.get(f"/admin/grupos/{l}/editar")
    else:
        r = _post(cli, f"/admin/grupos/{l}/{rota}", [("csrf", csrf)])
    assert r.status_code == 418 and r.text == "resolvedor trocado"
    assert chamadas == [(str(l), rota != "grupo")]


def test_contagem_de_ativos_tem_uma_funcao_so(adm, monkeypatch):
    from painel.rotas_extras import admin
    cli, _, contas_db, _ = adm
    l = _gid(contas_db, "Leitor")
    monkeypatch.setattr(admin, "_usuarios_ativos", lambda c, gid: 7 if gid == l else 0)
    assert "7 usuários ativos" in cli.get(f"/admin/grupos/{l}").text
    h = _revisar(cli, l, sorted(LEITOR | {"triar_artigos"})).text
    assert '<p class="perm-efeito">Efeito imediato: vale a partir do próximo pedido dos 7 usuários ativos deste grupo.</p>' in h
