"""Uma etapa interrompida no meio da gravacao de um item (erro de banco, Ctrl+C) nao deixa a chamada paga como "feita" sem os
dados dela: o que o item gravou e desfeito, a chamada fica registrada como falha ("falha_ao_gravar: <Tipo>"), com o mesmo bruto,
e a retomada refaz o item. E o --limite vale para a execucao inteira: retomar nunca passa do numero pedido.
Tudo offline: adaptadores simulados e bancos temporarios."""
import hashlib
import sqlite3

import pytest

from adaptadores.repositorio_sqlite import RepositorioSQLite
from test_entrada_multi_run import _banco, _c, _rodar, _runs

# (etapa gravada em chamadas, metodo do repositorio que falha, tabela de dados ligada a chamada)
ETAPAS = {
    "busca-web": ("busca_web", "salvar_resultados_web", "resultados_web"),
    "academico": ("busca_academica", "salvar_artigos", "ocorrencias"),
    "baixar": ("download", "salvar_pagina", "paginas"),
    "classificar": ("classificacao", "salvar_classificacao", "classificacoes"),
    "triar-escopo": ("triagem_escopo", "salvar_triagem_escopo", "triagem_escopo"),
}


def _preparar(ambiente_cli, monkeypatch, comando):
    """Roda o que a etapa precisa antes e devolve os argumentos da etapa."""
    if comando == "busca-web":
        return ["busca-web", "--simulado", "--ufs", "PI", "--limite", "3"]
    if comando == "academico":
        return ["academico", "--simulado", "--termos", "T01", "T25", "T03", "--paginas", "1"]
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "3")
    a = _runs(ambiente_cli, "busca-web")[-1]
    if comando == "baixar":
        return ["baixar", "--simulado", "--ufs", "PI", "--de", a, "--limite", "3"]
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a)
    d = _runs(ambiente_cli, "baixar")[-1]
    if comando == "classificar":
        return ["classificar", "--simulado", "--ufs", "PI", "--de", d, "--limite", "3"]
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T01", "T25", "--paginas", "1")
    return ["triar-escopo", "--fonte", "artigos", "--simulado", "--amostra", "6", "--lote", "2"]


def _falhar_na_segunda(monkeypatch, metodo, excecao):
    original = getattr(RepositorioSQLite, metodo)
    vezes = []

    def falso(self, *a, **k):
        vezes.append(1)
        resultado = original(self, *a, **k)          # grava antes de falhar: o que o item escreveu precisa ser desfeito
        if len(vezes) == 2:
            raise excecao
        return resultado
    monkeypatch.setattr(RepositorioSQLite, metodo, falso)
    return lambda: monkeypatch.setattr(RepositorioSQLite, metodo, original)


@pytest.mark.parametrize("excecao,status", [(sqlite3.OperationalError("database is locked"), "falhou"),
                                            (KeyboardInterrupt(), "interrompida")])
@pytest.mark.parametrize("comando", list(ETAPAS))
def test_item_interrompido_na_gravacao_vira_falha_rastreada_e_a_retomada_refaz(ambiente_cli, monkeypatch, comando, excecao, status):
    etapa, metodo, tabela = ETAPAS[comando]
    argv = _preparar(ambiente_cli, monkeypatch, comando)
    restaurar = _falhar_na_segunda(monkeypatch, metodo, excecao)
    _rodar(monkeypatch, *argv)
    run = _runs(ambiente_cli, argv[0])[-1]
    db = _banco(ambiente_cli)
    assert db.execute("SELECT status FROM execucoes WHERE run_id=?", (run,)).fetchone()[0] == status
    chamadas = db.execute("SELECT chamada_id, chave_idempotencia, sucesso, erro, raw_path, raw_sha256 FROM chamadas "
                          "WHERE run_id=? AND etapa=? ORDER BY chamada_id", (run, etapa)).fetchall()
    assert [c["sucesso"] for c in chamadas] == [1, 0]
    falha = chamadas[1]
    assert falha["erro"] == f"falha_ao_gravar: {type(excecao).__name__}"
    assert db.execute(f"SELECT COUNT(*) FROM {tabela} WHERE chamada_id=?", (falha["chamada_id"],)).fetchone()[0] == 0
    assert db.execute(f"SELECT COUNT(*) FROM {tabela} WHERE chamada_id=?", (chamadas[0]["chamada_id"],)).fetchone()[0] > 0
    # o bruto da chamada que falhou continua no disco e confere com o hash gravado
    arquivos = [p for p in ambiente_cli.rglob("*") if p.is_file() and p.as_posix().endswith(falha["raw_path"])]
    assert falha["raw_path"] and len(arquivos) == 1
    assert hashlib.sha256(arquivos[0].read_bytes()).hexdigest() == falha["raw_sha256"]

    restaurar()
    _rodar(monkeypatch, argv[0], "--retomar", run, *argv[1:]) if argv[0] != "triar-escopo" else \
        _rodar(monkeypatch, "triar-escopo", "--retomar", run, "--fonte", "artigos", "--simulado", "--amostra", "6", "--lote", "2")
    db = _banco(ambiente_cli)
    assert db.execute("SELECT status FROM execucoes WHERE run_id=?", (run,)).fetchone()[0] == "concluida"
    refeita = db.execute("SELECT chamada_id FROM chamadas WHERE run_id=? AND chave_idempotencia=? AND sucesso=1",
                         (run, falha["chave_idempotencia"])).fetchall()
    assert len(refeita) == 1
    assert db.execute(f"SELECT COUNT(*) FROM {tabela} WHERE chamada_id=?", (refeita[0][0],)).fetchone()[0] > 0
    # toda chamada com sucesso da etapa tem os seus dados
    orfas = db.execute(f"SELECT COUNT(*) FROM chamadas c WHERE c.run_id=? AND c.etapa=? AND c.sucesso=1 "
                       f"AND NOT EXISTS (SELECT 1 FROM {tabela} t WHERE t.chamada_id=c.chamada_id)", (run, etapa)).fetchone()[0]
    assert orfas == 0


def test_falha_na_gravacao_guarda_o_erro_anterior_da_chamada(ambiente_cli, monkeypatch):
    """Uma chamada que ja tinha falhado (por exemplo, HTTP 500) e cuja gravacao tambem falha guarda os dois motivos."""
    from aplicacao.comum import item_gravado
    from adaptadores.bruto_local import BrutoLocal
    from dominio.modelos import RegistroChamada
    repo = RepositorioSQLite(ambiente_cli / "x.db")
    bruto = BrutoLocal(ambiente_cli / "raw")
    run = repo.iniciar_execucao("busca-web", "h", "{}", "c")
    reg = RegistroChamada(provedor="p", operacao="buscar", parametros={}, requisitado_em="2026-10-19T00:00:00+00:00",
                          http_status=500, erro="HTTP 500", raw=b"{}", raw_ext="json")
    with pytest.raises(RuntimeError):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            raise RuntimeError("x")
    linha = repo.conn.execute("SELECT erro, sucesso FROM chamadas WHERE run_id=?", (run,)).fetchall()
    assert [tuple(l) for l in linha] == [("falha_ao_gravar: RuntimeError | HTTP 500", 0)]


# ====================== --limite vale para a execucao inteira ======================
@pytest.mark.parametrize("comando", ["busca-web", "baixar", "classificar"])
def test_retomar_nao_passa_do_limite(ambiente_cli, monkeypatch, comando):
    etapa = ETAPAS[comando][0]
    argv = _preparar(ambiente_cli, monkeypatch, comando)
    argv = argv[:-1] + ["2"]                                         # --limite 2
    metodo = ETAPAS[comando][1]
    restaurar = _falhar_na_segunda(monkeypatch, metodo, KeyboardInterrupt())
    _rodar(monkeypatch, *argv)                                       # 1 item gravado, o 2o interrompido
    restaurar()
    run = _runs(ambiente_cli, argv[0])[-1]
    for _ in range(2):
        _rodar(monkeypatch, argv[0], "--retomar", run, *argv[1:])
    chaves = _c(ambiente_cli, "SELECT COUNT(DISTINCT chave_idempotencia) FROM chamadas WHERE run_id=? AND etapa=?", run, etapa)
    sucesso = _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas WHERE run_id=? AND etapa=? AND sucesso=1", run, etapa)
    assert chaves == 2 and sucesso == 2


@pytest.mark.parametrize("comando", ["busca-web", "baixar", "classificar"])
def test_limite_numa_execucao_sem_retomada_continua_igual(ambiente_cli, monkeypatch, comando):
    etapa = ETAPAS[comando][0]
    argv = _preparar(ambiente_cli, monkeypatch, comando)
    _rodar(monkeypatch, *argv)                                       # --limite 3
    run = _runs(ambiente_cli, argv[0])[-1]
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas WHERE run_id=? AND etapa=?", run, etapa) == 3


# ====================== o bloco do item: confirmacao, falha dupla e o que estava pendente ======================
class _Repo(RepositorioSQLite):
    """Repositorio real com pontos de falha controlados pelo teste."""
    falhar_confirmar = None          # None | "antes" (nao confirma e levanta) | "depois" (confirma e levanta)
    falhar_salvar_chamada_na = None  # numero da chamada a salvar_chamada que levanta

    def confirmar(self):
        modo, self.falhar_confirmar = self.falhar_confirmar, None
        if modo == "antes":
            raise sqlite3.OperationalError("database is locked")
        super().confirmar()
        if modo == "depois":
            raise KeyboardInterrupt()

    def salvar_chamada(self, **campos):
        self.n_salvar = getattr(self, "n_salvar", 0) + 1
        if self.n_salvar == self.falhar_salvar_chamada_na:
            raise sqlite3.OperationalError("database is locked")
        return super().salvar_chamada(**campos)


def _cenario(ambiente_cli):
    from adaptadores.bruto_local import BrutoLocal
    from dominio.modelos import RegistroChamada
    repo = _Repo(ambiente_cli / "y.db")
    bruto = BrutoLocal(ambiente_cli / "raw_y")
    run = repo.iniciar_execucao("busca-web", "h", "{}", "c")
    reg = RegistroChamada(provedor="p", operacao="buscar", parametros={}, requisitado_em="2026-10-19T00:00:00+00:00",
                          raw=b'{"ok": 1}', raw_ext="json")
    return repo, bruto, run, reg


def _linhas(repo, run):
    return [tuple(l) for l in repo.conn.execute("SELECT sucesso, erro FROM chamadas WHERE run_id=? ORDER BY chamada_id", (run,))]


def _metricas(repo, run):
    return {l[0]: l[1] for l in repo.conn.execute("SELECT chave, valor FROM metricas_run WHERE run_id=?", (run,))}


def test_falha_na_propria_confirmacao_do_item_desfaz_e_registra_a_falha(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    with pytest.raises(sqlite3.OperationalError):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            repo.registrar_metrica(run, "dado_do_item", 1)
            repo.falhar_confirmar = "antes"
    assert _linhas(repo, run) == [(0, "falha_ao_gravar: OperationalError")]
    assert "dado_do_item" not in _metricas(repo, run)


def test_interrupcao_depois_de_confirmar_nao_registra_a_chamada_duas_vezes(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    with pytest.raises(KeyboardInterrupt):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            repo.registrar_metrica(run, "dado_do_item", 1)
            repo.falhar_confirmar = "depois"
    assert _linhas(repo, run) == [(1, None)]
    assert _metricas(repo, run)["dado_do_item"] == 1


def test_falha_ao_registrar_a_propria_chamada_nao_deixa_sucesso(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    repo.falhar_salvar_chamada_na = 1
    with pytest.raises(sqlite3.OperationalError):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            pytest.fail("o bloco nao pode rodar sem a chamada registrada")
    assert _linhas(repo, run) == [(0, "falha_ao_gravar: OperationalError")]


def test_se_o_registro_da_falha_tambem_falha_a_excecao_original_sobe_e_nada_fica_como_sucesso(ambiente_cli, caplog):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    repo.falhar_salvar_chamada_na = 2               # a 1a grava a chamada; a 2a (o registro da falha) quebra
    with pytest.raises(RuntimeError):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            raise RuntimeError("erro do item")
    assert _linhas(repo, run) == []
    assert "Chamada sem registro" in caplog.text and "RuntimeError" in caplog.text and "OperationalError" in caplog.text


def test_o_que_estava_pendente_antes_do_item_nao_se_perde_quando_o_item_falha(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    repo.registrar_metrica(run, "antes_do_item", 7)  # pendente, sem confirmar
    with pytest.raises(RuntimeError):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            raise RuntimeError("x")
    assert _metricas(repo, run)["antes_do_item"] == 7


# ====================== o --limite conta itens com chamada, com ou sem sucesso ======================
def test_item_que_falha_no_provedor_conta_no_limite_e_e_repetido_sem_abrir_terceiro(ambiente_cli, monkeypatch):
    from adaptadores.simulados import BuscaSimulada
    original = BuscaSimulada.buscar
    primeira = []

    def buscar(self, consulta, filtros):
        resp = original(self, consulta, filtros)
        if not primeira or primeira[0] == consulta.id:
            primeira[:1] = [consulta.id]
            resp.chamada.erro = "HTTP 500"
        return resp
    monkeypatch.setattr(BuscaSimulada, "buscar", buscar)
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "2")
    run = _runs(ambiente_cli, "busca-web")[-1]
    _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI", "--limite", "2")
    por_chave = _banco(ambiente_cli).execute("SELECT chave_idempotencia, COUNT(*), SUM(sucesso) FROM chamadas WHERE run_id=? "
                                             "AND etapa='busca_web' GROUP BY chave_idempotencia ORDER BY MIN(chamada_id)", (run,)).fetchall()
    assert [(l[1], l[2]) for l in por_chave] == [(2, 0), (1, 1)]


# ====================== regras da linha de comando ======================
@pytest.mark.parametrize("valor", ["0", "-1", "abc", "1.5"])
def test_limite_precisa_ser_inteiro_positivo(ambiente_cli, monkeypatch, capsys, valor):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", valor)
    assert e.value.code == 2
    assert "argument --limite: precisa ser um inteiro maior ou igual a 1" in capsys.readouterr().err


def test_limite_da_triagem_tambem_precisa_ser_positivo(ambiente_cli, monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "triar-escopo", "--fonte", "artigos", "--simulado", "--limite", "0")
    assert e.value.code == 2 and "precisa ser um inteiro maior ou igual a 1" in capsys.readouterr().err


@pytest.mark.parametrize("comando", ["academico", "tudo"])
def test_limite_nao_vale_para_a_busca_academica(ambiente_cli, monkeypatch, comando):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, comando, "--simulado", "--ufs", "PI", "--limite", "2")
    assert str(e.value) == "--limite não vale para a busca acadêmica: limite a busca com --termos e --paginas."
    assert not (ambiente_cli / "data" / "simulado.db").exists() or _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas") == 0


def test_retomar_sem_o_limite_original_e_recusado_e_com_outro_valor_vale(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "1")
    run = _runs(ambiente_cli, "busca-web")[-1]
    antes = _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas")
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI")
    assert str(e.value) == ("Esta execução foi criada com --limite 1. Ao retomar, repita --limite 1: "
                            "sem ele a retomada não teria teto de chamadas.")
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas") == antes
    _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI", "--limite", "2")
    assert _c(ambiente_cli, "SELECT COUNT(DISTINCT chave_idempotencia) FROM chamadas WHERE run_id=?", run) == 2


def test_retomar_execucao_criada_sem_limite_continua_sem_exigir(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--tecnologias", "leitura_placas")
    run = _runs(ambiente_cli, "busca-web")[-1]
    _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI", "--tecnologias", "leitura_placas")
    assert _c(ambiente_cli, "SELECT status FROM execucoes WHERE run_id=?", run) == "concluida"


@pytest.mark.parametrize("comando", ["baixar", "classificar"])
def test_listar_com_retomar_e_recusado(ambiente_cli, monkeypatch, comando):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, comando, "--simulado", "--ufs", "PI", "--de", "x", "--retomar", "y", "--listar")
    assert str(e.value) == "--listar não vale com --retomar: a prévia não conhece as chamadas já feitas da execução."


# ====================== retrabalho R1: o trabalho entre a chamada paga e o seu registro ======================
@pytest.mark.parametrize("excecao,status", [(KeyboardInterrupt(), "interrompida"), (RuntimeError("pdf quebrado"), "falhou")])
def test_falha_na_extracao_depois_do_download_registra_a_chamada(ambiente_cli, monkeypatch, excecao, status):
    from adaptadores.simulados import ExtratorSimulado
    argv = _preparar(ambiente_cli, monkeypatch, "baixar")
    original, vezes = ExtratorSimulado.extrair, []

    def extrair(self, *a, **k):
        vezes.append(1)
        if len(vezes) == 2:
            raise excecao
        return original(self, *a, **k)
    monkeypatch.setattr(ExtratorSimulado, "extrair", extrair)
    _rodar(monkeypatch, *argv)
    run = _runs(ambiente_cli, "baixar")[-1]
    db = _banco(ambiente_cli)
    assert db.execute("SELECT status FROM execucoes WHERE run_id=?", (run,)).fetchone()[0] == status
    linhas = db.execute("SELECT sucesso, erro, raw_path FROM chamadas WHERE run_id=? AND etapa='download' ORDER BY chamada_id",
                        (run,)).fetchall()
    assert [(l[0], l[1]) for l in linhas] == [(1, None), (0, f"falha_ao_extrair: {type(excecao).__name__}")]
    assert linhas[1][2]                                              # o bruto do download continua apontado
    monkeypatch.setattr(ExtratorSimulado, "extrair", original)
    _rodar(monkeypatch, "baixar", "--retomar", run, *argv[1:])
    assert _c(ambiente_cli, "SELECT COUNT(DISTINCT chave_idempotencia) FROM chamadas WHERE run_id=? AND etapa='download'", run) == 3
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas WHERE run_id=? AND etapa='download' AND sucesso=1", run) == 3


def test_falha_na_validacao_da_triagem_registra_a_chamada(ambiente_cli, monkeypatch):
    import aplicacao.triagem_escopo as etapa
    argv = _preparar(ambiente_cli, monkeypatch, "triar-escopo")
    original, vezes = etapa.validar_resposta, []

    def validar(*a, **k):
        vezes.append(1)
        if len(vezes) == 2:
            raise RuntimeError("bug na validacao")
        return original(*a, **k)
    monkeypatch.setattr(etapa, "validar_resposta", validar)
    _rodar(monkeypatch, *argv)
    run = _runs(ambiente_cli, "triar-escopo")[-1]
    linhas = [tuple(l) for l in _banco(ambiente_cli).execute(
        "SELECT sucesso, erro FROM chamadas WHERE run_id=? AND etapa='triagem_escopo' ORDER BY chamada_id", (run,))]
    assert linhas == [(1, None), (0, "falha_ao_validar: RuntimeError")]
    assert _c(ambiente_cli, "SELECT status FROM execucoes WHERE run_id=?", run) == "falhou"


@pytest.mark.parametrize("gravado", ["{", "[]", '{"argumentos": "x"}', '"texto"', "", "   ", "null", '{"argumentos": null}'])
def test_argumentos_gravados_ilegiveis_exigem_limite_ao_retomar(ambiente_cli, monkeypatch, gravado):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "1")
    run = _runs(ambiente_cli, "busca-web")[-1]
    db = _banco(ambiente_cli)
    db.execute("UPDATE execucoes SET ambiente_json=? WHERE run_id=?", (gravado, run))
    db.commit()
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI")
    assert str(e.value) == f"Os argumentos gravados da execução {run} estão ilegíveis. Ao retomar, informe --limite."
    _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI", "--limite", "1")
    assert _c(ambiente_cli, "SELECT status FROM execucoes WHERE run_id=?", run) == "concluida"


def test_chaves_da_execucao_usam_indice(tmp_path):
    repo = RepositorioSQLite(tmp_path / "z.db")
    plano = " ".join(l[3] for l in repo.conn.execute(
        "EXPLAIN QUERY PLAN SELECT DISTINCT chave_idempotencia FROM chamadas WHERE run_id=? AND etapa=?", ("a", "b")))
    assert "USING COVERING INDEX ix_chamadas_run_etapa_chave" in plano and "TEMP B-TREE" not in plano


# ====================== retrabalho R2 ======================
@pytest.mark.parametrize("gravado", [None, "{}", '{"pausas": {}}'])
def test_execucao_sem_argumentos_gravados_retoma_sem_exigir_limite(ambiente_cli, monkeypatch, gravado):
    """Coluna NULL, ou um objeto sem a chave "argumentos" (execucao de antes do registro dos argumentos), conta como
    "sem registro", nao como ilegivel: a retomada segue sem exigir --limite."""
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "1")
    run = _runs(ambiente_cli, "busca-web")[-1]
    db = _banco(ambiente_cli)
    db.execute("UPDATE execucoes SET ambiente_json=? WHERE run_id=?", (gravado, run))
    db.commit()
    _rodar(monkeypatch, "busca-web", "--retomar", run, "--simulado", "--ufs", "PI", "--tecnologias", "leitura_placas")
    assert _c(ambiente_cli, "SELECT status FROM execucoes WHERE run_id=?", run) == "concluida"


def test_interrupcao_na_extracao_continua_interrupcao_mesmo_se_o_registro_da_falha_quebrar(ambiente_cli, monkeypatch):
    from adaptadores.simulados import ExtratorSimulado
    argv = _preparar(ambiente_cli, monkeypatch, "baixar")
    original_extrair, vezes = ExtratorSimulado.extrair, []

    def extrair(self, *a, **k):
        vezes.append(1)
        if len(vezes) == 2:
            raise KeyboardInterrupt()
        return original_extrair(self, *a, **k)
    original_salvar, salvas = RepositorioSQLite.salvar_chamada, []

    def salvar_chamada(self, **campos):
        if campos.get("etapa") == "download":
            salvas.append(1)
            if len(salvas) >= 2:                      # o 1o item grava; todo registro depois disso quebra
                raise sqlite3.OperationalError("database is locked")
        return original_salvar(self, **campos)
    monkeypatch.setattr(ExtratorSimulado, "extrair", extrair)
    monkeypatch.setattr(RepositorioSQLite, "salvar_chamada", salvar_chamada)
    _rodar(monkeypatch, *argv)
    run = _runs(ambiente_cli, "baixar")[-1]
    assert _c(ambiente_cli, "SELECT status FROM execucoes WHERE run_id=?", run) == "interrompida"
    linhas = [tuple(l) for l in _banco(ambiente_cli).execute(
        "SELECT sucesso FROM chamadas WHERE run_id=? AND etapa='download' ORDER BY chamada_id", (run,))]
    assert linhas == [(1,)]
    log = "".join(p.read_text(encoding="utf-8") for p in (ambiente_cli / "logs").glob("*.log"))
    assert "O registro da falha depois da chamada levantou OperationalError; segue a excecao original (KeyboardInterrupt)" in log



# ====================== a confirmacao do que estava pendente, no inicio do item ======================
def test_falha_ao_confirmar_o_pendente_antes_do_item_registra_a_chamada_como_falha(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    repo.registrar_metrica(run, "pendente_de_antes", 1)
    repo.falhar_confirmar = "antes"                                # a primeira confirmacao (a do pendente) falha
    corpo = []
    with pytest.raises(sqlite3.OperationalError):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            corpo.append(1)
    assert corpo == []                                              # o item nao chega a gravar nada
    assert _linhas(repo, run) == [(0, "falha_ao_gravar: OperationalError")]
    assert "pendente_de_antes" not in _metricas(repo, run)          # o pendente foi desfeito


def test_interrupcao_na_confirmacao_do_pendente_registra_a_chamada_e_mantem_o_pendente(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    repo.registrar_metrica(run, "pendente_de_antes", 1)
    repo.falhar_confirmar = "depois"                               # confirma o pendente e entao chega o Ctrl+C
    with pytest.raises(KeyboardInterrupt):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            pass
    assert _linhas(repo, run) == [(0, "falha_ao_gravar: KeyboardInterrupt")]
    assert _metricas(repo, run)["pendente_de_antes"] == 1


def test_falha_ao_confirmar_o_pendente_e_ao_registrar_a_falha_mantem_a_excecao_original(ambiente_cli):
    from aplicacao.comum import item_gravado
    repo, bruto, run, reg = _cenario(ambiente_cli)
    repo.falhar_confirmar = "antes"

    def segunda(**campos):                                         # o registro da falha tambem falha, com outro erro
        raise RuntimeError("segunda falha")
    repo.salvar_chamada = segunda
    with pytest.raises(sqlite3.OperationalError, match="^database is locked$"):
        with item_gravado(repo, bruto, run, "busca_web", "consulta_web", "Q1", "k1", reg, []):
            pass
    assert _linhas(repo, run) == []
