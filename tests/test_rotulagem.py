"""Rotulagem minima: selecao pura (estratos, folga, semente), plano contra bancos montados a mao, comando `rotulagem-modelo`
(--listar, geracao, recusa de sobrescrever, banco intacto) e o ciclo completo: gerar, preencher, importar, trava aberta."""
import hashlib
import sys

import pandas as pd
import pytest

import config.settings as S
import main
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import rotulagem as RT
from dados_rotulagem import construir
from dominio import auditoria_negativos as AN, rotulagem as R
from painel import analises_blocos as blocos


# ============================== dominio ==============================
def test_folga_arredonda_para_cima_e_zero_nao_pede_nada():
    assert R.com_folga(200, 10) == 220 and R.com_folga(50, 10) == 55 and R.com_folga(1, 10) == 2 and R.com_folga(33, 10) == 37
    assert R.com_folga(0, 10) == 0 and R.com_folga(-5, 10) == 0 and R.com_folga(100, 0) == 100


def test_alocacao_proporcional_soma_n_e_respeita_o_tamanho():
    t = {"a": 7, "b": 7, "c": 7}
    for n in range(0, 22):
        r = R.alocar_proporcional(t, n)
        assert sum(r.values()) == min(n, 21) and all(0 <= r[k] <= 7 for k in t)
    assert R.alocar_proporcional({"x": 1, "y": 99}, 10) == {"x": 0, "y": 10}


def _achados(n=300, confere0=20, cita0=60, snippet=40):
    ufs, tecs = ("PI", "CE", "BA", "SP"), ("rf", "lp", "vi")
    saida = []
    for i in range(1, n + 1):
        j = i - 1
        saida.append({"achado_id": i, "uf": ufs[j % 4], "tecnologia": tecs[j % 3], "evidencia_confere": 0 if j < confere0 else 1,
                      "evidencia_cita_tecnologia": 0 if confere0 <= j < confere0 + cita0 else 1,
                      "origem_texto": "snippet" if confere0 + cita0 <= j < confere0 + cita0 + snippet else "pagina",
                      "confianca": "baixa" if confere0 + cita0 <= j < confere0 + cita0 + snippet else "alta"})
    return saida


def test_achados_selecao_e_reproduzivel_sem_repeticao_e_do_tamanho_pedido():
    c = _achados()
    a = R.selecionar_achados(c, 100, "s1")
    assert a == R.selecionar_achados(c, 100, "s1") and [x[0]["achado_id"] for x in a] != [x[0]["achado_id"] for x in R.selecionar_achados(c, 100, "s2")]
    ids = [x[0]["achado_id"] for x in a]
    assert len(ids) == 100 == len(set(ids)) and ids == sorted(ids)
    assert len(R.selecionar_achados(c, 1000, "s")) == 300 and R.selecionar_achados(c, 0) == [] and R.selecionar_achados([], 5) == []


def test_achados_enriquecidos_tem_teto_todos_os_que_nao_conferem_e_resto_sorteado():
    c = _achados()
    a = R.selecionar_achados(c, 100, "s")
    por = {}
    for x, chave, _ in a:
        por.setdefault(chave, []).append(x["achado_id"])
    assert set(por["evidencia_nao_confere"]) == {i for i in range(1, 21)}                       # todos entram
    enriquecidos = sum(len(v) for k, v in por.items() if k != "sorteio_uf_tecnologia")
    assert enriquecidos <= 70 and len(por["sorteio_uf_tecnologia"]) >= 30                        # teto de 70%; o resto e sorteio do que "parece certo"
    assert {"evidencia_nao_cita_tecnologia", "so_snippet"} <= set(por)                           # nenhum estrato e engolido pela prioridade
    assert all(c[i - 1]["evidencia_confere"] == 1 and c[i - 1]["evidencia_cita_tecnologia"] == 1 and c[i - 1]["origem_texto"] == "pagina"
               for i in por["sorteio_uf_tecnologia"])
    ufs = {c[i - 1]["uf"] for i in por["sorteio_uf_tecnologia"]}
    assert ufs == {"PI", "CE", "BA", "SP"}                                                        # estratificado por UF


def test_achados_sorteio_completa_com_sobras_quando_faltam_limpos():
    c = _achados(n=60, confere0=10, cita0=30, snippet=15)                                          # so 5 limpos
    a = R.selecionar_achados(c, 50, "s")
    assert len(a) == 50 == len({x[0]["achado_id"] for x in a})


def test_achados_aleatoria_e_simples_sem_estrato_de_erro():
    c = _achados()
    a = R.selecionar_achados(c, 60, "s", aleatoria=True)
    assert len(a) == 60 and {x[1] for x in a} == {"sorteio_simples"}
    assert a == R.selecionar_achados(c, 60, "s", aleatoria=True)
    # um sorteio simples nao concentra os erros: a fracao de erros fica perto da populacao (120 de 300), longe de 70%
    erros = sum(1 for x, _, _ in a if x["evidencia_confere"] == 0 or x["evidencia_cita_tecnologia"] == 0 or x["origem_texto"] != "pagina")
    assert erros < 0.6 * 60


def _artigos(n_el=100, n_q=60, n_ex=200, n_sem=10):
    saida, i = [], 0
    for status, n in (("elegivel", n_el), ("quarentena", n_q), ("excluido", n_ex), (None, n_sem)):
        for k in range(n):
            i += 1
            saida.append({"artigo_id": i, "status_escopo": status, "valido_escopo": 1 if status else None, "nivel": ("alta", "media", "baixa")[k % 3],
                          "decisao": "pendente"})
    return saida


def test_triagem_composicao_por_veredito_e_excluidos_em_ordem_unica():
    c = _artigos()
    base, h4 = R.selecionar_artigos(c, 60, 40, "s")
    cont = {s: sum(1 for a, _, _ in base if R.status_do_modelo(a) == s) for s in ("elegivel", "quarentena", "excluido")}
    assert len(base) == 60 and cont == {"elegivel": 30, "quarentena": 12, "excluido": 18}
    assert len(h4) == 40 and all(R.status_do_modelo(a) == "excluido" for a, _, _ in h4)
    ids_base, ids_h4 = {a["artigo_id"] for a, _, _ in base}, {a["artigo_id"] for a, _, _ in h4}
    assert not ids_base & ids_h4
    # a base e o h4 formam o inicio de UMA permutacao dos excluidos: pedir so a base e depois mais um h4 nao muda a base
    assert R.selecionar_artigos(c, 60, 0, "s")[0] == base
    exc_junto = {a["artigo_id"] for a, _, _ in base if R.status_do_modelo(a) == "excluido"} | ids_h4
    assert len(exc_junto) == 58
    assert R.selecionar_artigos(c, 60, 40, "s") == (base, h4) and R.selecionar_artigos(c, 60, 40, "outra")[0] != base


def test_triagem_elegiveis_e_quarentena_seguem_os_niveis_de_relevancia():
    base, _ = R.selecionar_artigos(_artigos(), 60, 0, "s")
    niveis = {a["nivel"] for a, _, _ in base if R.status_do_modelo(a) == "elegivel"}
    assert niveis == {"alta", "media", "baixa"}


def test_triagem_cota_que_nao_cabe_migra_e_sem_veredito_completa():
    c = _artigos(n_el=3, n_q=2, n_ex=500, n_sem=20)
    base, _ = R.selecionar_artigos(c, 40, 0, "s")
    assert len(base) == 40 and sum(1 for a, _, _ in base if R.status_do_modelo(a) == "elegivel") == 3
    c = _artigos(n_el=3, n_q=2, n_ex=5, n_sem=50)
    base, _ = R.selecionar_artigos(c, 40, 0, "s")
    assert len(base) == 40 and sum(1 for a, _, _ in base if R.status_do_modelo(a) == "sem_veredito") == 30
    assert R.selecionar_artigos(_artigos(), 0, 0, "s") == ([], [])


def test_veredito_invalido_conta_como_sem_veredito():
    assert R.status_do_modelo({"status_escopo": "excluido", "valido_escopo": 0}) == "sem_veredito"
    assert R.status_do_modelo({"status_escopo": "excluido", "valido_escopo": 1}) == "excluido"
    assert R.status_do_modelo({"status_escopo": None, "valido_escopo": None}) == "sem_veredito"


def test_h4_usa_a_funcao_do_dominio_nao_numeros_fixos():
    assert R.minimo_h4(0.05) == AN.amostra_minima_sem_erros(0.05) == 59 and R.minimo_h4(0.02) == AN.amostra_minima_sem_erros(0.02) == 149


# ============================== plano (aplicacao) sobre banco montado a mao ==============================
def _banco(tmp_path, nome="r.db", **kw):
    n = kw.get("n_artigos", 120)
    padrao = dict(n_achados=260, n_artigos=120, n_negativos=80, confere0=30, cita0=40, snippet=30,
                  escopo=[(i, "elegivel" if i % 3 == 0 else "excluido" if i % 3 == 1 else "quarentena") for i in range(n)])
    return construir(tmp_path / nome, **{**padrao, **kw})


def _plano(banco, **kw):
    repo = RepositorioSQLite(banco)
    try:
        return RT.planejar(repo, **kw)
    finally:
        repo.fechar()


def test_plano_pede_o_que_falta_com_folga(tmp_path):
    p = _plano(_banco(tmp_path))
    assert (p["achados"]["faltam"], p["achados"]["pedir"], len(p["achados"]["linhas"])) == (200, 220, 220)
    assert (p["triagem"]["faltam"], p["triagem"]["pedir"], len(p["triagem"]["linhas"])) == (50, 55, 55)
    assert (p["auditoria"]["faltam"], p["auditoria"]["pedir"], p["auditoria"]["minimo"], p["auditoria"]["n_universo"]) == (59, 59, 59, 80)
    assert p["triagem"]["h4"] is None
    assert [n for n, _ in RT.arquivos_do_plano(p)] == [RT.ARQ_ACHADOS, RT.ARQ_TRIAGEM, RT.ARQ_AUDITORIA]
    sem_folga = _plano(_banco(tmp_path, "sem_folga.db"), folga=0)
    assert len(RT.arquivos_do_plano(sem_folga)) == 3 and sem_folga["achados"]["pedir"] == 200


def test_plano_exclui_ja_verificados_ja_decididos_e_ja_auditados(tmp_path):
    ver = [(i, "em_uso") for i in range(50)]
    dec = [(i, "excluir") for i in range(10)]
    banco = _banco(tmp_path, verificados=ver, decisoes=dec)
    p = _plano(banco)
    assert p["achados"]["n_verificados"] == 50 and p["achados"]["faltam"] == 150 and p["achados"]["pedir"] == 165
    assert not {l["achado_id"] for l in p["achados"]["linhas"]} & set(range(1, 51))
    assert p["triagem"]["faltam"] == 40 and p["triagem"]["pedir"] == 44
    assert not {l["artigo_id"] for l in p["triagem"]["linhas"]} & set(range(1, 11))
    # auditoria: 10 paginas ja conferidas saem do sorteio e do que falta
    repo = RepositorioSQLite(banco)
    for cand in repo.candidatos_auditoria_negativos()[:10]:
        repo.importar_auditoria_negativos([{"classificacao_id": cand["classificacao_id"], "url_id": None, "uf": None, "revisor": "Ana",
                                            "tinha_aplicacao": 0, "tecnologia": None, "observacao": None, "linha": 2}])
    repo.fechar()
    p = _plano(banco)
    assert p["auditoria"]["n_auditadas"] == 10 and p["auditoria"]["faltam"] == 49 and p["auditoria"]["pedir"] == 49 and p["auditoria"]["pool"] == 70


def test_auditoria_usa_a_mesma_selecao_do_comando_existente(tmp_path):
    banco = _banco(tmp_path)
    repo = RepositorioSQLite(banco)
    esperado = AN.amostrar(repo.candidatos_auditoria_negativos(), 59, AN.SEMENTE_PADRAO)
    repo.fechar()
    p = _plano(banco)
    assert [l["classificacao_id"] for l in p["auditoria"]["linhas"]] == [c["classificacao_id"] for c in esperado]
    assert list(p["auditoria"]["linhas"][0]) == list(AN.COLUNAS_AMOSTRA)


def test_trava_ja_destravada_nao_gera_linhas(tmp_path):
    ver = [(i, "descartado" if i < 50 else "piloto") for i in range(200)]
    dec = [(i, "incluir" if i < 10 else "excluir") for i in range(50)]
    banco = _banco(tmp_path, verificados=ver, decisoes=dec, n_negativos=0)
    p = _plano(banco)
    assert p["achados"]["pedir"] == 0 and p["achados"]["linhas"] == [] and p["triagem"]["linhas"] == []
    assert p["triagem"]["trava"]["destravado"] and p["achados"]["trava"]["destravado"]
    assert RT.arquivos_do_plano(p) == [] and sum("já destravado" in l for l in RT.resumo_texto(p)) == 2


def test_h4_conta_excluidos_ja_checados_e_os_da_base(tmp_path):
    dec = [(i, "excluir") for i in range(1, 120, 3)][:5]                    # artigos de posicao 1, 4, 7... sao `excluido` no modelo
    banco = _banco(tmp_path, decisoes=dec, n_artigos=300)
    p = _plano(banco, h4=True, meta_h4=0.05)
    h = p["triagem"]["h4"]
    na_base = sum(1 for l in p["triagem"]["linhas"] if "excluído" in l["estrato"])
    assert h["minimo"] == 59 and h["ja_checados"] == 5 and h["na_base"] == na_base and h["faltam"] == 59 - 5 - na_base == h["pedir"]
    ids = {l["artigo_id"] for l in p["triagem"]["linhas"]} | {l["artigo_id"] for l in h["linhas"]}
    assert len(ids) == len(p["triagem"]["linhas"]) + len(h["linhas"])
    assert _plano(banco, h4=True, meta_h4=0.02)["triagem"]["h4"]["minimo"] == 149


def test_colunas_dos_achados_e_da_triagem_sao_as_da_exportacao(tmp_path):
    banco = _banco(tmp_path)
    repo = RepositorioSQLite(banco)
    export = repo.tabelas_para_exportacao()
    repo.fechar()
    p = _plano(banco)
    assert set(export["Achados"].columns) <= set(p["achados"]["linhas"][0]) and set(p["achados"]["linhas"][0]) - set(export["Achados"].columns) == {"estrato"}
    extras = set(p["triagem"]["linhas"][0]) - set(export["Triagem"].columns)
    assert set(export["Triagem"].columns) <= set(p["triagem"]["linhas"][0]) and extras == {"estrato", "resumo"}
    assert list(p["achados"]["linhas"][0])[:2] == ["achado_id", "estrato"]


# ============================== comando e ciclo completo ==============================
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(S, "OUT_DIR", tmp_path / "outputs")
    monkeypatch.setitem(S.OPCOES["excel"], "pasta", tmp_path / "outputs")
    banco = construir(tmp_path / "meu.db", n_achados=260, n_artigos=120, n_negativos=80, confere0=30, cita0=40, snippet=30,
                      escopo=[(i, "elegivel" if i % 3 == 0 else "excluido" if i % 3 == 1 else "quarentena") for i in range(120)])
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", banco)
    return tmp_path, banco


def _hash(caminho):
    return hashlib.sha256(open(caminho, "rb").read()).hexdigest()


def test_listar_mostra_contagens_e_nao_grava_nada(ambiente, monkeypatch, capsys):
    tmp, banco = ambiente
    antes = _hash(banco)
    _rodar(monkeypatch, "rotulagem-modelo", "--listar", "--h4")
    saida = capsys.readouterr().out
    assert "faltam 200" in saida and "-> 220 linha(s)" in saida and "faltam 50" in saida and "-> 55" in saida and "59" in saida
    assert "rotulagem_triagem_h4.xlsx" in saida and "Nada foi gravado" in saida
    assert not (tmp / "outputs").exists() and _hash(banco) == antes
    _rodar(monkeypatch, "rotulagem-modelo", "--estimar")                                # sinonimo
    assert "Nada foi gravado" in capsys.readouterr().out


def test_gera_arquivos_leiame_e_nao_altera_o_banco(ambiente, monkeypatch, capsys):
    tmp, banco = ambiente
    antes = _hash(banco)
    _rodar(monkeypatch, "rotulagem-modelo", "--h4")
    saida = capsys.readouterr().out
    pasta = tmp / "outputs" / "rotulagem"
    assert sorted(p.name for p in pasta.iterdir()) == ["LEIA-ME.txt", "auditoria_negativos.csv", "rotulagem_achados.xlsx", "rotulagem_triagem.xlsx",
                                                      "rotulagem_triagem_h4.xlsx"]
    assert "python main.py achados-importar" in saida and "auditoria-negativos-importar" in saida and _hash(banco) == antes
    achados = pd.read_excel(pasta / "rotulagem_achados.xlsx", sheet_name=None)
    assert set(achados) == {"Achados", "LEIA-ME"} and len(achados["Achados"]) == 220
    leia = " ".join(str(x) for x in achados["LEIA-ME"].iloc[:, 0])
    assert "ENRIQUECIDA" in leia and "NÃO para estimar a precisão global" in leia and "--aleatoria" in leia
    assert "sem --independente" in leia
    txt = (pasta / "LEIA-ME.txt").read_text(encoding="utf-8")
    for esperado in ("220 linha(s)", "55 linha(s)", "59 linha(s)", "achados-importar", "triagem-importar", "auditoria-negativos-importar",
                     "ordem de grandeza", "Não use --independente"):
        assert esperado in txt, esperado
    triagem = pd.read_excel(pasta / "rotulagem_triagem.xlsx", sheet_name=None)
    assert set(triagem) == {"Triagem", "LEIA-ME"} and len(triagem["Triagem"]) == 55
    assert pd.read_csv(pasta / "auditoria_negativos.csv").shape == (59, len(AN.COLUNAS_AMOSTRA))


def test_recusa_sobrescrever_e_e_deterministico_com_semente(ambiente, monkeypatch, capsys):
    tmp, _ = ambiente
    _rodar(monkeypatch, "rotulagem-modelo", "--saida", str(tmp / "a"), "--semente", "x")
    arq = tmp / "a" / "rotulagem_achados.xlsx"
    arq.write_bytes(arq.read_bytes() + b"")                                               # existe
    marca = _hash(arq)
    with pytest.raises(SystemExit, match="Já existem"):
        _rodar(monkeypatch, "rotulagem-modelo", "--saida", str(tmp / "a"), "--semente", "x")
    assert _hash(arq) == marca
    _rodar(monkeypatch, "rotulagem-modelo", "--saida", str(tmp / "b"), "--semente", "x")
    _rodar(monkeypatch, "rotulagem-modelo", "--saida", str(tmp / "c"), "--semente", "y")
    ids = lambda d: pd.read_excel(tmp / d / "rotulagem_achados.xlsx", sheet_name="Achados")["achado_id"].tolist()
    assert ids("a") == ids("b") and ids("a") != ids("c")


def test_aleatoria_muda_o_modo_da_amostra(ambiente, monkeypatch):
    tmp, _ = ambiente
    _rodar(monkeypatch, "rotulagem-modelo", "--aleatoria", "--saida", str(tmp / "z"))
    a = pd.read_excel(tmp / "z" / "rotulagem_achados.xlsx", sheet_name="Achados")
    assert set(a["estrato"]) == {"sorteio simples (--aleatoria)"}
    assert "ALEATÓRIA SIMPLES" in " ".join(str(x) for x in pd.read_excel(tmp / "z" / "rotulagem_achados.xlsx", sheet_name="LEIA-ME").iloc[:, 0])


def _preencher(pasta):
    """Faz o papel da pessoa: preenche os arquivos gerados, de forma que as duas classes aparecam."""
    caminho = pasta / "rotulagem_achados.xlsx"
    abas = pd.read_excel(caminho, sheet_name=None)
    a = abas["Achados"]
    a["verificado"] = 1
    a["status_final"] = ["em_uso" if e.startswith("sorteio") else "descartado" for e in a["estrato"]]
    a["verificado_por"] = "Ana"
    with pd.ExcelWriter(caminho) as xw:
        for nome, df in abas.items():
            df.to_excel(xw, sheet_name=nome, index=False)
    caminho = pasta / "rotulagem_triagem.xlsx"
    abas = pd.read_excel(caminho, sheet_name=None)
    t = abas["Triagem"]
    t["decisao"] = ["incluir" if "elegivel" in e else "excluir" for e in t["estrato"]]
    t["motivo"] = ["fora do tema" if d == "excluir" else None for d in t["decisao"]]
    t["revisor"] = "Ana"
    with pd.ExcelWriter(caminho) as xw:
        for nome, df in abas.items():
            df.to_excel(xw, sheet_name=nome, index=False)
    caminho = pasta / "auditoria_negativos.csv"
    c = pd.read_csv(caminho, dtype=str)
    c["revisor"], c["tinha_aplicacao"] = "Ana", "0"
    c.to_csv(caminho, index=False, encoding="utf-8-sig")


def test_ciclo_completo_gerar_preencher_importar_e_a_trava_abre(ambiente, monkeypatch, capsys):
    tmp, banco = ambiente
    pasta = tmp / "outputs" / "rotulagem"
    assert not LeituraPainelSQLite(banco).analise_prontidao()["h2"]["destravado"]
    _rodar(monkeypatch, "rotulagem-modelo")
    _preencher(pasta)
    _rodar(monkeypatch, "achados-importar", str(pasta / "rotulagem_achados.xlsx"))
    _rodar(monkeypatch, "triagem-importar", str(pasta / "rotulagem_triagem.xlsx"))
    _rodar(monkeypatch, "auditoria-negativos-importar", str(pasta / "auditoria_negativos.csv"))
    saida = capsys.readouterr().out
    assert "Findings verified: 220" in saida and "Rows imported: 55" in saida and "Respostas novas: 59" in saida
    p = LeituraPainelSQLite(banco).analise_prontidao()
    assert p["h2"]["destravado"] and p["h2"]["n_verificados_total"] == 220 and p["h2"]["condicoes"][1]["n"] >= 40
    assert p["h5"]["destravado"] and p["h5"]["condicoes"][1]["n"] >= 10
    assert p["auditoria"]["condicoes"][0]["n"] == 59 and p["auditoria"]["destravado"]
    # a pagina inicial e /analises passam a mostrar "destravado"
    _rodar(monkeypatch, "rotulagem-modelo", "--listar")
    assert "Nada a gerar" in capsys.readouterr().out
    cartoes = blocos.bloco_prontidao(LeituraPainelSQLite(banco).analise_prontidao())["cartoes"]
    assert all(c["status"] == "destravado" for c in cartoes)


def test_importacao_independente_nao_abre_a_trava(ambiente, monkeypatch):
    """`--independente` so grava no historico: nao e o padrao e nao conta para a prontidao."""
    tmp, banco = ambiente
    _rodar(monkeypatch, "rotulagem-modelo")
    _preencher(tmp / "outputs" / "rotulagem")
    _rodar(monkeypatch, "achados-importar", str(tmp / "outputs" / "rotulagem" / "rotulagem_achados.xlsx"), "--independente")
    assert LeituraPainelSQLite(banco).analise_prontidao()["h2"]["n_verificados_total"] == 0


def test_importadores_ignoram_colunas_estrato_e_resumo_mas_continuam_validando(ambiente, monkeypatch):
    tmp, banco = ambiente
    _rodar(monkeypatch, "rotulagem-modelo")
    pasta = tmp / "outputs" / "rotulagem"
    caminho = pasta / "rotulagem_achados.xlsx"
    abas = pd.read_excel(caminho, sheet_name=None)
    a = abas["Achados"]
    a["status_final"], a["verificado_por"] = a["status_final"].astype(object), a["verificado_por"].astype(object)
    a.at[0, "verificado"], a.at[0, "status_final"], a.at[0, "verificado_por"] = 1, "invalido", "Ana"   # valor fora do vocabulario
    with pd.ExcelWriter(caminho) as xw:
        for nome, df in abas.items():
            df.to_excel(xw, sheet_name=nome, index=False)
    with pytest.raises(SystemExit, match="Invalid status_final"):
        _rodar(monkeypatch, "achados-importar", str(caminho))
    assert LeituraPainelSQLite(banco).analise_prontidao()["h2"]["n_verificados_total"] == 0        # nada foi gravado pela metade
