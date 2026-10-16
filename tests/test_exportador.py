"""M8: exportador Excel (C3), aba Secretarias (C4), importacao manual idempotente (C7) e o ciclo de verificacao humana."""
import sqlite3
import sys

import pandas as pd
import pytest

import main
import config.settings as S
from adaptadores.exportador_excel import ExportadorExcel, LIMITE_CELULA, MARCADOR
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def _banco(tmp_path):
    c = sqlite3.connect(tmp_path / "data" / "simulado.db")
    c.row_factory = sqlite3.Row
    return c


def _planilha(tmp_path):
    return next((tmp_path / "outputs").glob("simulado_resultado_*.xlsx"))


# ============================== C3: exportador ==============================
def test_c3_caractere_de_controle_e_celula_gigante_nao_quebram(tmp_path):
    df = pd.DataFrame({"a": ["texto\x07com\x00sino", "x" * 40_000, "normal"], "n": [1, 2, 3]})
    caminho = ExportadorExcel().exportar({"T": df}, tmp_path / "s.xlsx")
    lido = pd.read_excel(caminho, sheet_name="T")
    assert lido["a"][0] == "textocomsino" and lido["a"][2] == "normal"
    assert len(lido["a"][1]) == LIMITE_CELULA and lido["a"][1].endswith(MARCADOR)
    assert list(lido["n"]) == [1, 2, 3]


def test_c3_texto_no_limite_nao_e_alterado(tmp_path):
    texto = "y" * LIMITE_CELULA
    caminho = ExportadorExcel().exportar({"T": pd.DataFrame({"a": [texto]})}, tmp_path / "s.xlsx")
    assert pd.read_excel(caminho, sheet_name="T")["a"][0] == texto


def test_c3_texto_da_web_que_comeca_com_igual_nao_vira_formula(tmp_path):
    from openpyxl import load_workbook
    caminho = ExportadorExcel().exportar({"T": pd.DataFrame({"a": ['=HYPERLINK("http://x","clique")']})}, tmp_path / "s.xlsx")
    celula = load_workbook(caminho)["T"]["A2"]
    assert celula.data_type == "s" and "HYPERLINK" in celula.value


def test_c3_nao_altera_o_dataframe_de_entrada_nem_tipos_nao_texto(tmp_path):
    df = pd.DataFrame({"a": ["\x07x"], "n": [1.5], "d": [None]})
    ExportadorExcel().exportar({"T": df}, tmp_path / "s.xlsx")
    assert df["a"][0] == "\x07x"


def test_c3_pasta_vem_da_opcao_e_nome_de_aba_e_cortado_em_31(tmp_path):
    caminho = ExportadorExcel(pasta=tmp_path / "saida").exportar({"A" * 40: pd.DataFrame({"a": [1]})})
    assert caminho.startswith(str(tmp_path / "saida")) and pd.ExcelFile(caminho).sheet_names == ["A" * 31]


def test_c3_abas_que_colidem_depois_do_corte_sao_recusadas(tmp_path):
    with pytest.raises(ValueError, match="repetidos"):
        ExportadorExcel().exportar({"A" * 31 + "1": pd.DataFrame(), "A" * 31 + "2": pd.DataFrame()}, tmp_path / "s.xlsx")


def test_c3_opcao_excel_tem_a_pasta_de_saida():
    assert "pasta" in S.OPCOES["excel"]


def test_nomes_de_aba_da_exportacao_real_sao_unicos_e_cabem_em_31(tmp_path):
    repo = RepositorioSQLite(tmp_path / "t.db")
    nomes = list(repo.tabelas_para_exportacao()) + ["Resumo_UF"]
    assert len({n[:31] for n in nomes}) == len(nomes) and all(len(n) <= 31 for n in nomes)


# ============================== ciclo completo (secao 13) ==============================
def test_exportacao_gera_todas_as_abas_e_resumo_com_27_ufs(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    esperadas = set(RepositorioSQLite(ambiente_cli / "x.db").tabelas_para_exportacao()) - {"Resumo_UF_bruto"}
    abas = set(pd.ExcelFile(_planilha(ambiente_cli)).sheet_names)
    assert esperadas | {"Resumo_UF", "Secretarias"} <= abas and "Resumo_UF_bruto" not in abas
    assert len(pd.read_excel(_planilha(ambiente_cli), sheet_name="Resumo_UF")) == 27


def _verificar(xlsx, destino, ids_confirmados, id_descartado):
    """Simula a revisao humana: grava uma planilha so com a aba Achados editada."""
    df = pd.read_excel(xlsx, sheet_name="Achados")
    df["verificado"] = df["verificado"].astype(float)
    df["status_final"] = df["status_final"].astype(object)
    df["verificado_por"] = df["verificado_por"].astype(object)
    for i in ids_confirmados:
        df.loc[df["achado_id"] == i, ["verificado", "status_final", "verificado_por"]] = [1, "em_uso", "revisor1"]
    df.loc[df["achado_id"] == id_descartado, ["verificado", "status_final", "verificado_por"]] = [1, "descartado", "revisor1"]
    with pd.ExcelWriter(destino) as xw:
        df.to_excel(xw, sheet_name="Achados", index=False)


def test_ciclo_de_verificacao_alimenta_resumo_uf_e_secretarias(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    primeira = _planilha(ambiente_cli)
    assert len(pd.read_excel(primeira, sheet_name="Secretarias")) == 0              # nada verificado ainda
    ids = list(pd.read_excel(primeira, sheet_name="Achados")["achado_id"])
    assert len(ids) >= 3
    editada = ambiente_cli / "editada.xlsx"
    _verificar(primeira, editada, ids[:2], ids[2])
    _rodar(monkeypatch, "achados-importar", str(editada), "--simulado")

    novo = ambiente_cli / "outputs" / "segunda.xlsx"
    _rodar(monkeypatch, "exportar", "--simulado", "--saida", str(novo))
    sec = pd.read_excel(novo, sheet_name="Secretarias")
    assert sorted(sec["achado_id"]) == sorted(ids[:2])                                # exatamente os confirmados
    assert set(sec["status_final"]) == {"em_uso"} and set(sec["verificado_por"]) == {"revisor1"}
    assert {"uf", "tecnologia", "fornecedor", "menciona_lgpd", "evidencia", "url", "dominio", "fonte_oficial"} <= set(sec.columns)
    resumo = pd.read_excel(novo, sheet_name="Resumo_UF")
    assert resumo["n_verificados"].sum() == 3 and resumo["n_confirmados"].sum() == 2
    assert len(resumo) == 27


def test_status_final_invalido_encerra_com_mensagem(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    df = pd.read_excel(_planilha(ambiente_cli), sheet_name="Achados")
    df["status_final"] = df["status_final"].astype(object)
    df.loc[0, ["verificado", "status_final"]] = [1, "inventado"]
    ruim = ambiente_cli / "ruim.xlsx"
    with pd.ExcelWriter(ruim) as xw:
        df.to_excel(xw, sheet_name="Achados", index=False)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "achados-importar", str(ruim), "--simulado")
    assert "status_final" in str(e.value) and "inventado" in str(e.value)


def test_triagem_importar_so_aceita_pendente_incluir_excluir(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    tri = pd.read_excel(_planilha(ambiente_cli), sheet_name="Triagem")
    tri["decisao"] = tri["decisao"].astype(object)
    tri["revisor"] = "r1"
    tri.loc[0, "decisao"] = "incluir"
    tri.loc[1, "decisao"] = "EXCLUIR "          # maiusculas e espacos sao normalizados
    ok = ambiente_cli / "tri_ok.xlsx"
    with pd.ExcelWriter(ok) as xw:
        tri.to_excel(xw, sheet_name="Triagem", index=False)
    _rodar(monkeypatch, "triagem-importar", str(ok), "--simulado")
    decisoes = dict(_banco(ambiente_cli).execute("SELECT artigo_id, decisao FROM triagem").fetchall())
    assert decisoes[int(tri.loc[0, "artigo_id"])] == "incluir" and decisoes[int(tri.loc[1, "artigo_id"])] == "excluir"
    tri.loc[0, "decisao"] = "talvez"
    ruim = ambiente_cli / "tri_ruim.xlsx"
    with pd.ExcelWriter(ruim) as xw:
        tri.to_excel(xw, sheet_name="Triagem", index=False)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triagem-importar", str(ruim), "--simulado")
    assert "talvez" in str(e.value)


# ============================== C7: busca manual ==============================
def _preencher_modelo(ambiente_cli, linhas):
    """Abre o modelo gerado pelo CLI (utf-8-sig), preenche algumas linhas como o pesquisador faria e regrava."""
    modelo = ambiente_cli / "outputs" / "buscas_manuais_modelo.csv"
    df = pd.read_csv(modelo, encoding="utf-8-sig", dtype=str)
    for i, (n, ap, sel, data) in enumerate(linhas):
        df.loc[i, ["n_resultados", "n_apos_filtro", "n_selecionados", "data_busca"]] = [n, ap, sel, data]
    cheio = ambiente_cli / "manual_preenchido.csv"
    df.to_csv(cheio, index=False, encoding="utf-8-sig")
    return cheio


def test_c7_o_modelo_gerado_pelo_cli_e_lido_de_volta_com_as_colunas_certas(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    cheio = _preencher_modelo(ambiente_cli, [("120", "80", "10", "2026-10-01")])
    _rodar(monkeypatch, "manual-importar", str(cheio), "--simulado")
    linha = _banco(ambiente_cli).execute("SELECT * FROM buscas_manuais").fetchall()
    assert len(linha) == 1 and linha[0]["base"] == C.BASES_MANUAIS[0] and linha[0]["termo_id"] == "T01"
    assert (linha[0]["n_resultados"], linha[0]["n_apos_filtro"], linha[0]["n_selecionados"]) == (120, 80, 10)


def test_c7_importar_duas_vezes_deixa_o_mesmo_numero_de_linhas(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    cheio = _preencher_modelo(ambiente_cli, [("120", "80", "10", "2026-10-01"), ("30", "20", "5", "2026-10-02")])
    _rodar(monkeypatch, "manual-importar", str(cheio), "--simulado")
    _rodar(monkeypatch, "manual-importar", str(cheio), "--simulado")
    assert _banco(ambiente_cli).execute("SELECT COUNT(*) FROM buscas_manuais").fetchone()[0] == 2


def test_c7_reimportar_com_numero_corrigido_substitui_a_linha(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    _rodar(monkeypatch, "manual-importar", str(_preencher_modelo(ambiente_cli, [("120", "80", "10", "2026-10-01")])), "--simulado")
    _rodar(monkeypatch, "manual-importar", str(_preencher_modelo(ambiente_cli, [("125", "80", "10", "2026-10-01")])), "--simulado")
    linhas = _banco(ambiente_cli).execute("SELECT n_resultados FROM buscas_manuais").fetchall()
    assert [l[0] for l in linhas] == [125]


def test_c7_data_diferente_e_outra_busca(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    _rodar(monkeypatch, "manual-importar", str(_preencher_modelo(ambiente_cli, [("120", "80", "10", "2026-10-01")])), "--simulado")
    _rodar(monkeypatch, "manual-importar", str(_preencher_modelo(ambiente_cli, [("90", "70", "9", "2026-11-01")])), "--simulado")
    assert _banco(ambiente_cli).execute("SELECT COUNT(*) FROM buscas_manuais").fetchone()[0] == 2


def test_c7_sem_data_a_chave_tambem_e_idempotente(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    cheio = _preencher_modelo(ambiente_cli, [("120", "80", "10", None)])
    _rodar(monkeypatch, "manual-importar", str(cheio), "--simulado")
    _rodar(monkeypatch, "manual-importar", str(cheio), "--simulado")
    assert _banco(ambiente_cli).execute("SELECT COUNT(*) FROM buscas_manuais").fetchone()[0] == 1


def test_c7_chave_repetida_no_mesmo_arquivo_e_recusada_sem_gravar_nada(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    df = pd.read_csv(ambiente_cli / "outputs" / "buscas_manuais_modelo.csv", encoding="utf-8-sig", dtype=str).iloc[[0, 0]].copy()
    df["n_resultados"], df["data_busca"] = ["5", "7"], "2026-10-01"
    arq = ambiente_cli / "dup.csv"
    df.to_csv(arq, index=False, encoding="utf-8-sig")
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "manual-importar", str(arq), "--simulado")
    assert "mesma chave" in str(e.value)
    assert _banco(ambiente_cli).execute("SELECT COUNT(*) FROM buscas_manuais").fetchone()[0] == 0


def test_manual_rejeita_termo_id_ou_base_invalidos(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    for coluna, valor in (("termo_id", "T999"), ("base", "BaseInventada")):
        df = pd.read_csv(ambiente_cli / "outputs" / "buscas_manuais_modelo.csv", encoding="utf-8-sig", dtype=str).iloc[[0]].copy()
        df[coluna], df["n_resultados"] = valor, "5"
        arq = ambiente_cli / f"ruim_{coluna}.csv"
        df.to_csv(arq, index=False, encoding="utf-8-sig")
        with pytest.raises(SystemExit) as e:
            _rodar(monkeypatch, "manual-importar", str(arq), "--simulado")
        assert "Invalid termo_id or base" in str(e.value)
    # a validacao encerra antes de abrir o banco: nada foi gravado (o arquivo do banco nem chegou a existir)
    assert not (ambiente_cli / "data" / "simulado.db").exists()


def test_c7_linhas_sem_n_resultados_sao_ignoradas(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "manual-modelo")
    _rodar(monkeypatch, "manual-importar", str(ambiente_cli / "outputs" / "buscas_manuais_modelo.csv"), "--simulado")
    assert "Rows imported: 0" in capsys.readouterr().out


def test_planilha_de_download_traz_os_dois_motivos_de_bloqueio_do_robots(tmp_path):
    """Aba Download_resultado: `bloqueado_por_robots` (robots.txt lido e proibindo) e `robots_inacessivel` aparecem como motivos
    separados, com o erro original e o `http_status` vazio."""
    from adaptadores.bruto_local import BrutoLocal
    from aplicacao import busca_web, download, exportacao
    from dados_metricas import Busca4Urls, _consulta_pi, _novo_run
    from dominio.modelos import ArquivoBaixado
    from adaptadores.simulados import ExtratorSimulado, FetcherSimulado

    class Fetcher(FetcherSimulado):
        def baixar(self, url):
            base = super().baixar(url)
            reg = base.chamada
            if url.endswith("/pi/1"):
                reg.erro, reg.http_status = "bloqueado_por_robots", None
                reg.extras.update(robots_permitido=False, robots_status=200, robots_inacessivel=False, robots_tentativas=1)
            elif url.endswith("/pi/2"):
                reg.erro, reg.http_status = "robots_inacessivel", None
                reg.extras.update(robots_permitido=False, robots_status=503, robots_inacessivel=True, robots_tentativas=3)
            else:
                return base
            return ArquivoBaixado(url, None, "", b"", False, reg)

    repo, bruto = RepositorioSQLite(tmp_path / "x.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "baixar")
    busca_web.executar(repo, bruto, Busca4Urls(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, Fetcher(), ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    caminho = ExportadorExcel().exportar(exportacao.montar_tabelas(repo, C.UFS), tmp_path / "s.xlsx")
    aba = pd.read_excel(caminho, sheet_name="Download_resultado")
    por_motivo = {l["motivo"]: l for _, l in aba.iterrows() if l["resultado"] == "falha_download"}
    assert set(por_motivo) == {"bloqueado_por_robots", "robots_inacessivel"}
    assert por_motivo["bloqueado_por_robots"]["erro"] == "bloqueado_por_robots" and pd.isna(por_motivo["robots_inacessivel"]["http_status"])
    assert por_motivo["robots_inacessivel"]["erro"] == "robots_inacessivel"
