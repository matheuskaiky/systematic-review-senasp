"""O "mais recente" das linhas da coleta vem do horario delas, nao do numero (D101): no banco central os numeros seguem a
ordem de envio, que pode ser qualquer uma. Prova: o mesmo banco, com os numeros das tabelas da coleta trocados para que as
execucoes aparecam em ordem inversa, da as mesmas linhas em todas as views."""
import sqlite3
from collections import Counter
from datetime import datetime, timedelta

import pytest

from adaptadores.repositorio_sqlite import RepositorioSQLite

# (tabela, chave, execucao de cada linha) e quem aponta para ela
TABELAS = [
    ("chamadas", "chamada_id", "SELECT chamada_id, run_id FROM chamadas"),
    ("classificacoes", "classificacao_id", "SELECT classificacao_id, run_id FROM classificacoes"),
    ("resultados_web", "resultado_id", "SELECT resultado_id, run_id FROM resultados_web"),
    ("paginas", "pagina_id", "SELECT pagina_id, run_id FROM paginas"),
    ("ocorrencias", "ocorrencia_id", "SELECT ocorrencia_id, run_id FROM ocorrencias"),
    ("triagem_escopo", "id", "SELECT id, run_id FROM triagem_escopo"),
    ("achados", "achado_id", "SELECT a.achado_id, k.run_id FROM achados a JOIN classificacoes k USING (classificacao_id)"),
    ("achados_descartados", "descartado_id",
     "SELECT a.descartado_id, k.run_id FROM achados_descartados a JOIN classificacoes k USING (classificacao_id)"),
]
FILHOS = {"chamadas": [("ocorrencias", "chamada_id"), ("resultados_web", "chamada_id"), ("paginas", "chamada_id"),
                       ("classificacoes", "chamada_id"), ("triagem_escopo", "chamada_id")],
          "paginas": [("classificacoes", "pagina_id")],
          "classificacoes": [("achados", "classificacao_id"), ("achados_descartados", "classificacao_id")]}
COLUNA_DA_TABELA = {"achado_id": "achados", "classificacao_id": "classificacoes", "descartado_id": "achados_descartados",
                    "chamada_id": "chamadas", "pagina_id": "paginas", "ocorrencia_id": "ocorrencias", "resultado_id": "resultados_web"}


def _mais_horas(texto, horas):
    return None if texto is None else (datetime.fromisoformat(texto) + timedelta(hours=horas)).isoformat(timespec="seconds")


@pytest.fixture
def bancos(copiar_demo, tmp_path):
    """(limpo, permutado, mapas): a demonstracao com cada execucao uma hora depois da anterior (a ordem passa a importar),
    todas no relatorio, sem decisoes humanas; e a copia com os numeros da coleta em ordem inversa das execucoes."""
    banco, _ = copiar_demo("recencia")
    limpo, perm = tmp_path / "limpo.db", tmp_path / "perm.db"
    origem = sqlite3.connect(banco)
    destino = sqlite3.connect(limpo)
    origem.backup(destino)
    origem.close()
    d = destino
    runs = [r for (r,) in d.execute("SELECT run_id FROM execucoes ORDER BY iniciado_em, rowid")]
    for horas, run in enumerate(runs):
        for tabela, coluna in (("execucoes", "iniciado_em"), ("chamadas", "requisitado_em"), ("triagem_escopo", "criado_em")):
            for chave, valor in d.execute(f"SELECT rowid, {coluna} FROM {tabela} WHERE run_id = ?", (run,)).fetchall():
                d.execute(f"UPDATE {tabela} SET {coluna} = ? WHERE rowid = ?", (_mais_horas(valor, horas), chave))
    d.execute("UPDATE execucoes SET no_relatorio = 1, motivo_exclusao = NULL, excluida_em = NULL")
    d.execute("UPDATE achados SET verificado = 0, status_final = NULL, verificado_por = NULL, verificado_em = NULL, observacao = NULL")
    for t in ("triagem", "triagem_revisoes", "achados_revisoes", "sugestoes", "auditoria_negativos"):
        d.execute(f"DELETE FROM {t}")
    d.commit()
    p = sqlite3.connect(perm)
    d.backup(p)
    d.close()
    ordem = {r: i for i, r in enumerate(runs)}
    linhas = {t: p.execute(q).fetchall() for t, _, q in TABELAS}
    mapas = {}
    p.execute("CREATE TEMP TABLE mapa (velho INTEGER PRIMARY KEY, novo INTEGER)")
    for t, chave, _ in TABELAS:
        ids = sorted(i for i, _ in linhas[t])
        nova = sorted(linhas[t], key=lambda x: (-ordem[x[1]], x[0]))
        mapas[t] = {velho: novo for (velho, _), novo in zip(nova, ids)}
        p.execute("DELETE FROM mapa")
        p.executemany("INSERT INTO mapa VALUES (?, ?)", list(mapas[t].items()))
        p.execute(f"UPDATE {t} SET {chave} = -(SELECT novo FROM mapa WHERE velho = {t}.{chave})")
        p.execute(f"UPDATE {t} SET {chave} = -{chave}")
        for filho, coluna in FILHOS.get(t, []):
            p.execute(f"UPDATE {filho} SET {coluna} = (SELECT novo FROM mapa WHERE velho = {filho}.{coluna}) WHERE {coluna} IS NOT NULL")
    p.commit()
    assert p.execute("PRAGMA foreign_key_check").fetchall() == []
    p.close()
    for b in (limpo, perm):
        RepositorioSQLite(b).fechar()
    return limpo, perm, mapas


def _normal(v):
    return round(v, 9) if isinstance(v, float) else v


def test_todas_as_views_iguais_com_os_numeros_em_ordem_inversa(bancos):
    limpo, perm, mapas = bancos
    volta = {t: {novo: velho for velho, novo in m.items()} for t, m in mapas.items()}
    a, b = sqlite3.connect(limpo), sqlite3.connect(perm)
    views = [v for (v,) in a.execute("SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name")]
    diferentes = {}
    for v in views:
        ca = a.execute(f"SELECT * FROM {v}")
        cols = [c[0] for c in ca.description]
        la = Counter(repr(tuple(_normal(x) for x in r)) for r in ca.fetchall())
        idx = [(i, COLUNA_DA_TABELA[c]) for i, c in enumerate(cols) if c in COLUNA_DA_TABELA]
        lb = Counter()
        for r in b.execute(f"SELECT * FROM {v}").fetchall():
            r = list(r)
            for i, t in idx:
                if r[i] is not None:
                    r[i] = volta[t].get(r[i], r[i])
            lb[repr(tuple(_normal(x) for x in r))] += 1
        if la != lb:
            diferentes[v] = (sum((la - lb).values()), sum((lb - la).values()))
    assert len(views) == 73 and diferentes == {}


def test_a_permutacao_realmente_inverte_as_execucoes(bancos):
    """Garante que o teste acima prova algo: no banco permutado, numero maior nao e mais ser mais recente."""
    _, perm, _ = bancos
    p = sqlite3.connect(perm)
    inversoes = p.execute("SELECT COUNT(*) FROM chamadas a JOIN chamadas b ON b.chamada_id > a.chamada_id "
                          "AND b.requisitado_em < a.requisitado_em").fetchone()[0]
    assert inversoes > 1000


def test_triagem_refeita_numa_execucao_antiga_vale_pelo_horario(tmp_path):
    """O defeito que ja existia: a triagem refeita dentro de uma execucao antiga guarda o numero antigo com horario novo."""
    caminho = tmp_path / "t.db"
    repo = RepositorioSQLite(caminho)
    repo.fechar()
    c = sqlite3.connect(caminho)
    for run, inicio in (("20261001_100000_aaaaaa", "2026-10-01T10:00:00+00:00"), ("20261002_100000_bbbbbb", "2026-10-02T10:00:00+00:00")):
        c.execute("INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, status) VALUES (?, ?, 'h', '{}', 'concluida')",
                  (run, inicio))
    c.execute("INSERT INTO artigos (artigo_id, chave_dedup, titulo) VALUES (1, 'k', 'Artigo')")
    c.execute("INSERT INTO chamadas (chamada_id, run_id, etapa, provedor, parametros_json, chave_idempotencia, requisitado_em, "
              "sucesso, n_retornados) VALUES (1, '20261001_100000_aaaaaa', 'busca_academica', 's', '{}', 'k1', '2026-10-01T10:00:00+00:00', 1, 1)")
    c.execute("INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (1, 1, 'T01', '20261001_100000_aaaaaa', 1)")
    # id 1: execucao antiga, refeita no dia 3 (excluido); id 2: execucao nova, no dia 2 (incluido)
    for i, run, status, quando in ((1, "20261001_100000_aaaaaa", "excluido", "2026-10-03T10:00:00+00:00"),
                                   (2, "20261002_100000_bbbbbb", "incluido", "2026-10-02T10:00:00+00:00")):
        c.execute("INSERT INTO triagem_escopo (id, run_id, fonte, item_id, uf, status, valido, criado_em) VALUES (?, ?, 'artigo', 1, '', ?, 1, ?)",
                  (i, run, status, quando))
    c.commit()
    linha = c.execute("SELECT valor FROM v_prisma WHERE metrica LIKE '%automa%'").fetchone()
    assert linha is not None and linha[0] == 1                      # o veredito vigente e o refeito (excluido), o mais recente
