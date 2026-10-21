"""O painel inteiro sobre o PostgreSQL (painel na nuvem, D96): as paginas dao o mesmo HTML que sobre o SQLite com os
mesmos dados (o banco de demonstracao importado), e as gravacoes (verificar, desfazer, triar, sugerir) e o download do
catalogo funcionam com login. PostgreSQL real descartavel (PG_TESTE_URL)."""
import io
import re
import shutil
import sqlite3

import openpyxl
import pytest
from fastapi.testclient import TestClient

from adaptadores import migrador_postgres as M
from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_postgres import ContasPostgres
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_postgres import LeituraPainelPostgres
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.postgres import importador as I
from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
from adaptadores.repositorio_postgres import RepositorioPostgres
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from config.categorias_referencias import CATEGORIAS_REFERENCIAS
from config.eixos_tematicos import EIXOS_TEMATICOS
from config.modelos_exportacao import MODELOS_REFERENCIAS
from dominio import autenticacao as A
from painel.app import Contexto, criar_app
from test_painel_analises import SECOES

pytestmark = pytest.mark.postgres
SENHA = "senha-de-teste-123"


def _contexto(tmp):
    return Contexto(banco="real", nome_banco="demo", somente_leitura=False, pasta_backup=tmp / "backups", ufs=dict(C.UFS),
                    status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                    hosts_permitidos=("testserver",), autenticacao=True, modelos_referencias=dict(MODELOS_REFERENCIAS),
                    categorias_referencias=dict(CATEGORIAS_REFERENCIAS), eixos_tematicos=dict(EIXOS_TEMATICOS))


def _entrar(cli):
    csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get("/entrar").text).group(1)
    r = cli.post("/entrar", data={"login": "chefe", "senha": SENHA, "proximo": "/", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    return cli


@pytest.fixture(scope="module")
def paineis(copiar_demo, tmp_path_factory, pg_url_modulo):
    from datetime import datetime, timezone
    url = pg_url_modulo
    banco, raw = copiar_demo("painel_pg")
    tmp = tmp_path_factory.mktemp("painel_pg")
    sq = tmp / "sqlite.db"
    shutil.copy(banco, sq)
    M.aplicar(url)
    I.importar(banco, url)
    agora = datetime.now(timezone.utc).isoformat()
    contas_sq = ContasSQLite(tmp / "contas.db")
    contas_sq.garantir_padrao()
    contas_sq.definir_admin("chefe", "Coordenação", A.hash_senha(SENHA), agora)
    pool = criar_pool(url, maximo=6)
    chaves = chaves_do_banco(pool)
    contas_pg = ContasPostgres(pool, chaves)
    contas_pg.garantir_padrao()
    contas_pg.definir_admin("chefe", "Coordenação", A.hash_senha(SENHA), agora)
    app_sq = criar_app(LeituraPainelSQLite(sq), lambda: RepositorioSQLite(sq), BrutoLocal(raw), _contexto(tmp), contas=contas_sq)
    app_pg = criar_app(LeituraPainelPostgres(pool, chaves), lambda: RepositorioPostgres(pool, chaves), BrutoLocal(raw),
                       _contexto(tmp), contas=contas_pg)
    con = sqlite3.connect(sq)
    ids = {"achado": con.execute("SELECT MIN(achado_id) FROM achados").fetchone()[0],
           "artigo": con.execute("SELECT MIN(artigo_id) FROM artigos").fetchone()[0],
           "runs": [r[0] for r in con.execute("SELECT run_id FROM execucoes ORDER BY rowid")],
           "chamada": con.execute("SELECT MIN(chamada_id) FROM chamadas WHERE raw_path IS NOT NULL").fetchone()[0],
           "pendente": con.execute("SELECT MIN(achado_id) FROM achados WHERE verificado = 0").fetchone()[0],
           "artigo_pendente": con.execute("SELECT MIN(a.artigo_id) FROM artigos a LEFT JOIN triagem t ON t.artigo_id = a.artigo_id "
                                          "WHERE COALESCE(t.decisao, 'pendente') = 'pendente'").fetchone()[0],
           "banco": sq}
    con.close()
    yield _entrar(TestClient(app_sq)), _entrar(TestClient(app_pg)), ids, url, pool
    pool.close()


def _sem_variaveis(html):
    html = re.sub(r'name="csrf" value="[^"]+"', 'name="csrf" value=""', html)
    html = re.sub(r"\b\d{2}/\d{2}/\d{4} \d{2}:\d{2}\b", "DATA", html)         # "agora" de cada processo (ultimo acesso etc.)
    return html.replace("PostgreSQL", "demo")


def _rotas(i):
    web, outra = i["runs"][0], i["runs"][-1]
    return ["/", "/estados", "/estados/SP", "/achados", "/achados?p=2", "/achados?uf=SP&verificacao=pendente",
            "/achados?q=reconhecimento", "/achados?evidencia=0&confianca=baixa", f"/achados/{i['achado']}",
            "/execucoes", f"/execucoes/{web}", f"/execucoes/comparar?a={web}&b={outra}", "/chamadas",
            "/chamadas?etapa=classificacao", f"/chamadas/{i['chamada']}", "/literatura", "/literatura/artigos",
            "/literatura/artigos?q=estudo", f"/literatura/artigos/{i['artigo']}", "/literatura/prisma", "/sobre",
            "/analises", "/triagem-escopo", "/triagem-escopo?fonte=pagina", "/classificadores", "/solucoes", "/metodologia",
            "/buscar-texto?q=reconhecimento", "/revisao/achados", "/literatura/triagem",
            "/admin/usuarios", "/admin/grupos", "/admin/auditoria", "/estatisticas-usuarios"] + [f"/analises?secao={s}" for s in SECOES]


def test_paginas_iguais_nos_dois_bancos(paineis):
    sq, pg, ids, _, _ = paineis
    diferentes = []
    for rota in _rotas(ids):
        a, b = sq.get(rota), pg.get(rota)
        if a.status_code != b.status_code or _sem_variaveis(a.text) != _sem_variaveis(b.text):
            diferentes.append((rota, a.status_code, b.status_code))
    assert diferentes == []


def _form(cli, rota):
    pagina = cli.get(rota).text
    versao = re.search(r'name="versao" value="([^"]*)"', pagina)
    return re.search(r'name="csrf" value="([^"]+)"', pagina).group(1), (versao.group(1) if versao else "")


def _estado_sqlite(banco, sql, args):
    return [tuple(r) for r in sqlite3.connect(banco).execute(sql, args).fetchall()]


def _estado_pg(url, sql, args):
    import psycopg
    with psycopg.connect(url) as c:
        return [tuple(r) for r in c.execute(sql.replace("?", "%s"), args).fetchall()]


def test_verificar_e_desfazer_iguais_nos_dois_bancos(paineis):
    sq, pg, ids, url, _ = paineis
    achado = ids["pendente"]
    for cli in (sq, pg):
        csrf, versao = _form(cli, f"/achados/{achado}")
        r = cli.post(f"/achados/{achado}/verificar", data={"status_final": "em_uso", "versao": versao, "csrf": csrf}, follow_redirects=False)
        assert r.status_code == 303
    q = "SELECT verificado, status_final, verificado_por FROM achados WHERE achado_id = ?"
    assert _estado_pg(url, q, (achado,)) == _estado_sqlite(ids["banco"], q, (achado,)) == [(1, "em_uso", "Coordenação")]
    for cli in (sq, pg):
        csrf, _ = _form(cli, f"/achados/{achado}")
        assert cli.post(f"/achados/{achado}/desfazer", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    q2 = "SELECT verificado, status_final FROM achados WHERE achado_id = ?"
    assert _estado_pg(url, q2, (achado,)) == _estado_sqlite(ids["banco"], q2, (achado,)) == [(0, None)]
    q3 = "SELECT COUNT(*), SUM(desfeita) FROM achados_revisoes WHERE achado_id = ?"
    assert _estado_pg(url, q3, (achado,)) == _estado_sqlite(ids["banco"], q3, (achado,))


def test_triar_igual_nos_dois_bancos(paineis):
    sq, pg, ids, url, _ = paineis
    artigo = ids["artigo_pendente"]
    for cli in (sq, pg):
        csrf, versao = _form(cli, f"/literatura/artigos/{artigo}")
        r = cli.post(f"/literatura/artigos/{artigo}/triar", data={"decisao": "excluir", "motivo": "fora do escopo",
                                                                  "versao": versao, "csrf": csrf}, follow_redirects=False)
        assert r.status_code == 303
    q = "SELECT decisao, motivo, revisor FROM triagem WHERE artigo_id = ?"
    assert _estado_pg(url, q, (artigo,)) == _estado_sqlite(ids["banco"], q, (artigo,)) == [("excluir", "fora do escopo", "Coordenação")]


def test_catalogo_baixado_do_postgres_igual_ao_do_sqlite(paineis):
    sq, pg, _, _, _ = paineis

    def abas(cli):
        wb = openpyxl.load_workbook(io.BytesIO(cli.get("/literatura/catalogo.xlsx?modelo=professor").content), read_only=True)
        return {n: [tuple(r) for r in wb[n].iter_rows(values_only=True)] for n in wb.sheetnames}
    assert abas(pg) == abas(sq)


ROTAS_SEM_ID = ["/", "/estados", "/estados/SP", "/achados", "/achados?uf=SP&verificacao=pendente", "/achados?q=reconhecimento",
                "/execucoes", "/chamadas", "/literatura", "/literatura/artigos", "/literatura/artigos?q=estudo",
                "/literatura/prisma", "/sobre", "/analises", "/triagem-escopo", "/classificadores", "/solucoes", "/metodologia",
                "/buscar-texto?q=reconhecimento", "/revisao/achados", "/literatura/triagem", "/admin/usuarios", "/admin/grupos",
                "/admin/auditoria", "/estatisticas-usuarios"] + [f"/analises?secao={s}" for s in SECOES]


def test_painel_no_banco_vazio_igual_ao_sqlite_vazio(pg_url, tmp_path):
    """O banco da nuvem comeca vazio (so as migracoes e a conta do administrador): toda pagina abre e da o mesmo HTML
    que um SQLite vazio, e o catalogo baixa igual."""
    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc).isoformat()
    sq = tmp_path / "vazio.db"
    RepositorioSQLite(sq).fechar()                                  # so o esquema
    raw = tmp_path / "raw"
    raw.mkdir()
    contas_sq = ContasSQLite(tmp_path / "contas.db")
    contas_sq.garantir_padrao()
    contas_sq.definir_admin("chefe", "Coordenação", A.hash_senha(SENHA), agora)
    M.aplicar(pg_url)
    pool = criar_pool(pg_url)
    try:
        chaves = chaves_do_banco(pool)
        contas_pg = ContasPostgres(pool, chaves)
        contas_pg.garantir_padrao()
        contas_pg.definir_admin("chefe", "Coordenação", A.hash_senha(SENHA), agora)
        sq_cli = _entrar(TestClient(criar_app(LeituraPainelSQLite(sq), lambda: RepositorioSQLite(sq), BrutoLocal(raw),
                                              _contexto(tmp_path), contas=contas_sq)))
        pg_cli = _entrar(TestClient(criar_app(LeituraPainelPostgres(pool, chaves), lambda: RepositorioPostgres(pool, chaves),
                                              BrutoLocal(raw), _contexto(tmp_path), contas=contas_pg)))
        diferentes = []
        for rota in ROTAS_SEM_ID:
            a, b = sq_cli.get(rota), pg_cli.get(rota)
            if a.status_code != 200 or b.status_code != 200 or _sem_variaveis(a.text) != _sem_variaveis(b.text):
                diferentes.append((rota, a.status_code, b.status_code))
        assert diferentes == []
        catalogo = "/literatura/catalogo.xlsx?modelo=professor"
        assert sq_cli.get(catalogo).status_code == pg_cli.get(catalogo).status_code == 200
    finally:
        pool.close()



def test_planilha_completa_do_postgres_igual_a_do_sqlite(paineis):
    """Mesmas abas, cabecalhos e linhas; a ordem das linhas so vale onde a consulta tem ORDER BY (as views sem ORDER BY
    saem na ordem de cada banco)."""
    sq, pg, _, _, _ = paineis

    def abas(cli):
        r = cli.get("/execucoes/resultado.xlsx")
        assert r.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True)
        return {n: [tuple(x) for x in wb[n].iter_rows(values_only=True)] for n in wb.sheetnames}
    a, b = abas(sq), abas(pg)
    assert list(a) == list(b) and len(a) == 62

    def linhas(x):           # os testes anteriores deste modulo decidem nos dois bancos em segundos diferentes
        return sorted(re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00", "HORA", repr(r)) for r in x)
    for n in a:
        assert a[n][0] == b[n][0], n
        assert linhas(a[n][1:]) == linhas(b[n][1:]), n
    assert len(a["Achados"]) > 1 and len(a["Chamadas"]) > 1


def test_planilha_completa_com_o_postgres_fora_do_ar(paineis, monkeypatch):
    from adaptadores import leitura_postgres
    from dominio.erros import BancoIndisponivel

    def fora(*a, **k):
        raise sqlite3.OperationalError("banco PostgreSQL indisponível")
    monkeypatch.setattr(leitura_postgres, "ConexaoPostgres", fora)
    _, _, _, _, pool = paineis
    with pytest.raises(BancoIndisponivel):
        LeituraPainelPostgres(pool, chaves_do_banco(pool)).tabelas_para_exportacao()


def test_planilha_completa_le_o_postgres_num_so_instantaneo(paineis, monkeypatch):
    from adaptadores import leitura_postgres
    _, _, _, _, pool = paineis
    visto = {}

    def espiao(conn):
        visto["iso"] = conn.execute("SHOW transaction_isolation").fetchone()[0]
        visto["ro"] = conn.execute("SHOW transaction_read_only").fetchone()[0]
        return {}
    monkeypatch.setattr(leitura_postgres, "ler_tabelas", espiao)
    LeituraPainelPostgres(pool, chaves_do_banco(pool)).tabelas_para_exportacao()
    assert visto == {"iso": "repeatable read", "ro": "on"}
