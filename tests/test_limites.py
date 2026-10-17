"""Os limites do protocolo que foram resolvidos: artigos manuais, revisao em dupla, texto completo,
auditoria do pre-filtro, consultas combinadas e bancos antigos."""
import logging
import sqlite3
import sys

import pandas as pd
import pytest

import main
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import ClassificadorSimulado, ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, classificacao, download
from config import consultas as C
from dados_metricas import (BuscaSemPalavraChave, _consulta_pi, _id_artigo, _novo_run, _params, construir_academico,
                            construir_web)
from dominio.modelos import CandidatoDownload, PoliticaDownload, Termo
from dominio.servicos import escolher_auditoria, selecionar_candidatos, termo_composto

STATUS_PERMITIDOS = {"em_uso", "piloto", "licitacao", "anunciado", "em_estudo", "apenas_citado", "descartado"}


def _linhas(repo, view, where=""):
    return [dict(r) for r in repo.conn.execute(f"SELECT * FROM {view} {where}").fetchall()]


def _prisma(repo):
    return {r["metrica"]: r["valor"] for r in _linhas(repo, "v_prisma")}


@pytest.fixture
def ac(tmp_path):
    return construir_academico(tmp_path / "ac.db")[0]


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


# ============ 1. artigos das buscas manuais ============
def _manuais(*linhas):
    colunas = ("base", "termo_id", "titulo", "link", "autores_publicacao", "ano", "citacoes", "posicao", "data_busca")
    return pd.DataFrame([dict(zip(colunas, l)) for l in linhas], dtype=str)


LINHAS_MANUAIS = [
    ("IEEE", "T01", "Artigo A1", "https://ieee.example/1", None, "2023", None, "1", "2026-10-15"),    # ja vem do Scholar
    ("IEEE", "T25", "Artigo NOVO M1", "https://ieee.example/2", "Autor X", "2024", "7", "2", "2026-10-15"),
    ("ACM", "T25", "Artigo A1", None, None, None, None, None, "2026-10-16"),
    ("ACM", "T25", "Artigo NOVO M1", None, None, None, None, None, "2026-10-16"),
]


def test_artigos_manuais_sao_deduplicados_contra_o_scholar_e_entre_bases(ac):
    ocorrencias, novos = ac.importar_artigos_manuais(_manuais(*LINHAS_MANUAIS))
    assert (ocorrencias, novos) == (4, 1)                                      # so "Artigo NOVO M1" e artigo novo
    assert ac.conn.execute("SELECT COUNT(*) FROM artigos").fetchone()[0] == 13
    novo = ac.conn.execute("SELECT * FROM artigos WHERE titulo='Artigo NOVO M1'").fetchone()
    assert (novo["link"], novo["ano"], novo["citacoes"], novo["primeira_vez_run"]) == ("https://ieee.example/2", 2024, 7, "manual:IEEE")


def test_reimportar_artigos_manuais_nao_duplica(ac):
    ac.importar_artigos_manuais(_manuais(*LINHAS_MANUAIS))
    assert ac.importar_artigos_manuais(_manuais(*LINHAS_MANUAIS)) == (0, 0)
    assert ac.conn.execute("SELECT COUNT(*) FROM ocorrencias_manuais").fetchone()[0] == 4
    assert ac.conn.execute("SELECT COUNT(*) FROM artigos").fetchone()[0] == 13


def test_artigo_manual_completa_o_link_que_faltava_sem_sobrescrever(ac):
    ac.importar_artigos_manuais(_manuais(("IEEE", "T01", "Artigo A1", "https://ieee.example/a1", None, None, None, None, "")))
    assert ac.conn.execute("SELECT link FROM artigos WHERE titulo='Artigo A1'").fetchone()[0] == "https://ieee.example/a1"
    ac.importar_artigos_manuais(_manuais(("ACM", "T01", "Artigo A1", "https://acm.example/a1", None, None, None, None, "")))
    assert ac.conn.execute("SELECT link FROM artigos WHERE titulo='Artigo A1'").fetchone()[0] == "https://ieee.example/a1"


def test_rendimento_e_sobreposicao_por_fonte(ac):
    ac.importar_artigos_manuais(_manuais(*LINHAS_MANUAIS))
    f = {r["fonte"]: r for r in _linhas(ac, "v_rendimento_fonte")}
    assert set(f) == {"Google Scholar", "IEEE", "ACM"}
    assert (f["Google Scholar"]["n_artigos"], f["Google Scholar"]["n_exclusivos"], f["Google Scholar"]["n_incluidos"]) == (12, 11, 4)
    assert (f["IEEE"]["n_artigos"], f["IEEE"]["n_exclusivos"], f["IEEE"]["n_incluidos"], f["IEEE"]["n_pendentes"]) == (2, 0, 1, 1)
    assert (f["ACM"]["n_artigos"], f["ACM"]["pct_exclusivos"]) == (2, 0.0)
    pares = {(r["fonte_a"], r["fonte_b"]): r for r in _linhas(ac, "v_sobreposicao_fontes")}
    assert pares[("ACM", "IEEE")]["jaccard"] == 1.0 and pares[("ACM", "IEEE")]["n_em_comum"] == 2
    assert (pares[("ACM", "Google Scholar")]["n_em_comum"], pares[("ACM", "Google Scholar")]["n_uniao"]) == (1, 13)
    assert pares[("ACM", "Google Scholar")]["jaccard"] == 0.077 and pares[("ACM", "Google Scholar")]["n_incluidos_em_comum"] == 1


def test_termo_por_fonte(ac):
    ac.importar_artigos_manuais(_manuais(*LINHAS_MANUAIS))
    t = {(r["fonte"], r["termo_id"]): r for r in _linhas(ac, "v_rendimento_termo_fonte")}
    assert (t[("Google Scholar", "T01")]["n_artigos"], t[("Google Scholar", "T01")]["n_incluidos"]) == (8, 2)
    assert (t[("IEEE", "T01")]["n_artigos"], t[("IEEE", "T01")]["n_incluidos"], t[("IEEE", "T01")]["taxa_inclusao_pct"]) == (1, 1, 100.0)
    assert t[("ACM", "T25")]["n_artigos"] == 2 and t[("IEEE", "T25")]["n_artigos"] == 1


def test_prisma_com_duplicatas_entre_fontes(ac):
    ac.importar_artigos_manuais(_manuais(*LINHAS_MANUAIS))
    v = _prisma(ac)
    assert v["buscas manuais: artigos importados (por base)"] == 4
    assert v["registros (artigo x fonte) apos remover duplicatas entre termos"] == 16          # 12 Scholar + 2 IEEE + 2 ACM
    assert v["duplicatas entre fontes removidas"] == 3 and v["artigos unicos para triagem"] == 13
    assert v["Google Scholar: artigos unicos"] == 12 and v["pendentes de titulo e resumo"] == 5


@pytest.mark.parametrize("linha, trecho", [
    (("Inexistente", "T01", "Titulo", None, None, None, None, None, ""), "invalido"),
    (("IEEE", "T99", "Titulo", None, None, None, None, None, ""), "invalido"),
    (("IEEE", "T01", "   ", None, None, None, None, None, ""), "Titulo vazio"),
    (("IEEE", "T01", None, None, None, None, None, None, ""), "Titulo vazio"),
])
def test_validacao_dos_artigos_manuais(linha, trecho):
    from aplicacao.manual import validar_artigos_manuais
    with pytest.raises(SystemExit) as e:
        validar_artigos_manuais(_manuais(linha), C.TERMOS, C.BASES_MANUAIS)
    assert trecho in str(e.value)


def test_validacao_exige_as_colunas_obrigatorias():
    from aplicacao.manual import validar_artigos_manuais
    with pytest.raises(SystemExit) as e:
        validar_artigos_manuais(pd.DataFrame([{"base": "IEEE", "termo_id": "T01"}]), C.TERMOS, C.BASES_MANUAIS)
    assert "titulo" in str(e.value)


def test_cli_modelo_e_importacao_de_artigos_manuais(ambiente_cli, monkeypatch, capsys, silencio):
    _rodar(monkeypatch, "manual-artigos-modelo")
    modelo = ambiente_cli / "outputs" / "artigos_manuais_modelo.csv"
    assert modelo.read_bytes().startswith(b"\xef\xbb\xbf")
    assert modelo.read_text(encoding="utf-8-sig").strip() == "base,termo_id,titulo,link,autores_publicacao,ano,citacoes,posicao,data_busca"
    csv = ambiente_cli / "artigos.csv"
    _manuais(*LINHAS_MANUAIS).to_csv(csv, index=False, encoding="utf-8-sig")
    _rodar(monkeypatch, "manual-artigos-importar", str(csv), "--simulado")
    assert "Ocorrências novas: 4 | artigos novos: 2 | linhas no arquivo: 4" in capsys.readouterr().out    # A1 nao existe no banco simulado
    _rodar(monkeypatch, "manual-artigos-importar", str(csv), "--simulado")
    assert "Ocorrências novas: 0 | artigos novos: 0" in capsys.readouterr().out


def test_cli_rejeita_artigos_manuais_invalidos(ambiente_cli, monkeypatch):
    csv = ambiente_cli / "ruim.csv"
    _manuais(("Inexistente", "T01", "Titulo", None, None, None, None, None, "")).to_csv(csv, index=False)
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, "manual-artigos-importar", str(csv), "--simulado")


# ============ 2. revisao por mais de uma pessoa e historico ============
def _triagem(ac, revisor, decisoes, motivo=None):
    return pd.DataFrame([{"artigo_id": _id_artigo(ac, n), "decisao": d, "motivo": motivo, "confirmado_em_base": None,
                          "link_confirmado": None, "revisor": revisor} for n, d in decisoes.items()])


A = {1: "incluir", 2: "incluir", 3: "excluir", 4: "excluir", 5: "incluir"}
B = {1: "incluir", 2: "excluir", 3: "excluir", 4: "excluir", 5: "excluir"}


def _historico(ac):
    return ac.conn.execute("SELECT COUNT(*) FROM triagem_revisoes").fetchone()[0]


def test_revisao_independente_so_entra_no_historico(ac):
    antes = {r["artigo_id"]: r["decisao"] for r in _linhas(ac, "triagem")}
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Bia", B), so_historico=True)
    assert {r["artigo_id"]: r["decisao"] for r in _linhas(ac, "triagem")} == antes        # decisao final intocada
    assert _historico(ac) == 10


def test_concordancia_entre_revisores_com_kappa(ac):
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Bia", B), so_historico=True)
    k = _linhas(ac, "v_concordancia_revisores")
    assert len(k) == 1
    assert (k[0]["revisor_a"], k[0]["revisor_b"], k[0]["n_artigos_em_comum"]) == ("Ana", "Bia", 5)
    assert (k[0]["ambos_incluem"], k[0]["ambos_excluem"], k[0]["discordancias"]) == (1, 2, 2)
    assert k[0]["concordancia_pct"] == 60.0 and k[0]["kappa"] == 0.286


def test_discordancias_para_a_reuniao_de_consenso(ac):
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Bia", B), so_historico=True)
    d = {r["titulo"]: r for r in _linhas(ac, "v_discordancias_triagem")}
    assert set(d) == {"Artigo A2", "Artigo A5"}
    assert (d["Artigo A2"]["decisao_a"], d["Artigo A2"]["decisao_b"], d["Artigo A2"]["decisao_final"]) == ("incluir", "excluir", "incluir")


def test_reimportar_igual_nao_cria_historico_e_mudar_cria(ac):
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Bia", B), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    assert _historico(ac) == 10
    ac.importar_triagem(_triagem(ac, "Ana", {5: "excluir"}), so_historico=True)           # Ana mudou de ideia
    assert _historico(ac) == 11
    k = _linhas(ac, "v_concordancia_revisores")[0]                                          # vale a ultima decisao de cada um
    assert (k["discordancias"], k["concordancia_pct"], k["kappa"]) == (1, 80.0, 0.545)


def test_consenso_e_pendentes_ficam_fora_da_concordancia(ac):
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Bia", {**B, 6: "pendente"}), so_historico=True)
    ac.importar_triagem(_triagem(ac, "consenso", {2: "incluir", 5: "excluir"}))              # decisao final, sem so_historico
    k = _linhas(ac, "v_concordancia_revisores")
    assert len(k) == 1 and k[0]["n_artigos_em_comum"] == 5 and k[0]["kappa"] == 0.286
    assert ac.conn.execute("SELECT decisao FROM triagem WHERE artigo_id=?", (_id_artigo(ac, 5),)).fetchone()[0] == "excluir"
    assert ac.conn.execute("SELECT COUNT(*) FROM triagem_revisoes WHERE revisor='consenso'").fetchone()[0] == 2


def test_revisor_em_branco_vira_sem_revisor(ac):
    df = _triagem(ac, None, {1: "incluir"})
    ac.importar_triagem(df, so_historico=True)
    assert ac.conn.execute("SELECT revisor FROM triagem_revisoes").fetchone()[0] == "(sem revisor)"


def test_importacao_normal_tambem_grava_o_historico(ac):
    ac.importar_triagem(_triagem(ac, "Ana", {3: "incluir"}, motivo="mudei"))
    assert ac.conn.execute("SELECT decisao, motivo FROM triagem WHERE artigo_id=?", (_id_artigo(ac, 3),)).fetchone()[:] == ("incluir", "mudei")
    h = _linhas(ac, "triagem_revisoes")
    assert len(h) == 1 and (h[0]["revisor"], h[0]["decisao"], h[0]["motivo"]) == ("Ana", "incluir", "mudei") and h[0]["importado_em"]


def test_cli_triagem_independente_so_grava_historico(ambiente_cli, monkeypatch, silencio):
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T01", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    xlsx = next((ambiente_cli / "outputs").glob("simulado_resultado_*.xlsx"))
    df = pd.read_excel(xlsx, sheet_name="Triagem").head(3)
    df["decisao"], df["revisor"] = "incluir", "Ana"
    revisao = ambiente_cli / "revisao_ana.xlsx"
    with pd.ExcelWriter(revisao) as xw:
        df.to_excel(xw, sheet_name="Triagem", index=False)
    banco = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    _rodar(monkeypatch, "triagem-importar", str(revisao), "--simulado", "--independente")
    assert banco.execute("SELECT COUNT(*) FROM triagem_revisoes").fetchone()[0] == 3
    assert banco.execute("SELECT COUNT(*) FROM triagem").fetchone()[0] == 0
    _rodar(monkeypatch, "triagem-importar", str(revisao), "--simulado")
    assert banco.execute("SELECT COUNT(*) FROM triagem").fetchone()[0] == 3
    # a importacao normal e de outro tipo (nao independente): tem historico proprio, e so as independentes valem para o kappa
    assert banco.execute("SELECT COUNT(*) FROM triagem_revisoes WHERE independente=1").fetchone()[0] == 3
    assert banco.execute("SELECT COUNT(*) FROM triagem_revisoes WHERE independente=0").fetchone()[0] == 3


# ---------- historico da verificacao dos achados ----------
@pytest.fixture
def web(tmp_path, silencio):
    return construir_web(tmp_path)[0]


def _verificacao(achado_id, status, por, obs=None):
    return pd.DataFrame([{"achado_id": achado_id, "verificado": 1, "status_final": status, "verificado_por": por,
                          "observacao": obs}])


def test_historico_da_verificacao_de_achados(web):
    achado = web.conn.execute("SELECT achado_id FROM achados WHERE verificado=0").fetchone()[0]
    web.importar_verificacao_achados(_verificacao(achado, "em_uso", "Ana", "ok"), STATUS_PERMITIDOS)
    web.importar_verificacao_achados(_verificacao(achado, "em_uso", "Ana", "ok"), STATUS_PERMITIDOS)      # igual: sem linha nova
    assert web.conn.execute("SELECT COUNT(*) FROM achados_revisoes").fetchone()[0] == 1
    web.importar_verificacao_achados(_verificacao(achado, "piloto", "Ana", "corrigido"), STATUS_PERMITIDOS)
    web.importar_verificacao_achados(_verificacao(achado, "piloto", "Bia", "corrigido"), STATUS_PERMITIDOS)
    h = _linhas(web, "achados_revisoes", "ORDER BY revisao_id")
    assert [(x["verificado_por"], x["status_final"]) for x in h] == [("Ana", "em_uso"), ("Ana", "piloto"), ("Bia", "piloto")]
    assert web.conn.execute("SELECT status_final, verificado_por FROM achados WHERE achado_id=?", (achado,)).fetchone()[:] == ("piloto", "Bia")


def test_verificacao_invalida_nao_entra_no_historico(web):
    achado = web.conn.execute("SELECT achado_id FROM achados WHERE verificado=0").fetchone()[0]
    with pytest.raises(SystemExit):
        web.importar_verificacao_achados(_verificacao(achado, "inventado", "Ana"), STATUS_PERMITIDOS)
    assert web.conn.execute("SELECT COUNT(*) FROM achados_revisoes").fetchone()[0] == 0


# ============ 3. etapa de texto completo ============
def _com_texto_completo(ac, linhas):
    df = pd.DataFrame([{"artigo_id": _id_artigo(ac, n), "decisao": "incluir", "motivo": None, "confirmado_em_base": None,
                        "link_confirmado": None, "revisor": "Ana", "decisao_texto_completo": tc, "motivo_texto_completo": m}
                       for n, tc, m in linhas])
    ac.importar_triagem(df)


def test_texto_completo_alimenta_o_prisma_e_os_motivos(ac):
    _com_texto_completo(ac, [(1, "incluir", None), (2, "excluir", "sem dados"), (9, "pendente", None), (12, None, None)])
    v = _prisma(ac)
    assert (v["avaliados por texto completo"], v["excluidos por texto completo"]) == (2, 1)
    assert (v["aguardando texto completo"], v["incluidos no estudo (texto completo)"]) == (2, 1)
    assert v["incluidos por titulo e resumo"] == 4
    m = {(r["etapa"], r["motivo"]): r["n"] for r in _linhas(ac, "v_motivos_exclusao")}
    assert m[("texto_completo", "sem dados")] == 1 and m[("titulo_resumo", "sem IA")] == 2


def test_incluidos_finais_por_termo_e_fonte(ac):
    _com_texto_completo(ac, [(1, "incluir", None), (2, "excluir", "sem dados"), (9, "incluir", None)])
    t = {r["termo_id"]: r["n_incluidos_finais"] for r in _linhas(ac, "v_rendimento_termo")}
    assert t == {"T01": 1, "T02": 2, "T05": 0, "T25": 1}                       # A1 em T01, T02, T25; A9 so em T02
    assert _linhas(ac, "v_rendimento_fonte")[0]["n_incluidos_finais"] == 2


def test_exportacao_da_triagem_traz_as_colunas_de_texto_completo(ac):
    _com_texto_completo(ac, [(1, "incluir", None), (2, "excluir", "sem dados")])
    t = ac.tabelas_para_exportacao()["Triagem"]
    assert list(t.columns)[-2:] == ["decisao_texto_completo", "motivo_texto_completo"]
    linha = t[t["titulo"] == "Artigo A2"].iloc[0]
    assert (linha["decisao_texto_completo"], linha["motivo_texto_completo"]) == ("excluir", "sem dados")


def test_importar_triagem_sem_as_colunas_novas_preserva_o_texto_completo(ac):
    _com_texto_completo(ac, [(1, "incluir", None)])
    ac.importar_triagem(_triagem(ac, "Ana", {1: "incluir"}))                    # planilha antiga, sem as colunas
    assert ac.conn.execute("SELECT decisao_texto_completo FROM triagem WHERE artigo_id=?",
                           (_id_artigo(ac, 1),)).fetchone()[0] == "incluir"


def test_decisao_de_texto_completo_invalida_encerra(ac):
    with pytest.raises(SystemExit) as e:
        _com_texto_completo(ac, [(1, "talvez", None)])
    assert "full-text" in str(e.value)


# ============ 4. auditoria do pre-filtro ============
def _decisoes():
    politica = PoliticaDownload(palavras_chave=("facial",), dominios_excluir=("x.com",), max_urls_por_uf=100)
    cands = [CandidatoDownload(i, f"https://a.gov.br/{i}", "PI", "a.gov.br", "sem" if i < 10 else "facial", "", 1, 1, True)
             for i in range(12)]
    cands.append(CandidatoDownload(99, "https://x.com/1", "PI", "x.com", "facial", "", 1, 1, False))
    return selecionar_candidatos(cands, politica)


def test_amostra_de_auditoria_so_tem_descartados_pelo_prefiltro():
    amostra = escolher_auditoria(_decisoes(), 100, "s")
    assert len(amostra) == 10 and all(d[2] == "prefiltro_palavras" and not d[1] for d in amostra)
    assert {d[0].url_id for d in amostra} == set(range(10))


def test_amostra_de_auditoria_e_reprodutivel_e_depende_da_semente():
    ids = lambda s, n=4: [d[0].url_id for d in escolher_auditoria(_decisoes(), n, s)]
    assert ids("a") == ids("a") and len(ids("a")) == 4
    assert len({tuple(ids(s, 10)) for s in "abcdef"}) > 1
    assert escolher_auditoria(_decisoes(), 0, "a") == [] and escolher_auditoria([], 5, "a") == []


def _run_com_auditoria(tmp_path, auditoria):
    repo = RepositorioSQLite(tmp_path / "au.db")
    bruto = BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, BuscaSemPalavraChave(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0,
                      ufs={"PI"}, auditoria=auditoria, semente="s1")
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    return repo, run_id


def test_sem_auditoria_nada_descartado_e_baixado(tmp_path, silencio):
    repo, run_id = _run_com_auditoria(tmp_path, 0)
    assert repo.conn.execute("SELECT COUNT(*) FROM paginas").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM selecao_download WHERE auditoria=1").fetchone()[0] == 0
    assert _linhas(repo, "v_auditoria_prefiltro") == []


def test_auditoria_baixa_e_classifica_uma_amostra_dos_descartados(tmp_path, silencio):
    repo, run_id = _run_com_auditoria(tmp_path, 2)
    sel = _linhas(repo, "selecao_download")
    assert len(sel) == 3 and all(s["selecionada"] == 0 and s["motivo"] == "prefiltro_palavras" for s in sel)
    assert sum(s["auditoria"] for s in sel) == 2
    assert repo.conn.execute("SELECT COUNT(*) FROM paginas").fetchone()[0] == 2
    assert repo.conn.execute("SELECT COUNT(*) FROM classificacoes").fetchone()[0] == 2
    assert repo.conn.execute("SELECT valor FROM metricas_run WHERE chave='download_auditoria_amostra'").fetchone()[0] == 2
    f = dict(repo.conn.execute("SELECT * FROM v_funil WHERE run_id=?", (run_id,)).fetchone())
    assert (f["pares_url_uf_selecionados"], f["pares_descartados"], f["classificacoes"]) == (0, 3, 2)


def test_view_da_auditoria_estima_o_que_o_prefiltro_perdeu(tmp_path, silencio):
    repo, run_id = _run_com_auditoria(tmp_path, 2)
    a = _linhas(repo, "v_auditoria_prefiltro")[0]
    assert (a["n_descartadas_prefiltro"], a["n_amostra"], a["n_classificadas"], a["n_com_achado"]) == (3, 2, 2, 2)
    assert (a["taxa_com_achado_pct"], a["estimativa_com_achado_entre_descartadas"]) == (100.0, 3.0)
    assert a["n_verificadas"] == 0 and a["n_confirmadas"] == 0


def test_itens_auditados_aparecem_na_resolucao_do_download_e_da_classificacao(tmp_path, silencio):
    repo, _ = _run_com_auditoria(tmp_path, 2)
    d = _linhas(repo, "v_resultado_download")
    assert len(d) == 2 and all(x["auditoria"] == 1 and x["resultado"] == "ok" for x in d)
    assert {x["resultado"] for x in _linhas(repo, "v_resultado_classificacao")} == {"classificado"}


def test_cli_aceita_auditoria_e_registra_nos_argumentos(ambiente_cli, monkeypatch, silencio):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "1")
    busca = sqlite3.connect(ambiente_cli / "data" / "simulado.db").execute("SELECT run_id FROM execucoes").fetchone()[0]
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", busca, "--auditoria", "3")
    banco = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    assert banco.execute("SELECT valor FROM metricas_run WHERE chave='download_auditoria_amostra'").fetchone()[0] == 0   # nada foi descartado
    import json
    amb = json.loads(banco.execute("SELECT ambiente_json FROM execucoes WHERE comando LIKE 'baixar%'").fetchone()[0])
    assert amb["argumentos"]["auditoria"] == 3


# ============ 5. total reportado do Scholar ============
def test_estabilidade_do_total_reportado(ac):
    ac.conn.execute("UPDATE chamadas SET total_reportado=1200 WHERE alvo_id='T01' AND pagina=2")
    e = {r["termo_id"]: r for r in _linhas(ac, "v_total_reportado_estabilidade")}
    assert (e["T01"]["n_paginas"], e["T01"]["total_min"], e["T01"]["total_max"], e["T01"]["total_medio"], e["T01"]["variacao_pct"]) == (2, 1200, 1500, 1350, 20.0)
    assert (e["T02"]["n_paginas"], e["T02"]["variacao_pct"]) == (1, 0.0)


# ============ 6. combinacoes de termos ============
def test_termo_composto_herda_do_pai():
    pai = Termo("T01", '"reconhecimento facial"', "pt", "reconhecimento_identificacao")
    t = termo_composto("T47", pai, '"segurança pública" OR polícia')
    assert t == Termo("T47", '"reconhecimento facial" AND ("segurança pública" OR polícia)', "pt",
                      "reconhecimento_identificacao", "T01")
    assert termo_composto("T48", pai, "x", operador="OR").query == '"reconhecimento facial" OR (x)'


def test_nenhum_termo_da_configuracao_entregue_e_composto():
    assert all(t.pai == "" for t in C.TERMOS)


def test_ganho_de_contexto_compara_o_composto_com_o_pai(tmp_path):
    repo, _ = construir_academico(tmp_path / "c.db", composto=True)
    assert repo.conn.execute("SELECT pai FROM v_termos WHERE termo_id='T99'").fetchone()[0] == "T01"
    assert repo.conn.execute("SELECT pai FROM v_termos WHERE termo_id='T01'").fetchone()[0] in ("", None)
    g = _linhas(repo, "v_ganho_contexto")
    assert len(g) == 1                                                          # so o termo que tem pai
    g = g[0]
    assert (g["termo_composto"], g["termo_pai"]) == ("T99", "T01")
    assert (g["n_artigos_composto"], g["n_artigos_pai"], g["n_em_comum"]) == (3, 8, 2)
    assert (g["so_no_composto"], g["so_no_pai"]) == (1, 6)
    assert (g["n_incluidos_composto"], g["n_incluidos_pai"], g["n_incluidos_em_comum"]) == (3, 2, 2)
    assert (g["incluidos_so_no_composto"], g["incluidos_so_no_pai"]) == (1, 0)
    assert (g["taxa_inclusao_composto_pct"], g["taxa_inclusao_pai_pct"]) == (100.0, 40.0)


def test_composto_aparece_nos_pares_de_termos(tmp_path):
    repo, _ = construir_academico(tmp_path / "c.db", composto=True)
    p = repo.conn.execute("SELECT n_em_comum, jaccard FROM v_pares_termos WHERE termo_a='T01' AND termo_b='T99'").fetchone()
    assert (p["n_em_comum"], p["jaccard"]) == (2, 0.222)


# ============ 7. bancos criados antes das mudancas ============
def _banco_antigo(caminho):
    db = sqlite3.connect(caminho)
    db.executescript("""
        CREATE TABLE execucoes (run_id TEXT PRIMARY KEY, iniciado_em TEXT NOT NULL, finalizado_em TEXT, comando TEXT,
            config_hash TEXT NOT NULL, config_json TEXT NOT NULL, commit_git TEXT, status TEXT NOT NULL DEFAULT 'em_andamento',
            metricas_json TEXT, run_origem TEXT);
        CREATE TABLE selecao_download (run_id TEXT NOT NULL, url_id INTEGER NOT NULL, uf TEXT NOT NULL,
            selecionada INTEGER NOT NULL, motivo TEXT, PRIMARY KEY (run_id, url_id, uf));
        CREATE TABLE achados (achado_id INTEGER PRIMARY KEY AUTOINCREMENT, classificacao_id INTEGER NOT NULL, uf TEXT NOT NULL,
            tecnologia TEXT, status_reportado TEXT, fornecedor TEXT, menciona_lgpd INTEGER, evidencia TEXT,
            evidencia_confere INTEGER, confianca TEXT, verificado INTEGER NOT NULL DEFAULT 0, status_final TEXT,
            verificado_por TEXT, verificado_em TEXT, observacao TEXT);
        CREATE TABLE triagem (artigo_id INTEGER PRIMARY KEY, decisao TEXT NOT NULL DEFAULT 'pendente', motivo TEXT,
            confirmado_em_base TEXT, link_confirmado TEXT, revisor TEXT, revisado_em TEXT);
        CREATE VIEW v_extracao AS SELECT 1 AS definicao_antiga;
        INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json) VALUES ('r1', 'agora', 'h', '{}');
        INSERT INTO achados (classificacao_id, uf, confianca) VALUES (1, 'PI', 'alta');
        INSERT INTO triagem (artigo_id, decisao) VALUES (7, 'incluir');
    """)
    db.commit()
    db.close()


def _colunas(repo, tabela):
    return {r["name"] for r in repo.conn.execute(f"PRAGMA table_info({tabela})")}


def test_banco_antigo_ganha_as_colunas_novas_e_mantem_os_dados(tmp_path):
    _banco_antigo(tmp_path / "antigo.db")
    repo = RepositorioSQLite(tmp_path / "antigo.db")
    assert "ambiente_json" in _colunas(repo, "execucoes") and "auditoria" in _colunas(repo, "selecao_download")
    assert "confianca_original" in _colunas(repo, "achados")
    assert {"decisao_texto_completo", "motivo_texto_completo"} <= _colunas(repo, "triagem")
    assert repo.conn.execute("SELECT run_id FROM execucoes").fetchone()[0] == "r1"
    assert repo.conn.execute("SELECT confianca, confianca_original FROM achados").fetchone()[:] == ("alta", None)
    assert repo.conn.execute("SELECT decisao, decisao_texto_completo FROM triagem").fetchone()[:] == ("incluir", None)
    repo.conn.execute("INSERT INTO selecao_download (run_id, url_id, uf, selecionada) VALUES ('r1', 1, 'PI', 1)")
    assert repo.conn.execute("SELECT auditoria FROM selecao_download").fetchone()[0] == 0


def test_abrir_o_banco_antigo_duas_vezes_e_idempotente(tmp_path):
    _banco_antigo(tmp_path / "antigo.db")
    RepositorioSQLite(tmp_path / "antigo.db")
    RepositorioSQLite(tmp_path / "antigo.db")


def test_views_sao_recriadas_com_a_definicao_atual(tmp_path):
    _banco_antigo(tmp_path / "antigo.db")
    repo = RepositorioSQLite(tmp_path / "antigo.db")
    assert "n_urls" in [c[0] for c in repo.conn.execute("SELECT * FROM v_extracao").description]
    for (nome,) in repo.conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall():
        repo.conn.execute(f"SELECT * FROM {nome}").fetchall()


# ============ exportacao ============
def test_abas_novas_da_exportacao(ac):
    esperadas = {"Saldos", "Metricas_run", "Download_resultado", "Classif_resultado", "Achados_descartados",
                 "Confianca_ajustada", "Auditoria_prefiltro", "Fontes", "Fontes_sobreposicao", "Termos_fonte",
                 "Termos_total_estabilidade", "Ganho_contexto", "Revisores_kappa", "Discordancias",
                 "Historico_triagem", "Historico_achados"}
    tabelas = ac.tabelas_para_exportacao()
    assert esperadas <= set(tabelas) and all(len(n) <= 31 for n in tabelas)


# ============ kappa: so revisoes independentes ============
def test_reimportacao_normal_depois_do_consenso_nao_contamina_o_kappa(ac):
    ac.importar_triagem(_triagem(ac, "Ana", A), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Bia", B), so_historico=True)
    antes = _linhas(ac, "v_concordancia_revisores")[0]["kappa"]
    ac.importar_triagem(_triagem(ac, "Ana", {2: "excluir", 5: "excluir"}))         # Ana reimporta a planilha do consenso
    k = _linhas(ac, "v_concordancia_revisores")[0]
    assert antes == k["kappa"] == 0.286 and k["discordancias"] == 2
    assert {x["artigo_id"] for x in _linhas(ac, "v_discordancias_triagem")} == {_id_artigo(ac, 2), _id_artigo(ac, 5)}


def test_historico_distingue_importacao_independente_da_normal(ac):
    ac.importar_triagem(_triagem(ac, "Ana", {1: "incluir"}), so_historico=True)
    ac.importar_triagem(_triagem(ac, "Ana", {1: "incluir"}))                          # mesma decisao, outro tipo: nova linha
    ac.importar_triagem(_triagem(ac, "Ana", {1: "incluir"}))                          # repetida: sem linha nova
    h = _linhas(ac, "triagem_revisoes", "ORDER BY revisao_id")
    assert [x["independente"] for x in h] == [1, 0]


def test_revisao_normal_sozinha_nao_entra_no_kappa(ac):
    ac.importar_triagem(_triagem(ac, "Ana", A))
    ac.importar_triagem(_triagem(ac, "Bia", B))
    assert _linhas(ac, "v_concordancia_revisores") == [] and _linhas(ac, "v_discordancias_triagem") == []


def test_banco_antigo_recebe_a_coluna_independente(tmp_path):
    db = sqlite3.connect(tmp_path / "antigo.db")
    db.executescript("""CREATE TABLE triagem_revisoes (revisao_id INTEGER PRIMARY KEY AUTOINCREMENT, artigo_id INTEGER NOT NULL,
        revisor TEXT NOT NULL, decisao TEXT NOT NULL, motivo TEXT, decisao_texto_completo TEXT, motivo_texto_completo TEXT,
        importado_em TEXT NOT NULL);
        INSERT INTO triagem_revisoes (artigo_id, revisor, decisao, importado_em) VALUES (1, 'Ana', 'incluir', 'x');""")
    db.commit()
    db.close()
    repo = RepositorioSQLite(tmp_path / "antigo.db")
    assert repo.conn.execute("SELECT independente FROM triagem_revisoes").fetchone()[0] == 0     # historico antigo: nao independente


# ============ auditoria marcada nos achados e no funil ============
def test_achados_e_funil_marcam_o_que_veio_da_auditoria(tmp_path, silencio):
    repo, run_id = _run_com_auditoria(tmp_path, 2)
    f = dict(repo.conn.execute("SELECT * FROM v_funil WHERE run_id=?", (run_id,)).fetchone())
    assert (f["pares_auditoria"], f["paginas_auditoria"], f["achados_auditoria"]) == (2, 2, 2)
    assert f["paginas_baixadas"] - f["paginas_auditoria"] == f["pares_url_uf_selecionados"] == 0     # comparavel com os selecionados
    a = _linhas(repo, "v_achados_revisao")
    assert len(a) == 2 and all(x["auditoria"] == 1 for x in a)


def test_pipeline_sem_auditoria_nao_marca_nada(web):
    assert all(x["auditoria"] == 0 for x in _linhas(web, "v_achados_revisao"))
    f = _linhas(web, "v_funil")[0]
    assert (f["pares_auditoria"], f["paginas_auditoria"], f["achados_auditoria"]) == (0, 0, 0)


def test_par_selecionado_de_verdade_nao_conta_como_auditoria(tmp_path, silencio):
    repo, run_id = _run_com_auditoria(tmp_path, 2)
    par = repo.conn.execute("SELECT url_id, uf FROM selecao_download WHERE auditoria=1 LIMIT 1").fetchone()
    repo.conn.execute("INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json) VALUES ('outra', 'x', 'h', '{}')")
    repo.conn.execute("INSERT INTO selecao_download (run_id, url_id, uf, selecionada, auditoria) VALUES ('outra', ?, ?, 1, 0)",
                      (par["url_id"], par["uf"]))
    pares = {(r["url_id"], r["uf"]) for r in _linhas(repo, "v_pares_auditoria")}
    assert (par["url_id"], par["uf"]) not in pares and len(pares) == 1


def test_aba_passadas_na_exportacao(ac):
    assert "Passadas" in ac.tabelas_para_exportacao()
