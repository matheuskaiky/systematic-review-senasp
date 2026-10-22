"""Triagem da busca de viés algorítmico (banco `vies`): o prompt no escopo combinado para essa busca, a conferência da
resposta (relevância, tipo de fonte com sufixo, país/escopo, tópicos por extenso, eixo), as referências da web como itens,
a gravação e o comando `triar-escopo --banco vies`."""
import json
import logging
import unicodedata
import sqlite3
import sys

import pytest

import main
import config.settings as S
from adaptadores import triador_gemini
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_academica, busca_literatura, triagem_escopo
from config import consultas as C, triagem_escopo as TE
from config.eixos_tematicos import EIXOS_EXPLORACAO
from dominio import triagem_escopo as DT
from dominio.modelos import (ArtigoAcademico, FiltrosAcademicos, FiltrosBusca, PaginaAcademica, RegistroChamada,
                             RespostaBusca, ResultadoTriagemLote, ResultadoWeb)
from infra.util import agora

CFG = TE.config_vies(EIXOS_EXPLORACAO)
MAPAS = {"artigo": {t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts}, "web": {}}
PRECOS = {"entrada": 0.3, "saida": 2.5}
EIXO = next(iter(EIXOS_EXPLORACAO))


def _obj(**kw):
    o = {"id": "1", "relevancia": "alta", "confianca": "alta", "tipo_fonte": "Artigo científico", "pais_escopo": "Brasil",
         "topicos": ["Reconhecimento facial", "viés racial"], "eixo": EIXO, "justificativa": "trata de viés no policiamento"}
    o.update(kw)
    return o


def _item(**kw):
    i = {"item_id": 1, "fonte": "referencia", "uf": "", "provedor": None, "titulo": "T", "resumo": "r", "termos": ["q"],
         "autores_publicacao": "", "ano": 2024, "link": "https://e.org/a", "host": "e.org"}
    i.update(kw)
    return i


def _conferir(**kw):
    linhas, extras = DT.validar_resposta([_item()], json.dumps({"itens": [_obj(**kw)]}), CFG)
    assert extras["json_valido"]
    return linhas[0]


# ---------- configuração ----------
def test_configuracao_da_triagem_vies():
    assert (CFG.versao, CFG.vies, CFG.curta, CFG.ano_minimo, CFG.max_custo_padrao_usd) == ("v1", True, False, 0, 0.50)
    assert (CFG.lote_padrao, CFG.lote_maximo, CFG.tokens_fixos_por_chamada) == (10, 25, 2000)
    for trecho in ('answer "Indeterminado"', "1 to 5 short topics", '"conferência", "ensaio controlado"', '"query_terms" (the searches'):
        assert trecho in CFG.sistema_artigo
    assert len(CFG.tipos_fonte) == 43 and CFG.tipos_fonte[-1] == "Solução tecnológica / produto"
    assert CFG.eixos == tuple(EIXOS_EXPLORACAO) and CFG.sem_eixo == "Nenhum"
    for eixo, perguntas in EIXOS_EXPLORACAO.items():
        assert f'"{eixo}" ({perguntas})' in CFG.sistema_artigo
    assert "; ".join(TE.TIPOS_FONTE) in CFG.sistema_artigo and CFG.sistema_artigo == CFG.sistema_web
    assert "{" not in CFG.sistema_artigo.replace('{"', "")            # nenhum marcador sobrando


@pytest.mark.parametrize("tipo, rotulo", [
    ("Artigo científico", "Artigo científico"), ("Livro", "Livro"), ("TCC", "TCC"),
    ("Reportagem", "Reportagem / literatura cinzenta"), ("Relatório técnico", "Relatório técnico / literatura cinzenta"),
    ("Solução tecnológica / produto", "Solução tecnológica / produto / literatura cinzenta"),
    ("Norma", "Norma / fonte primária"), ("Documento regulatório", "Documento regulatório / fonte primária"),
    ("Regulação", "Regulação / fonte primária"),
])
def test_tipo_de_fonte_ganha_o_sufixo_do_codigo(tipo, rotulo):
    assert _conferir(tipo_fonte=tipo)["tipo_fonte"] == rotulo


def test_os_sufixos_cobrem_os_43_tipos():
    assert set(TE.SUFIXOS_TIPO_FONTE) == set(TE.TIPOS_FONTE)
    assert sum(1 for s in TE.SUFIXOS_TIPO_FONTE.values() if s == "") == 11
    assert sum(1 for s in TE.SUFIXOS_TIPO_FONTE.values() if s == " / fonte primária") == 5


# ---------- esquema e mensagem ----------
def test_esquema_da_triagem_vies():
    obj = DT.montar_esquema(CFG, ["1", "2"])["properties"]["itens"]["items"]
    assert obj["required"] == ["id", "relevancia", "confianca", "tipo_fonte", "pais_escopo", "topicos", "eixo", "justificativa"]
    assert obj["properties"]["id"]["enum"] == ["1", "2"]
    assert obj["properties"]["relevancia"]["enum"] == ["alta", "media", "baixa", "fora_do_escopo"]
    assert obj["properties"]["tipo_fonte"]["enum"] == list(TE.TIPOS_FONTE)
    assert obj["properties"]["eixo"]["enum"] == list(EIXOS_EXPLORACAO) + ["Nenhum"]
    assert obj["properties"]["topicos"]["type"] == "array"
    assert obj["properties"]["topicos"]["description"] == "1 to 5 short topics in Portuguese"     # como o prompt e o código


def test_mensagem_leva_consultas_por_extenso_e_dados_do_item():
    linha = DT.linha_do_item(_item(termos=["inteligência artificial segurança pública"], autores_publicacao="A - R, 2024"), CFG)
    assert linha == {"id": "1", "query_terms": ["inteligência artificial segurança pública"], "titulo": "T", "resumo": "r",
                     "autores_publicacao": "A - R, 2024", "ano": 2024, "url": "https://e.org/a", "host": "e.org"}
    texto = DT.montar_mensagem_usuario([_item()], CFG)
    assert texto.startswith("Screen the following 1 items (web pages found by web searches in Portuguese).")


def test_referencia_usa_os_textos_das_consultas_dos_conjuntos():
    assert DT.montar_termos({"fonte": "referencia", "termos_ids": ["LA2", "LA1", "LA2"]}, MAPAS) == [
        MAPAS["artigo"]["LA2"], MAPAS["artigo"]["LA1"]]


# ---------- conferência da resposta ----------
@pytest.mark.parametrize("relevancia, confianca, status, valido", [
    ("alta", "alta", "elegivel", True), ("media", "baixa", "elegivel", True), ("baixa", "media", "quarentena", True),
    ("fora_do_escopo", "alta", "excluido", True), ("fora_do_escopo", "media", "quarentena", True),
    (" ALTA ", "alta", "elegivel", True), ("x", "alta", "quarentena", False), (None, "alta", "quarentena", False),
    (3, "alta", "quarentena", False), ("alta", "certa", "elegivel", False),
])
def test_relevancia_vira_status(relevancia, confianca, status, valido):
    linha = _conferir(relevancia=relevancia, confianca=confianca)
    assert (linha["status"], linha["valido"]) == (status, valido)
    assert linha["categoria_motivo"] is None


@pytest.mark.parametrize("campo, valor, esperado, problema", [
    ("tipo_fonte", "artigo científico", None, "tipo_fonte_invalido"), ("tipo_fonte", "Tese", None, "tipo_fonte_invalido"),
    ("tipo_fonte", None, None, "tipo_fonte_invalido"), ("tipo_fonte", " Livro ", "Livro", None),
    ("tipo_fonte", unicodedata.normalize("NFD", "Artigo científico"), "Artigo científico", None),
    ("tipo_fonte", True, None, "tipo_fonte_invalido"), ("tipo_fonte", 3, None, "tipo_fonte_invalido"),
    ("pais_escopo", "Brasil\nSP", "Brasil SP", None), ("pais_escopo", "Bra\tsil", "Bra sil", None),
    ("pais_escopo", "Brasil / SP", "Brasil / SP", None), ("pais_escopo", "  EUA ", "EUA", None),
    ("pais_escopo", "", None, "pais_escopo_invalido"), ("pais_escopo", "   ", None, "pais_escopo_invalido"),
    ("pais_escopo", "x" * 40, "x" * 40, None), ("pais_escopo", "x" * 41, None, "pais_escopo_invalido"),
    ("pais_escopo", ["Brasil"], None, "pais_escopo_invalido"),
    ("topicos", ["Reconhecimento facial"], "Reconhecimento facial", None),
    ("topicos", ["a", "b", "c", "d", "e"], "a; b; c; d; e", None),
    ("topicos", ["a", "b", "c", "d", "e", "f"], None, "topicos_invalidos"),
    ("topicos", ["Viés", "viés", " VIÉS "], "Viés", None),
    ("topicos", ["Viés", unicodedata.normalize("NFD", "viés")], "Viés", None),
    ("topicos", ["a", "b", "c", "d", "e", "A"], "a; b; c; d; e", None),       # repetidos saem antes de contar
    ("topicos", {"a": 1}, None, "topicos_invalidos"),
    ("topicos", ["  policiamento   preditivo "], "policiamento preditivo", None),
    ("topicos", ["", "  "], None, "topicos_invalidos"), ("topicos", [], None, "topicos_invalidos"),
    ("topicos", ["a; b"], None, "topicos_invalidos"), ("topicos", ["x" * 81], None, "topicos_invalidos"),
    ("topicos", ["x" * 80], "x" * 80, None), ("topicos", "a; b", None, "topicos_invalidos"),
    ("topicos", ["a", 3], None, "topicos_invalidos"), ("topicos", None, None, "topicos_invalidos"),
    ("eixo", EIXO, EIXO, None), ("eixo", "Nenhum", None, None), ("eixo", "Outro", None, "eixo_invalido"),
    ("eixo", None, None, "eixo_invalido"), ("eixo", EIXO.lower(), None, "eixo_invalido"),
    ("eixo", unicodedata.normalize("NFD", EIXO), EIXO, None),
    ("justificativa", "  ok  ", "ok", None), ("justificativa", "", None, None), ("justificativa", None, None, None),
    ("justificativa", "x" * 300, "x" * 300, None), ("justificativa", "x" * 301, None, "justificativa_invalida"),
    ("justificativa", 5, None, "justificativa_invalida"), ("justificativa", ["a"], None, "justificativa_invalida"),
])
def test_campos_da_triagem_vies(campo, valor, esperado, problema):
    linha = _conferir(**{campo: valor})
    assert linha[campo] == esperado
    assert linha["problemas"] == ([problema] if problema else [])
    assert linha["valido"] is (problema is None)


def test_erros_combinados_aparecem_todos_na_ordem_dos_campos():
    linha = _conferir(relevancia="?", confianca="?", tipo_fonte="?", pais_escopo="", topicos=[], eixo="?")
    assert linha["problemas"] == ["relevancia_invalida", "confianca_invalida", "tipo_fonte_invalido", "pais_escopo_invalido",
                                  "topicos_invalidos", "eixo_invalido"]
    assert (linha["status"], linha["valido"]) == ("quarentena", False)


def test_item_ausente_na_resposta_fica_invalido_em_quarentena():
    linhas, extras = DT.validar_resposta([_item(), _item(item_id=2)], json.dumps({"itens": [_obj()]}), CFG)
    assert extras["ids_ausentes"] == ["2"] and linhas[1]["status"] == "quarentena" and not linhas[1]["valido"]
    assert (linhas[1]["tipo_fonte"], linhas[1]["topicos"]) == (None, None)


# ---------- banco ----------
class _Busca:
    nome = "falsa"

    def __init__(self, resultados):
        self._r = resultados

    def buscar(self, consulta, filtros):
        return RespostaBusca(self._r(consulta), RegistroChamada(provedor="falsa", operacao="buscar", parametros={},
                                                                 requisitado_em=agora(), http_status=200, raw=b"{}"))


class _Scholar:
    nome = "falso"

    def buscar_pagina(self, termo, inicio, filtros):
        arts = [ArtigoAcademico(f"Artigo {termo.id}", "https://s.org/" + termo.id, "A Autor - Rev, 2022", 2022, "r", 0, 1)]
        return PaginaAcademica(arts, 1, RegistroChamada(provedor="falso", operacao="buscar_pagina", parametros={},
                                                         requisitado_em=agora(), http_status=200, raw=b"{}"))


def construir_vies(caminho, raw):
    logging.disable(logging.CRITICAL)
    repo = RepositorioSQLite(caminho)
    try:
        run = repo.iniciar_execucao("buscar-literatura", "h", "{}", "c")
        busca_literatura.executar(repo, BrutoLocal(raw), _Busca(lambda c: [
            ResultadoWeb("https://comum.org/x", f"comum por {c.id}", "trecho " * (1 if c.id == "LA1" else 3), "2025-01-01", 1),
            ResultadoWeb(f"https://so.org/{c.id}", f"só {c.id}", "s", None, 2)]), run,
            [("A", C.CONJUNTOS_LITERATURA["A"][:2]), ("B", C.CONJUNTOS_LITERATURA["B"][:1])], FiltrosBusca(max_resultados=20), [], 0)
        busca_academica.executar(repo, BrutoLocal(raw), _Scholar(), run, C.CONJUNTOS_LITERATURA["B"][:1],
                                 FiltrosAcademicos(por_pagina=20), 1, [], 0)
        repo.finalizar_execucao(run, "concluida")
    finally:
        repo.fechar()
        logging.disable(logging.NOTSET)


@pytest.fixture
def vies(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    repo = RepositorioSQLite(tmp_path / "busca.db")
    yield repo, BrutoLocal(tmp_path / "raw")
    repo.fechar()


def test_referencias_da_web_viram_itens(vies):
    repo, _ = vies
    itens = repo.itens_para_triagem_escopo("referencia")
    assert [i["link"] for i in itens] == ["https://comum.org/x", "https://so.org/LA1", "https://so.org/LA2", "https://so.org/LB1"]
    comum = itens[0]
    assert comum["termos_ids"] == ["LA1", "LA2", "LB1"] and comum["fonte"] == "referencia" and comum["uf"] == ""
    assert comum["titulo"] == "comum por LB1" and comum["resumo"] == "trecho " * 3      # trecho mais longo; empate: o mais recente
    assert (comum["ano"], comum["host"], comum["provedor"], comum["autores_publicacao"]) == (2025, "comum.org", None, "")
    assert (itens[1]["ano"], itens[1]["termos_ids"]) == (None, ["LA1"])


def test_referencia_sem_ocorrencia_no_relatorio_fica_de_fora(vies):
    repo, _ = vies
    repo.conn.execute("INSERT INTO referencias_web (url_original, url_normalizada, dominio, primeira_vez_run, primeira_vez_em) "
                      "VALUES ('https://orfa.org/', 'orfa.org', 'orfa.org', 'r', '2026-01-01')")
    assert "https://orfa.org/" not in [i["link"] for i in repo.itens_para_triagem_escopo("referencia")]
    repo.conn.execute("UPDATE execucoes SET no_relatorio = 0")          # execução fora do relatório: nada para triar
    assert repo.itens_para_triagem_escopo("referencia") == []


class _Triador:
    """Responde no esquema da triagem de vies; `respostas` decide, por chave de item, o objeto devolvido."""
    nome = "falso-vies"

    def __init__(self, respostas=None):
        self.respostas, self.chamadas = respostas or {}, 0

    def triar(self, itens, instr):
        self.chamadas += 1
        assert instr.versao == "v1" and instr.sistema == CFG.sistema_artigo
        objs = [self.respostas.get(DT.chave_item(i), _obj(id=DT.chave_item(i))) for i in itens]
        reg = RegistroChamada(provedor=self.nome, operacao="triar_escopo", parametros={}, requisitado_em=agora(),
                              http_status=200, raw=b"{}", custo_usd=0.001)
        return ResultadoTriagemLote(json.dumps({"itens": objs}), reg)


def _executar(repo, bruto, triador, fonte="referencia", **kw):
    run = repo.iniciar_execucao("triar-escopo", "h", "{}", "c")
    r = triagem_escopo.executar(repo, bruto, triador, run, fonte, MAPAS, CFG, PRECOS, [], 0, lote=kw.pop("lote", 2), **kw)
    return run, r


def test_grava_os_campos_da_triagem_vies(vies):
    repo, bruto = vies
    t = _Triador({"2": _obj(id="2", relevancia="fora_do_escopo", tipo_fonte="Reportagem", pais_escopo="EUA",
                            topicos=["vigilância"], eixo="Nenhum")})
    run, r = _executar(repo, bruto, t, limite=3)
    assert (r["itens_triados"], r["chamadas"]) == (3, 2)
    linhas = repo.conn.execute("SELECT item_id, fonte, status, status_bruto, tipo_fonte, pais_escopo, topicos, eixo, "
                               "prompt_versao, valido FROM triagem_escopo ORDER BY item_id").fetchall()
    assert [tuple(l) for l in linhas] == [
        (1, "referencia", "elegivel", "alta", "Artigo científico", "Brasil", "Reconhecimento facial; viés racial", EIXO, "v1", 1),
        (2, "referencia", "excluido", "fora_do_escopo", "Reportagem / literatura cinzenta", "EUA", "vigilância", None, "v1", 1),
        (3, "referencia", "elegivel", "alta", "Artigo científico", "Brasil", "Reconhecimento facial; viés racial", EIXO, "v1", 1)]


def test_repetir_nao_chama_de_novo_e_artigos_tambem_triam(vies):
    repo, bruto = vies
    t = _Triador()
    _executar(repo, bruto, t, limite=2)
    _, r = _executar(repo, bruto, t, limite=2)
    assert (t.chamadas, r["a_triar"]) == (1, 0)                    # os 2 já triados com o prompt v1 são pulados
    _, r = _executar(repo, bruto, t, fonte="artigo")
    assert r["itens_triados"] == 1 and repo.conn.execute(
        "SELECT topicos FROM triagem_escopo WHERE fonte = 'artigo'").fetchone()[0] == "Reconhecimento facial; viés racial"


def test_aba_da_planilha_completa_mostra_a_referencia_e_os_campos_novos(vies):
    from adaptadores.consultas_exportacao import CONSULTAS_EXPORTACAO
    repo, bruto = vies
    _executar(repo, bruto, _Triador(), limite=1)
    cur = repo.conn.execute(CONSULTAS_EXPORTACAO["Triagem_escopo"])
    linha = dict(zip([d[0] for d in cur.description], cur.fetchone()))
    assert (linha["fonte"], linha["item"], linha["tipo_fonte"], linha["pais_escopo"], linha["eixo"]) == (
        "referencia", "https://comum.org/x", "Artigo científico", "Brasil", EIXO)
    assert linha["topicos"] == "Reconhecimento facial; viés racial"


def test_banco_antigo_ganha_as_colunas_ao_abrir(tmp_path):
    caminho = tmp_path / "antigo.db"
    RepositorioSQLite(caminho).fechar()
    con = sqlite3.connect(caminho)
    for c in ("tipo_fonte", "pais_escopo", "topicos", "eixo"):
        con.execute(f"ALTER TABLE triagem_escopo DROP COLUMN {c}")
    con.execute("DELETE FROM meta_schema")
    con.commit()
    con.close()
    RepositorioSQLite(caminho).fechar()
    colunas = {l[1] for l in sqlite3.connect(caminho).execute("PRAGMA table_info(triagem_escopo)")}
    assert {"tipo_fonte", "pais_escopo", "topicos", "eixo"} <= colunas


# ---------- comando ----------
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.fixture
def banco_vies(ambiente_cli, monkeypatch):
    (ambiente_cli / "data" / "vies").mkdir(parents=True)
    construir_vies(ambiente_cli / "data" / "vies" / "busca.db", ambiente_cli / "data" / "vies" / "raw")

    def sem_rede(*a, **k):
        raise AssertionError("chamada de rede nao permitida nos testes")
    monkeypatch.setattr(triador_gemini, "chamar", sem_rede)
    return ambiente_cli


@pytest.mark.parametrize("argv, mensagem", [
    (["--banco", "vies", "--fonte", "web", "--estimar"], "Com --banco vies, a triagem é de --fonte artigos ou --fonte referencias."),
    (["--banco", "vies", "--fonte", "artigos", "--curta", "--estimar"], "--curta não vale com --banco vies."),
    (["--fonte", "referencias", "--estimar"], "--fonte referencias vale só com --banco vies."),
    (["--banco", "vies", "--fonte", "referencias", "--amostra", "2", "--estratificar", "--estimar"],
     "--estratificar não vale com --fonte referencias (as referências não têm estratos)."),
])
def test_combinacoes_recusadas(argv, mensagem, ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triar-escopo", *argv)
    assert str(e.value) == mensagem


def test_estimar_no_banco_vies_nao_chama_e_usa_o_prompt_v1(banco_vies, monkeypatch, capsys):
    _rodar(monkeypatch, "triar-escopo", "--banco", "vies", "--fonte", "referencias", "--estimar")
    saida = capsys.readouterr().out
    assert "Itens no banco: 4 | na amostra: 4 | já triados com este prompt: 0 | a triar: 4" in saida
    _rodar(monkeypatch, "triar-escopo", "--banco", "vies", "--fonte", "artigos", "--estimar")
    assert "Itens no banco: 1 |" in capsys.readouterr().out
    con = sqlite3.connect(banco_vies / "data" / "vies" / "busca.db")
    assert con.execute("SELECT COUNT(*) FROM execucoes WHERE comando LIKE 'triar-escopo%'").fetchone()[0] == 0


def test_regra_11_vale_no_banco_vies(banco_vies, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triar-escopo", "--banco", "vies", "--fonte", "referencias")
    assert "regra 11" in str(e.value)


# ---------- PostgreSQL ----------
def test_postgres_tem_as_colunas_novas(pg_url):
    from adaptadores import migrador_postgres as M
    import psycopg
    M.aplicar(pg_url)
    with psycopg.connect(pg_url) as con:
        colunas = {l[0] for l in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'triagem_escopo'")}
    assert {"tipo_fonte", "pais_escopo", "topicos", "eixo"} <= colunas


def test_pacote_de_envio_continua_na_versao_2_sem_as_colunas_do_vies():
    from dominio import pacote_coleta as P
    assert P.VERSAO == 2 and P.CAMPOS_SO_DO_VIES == {"triagem_escopo": ("tipo_fonte", "pais_escopo", "topicos", "eixo")}
    assert not set(P.CAMPOS_SO_DO_VIES["triagem_escopo"]) & set(P.COLUNAS["triagem_escopo"])
    assert len(P.TIPOS["triagem_escopo"][0]) == len(P.COLUNAS["triagem_escopo"])
