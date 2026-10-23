"""Copia um banco SQLite (pesquisa e, opcionalmente, contas) para um PostgreSQL ja migrado (D96, plano de migracao 6).

- Le um snapshot consistente feito pela API de backup do SQLite (nunca a copia do arquivo em uso).
- Recusa antes de copiar: arquivo que nao abre, tabela presente nos dois arquivos, linha com chave estrangeira sem par
  (PRAGMA foreign_key_check), tabela ou coluna sem lugar no PostgreSQL, destino com dados. Nunca apaga nem sobrescreve.
- Copia tabela a tabela com COPY, na ordem das chaves estrangeiras do PostgreSQL (pai antes do filho; empate pela ordem
  de criacao no SQLite), tudo numa unica transacao: ou entra tudo, ou nada.
- Mantem os identificadores; `execucoes.ordem_gravacao` recebe a ordem de gravacao do SQLite (rowid); as sequencias
  das colunas de identidade sao reajustadas ao maior valor importado.
- Devolve o relatorio de linhas por tabela (origem e destino), conferido antes de confirmar.
Todo erro sai como ErroImportacao com mensagem fixa (o codigo SQLSTATE quando vem do PostgreSQL; nunca a URL)."""
import sqlite3
import tempfile
from pathlib import Path

import psycopg

from adaptadores import migrador_postgres


class ErroImportacao(Exception):
    pass


def _snapshot(origem, pasta):
    destino = Path(pasta) / "snapshot.db"
    try:
        fonte = sqlite3.connect(Path(origem).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            alvo = sqlite3.connect(destino)
            try:
                fonte.backup(alvo)
            finally:
                alvo.close()
        finally:
            fonte.close()
    except sqlite3.Error:
        raise ErroImportacao(f"O arquivo SQLite {origem} não existe ou não pode ser lido.") from None
    return destino


NUNCA_COPIADAS = ("meta_schema", "tokens_api")    # o token de envio so vale no banco onde foi gerado (D98)


def _tabelas_sqlite(con):
    return [n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                      "ORDER BY rowid") if n not in NUNCA_COPIADAS]


def ordem_de_copia(tabelas, pais):
    """`tabelas` na ordem de criacao; `pais`: {tabela: {tabelas que ela referencia}}. Pai antes do filho; entre as
    prontas, a primeira na ordem de criacao. Auto-referencia nao conta (o COPY confere no fim do comando). Ciclo: erro."""
    feitas, ordem = set(), []
    while len(ordem) < len(tabelas):
        for t in tabelas:
            if t not in feitas and {p for p in pais.get(t, ()) if p != t and p in tabelas} <= feitas:
                feitas.add(t)
                ordem.append(t)
                break
        else:
            raise ErroImportacao("Chaves estrangeiras em ciclo entre as tabelas: " + ", ".join(t for t in tabelas if t not in feitas) + ".")
    return ordem


def importar(origem_pesquisa, url, origem_contas=None, esquema="public"):
    """Importa e devolve {tabela: (linhas na origem, linhas no destino)}. `url`: conexao direta do PostgreSQL; `esquema`:
    onde gravar (fora do public, a sessao so enxerga esse esquema)."""
    try:
        migrador_postgres.conferir_esquema(esquema)
        migrador_postgres.conferir_url(url)      # nunca a URL do pool: o esquema escolhido ficaria na conexao compartilhada
    except migrador_postgres.ErroMigracao as erro:
        raise ErroImportacao(str(erro)) from None
    with tempfile.TemporaryDirectory() as pasta:
        Path(pasta, "p").mkdir()
        snapshots = [_snapshot(origem_pesquisa, Path(pasta) / "p")]
        if origem_contas is not None:
            Path(pasta, "c").mkdir()
            snapshots.append(_snapshot(origem_contas, Path(pasta) / "c"))
        conexoes = [sqlite3.connect(s) for s in snapshots]
        try:
            return _importar(conexoes, url, esquema)
        finally:
            for c in conexoes:
                c.close()


def _importar(conexoes, url, esquema):
    de_onde, tabelas = {}, []
    for con in conexoes:
        for t in _tabelas_sqlite(con):
            if t in de_onde:
                raise ErroImportacao(f"A tabela {t} aparece nos dois arquivos SQLite: a importação recusa para não misturar dados.")
            de_onde[t] = con
            tabelas.append(t)
        orfa = con.execute("PRAGMA foreign_key_check").fetchone()
        if orfa:
            raise ErroImportacao(f"O SQLite tem linha com chave estrangeira sem par (tabela {orfa[0]}, rowid {orfa[1]}, "
                                 f"aponta para {orfa[2]}): corrija antes de importar.")
    try:
        pg = psycopg.connect(url, connect_timeout=10)
    except psycopg.Error:
        raise ErroImportacao("Não foi possível conectar ao PostgreSQL (confira a URL, a senha e se o banco está no ar).") from None
    if esquema != "public":
        try:
            pg.execute(f'SET search_path TO "{esquema}"')
        except psycopg.Error:
            pg.close()
            raise ErroImportacao("Não foi possível conectar ao PostgreSQL (confira a URL, a senha e se o banco está no ar).") from None
    tabela_atual = None
    try:
        with pg:
            destino = {}
            for t, c in pg.execute("SELECT table_name, column_name FROM information_schema.columns "
                                   "WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position"):
                destino.setdefault(t, []).append(c)
            if "versao_esquema" not in destino:
                raise ErroImportacao("O PostgreSQL ainda não tem o esquema: rode antes python main.py pg-migrar.")
            pais = {}
            for filho, pai in pg.execute(
                    "SELECT tc.table_name, ccu.table_name FROM information_schema.table_constraints tc "
                    "JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name "
                    "AND ccu.table_schema = tc.table_schema WHERE tc.table_schema = current_schema() AND tc.constraint_type = 'FOREIGN KEY'"):
                pais.setdefault(filho, set()).add(pai)
            colunas = {}
            for t in tabelas:
                if t not in destino:
                    raise ErroImportacao(f"A tabela {t} do SQLite não existe no PostgreSQL: o esquema está desatualizado.")
                cols = [c[1] for c in de_onde[t].execute(f'PRAGMA table_info("{t}")')]
                faltam = [c for c in cols if c not in destino[t]]
                if faltam:
                    raise ErroImportacao(f"Colunas de {t} sem lugar no PostgreSQL: {', '.join(faltam)}.")
                if pg.execute(f'SELECT EXISTS (SELECT 1 FROM "{t}")').fetchone()[0]:
                    raise ErroImportacao(f"A tabela {t} do PostgreSQL já tem dados: a importação só vale para um banco vazio.")
                colunas[t] = cols
            relatorio = {}
            for t in ordem_de_copia(tabelas, pais):
                tabela_atual = t
                extra = ["ordem_gravacao"] if t == "execucoes" else []
                lista = ", ".join(f'"{c}"' for c in colunas[t] + extra)
                sel = ", ".join([f'"{c}"' for c in colunas[t]] + (["rowid"] if extra else []))
                n = 0
                with pg.cursor().copy(f'COPY "{t}" ({lista}) FROM STDIN') as cp:
                    for linha in de_onde[t].execute(f'SELECT {sel} FROM "{t}" ORDER BY rowid'):
                        cp.write_row(linha)
                        n += 1
                relatorio[t] = n
            tabela_atual = None
            final = {t: (n, pg.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t, n in relatorio.items()}
            diferentes = {t: v for t, v in final.items() if v[0] != v[1]}
            if diferentes:
                raise ErroImportacao("Contagens diferentes depois da cópia: " + ", ".join(f"{t} {a}≠{b}" for t, (a, b) in diferentes.items()))
            for t, col in pg.execute("SELECT table_name, column_name FROM information_schema.columns "
                                     "WHERE table_schema = current_schema() AND is_identity = 'YES'").fetchall():
                pg.execute(f"SELECT setval(pg_get_serial_sequence('\"{t}\"', '{col}'), "
                           f'COALESCE((SELECT MAX("{col}") FROM "{t}"), 0) + 1, false)')
            return {t: final[t] for t in tabelas}
    except psycopg.Error as erro:
        onde = f"A cópia da tabela {tabela_atual} falhou" if tabela_atual else "A importação falhou"
        raise ErroImportacao(f"{onde} e nada foi importado (código do PostgreSQL: {erro.sqlstate or 'sem código'}).") from None
