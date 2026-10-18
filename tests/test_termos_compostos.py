"""RD4 e RD5: termos compostos do piloto (desligados por padrao), filtro de idioma dos resultados (`lr`) e busca sem filtro de ano (D79; antes, ano inicial 2022).

Nenhum teste abre conexao: o adaptador real tem `chamar` substituido e a linha de comando roda com --simulado.
"""
import json
import sqlite3
import sys

import pytest

import main
import config.settings as S
from adaptadores import academico_serpapi_scholar as modulo
from adaptadores.academico_serpapi_scholar import AcademicoSerpApiScholar
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_academica
from config import consultas as C
from dominio.modelos import FiltrosAcademicos, RegistroChamada, Termo

CHAVE = "CHAVE-SERPAPI-FALSA-123456"
TERMO = Termo("T01", '"reconhecimento facial"', "pt", "reconhecimento_identificacao")

PT_A = '("segurança pública" OR polícia OR policiamento)'
EN_A = '((Brazil OR Brazilian) AND ("public security" OR police OR policing))'
# Lista aprovada pelo pesquisador (docs/GUIA_DO_PROJETO.md, secao 6.5): 6 termos-pai x 2 variantes.
ESPERADOS = [
    ("T47", "T15", '"aprendizado de máquina" AND ' + PT_A),
    ("T48", "T15", '"aprendizado de máquina" "segurança pública"'),
    ("T49", "T06", '"videoanálise" AND ' + PT_A),
    ("T50", "T06", '"videoanálise" "segurança pública"'),
    ("T51", "T01", '"reconhecimento facial" AND ' + PT_A),
    ("T52", "T01", '"reconhecimento facial" "segurança pública"'),
    ("T53", "T25", '"facial recognition" AND ' + EN_A),
    ("T54", "T25", '"facial recognition" Brazil police'),
    ("T55", "T40", '"machine learning" AND ' + EN_A),
    ("T56", "T40", '"machine learning" Brazil police'),
    ("T57", "T33", '"predictive policing" AND ' + EN_A),
    ("T58", "T33", '"predictive policing" Brazil police'),
]
# Ampliacao (RD4, 17/10/2026): variante B para os pais com total >= 100 ainda nao testados; A tambem nos genericos
# (total >= 5000), onde A e B trouxeram artigos diferentes no piloto. Sem T06 (o composto quase nao trouxe resultados).
EN_B = " Brazil police"
AMPLIACAO = [
    ("T59", "T03", '"biometria facial" "segurança pública"'),
    ("T60", "T04", '"reconhecimento de voz" "segurança pública"'),
    ("T61", "T07", '"câmeras inteligentes" "segurança pública"'),
    ("T62", "T16", '"análise de vínculos" "segurança pública"'),
    ("T63", "T26", '"real-time facial recognition"' + EN_B),
    ("T64", "T27", '"facial biometrics"' + EN_B),
    ("T65", "T28", '"voice recognition"' + EN_B),
    ("T66", "T28", '"voice recognition" AND ' + EN_A),
    ("T67", "T29", '"intelligent video surveillance"' + EN_B),
    ("T68", "T30", '"video analytics"' + EN_B),
    ("T69", "T31", '"smart cameras"' + EN_B),
    ("T70", "T31", '"smart cameras" AND ' + EN_A),
    ("T71", "T32", '"automatic license plate recognition"' + EN_B),
    ("T72", "T35", '"crime hotspot mapping"' + EN_B),
    ("T73", "T36", '"algorithmic risk assessment"' + EN_B),
    ("T74", "T41", '"link analysis"' + EN_B),
    ("T75", "T41", '"link analysis" AND ' + EN_A),
    ("T76", "T44", '"gunshot detection"' + EN_B),
]


# ====================== configuracao ======================
def test_termos_compostos_do_piloto():
    assert [(t.id, t.pai, t.query) for t in C.TERMOS_COMPOSTOS] == ESPERADOS + AMPLIACAO


def test_composto_herda_idioma_e_grupo_do_pai():
    pais = {t.id: t for t in C.TERMOS}
    for t in C.TERMOS_COMPOSTOS:
        assert (t.idioma, t.grupo) == (pais[t.pai].idioma, pais[t.pai].grupo)


def test_compostos_ficam_fora_da_lista_principal():
    """A lista principal continua com os 46 termos; nenhum id se repete entre as duas listas."""
    assert len(C.TERMOS) == 46 and not any(t.pai for t in C.TERMOS)
    ids = [t.id for t in C.TERMOS + C.TERMOS_COMPOSTOS]
    assert len(ids) == len(set(ids)) == 76


def test_sem_filtro_de_ano_e_sem_filtro_de_idioma_por_padrao():
    """D79: o recorte de ano sai da busca e passa para a analise."""
    assert C.FILTROS_ACADEMICOS == FiltrosAcademicos(ano_inicial=None, ano_final=None, por_pagina=20, idioma_resultados=None)


def test_filtro_de_idioma_e_opcional_no_dominio():
    assert FiltrosAcademicos().idioma_resultados is None
    assert FiltrosAcademicos(2022, None, 20, "lang_pt").idioma_resultados == "lang_pt"


def test_snapshot_da_configuracao_guarda_os_compostos_com_o_pai():
    termos = {t["id"]: t for t in json.loads(S.snapshot_config()["json"])["termos"]}
    assert termos["T47"]["pai"] == "T15" and termos["T47"]["query"] == ESPERADOS[0][2]
    assert "T01" in termos and len(termos) == 76


# ====================== adaptador ======================
class _Resp:
    ok, status_code, content = True, 200, b"{}"
    text = '{"organic_results": []}'


def _chamar(monkeypatch):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": _Resp(), "http_status": 200, "latencia_ms": 1, "tentativas": 1, "erro": None,
                "latencia_total_ms": 1, "historico": [], "corpo_erro": None}

    monkeypatch.setattr(modulo, "chamar", falso)
    return visto


def test_lr_vai_na_requisicao_e_no_registro_quando_definido(monkeypatch):
    visto = _chamar(monkeypatch)
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FiltrosAcademicos(2022, None, 20, "lang_pt"))
    esperado = {"engine": "google_scholar", "q": '"reconhecimento facial"', "hl": "pt", "num": 20, "start": 0,
                "as_ylo": 2022, "lr": "lang_pt"}
    assert pag.chamada.parametros == esperado
    assert visto["params"] == {**esperado, "api_key": CHAVE}


def test_sem_filtro_de_idioma_nao_envia_lr(monkeypatch):
    visto = _chamar(monkeypatch)
    AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 0, FiltrosAcademicos(2022, None, 20))
    assert "lr" not in visto["params"]


def test_sem_filtro_de_ano_nao_envia_as_ylo_nem_as_yhi(monkeypatch):
    visto = _chamar(monkeypatch)
    pag = AcademicoSerpApiScholar(CHAVE).buscar_pagina(TERMO, 20, C.FILTROS_ACADEMICOS)
    esperado = {"engine": "google_scholar", "q": '"reconhecimento facial"', "hl": "pt", "num": 20, "start": 20}
    assert pag.chamada.parametros == esperado
    assert visto["params"] == {**esperado, "api_key": CHAVE}


def test_lr_confirmado_sem_todo_no_adaptador():
    """`lr=lang_pt` confirmado em chamada real (17/10/2026, execucao 20261017_192037_9b607d): o TODO sai e fica o registro."""
    linhas = open(modulo.__file__, encoding="utf-8").read().splitlines()
    assert not any("TODO(verificar)" in l and "lr" in l for l in linhas)
    assert any("lr" in l and "20261017_192037_9b607d" in l for l in linhas)


# ====================== linha de comando ======================
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


@pytest.fixture
def capturado(monkeypatch):
    """Guarda os termos e os filtros que a linha de comando entrega a etapa, sem trocar o comportamento dela."""
    visto = {}
    original = busca_academica.executar

    def espiao(repo, bruto, academico, run_id, termos, filtros, *resto, **kw):
        visto.update(termos=[t.id for t in termos], filtros=filtros)
        return original(repo, bruto, academico, run_id, termos, filtros, *resto, **kw)

    monkeypatch.setattr(busca_academica, "executar", espiao)
    return visto


def test_sem_termos_roda_so_a_lista_principal(ambiente_cli, monkeypatch, capturado):
    _rodar(monkeypatch, "academico", "--simulado", "--paginas", "1")
    assert capturado["termos"] == [t.id for t in C.TERMOS]
    assert capturado["filtros"] == C.FILTROS_ACADEMICOS


def test_composto_roda_quando_citado_em_termos(ambiente_cli, monkeypatch, capturado):
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T47", "T54", "T01", "--paginas", "1")
    assert sorted(capturado["termos"]) == ["T01", "T47", "T54"]
    conn = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    assert sorted(r[0] for r in conn.execute("SELECT alvo_id FROM chamadas WHERE etapa='busca_academica'")) == \
        ["T01", "T47", "T54"]


def test_flag_idioma_resultados_so_troca_o_lr(ambiente_cli, monkeypatch, capturado):
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T15", "--paginas", "1",
           "--idioma-resultados", "lang_pt")
    f = capturado["filtros"]
    assert f.idioma_resultados == "lang_pt"
    assert (f.ano_inicial, f.ano_final, f.por_pagina) == (C.FILTROS_ACADEMICOS.ano_inicial,
                                                          C.FILTROS_ACADEMICOS.ano_final, C.FILTROS_ACADEMICOS.por_pagina)


def test_v_termos_mostra_o_composto_com_o_pai(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T47", "--paginas", "1")
    conn = sqlite3.connect(ambiente_cli / "data" / "simulado.db")
    assert conn.execute("SELECT pai, query FROM v_termos WHERE termo_id='T47'").fetchone() == ("T15", ESPERADOS[0][2])


# ====================== registro de buscas (anexo do protocolo) ======================
def test_registro_de_buscas_mostra_o_filtro_de_idioma(tmp_path):
    repo = RepositorioSQLite(tmp_path / "r.db")
    run_id = repo.iniciar_execucao("teste", "h", "{}", None)
    for i, extra in enumerate(({"lr": "lang_pt"}, {})):
        reg = RegistroChamada(provedor="serpapi_scholar", operacao="buscar_pagina",
                              parametros={"engine": "google_scholar", "q": '"x"', "hl": "pt", "num": 20, "start": 0,
                                          "as_ylo": 2022, **extra},
                              requisitado_em="2026-10-17T10:00:00+00:00", http_status=200, latencia_ms=1)
        repo.salvar_chamada(run_id=run_id, etapa="busca_academica", alvo_tipo="termo", alvo_id=f"T{i}",
                            chave=f"k{i}", registro=reg, raw_path="x.json", raw_sha256="y" * 64, pagina=1)
    repo.confirmar()
    filtros = dict(repo.conn.execute("SELECT termo_id, filtros FROM v_registro_buscas").fetchall())
    assert filtros["T0"] == "idioma=pt; por_pagina=20; ano_inicial=2022; ano_final=; idioma_resultados=lang_pt"
    assert filtros["T1"] == "idioma=pt; por_pagina=20; ano_inicial=2022; ano_final=; idioma_resultados="
