"""Leitura consistente do banco `vies`: cada resposta das analises, da visao geral e do sorteio da validacao le um so
estado do banco (uma conexao e uma transacao de leitura por resposta), no SQLite e no PostgreSQL; a conexao fecha ou volta
ao pool no fim, mesmo com erro; nada fica aberto durante a renderizacao."""
import sqlite3
import threading

import jinja2
import pytest

from adaptadores import leitura_sqlite as LS
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from painel import visao_geral, visao_geral_vies
from painel.rotas_extras.analises import montar_vies
from dominio import analises_ferramentas as AF
from test_validacao_vies import _cli, _contexto, _post, banco  # noqa: F401  (fixture `banco`: vies com triagem)

SECOES = ("panorama", "ferramentas", "tipos", "temas", "tempo", "consultas", "web")


# ---------- conexoes do adaptador SQLite, contadas ----------
class _Rastreada(sqlite3.Connection):
    abertas = []
    todas = []

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        _Rastreada.abertas.append(self)
        _Rastreada.todas.append(self)

    def close(self):
        if self in _Rastreada.abertas:
            _Rastreada.abertas.remove(self)
        super().close()


class _Sqlite3:
    """O modulo sqlite3 visto pelo adaptador de leitura, com o connect contado (so as conexoes deste adaptador)."""
    def __getattr__(self, nome):
        return getattr(sqlite3, nome)

    @staticmethod
    def connect(*a, **k):
        return sqlite3.connect(*a, factory=_Rastreada, **k)


@pytest.fixture
def rastreio(monkeypatch):
    _Rastreada.abertas, _Rastreada.todas = [], []
    monkeypatch.setattr(LS, "sqlite3", _Sqlite3())
    return _Rastreada


def _gravar_sqlite(banco):
    """Uma atualizacao controlada, confirmada por outra conexao: muda as triagens e as referencias juntas."""
    con = sqlite3.connect(banco)
    try:
        con.execute("PRAGMA busy_timeout = 5000")
        con.execute("UPDATE triagem_escopo SET justificativa = 'depois'")
        con.execute("UPDATE referencias_web SET url_original = url_original || '#depois'")
        con.commit()
    finally:
        con.close()


def _estado(l, versao):
    """O que duas consultas diferentes da mesma operacao veem: as URLs das referencias e as justificativas das triagens."""
    return (sorted(r["url_original"] for r in l.linhas_referencias_web()),
            sorted(t["justificativa"] for t in l.triagens_vies(versao).values()))


# ---------- A: atualizacao concorrente (SQLite) ----------
def test_sqlite_duas_consultas_da_mesma_operacao_veem_o_mesmo_estado(banco):
    leitura, versao = LeituraPainelSQLite(banco), _contexto("vies").versao_triagem_vies
    antes = _estado(leitura, versao)
    assert antes[0] and set(antes[1]) == {"trata de viés"}
    with leitura.instantaneo() as l:
        urls = sorted(r["url_original"] for r in l.linhas_referencias_web())
        _gravar_sqlite(banco)
        justificativas = sorted(t["justificativa"] for t in l.triagens_vies(versao).values())
        assert (urls, justificativas) == antes                       # a segunda consulta nao ve a gravacao
        assert _estado(l, versao) == antes                           # nem a primeira repetida
        assert _estado(leitura, versao) != antes                     # a leitura original nao foi presa ao bloco
    depois = _estado(leitura, versao)
    assert set(depois[1]) == {"depois"} and all(u.endswith("#depois") for u in depois[0])
    with leitura.instantaneo() as l:                                 # uma operacao nova ve a atualizacao
        assert _estado(l, versao) == depois


def test_sqlite_o_objeto_do_bloco_e_outro_e_a_leitura_original_nao_muda(banco, rastreio):
    leitura = LeituraPainelSQLite(banco)
    with leitura.instantaneo() as l:
        assert l is not leitura and type(l) is type(leitura)
        l.linhas_referencias_web()
        l.triagens_vies(_contexto("vies").versao_triagem_vies)
        assert len(rastreio.todas) == 1                              # as consultas do bloco numa conexao so
        leitura.linhas_referencias_web()                             # fora do bloco: a conexao propria de cada consulta
        assert len(rastreio.todas) == 2 and len(rastreio.abertas) == 1
    assert rastreio.abertas == []


# ---------- B: falha durante a leitura (SQLite) ----------
def test_sqlite_erro_no_meio_fecha_a_conexao_e_o_banco_continua_disponivel(banco, rastreio):
    leitura = LeituraPainelSQLite(banco)
    with pytest.raises(RuntimeError, match="^falha de teste$"):
        with leitura.instantaneo() as l:
            l.linhas_referencias_web()
            raise RuntimeError("falha de teste")
    assert len(rastreio.todas) == 1 and rastreio.abertas == []
    with pytest.raises(Exception):                                   # o objeto do bloco nao abre conexao nova depois
        l.linhas_referencias_web()
    assert len(rastreio.todas) == 1
    _gravar_sqlite(banco)                                            # nenhuma transacao presa: grava e le de novo
    with leitura.instantaneo() as l2:
        assert all(r["url_original"].endswith("#depois") for r in l2.linhas_referencias_web())
    assert rastreio.abertas == []


def test_sqlite_erro_de_sql_no_meio_propaga_e_fecha(banco, rastreio):
    leitura = LeituraPainelSQLite(banco)
    with pytest.raises(sqlite3.OperationalError):
        with leitura.instantaneo() as l:
            l.linhas_referencias_web()
            l._consulta("SELECT * FROM tabela_que_nao_existe")
    assert rastreio.abertas == []


def test_sqlite_o_bloco_nao_grava(banco):
    with LeituraPainelSQLite(banco).instantaneo() as l:
        with pytest.raises(sqlite3.OperationalError):
            l._consulta("UPDATE referencias_web SET dominio = 'x'")


# ---------- C: operacoes simultaneas (SQLite) ----------
def test_sqlite_operacoes_simultaneas_tem_cada_uma_o_seu_estado(banco, rastreio):
    leitura, versao = LeituraPainelSQLite(banco), _contexto("vies").versao_triagem_vies
    antes = _estado(leitura, versao)
    rastreio.todas.clear()
    leram, gravou = threading.Barrier(3), threading.Event()
    vistos, erros = {}, []

    def operacao(nome):
        try:
            with leitura.instantaneo() as l:
                urls = sorted(r["url_original"] for r in l.linhas_referencias_web())
                leram.wait(10)
                gravou.wait(10)
                vistos[nome] = (urls, sorted(t["justificativa"] for t in l.triagens_vies(versao).values()))
        except Exception as e:                                       # pragma: no cover - so aparece se falhar
            erros.append(e)

    fios = [threading.Thread(target=operacao, args=(n,)) for n in ("um", "dois")]
    for f in fios:
        f.start()
    leram.wait(10)
    _gravar_sqlite(banco)
    gravou.set()
    for f in fios:
        f.join(10)
    assert erros == [] and vistos == {"um": antes, "dois": antes}
    assert len(rastreio.todas) == 2 and rastreio.todas[0] is not rastreio.todas[1]   # uma conexao propria por operacao
    assert rastreio.abertas == []
    with leitura.instantaneo() as l:
        assert _estado(l, versao) != antes


# ---------- rotas: uma resposta, um estado; nada aberto durante a renderizacao ----------
@pytest.fixture
def renderizacoes(monkeypatch, rastreio):
    """Quantas conexoes do adaptador estavam abertas a cada renderizacao de modelo."""
    vistas = []
    original = jinja2.Template.render

    def render(self, *a, **k):
        vistas.append(len(rastreio.abertas))
        return original(self, *a, **k)
    monkeypatch.setattr(jinja2.Template, "render", render)
    return vistas


@pytest.mark.parametrize("secao", SECOES)
def test_rota_analises_uma_conexao_e_nada_aberto_ao_renderizar(banco, tmp_path, rastreio, renderizacoes, secao):
    cli = _cli(banco, tmp_path)
    rastreio.todas.clear()
    renderizacoes.clear()
    r = cli.get(f"/analises?secao={secao}")
    assert r.status_code == 200
    assert len(rastreio.todas) == 1 and rastreio.abertas == [] and renderizacoes and set(renderizacoes) == {0}


def test_rota_visao_geral_uma_conexao_e_nada_aberto_ao_renderizar(banco, tmp_path, rastreio, renderizacoes):
    cli = _cli(banco, tmp_path)
    rastreio.todas.clear()
    renderizacoes.clear()
    assert cli.get("/").status_code == 200
    assert len(rastreio.todas) == 1 and rastreio.abertas == [] and renderizacoes and set(renderizacoes) == {0}


def test_rota_sortear_le_numa_conexao_so(banco, tmp_path, rastreio):
    cli = _cli(banco, tmp_path)
    rastreio.todas.clear()
    r = _post(cli, "/validacao/sortear")
    assert r.status_code == 303 and len(rastreio.todas) == 1 and rastreio.abertas == []


def test_rota_analises_sem_gravacao_no_meio_e_estavel(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    assert cli.get("/analises?secao=panorama").text == cli.get("/analises?secao=panorama").text


def test_rota_analises_resposta_com_gravacao_no_meio_e_a_do_estado_anterior(banco, tmp_path, monkeypatch):
    """A pagina de uma resposta com gravacao no meio e igual a pagina do estado anterior (copia do banco antes da gravacao)."""
    import shutil
    copia = tmp_path / "copia"
    copia.mkdir()
    con = sqlite3.connect(banco)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    shutil.copy(banco, copia / "busca.db")
    esperado = _cli(copia / "busca.db", copia).get("/analises?secao=panorama").text
    original = LeituraPainelSQLite.linhas_artigos_das_consultas
    feito = []

    def com_gravacao(self, consultas):
        if not feito and self._caminho == banco:
            feito.append(1)
            c2 = sqlite3.connect(banco)
            c2.execute("DELETE FROM triagem_escopo")
            c2.commit()
            c2.close()
        return original(self, consultas)
    cli = _cli(banco, tmp_path)
    monkeypatch.setattr(LeituraPainelSQLite, "linhas_artigos_das_consultas", com_gravacao)
    assert cli.get("/analises?secao=panorama").text == esperado and feito == [1]
    assert cli.get("/analises?secao=panorama").text != esperado


def test_rota_visao_geral_com_gravacao_no_meio_e_a_do_estado_anterior(banco, tmp_path, monkeypatch):
    cli = _cli(banco, tmp_path)
    esperado = cli.get("/").text
    original = LeituraPainelSQLite.linhas_artigos_das_consultas
    feito = []

    def com_gravacao(self, consultas):
        if not feito:
            feito.append(1)
            c2 = sqlite3.connect(banco)
            c2.execute("DELETE FROM triagem_escopo")
            c2.commit()
            c2.close()
        return original(self, consultas)
    monkeypatch.setattr(LeituraPainelSQLite, "linhas_artigos_das_consultas", com_gravacao)
    assert cli.get("/").text == esperado and feito == [1]
    assert cli.get("/").text != esperado


def test_rota_sortear_com_gravacao_no_meio_sorteia_o_estado_anterior(banco, tmp_path, monkeypatch):
    """Sem leitura consistente, as triagens invalidadas no meio deixariam o sorteio vazio (409)."""
    original = LeituraPainelSQLite.linhas_artigos_das_consultas
    feito = []

    def com_gravacao(self, consultas):
        if not feito:
            feito.append(1)
            c2 = sqlite3.connect(banco)
            c2.execute("UPDATE triagem_escopo SET valido = 0")
            c2.commit()
            c2.close()
        return original(self, consultas)
    cli = _cli(banco, tmp_path)
    monkeypatch.setattr(LeituraPainelSQLite, "linhas_artigos_das_consultas", com_gravacao)
    r = _post(cli, "/validacao/sortear")
    assert feito == [1] and r.status_code == 303
    assert sqlite3.connect(banco).execute("SELECT COUNT(*) FROM validacao_vies").fetchone()[0] == 5


def test_rota_analises_erro_no_meio_fecha_a_conexao(banco, tmp_path, rastreio, monkeypatch):
    def falha(self, versao):
        raise RuntimeError("falha de teste")
    cli = _cli(banco, tmp_path)
    monkeypatch.setattr(LeituraPainelSQLite, "triagens_vies", falha)
    rastreio.todas.clear()
    with pytest.raises(RuntimeError, match="^falha de teste$"):
        cli.get("/analises?secao=panorama")
    assert len(rastreio.todas) == 1 and rastreio.abertas == []
    monkeypatch.undo()


# ---------- banco real (Tarefa 1): as analises continuam como antes ----------
def test_banco_real_nao_usa_a_leitura_consistente(banco, tmp_path, monkeypatch):
    chamadas = []
    original = LeituraPainelSQLite.instantaneo

    def contada(self):
        chamadas.append(1)
        return original(self)
    monkeypatch.setattr(LeituraPainelSQLite, "instantaneo", contada)
    cli = _cli(banco, tmp_path, nome="real")
    assert cli.get("/analises").status_code == 200 and cli.get("/").status_code == 200
    assert chamadas == []


# ---------- PostgreSQL ----------
@pytest.fixture
def pg_vies(pg_url, banco):
    """O mesmo banco `vies` (com triagem) importado num PostgreSQL local descartavel; devolve (leitura, pool, url)."""
    from adaptadores import migrador_postgres as M
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres import conexao as CX, importador as I
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    I.importar(banco, pg_url, esquema="vies")
    pool = CX.criar_pool(pg_url, esquema="vies")
    try:
        yield LeituraPainelPostgres(pool, CX.chaves_do_banco(pool)), pool, pg_url
    finally:
        pool.close()


def _gravar_pg(url):
    import psycopg
    with psycopg.connect(url) as c:
        c.execute("UPDATE vies.triagem_escopo SET justificativa = 'depois'")
        c.execute("UPDATE vies.referencias_web SET url_original = url_original || '#depois'")


def _presas(url):
    """Sessoes deste banco paradas no meio de uma transacao."""
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        return c.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database() "
                         "AND state LIKE 'idle in transaction%'").fetchone()[0]


@pytest.mark.postgres
def test_pg_duas_consultas_da_mesma_operacao_veem_o_mesmo_estado(pg_vies):
    leitura, pool, url = pg_vies
    versao = _contexto("vies").versao_triagem_vies
    antes = _estado(leitura, versao)
    assert antes[0] and set(antes[1]) == {"trata de viés"}
    with leitura.instantaneo() as l:
        assert l is not leitura and type(l) is type(leitura)
        urls = sorted(r["url_original"] for r in l.linhas_referencias_web())
        _gravar_pg(url)
        assert (urls, sorted(t["justificativa"] for t in l.triagens_vies(versao).values())) == antes
        assert _estado(l, versao) == antes
        assert _estado(leitura, versao) != antes
    depois = _estado(leitura, versao)
    assert set(depois[1]) == {"depois"}
    with leitura.instantaneo() as l:
        assert _estado(l, versao) == depois


@pytest.mark.postgres
def test_pg_uma_conexao_do_pool_por_operacao_e_somente_leitura(pg_vies, monkeypatch):
    leitura, pool, _ = pg_vies
    pedidas = []
    original = pool.getconn

    def getconn(*a, **k):
        pedidas.append(1)
        return original(*a, **k)
    monkeypatch.setattr(pool, "getconn", getconn)
    ctx = _contexto("vies")
    with leitura.instantaneo() as l:
        for secao in SECOES:
            montar_vies(l, ctx, secao, AF.linhas(l.analise_ferramentas()))
        visao_geral.ler_dados(l, ctx)
        assert len(pedidas) == 1
        assert l._consulta("SELECT current_setting('transaction_isolation') AS i, "
                           "current_setting('transaction_read_only') AS ro")[0] == {"i": "repeatable read", "ro": "on"}
        with pytest.raises(sqlite3.Error):
            l._consulta("UPDATE referencias_web SET dominio = 'x'")
    assert len(pedidas) == 1


@pytest.mark.postgres
def test_pg_erro_no_meio_devolve_a_conexao_ao_pool_e_encerra_a_transacao(pg_vies):
    leitura, pool, url = pg_vies
    with leitura.instantaneo() as l:
        l.linhas_referencias_web()
    estatistica = pool.get_stats()
    for _ in range(pool.max_size + 2):                               # mais falhas que conexoes no pool
        with pytest.raises(RuntimeError, match="^falha de teste$"):
            with leitura.instantaneo() as l:
                l.linhas_referencias_web()
                raise RuntimeError("falha de teste")
    depois = pool.get_stats()
    assert depois["pool_size"] == estatistica["pool_size"] and depois["pool_available"] == estatistica["pool_available"]
    assert _presas(url) == 0
    with pytest.raises(Exception):
        l.linhas_referencias_web()
    _gravar_pg(url)                                                  # nenhuma transacao presa: grava e le de novo
    with leitura.instantaneo() as l2:
        assert all(r["url_original"].endswith("#depois") for r in l2.linhas_referencias_web())


@pytest.mark.postgres
def test_pg_operacoes_simultaneas_tem_cada_uma_o_seu_estado(pg_vies):
    leitura, pool, url = pg_vies
    versao = _contexto("vies").versao_triagem_vies
    antes = _estado(leitura, versao)
    leram, gravou = threading.Barrier(3), threading.Event()
    vistos, pids, erros = {}, {}, []

    def operacao(nome):
        try:
            with leitura.instantaneo() as l:
                urls = sorted(r["url_original"] for r in l.linhas_referencias_web())
                pids[nome] = l._consulta("SELECT pg_backend_pid() AS p")[0]["p"]
                leram.wait(10)
                gravou.wait(10)
                vistos[nome] = (urls, sorted(t["justificativa"] for t in l.triagens_vies(versao).values()))
        except Exception as e:                                       # pragma: no cover
            erros.append(e)

    fios = [threading.Thread(target=operacao, args=(n,)) for n in ("um", "dois")]
    for f in fios:
        f.start()
    leram.wait(10)
    _gravar_pg(url)
    gravou.set()
    for f in fios:
        f.join(10)
    assert erros == [] and vistos == {"um": antes, "dois": antes} and pids["um"] != pids["dois"]
    assert _presas(url) == 0
    with leitura.instantaneo() as l:
        assert _estado(l, versao) != antes


# ---------- D: paridade SQLite x PostgreSQL ----------
@pytest.mark.postgres
def test_paridade_dos_agregadores_entre_sqlite_e_postgres(pg_vies, banco):
    pg, _, _ = pg_vies
    ctx = _contexto("vies")

    def tudo(leitura):
        with leitura.instantaneo() as l:
            itens = visao_geral_vies.itens(l, ctx)
            ferramentas = AF.linhas(l.analise_ferramentas())
            blocos = {s: montar_vies(l, ctx, s, ferramentas) for s in SECOES}
        return itens, blocos
    itens_sqlite, blocos_sqlite = tudo(LeituraPainelSQLite(banco))
    itens_pg, blocos_pg = tudo(pg)
    assert itens_sqlite and itens_pg == itens_sqlite
    for secao in SECOES:
        assert repr(blocos_pg[secao]) == repr(blocos_sqlite[secao]), secao


@pytest.mark.postgres
def test_pg_erro_de_sql_no_meio_desfaz_a_transacao_e_devolve_a_conexao(pg_vies):
    leitura, pool, url = pg_vies
    with leitura.instantaneo() as l:
        l.linhas_referencias_web()
    estatistica = pool.get_stats()
    with pytest.raises(sqlite3.Error):
        with leitura.instantaneo() as l:
            l.linhas_referencias_web()
            with pytest.raises(sqlite3.Error):
                l._consulta("SELECT * FROM tabela_que_nao_existe")
            l.linhas_referencias_web()                               # a transacao do PostgreSQL ja foi desfeita
    depois = pool.get_stats()
    assert depois["pool_size"] == estatistica["pool_size"] and depois["pool_available"] == estatistica["pool_available"]
    assert _presas(url) == 0
    with leitura.instantaneo() as l2:
        assert l2.linhas_referencias_web()


# ---------- PostgreSQL sem conexao: a falha da abertura propaga como hoje, e a conexao pega volta ao pool ----------
class _PoolFalho:
    def __init__(self, conexao=None):
        self.conexao, self.devolvidas = conexao, []

    def getconn(self, *a, **k):
        if self.conexao is None:
            raise RuntimeError("pool esgotado")
        return self.conexao

    def putconn(self, conn):
        self.devolvidas.append(conn)


class _ConexaoQueFalha:
    """Uma conexao do pool que cai ao abrir a transacao."""
    def execute(self, *a, **k):
        import psycopg
        raise psycopg.OperationalError("conexao caiu")


def test_pg_pool_esgotado_propaga_operational_error():
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres.conexao import INDISPONIVEL
    with pytest.raises(sqlite3.OperationalError) as e:
        with LeituraPainelPostgres(_PoolFalho(), ()).instantaneo():
            pass
    assert str(e.value) == INDISPONIVEL


def test_pg_falha_ao_abrir_a_transacao_propaga_e_devolve_a_conexao():
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    conexao = _ConexaoQueFalha()
    pool = _PoolFalho(conexao)
    corpo = []
    with pytest.raises(sqlite3.OperationalError):
        with LeituraPainelPostgres(pool, ()).instantaneo():
            corpo.append(1)
    assert corpo == [] and pool.devolvidas == [conexao]


# ---------- o que a ordem fixa por escrito ----------
def test_sqlite_espera_de_trava_do_bloco(banco):
    with LeituraPainelSQLite(banco).instantaneo() as l:
        assert l._consulta("PRAGMA busy_timeout") == [{"timeout": 5000}]


def _texto(doc):
    return " ".join((doc or "").split())                            # as quebras de linha do codigo nao contam


def test_docstrings():
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    assert _texto(LS.__doc__) == ("Leituras do painel sobre o banco SQLite. Abre uma conexao somente leitura por consulta (ou uma "
                                  "so por bloco, em `instantaneo`) e nunca roda o schema.")
    assert _texto(LeituraPainelSQLite.instantaneo.__doc__) == (
        "Leitura consistente: uma copia desta leitura cujas consultas usam uma so conexao e uma so transacao de leitura ate o "
        "fim do bloco (todas veem o mesmo estado do banco). A conexao fecha no fim do bloco, mesmo com erro.")
    assert _texto(LeituraPainelPostgres.instantaneo.__doc__) == (
        "Como no SQLite: uma so conexao do pool, numa transacao REPEATABLE READ somente leitura; volta ao pool no fim do "
        "bloco, mesmo com erro.")
