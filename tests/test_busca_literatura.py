"""Busca de literatura na web (D103 a D107): tabelas das referencias, etapa, comando `buscar-literatura`.
Nenhum teste abre conexao: os adaptadores sao simulados ou falsos."""
import json
import logging
import sqlite3
import sys

import pytest

import config.settings as S
import main
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_literatura
from aplicacao.comum import registrar_chamada
from config import consultas as C
from dominio.modelos import FiltrosBusca, RegistroChamada, RespostaBusca, ResultadoWeb, Termo
from dominio.servicos import chave_filtros_busca, hash_chave
from infra.util import agora


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def repo(tmp_path):
    r = RepositorioSQLite(tmp_path / "t.db")
    yield r
    r.fechar()


def _run(repo, nome="buscar-literatura"):
    snap = S.snapshot_config()
    return repo.iniciar_execucao(nome, snap["hash"], snap["json"], "teste00", None)


def _chamada(repo, run_id, alvo="LA1"):
    reg = RegistroChamada(provedor="falso", operacao="buscar", parametros={}, requisitado_em=agora(), http_status=200)
    chamada_id, _ = registrar_chamada(repo, None, run_id, "busca_literatura", "consulta_literatura", alvo, "k-" + alvo, reg, [])
    return chamada_id


def _r(url, n, titulo=None, snippet=None, data=None):
    return ResultadoWeb(url, titulo, snippet, data, n)


def _linhas(repo, sql, *p):
    return [tuple(l) for l in repo.conn.execute(sql, p)]


# ---------- tabelas ----------
def test_colunas_das_tabelas_novas(repo):
    assert [l[1] for l in repo.conn.execute("PRAGMA table_info(referencias_web)")] == [
        "referencia_id", "url_normalizada", "url_original", "dominio", "primeira_vez_run", "primeira_vez_em"]
    assert [l[1] for l in repo.conn.execute("PRAGMA table_info(ocorrencias_web)")] == [
        "ocorrencia_id", "chamada_id", "run_id", "conjunto", "consulta_id", "referencia_id", "posicao", "titulo", "snippet",
        "data_pub"]
    indices = {l[1] for l in repo.conn.execute("PRAGMA index_list(ocorrencias_web)")}
    assert {"ix_ocorrencias_web_run", "ix_ocorrencias_web_referencia"} <= indices


# ---------- repositorio ----------
def test_salvar_referencias_grava_referencia_e_ocorrencias_na_ordem_da_resposta(repo):
    run_id = _run(repo)
    cid = _chamada(repo, run_id)
    novas = repo.salvar_referencias_web(cid, run_id, "A", "LA1", [
        _r("https://WWW.Exemplo.org/a?utm_source=x", 1, "Título A", "trecho A", "2024-01-02"),
        _r("https://outro.br/b", 2, None, None, None)])
    assert novas == 2
    refs = _linhas(repo, "SELECT referencia_id, url_normalizada, url_original, dominio, primeira_vez_run FROM referencias_web "
                         "ORDER BY referencia_id")
    assert refs == [(1, "https://exemplo.org/a", "https://WWW.Exemplo.org/a?utm_source=x", "exemplo.org", run_id),
                    (2, "https://outro.br/b", "https://outro.br/b", "outro.br", run_id)]
    assert all(l[0] for l in _linhas(repo, "SELECT primeira_vez_em FROM referencias_web"))
    assert _linhas(repo, "SELECT chamada_id, run_id, conjunto, consulta_id, referencia_id, posicao, titulo, snippet, data_pub "
                         "FROM ocorrencias_web ORDER BY ocorrencia_id") == [
        (cid, run_id, "A", "LA1", 1, 1, "Título A", "trecho A", "2024-01-02"),
        (cid, run_id, "A", "LA1", 2, 2, None, None, None)]


def test_url_ja_gravada_nao_vira_referencia_nova_e_mantem_a_original(repo):
    run1 = _run(repo)
    repo.salvar_referencias_web(_chamada(repo, run1), run1, "A", "LA1", [_r("https://exemplo.org/a?utm_source=x", 1)])
    run2 = _run(repo)
    cid = _chamada(repo, run2, "LB2")
    assert repo.salvar_referencias_web(cid, run2, "B", "LB2", [_r("https://www.exemplo.org/a", 4, "Outro título")]) == 0
    assert _linhas(repo, "SELECT referencia_id, url_original, primeira_vez_run FROM referencias_web") == [
        (1, "https://exemplo.org/a?utm_source=x", run1)]
    assert _linhas(repo, "SELECT run_id, conjunto, consulta_id, referencia_id, posicao, titulo FROM ocorrencias_web "
                         "ORDER BY ocorrencia_id") == [(run1, "A", "LA1", 1, 1, None), (run2, "B", "LB2", 1, 4, "Outro título")]


def test_url_repetida_na_mesma_resposta_vira_uma_referencia_e_duas_ocorrencias(repo):
    run_id = _run(repo)
    cid = _chamada(repo, run_id)
    novas = repo.salvar_referencias_web(cid, run_id, "A", "LA1", [
        _r("https://exemplo.org/a?utm_source=x", 1), _r("https://outro.br/b", 2), _r("https://www.exemplo.org/a", 3)])
    assert novas == 2
    assert _linhas(repo, "SELECT referencia_id, url_original FROM referencias_web ORDER BY referencia_id") == [
        (1, "https://exemplo.org/a?utm_source=x"), (2, "https://outro.br/b")]
    assert _linhas(repo, "SELECT referencia_id, posicao FROM ocorrencias_web ORDER BY ocorrencia_id") == [(1, 1), (2, 2), (1, 3)]


def test_resposta_vazia_nao_grava_nem_consulta(repo):
    run_id = _run(repo)
    cid = _chamada(repo, run_id)
    comandos = []
    repo.conn.set_trace_callback(comandos.append)
    try:
        assert repo.salvar_referencias_web(cid, run_id, "A", "LA1", []) == 0
    finally:
        repo.conn.set_trace_callback(None)
    assert not [c for c in comandos if "referencias_web" in c]
    assert _linhas(repo, "SELECT COUNT(*) FROM ocorrencias_web") == [(0,)]


def test_uma_so_leitura_das_urls_gravadas_por_resposta(repo):
    run_id = _run(repo)
    repo.salvar_referencias_web(_chamada(repo, run_id), run_id, "A", "LA1", [_r(f"https://e.org/{n}", n) for n in range(1, 11)])
    cid = _chamada(repo, run_id, "LA2")
    comandos = []
    repo.conn.set_trace_callback(comandos.append)
    try:
        novas = repo.salvar_referencias_web(cid, run_id, "A", "LA2", [_r(f"https://e.org/{n}", n) for n in range(6, 21)])
    finally:
        repo.conn.set_trace_callback(None)
    assert novas == 10
    assert len([c for c in comandos if c.lstrip().upper().startswith("SELECT")]) == 1
    assert len([c for c in comandos if "INSERT INTO referencias_web" in c]) == 10


def test_referencias_nao_tocam_as_tabelas_da_tarefa_1(repo):
    run_id = _run(repo)
    repo.salvar_referencias_web(_chamada(repo, run_id), run_id, "A", "LA1", [_r("https://exemplo.org/a", 1)])
    assert _linhas(repo, "SELECT (SELECT COUNT(*) FROM urls), (SELECT COUNT(*) FROM resultados_web)") == [(0, 0)]


# ---------- etapa ----------
class _BuscaFalsa:
    nome = "falsa"

    def __init__(self, resultados=None, erro_em=()):
        self.pedidos, self._resultados, self._erro_em = [], resultados, set(erro_em)

    def buscar(self, consulta, filtros):
        self.pedidos.append((consulta, filtros))
        erro = "HTTP 500" if consulta.id in self._erro_em else None
        reg = RegistroChamada(provedor=self.nome, operacao="buscar", parametros={"query": consulta.texto},
                              requisitado_em=agora(), http_status=500 if erro else 200, erro=erro, raw=b"{}")
        res = [] if erro else (self._resultados if self._resultados is not None
                               else [_r(f"https://lit.org/{consulta.id}/{n}", n, f"t{n}") for n in (1, 2)])
        return RespostaBusca(res, reg)


T_A = (Termo("LA1", "q a1", "pt", "conjunto_A"), Termo("LA2", "q a2", "pt", "conjunto_A"))
T_B = (Termo("LB1", "q b1", "pt", "conjunto_B"),)
FILTROS = FiltrosBusca(max_resultados=20, idiomas=("pt",), pais="BR")


def _etapa(repo, tmp_path, busca, conjuntos, limite=None, run_id=None):
    run_id = run_id or _run(repo)
    busca_literatura.executar(repo, BrutoLocal(tmp_path / "raw"), busca, run_id, conjuntos, FILTROS, [], 0, limite)
    return run_id


def test_etapa_pede_cada_consulta_na_ordem_dos_conjuntos(repo, tmp_path, silencio):
    busca = _BuscaFalsa()
    run_id = _etapa(repo, tmp_path, busca, [("B", T_B), ("A", T_A)])
    assert [(c.id, c.texto, c.idioma, c.uf, c.tecnologia, c.modelo_id, c.perfil, c.cidade) for c, _ in busca.pedidos] == [
        ("LB1", "q b1", "pt", "", "", "LB1", "literatura", ""),
        ("LA1", "q a1", "pt", "", "", "LA1", "literatura", ""),
        ("LA2", "q a2", "pt", "", "", "LA2", "literatura", "")]
    assert all(f is FILTROS for _, f in busca.pedidos)
    assert _linhas(repo, "SELECT etapa, alvo_tipo, alvo_id, uf, pagina, sucesso, n_retornados, n_novos, chave_idempotencia "
                         "FROM chamadas WHERE run_id=? ORDER BY chamada_id", run_id) == [
        ("busca_literatura", "consulta_literatura", t.id, None, None, 1, 2, 2,
         hash_chave("busca_literatura", "falsa", t.id, chave_filtros_busca(FILTROS))) for t in (T_B[0], T_A[0], T_A[1])]
    assert _linhas(repo, "SELECT conjunto, consulta_id, posicao FROM ocorrencias_web ORDER BY ocorrencia_id") == [
        ("B", "LB1", 1), ("B", "LB1", 2), ("A", "LA1", 1), ("A", "LA1", 2), ("A", "LA2", 1), ("A", "LA2", 2)]


def test_chave_muda_com_os_filtros():
    a = hash_chave("busca_literatura", "falsa", "LA1", chave_filtros_busca(FILTROS))
    b = hash_chave("busca_literatura", "falsa", "LA1", chave_filtros_busca(FiltrosBusca(max_resultados=20, idiomas=("pt",))))
    assert a != b


def test_retomada_nao_repete_consulta_ja_feita(repo, tmp_path, silencio):
    run_id = _etapa(repo, tmp_path, _BuscaFalsa(), [("A", T_A)])
    busca = _BuscaFalsa()
    _etapa(repo, tmp_path, busca, [("A", T_A), ("B", T_B)], run_id=run_id)
    assert [c.id for c, _ in busca.pedidos] == ["LB1"]
    assert _linhas(repo, "SELECT COUNT(*) FROM ocorrencias_web") == [(6,)]


def test_limite_vale_para_a_execucao_inteira(repo, tmp_path, silencio):
    busca = _BuscaFalsa()
    run_id = _etapa(repo, tmp_path, busca, [("A", T_A), ("B", T_B)], limite=2)
    assert [c.id for c, _ in busca.pedidos] == ["LA1", "LA2"]
    busca = _BuscaFalsa()
    _etapa(repo, tmp_path, busca, [("A", T_A), ("B", T_B)], limite=2, run_id=run_id)
    assert busca.pedidos == []                                     # a retomada conta as 2 chamadas ja feitas
    busca = _BuscaFalsa()
    _etapa(repo, tmp_path, busca, [("A", T_A), ("B", T_B)], limite=3, run_id=run_id)
    assert [c.id for c, _ in busca.pedidos] == ["LB1"]


def test_falha_fica_registrada_sem_referencias(repo, tmp_path, silencio):
    run_id = _etapa(repo, tmp_path, _BuscaFalsa(erro_em={"LA1"}), [("A", T_A)])
    assert _linhas(repo, "SELECT alvo_id, sucesso, erro, n_retornados, n_novos FROM chamadas WHERE run_id=? ORDER BY chamada_id",
                   run_id) == [("LA1", 0, "HTTP 500", 0, 0), ("LA2", 1, None, 2, 2)]
    assert _linhas(repo, "SELECT DISTINCT consulta_id FROM ocorrencias_web") == [("LA2",)]


def test_link_invalido_e_descartado_e_contado(repo, tmp_path, silencio):
    busca = _BuscaFalsa(resultados=[_r("https://ok.org/1", 1), _r("nao e url", 2), _r("ftp://x.org/a", 3)])
    run_id = _etapa(repo, tmp_path, busca, [("B", T_B)])
    assert _linhas(repo, "SELECT n_retornados, n_novos FROM chamadas WHERE run_id=?", run_id) == [(3, 1)]
    assert json.loads(repo.conn.execute("SELECT extras_json FROM chamadas WHERE run_id=?", (run_id,)).fetchone()[0])[
        "urls_invalidas"] == 2
    assert _linhas(repo, "SELECT url_normalizada FROM referencias_web") == [("https://ok.org/1",)]


def test_resposta_sem_resultados_grava_so_a_chamada(repo, tmp_path, silencio):
    run_id = _etapa(repo, tmp_path, _BuscaFalsa(resultados=[]), [("B", T_B)])
    assert _linhas(repo, "SELECT sucesso, n_retornados, n_novos FROM chamadas WHERE run_id=?", run_id) == [(1, 0, 0)]
    assert _linhas(repo, "SELECT COUNT(*) FROM ocorrencias_web") == [(0,)]


@pytest.mark.parametrize("urls, refs, ocorrencias", [
    # www, barra final, parametro de rastreio, fragmento e maiusculas no host viram a mesma referencia; a original e a 1a
    (["https://www.a.org/x/?utm_source=1", "https://a.org/x#f", "https://A.org/x"],
     [("https://a.org/x", "https://www.a.org/x/?utm_source=1")], [1, 1, 1]),
    # esquema diferente nao junta
    (["https://a.org/x", "http://a.org/x"], [("https://a.org/x", "https://a.org/x"), ("http://a.org/x", "http://a.org/x")], [1, 2]),
    # a ordem dos parametros nao importa
    (["https://a.org/x?b=1&a=2", "https://a.org/x?a=2&b=1"], [("https://a.org/x?a=2&b=1", "https://a.org/x?b=1&a=2")], [1, 1]),
])
def test_urls_que_normalizam_igual_viram_uma_referencia(repo, urls, refs, ocorrencias):
    run_id = _run(repo)
    novas = repo.salvar_referencias_web(_chamada(repo, run_id), run_id, "A", "LA1", [_r(u, n) for n, u in enumerate(urls, 1)])
    assert novas == len(refs)
    assert _linhas(repo, "SELECT url_normalizada, url_original FROM referencias_web ORDER BY referencia_id") == refs
    assert [r for (r,) in repo.conn.execute("SELECT referencia_id FROM ocorrencias_web ORDER BY ocorrencia_id")] == ocorrencias


def test_url_que_ja_esta_na_tarefa_1_vira_referencia_sem_tocar_urls(repo):
    run_id = _run(repo)
    repo.conn.execute("INSERT INTO urls (url_normalizada, url_original, dominio, fonte_oficial) "
                      "VALUES ('https://a.org/x', 'https://a.org/x', 'a.org', 0)")
    assert repo.salvar_referencias_web(_chamada(repo, run_id), run_id, "A", "LA1", [_r("https://a.org/x", 1)]) == 1
    assert _linhas(repo, "SELECT COUNT(*) FROM referencias_web") == [(1,)]
    assert _linhas(repo, "SELECT url_id, url_normalizada FROM urls") == [(1, "https://a.org/x")]


# ---------- janela entre a chamada paga e o registro ----------
class _ListaQueInterrompe(list):
    def __iter__(self):
        raise KeyboardInterrupt


def test_interrupcao_depois_da_chamada_fica_registrada_como_falha(repo, tmp_path, silencio):
    busca = _BuscaFalsa(resultados=_ListaQueInterrompe([_r("https://a.org/1", 1)]))
    run_id = _run(repo)
    with pytest.raises(KeyboardInterrupt):
        _etapa(repo, tmp_path, busca, [("A", T_A)], run_id=run_id)
    assert _linhas(repo, "SELECT alvo_id, sucesso, erro FROM chamadas WHERE run_id=?", run_id) == [
        ("LA1", 0, "falha_ao_validar: KeyboardInterrupt")]
    assert _linhas(repo, "SELECT COUNT(*) FROM ocorrencias_web") == [(0,)]
    assert [c.id for c, _ in busca.pedidos] == ["LA1"]                 # parou na primeira consulta


def test_registro_da_falha_que_falha_nao_esconde_a_interrupcao(repo, tmp_path, silencio, monkeypatch):
    import aplicacao.comum as comum

    def quebra(*a, **k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(comum, "registrar_chamada", quebra)
    busca = _BuscaFalsa(resultados=_ListaQueInterrompe([_r("https://a.org/1", 1)]))
    with pytest.raises(KeyboardInterrupt):
        _etapa(repo, tmp_path, busca, [("A", T_A)])


def test_falha_e_refeita_na_retomada_e_conta_no_limite(repo, tmp_path, silencio):
    run_id = _etapa(repo, tmp_path, _BuscaFalsa(erro_em={"LA1"}), [("A", T_A), ("B", T_B)], limite=2)
    busca = _BuscaFalsa()
    _etapa(repo, tmp_path, busca, [("A", T_A), ("B", T_B)], limite=2, run_id=run_id)
    assert [c.id for c, _ in busca.pedidos] == ["LA1"]                 # refaz a falha; LB1 passaria do limite
    assert _linhas(repo, "SELECT alvo_id, sucesso FROM chamadas WHERE run_id=? ORDER BY chamada_id", run_id) == [
        ("LA1", 0), ("LA2", 1), ("LA1", 1)]


# ---------- comando ----------
def _cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", "buscar-literatura", *args])
    main.main()


def _db(ambiente_cli):
    return sqlite3.connect(ambiente_cli / "data" / "simulado.db")


def test_comando_simulado_grava_uma_execucao_com_as_consultas(ambiente_cli, monkeypatch, silencio):
    _cli(monkeypatch, "--conjunto", "A", "--simulado")
    db = _db(ambiente_cli)
    assert db.execute("SELECT comando, status FROM execucoes").fetchall() == [("buscar-literatura [simulado]", "concluida")]
    assert db.execute("SELECT etapa, alvo_tipo, provedor, alvo_id, n_retornados FROM chamadas ORDER BY chamada_id").fetchall() == [
        ("busca_literatura", "consulta_literatura", "simulado", f"LA{n}", 3) for n in range(1, 6)]
    assert db.execute("SELECT n_novos FROM chamadas ORDER BY chamada_id").fetchall() == [(3,), (2,), (2,), (2,), (2,)]
    assert db.execute("SELECT COUNT(*) FROM referencias_web").fetchone() == (11,)          # 2 por consulta + 1 comum
    assert db.execute("SELECT COUNT(*), COUNT(DISTINCT consulta_id) FROM ocorrencias_web WHERE conjunto='A'").fetchone() == (15, 5)
    assert db.execute("SELECT (SELECT COUNT(*) FROM urls), (SELECT COUNT(*) FROM resultados_web)").fetchone() == (0, 0)
    amb = json.loads(db.execute("SELECT ambiente_json FROM execucoes").fetchone()[0])["argumentos"]
    assert (amb["conjunto"], amb["cmd"]) == (["A"], "buscar-literatura")


def test_comando_segue_a_ordem_dos_conjuntos_sem_repetir(ambiente_cli, monkeypatch, silencio):
    _cli(monkeypatch, "--conjunto", "B", "A", "B", "--simulado")
    alvos = [a for (a,) in _db(ambiente_cli).execute("SELECT alvo_id FROM chamadas ORDER BY chamada_id")]
    assert alvos == ["LB1", "LB2", "LB3", "LB4", "LB5", "LA1", "LA2", "LA3", "LA4", "LA5"]
    assert _db(ambiente_cli).execute("SELECT DISTINCT conjunto FROM ocorrencias_web ORDER BY ocorrencia_id").fetchall() == [
        ("B",), ("A",)]


def test_comando_com_limite(ambiente_cli, monkeypatch, silencio):
    _cli(monkeypatch, "--conjunto", "A", "B", "--simulado", "--limite", "2")
    assert _db(ambiente_cli).execute("SELECT alvo_id FROM chamadas ORDER BY chamada_id").fetchall() == [("LA1",), ("LA2",)]


def _primeira(ambiente_cli, monkeypatch, *args):
    _cli(monkeypatch, *args)
    return _db(ambiente_cli).execute("SELECT run_id FROM execucoes").fetchone()[0]


def test_comando_retomado_nao_repete(ambiente_cli, monkeypatch, silencio):
    run_id = _primeira(ambiente_cli, monkeypatch, "--conjunto", "A", "B", "--simulado", "--limite", "2")
    _cli(monkeypatch, "--conjunto", "A", "B", "A", "--simulado", "--limite", "4", "--retomar", run_id)
    assert _db(ambiente_cli).execute("SELECT alvo_id FROM chamadas ORDER BY chamada_id").fetchall() == [
        (f"LA{n}",) for n in range(1, 5)]


@pytest.mark.parametrize("novo, antes_txt", [
    (("B",), "A B"),            # outro conjunto
    (("A",), "A B"),            # menos conjuntos
    (("B", "A"), "A B"),        # outra ordem
])
def test_retomada_com_outro_conjunto_e_recusada(novo, antes_txt, ambiente_cli, monkeypatch, silencio):
    run_id = _primeira(ambiente_cli, monkeypatch, "--conjunto", "A", "B", "--simulado", "--limite", "1")
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "--conjunto", *novo, "--simulado", "--limite", "1", "--retomar", run_id)
    assert str(e.value) == (f"Esta execução foi criada com --conjunto {antes_txt}. Ao retomar, repita --conjunto {antes_txt}: "
                            "ampliar a busca exige uma execução nova.")
    assert _db(ambiente_cli).execute("SELECT COUNT(*) FROM chamadas").fetchone() == (1,)


def test_retomada_ampliando_um_conjunto_e_recusada(ambiente_cli, monkeypatch, silencio):
    run_id = _primeira(ambiente_cli, monkeypatch, "--conjunto", "A", "--simulado", "--limite", "1")
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "--conjunto", "A", "B", "--simulado", "--limite", "1", "--retomar", run_id)
    assert str(e.value) == ("Esta execução foi criada com --conjunto A. Ao retomar, repita --conjunto A: "
                            "ampliar a busca exige uma execução nova.")


def test_retomada_de_execucao_de_outro_comando_e_recusada(ambiente_cli, monkeypatch, silencio):
    monkeypatch.setattr(sys, "argv", ["main.py", "busca-web", "--simulado", "--ufs", "PI", "--limite", "1"])
    main.main()
    run_id = _db(ambiente_cli).execute("SELECT run_id FROM execucoes").fetchone()[0]
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "--conjunto", "A", "--simulado", "--limite", "1", "--retomar", run_id)
    assert str(e.value) == f"A execução {run_id} não é uma execução de buscar-literatura neste banco."
    assert _db(ambiente_cli).execute("SELECT COUNT(*) FROM chamadas WHERE etapa='busca_literatura'").fetchone() == (0,)


def test_retomada_de_execucao_inexistente_e_recusada(ambiente_cli, monkeypatch, silencio):
    _primeira(ambiente_cli, monkeypatch, "--conjunto", "A", "--simulado", "--limite", "1")
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "--conjunto", "A", "--simulado", "--limite", "1", "--retomar", "20990101_000000_ffffff")
    assert str(e.value) == "A execução 20990101_000000_ffffff não é uma execução de buscar-literatura neste banco."


@pytest.mark.parametrize("ambiente", [
    "{", '"texto"', '{"argumentos": []}',
    # o conjunto gravado decide a retomada: so uma lista nao vazia de textos vale (fecha nos outros casos)
    '{"argumentos": {"cmd": "buscar-literatura"}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": null}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": 42}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": "AB"}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": []}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": [null]}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": ["A", 1]}}',
    '{"argumentos": {"cmd": "buscar-literatura", "conjunto": {"A": 1}}}',
])
def test_retomada_com_argumentos_ilegiveis_e_recusada(ambiente, ambiente_cli, monkeypatch, silencio):
    run_id = _primeira(ambiente_cli, monkeypatch, "--conjunto", "A", "--simulado", "--limite", "1")
    db = _db(ambiente_cli)
    db.execute("UPDATE execucoes SET ambiente_json=?", (ambiente,))
    db.commit()
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "--conjunto", "A", "--simulado", "--limite", "1", "--retomar", run_id)
    assert str(e.value) == (f"Os argumentos gravados da execução {run_id} estão ilegíveis: "
                            "não dá para conferir o --conjunto da retomada.")


@pytest.mark.parametrize("args", [
    ("--simulado",),                                                    # sem --conjunto
    ("--conjunto", "C", "--simulado"),                                  # conjunto desconhecido
    ("--conjunto", "a", "--simulado"),                                  # minuscula
    ("--conjunto", "--simulado"),                                       # --conjunto vazio
    ("--conjunto", "A", "--fonte", "web", "--simulado"),                # --fonte ainda nao existe
    ("--conjunto", "A", "--simulado", "--ufs", "PI"),
    ("--conjunto", "A", "--simulado", "--termos", "T01"),
    ("--conjunto", "A", "--simulado", "--de", "x"),
    ("--conjunto", "A", "--simulado", "--paginas", "2"),
    ("--conjunto", "A", "--simulado", "--perfil", "oficial"),
    ("--conjunto", "A", "--simulado", "--idioma-resultados", "lang_en"),
    ("--conjunto", "A", "--simulado", "--tecnologias", "reconhecimento_facial"),
    ("--conjunto", "A", "--simulado", "--auditoria", "1"),
    ("--conjunto", "A", "--simulado", "--limite", "0"),
])
def test_argumentos_invalidos_sao_recusados_pelo_analisador(args, ambiente_cli, monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, *args)
    assert e.value.code == 2
    assert not (ambiente_cli / "data" / "simulado.db").exists()


def test_comandos_antigos_nao_ganham_conjunto(ambiente_cli, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "busca-web", "--simulado", "--conjunto", "A"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert e.value.code == 2


def test_com_o_serpapi_google_a_execucao_falha_sem_chamar(ambiente_cli, monkeypatch, silencio):
    from adaptadores import busca_serpapi_google
    monkeypatch.setenv("SERPAPI_KEY", "CHAVE-FALSA-123")
    monkeypatch.setitem(S.PROVEDORES, "busca_web", "serpapi_google")
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", ambiente_cli / "data" / "pesquisa.db")   # nunca o banco real
    monkeypatch.setitem(S.OPCOES["local"], "raiz", ambiente_cli / "data" / "raw")
    monkeypatch.setattr(busca_serpapi_google, "chamar", lambda *a, **k: pytest.fail("nao deveria chamar"))
    _cli(monkeypatch, "--conjunto", "A", "--limite", "1")
    db = sqlite3.connect(ambiente_cli / "data" / "pesquisa.db")
    assert db.execute("SELECT comando, status FROM execucoes").fetchall() == [("buscar-literatura", "falhou")]
    assert db.execute("SELECT COUNT(*) FROM chamadas").fetchone() == (0,)


# ---------- relatorio ----------
def test_metodologia_conhece_a_etapa_e_cobra_o_preco():
    from painel import metodologia_texto
    assert metodologia_texto.ETAPAS["busca_literatura"] == "busca de literatura na web"
    assert "busca_literatura" in metodologia_texto.ETAPAS_COM_PRECO
