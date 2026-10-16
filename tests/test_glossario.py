"""Glossario "Sobre os dados": cobertura de todas as chaves, ancoras unicas e pagina funcionando (banco vazio e demonstracao)."""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401

from adaptadores.repositorio_sqlite import RepositorioSQLite  # noqa: E402
from config import vocabulario as V  # noqa: E402
from painel import glossario, rotulos  # noqa: E402


def _ids():
    return glossario.ids_de_ancoras()


@pytest.mark.parametrize("prefixo,chaves", [
    ("tecnologia", V.TECNOLOGIAS), ("status", V.STATUS), ("status", V.STATUS_FINAL_EXTRA), ("confianca", V.CONFIANCA),
    ("status", rotulos.STATUS), ("descarte", rotulos.MOTIVOS_DESCARTE), ("falha", rotulos.MOTIVOS_FALHA),
    ("download", rotulos.MOTIVOS_DOWNLOAD),
    ("origem", rotulos.ORIGEM_TEXTO), ("verificacao", rotulos.VERIFICACAO), ("confianca", rotulos.CONFIANCA),
    ("tecnologia", rotulos.TECNOLOGIAS)])
def test_toda_chave_tem_entrada_no_glossario(prefixo, chaves):
    faltam = [f"{prefixo}-{k}" for k in chaves if f"{prefixo}-{k}" not in _ids()]
    assert not faltam, faltam


def test_entradas_tem_texto_e_ancoras_sao_unicas_e_validas():
    ids = _ids()
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_-]*", i) for i in ids), [i for i in ids if not re.fullmatch(r"[a-z][a-z0-9_-]*", i)]
    for secao in glossario.SECOES:
        assert secao["titulo"] and secao["intro"] and secao["entradas"]
        for e in secao["entradas"]:
            assert e["termo"].strip() and len(e["texto"]) > 30, e["id"]


def test_termos_pedidos_estao_explicados():
    ids = set(_ids())
    for esperado in ("kpi-consultas-web", "kpi-urls-unicas", "kpi-paginas-com-texto", "kpi-classificacoes", "kpi-achados",
                     "kpi-evidencia-confere", "kpi-verificados", "kpi-ufs-confirmadas", "kpi-gasto-real", "evidencia-confere",
                     "evidencia-cita-tecnologia", "evidencia-cita-lgpd", "confianca-snippet", "fora-do-relatorio", "estadual",
                     "municipal", "triagem-titulo-resumo", "triagem-texto-completo", "prisma-identificacao", "prisma-inclusao",
                     "idempotencia", "config-hash", "execucao-concluida", "execucao-em_andamento", "execucao-interrompida",
                     "execucao-falhou", "triagem-incluir", "triagem-excluir", "triagem-pendente", "prisma-removidos-automatico", "diferenca-saldo",
                     "achado-por-varios-termos"):
        assert esperado in ids, esperado


class _Ancoras(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.sumario = set(), [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "nav" and a.get("aria-labelledby") == "sumario-titulo":
            self.sumario = True
        if tag == "a" and (a.get("href") or "").startswith("#"):
            self.links.append(a["href"][1:])


def _confere_pagina(cli):
    r = cli.get("/sobre")
    assert r.status_code == 200
    p = _Ancoras()
    p.feed(r.text)
    assert p.sumario, "falta o sumario"
    internos = [l for l in p.links if l != "conteudo"]
    assert len(internos) >= len(_ids()), "o sumario deve apontar para cada secao e cada termo"
    quebrados = [l for l in p.links if l not in p.ids]
    assert not quebrados, quebrados
    assert set(_ids()) <= p.ids
    assert "Sobre os dados" in r.text and "Evidência confere" in r.text
    return r.text


def test_pagina_sobre_responde_em_banco_vazio(tmp_path):
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    _confere_pagina(TestClient(_app(vazio, tmp_path / "raw", tmp_path, nome="simulado")[0]))


def test_pagina_sobre_responde_sem_banco(tmp_path):
    _confere_pagina(TestClient(_app(tmp_path / "naoexiste.db", tmp_path / "raw", tmp_path)[0]))
    assert not (tmp_path / "naoexiste.db").exists()


def test_pagina_sobre_na_demo_mostra_definicoes_oficiais_dos_status(demo, tmp_path):
    banco, raw = demo
    html = _confere_pagina(TestClient(_app(banco, raw, tmp_path)[0]))
    for definicao in V.STATUS.values():
        assert definicao.replace("&", "&amp;") in html or definicao in html
    assert 'aria-current="page"' in html and 'href="/sobre"' in html


def test_pagina_sobre_nao_tem_script_nem_estilo_inline(demo, tmp_path):
    banco, raw = demo
    html = TestClient(_app(banco, raw, tmp_path)[0]).get("/sobre").text
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "style=" not in html
