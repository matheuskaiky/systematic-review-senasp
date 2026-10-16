import sqlite3
import sys

import pytest

import main
import config.settings as S
from composicao import Fabrica


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def _banco(tmp_path):
    conn = sqlite3.connect(tmp_path / "data" / "simulado.db")
    conn.row_factory = sqlite3.Row
    return conn


def _runs(tmp_path):
    return _banco(tmp_path).execute("SELECT * FROM execucoes ORDER BY iniciado_em, run_id").fetchall()


def _n(tmp_path, sql, *args):
    return _banco(tmp_path).execute(sql, args).fetchone()[0]


# ---------- C5: --de ----------
def test_classificar_sem_de_encerra_com_mensagem_e_nao_cria_execucao(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "classificar", "--simulado")
    assert "--de" in str(e.value)
    assert _runs(ambiente_cli) == []


def test_baixar_sem_de_encerra_com_mensagem(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "baixar", "--simulado")
    assert "--de" in str(e.value)


def test_de_inexistente_encerra_com_mensagem(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "classificar", "--simulado", "--de", "nao_existe")
    assert "nao_existe" in str(e.value)


def test_comandos_completos_nao_exigem_de(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "pipeline-uf", "--simulado", "--ufs", "PI", "--limite", "2")
    assert [r["status"] for r in _runs(ambiente_cli)] == ["concluida"]


def _busca_e_baixa(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "3")
    busca = _runs(ambiente_cli)[0]["run_id"]
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", busca)
    baixa = [r for r in _runs(ambiente_cli) if r["run_id"] != busca][0]["run_id"]
    return busca, baixa


def test_etapas_encadeadas_por_de(ambiente_cli, monkeypatch):
    busca, baixa = _busca_e_baixa(ambiente_cli, monkeypatch)
    _rodar(monkeypatch, "classificar", "--simulado", "--ufs", "PI", "--de", baixa)
    assert _n(ambiente_cli, "SELECT run_origem FROM execucoes WHERE run_id=?", baixa) == busca
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM classificacoes") == 3


def test_retomar_sem_de_reaproveita_o_de_guardado(ambiente_cli, monkeypatch):
    busca, baixa = _busca_e_baixa(ambiente_cli, monkeypatch)
    chamadas = _n(ambiente_cli, "SELECT COUNT(*) FROM chamadas")
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--retomar", baixa)    # sem --de
    assert _n(ambiente_cli, "SELECT run_origem FROM execucoes WHERE run_id=?", baixa) == busca
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM chamadas") == chamadas              # nada novo
    assert _n(ambiente_cli, "SELECT status FROM execucoes WHERE run_id=?", baixa) == "concluida"


# ---------- retomada ----------
def test_tudo_retomar_nao_adiciona_chamadas(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1")
    run_id = _runs(ambiente_cli)[0]["run_id"]
    antes = _n(ambiente_cli, "SELECT COUNT(*) FROM chamadas")
    sucessos = _n(ambiente_cli, "SELECT COUNT(*) FROM chamadas WHERE sucesso=1")
    assert antes == sucessos                                                  # nenhuma falha no simulado
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1", "--retomar", run_id)
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM chamadas") == antes
    assert len(_runs(ambiente_cli)) == 1


def test_tudo_simulado_registra_saldos_e_achados_com_evidencia(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1")
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM saldos") == 2
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM achados") == 6
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM achados WHERE evidencia_confere=1") == 6


def test_retomar_com_configuracao_alterada_encerra(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "1")
    run_id = _runs(ambiente_cli)[0]["run_id"]
    monkeypatch.setitem(S.PROVEDORES, "classificador", "openai_compat")
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--retomar", run_id)


# ---------- execucao que encerra por SystemExit (falta de chave) ----------
def test_execucao_que_encerra_por_falta_de_chave_nao_consta_como_concluida(ambiente_cli, monkeypatch):
    class SemChave(Fabrica):
        @property
        def busca_web(self):
            raise SystemExit("Set PERPLEXITY_API_KEY in .env to use 'perplexity_search'")

    monkeypatch.setattr(main, "Fabrica", SemChave)
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI")
    assert [r["status"] for r in _runs(ambiente_cli)] == ["falhou"]


# ---------- C9: estimar ----------
def test_estimar_real_funciona_sem_chave(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "estimar")
    saida = capsys.readouterr().out
    assert "Web queries: 270" in saida
    assert "Saldo: indisponível" in saida


def test_estimar_simulado_mostra_saldo(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "estimar", "--simulado")
    assert "Academic provider balance: 999" in capsys.readouterr().out


# ---------- C6: exportar e importar com --simulado ----------
def test_exportar_simulado_gera_planilha_com_prefixo(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    arquivos = list((ambiente_cli / "outputs").glob("simulado_resultado_*.xlsx"))
    assert len(arquivos) == 1
    import pandas as pd
    abas = pd.ExcelFile(arquivos[0]).sheet_names
    assert {"Achados", "Funil", "Resumo_UF", "Triagem", "Artigos"} <= set(abas)
    assert len(pd.read_excel(arquivos[0], sheet_name="Resumo_UF")) == 27


def test_exportar_com_saida_explicita(ambiente_cli, monkeypatch):
    destino = ambiente_cli / "x" / "meu.xlsx"
    _rodar(monkeypatch, "exportar", "--simulado", "--saida", str(destino))
    assert destino.exists()


def test_importadores_aceitam_simulado(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "--paginas", "1")
    _rodar(monkeypatch, "exportar", "--simulado")
    xlsx = next((ambiente_cli / "outputs").glob("simulado_resultado_*.xlsx"))
    _rodar(monkeypatch, "achados-importar", str(xlsx), "--simulado")
    _rodar(monkeypatch, "triagem-importar", str(xlsx), "--simulado")


def test_manual_modelo_gera_csv(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "manual-modelo")
    csv = ambiente_cli / "outputs" / "buscas_manuais_modelo.csv"
    assert csv.read_bytes().startswith(b"\xef\xbb\xbf")             # utf-8-sig
    n_linhas = len(csv.read_text(encoding="utf-8-sig").strip().splitlines())
    assert n_linhas == 1 + len(main.C.TERMOS) * len(main.C.BASES_MANUAIS)


def test_execucao_grava_o_resumo_de_metricas(ambiente_cli, monkeypatch):
    import json
    _rodar(monkeypatch, "tudo", "--simulado", "--ufs", "PI", "CE", "--paginas", "1")
    linha = _runs(ambiente_cli)[0]
    m = json.loads(linha["metricas_json"])
    assert linha["status"] == "concluida" and linha["finalizado_em"] and linha["config_hash"] and linha["config_json"]
    esperadas = len(main.C.TERMOS) + 20 + 6 + 6      # academico + busca web + download + classificacao
    assert (m["chamadas"], m["sucesso"], m["falhas"]) == (esperadas, esperadas, 0)
    assert (m["tokens_entrada"], m["tokens_saida"], m["custo_usd"]) == (600, 120, 0.0)
    assert m["latencia_media_ms"] == 1
    metricas = {l["chave"]: l["valor"] for l in _banco(ambiente_cli).execute("SELECT * FROM metricas_run")}
    # alteracao deliberada: o download agora registra `download_desistencias` (paginas abandonadas por excesso de falhas)
    assert metricas == {"download_candidatos": 6, "download_selecionados": 6, "download_auditoria_amostra": 0,
                        "download_desistencias": 0, "classificacao_ignorados_sem_texto": 0, "classificacao_desistencias": 0,
                        "classificacao_nome_solucao_descartado": 0}      # RC15: nomes de solucao descartados por nao estarem no texto


def test_migrar_robots_esta_na_ajuda_do_programa(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "migrar-robots", "--help"])
    with pytest.raises(SystemExit) as e:
        main.main()
    saida = capsys.readouterr().out
    assert e.value.code == 0 and "--aplicar" in saida and "copia de seguranca" in saida


def test_painel_somente_leitura_recusa_esquema_desatualizado(tmp_path, monkeypatch):
    """O painel nao grava em --somente-leitura: com o esquema antigo ele avisa em vez de abrir com views faltando."""
    import sqlite3
    import pytest
    import main
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    banco = tmp_path / "busca.db"
    RepositorioSQLite(banco).fechar()
    c = sqlite3.connect(banco)
    c.execute("UPDATE meta_schema SET valor='antiga' WHERE chave='assinatura'")
    c.commit()
    c.close()
    monkeypatch.setitem(main.S.OPCOES["sqlite"], "caminho", banco)
    argv = ["main.py", "painel", "--somente-leitura", "--porta", "8999"]
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as e:
        main.main()
    assert "desatualizado" in str(e.value)
