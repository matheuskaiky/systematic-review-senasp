"""Blocos de RE7 e RD12 (painel/analises_blocos_ruido.py): formato dos blocos, titulos com numeros, SVG bem formado, texto escapado,
links validos, avisos de "sugestao", ausencia de palavras de veredito, e entradas vazias."""
import json
import re
import xml.etree.ElementTree as ET

import pytest

from dominio import analise_termos as at
from dominio import refinamento_busca as refino
from painel import analises_blocos_ruido as br

HOSTIL = "<b>x</b>&"
CHAVES = {"id", "titulo", "subtitulo", "grafico", "texto", "selo", "aviso", "pares", "tabela", "link"}
PALAVRAS_DE_VEREDITO = ("recomendamos", "recomenda-se", "ótimo", "otimo", "excelente", "péssimo", "pessimo", "vale a pena", "deve usar")


def _it(i, status, titulo="", resumo="", uf="PI", **extra):
    return {"item_id": i, "uf": uf, "status": status, "valido": 1, "titulo": titulo, "resumo": resumo, **extra}


# ---------------------------------------------------------------- dados de entrada, montados com as funcoes de dominio
def _dados_prefiltro(hostil=False):
    itens, n = [], iter(range(1, 400))
    for k in range(20):
        itens.append(_it(next(n), "elegivel" if k < 16 else "excluido", "camera na viatura", "x", selecionada=1, motivo=None,
                         n_ocorrencias=5, melhor_posicao=1))
    for k in range(10):
        itens.append(_it(next(n), "elegivel" if k < 7 else "excluido", f"senasp {HOSTIL if hostil else 'painel'}" if k < 7 else "futebol",
                         "senasp" if k < 7 else "bola", selecionada=0, motivo="prefiltro_palavras", n_ocorrencias=1, melhor_posicao=4))
    for k in range(8):
        itens.append(_it(next(n), "elegivel" if k < 6 else "excluido", "sistema", "outro", uf="PI" if k < 5 else "AM", selecionada=0,
                         motivo="limite_por_uf", n_ocorrencias=1, melhor_posicao=7 + k))
    r = at.auditar_prefiltro(itens, ["camera"], limite_por_uf=20, min_suporte=3)
    r.update({"run_id": "R1", "comando": "pipeline-uf", "prefiltro": ["camera"], "n_selecao": len(itens), "n_sem_triagem": 0, "tem_dados": True})
    return r


def _dados_ruido(hostil=False):
    rotulo = HOSTIL if hostil else "reconhecimento facial"
    linhas = []
    for i in range(14):
        linhas.append({"item_id": i, "uf": "", "status": "elegivel" if i < 3 else "excluido", "valido": 1, "termos_consulta": json.dumps([rotulo]),
                       "categoria_motivo": None if i < 3 else "FORA_SEGURANCA_PUBLICA", "termo_gerador": rotulo, "sinal_negativo": "saude" if i >= 3 else None,
                       "dominio_tematico": None if i < 3 else "saude", "escopo_geografico": "brasil"})
    for i in range(20, 24):
        linhas.append({"item_id": i, "uf": "", "status": "elegivel", "valido": 1, "termos_consulta": json.dumps(['"policiamento preditivo"']),
                       "categoria_motivo": None, "termo_gerador": None, "sinal_negativo": None, "dominio_tematico": None, "escopo_geografico": "brasil"})
    corpus = [{"id": i, "uf": "", "titulo": "Saude e imagem" if i >= 3 and i < 14 else "Polícia", "resumo": "x", "incluido_humano": 0} for i in range(24)]
    fichas = refino.ficha_por_termo(linhas)
    for f in fichas:
        f["termo_id"], f["grupo"] = ("T01", "g") if f["termo"] == rotulo else ("T02", "g")
    aval = refino.avaliar_negativos(linhas, corpus, at.PALAVRAS_CENTRAIS_PADRAO)
    return {"n_itens": len(linhas), "n_invalidos": 0, "n_termos": len(fichas), "tem_dados": True, "tabela": at.tabela_por_termo(fichas),
            "fichas": fichas, "matriz": refino.matriz_ruido(linhas), "negativos": aval["negativos"], "negativos_por_termo": aval["por_termo"],
            "n_negativos": len(aval["negativos"]), "por_veredito": {v: sum(1 for n in aval["negativos"] if n["veredito"] == v) for v in refino.VEREDITOS},
            "n_termos_com_negativo_seguro": 1, "n_negativos_seguros_de_ganho": 1, "ganho_minimo_negativo": 3}


def _dados_simulacao(hostil=False):
    termos, sims = [], []
    for tid, query, idioma, base in (("T01", HOSTIL if hostil else '"reconhecimento facial"', "pt", "Polícia usa"),
                                     ("T40", '"machine learning"', "en", "police use"), ("T99", '"sem elegiveis"', "pt", "x")):
        itens = []
        for k in range(14):
            ok = k < (0 if tid == "T99" else 8)
            itens.append(_it(k, "elegivel" if ok else "excluido", f"{base} modelo" if k % 2 == 0 and ok else "modelo de saude", "resumo"))
        sim = at.simular_contextos(itens, at.candidatas_do_termo(itens, query, idioma))
        sims.append(sim)
        termos.append({"termo_id": tid, "termo": query, "idioma": idioma, "grupo": "g", "n": sim["n"], "n_elegivel": sim["n_elegivel"],
                       "n_quarentena": sim["n_quarentena"], "n_excluido": sim["n_excluido"], "elegivel": sim["elegivel"],
                       "amostra_pequena": sim["amostra_pequena"], "n_candidatas": len(sim["candidatas"]), "candidatas": sim["candidatas"][:20]})
    return {"tem_dados": True, "n_termos": 3, "n_pares": sum(t["n"] for t in termos), "limite_perda": at.LIMITE_PERDA_UTEIS,
            "limites": list(at.LIMITES_SIMULACAO), "aviso": at.AVISO_PREFILTRO, "termos": termos, "agregado": at.agregar_simulacoes(sims)}


FABRICAS = [("prefiltro", br.blocos_prefiltro, _dados_prefiltro), ("ruido", br.blocos_ruido_termos, _dados_ruido),
            ("simulacao", br.blocos_simulacao, _dados_simulacao)]


def _svgs(bloco):
    return re.findall(r"<svg.*?</svg>", str(bloco["grafico"] or ""), flags=re.S)


def _tudo(blocos):
    """Todo o texto de um conjunto de blocos, para as buscas por palavras."""
    partes = []
    for bl in blocos:
        partes += [bl["titulo"], bl["subtitulo"], bl["aviso"] or "", str(bl["grafico"] or ""), *bl["texto"],
                   *(f"{k} {v}" for k, v in bl["pares"])]
        if bl["tabela"]:
            partes += list(bl["tabela"]["cabecalho"]) + [str(c) for l in bl["tabela"]["linhas"] for c in l]
    return " ".join(partes)


# ---------------------------------------------------------------- formato comum
@pytest.mark.parametrize("nome,fb,dados", FABRICAS)
def test_blocos_tem_o_formato_do_painel_e_svg_bem_formado(nome, fb, dados):
    blocos = fb(dados())
    assert len(blocos) >= 2
    ids = [bl["id"] for bl in blocos]
    assert len(ids) == len(set(ids))
    for bl in blocos:
        assert set(bl) == CHAVES and bl["titulo"] and isinstance(bl["texto"], list) and isinstance(bl["pares"], list)
        for svg in _svgs(bl):
            ET.fromstring(svg)
        if bl["tabela"]:
            cab = bl["tabela"]["cabecalho"]
            assert all(len(l) == len(cab) for l in bl["tabela"]["linhas"]), bl["id"]
        for k, v in bl["pares"]:
            assert isinstance(k, str) and isinstance(v, str)
        if bl["link"]:
            assert bl["link"]["href"].startswith("/") and bl["link"]["rotulo"]


@pytest.mark.parametrize("nome,fb,dados", FABRICAS)
def test_blocos_sao_deterministicos_e_nao_alteram_a_entrada(nome, fb, dados):
    d = dados()
    copia = json.dumps(d, sort_keys=True, default=str)
    a, b = fb(d), fb(d)
    assert [x["titulo"] for x in a] == [x["titulo"] for x in b] and [str(x["grafico"]) for x in a] == [str(x["grafico"]) for x in b]
    assert json.dumps(d, sort_keys=True, default=str) == copia


@pytest.mark.parametrize("nome,fb,dados", FABRICAS)
def test_texto_hostil_sai_escapado_no_grafico(nome, fb, dados):
    blocos = fb(dados(hostil=True))
    for bl in blocos:
        for svg in _svgs(bl):
            ET.fromstring(svg)
        assert HOSTIL not in str(bl["grafico"] or "")
    if nome != "prefiltro":                       # no pre-filtro as palavras vem de um texto ja quebrado em palavras (sem marcas)
        assert any("&lt;b&gt;" in str(bl["grafico"] or "") for bl in blocos)


@pytest.mark.parametrize("nome,fb,dados", FABRICAS)
def test_entradas_vazias_ou_ausentes_devolvem_um_bloco_com_aviso(nome, fb, dados):
    for entrada in (None, {}, {"tem_dados": False}):
        blocos = fb(entrada)
        assert len(blocos) == 1 and blocos[0]["aviso"] and blocos[0]["grafico"] is None
        assert "ainda não há dados" in blocos[0]["titulo"].lower()


@pytest.mark.parametrize("nome,fb,dados", FABRICAS)
def test_nenhum_bloco_usa_palavras_de_veredito_e_todos_marcam_sugestao(nome, fb, dados):
    blocos = fb(dados())
    texto = _tudo(blocos).lower()
    assert not [p for p in PALAVRAS_DE_VEREDITO if p in texto]
    for bl in blocos:
        if bl["grafico"] or bl["tabela"]:
            assert bl["aviso"], bl["id"]
    assert any("sugestão para avaliação do pesquisador" in (bl["aviso"] or "").lower() or "confirma" in (bl["aviso"] or "").lower()
               for bl in blocos)


# ---------------------------------------------------------------- pre-filtro
def test_prefiltro_titulos_contam_os_numeros():
    d = _dados_prefiltro()
    blocos = {bl["id"]: bl for bl in br.blocos_prefiltro(d)}
    assert set(blocos) == {"prefiltro_grupos", "prefiltro_limite_uf", "prefiltro_palavras", "prefiltro_desempenho"}
    g = {x["chave"]: x for x in d["grupos"]}
    t = blocos["prefiltro_grupos"]["titulo"]
    assert f"{g['nao_selecionada']['n']} resultados" in t and f"{g['nao_selecionada']['n_elegivel']} (" in t and "80%" in t     # 16 de 20 selecionados
    assert "elegíveis" in t and "Wilson" in blocos["prefiltro_grupos"]["subtitulo"]
    lim = d["limite_por_uf"]
    assert str(lim["n_elegiveis_perdidos"]) in blocos["prefiltro_limite_uf"]["titulo"] and str(lim["limite"]) in blocos["prefiltro_limite_uf"]["titulo"]
    assert "senasp" in blocos["prefiltro_palavras"]["titulo"]


def test_prefiltro_memoria_de_calculo_traz_o_intervalo_e_o_run():
    d = _dados_prefiltro()
    grupos = br.blocos_prefiltro(d)[0]
    assert ("Coleta analisada", "R1") in grupos["pares"]
    linha = grupos["tabela"]["linhas"][0]
    assert linha[0] == "Selecionados para download" and "IC 95%" in linha[3] and "80,0%" in linha[3]
    assert [l[0] for l in grupos["tabela"]["linhas"]][:2] == ["Selecionados para download", "Não selecionados (todos os motivos)"]


def test_prefiltro_sem_palavras_candidatas_ou_sem_corte_nao_quebra():
    d = _dados_prefiltro()
    d["palavras_candidatas"] = []
    d["limite_por_uf"] = {**d["limite_por_uf"], "por_uf": [], "n_elegiveis_perdidos": 0, "curva": []}
    d["desempenho_prefiltro"] = [{"palavra": "camera", "n": 0, "n_elegivel": 0, "elegivel": at.proporcao(0, 0), "n_unica": 0}]
    blocos = {bl["id"]: bl for bl in br.blocos_prefiltro(d)}
    assert "Nenhuma palavra nova" in blocos["prefiltro_palavras"]["titulo"] and blocos["prefiltro_palavras"]["aviso"]
    assert "prefiltro_limite_uf" not in blocos and "prefiltro_desempenho" not in blocos


# ---------------------------------------------------------------- ruido por termo
def test_ruido_blocos_titulos_links_e_tabela_de_acao():
    d = _dados_ruido()
    blocos = {bl["id"]: bl for bl in br.blocos_ruido_termos(d)}
    assert set(blocos) == {"ruido_tabela", "ruido_mapa", "ruido_negativos"}
    t = blocos["ruido_tabela"]
    assert "menos da metade" in t["titulo"] and "reconhecimento facial" in t["titulo"] and "(21%)" in t["titulo"]
    svg = str(t["grafico"])
    assert "/literatura/artigos?termo=T01" in svg and "/literatura/artigos?termo=T02" in svg
    assert t["tabela"]["cabecalho"][-2:] == ["Ação sugerida", "Por quê"]
    assert any(l[5] in ("manter", "candidato a ganhar contexto", "revisar o termo", "observar", "amostra pequena") for l in t["tabela"]["linhas"])
    assert any("Como ler" in x for x in t["texto"])
    mapa = str(blocos["ruido_mapa"]["grafico"])
    assert "/triagem-escopo?fonte=artigo" in mapa and "dominio_tematico=saude" in mapa and "Saúde" in mapa


def test_ruido_negativos_titulo_usa_contagens_do_conjunto_todo():
    d = _dados_ruido()
    d["por_veredito"] = {"seguro": 300, "arriscado": 5, "perigoso": 20}
    d["n_negativos"], d["n_negativos_seguros_de_ganho"], d["n_termos_com_negativo_seguro"] = 325, 10, 7
    d["negativos"] = d["negativos"][:2]                                         # o recorte de exibicao nao muda o titulo
    t = {bl["id"]: bl for bl in br.blocos_ruido_termos(d)}["ruido_negativos"]["titulo"]
    assert t.startswith("300 de 325") and "só 10 delas tirariam 3 ou mais excluídos" in t and "7 termos" in t


def test_ruido_termo_sem_id_nao_gera_link_e_sem_negativos_omite_o_bloco():
    d = _dados_ruido()
    for l in d["tabela"]:
        l["termo_id"] = None
    d["negativos"] = []
    blocos = {bl["id"]: bl for bl in br.blocos_ruido_termos(d)}
    assert "/literatura/artigos" not in str(blocos["ruido_tabela"]["grafico"]) and "ruido_negativos" not in blocos


# ---------------------------------------------------------------- simulacao
def test_simulacao_blocos_titulos_e_estrutura():
    d = _dados_simulacao()
    blocos = {bl["id"]: bl for bl in br.blocos_simulacao(d)}
    assert set(blocos) == {"simulacao_resumo", "simulacao_mapa", "simulacao_termos", "simulacao_limites"}
    r = blocos["simulacao_resumo"]
    assert re.match(r"\d+ de \d+ contextos candidatos perderiam mais de 10% dos elegíveis", r["titulo"])
    assert "candidatas, não aprovadas" in " ".join(r["texto"]) and "Elegíveis perdidos" in r["tabela"]["cabecalho"]
    assert {l[1] for l in r["tabela"]["linhas"]} == {"pt", "en"}                  # os dois idiomas ficam separados
    assert "perde muitos úteis" in {l[-1] for l in r["tabela"]["linhas"]}
    assert re.match(r"Só \d+ de \d+ combinações", blocos["simulacao_mapa"]["titulo"]) and "10%" in blocos["simulacao_mapa"]["titulo"]
    assert "T99" not in str(blocos["simulacao_mapa"]["grafico"])                 # termo sem elegiveis fica fora do mapa
    assert any("nenhum resultado elegível" in x for x in blocos["simulacao_mapa"]["texto"])
    limites = blocos["simulacao_limites"]
    assert any("RD4" in x for x in limites["texto"]) and any("topo do ranking" in x for x in limites["texto"])


def test_simulacao_tabela_de_trade_off_mostra_a_perda_ao_lado_do_ruido():
    d = _dados_simulacao()
    t = {bl["id"]: bl for bl in br.blocos_simulacao(d)}["simulacao_termos"]["tabela"]
    assert t["cabecalho"].index("Ruído removido (IC 95%)") < t["cabecalho"].index("Elegíveis perdidos")
    por_termo = {}
    for l in t["linhas"]:
        por_termo.setdefault(l[0], []).append(l)
    assert all(len(v) <= br.MAX_LINHAS_TERMO for v in por_termo.values())
    assert not any(k.startswith("T99") for k in por_termo)                        # sem elegivel nao ha trade-off a mostrar
    for linhas in por_termo.values():                                             # ordenadas por ruido removido
        valores = [float(l[4].split("%")[0].replace(",", ".")) for l in linhas if l[4] != "—"]
        assert valores == sorted(valores, reverse=True)
    assert {l[2] for l in t["linhas"]} <= {"padrão", "automática"}


def test_simulacao_de_um_termo_so_tem_titulo_do_termo_e_link():
    d = _dados_simulacao()
    d["termos"] = d["termos"][:1]
    d["n_termos"] = 1
    bl = {x["id"]: x for x in br.blocos_simulacao(d)}["simulacao_termos"]
    assert bl["titulo"].startswith("Termo T01") and bl["link"]["href"] == "/literatura/artigos?termo=T01"


def test_simulacao_limite_de_perda_configuravel_muda_o_titulo():
    d = _dados_simulacao()
    d["limite_perda"] = 0.5
    assert "perderiam mais de 50%" in br.blocos_simulacao(d)[0]["titulo"]


def test_simulacao_sem_agregado_ou_sem_termos_com_elegiveis_omite_blocos():
    d = _dados_simulacao()
    d["agregado"] = []
    for t in d["termos"]:
        t["n_elegivel"] = 0
    ids = [bl["id"] for bl in br.blocos_simulacao(d)]
    assert ids == ["simulacao_limites"]
