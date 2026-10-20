"""Fonte de ícones v2: o recuo esquerdo de cada glifo é o início real do desenho, então o ícone fica centrado na sua caixa
(na v1 o recuo era 0 e o navegador deslocava cada ícone para a esquerda pela própria margem)."""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

TTFont = pytest.importorskip("fontTools.ttLib").TTFont

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "painel" / "static" / "fonts"
V1, V2 = FONTES / "observatorio-icones-v1.woff2", FONTES / "observatorio-icones-v2.woff2"
FERRAMENTA = RAIZ / "design" / "tools" / "corrigir_recuo_fonte.py"


def test_v2_tem_recuo_igual_ao_inicio_do_desenho_em_todo_glifo():
    fonte = TTFont(V2)
    glyf, hmtx = fonte["glyf"], fonte["hmtx"]
    errados = [n for n in fonte.getGlyphOrder() if glyf[n].numberOfContours and hmtx[n][1] != glyf[n].xMin]
    assert errados == [] and len(fonte.getGlyphOrder()) == 474


def test_v2_so_muda_o_recuo_e_a_versao():
    v1, v2 = TTFont(V1), TTFont(V2)
    assert v1.getGlyphOrder() == v2.getGlyphOrder() and v1.getBestCmap() == v2.getBestCmap()
    for n in v2.getGlyphOrder():
        assert v1["hmtx"][n][0] == v2["hmtx"][n][0] == 1024
        if v2["glyf"][n].numberOfContours:
            assert v1["glyf"][n].getCoordinates(v1["glyf"])[0] == v2["glyf"][n].getCoordinates(v2["glyf"])[0]
    assert v2["name"].getDebugName(1) == "Observatorio Icones"
    assert v2["name"].getDebugName(3) == "Observatorio Icones v2" and v2["name"].getDebugName(5) == "Version 2.0"


def test_ferramenta_refaz_a_v2_a_partir_da_v1_byte_a_byte(tmp_path):
    saida = tmp_path / "v2.woff2"
    r = subprocess.run([sys.executable, str(FERRAMENTA), str(V1), str(saida)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert hashlib.sha256(saida.read_bytes()).hexdigest() == hashlib.sha256(V2.read_bytes()).hexdigest()


def test_ferramenta_sem_argumentos_explica_o_uso():
    r = subprocess.run([sys.executable, str(FERRAMENTA)], capture_output=True, text=True)
    assert r.returncode == 1 and "Uso: python3 corrigir_recuo_fonte.py <entrada.woff2> <saida.woff2>" in r.stderr


def test_painel_carrega_a_v2():
    js = (RAIZ / "painel" / "static" / "painel.js").read_text(encoding="utf-8")
    assert '"/static/fonts/observatorio-icones-v2.woff2"' in js and "observatorio-icones-v1" not in js


def test_construtor_grava_o_recuo_do_desenho():
    fonte = (RAIZ / "design" / "tools" / "construir_fonte_icones.py").read_text(encoding="utf-8")
    assert 'fb.setupHorizontalMetrics({g: (UPM, getattr(fb.font["glyf"][g], "xMin", 0)) for g in ordem})' in fonte
    assert "(UPM, 0) for g in ordem" not in fonte
    assert '"uniqueFontIdentifier": "Observatorio Icones v2"' in fonte and '"version": "Version 2.0"' in fonte
