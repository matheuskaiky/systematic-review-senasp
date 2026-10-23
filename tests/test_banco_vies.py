"""Banco separado da busca de viés algorítmico (D111): com --banco vies, os dados, os brutos, as contas, as cópias, as
saídas e os registros ficam em data/vies, outputs/vies e logs/vies, com os mesmos nomes de arquivo; sem a opção, tudo
continua como antes. Nenhum teste abre conexão: `chamar` é substituído."""
import json
import logging
import pathlib
import sqlite3
import sys
import types

import pytest

import config.settings as S
import main
from adaptadores import academico_serpapi_scholar as modulo_scholar, busca_perplexity as modulo_perplexity
from composicao import banco_escolhido
from config import consultas as C

SINT = pathlib.Path(__file__).parent / "fixtures" / "sintetico"
IDS_LITERATURA = [f"LA{n}" for n in range(1, 6)] + [f"LB{n}" for n in range(1, 6)] + [f"LC{n}" for n in range(1, 6)]
SENHA = "senha-de-teste-123"


class _Resp:
    ok = True

    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()

    def json(self):
        return json.loads(self.text)


def _chamar(modulo, monkeypatch, arquivo):
    texto = (SINT / arquivo).read_text(encoding="utf-8")
    pedidos = []

    def falso(metodo, url, **kw):
        if "q" in kw.get("params", {}) or "json_body" in kw:      # o saldo da SerpApi nao e uma busca
            pedidos.append(kw)
        return {"resp": _Resp(texto), "http_status": 200, "latencia_ms": 4, "tentativas": 1, "erro": None,
                "latencia_total_ms": 4, "historico": [], "corpo_erro": None}
    monkeypatch.setattr(modulo, "chamar", falso)
    return pedidos


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def ambiente(ambiente_cli, monkeypatch):
    """Tudo no tmp: o banco real (data/busca.db) também, para provar que o vies não o toca."""
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", ambiente_cli / "data" / "busca.db")
    monkeypatch.setitem(S.OPCOES["local"], "raiz", ambiente_cli / "data" / "raw")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "CHAVE-FALSA-PPLX")
    monkeypatch.setenv("SERPAPI_KEY", "CHAVE-FALSA-SERP")
    return ambiente_cli


def _cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    main.main()


def _caminhos():
    return (S.DATA_DIR, S.OUT_DIR, S.LOG_DIR, S.OPCOES["sqlite"]["caminho"], S.OPCOES["local"]["raiz"], S.OPCOES["excel"]["pasta"])


# ---------- as pastas do banco ----------
def test_banco_vies_usa_pastas_proprias_e_devolve_as_de_antes(ambiente):
    antes = _caminhos()
    d, o, lg = S.DATA_DIR, S.OUT_DIR, S.LOG_DIR
    with banco_escolhido("vies"):
        assert _caminhos() == (d / "vies", o / "vies", lg / "vies", d / "vies" / "busca.db", d / "vies" / "raw", o / "vies")
    assert _caminhos() == antes


def test_pastas_voltam_mesmo_quando_o_comando_falha(ambiente):
    antes = _caminhos()
    with pytest.raises(RuntimeError):
        with banco_escolhido("vies"):
            raise RuntimeError("falha no comando")
    assert _caminhos() == antes


def test_banco_real_nao_muda_nada(ambiente):
    antes = _caminhos()
    with banco_escolhido("real"):
        assert _caminhos() == antes
    assert _caminhos() == antes


@pytest.mark.parametrize("args, mensagem", [
    (("outro",), "Banco desconhecido: outro. Use um destes: real, vies."),
    (("vies", True, False), "--banco vies não vale com --simulado nem com --demo."),
    (("vies", False, True), "--banco vies não vale com --simulado nem com --demo."),
])
def test_combinacoes_recusadas(args, mensagem, ambiente):
    antes = _caminhos()
    with pytest.raises(SystemExit) as e:
        with banco_escolhido(*args):
            pass
    assert str(e.value) == mensagem and _caminhos() == antes


def test_vies_vale_no_postgres_e_o_banco_em_uso_volta_ao_real(ambiente, monkeypatch):
    from composicao import banco_em_uso
    monkeypatch.setenv("DB_BACKEND", "postgres")
    assert banco_em_uso() == "real"
    with banco_escolhido("vies"):                                  # no PostgreSQL, o vies e um esquema proprio
        assert banco_em_uso() == "vies"
    assert banco_em_uso() == "real"
    with banco_escolhido("real"):
        assert banco_em_uso() == "real"


# ---------- registro da configuração e termos ----------
def test_registro_do_banco_real_nao_muda():
    a, b = S.snapshot_config(), S.snapshot_config("real")
    assert a == b and "banco" not in json.loads(a["json"])
    assert [t["id"] for t in json.loads(a["json"])["termos"]] == [t.id for t in C.TERMOS + C.TERMOS_COMPOSTOS]


def test_registro_do_vies_tem_os_termos_dos_conjuntos():
    d = json.loads(S.snapshot_config("vies")["json"])
    assert d["banco"] == "vies" and [t["id"] for t in d["termos"]] == IDS_LITERATURA
    assert S.snapshot_config("vies")["hash"] != S.snapshot_config()["hash"]


def test_termos_de_cada_banco():
    assert [t.id for t in S.termos_do_banco("vies")] == IDS_LITERATURA
    assert S.termos_do_banco("real") == C.TERMOS + C.TERMOS_COMPOSTOS
    with pytest.raises(ValueError, match="^banco desconhecido: 'outro'$"):
        S.termos_do_banco("outro")
    assert [t.id for t in main._termos_padrao("real")] == [t.id for t in C.TERMOS]
    assert [t.id for t in main._termos_padrao("vies")] == IDS_LITERATURA
    assert list(main._mapas_termos_triagem("vies")["artigo"]) == IDS_LITERATURA
    assert list(main._mapas_termos_triagem()["artigo"]) == [t.id for t in C.TERMOS + C.TERMOS_COMPOSTOS]


@pytest.mark.parametrize("ns, sufixo", [
    ({"banco": "vies"}, " --banco vies"), ({"banco": "real"}, ""), ({}, ""),
])
def test_comandos_sugeridos_levam_o_banco(ns, sufixo):
    assert main._sufixo_banco(types.SimpleNamespace(**ns)) == sufixo


# ---------- linha de comando ----------
SEM_BANCO = {"pg-demo", "painel-demo"}


def _subcomandos(monkeypatch):
    import argparse
    capturado = {}

    def para(self, *a, **k):
        capturado["p"] = self
        raise SystemExit(0)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", para)
    monkeypatch.setattr(sys, "argv", ["main.py"])
    with pytest.raises(SystemExit):
        main.main()
    sub = next(a for a in capturado["p"]._actions if a.__class__.__name__ == "_SubParsersAction")
    return sub.choices


def test_todo_comando_que_abre_o_banco_aceita_banco_e_o_padrao_e_o_real(monkeypatch):
    for nome, s in _subcomandos(monkeypatch).items():
        acoes = [a for a in s._actions if "--banco" in a.option_strings]
        assert bool(acoes) == (nome not in SEM_BANCO), nome
        if acoes:
            assert (acoes[0].default, tuple(acoes[0].choices)) == ("real", ("real", "vies")), nome


@pytest.mark.parametrize("args", [("exportar", "--banco", "outro"), ("painel-demo", "--banco", "vies"),
                                  ("pg-demo", "--banco", "vies"), ("pg-migrar", "--banco", "outro"),
                                  ("pg-importar", "--banco", "outro")])
def test_banco_invalido_ou_em_comando_sem_banco_e_recusado(args, ambiente, monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, *args)
    assert e.value.code == 2
    erro = capsys.readouterr().err
    assert ("invalid choice: 'outro'" in erro) if "outro" in args else ("unrecognized arguments: --banco vies" in erro)


def test_busca_de_literatura_no_vies_grava_so_nas_pastas_do_vies(ambiente, monkeypatch, silencio):
    _chamar(modulo_perplexity, monkeypatch, "perplexity_search_sintetico.json")
    _cli(monkeypatch, "buscar-literatura", "--banco", "vies", "--conjunto", "A", "--limite", "1")
    vies = sqlite3.connect(ambiente / "data" / "vies" / "busca.db")
    assert vies.execute("SELECT comando, status FROM execucoes").fetchall() == [("buscar-literatura", "concluida")]
    run_id = vies.execute("SELECT run_id FROM execucoes").fetchone()[0]
    assert vies.execute("SELECT alvo_id FROM chamadas").fetchall() == [("LA1",)]
    assert vies.execute("SELECT COUNT(*) FROM ocorrencias_web").fetchone()[0] > 0
    assert json.loads(vies.execute("SELECT config_json FROM execucoes").fetchone()[0])["banco"] == "vies"
    assert list((ambiente / "data" / "vies" / "raw").rglob("*.json"))
    assert (ambiente / "logs" / "vies" / f"{run_id}.log").exists()
    assert not (ambiente / "data" / "busca.db").exists() and not (ambiente / "data" / "raw").exists()


def test_busca_de_literatura_no_banco_real_e_recusada_e_simulada_vale(ambiente, monkeypatch, silencio):
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "buscar-literatura", "--conjunto", "A", "--limite", "1")
    assert str(e.value) == "buscar-literatura grava no banco vies: use --banco vies (ou --simulado para testar sem custo)."
    assert not (ambiente / "data" / "busca.db").exists()
    _cli(monkeypatch, "buscar-literatura", "--conjunto", "A", "--limite", "1", "--simulado")
    assert (ambiente / "data" / "simulado.db").exists()


def test_scholar_no_vies_usa_os_termos_dos_conjuntos_e_v_termos_os_mostra(ambiente, monkeypatch, silencio):
    pedidos = _chamar(modulo_scholar, monkeypatch, "serpapi_scholar_sintetico.json")
    _cli(monkeypatch, "academico", "--banco", "vies", "--termos", "LA1", "LB2", "T01", "--paginas", "1")
    vies = sqlite3.connect(ambiente / "data" / "vies" / "busca.db")
    assert sorted(a for (a,) in vies.execute("SELECT alvo_id FROM chamadas")) == ["LA1", "LB2"]   # T01 não é termo do vies
    assert [p["params"]["q"] for p in pedidos] == [C.CONJUNTOS_LITERATURA["A"][0].query, C.CONJUNTOS_LITERATURA["B"][1].query]
    assert [t for (t,) in vies.execute("SELECT termo_id FROM v_termos ORDER BY termo_id")] == sorted(IDS_LITERATURA)
    assert not (ambiente / "data" / "busca.db").exists()


def test_scholar_no_vies_sem_termos_roda_os_dez_do_conjunto(ambiente, monkeypatch, silencio):
    pedidos = _chamar(modulo_scholar, monkeypatch, "serpapi_scholar_sintetico.json")
    _cli(monkeypatch, "academico", "--banco", "vies", "--paginas", "1")
    assert [p["params"]["q"] for p in pedidos] == [t.query for t in S.termos_do_banco("vies")]


def _uma_busca_no_vies(monkeypatch):
    _chamar(modulo_perplexity, monkeypatch, "perplexity_search_sintetico.json")
    _cli(monkeypatch, "buscar-literatura", "--banco", "vies", "--conjunto", "A", "--limite", "1")


def test_saidas_do_vies_ficam_em_outputs_vies(ambiente, monkeypatch, silencio, capsys):
    _uma_busca_no_vies(monkeypatch)
    capsys.readouterr()
    _cli(monkeypatch, "exportar", "--banco", "vies")
    gerado = pathlib.Path(capsys.readouterr().out.split("Generated:")[-1].strip())
    assert gerado.parent == ambiente / "outputs" / "vies" and gerado.name.startswith("resultado_") and gerado.exists()
    _cli(monkeypatch, "manual-modelo", "--banco", "vies")
    modelo = ambiente / "outputs" / "vies" / "buscas_manuais_modelo.csv"
    assert modelo.exists() and "LA1" in modelo.read_text(encoding="utf-8") and "T01" not in modelo.read_text(encoding="utf-8")
    assert not (ambiente / "outputs" / "buscas_manuais_modelo.csv").exists()
    _cli(monkeypatch, "painel-relatorio", "--banco", "vies")
    relatorios = list((ambiente / "outputs" / "vies").glob("relatorio_*.html"))
    assert len(relatorios) == 1 and 'class="banner banner-vies"' in relatorios[0].read_text(encoding="utf-8")


def test_enviar_recusa_o_vies(ambiente, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "enviar", "--banco", "vies", "--run", "20261021_000000_abcdef")
    assert str(e.value) == "enviar não vale com --banco vies: a nuvem tem só o banco da pesquisa."


def test_usuario_admin_do_vies_cria_as_contas_do_vies(ambiente, monkeypatch, capsys):
    it = iter([SENHA, SENHA])
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(it))
    _cli(monkeypatch, "usuario-admin", "--banco", "vies", "--login", "chefe", "--nome", "Chefe")
    assert capsys.readouterr().out.strip().endswith("Administrador criado: chefe")
    assert (ambiente / "data" / "vies" / "contas.db").exists() and not (ambiente / "data" / "contas.db").exists()


def test_painel_do_vies_abre_o_banco_do_vies_com_o_rotulo_proprio(ambiente, monkeypatch, silencio):
    import uvicorn
    import painel.app as painel_app
    from fastapi.testclient import TestClient
    _uma_busca_no_vies(monkeypatch)
    capturado = {}
    criar_original = painel_app.criar_app
    monkeypatch.setattr(painel_app, "criar_app", lambda leitura, fab, bruto, contexto, **kw:
                        capturado.update(contexto=contexto, bruto=bruto) or criar_original(leitura, fab, bruto, contexto, **kw))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: capturado.update(app=app))
    _cli(monkeypatch, "painel", "--banco", "vies", "--somente-leitura")
    ctx = capturado["contexto"]
    assert (ctx.banco, ctx.nome_banco) == ("vies", "busca.db")
    assert sorted(ctx.termos) == sorted(IDS_LITERATURA)
    assert ctx.comando_criar_banco == "python main.py buscar-literatura --conjunto A --limite 5 --banco vies"
    assert capturado["bruto"].raiz == ambiente / "data" / "vies" / "raw"
    html = TestClient(capturado["app"], base_url="http://127.0.0.1").get("/").text
    assert 'class="banner banner-vies"' in html and "BANCO VIÉS ALGORÍTMICO" in html
    assert _caminhos()[0] == ambiente / "data"                       # ao fim do comando as pastas voltaram


def test_sem_banco_tudo_continua_no_de_sempre(ambiente, monkeypatch, silencio, capsys):
    _cli(monkeypatch, "manual-modelo")
    assert (ambiente / "outputs" / "buscas_manuais_modelo.csv").exists()
    assert not (ambiente / "outputs" / "vies").exists() and not (ambiente / "data" / "vies").exists()


def test_pastas_voltam_tambem_com_ctrl_c(ambiente):
    antes = _caminhos()
    with pytest.raises(KeyboardInterrupt):
        with banco_escolhido("vies"):
            raise KeyboardInterrupt
    assert _caminhos() == antes
    with banco_escolhido("vies"):                                 # e o banco pode ser escolhido de novo depois
        pass


@pytest.mark.parametrize("fora, dentro", [("vies", "real"), ("real", "vies"), ("real", "real")])
def test_nenhum_banco_dentro_de_outro(fora, dentro, ambiente):
    antes = _caminhos()
    with banco_escolhido(fora):
        de_fora = _caminhos()
        with pytest.raises(SystemExit) as e:
            with banco_escolhido(dentro):
                pass
        assert str(e.value) == f"O banco {fora} já está escolhido neste comando: não dá para escolher outro dentro dele."
        assert _caminhos() == de_fora
    assert _caminhos() == antes
    with banco_escolhido(dentro):                                 # depois de sair, escolher de novo vale
        pass


def test_banco_desconhecido_e_recusado_antes_de_olhar_o_de_fora(ambiente):
    with banco_escolhido("real"):
        with pytest.raises(SystemExit) as e:
            with banco_escolhido("outro"):
                pass
    assert str(e.value) == "Banco desconhecido: outro. Use um destes: real, vies."


def test_nao_se_escolhe_um_banco_dentro_de_outro(ambiente):
    antes = _caminhos()
    with banco_escolhido("vies"):
        with pytest.raises(SystemExit) as e:
            with banco_escolhido("vies"):
                pass
        assert str(e.value) == "O banco vies já está escolhido neste comando: não dá para escolher outro dentro dele."
        assert _caminhos()[0] == antes[0] / "vies"                # o de fora continua valendo
    assert _caminhos() == antes


def test_estimar_no_vies_conta_os_quinze_termos(ambiente, monkeypatch, capsys):
    _cli(monkeypatch, "estimar", "--banco", "vies")
    assert f"Academic terms: 15 | pages per term (max.): {C.MAX_PAGINAS_ACADEMICO}" in capsys.readouterr().out


def test_registro_do_vies_tem_os_caminhos_do_vies(ambiente, monkeypatch, silencio):
    _uma_busca_no_vies(monkeypatch)
    cfg = json.loads(sqlite3.connect(ambiente / "data" / "vies" / "busca.db").execute("SELECT config_json FROM execucoes").fetchone()[0])
    assert cfg["opcoes"]["sqlite"]["caminho"] == str(ambiente / "data" / "vies" / "busca.db")
    assert cfg["opcoes"]["local"]["raiz"] == str(ambiente / "data" / "vies" / "raw")


def test_leia_me_da_rotulagem_no_vies_manda_importar_no_vies(ambiente, monkeypatch, silencio):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from aplicacao import rotulagem as RT
    repo = RepositorioSQLite(ambiente / "r.db")
    try:
        plano = RT.planejar(repo, pasta="outputs/vies/rotulagem", sufixo_banco=" --banco vies")
        sem = RT.planejar(repo, pasta="outputs/rotulagem")
    finally:
        repo.fechar()
    linhas = [l for l in RT.leiame_pasta(plano) if "python main.py" in l]
    assert linhas and all("--banco vies" in l for l in linhas)
    assert not [l for l in RT.leiame_pasta(sem) if "--banco" in l]


def test_entrada_do_painel_do_vies_ensina_a_criar_o_admin_do_vies(ambiente, tmp_path):
    from fastapi.testclient import TestClient
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.contas_sqlite import ContasSQLite
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from config import vocabulario as V
    from painel.app import Contexto, criar_app
    banco = tmp_path / "busca.db"
    RepositorioSQLite(banco).fechar()
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    for nome, esperado in (("vies", "--nome &lt;nome&gt; --banco vies</code>"), ("real", "--nome &lt;nome&gt;</code>")):
        ctx = Contexto(banco=nome, nome_banco="busca.db", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                       status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                       autenticacao=True)
        html = TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx,
                                    contas=contas)).get("/entrar").text
        assert esperado in html, nome


def test_painel_do_vies_com_login_usa_as_contas_e_as_copias_do_vies(ambiente, monkeypatch, silencio):
    import uvicorn
    import painel.app as painel_app
    _uma_busca_no_vies(monkeypatch)
    capturado = {}
    criar_original = painel_app.criar_app
    monkeypatch.setattr(painel_app, "criar_app", lambda leitura, fab, bruto, contexto, **kw:
                        capturado.update(contexto=contexto, contas=kw.get("contas")) or criar_original(leitura, fab, bruto, contexto, **kw))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: capturado.update(app=app))
    _cli(monkeypatch, "painel", "--banco", "vies")
    assert capturado["contexto"].pasta_backup == ambiente / "data" / "vies" / "backups"
    assert (ambiente / "data" / "vies" / "contas.db").exists() and not (ambiente / "data" / "contas.db").exists()


def test_metodologia_do_vies_avisa_que_e_outro_banco():
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from test_metodologia_texto import _fatos
    from painel.metodologia_texto import gerar_metodologia, para_texto
    frase = "Estes dados são do banco da busca de viés algorítmico na segurança pública, separado do banco da pesquisa"
    for banco, tem in (("vies", True), ("real", False), ("demo", False)):
        f = _fatos()
        f["banco"] = banco
        r = " | ".join(para_texto(x) for x in gerar_metodologia(f)["ressalvas"])
        assert (frase in r) == tem, banco
