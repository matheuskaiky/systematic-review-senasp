"""Faixa do banco no painel: no banco de viés algorítmico, as dicas de comando das telas valem com --banco vies (D111)."""
import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from config import consultas as C, vocabulario as V
from painel.app import Contexto, criar_app

def _cli(tmp_path, banco, somente_leitura=False):
    ctx = Contexto(banco=banco, nome_banco="busca.db", somente_leitura=somente_leitura, pasta_backup=tmp_path / "b",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver",))
    return TestClient(criar_app(LeituraPainelSQLite(tmp_path / "nao.db"), lambda: None, BrutoLocal(tmp_path), ctx))


@pytest.mark.parametrize("banco, somente_leitura, detalhe", [
    ("vies", False, "busca.db · comandos: acrescente --banco vies"),
    ("vies", True, "busca.db · somente leitura · comandos: acrescente --banco vies"),
    ("real", False, "busca.db"), ("real", True, "busca.db · somente leitura"),
])
def test_faixa_do_banco(banco, somente_leitura, detalhe, tmp_path):
    html = _cli(tmp_path, banco, somente_leitura).get("/sobre").text
    assert f'<span class="banner-detalhe">{detalhe}</span>' in html



# ---------- escopo da busca de viés na página do artigo (só no banco vies) ----------
PERGUNTA_VIES = ("Este item serve ao estudo de viés algorítmico na inteligência artificial aplicada à segurança pública e à "
                 "investigação criminal?")
PERGUNTA_REAL = "Este artigo serve ao escopo da pesquisa: inteligência artificial na segurança pública brasileira?"


@pytest.mark.parametrize("banco, presentes, ausentes", [
    ("vies", [PERGUNTA_VIES, "de qualquer país e ano.", "de preferência com viés algorítmico, discriminação, ética, direitos ou governança."],
     [PERGUNTA_REAL, "e publicação a partir de 2022."]),
    ("real", [PERGUNTA_REAL, "e publicação a partir de 2022.", "se falta qualquer um (o motivo vai ao PRISMA)."],
     [PERGUNTA_VIES, "de qualquer país e ano."]),
])
def test_escopo_da_pagina_do_artigo_depende_do_banco(banco, presentes, ausentes, copiar_demo, tmp_path):
    import sqlite3
    demo, raw = copiar_demo("escopo_artigo")
    ctx = Contexto(banco=banco, nome_banco="demo.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",))
    artigo = sqlite3.connect(demo).execute("SELECT MIN(artigo_id) FROM artigos").fetchone()[0]
    html = TestClient(criar_app(LeituraPainelSQLite(demo), lambda: None, BrutoLocal(raw), ctx)).get(f"/literatura/artigos/{artigo}").text
    for t in presentes:
        assert t in html, t
    for t in ausentes:
        assert t not in html, t
