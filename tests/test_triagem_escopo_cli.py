"""Comando `triar-escopo`: regra 11 (so por amostra), --estimar sem chamada e sem chave, execucao simulada."""
import json
import sqlite3
import sys

import pytest

import main
import config.settings as S
from adaptadores import triador_gemini
from adaptadores.simulados import TriadorSimulado
from config import triagem_escopo as TE
from dados_metricas import construir_academico


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def _banco(tmp_path, nome="simulado.db"):
    conn = sqlite3.connect(tmp_path / "data" / nome)
    conn.row_factory = sqlite3.Row
    return conn


def _n(tmp_path, sql, nome="simulado.db"):
    return _banco(tmp_path, nome).execute(sql).fetchone()[0]


@pytest.fixture
def simulado(ambiente_cli, monkeypatch):
    """Banco simulado com 12 artigos (4 termos, 1 pagina)."""
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T01", "T02", "T03", "T04", "--paginas", "1")
    return ambiente_cli


@pytest.fixture
def banco_real_falso(ambiente_cli, monkeypatch):
    """O `busca.db` aponta para um arquivo temporario (o caminho real e fixado na importacao de config.settings)."""
    destino = ambiente_cli / "data" / "busca.db"
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", destino)
    repo, _ = construir_academico(destino)
    repo.fechar()

    def sem_rede(*a, **k):
        raise AssertionError("chamada de rede nao permitida nos testes")
    monkeypatch.setattr(triador_gemini, "chamar", sem_rede)
    return ambiente_cli


def test_recusa_sem_amostra_nem_limite_e_nao_cria_execucao(ambiente_cli, monkeypatch):
    for fonte in ("artigos", "web"):
        with pytest.raises(SystemExit) as e:
            _rodar(monkeypatch, "triar-escopo", "--fonte", fonte, "--simulado")
        msg = str(e.value)
        assert "regra 11" in msg and "--amostra" in msg and "--limite" in msg and "--tudo" in msg and "--estimar" in msg
    assert not (ambiente_cli / "data" / "simulado.db").exists()          # recusou antes de abrir o banco


def test_lote_acima_do_maximo_e_recusado(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--amostra", "5", "--lote", "51")
    assert "50" in str(e.value)
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--amostra", "5", "--lote", "0")


def test_fonte_e_obrigatoria_e_validada(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, "triar-escopo", "--simulado", "--amostra", "5")
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, "triar-escopo", "--fonte", "livros", "--simulado", "--amostra", "5")


def test_estimar_nao_faz_chamada_nao_pede_chave_e_nao_cria_execucao(banco_real_falso, monkeypatch, capsys):
    import os
    assert not os.environ.get("GEMINI_API_KEY")
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--estimar", "--amostra", "6", "--estratificar")
    saida = capsys.readouterr().out
    assert "Itens no banco: 12 | na amostra: 6 | já triados com este prompt: 0 | a triar: 6" in saida
    assert "Lote: 10 | chamadas (requisições): 1" in saida and "Custo estimado (US$): baixo" in saida
    assert "chamadas (requisições): 1" in saida and "Nível gratuito: limite de 500 requisições por dia por modelo" in saida
    assert "usaria 0.2% da cota diária" in saida
    assert "janela de contexto" in saida and "por chamada" in saida and "ordem de grandeza" in saida
    assert _n(banco_real_falso, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo'", "busca.db") == 0
    assert _n(banco_real_falso, "SELECT COUNT(*) FROM execucoes WHERE comando LIKE 'triar-escopo%'", "busca.db") == 0
    # sem --amostra, --estimar mostra o conjunto inteiro (nao e uma execucao paga)
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--estimar")
    assert "na amostra: 12" in capsys.readouterr().out


def test_execucao_real_sem_chave_encerra_sem_chamar_e_nao_consta_como_concluida(banco_real_falso, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--amostra", "3")
    assert "GEMINI_API_KEY" in str(e.value)
    assert _n(banco_real_falso, "SELECT status FROM execucoes WHERE comando='triar-escopo'", "busca.db") == "falhou"
    assert _n(banco_real_falso, "SELECT COUNT(*) FROM triagem_escopo", "busca.db") == 0


def test_simulado_com_amostra_grava_triagem_e_registra_execucao(simulado, monkeypatch, capsys):
    antes = {t: _n(simulado, f"SELECT COUNT(*) FROM {t}") for t in ("triagem", "achados", "artigos")}
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--amostra", "12", "--estratificar")
    saida = capsys.readouterr().out
    assert "12 itens triados em 2 chamadas" in saida
    assert _n(simulado, "SELECT COUNT(*) FROM triagem_escopo") == 12
    assert _n(simulado, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo' AND sucesso=1") == 2
    ex = _banco(simulado).execute("SELECT * FROM execucoes WHERE comando LIKE 'triar-escopo%'").fetchone()
    assert ex["comando"] == "triar-escopo [simulado]" and ex["status"] == "concluida" and ex["run_origem"] is None
    cfg = json.loads(ex["config_json"])
    assert cfg["triagem_escopo"]["versao"] == "t1" and cfg["triagem_escopo"]["lote"] == 10
    assert "elegivel" in cfg["triagem_escopo"]["status"] and "TEMPORAL RULE" in cfg["triagem_escopo"]["sistema_artigo"]
    assert "termos" in cfg and ex["config_hash"] != S.snapshot_config()["hash"] and len(ex["config_hash"]) == 12
    assert {t: _n(simulado, f"SELECT COUNT(*) FROM {t}") for t in antes} == antes
    # repetir o mesmo comando nao chama de novo
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--amostra", "12", "--estratificar")
    assert "Nada a triar" in capsys.readouterr().out
    assert _n(simulado, "SELECT COUNT(*) FROM chamadas WHERE etapa='triagem_escopo'") == 2


def test_simulado_limite_e_lote_menor(simulado, monkeypatch, capsys):
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--limite", "5", "--lote", "2")
    assert "5 itens triados em 3 chamadas" in capsys.readouterr().out
    assert _n(simulado, "SELECT valor FROM metricas_run WHERE chave='triagem_escopo_lote'") == 2


def test_teto_de_custo_padrao_e_o_da_configuracao(simulado, monkeypatch, capsys):
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--amostra", "3")
    assert f"teto US$ {TE.MAX_CUSTO_PADRAO_USD:.2f}" in capsys.readouterr().out


def test_tudo_mostra_a_estimativa_antes_de_rodar(simulado, monkeypatch, capsys):
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--tudo")
    saida = capsys.readouterr().out
    assert saida.index("Custo estimado") < saida.index("itens triados em")
    assert _n(simulado, "SELECT COUNT(*) FROM triagem_escopo") == 12


def test_web_simulado_com_amostra(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "pipeline-uf", "--simulado", "--ufs", "PI", "--limite", "4")
    _rodar(monkeypatch, "triar-escopo", "--fonte", "web", "--simulado", "--amostra", "6", "--estratificar")
    assert "itens triados" in capsys.readouterr().out
    assert _n(ambiente_cli, "SELECT COUNT(*) FROM triagem_escopo WHERE fonte='web' AND uf='PI'") >= 1


def test_cota_diaria_interrompe_a_execucao_sem_traceback_e_retoma_com_retomar(simulado, monkeypatch, capsys):
    from composicao import Fabrica
    monkeypatch.setattr(Fabrica, "triador", TriadorSimulado(cota_diaria_chamadas={2}), raising=False)
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--limite", "6", "--lote", "2")
    saida = capsys.readouterr().out
    ex = _banco(simulado).execute("SELECT run_id, status FROM execucoes WHERE comando LIKE 'triar-escopo%'").fetchone()
    assert ex["status"] == "interrompida"
    assert _n(simulado, "SELECT COUNT(*) FROM triagem_escopo") == 2
    assert "Cota diária do provedor" in saida and f"--retomar {ex['run_id']}" in saida
    assert "meia-noite no horário do Pacífico" in saida and "Traceback" not in saida
    monkeypatch.setattr(Fabrica, "triador", TriadorSimulado(), raising=False)
    _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--limite", "6", "--lote", "2",
           "--retomar", ex["run_id"])
    assert _n(simulado, "SELECT COUNT(*) FROM triagem_escopo") == 6
    assert _n(simulado, "SELECT status FROM execucoes WHERE comando LIKE 'triar-escopo%'") == "concluida"
