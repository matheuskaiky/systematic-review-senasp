"""RC14: tecnologia `atendimento_virtual` (BO online, chatbot, WhatsApp, delegacia virtual) e a opcao `--tecnologias`.

Vocabulario, esquema do classificador, prompt v5, geracao das consultas com e sem a restricao, `estimar`, validacao da
linha de comando, execucao simulada e as telas do painel com a demonstracao (sempre offline)."""
import json
import re
import shutil
import sqlite3
import sys
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import main
import painel_demo
import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada, ExtratorSimulado
from aplicacao import busca_web, classificacao, download
from config import consultas as C, prompts as P, vocabulario as V
from dominio.esquemas import esquema_classificacao
from dominio.modelos import (Achado, ArquivoBaixado, ParametrosClassificacao, RegistroChamada, ResultadoClassificacao)
from dominio.servicos import gerar_consultas_web, palavras_chave_tecnologia
from infra.util import agora
from painel import rotulos
from painel.glossario import SECOES
from test_painel import _app

NOVA = "atendimento_virtual"


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def _banco(tmp_path):
    conn = sqlite3.connect(tmp_path / "data" / "simulado.db")
    conn.row_factory = sqlite3.Row
    return conn


# ---------- vocabulario e configuracao ----------
def test_vocabulario_tem_seis_tecnologias_e_a_nova_e_curta():
    assert list(V.TECNOLOGIAS) == ["reconhecimento_facial", "leitura_placas", "videomonitoramento_inteligente",
                                   "analise_preditiva", "outra_ia", NOVA]
    assert len(V.TECNOLOGIAS[NOVA]) <= 70          # o texto vai inteiro para a consulta de busca


def test_palavras_do_prefiltro_cobrem_o_atendimento_virtual():
    assert {"chatbot", "whatsapp", "atendimento virtual", "delegacia virtual", "boletim de ocorrencia"} <= set(C.POLITICA_DOWNLOAD.palavras_chave)


def test_rotulo_e_glossario_da_nova_tecnologia():
    assert rotulos.TECNOLOGIAS[NOVA] == "Atendimento virtual (BO online, chatbot, WhatsApp)"
    secao = next(s for s in SECOES if s["id"] == "tecnologias")
    assert len(secao["entradas"]) == 6 and "seis categorias" in secao["intro"]


def test_o_hash_da_configuracao_muda_com_a_nova_tecnologia(monkeypatch):
    antes = S.snapshot_config()
    monkeypatch.setattr(V, "TECNOLOGIAS", {k: v for k, v in V.TECNOLOGIAS.items() if k != NOVA})
    assert S.snapshot_config()["hash"] != antes["hash"]


# ---------- esquema e prompt ----------
def test_esquema_da_resposta_aceita_a_nova_tecnologia():
    e = esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA)
    assert NOVA in e["properties"]["achados"]["items"]["properties"]["tecnologia"]["enum"]


def test_enum_do_esquema_chega_a_todos_os_formatos_dos_adaptadores():
    from adaptadores.classificador_gemini import FORMATOS_ESQUEMA, _para_esquema_gemini
    from test_classificador_gemini import _gemini, _instr
    e = esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA)
    assert NOVA in _para_esquema_gemini(e)["properties"]["achados"]["items"]["properties"]["tecnologia"]["enum"]
    for formato in FORMATOS_ESQUEMA:                                   # responseSchema, responseJsonSchema e responseFormat
        g = _gemini(formato_esquema=formato)._corpo(_instr())["generationConfig"]
        assert NOVA in json.dumps(g), formato
    assert NOVA in json.dumps(e)                    # formato neutro: o openai_compat entrega o JSON Schema como esta
def test_prompt_v5_define_a_categoria_e_mantem_as_regras_do_v4():
    s = P.SYSTEM_PROMPT
    assert P.PROMPT_VERSAO == "v5"
    regra9 = s.split("9. Technology categories")[1].split("Status definitions")[0]
    assert "'atendimento_virtual'" in regra9 and "WhatsApp" in regra9 and "chatbot" in regra9 and "virtual police station" in regra9
    assert "'outra_ia'" in regra9 and "artificial intelligence or automation" in regra9
    assert "LITERAL excerpt" in s and "100% literal" in s                       # evidencia continua literal
    assert "'nome_solucao'" in s and "PROPER NAME" in s and "Do NOT add the name" in s   # regra 7 do v4 intacta


# ---------- geracao das consultas ----------
def test_consultas_so_da_nova_tecnologia_sao_subconjunto_identico_das_completas():
    ufs = {k: v for k, v in C.UFS.items() if k in ("PI", "TO", "CE")}
    todas = {c.id: c for c in gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, ufs)}
    so_nova = gerar_consultas_web(C.MODELOS_WEB, {NOVA: V.TECNOLOGIAS[NOVA]}, ufs)
    assert len(todas) == 3 * 6 * 2 and len(so_nova) == 3 * 1 * 2 == 6
    assert {c.tecnologia for c in so_nova} == {NOVA}
    assert all(todas[c.id] == c for c in so_nova)       # mesmo id, texto e perfil: a chave de idempotencia nao muda
    pi = next(c for c in so_nova if c.id == f"M01-PI-{NOVA}")
    assert pi.texto == f"{V.TECNOLOGIAS[NOVA]} Secretaria de Segurança Pública Piauí" and pi.perfil == "oficial"


# ---------- estimar e validacao da linha de comando ----------
def test_estimar_com_ufs_e_tecnologias_mostra_seis_consultas_e_tres_centavos(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "estimar", "--simulado", "--ufs", "PI", "TO", "CE", "--tecnologias", NOVA)
    saida = capsys.readouterr().out
    assert "Web queries: 6 | estimated cost: US$ 0.03" in saida
    assert "Pages to download (ceiling): 120" in saida          # 40 por UF x 3 UFs


def test_estimar_sem_opcoes_conta_as_324_consultas(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "estimar", "--simulado")
    assert "Web queries: 324 | estimated cost: US$ 1.62" in capsys.readouterr().out


def test_estimar_so_com_tecnologia_conta_as_27_ufs(ambiente_cli, monkeypatch, capsys):
    _rodar(monkeypatch, "estimar", "--simulado", "--tecnologias", NOVA, "outra_ia")
    assert "Web queries: 108 " in capsys.readouterr().out       # 27 x 2 x 2


@pytest.mark.parametrize("cmd", ["estimar", "busca-web", "pipeline-uf", "tudo"])
def test_tecnologia_invalida_lista_as_validas_e_nao_cria_execucao(cmd, ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, cmd, "--simulado", "--tecnologias", NOVA, "inexistente")
    msg = str(e.value)
    assert "inexistente" in msg and all(k in msg for k in V.TECNOLOGIAS)
    assert not (ambiente_cli / "data" / "simulado.db").exists()


def test_opcao_so_existe_nos_comandos_que_buscam_na_web(ambiente_cli, monkeypatch):
    for cmd in ("baixar", "classificar", "academico"):
        with pytest.raises(SystemExit) as e:
            _rodar(monkeypatch, cmd, "--simulado", "--tecnologias", NOVA)
        assert e.value.code == 2                                  # argparse: argumento desconhecido


# ---------- execucao simulada ----------
def test_busca_web_simulada_so_com_a_nova_tecnologia(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--tecnologias", NOVA)
    conn = _banco(ambiente_cli)
    assert [r[0] for r in conn.execute("SELECT alvo_id FROM chamadas WHERE etapa='busca_web' ORDER BY alvo_id")] == [f"M01-PI-{NOVA}", f"M02-PI-{NOVA}"]
    assert {r[0] for r in conn.execute("SELECT tecnologia FROM resultados_web")} == {NOVA}
    amb = json.loads(conn.execute("SELECT ambiente_json FROM execucoes").fetchone()[0])
    assert amb["argumentos"]["tecnologias"] == [NOVA]


def test_o_hash_e_a_chave_nao_dependem_da_opcao(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--tecnologias", NOVA)
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--tecnologias", NOVA, "outra_ia")
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI")
    conn = _banco(ambiente_cli)
    assert len({r[0] for r in conn.execute("SELECT config_hash FROM execucoes")}) == 1
    # a consulta da nova tecnologia tem a mesma chave nas tres execucoes
    chaves = [r[0] for r in conn.execute("SELECT chave_idempotencia FROM chamadas WHERE alvo_id=?", (f"M01-PI-{NOVA}",))]
    assert len(chaves) == 3 and len(set(chaves)) == 1


def test_sem_a_opcao_a_busca_simulada_usa_as_seis_tecnologias(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI")
    conn = _banco(ambiente_cli)
    assert conn.execute("SELECT COUNT(*) FROM chamadas WHERE etapa='busca_web'").fetchone()[0] == 12
    amb = json.loads(conn.execute("SELECT ambiente_json FROM execucoes").fetchone()[0])
    assert amb["argumentos"]["tecnologias"] is None


def test_pipeline_uf_simulado_com_a_opcao_roda_as_tres_etapas(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "pipeline-uf", "--simulado", "--ufs", "PI", "--tecnologias", NOVA, "--limite", "2")
    conn = _banco(ambiente_cli)
    assert [r[0] for r in conn.execute("SELECT status FROM execucoes")] == ["concluida"]
    assert conn.execute("SELECT COUNT(*) FROM chamadas WHERE etapa='busca_web'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chamadas WHERE etapa='classificacao'").fetchone()[0] >= 1


class _ClassificadorAtendimento:
    """Devolve um achado `atendimento_virtual` com trecho literal, e outro fora do vocabulario (descartado)."""
    nome = "simulado_atendimento"

    def classificar(self, entrada, instr):
        reg = RegistroChamada(provedor=self.nome, operacao="classificar", parametros={}, requisitado_em=agora(), http_status=200,
                              latencia_ms=1, raw=b"{}", tokens_entrada=1, tokens_saida=1, custo_usd=0.0)
        trecho = "registro de boletim de ocorrência online por WhatsApp"
        achados = [Achado(NOVA, "em_uso", "", False, trecho, "alta", nome_solucao="Delegacia Virtual Modelo"),
                   Achado("tecnologia_inexistente", "em_uso", "", False, trecho, "alta")]
        return ResultadoClassificacao(True, achados, True, "{}", reg)


class _FetcherAtendimento:
    nome = "simulado_atendimento"
    TEXTO = ("A Secretaria lançou o Delegacia Virtual Modelo, com registro de boletim de ocorrência online por WhatsApp e "
             "assistente de inteligência artificial. " * 3).encode()

    def baixar(self, url):
        reg = RegistroChamada(provedor=self.nome, operacao="baixar", parametros={}, requisitado_em=agora(), http_status=200,
                              latencia_ms=1, raw=self.TEXTO, raw_ext="html")
        return ArquivoBaixado(url, 200, "text/html", self.TEXTO, False, reg)


def test_etapas_com_a_nova_tecnologia_gravam_o_achado_e_descartam_o_invalido(tmp_path):
    repo, bruto = RepositorioSQLite(tmp_path / "s.db"), BrutoLocal(tmp_path / "raw")
    run = repo.iniciar_execucao("teste", "h", "{}", None)
    ufs = {"PI": C.UFS["PI"]}
    consultas = gerar_consultas_web(C.MODELOS_WEB, {NOVA: V.TECNOLOGIAS[NOVA]}, ufs)
    busca_web.executar(repo, bruto, BuscaSimulada(), run, consultas, C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, _FetcherAtendimento(), ExtratorSimulado(), run, run, replace(C.POLITICA_DOWNLOAD, palavras_chave=()), [], 0,
                      ufs={"PI"})
    params = ParametrosClassificacao(
        versao_prompt=P.PROMPT_VERSAO, sistema="s", usuario_template="{nome} {uf} {url} {titulo} {origem} {texto}",
        esquema=esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA),
        tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS),
        palavras_tecnologia={k: tuple(sorted(palavras_chave_tecnologia(v))) for k, v in V.TECNOLOGIAS.items()})
    classificacao.executar(repo, bruto, _ClassificadorAtendimento(), run, run, params, C.UFS, [], 0, ufs={"PI"})
    achados = repo.conn.execute("SELECT tecnologia, nome_solucao, evidencia_confere, evidencia_cita_tecnologia FROM achados").fetchall()
    assert achados and {tuple(a) for a in achados} == {(NOVA, "Delegacia Virtual Modelo", 1, 1)}
    assert repo.conn.execute("SELECT COUNT(*) FROM achados_descartados WHERE motivo='tecnologia_fora_do_vocabulario'").fetchone()[0] == len(achados)


# ---------- painel com a demonstracao ----------
@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("demo_atendimento")
    return painel_demo.construir(pasta), pasta / "raw_demo"


@pytest.fixture
def cliente(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path, somente_leitura=True)
    return TestClient(app), copia


def test_demo_tem_achados_da_nova_tecnologia_com_nome_ficticio(cliente):
    _, banco = cliente
    conn = sqlite3.connect(banco)
    n = conn.execute("SELECT COUNT(*) FROM achados WHERE tecnologia=?", (NOVA,)).fetchone()[0]
    ufs = conn.execute("SELECT COUNT(DISTINCT uf) FROM achados WHERE tecnologia=?", (NOVA,)).fetchone()[0]
    nomes = {r[0] for r in conn.execute("SELECT DISTINCT nome_solucao FROM achados WHERE tecnologia=? AND nome_solucao <> ''", (NOVA,))}
    assert n > 0 and ufs >= 2 and nomes == {"Delegacia Virtual Modelo"}


def test_adocao_mostra_a_sexta_tecnologia_na_matriz_no_mosaico_e_na_lgpd(cliente):
    cli, _ = cliente
    html = cli.get("/analises?secao=adocao").text
    rotulo = rotulos.TECNOLOGIAS[NOVA]
    assert html.count(rotulo.replace("&", "&amp;")) >= 3 or html.count("Atendimento virtual") >= 3
    assert f"tecnologia={NOVA}" in html                      # matriz e barras da LGPD ligam para /achados daquela tecnologia
    assert "Região e tecnologia" in html or "região" in html.lower()


def test_achados_filtra_pela_nova_tecnologia(cliente):
    cli, banco = cliente
    conn = sqlite3.connect(banco)
    total = conn.execute("SELECT COUNT(*) FROM v_achados_revisao WHERE tecnologia=?", (NOVA,)).fetchone()[0] \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='v_achados_revisao'").fetchone() else None
    r = cli.get(f"/achados?tecnologia={NOVA}")
    assert r.status_code == 200
    assert "Atendimento virtual" in r.text
    assert "Delegacia Virtual Modelo" in r.text or re.search(r"/achados/\d+", r.text)
    if total is not None:
        assert total > 0


def test_o_filtro_de_tecnologia_oferece_as_seis_opcoes(cliente):
    cli, _ = cliente
    html = cli.get("/achados").text
    assert all(f'value="{k}"' in html for k in V.TECNOLOGIAS)
