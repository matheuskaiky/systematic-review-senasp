"""RG4 (b): auditoria do que o modelo NAO marcou (falsos negativos): sorteio reproduzivel, importacao validada e idempotente,
view, leitura (Wilson, limite exato, tamanho de amostra) e bloco do painel."""
import sqlite3
import sys

import pandas as pd
import pytest

import main
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from dominio import auditoria_negativos as AN, estatistica as est
from painel import analises_blocos as b
from test_leitura_analises import Minimo, _sql

TECNOLOGIAS = {"reconhecimento_facial", "leitura_placas", "outra_ia"}


def _negativo(m, uf, origem="pagina", relevante=0, n_achados=0, valido=1):
    """Classificacao sem achado, com a pagina baixada (texto_path); devolve o classificacao_id."""
    cid = m.chamada("classificacao", "gemini", f"{m._n}:{uf}")
    url = m.url("x.gov.br")
    pid = None
    if origem == "pagina":
        ch = m.chamada("download", "requests", url)
        _sql(m.caminho, "INSERT INTO paginas (run_id, url_id, chamada_id, extracao_ok, texto_path) VALUES (?,?,?,1,?)",
             (m.run, url, ch, f"data/raw/txt/{url}.txt"))
        pid = _sql(m.caminho, "SELECT MAX(pagina_id) FROM paginas")[0][0]
    _sql(m.caminho, """INSERT INTO classificacoes (chamada_id, run_id, url_id, pagina_id, uf, origem_texto, classificador, prompt_versao,
                           relevante, json_valido, n_achados) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
         (cid, m.run, url, pid, uf, origem, "gemini", "v4", relevante, valido, n_achados))
    return _sql(m.caminho, "SELECT MAX(classificacao_id) FROM classificacoes")[0][0]


@pytest.fixture
def minimo(tmp_path):
    return Minimo(tmp_path / "neg.db")


def _banco_com_negativos(minimo, por_uf):
    """por_uf = {uf: n negativos}. Devolve {uf: [classificacao_id]}."""
    ids = {uf: [_negativo(minimo, uf) for _ in range(n)] for uf, n in por_uf.items()}
    return ids


def _resposta(cid, revisor="Ana", tinha=0, tecnologia=None, obs=None):
    return {"classificacao_id": str(cid), "revisor": revisor, "tinha_aplicacao": str(tinha), "tecnologia": tecnologia, "observacao": obs}


# ============================== dominio: sorteio, validacao, tamanho de amostra ==============================
def _candidatos(**por_uf):
    return [{"classificacao_id": i, "uf": uf} for uf, ids in por_uf.items() for i in ids]


def test_sorteio_e_reproduzivel_proporcional_por_uf_e_sem_repeticao():
    cands = _candidatos(PI=range(1, 61), CE=range(100, 130), AC=range(200, 210))            # 60, 30 e 10 = 100
    a = AN.amostrar(cands, 20, "s1")
    assert a == AN.amostrar(cands, 20, "s1") and a != AN.amostrar(cands, 20, "s2")
    por_uf = {uf: sum(1 for x in a if x["uf"] == uf) for uf in ("PI", "CE", "AC")}
    assert por_uf == {"PI": 12, "CE": 6, "AC": 2} and len({x["classificacao_id"] for x in a}) == 20
    assert [x["classificacao_id"] for x in a] == [x["classificacao_id"] for x in sorted(a, key=lambda c: (c["uf"], c["classificacao_id"]))]


def test_sorteio_restos_vao_para_as_maiores_sobras_e_a_soma_fecha():
    cands = _candidatos(PI=range(1, 8), CE=range(100, 107), AC=range(200, 207))             # 7, 7, 7
    for n in range(1, 21):
        a = AN.amostrar(cands, n, "x")
        assert len(a) == n
    assert AN.amostrar(cands, 100, "x") == sorted(cands, key=lambda c: (c["uf"], c["classificacao_id"])) and AN.amostrar(cands, 0) == [] \
        and AN.amostrar([], 5) == []


def test_validar_respostas_aceita_sim_nao_pula_linha_vazia_e_recusa_o_resto():
    linhas = [_resposta(1, "Ana", "1", "outra_ia"), _resposta(2, "Ana", "nao"), _resposta(3, "Ana", ""), _resposta(4, "Ana", "sim", "leitura_placas")]
    registros, sem = AN.validar_respostas(linhas, TECNOLOGIAS)
    assert sem == 1 and [(r["classificacao_id"], r["tinha_aplicacao"], r["tecnologia"]) for r in registros] == [
        (1, 1, "outra_ia"), (2, 0, None), (4, 1, "leitura_placas")]
    assert [r["linha"] for r in registros] == [2, 3, 5]
    for ruim, trecho in ((_resposta(1, "Ana", "talvez"), "tinha_aplicacao"), (_resposta(1, "", "1", "outra_ia"), "revisor"),
                         (_resposta(1, "Ana", "1"), "tecnologia"), (_resposta(1, "Ana", "1", "inventada"), "vocabulário"),
                         (_resposta(1, "Ana", "0", "outra_ia"), "só vale"), (_resposta("x", "Ana", "0"), "classificacao_id")):
        with pytest.raises(SystemExit, match=trecho):
            AN.validar_respostas([ruim], TECNOLOGIAS)
    with pytest.raises(SystemExit, match="repetido"):
        AN.validar_respostas([_resposta(1, "Ana", "0"), _resposta(1, "Ana", "0")], TECNOLOGIAS)
    assert AN.validar_respostas([_resposta(1, "Ana", "0"), _resposta(1, "Bia", "1", "outra_ia")], TECNOLOGIAS)[0][1]["revisor"] == "Bia"


def test_amostra_minima_sem_erros_e_calculada_pelas_funcoes_do_projeto():
    assert AN.amostra_minima_sem_erros(0.05) == 59 and AN.amostra_minima_sem_erros(0.02) == 149
    for meta in (0.05, 0.02, 0.10):
        n = AN.amostra_minima_sem_erros(meta)
        assert est.limite_superior_binomial_exato(0, n) < meta <= est.limite_superior_binomial_exato(0, n - 1)


# ============================== repositorio ==============================
def test_universo_da_auditoria_e_so_negativo_vigente_valido_com_texto_da_pagina(minimo):
    certo = _negativo(minimo, "PI")
    _negativo(minimo, "PI", origem="snippet")                              # so snippet: fora
    _negativo(minimo, "PI", valido=0)                                      # JSON invalido nao e "sem achado": fora
    _negativo(minimo, "PI", relevante=1, n_achados=0)                      # relevante sem achado gravado: dentro (n_achados = 0)
    minimo.achado("PI", "outra_ia", "em_uso")                              # positivo: fora
    repo = RepositorioSQLite(minimo.caminho)
    ids = {l["classificacao_id"] for l in repo.conn.execute("SELECT classificacao_id FROM v_negativos_auditaveis")}
    assert certo in ids and len(ids) == 2
    c = {x["classificacao_id"]: x for x in repo.candidatos_auditoria_negativos()}[certo]
    assert c["uf"] == "PI" and c["url"].startswith("https://x.gov.br") and c["texto_path"].endswith(".txt") and c["classificador"] == "gemini"


def test_importacao_grava_e_e_idempotente_e_conflito_nao_sobrescreve(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 3})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    regs, _ = AN.validar_respostas([_resposta(ids[0], "Ana", 0), _resposta(ids[1], "Ana", 1, "outra_ia", "perdeu o chatbot")], TECNOLOGIAS)
    assert repo.importar_auditoria_negativos(regs) == {"novas": 2, "iguais": 0, "conflitos": []}
    assert repo.importar_auditoria_negativos(regs) == {"novas": 0, "iguais": 2, "conflitos": []}
    linhas = [dict(r) for r in repo.conn.execute("SELECT * FROM auditoria_negativos ORDER BY auditoria_id")]
    assert [(l["classificacao_id"], l["url_id"], l["uf"], l["revisor"], l["tinha_aplicacao"], l["tecnologia"]) for l in linhas] == [
        (ids[0], linhas[0]["url_id"], "PI", "Ana", 0, None), (ids[1], linhas[1]["url_id"], "PI", "Ana", 1, "outra_ia")]
    assert linhas[1]["observacao"] == "perdeu o chatbot" and linhas[0]["revisado_em"]
    mudou, _ = AN.validar_respostas([_resposta(ids[0], "Ana", 1, "outra_ia"), _resposta(ids[2], "Ana", 0), _resposta(ids[0], "Bia", 0)], TECNOLOGIAS)
    r = repo.importar_auditoria_negativos(mudou)
    assert r["novas"] == 2 and r["conflitos"] == [(ids[0], "Ana", 2)]                                  # Bia e outro revisor: entra
    assert repo.conn.execute("SELECT tinha_aplicacao FROM auditoria_negativos WHERE classificacao_id=? AND revisor='Ana'", (ids[0],)).fetchone()[0] == 0
    assert {x["classificacao_id"] for x in repo.candidatos_auditoria_negativos()} == set()            # ja conferidas saem do proximo sorteio


def test_importacao_recusa_antes_de_gravar_classificacao_inexistente_com_achado_ou_url_trocada(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 2})["PI"]
    minimo.achado("PI", "outra_ia", "em_uso")
    com_achado = _sql(minimo.caminho, "SELECT MAX(classificacao_id) FROM classificacoes")[0][0]
    repo = RepositorioSQLite(minimo.caminho)
    for ruim, trecho in (([_resposta(ids[0], "Ana", 0), _resposta(9999, "Ana", 0)], "inexistente"),
                         ([_resposta(ids[0], "Ana", 0), _resposta(com_achado, "Ana", 0)], "tem achados"),
                         ([{**_resposta(ids[0], "Ana", 0), "uf": "CE"}], "não conferem"),
                         ([{**_resposta(ids[0], "Ana", 0), "url_id": "99999"}], "não conferem")):
        regs, _ = AN.validar_respostas(ruim, TECNOLOGIAS)
        with pytest.raises(SystemExit, match=trecho):
            repo.importar_auditoria_negativos(regs)
        assert repo.conn.execute("SELECT COUNT(*) FROM auditoria_negativos").fetchone()[0] == 0
    ok, _ = AN.validar_respostas([{**_resposta(ids[0], "Ana", 0), "uf": "PI", "url_id": str(repo.conn.execute(
        "SELECT url_id FROM classificacoes WHERE classificacao_id=?", (ids[0],)).fetchone()[0])}], TECNOLOGIAS)
    assert repo.importar_auditoria_negativos(ok)["novas"] == 1


def test_a_tabela_nao_aceita_resposta_fora_de_0_e_1_nem_repeticao(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 1})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    url = repo.conn.execute("SELECT url_id FROM classificacoes").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        repo._inserir("auditoria_negativos", classificacao_id=ids[0], url_id=url, uf="PI", revisor="Ana", revisado_em="x", tinha_aplicacao=2)
    repo._inserir("auditoria_negativos", classificacao_id=ids[0], url_id=url, uf="PI", revisor="Ana", revisado_em="x", tinha_aplicacao=0)
    with pytest.raises(sqlite3.IntegrityError):
        repo._inserir("auditoria_negativos", classificacao_id=ids[0], url_id=url, uf="PI", revisor="Ana", revisado_em="x", tinha_aplicacao=1)


# ============================== view e leitura ==============================
def _auditar(minimo, repo, respostas):
    regs, _ = AN.validar_respostas(respostas, TECNOLOGIAS)
    return repo.importar_auditoria_negativos(regs)


def test_view_conta_por_classificacao_com_a_posicao_conservadora_e_por_tecnologia(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 6})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    _auditar(minimo, repo, [_resposta(ids[0], "Ana", 1, "outra_ia"), _resposta(ids[0], "Bia", 0),            # um achou: conta como perdida
                            _resposta(ids[1], "Ana", 1, "leitura_placas"), _resposta(ids[2], "Ana", 0),
                            _resposta(ids[3], "Ana", 0), _resposta(ids[4], "Ana", 1, "outra_ia")])
    v = {(l["grupo"], l["tecnologia"]): dict(l) for l in repo.conn.execute("SELECT * FROM v_auditoria_negativos")}
    assert (v[("total", None)]["n_auditadas"], v[("total", None)]["n_com_aplicacao_perdida"], v[("total", None)]["taxa_perdida_pct"]) == (5, 3, 60.0)
    assert v[("tecnologia", "outra_ia")]["n_com_aplicacao_perdida"] == 2 and v[("tecnologia", "leitura_placas")]["n_com_aplicacao_perdida"] == 1


def test_leitura_sem_conferencia_traz_o_universo_e_os_tamanhos_de_amostra(minimo, tmp_path):
    _banco_com_negativos(minimo, {"PI": 4, "CE": 2})
    RepositorioSQLite(minimo.caminho).fechar()
    d = LeituraPainelSQLite(minimo.caminho).analise_auditoria_negativos()
    assert (d["n_auditadas"], d["n_perdidas"], d["taxa"], d["ic_wilson"], d["limite_superior"], d["tem_dados"]) == (0, 0, None, None, None, False)
    assert (d["n_universo"], d["n_restantes"], d["estimativa_paginas_perdidas"], d["por_tecnologia"]) == (6, 6, None, [])
    assert [(m["meta"], m["n_sem_erros"], m["abaixo_da_meta"], m["faltam_sem_erros"]) for m in d["metas"]] == [(0.05, 59, None, 59), (0.02, 149, None, 149)]


def test_leitura_com_conferencia_usa_wilson_e_o_limite_exato(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 12})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    _auditar(minimo, repo, [_resposta(i, "Ana", 1 if n == 0 else 0, "outra_ia" if n == 0 else None) for n, i in enumerate(ids[:10])])
    d = LeituraPainelSQLite(minimo.caminho).analise_auditoria_negativos()
    assert (d["n_auditadas"], d["n_perdidas"], d["taxa"], d["n_universo"], d["n_restantes"]) == (10, 1, 0.1, 12, 2)
    assert d["ic_wilson"] == est.intervalo_wilson(1, 10) and d["limite_superior"] == est.limite_superior_binomial_exato(1, 10)
    assert d["por_tecnologia"] == [{"tecnologia": "outra_ia", "n": 1}]
    assert all(m["abaixo_da_meta"] is False and m["faltam_sem_erros"] is None for m in d["metas"])           # houve erro: so mais conferencia ajuda
    est_p = d["estimativa_paginas_perdidas"]
    assert est_p["pontual"] == round(12 * 0.1) and est_p["minimo"] <= est_p["pontual"] <= est_p["maximo"]


def test_zero_erros_em_amostra_grande_atinge_a_meta(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 60})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    _auditar(minimo, repo, [_resposta(i, "Ana", 0) for i in ids])
    d = LeituraPainelSQLite(minimo.caminho).analise_auditoria_negativos()
    assert d["n_auditadas"] == 60 and d["taxa"] == 0.0 and d["limite_superior"] < 0.05
    assert [m["abaixo_da_meta"] for m in d["metas"]] == [True, False] and d["metas"][1]["faltam_sem_erros"] == 149 - 60


def test_auditoria_so_conta_execucoes_do_relatorio(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 2})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    _auditar(minimo, repo, [_resposta(i, "Ana", 0) for i in ids])
    repo.definir_no_relatorio(minimo.run, False, "piloto")
    d = LeituraPainelSQLite(minimo.caminho).analise_auditoria_negativos()
    assert (d["n_auditadas"], d["n_universo"]) == (0, 0)


def test_leitura_em_banco_antigo_devolve_vazio(tmp_path):
    antigo = tmp_path / "antigo.db"
    sqlite3.connect(antigo).close()
    d = LeituraPainelSQLite(antigo).analise_auditoria_negativos()
    assert d["n_auditadas"] == 0 and not d["tem_dados"] and d["n_universo"] == 0


# ============================== bloco do painel ==============================
def test_bloco_sem_conferencia_mostra_aguardando_e_o_tamanho_recomendado(minimo):
    _banco_com_negativos(minimo, {"PI": 4})
    RepositorioSQLite(minimo.caminho).fechar()
    bl = b.bloco_auditoria_negativos(LeituraPainelSQLite(minimo.caminho).analise_auditoria_negativos())
    texto = " ".join(bl["texto"])
    assert "Aguardando conferência humana" in bl["titulo"] and "aguardando conferência humana" in bl["aviso"].lower()
    assert "59 páginas" in texto and "149 páginas" in texto and "5%" in texto and "2%" in texto
    assert "auditoria-negativos-modelo --amostra 59" in texto and "auditoria-negativos-importar" in texto
    assert bl["grafico"] is None and dict(bl["pares"])["Páginas sem achado (texto da página)"] == "4"


def test_bloco_sem_nenhuma_pagina_para_conferir(tmp_path):
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    bl = b.bloco_auditoria_negativos(LeituraPainelSQLite(vazio).analise_auditoria_negativos())
    assert "Ainda não há páginas sem achado" in bl["titulo"] and "Aguardando conferência humana" in bl["aviso"]


def test_bloco_com_conferencia_traz_taxa_semaforo_e_a_tabela_de_metas(minimo):
    ids = _banco_com_negativos(minimo, {"PI": 12})["PI"]
    repo = RepositorioSQLite(minimo.caminho)
    _auditar(minimo, repo, [_resposta(i, "Ana", 1 if n == 0 else 0, "outra_ia" if n == 0 else None) for n, i in enumerate(ids[:10])])
    d = LeituraPainelSQLite(minimo.caminho).analise_auditoria_negativos()
    bl = b.bloco_auditoria_negativos(d)
    assert bl["titulo"] == "1 de 10 páginas sem achado conferidas tinham uma aplicação que o modelo não marcou (10,00%)"
    assert "an-semaforo" in str(bl["grafico"]) or "semaforo" in str(bl["grafico"])
    assert "no máximo" in bl["texto"][0] and "Wilson" in bl["texto"][0] and "a amostra foi sorteada" in bl["texto"][1]
    assert [l[0] for l in bl["tabela"]["linhas"]] == ["Abaixo de 5%", "Abaixo de 2%"] and bl["tabela"]["linhas"][0][2] == "59"
    assert all("ainda não prova" in l[3] for l in bl["tabela"]["linhas"])


# ============================== linha de comando ==============================
def _preparar_cli(ambiente_cli, monkeypatch):
    def rodar(*argv):
        monkeypatch.setattr(sys, "argv", ["main.py", *argv])
        main.main()
    rodar("exportar", "--simulado", "--saida", str(ambiente_cli / "x.xlsx"))              # cria o banco simulado
    m = Minimo.__new__(Minimo)
    m.caminho, m.run, m._n = ambiente_cli / "data" / "simulado.db", "R1", 0
    _sql(m.caminho, "INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, no_relatorio) VALUES ('R1','2026-01-01T00:00:00','h','{}',1)")
    for uf, n in (("PI", 8), ("CE", 4)):
        for _ in range(n):
            _negativo(m, uf)
    return rodar


def test_cli_amostra_reproduzivel_importacao_idempotente_e_recusa_sobrescrever(ambiente_cli, monkeypatch, capsys):
    rodar = _preparar_cli(ambiente_cli, monkeypatch)
    a, b2 = ambiente_cli / "a.csv", ambiente_cli / "b.csv"
    rodar("auditoria-negativos-modelo", "--amostra", "6", "--semente", "teste", "--saida", str(a), "--simulado")
    rodar("auditoria-negativos-modelo", "--amostra", "6", "--semente", "teste", "--saida", str(b2), "--simulado")
    assert a.read_bytes() == b2.read_bytes()
    saida = capsys.readouterr().out
    assert "amostra sorteada: 6" in saida and "Páginas sem achado ainda não conferidas: 12" in saida
    with pytest.raises(SystemExit, match="já existe"):
        rodar("auditoria-negativos-modelo", "--amostra", "6", "--saida", str(a), "--simulado")
    df = pd.read_csv(a, encoding="utf-8-sig", dtype=str)
    assert list(df.columns) == list(AN.COLUNAS_AMOSTRA) and len(df) == 6 and set(df["uf"]) == {"PI", "CE"}
    assert df["url"].str.startswith("https://").all() and df["texto_path"].str.endswith(".txt").all()
    assert sorted(df["uf"].value_counts().tolist()) == [2, 4]                                  # proporcional: 8 PI e 4 CE de 12
    # a pessoa responde 4 linhas (uma achou uma aplicacao) e deixa 2 em branco
    df.loc[:3, "revisor"] = "Ana"
    df.loc[:3, "tinha_aplicacao"] = "0"
    df.loc[0, "tinha_aplicacao"], df.loc[0, "tecnologia"] = "1", "outra_ia"
    df.to_csv(a.with_name("respondida.csv"), index=False, encoding="utf-8-sig")
    rodar("auditoria-negativos-importar", str(a.with_name("respondida.csv")), "--simulado")
    assert "Respostas novas: 4 | já gravadas iguais: 0 | linhas sem resposta (puladas): 2" in capsys.readouterr().out
    rodar("auditoria-negativos-importar", str(a.with_name("respondida.csv")), "--simulado")
    assert "Respostas novas: 0 | já gravadas iguais: 4" in capsys.readouterr().out
    df.loc[1, "tinha_aplicacao"], df.loc[1, "tecnologia"] = "1", "leitura_placas"                # Ana muda de ideia: conflito
    df.to_csv(a.with_name("conflito.csv"), index=False, encoding="utf-8-sig")
    rodar("auditoria-negativos-importar", str(a.with_name("conflito.csv")), "--simulado")
    assert "CONFLITOS: 1" in capsys.readouterr().out
    banco = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    assert banco.execute("SELECT COUNT(*), SUM(tinha_aplicacao) FROM auditoria_negativos").fetchone() == (4, 1)
    rodar("auditoria-negativos-modelo", "--amostra", "30", "--saida", str(ambiente_cli / "resto.csv"), "--simulado")      # so as 8 nao conferidas
    assert len(pd.read_csv(ambiente_cli / "resto.csv")) == 8


def test_cli_importar_recusa_tecnologia_fora_do_vocabulario(ambiente_cli, monkeypatch):
    rodar = _preparar_cli(ambiente_cli, monkeypatch)
    rodar("auditoria-negativos-modelo", "--amostra", "2", "--saida", str(ambiente_cli / "a.csv"), "--simulado")
    df = pd.read_csv(ambiente_cli / "a.csv", dtype=str)
    df["revisor"], df["tinha_aplicacao"], df["tecnologia"] = "Ana", "1", "drone_com_ia"
    df.to_csv(ambiente_cli / "r.csv", index=False)
    with pytest.raises(SystemExit, match="vocabulário"):
        rodar("auditoria-negativos-importar", str(ambiente_cli / "r.csv"), "--simulado")
    assert sqlite3.connect(ambiente_cli / "data" / "simulado.db").execute("SELECT COUNT(*) FROM auditoria_negativos").fetchone()[0] == 0
