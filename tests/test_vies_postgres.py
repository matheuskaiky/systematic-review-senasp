"""O banco `vies` no PostgreSQL da nuvem: um esquema próprio no mesmo banco, as contas compartilhadas no esquema public,
migração e importação por esquema, e o banco real intacto."""
import sys

import psycopg
import pytest

import config.settings as S
from adaptadores import migrador_postgres as M
from adaptadores.contas_postgres import ContasPostgres
from adaptadores.leitura_postgres import LeituraPainelPostgres
from adaptadores.postgres import conexao as CX, importador as I
from dominio import autenticacao as A
from test_triagem_vies import construir_vies

MSG_POOLER = ("Fora do esquema public, use a conexão direta (sem -pooler): o pool do Neon não guarda o esquema escolhido "
              "entre as transações.")
POOLER = "postgresql://u:s@ep-x-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"
DIRETA = "postgresql://u:s@ep-x.sa-east-1.aws.neon.tech/neondb?sslmode=require"


# ---------- regras sem banco ----------
def test_esquema_de_cada_banco():
    assert S.ESQUEMAS_POSTGRES == {"real": "public", "vies": "vies"} and set(S.ESQUEMAS_POSTGRES) == set(S.BANCOS)


@pytest.mark.parametrize("esquema, valido", [
    ("public", True), ("vies", True), ("_x9", True), ("a" * 63, True),
    ("", False), ("a" * 64, False), ("Vies", False), ("vi-es", False), ("9vies", False), ('vies"; drop', False),
    (" vies", False), ("vies ", False), ("viés", False), (None, False), (1, False), (["vies"], False),
    ("vies\n", False), ("pg_catalog", False), ("pg_vies", False), ("pg", True),
])
def test_nome_do_esquema(esquema, valido):
    if valido:
        assert M.conferir_esquema(esquema) == esquema
    else:
        with pytest.raises(M.ErroMigracao) as e:
            M.conferir_esquema(esquema)
        assert str(e.value) == "Esquema do PostgreSQL inválido."


@pytest.mark.parametrize("url, esquema, mensagem", [
    (POOLER, "vies", MSG_POOLER),
    (DIRETA, "Vies", "Esquema do PostgreSQL inválido."),
    ("postgresql://u:s@ep-x.neon.tech/neondb", "vies", CX.TLS),
    ("nada", "vies", CX.URL_INVALIDA),
    ("nada", "Vies", "Esquema do PostgreSQL inválido."),                         # o esquema e conferido antes da URL
    ("postgresql://u:s@ep-x-pooler.sa-east-1.aws.neon.tech/neondb", "vies", CX.TLS),  # TLS antes do pooler
])
def test_pool_fora_do_public_recusa_antes_de_conectar(url, esquema, mensagem):
    with pytest.raises(ValueError) as e:
        CX.criar_pool(url, esquema=esquema)
    assert str(e.value) == mensagem


def test_pool_do_banco_real_continua_aceitando_o_pooler(monkeypatch):
    abertos = []
    class Pool:
        check_connection = None

        def __init__(self, *a, **k):
            abertos.append(k)
    monkeypatch.setattr(CX, "ConnectionPool", Pool)
    assert isinstance(CX.criar_pool(POOLER), Pool) and abertos[0]["configure"] is CX._configurar


def test_mensagem_do_pooler():
    assert CX.POOLER_ESQUEMA == MSG_POOLER


def test_importar_recusa_esquema_invalido(tmp_path):
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(tmp_path / "x.db", DIRETA, esquema="x-y")
    assert str(e.value) == "Esquema do PostgreSQL inválido."


@pytest.mark.parametrize("url, mensagem", [
    (POOLER, "Use a conexão direta (sem -pooler) para migrar: a URL do pool não mantém a trava da migração."),
    ("postgresql://u:s@ep-x.neon.tech/neondb", "Conexão remota sem TLS: acrescente sslmode=require à URL do PostgreSQL."),
])
def test_importar_recusa_pooler_e_falta_de_tls_antes_de_ler_o_arquivo(url, mensagem, tmp_path):
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(tmp_path / "nao_existe.db", url, esquema="vies")
    assert str(e.value) == mensagem


def test_usuario_admin_com_banco_no_postgres_e_recusado(monkeypatch):
    import main
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setattr(sys, "argv", ["main.py", "usuario-admin", "--banco", "vies", "--login", "x", "--nome", "X"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert str(e.value) == "usuario-admin no PostgreSQL não usa --banco: as contas são as mesmas nos dois bancos (esquema public)."


def test_pg_importar_do_banco_real_e_recusado(monkeypatch):
    import main
    monkeypatch.setenv("DATABASE_URL_DIRECT", "")
    for argv in (["pg-importar"], ["pg-importar", "--banco", "real"]):
        monkeypatch.setattr(sys, "argv", ["main.py", *argv])
        with pytest.raises(SystemExit) as e:
            main.main()
        assert str(e.value) == "pg-importar só vale com --banco vies: o banco real chega à nuvem pelo enviar (D97)."


def test_pg_importar_sem_url_e_recusado(monkeypatch):
    import main
    monkeypatch.setenv("DATABASE_URL_DIRECT", "")
    monkeypatch.setattr(sys, "argv", ["main.py", "pg-importar", "--banco", "vies"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert str(e.value) == "Defina DATABASE_URL_DIRECT no ambiente: a conexão direta do PostgreSQL (no Neon, a URL sem -pooler)."


# ---------- contra PostgreSQL real ----------
def _tabelas(url, esquema):
    with psycopg.connect(url) as c:
        return {t for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (esquema,))}


def _linhas(url, esquema, tabela):
    with psycopg.connect(url) as c:
        return c.execute(f'SELECT COUNT(*) FROM "{esquema}"."{tabela}"').fetchone()[0]


@pytest.mark.postgres
def test_migrar_o_vies_cria_so_o_esquema_dele_e_cada_esquema_tem_o_seu_registro(pg_url):
    todos = M.aplicar(pg_url, esquema="vies")
    assert todos and _tabelas(pg_url, "public") == set()
    assert M.pendentes(pg_url) == todos and M.pendentes(pg_url, esquema="vies") == []
    assert M.aplicar(pg_url) == todos and M.aplicar(pg_url, esquema="vies") == []
    assert _tabelas(pg_url, "vies") == _tabelas(pg_url, "public")
    with psycopg.connect(pg_url) as c:
        assert c.execute("SELECT COUNT(*) FROM vies.versao_esquema").fetchone()[0] == len(todos)
        assert c.execute("SELECT COUNT(*) FROM public.versao_esquema").fetchone()[0] == len(todos)


@pytest.mark.postgres
def test_pool_do_vies_enxerga_so_o_esquema_dele_e_o_public_fica_como_antes(pg_url):
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    vies, real = CX.criar_pool(pg_url, esquema="vies"), CX.criar_pool(pg_url)
    try:
        with vies.connection() as c:
            assert c.execute("SELECT current_schema(), current_setting('search_path')").fetchone() == ("vies", "vies")
        with real.connection() as c:
            assert c.execute("SELECT current_schema()").fetchone()[0] == "public"
            assert c.execute("SELECT current_setting('search_path')").fetchone()[0] == '"$user", public'
        assert dict((t, cols) for t, _, _, cols in CX.chaves_do_banco(vies)) == dict((t, cols) for t, _, _, cols in CX.chaves_do_banco(real))
    finally:
        vies.close()
        real.close()


@pytest.mark.postgres
def test_importar_o_vies_grava_so_no_esquema_dele_e_nao_repete(pg_url, tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    relatorio = I.importar(tmp_path / "busca.db", pg_url, esquema="vies")
    assert relatorio["referencias_web"][0] == relatorio["referencias_web"][1] == _linhas(pg_url, "vies", "referencias_web") > 0
    assert all(a == b for a, b in relatorio.values())
    assert _linhas(pg_url, "public", "referencias_web") == _linhas(pg_url, "public", "execucoes") == 0
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(tmp_path / "busca.db", pg_url, esquema="vies")
    assert str(e.value).endswith("já tem dados: a importação só vale para um banco vazio.")
    with psycopg.connect(pg_url) as c:                 # a identidade continua depois do maior id importado
        maior = c.execute("SELECT MAX(chamada_id) FROM vies.chamadas").fetchone()[0]
        assert c.execute("SELECT nextval(pg_get_serial_sequence('vies.chamadas', 'chamada_id'))").fetchone()[0] == maior + 1


@pytest.mark.postgres
def test_importar_num_esquema_que_nao_existe_e_recusado(pg_url, tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    M.aplicar(pg_url)
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(tmp_path / "busca.db", pg_url, esquema="vies")
    assert str(e.value) == "O PostgreSQL ainda não tem o esquema: rode antes python main.py pg-migrar."
    assert _linhas(pg_url, "public", "execucoes") == 0


@pytest.mark.postgres
def test_painel_do_vies_le_o_vies_e_as_contas_do_public(pg_url, tmp_path, monkeypatch):
    from composicao import Fabrica, banco_escolhido
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    I.importar(tmp_path / "busca.db", pg_url, esquema="vies")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    with banco_escolhido("vies"):
        fab = Fabrica()
        assert fab.esquema_postgres_pendente() == [] and fab.esquema_postgres_pendente(contas=True) == []
        assert isinstance(fab.leitura_painel(), LeituraPainelPostgres)
        assert len(fab.leitura_painel().linhas_referencias_web()) == _linhas(pg_url, "vies", "referencias_web")
        contas = fab.contas(None)
        assert isinstance(contas, ContasPostgres) and fab.postgres_contas is not fab.postgres
        contas.garantir_padrao()
        gid = next(g["grupo_id"] for g in contas.grupos() if g["nome"] == "Administrador")
        contas.criar_usuario("ana", "Ana", gid, A.hash_senha("senha-de-teste-123"), "2026-10-22T00:00:00+00:00")
    assert _linhas(pg_url, "public", "usuarios") == 1 and _linhas(pg_url, "vies", "usuarios") == 0
    with banco_escolhido("real"):
        fab = Fabrica()
        assert fab.postgres_contas is fab.postgres
        assert fab.leitura_painel().linhas_referencias_web() == []
        assert [u["login"] for u in fab.contas(None).listar_usuarios()] == ["ana"]
    fab.postgres[0].close()


@pytest.mark.postgres
def test_painel_do_vies_com_esquema_desatualizado(pg_url, monkeypatch):
    from composicao import Fabrica, banco_escolhido
    M.aplicar(pg_url)
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    with banco_escolhido("vies"):
        fab = Fabrica()
        assert fab.esquema_postgres_pendente() == M.pendentes(pg_url, esquema="vies") != []
        assert fab.esquema_postgres_pendente(contas=True) == []


# ---------- linha de comando contra PostgreSQL real ----------
@pytest.fixture
def vies_local(tmp_path, monkeypatch):
    """O banco local do vies num diretorio de teste (as pastas que o banco_escolhido usa)."""
    monkeypatch.setattr(S, "DATA_DIR", tmp_path / "data")
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", tmp_path / "data" / "busca.db")
    monkeypatch.setitem(S.OPCOES["local"], "raiz", tmp_path / "data" / "raw")
    return tmp_path / "data" / "vies" / "busca.db"


def _main(monkeypatch, *argv):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.mark.postgres
def test_pg_migrar_com_banco_vies_pela_linha_de_comando(pg_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL_DIRECT", pg_url)
    _main(monkeypatch, "pg-migrar", "--banco", "vies")
    assert capsys.readouterr().out.startswith("Migrações aplicadas: V0001_compatibilidade.sql")
    assert "referencias_web" in _tabelas(pg_url, "vies") and _tabelas(pg_url, "public") == set()


@pytest.mark.postgres
def test_pg_importar_na_ordem_das_conferencias(pg_url, vies_local, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://u:s@ep-x-pooler.neon.tech/neondb?sslmode=require")
    with pytest.raises(SystemExit) as e:                       # o arquivo local antes da URL da nuvem
        _main(monkeypatch, "pg-importar", "--banco", "vies")
    assert str(e.value) == f"O banco local {vies_local} não existe."
    construir_vies(vies_local, vies_local.parent / "raw")
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "pg-importar", "--banco", "vies")
    assert str(e.value) == "Use a conexão direta (sem -pooler) para migrar: a URL do pool não mantém a trava da migração."
    monkeypatch.setenv("DATABASE_URL_DIRECT", pg_url)
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "pg-importar", "--banco", "vies")
    assert str(e.value) == "O esquema PostgreSQL do banco vies está desatualizado: rode antes python main.py pg-migrar --banco vies."
    M.aplicar(pg_url, esquema="vies")
    capsys.readouterr()
    _main(monkeypatch, "pg-importar", "--banco", "vies")
    saida = capsys.readouterr().out.splitlines()
    assert saida[-1].startswith("Importação conferida: ") and saida[-1].endswith(" (esquema vies).")
    assert _linhas(pg_url, "vies", "referencias_web") > 0 and _tabelas(pg_url, "public") == set()


def _abrir(monkeypatch, banco):
    import uvicorn
    import painel.app as painel_app
    capturado = {}
    original = painel_app.criar_app
    monkeypatch.setattr(painel_app, "criar_app", lambda leitura, fab, bruto, contexto, **kw:
                        capturado.update(contexto=contexto) or original(leitura, fab, bruto, contexto, **kw))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    _main(monkeypatch, "painel", "--banco", banco)
    return capturado["contexto"]


@pytest.mark.postgres
def test_painel_no_postgres_recebe_envios_so_no_banco_real(pg_url, monkeypatch):
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    assert _abrir(monkeypatch, "real").aceita_envios is True
    vies = _abrir(monkeypatch, "vies")
    assert (vies.aceita_envios, vies.banco) == (False, "vies")


@pytest.mark.postgres
def test_painel_do_vies_no_postgres_confere_os_dois_esquemas_nesta_ordem(pg_url, monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    with pytest.raises(SystemExit) as e:                       # nada migrado: o esquema da pesquisa vem primeiro
        _abrir(monkeypatch, "vies")
    assert str(e.value).startswith("O esquema PostgreSQL está desatualizado: rode python main.py pg-migrar --banco vies (faltam: V0001")
    M.aplicar(pg_url, esquema="vies")
    with pytest.raises(SystemExit) as e:                       # o vies em dia, as contas (public) nao
        _abrir(monkeypatch, "vies")
    assert str(e.value).startswith("O esquema PostgreSQL das contas está desatualizado: rode python main.py pg-migrar (faltam: V0001")
