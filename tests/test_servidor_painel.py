"""Painel no servidor (atras do Caddy, com HTTPS): sempre com login, dominio vindo de PAINEL_HOSTS, cabecalhos do proxy
confiados, cookies seguros em https; e o SQLite em WAL com synchronous=FULL em toda conexao que grava."""
import logging
import shutil
import sqlite3
import sys

import pytest
import uvicorn
from fastapi.testclient import TestClient

import main
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite

DOMINIO = "revisao.exemplo.br"


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.fixture
def servidor(ambiente_cli, monkeypatch, copiar_demo):
    """Copia do banco de demonstracao da sessao em data/ temporario; uvicorn.run e trocado por um gravador (nada escuta na rede)."""
    banco, raw = copiar_demo("demo_servidor")
    (ambiente_cli / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(banco, ambiente_cli / "data" / "demo.db")
    shutil.copytree(raw, ambiente_cli / "data" / "raw_demo")
    chamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: chamadas.append((app, k)))
    monkeypatch.setenv("PAINEL_HOSTS", f" {DOMINIO} , outro.exemplo.br ,")
    return ambiente_cli, chamadas


def test_servidor_liga_o_login_ate_na_demonstracao_e_confia_no_proxy(servidor, monkeypatch):
    dados, chamadas = servidor
    _rodar(monkeypatch, "painel", "--demo", "--servidor", "--porta", "8000")
    (app, k), = chamadas
    assert k == {"host": "0.0.0.0", "port": 8000, "log_level": "warning", "proxy_headers": True,
                 "forwarded_allow_ips": "127.0.0.1"}
    assert (dados / "data" / "contas_demo.db").exists()
    cli = TestClient(app, base_url=f"https://{DOMINIO}")
    r = cli.get("/entrar")
    assert r.status_code == 200 and 'action="/entrar"' in r.text
    assert cli.get("/chamadas", follow_redirects=False).status_code in (303,)   # sem login, a pagina restrita pede entrada


@pytest.mark.parametrize("valor,esperado", [("172.18.0.2", "172.18.0.2"), ("*", "*"), ("", "127.0.0.1"), ("   ", "127.0.0.1"),
                                             (" 10.0.0.1 ", "10.0.0.1")])
def test_proxy_confiavel_vem_de_painel_proxy_ips(servidor, monkeypatch, valor, esperado):
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_PROXY_IPS", valor)
    _rodar(monkeypatch, "painel", "--demo", "--servidor")
    assert chamadas[0][1]["forwarded_allow_ips"] == esperado and chamadas[0][1]["port"] == 8000


@pytest.mark.parametrize("valor", ["*", "https://revisao.exemplo.br", "revisao.exemplo.br:443", "revisao.exemplo.br/",
                                   "exemplo.br,*", "-revisao.br", "revisao..br", "revi são.br"])
def test_painel_hosts_so_aceita_nomes_de_dominio(servidor, monkeypatch, valor):
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_HOSTS", valor)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel", "--demo", "--servidor")
    assert str(e.value).startswith("PAINEL_HOSTS aceita só nomes de domínio, sem esquema, porta, barra ou '*': ")
    assert chamadas == []


def test_painel_hosts_em_maiusculas_vale_em_minusculas(servidor, monkeypatch):
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_HOSTS", "REVISAO.Exemplo.BR")
    _rodar(monkeypatch, "painel", "--demo", "--servidor")
    assert TestClient(chamadas[0][0], base_url="https://revisao.exemplo.br").get("/entrar").status_code == 200


@pytest.mark.parametrize("comando", [["painel", "--simulado", "--demo"], ["painel", "--simulado", "--demo", "--servidor"],
                                     ["usuario-admin", "--login", "chefe", "--nome", "Chefe", "--simulado", "--demo"]])
def test_simulado_e_demo_juntos_sao_recusados(servidor, monkeypatch, comando):
    _, chamadas = servidor
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: pytest.fail("nao pode pedir senha antes de recusar"))
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, *comando)
    assert str(e.value) == "Use --simulado ou --demo, não os dois." and chamadas == []


@pytest.mark.parametrize("host,esperado", [(DOMINIO, 200), ("outro.exemplo.br", 200), ("localhost", 200), ("127.0.0.1", 200),
                                           ("malicioso.exemplo", 400), ("revisao.exemplo.br.malicioso", 400)])
def test_hosts_aceitos_sao_o_dominio_e_o_local(servidor, monkeypatch, host, esperado):
    _, chamadas = servidor
    _rodar(monkeypatch, "painel", "--demo", "--servidor")
    app = chamadas[0][0]
    assert TestClient(app, base_url=f"https://{host}").get("/entrar").status_code == esperado


@pytest.mark.parametrize("valor", [None, "", "   ", " , ,"])
def test_servidor_sem_dominio_e_recusado(servidor, monkeypatch, valor):
    _, chamadas = servidor
    if valor is None:
        monkeypatch.delenv("PAINEL_HOSTS")
    else:
        monkeypatch.setenv("PAINEL_HOSTS", valor)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel", "--demo", "--servidor")
    assert str(e.value) == ("--servidor exige a variável PAINEL_HOSTS com o domínio do painel "
                            "(por exemplo, revisao.exemplo.br; vários separados por vírgula).")
    assert chamadas == []


def test_servidor_recusa_somente_leitura(servidor, monkeypatch):
    _, chamadas = servidor
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel", "--demo", "--servidor", "--somente-leitura")
    assert str(e.value) == "--somente-leitura desliga o login e não vale com --servidor." and chamadas == []


def test_sem_servidor_continua_so_local(servidor, monkeypatch):
    _, chamadas = servidor
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel", "--demo", "--host", "0.0.0.0")
    assert str(e.value) == "O painel só aceita conexões locais (127.0.0.1)." and chamadas == []
    _rodar(monkeypatch, "painel", "--demo")
    app, k = chamadas[0]
    assert k == {"host": "127.0.0.1", "port": 8000, "log_level": "warning"}
    assert TestClient(app, base_url="http://127.0.0.1").get("/entrar").status_code == 404   # a demonstracao local continua sem login


def test_cookies_seguros_no_servidor_ate_em_http(servidor, monkeypatch):
    _, chamadas = servidor
    _rodar(monkeypatch, "painel", "--demo", "--servidor")
    app = chamadas[0][0]
    for base in (f"https://{DOMINIO}", "http://localhost"):
        r = TestClient(app, base_url=base).get("/entrar")
        cookie = next(v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("__session="))
        assert "Secure" in cookie, (base, cookie)


def test_admin_da_demonstracao_vai_para_contas_demo(servidor, monkeypatch):
    dados, _ = servidor
    respostas = iter(["senha-boa-123456", "senha-boa-123456"])
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(respostas))
    _rodar(monkeypatch, "usuario-admin", "--login", "chefe", "--nome", "Chefe", "--demo")
    assert ContasSQLite(dados / "data" / "contas_demo.db").usuario_por_login("chefe")["grupo"] == "Administrador"
    assert not (dados / "data" / "contas.db").exists()


def test_caminho_das_contas_por_banco():
    from pathlib import Path
    from types import SimpleNamespace
    f = SimpleNamespace(caminho_banco=Path("/x/dados/busca.db"))
    assert main._caminho_contas(f, False) == Path("/x/dados/contas.db")
    assert main._caminho_contas(f, True) == Path("/x/dados/contas_simulado.db")
    assert main._caminho_contas(f, False, True) == Path("/x/dados/contas_demo.db")


def test_banco_da_pesquisa_e_de_contas_em_wal_com_synchronous_full(tmp_path):
    repo = RepositorioSQLite(tmp_path / "busca.db")
    assert repo.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert repo.conn.execute("PRAGMA synchronous").fetchone()[0] == 2          # 2 = FULL
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    with contas._conexao() as conn:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert sqlite3.connect(tmp_path / "contas.db").execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_escritor_confirma_com_leitor_no_meio_de_uma_leitura(tmp_path):
    """Com WAL, um leitor com a transacao aberta nao impede o escritor de confirmar (no modo antigo, o COMMIT daria
    "database is locked"); o leitor continua vendo o retrato do inicio da sua leitura."""
    repo = RepositorioSQLite(tmp_path / "busca.db")
    leitor = sqlite3.connect(f"file:{(tmp_path / 'busca.db').as_posix()}?mode=ro", uri=True, isolation_level=None)
    sql = "SELECT COUNT(*) FROM meta_schema WHERE chave='teste_wal'"
    leitor.execute("BEGIN")
    assert leitor.execute(sql).fetchone()[0] == 0
    repo.conn.execute("PRAGMA busy_timeout = 100")
    repo.conn.execute("INSERT INTO meta_schema (chave, valor) VALUES ('teste_wal', '1')")
    repo.conn.commit()
    assert leitor.execute(sql).fetchone()[0] == 0
    leitor.execute("COMMIT")
    assert leitor.execute(sql).fetchone()[0] == 1


def test_wal_e_ligado_so_uma_vez_e_falha_vira_aviso(tmp_path, caplog):
    from infra.sqlite_wal import ligar_wal
    caminho = tmp_path / "antigo.db"
    antigo = sqlite3.connect(caminho, isolation_level=None)
    antigo.execute("CREATE TABLE t (a)")
    outro = sqlite3.connect(caminho, isolation_level=None)
    outro.execute("BEGIN")
    outro.execute("SELECT * FROM t").fetchall()                       # outra conexao segurando uma leitura
    antigo.execute("PRAGMA busy_timeout = 100")
    with caplog.at_level(logging.WARNING):
        assert ligar_wal(antigo, caminho) == "delete"
    assert f"SQLite: não foi possível ligar o modo WAL em {caminho}" in caplog.text
    outro.execute("COMMIT")
    assert ligar_wal(antigo, caminho) == "wal"
    outro.execute("BEGIN")
    outro.execute("SELECT * FROM t").fetchall()
    assert ligar_wal(antigo, caminho) == "wal"                        # ja em WAL: nada a trocar, mesmo com leitor aberto
