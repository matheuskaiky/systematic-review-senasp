"""RB17 (D78, decisao 6): sugestoes sobre uma decisao ja tomada. Quem nao e o autor sugere outro valor com um motivo; o autor ou um
administrador aceita (vira uma decisao nova de quem aceita) ou descarta. Aqui fica o nucleo: validacao, tabela, repositorio e leitura."""
import logging
import sqlite3

import pytest

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from config import vocabulario as V
from dados_metricas import construir_academico, construir_classificacao_mista


class _Preguicoso:
    """Importa o modulo so no uso (a falta do modulo vira falha de cada teste, nao erro de coleta)."""
    def __init__(self, nome):
        self._nome = nome

    def __getattr__(self, attr):
        import importlib
        return getattr(importlib.import_module(self._nome), attr)


sugestoes = _Preguicoso("aplicacao.sugestoes")


def validar_sugestao(*args):
    from dominio.sugestoes import validar_sugestao as v
    return v(*args)

PERMITIDOS = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
MOTIVO_EXCLUIR = "Informe o motivo da exclusão: ele entra nos motivos de exclusão do PRISMA"


# ====================== validacao (dominio) ======================
@pytest.mark.parametrize("alvo,valor,motivo,esperado", [
    ("achado", "em_uso", "", ("em_uso", "")),
    ("achado", " Em_Uso ", " veja a página 2 ", ("em_uso", " veja a página 2 ")),
    ("achado", "", "", "Escolha o valor sugerido."),
    ("achado", "   ", "", "Escolha o valor sugerido."),
    ("achado", None, "", "Escolha o valor sugerido."),
    ("achado", "foo", "", "Valor sugerido inválido para o achado: 'foo'."),
    ("artigo", "incluir", "", ("incluir", "")),
    ("artigo", " EXCLUIR ", "fora do tema", ("excluir", "fora do tema")),
    ("artigo", "pendente", "", "Valor sugerido inválido para o artigo: 'pendente'."),
    ("artigo", "excluir", "   ", MOTIVO_EXCLUIR),
    ("artigo", "excluir", None, MOTIVO_EXCLUIR),
    ("outro", "incluir", "", "Tipo de item inválido: 'outro'."),
    ("achado", "em_uso", "x" * 2000, ("em_uso", "x" * 2000)),
    ("achado", "em_uso", "x" * 2001, "O motivo passa de 2000 caracteres."),
    ("artigo", "", "x" * 2001, "Escolha o valor sugerido."),
    ("artigo", "excluir", "x" * 2001, "O motivo passa de 2000 caracteres."),
    ("outro", "", "", "Tipo de item inválido: 'outro'."),
])
def test_validar_sugestao_tabela(alvo, valor, motivo, esperado):
    if isinstance(esperado, tuple):
        assert validar_sugestao(alvo, valor, motivo, PERMITIDOS) == esperado
    else:
        with pytest.raises(ValueError) as e:
            validar_sugestao(alvo, valor, motivo, PERMITIDOS)
        assert str(e.value) == esperado


# ====================== achados ======================
@pytest.fixture
def achados(tmp_path):
    logging.disable(logging.CRITICAL)
    repo, _ = construir_classificacao_mista(tmp_path)
    a = repo.conn.execute("SELECT MIN(achado_id) FROM achados").fetchone()[0]
    assert a is not None
    repo.verificar_achado(a, "em_uso", "Ana", "ok", PERMITIDOS)
    yield repo, tmp_path / "cl.db", a
    logging.disable(logging.NOTSET)


def _ficha(repo, tipo, i):
    """A ficha que a pagina mostraria (leitura do banco do proprio repositorio)."""
    caminho = repo.conn.execute("PRAGMA database_list").fetchone()[2]
    return LeituraPainelSQLite(caminho).estado_decisao(tipo, i)


def _versao_achado(repo, a):
    return _ficha(repo, "achado", a)


def _sug(repo, sid):
    return dict(repo.conn.execute("SELECT * FROM sugestoes WHERE sugestao_id=?", (sid,)).fetchone())


def test_criar_sugestao_de_achado(achados):
    repo, _, a = achados
    v = _versao_achado(repo, a)
    sid = sugestoes.criar(repo, "achado", a, "descartado", "não é IA", "Bia", v, PERMITIDOS)
    s = _sug(repo, sid)
    assert (s["alvo_tipo"], s["alvo_id"], s["valor"], s["motivo"], s["autor"], s["autor_chave"], s["estado_alvo"], s["valor_alvo"],
            s["situacao"]) == ("achado", a, "descartado", "não é IA", "Bia", "bia", v, "em_uso", "aberta")
    assert s["criado_em"] and s["resolvido_por"] is None and s["resolvido_em"] is None


@pytest.mark.parametrize("caso,esperado", [
    ("autor_vazio", "Informe o nome do revisor"),
    ("inexistente", "Achado inexistente: 999999"),
    ("versao", "A decisão deste item mudou depois que a página foi aberta: recarregue a página antes de sugerir"),
    ("nao_decidido", "Só se sugere sobre um item já decidido."),
    ("autor_da_decisao", "Quem tomou a decisão não sugere: decida de novo."),
    ("autor_da_decisao_maiusculas", "Quem tomou a decisão não sugere: decida de novo."),
    ("repetida_maiusculas", "Você já sugeriu este valor para este item."),
    ("versao_vazia", "A decisão deste item mudou depois que a página foi aberta: recarregue a página antes de sugerir"),
    ("id_texto", "Achado inexistente: '1'"),
    ("id_bool", "Achado inexistente: True"),
    ("id_zero", "Achado inexistente: 0"),
    ("id_enorme", "Achado inexistente: 9223372036854775808"),
    ("id_none", "Achado inexistente: None"),
    ("autor_vazio_e_valor_invalido", "Valor sugerido inválido para o achado: 'foo'."),
    ("igual", "O valor sugerido é igual à decisão atual."),
    ("repetida", "Você já sugeriu este valor para este item."),
    ("valor_invalido", "Valor sugerido inválido para o achado: 'foo'."),
])
def test_criar_sugestao_de_achado_recusas(achados, caso, esperado):
    repo, _, a = achados
    v = _versao_achado(repo, a)
    outro = repo.conn.execute("SELECT MIN(achado_id) FROM achados WHERE verificado=0 AND achado_id<>?", (a,)).fetchone()[0]
    assert outro is not None
    args = {"alvo_id": a, "valor": "descartado", "autor": "Bia", "versao": v}
    if caso == "autor_vazio":
        args["autor"] = "   "
    elif caso == "inexistente":
        args["alvo_id"] = 999999
    elif caso == "versao":
        args["versao"] = "ficha-antiga"
    elif caso == "nao_decidido":
        args.update(alvo_id=outro, versao=_versao_achado(repo, outro))
    elif caso == "autor_da_decisao":
        args["autor"] = " Ana "
    elif caso == "autor_da_decisao_maiusculas":
        args["autor"] = "ANA"
    elif caso == "repetida_maiusculas":
        sugestoes.criar(repo, "achado", a, "descartado", "", "Érica", v, PERMITIDOS)
        args["autor"] = "érica"
    elif caso == "versao_vazia":
        args["versao"] = ""
    elif caso == "id_texto":
        args["alvo_id"] = "1"
    elif caso == "id_bool":
        args["alvo_id"] = True
    elif caso == "id_zero":
        args["alvo_id"] = 0
    elif caso == "id_enorme":
        args["alvo_id"] = 2 ** 63
    elif caso == "id_none":
        args["alvo_id"] = None
    elif caso == "autor_vazio_e_valor_invalido":
        args.update(autor="", valor="foo")
    elif caso == "igual":
        args["valor"] = "em_uso"
    elif caso == "repetida":
        sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", v, PERMITIDOS)
    elif caso == "valor_invalido":
        args["valor"] = "foo"
    antes = repo.conn.execute("SELECT COUNT(*) FROM sugestoes").fetchone()[0]
    with pytest.raises(SystemExit) as e:
        sugestoes.criar(repo, "achado", args["alvo_id"], args["valor"], "", args["autor"], args["versao"], PERMITIDOS)
    assert str(e.value) == esperado
    assert repo.conn.execute("SELECT COUNT(*) FROM sugestoes").fetchone()[0] == antes
    assert not repo.conn.in_transaction


def test_aceitar_aplica_a_decisao_de_quem_aceita(achados):
    repo, _, a = achados
    sid = sugestoes.criar(repo, "achado", a, "descartado", "não é IA", "Bia", _versao_achado(repo, a), PERMITIDOS)
    n_hist = repo.conn.execute("SELECT COUNT(*) FROM achados_revisoes WHERE achado_id=?", (a,)).fetchone()[0]
    sugestoes.aceitar(repo, sid, "Ana", PERMITIDOS)
    est = repo.conn.execute("SELECT status_final, verificado_por, observacao FROM achados WHERE achado_id=?", (a,)).fetchone()
    assert tuple(est) == ("descartado", "Ana", "não é IA")
    s = _sug(repo, sid)
    assert (s["situacao"], s["resolvido_por"]) == ("aceita", "Ana") and s["resolvido_em"]
    assert repo.conn.execute("SELECT COUNT(*) FROM achados_revisoes WHERE achado_id=?", (a,)).fetchone()[0] == n_hist + 1


def test_aceitar_descarta_as_outras_e_motivo_vazio_mantem_a_observacao(achados):
    repo, _, a = achados
    v = _versao_achado(repo, a)
    s1 = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", v, PERMITIDOS)
    s2 = sugestoes.criar(repo, "achado", a, "piloto", "outra", "Caio", v, PERMITIDOS)
    sugestoes.aceitar(repo, s1, "Ana", PERMITIDOS)
    assert repo.conn.execute("SELECT observacao FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == "ok"
    assert (_sug(repo, s2)["situacao"], _sug(repo, s2)["resolvido_por"]) == ("descartada", "Ana")


def test_quem_sugeriu_nao_aceita_mas_pode_descartar(achados):
    repo, _, a = achados
    sid = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", _versao_achado(repo, a), PERMITIDOS)
    with pytest.raises(SystemExit) as e:
        sugestoes.aceitar(repo, sid, " BIA ", PERMITIDOS)
    assert str(e.value) == "Quem sugeriu não aceita a própria sugestão."
    assert _sug(repo, sid)["situacao"] == "aberta"
    sugestoes.descartar(repo, sid, "Bia")
    assert _sug(repo, sid)["situacao"] == "descartada"


def test_aceitar_quando_a_gravacao_falha_deixa_a_sugestao_aberta(achados):
    repo, _, a = achados
    sid = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", _versao_achado(repo, a), PERMITIDOS)
    with pytest.raises(SystemExit):
        sugestoes.aceitar(repo, sid, "Ana", set(V.STATUS))          # "descartado" fora dos permitidos desta chamada
    assert _sug(repo, sid)["situacao"] == "aberta" and not repo.conn.in_transaction


VENCIDA = "Esta sugestão foi feita sobre uma decisão que já mudou: descarte-a ou sugira de novo."


def _mesmo_segundo(repo, tabela, coluna_id, i, coluna_tempo, quando):
    repo.conn.execute(f"UPDATE {tabela} SET {coluna_tempo}=? WHERE {coluna_id}=?", (quando, i))
    repo.conn.commit()


def test_sugestao_vencida_e_recusada_mesmo_no_mesmo_segundo(achados):
    repo, _, a = achados
    v = _versao_achado(repo, a)
    t0 = repo.conn.execute("SELECT verificado_em FROM achados WHERE achado_id=?", (a,)).fetchone()[0]
    s1 = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", v, PERMITIDOS)
    repo.verificar_achado(a, "piloto", "Caio", "outra leitura", PERMITIDOS)
    _mesmo_segundo(repo, "achados", "achado_id", a, "verificado_em", t0)                      # mesmo segundo da decisao vista
    with pytest.raises(SystemExit) as e:
        sugestoes.aceitar(repo, s1, "Ana", PERMITIDOS)
    assert str(e.value) == VENCIDA
    assert _sug(repo, s1)["situacao"] == "aberta" and not repo.conn.in_transaction
    assert repo.conn.execute("SELECT status_final FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == "piloto"
    with pytest.raises(SystemExit) as e:                                                       # a ficha antiga nao serve para sugerir
        sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", v, PERMITIDOS)
    assert str(e.value).startswith("A decisão deste item mudou")
    s2 = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", _versao_achado(repo, a), PERMITIDOS)   # a nova ficha serve
    sugestoes.descartar(repo, s1, "Ana")                                                       # a vencida pode ser descartada
    assert _sug(repo, s1)["situacao"] == "descartada" and _sug(repo, s2)["situacao"] == "aberta"


def test_mesmo_valor_com_outro_motivo_no_mesmo_segundo_tambem_vence(artigos):
    repo, art = artigos
    t0 = repo.conn.execute("SELECT revisado_em FROM triagem WHERE artigo_id=?", (art,)).fetchone()[0]
    sid = sugestoes.criar(repo, "artigo", art, "excluir", "fora do tema", "Bia", _versao_artigo(repo, art), PERMITIDOS)
    repo.registrar_triagem(art, "incluir", "Caio", "relevante", "ACM", "https://exemplo.org/b")
    _mesmo_segundo(repo, "triagem", "artigo_id", art, "revisado_em", t0)
    with pytest.raises(SystemExit) as e:
        sugestoes.aceitar(repo, sid, "Ana", PERMITIDOS)
    assert str(e.value) == VENCIDA


def test_ficha_muda_com_qualquer_campo():
    from dominio.sugestoes import chave_autor, ficha_da_decisao
    base = (1, "em_uso", "Ana", "2026-10-19T00:00:00+00:00", "ok")
    assert ficha_da_decisao(base) == ficha_da_decisao(list(base))
    for k in range(len(base)):
        outro = list(base)
        outro[k] = "x" if base[k] != "x" else "y"
        assert ficha_da_decisao(outro) != ficha_da_decisao(base), k
    assert chave_autor(" Érica ") == chave_autor("ÉRICA") == chave_autor("e\u0301rica") == "érica"


def test_recusa_antes_do_banco_desfaz_a_transacao_do_chamador(achados):
    repo, _, a = achados
    repo.conn.execute("BEGIN IMMEDIATE")
    repo.conn.execute("UPDATE achados SET observacao='pendente' WHERE achado_id=?", (a,))
    with pytest.raises(SystemExit) as e:
        sugestoes.criar(repo, "achado", True, "descartado", "", "Bia", "x", PERMITIDOS)
    assert str(e.value) == "Achado inexistente: True"
    assert not repo.conn.in_transaction
    assert repo.conn.execute("SELECT observacao FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == "ok"


@pytest.mark.parametrize("acao", ["aceitar", "descartar"])
def test_resolver_duas_vezes_inexistente_e_sem_revisor(achados, acao):
    repo, _, a = achados
    sid = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", _versao_achado(repo, a), PERMITIDOS)
    resolver = (lambda s, r: sugestoes.aceitar(repo, s, r, PERMITIDOS)) if acao == "aceitar" else \
        (lambda s, r: sugestoes.descartar(repo, s, r))
    for sid_ruim, revisor, msg in ((999999, "Ana", "Sugestão inexistente: 999999"), (sid, "  ", "Informe o nome do revisor")):
        with pytest.raises(SystemExit) as e:
            resolver(sid_ruim, revisor)
        assert str(e.value) == msg
    resolver(sid, "Ana")
    with pytest.raises(SystemExit) as e:
        resolver(sid, "Ana")
    assert str(e.value) == "Esta sugestão já foi resolvida."


def test_descartar_nao_muda_a_decisao(achados):
    repo, _, a = achados
    sid = sugestoes.criar(repo, "achado", a, "descartado", "", "Bia", _versao_achado(repo, a), PERMITIDOS)
    sugestoes.descartar(repo, sid, "Chefe")
    s = _sug(repo, sid)
    assert (s["situacao"], s["resolvido_por"]) == ("descartada", "Chefe") and s["resolvido_em"]
    assert repo.conn.execute("SELECT status_final FROM achados WHERE achado_id=?", (a,)).fetchone()[0] == "em_uso"


def test_leitura_lista_so_as_abertas_em_ordem(achados):
    repo, caminho, a = achados
    v = _versao_achado(repo, a)
    s1 = sugestoes.criar(repo, "achado", a, "descartado", "m1", "Bia", v, PERMITIDOS)
    s2 = sugestoes.criar(repo, "achado", a, "piloto", "m2", "Caio", v, PERMITIDOS)
    s3 = sugestoes.criar(repo, "achado", a, "piloto", "", "Bia", v, PERMITIDOS)
    sugestoes.descartar(repo, s2, "Ana")
    leitura = LeituraPainelSQLite(caminho)
    abertas = leitura.sugestoes_abertas("achado", a)
    assert [x["sugestao_id"] for x in abertas] == [s1, s3]
    assert set(abertas[0]) == {"sugestao_id", "valor", "motivo", "autor", "criado_em", "estado_alvo", "valor_alvo"}
    assert (abertas[0]["estado_alvo"], abertas[0]["valor_alvo"]) == (v, "em_uso")
    assert leitura.sugestoes_abertas("achado", a + 100000) == []
    s = leitura.sugestao(s1)
    assert (s["alvo_tipo"], s["alvo_id"], s["situacao"], s["autor"]) == ("achado", a, "aberta", "Bia")
    assert leitura.sugestao(999999) is None
    repo.conn.execute("DROP TABLE sugestoes")                    # banco antigo, aberto so para leitura
    repo.conn.commit()
    assert leitura.sugestoes_abertas("achado", a) == [] and leitura.sugestao(s1) is None


def test_portas_declaram_os_metodos():
    from dominio import portas
    for nome in ("criar_sugestao", "aceitar_sugestao", "descartar_sugestao"):
        assert hasattr(portas.Repositorio, nome), nome
    for nome in ("sugestoes_abertas", "sugestao", "estado_decisao"):
        assert hasattr(portas.LeituraPainel, nome), nome


def test_tabela_recusa_valores_fora_do_dominio(achados):
    repo, _, a = achados
    for coluna, valor in (("alvo_tipo", "web"), ("situacao", "pendente")):
        campos = {"alvo_tipo": "achado", "alvo_id": a, "valor": "x", "motivo": "", "autor": "Bia", "autor_chave": "bia", "estado_alvo": "v",
                  "valor_alvo": "em_uso",
                  "criado_em": "2026-10-19T00:00:00+00:00", "situacao": "aberta"}
        campos[coluna] = valor
        with pytest.raises(sqlite3.IntegrityError):
            repo.conn.execute(f"INSERT INTO sugestoes ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
                              tuple(campos.values()))
        repo.conn.rollback()


# ====================== artigos ======================
@pytest.fixture
def artigos(tmp_path):
    repo, _ = construir_academico(tmp_path / "a.db")
    art = repo.conn.execute("SELECT MIN(artigo_id) FROM artigos").fetchone()[0]
    assert art is not None
    repo.registrar_triagem(art, "incluir", "Ana", None, "IEEE", "https://exemplo.org/a")
    return repo, art


def _versao_artigo(repo, art):
    return _ficha(repo, "artigo", art)


def test_artigo_sugerir_excluir_e_aceitar_mantem_base_e_link(artigos):
    repo, art = artigos
    sid = sugestoes.criar(repo, "artigo", art, "excluir", "fora do tema", "Bia", _versao_artigo(repo, art), PERMITIDOS)
    sugestoes.aceitar(repo, sid, "Ana", PERMITIDOS)
    t = repo.conn.execute("SELECT decisao, motivo, revisor, confirmado_em_base, link_confirmado FROM triagem WHERE artigo_id=?",
                          (art,)).fetchone()
    assert tuple(t) == ("excluir", "fora do tema", "Ana", "IEEE", "https://exemplo.org/a")
    assert _sug(repo, sid)["situacao"] == "aceita"


def test_artigo_aceitar_incluir_com_motivo_vazio(artigos):
    repo, art = artigos
    repo.registrar_triagem(art, "excluir", "Ana", "fora do tema", "IEEE", "https://exemplo.org/a")
    sid = sugestoes.criar(repo, "artigo", art, "incluir", "", "Bia", _versao_artigo(repo, art), PERMITIDOS)
    sugestoes.aceitar(repo, sid, "Ana", PERMITIDOS)
    t = repo.conn.execute("SELECT decisao, motivo, revisor FROM triagem WHERE artigo_id=?", (art,)).fetchone()
    assert tuple(t) == ("incluir", None, "Ana")


@pytest.mark.parametrize("caso,esperado", [
    ("inexistente", "Artigo inexistente: 999999"),
    ("nao_decidido", "Só se sugere sobre um item já decidido."),
    ("pendente", "Só se sugere sobre um item já decidido."),
    ("igual", "O valor sugerido é igual à decisão atual."),
    ("excluir_sem_motivo", MOTIVO_EXCLUIR),
    ("texto_completo", "Este artigo já tem decisão de texto completo: as sugestões valem só para a triagem por título e resumo."),
])
def test_artigo_recusas(artigos, caso, esperado):
    repo, art = artigos
    outro = repo.conn.execute("SELECT MIN(artigo_id) FROM artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM triagem)").fetchone()[0]
    assert outro is not None
    alvo, valor, motivo, versao = art, "excluir", "fora do tema", _versao_artigo(repo, art)
    if caso == "inexistente":
        alvo = 999999
    elif caso == "nao_decidido":
        alvo, versao = outro, _versao_artigo(repo, outro)
    elif caso == "pendente":
        repo.registrar_triagem(outro, "pendente", "Ana")
        alvo, versao = outro, _versao_artigo(repo, outro)
    elif caso == "igual":
        valor = "incluir"
    elif caso == "excluir_sem_motivo":
        motivo = " "
    elif caso == "texto_completo":
        repo.registrar_triagem(art, "incluir", "Ana", None, "IEEE", "https://exemplo.org/a", "texto_completo")
        versao = _versao_artigo(repo, art)
    with pytest.raises(SystemExit) as e:
        sugestoes.criar(repo, "artigo", alvo, valor, motivo, "Bia", versao, PERMITIDOS)
    assert str(e.value) == esperado
