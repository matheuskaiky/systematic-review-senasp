"""Blocos da análise RG5 (painel/analises_blocos_cobertura.py): títulos que contam a conclusão com os números, avisos de cobertura
relativa, estados vazios, links e escape. Os dicionários de entrada vêm do leitor com dados montados a mão (sem banco)."""
import json

import pytest
from markupsafe import Markup

from adaptadores.leitura_termos_cobertura import LeituraTermosCobertura
from painel import analises_blocos_cobertura as B

CHAVES_BLOCO = {"id", "titulo", "subtitulo", "grafico", "texto", "selo", "aviso", "pares", "tabela", "link", "motivos"}   # `motivos` entrou na Etapa 2 do front-end


class Falso(LeituraTermosCobertura):
    """Leitor sem banco: devolve a carga montada a mão (as contas são as mesmas do leitor real)."""

    def __init__(self, itens, status, termos, creditos):
        ids = sorted(termos)
        self._base = {"termos": [termos[t] for t in ids], "meta": termos, "itens": {t: itens.get(t, {}) for t in ids}, "status": status,
                      "creditos": {t: creditos.get(t, 0) for t in ids}, "tem_triagem": bool(status)}

    def _carregar_termos(self):
        return self._base


def _t(i, idioma, grupo, query=None):
    return {"termo_id": i, "query": query or f'"termo {i}"', "idioma": idioma, "grupo": grupo, "pai": None}


def _leitor():
    termos = {"T01": _t("T01", "pt", "analise_preditiva"), "T02": _t("T02", "pt", "analise_preditiva"), "T03": _t("T03", "en", "video_monitoramento"),
              "T04": _t("T04", "en", "video_monitoramento")}
    itens = {"T01": {1: 1, 2: 2, 3: 3, 4: 4}, "T02": {3: 1, 5: 2, 9: 3}, "T03": {6: 1, 1: 2, 7: 3}}
    status = {1: "elegivel", 2: "elegivel", 3: "excluido", 4: "quarentena", 5: "elegivel", 6: "elegivel", 7: "excluido"}
    return Falso(itens, status, termos, {"T01": 2, "T02": 1, "T03": 1, "T04": 1})


@pytest.fixture(scope="module")
def entradas():
    L = _leitor()
    return {"ct": L.analise_cobertura_termos(), "rd": L.analise_redundancia_termos(1), "inc": L.analise_cobertura_incremental()}


WEB = {"tem_dados": True, "tem_triagem": True, "n_resultados": 5, "n_triados": 5, "n_elegiveis": 3, "n_quarentena": 1, "custo_total_usd": 0.02,
       "por_celula": [
           {"chave": "reconhecimento_facial|M01", "tecnologia": "reconhecimento_facial", "modelo_id": "M01", "perfil": "oficial", "n_consultas": 1,
            "n_linhas": 3, "n_resultados": 3, "n_triados": 3, "n_elegiveis": 2, "n_quarentena": 0, "n_excluidos": 1, "precisao": 0.6667,
            "ic_inf": 0.2, "ic_sup": 0.9, "custo_usd": 0.005, "elegiveis_por_usd": 400.0, "n_elegiveis_unicos": 0, "pct_elegiveis_de_outros": 100.0,
            "posicao_media_elegiveis": 1.5},
           {"chave": "reconhecimento_facial|M02", "tecnologia": "reconhecimento_facial", "modelo_id": "M02", "perfil": "geral", "n_consultas": 1,
            "n_linhas": 2, "n_resultados": 2, "n_triados": 2, "n_elegiveis": 2, "n_quarentena": 0, "n_excluidos": 0, "precisao": 1.0,
            "ic_inf": 0.34, "ic_sup": 1.0, "custo_usd": 0.005, "elegiveis_por_usd": 400.0, "n_elegiveis_unicos": 1, "pct_elegiveis_de_outros": 50.0,
            "posicao_media_elegiveis": 1.5}],
       "por_modelo": [
           {"modelo_id": "M01", "perfil": "oficial", "n_resultados": 4, "n_triados": 4, "n_elegiveis": 2, "n_elegiveis_unicos": 0, "precisao": 0.5},
           {"modelo_id": "M02", "perfil": "geral", "n_resultados": 3, "n_triados": 3, "n_elegiveis": 3, "n_elegiveis_unicos": 1, "precisao": 1.0}],
       "sobreposicao_modelos": [{"modelo_a": "M01", "modelo_b": "M02", "n_a": 2, "n_b": 3, "n_em_comum": 2, "n_uniao": 3, "jaccard": 0.6667,
                                 "so_a": 0, "so_b": 1, "jaccard_resultados": 0.4}],
       "incremental": {"universo": 3, "n_chaves": 2, "custo_total": 0.01, "criterio_desempate": "x",
                       "passos": [{"ordem": 1, "chave": "reconhecimento_facial|M01", "tecnologia": "reconhecimento_facial", "modelo_id": "M01",
                                   "n_elegiveis": 2, "ganho": 2, "acumulado": 2, "pct_acumulado": 66.7, "custo_usd": 0.005, "custo_acumulado_usd": 0.005},
                                  {"ordem": 2, "chave": "reconhecimento_facial|M02", "tecnologia": "reconhecimento_facial", "modelo_id": "M02",
                                   "n_elegiveis": 2, "ganho": 1, "acumulado": 3, "pct_acumulado": 100.0, "custo_usd": 0.005, "custo_acumulado_usd": 0.01}],
                       "marcos": [{"percentual": p, "atingido": True, "n_chaves": 2, "chave_final": "reconhecimento_facial|M02", "acumulado": 3,
                                   "creditos_acumulados": 0.01} for p in (80, 90, 95, 100)],
                       "dispensaveis": [], "com_unicos": [{"chave": "reconhecimento_facial|M02", "n_unicos": 1, "n_itens": 2}]}}


def _por_id(blocos):
    return {b["id"]: b for b in blocos}


def _texto_tudo(b):
    partes = [b["titulo"], b["subtitulo"], b["aviso"] or "", *b["texto"], *(f"{k} {v}" for k, v in b["pares"])]
    if b["tabela"]:
        partes += [str(c) for linha in b["tabela"]["linhas"] for c in linha] + list(b["tabela"]["cabecalho"])
    return " ".join(partes)


# ============================== formato comum ==============================
def test_todos_os_blocos_tem_o_formato_de_analises_blocos(entradas):
    blocos = (B.blocos_cobertura_termos(entradas["ct"], entradas["inc"]) + B.blocos_redundancia(entradas["rd"], entradas["inc"])
              + B.blocos_cobertura_web(WEB))
    assert len(blocos) == 4 + 4 + 3
    ids = [b["id"] for b in blocos]
    assert len(set(ids)) == len(ids)
    for b in blocos:
        assert set(b) == CHAVES_BLOCO
        assert b["titulo"] and isinstance(b["texto"], list) and isinstance(b["pares"], list)
        assert b["grafico"] is None or isinstance(b["grafico"], Markup)
        if b["tabela"]:
            assert all(len(l) == len(b["tabela"]["cabecalho"]) for l in b["tabela"]["linhas"])
        assert "<script" not in _texto_tudo(b).lower()


def test_blocos_de_cobertura_avisam_que_e_relativa_e_que_elegivel_e_do_modelo(entradas):
    for b in B.blocos_cobertura_termos(entradas["ct"], entradas["inc"]) + B.blocos_redundancia(entradas["rd"], entradas["inc"]):
        if b["grafico"] or b["tabela"]:
            assert "relativa" in b["aviso"] and "opinião do modelo" in b["aviso"], b["id"]
    for b in B.blocos_cobertura_web(WEB):
        assert "relativa" in b["aviso"] and "opinião do modelo" in b["aviso"], b["id"]


# ============================== rendimento por termo ==============================
def test_curva_titulo_conta_a_conclusao_com_os_numeros(entradas):
    b = _por_id(B.blocos_cobertura_termos(entradas["ct"], entradas["inc"]))["termos_curva"]
    assert b["titulo"] == "Com 3 dos 4 termos já se encontram 95% dos artigos elegíveis coletados (4 de 4)"
    assert "4 créditos dos 5 créditos" in " ".join(b["texto"])
    assert "svg" in b["grafico"] and "95%" in b["grafico"]                    # linha de corte e teto em 95%
    pares = dict(b["pares"])
    assert pares["Universo (artigos da base)"] == "4" and "3 termos" in pares["Menor prefixo que alcança 95%"]
    assert "Critério de desempate" in pares
    assert [l[0] for l in b["tabela"]["linhas"]] == [1, 2, 3, 4]


def test_curva_com_quarentena_menciona_a_base(entradas):
    inc = _leitor().analise_cobertura_incremental(incluir_quarentena=True)
    b = B.bloco_curva_cobertura(inc)
    assert "elegíveis ou em quarentena" in b["titulo"] and "(5 de 5)" in b["titulo"]


def test_precisao_titulo_barras_com_links_e_tabela(entradas):
    d = dict(entradas["ct"])
    d["por_termo"] = [dict(t, n_triados=max(t["n_triados"], 10)) for t in d["por_termo"]]       # para passar do mínimo de destaque
    b = _por_id(B.blocos_cobertura_termos(d))["termos_precisao"]
    assert "pelo menos 10 artigos" in b["titulo"]
    assert "/literatura/artigos?termo=T01" in b["grafico"]
    assert any("/literatura/artigos?termo=T01" in str(l[0]) for l in b["tabela"]["linhas"])
    assert b["tabela"]["cabecalho"][:2] == ["Termo", "Idioma"]
    assert any("T04" in t for t in b["texto"]) and any("1 crédito sem retorno" in t for t in b["texto"])    # T04 não devolveu nada


def test_precisao_sem_termo_firme_usa_titulo_geral(entradas):
    b = _por_id(B.blocos_cobertura_termos(entradas["ct"]))["termos_precisao"]
    assert b["titulo"] == "Precisão de cada termo: 57% dos artigos coletados são elegíveis"
    assert "intervalo de 95%" in " ".join(b["texto"])


def test_idioma_e_faixa(entradas):
    por = _por_id(B.blocos_cobertura_termos(entradas["ct"]))
    assert por["termos_idioma"]["titulo"] == "Artigos elegíveis achados só por termos em português: 2; só em inglês: 1; pelos dois: 1"
    assert "Só termos em português" in por["termos_idioma"]["grafico"]
    assert por["termos_faixa"]["titulo"] == "Parte de artigos elegíveis por posição e grupo de termo"       # só existe a faixa 1-10: sem comparação
    assert por["termos_faixa"]["grafico"] is not None


def test_sem_termos_devolve_um_bloco_vazio_com_aviso():
    blocos = B.blocos_cobertura_termos({})
    assert len(blocos) == 1 and blocos[0]["grafico"] is None and blocos[0]["aviso"]
    assert len(B.blocos_cobertura_termos(None)) == 1


def test_sem_triagem_os_blocos_explicam_o_que_rodar():
    L = Falso({"T01": {1: 1}}, {}, {"T01": _t("T01", "pt", "g")}, {"T01": 1})
    ct, inc = L.analise_cobertura_termos(), L.analise_cobertura_incremental()
    blocos = B.blocos_cobertura_termos(ct, inc)
    assert all(b["grafico"] is None for b in blocos)
    assert any("triar-escopo" in (b["aviso"] or "") for b in blocos)


# ============================== redundância ==============================
def test_jaccard_titulo_e_matriz(entradas):
    por = _por_id(B.blocos_redundancia(entradas["rd"], entradas["inc"]))
    b = por["termos_jaccard"]
    assert b["titulo"] == "Há termos redundantes: o par mais parecido (T01 e T03) tem 1 de 3 artigos elegíveis em comum (33%)"   # Jaccard 0,33 >= 0,3
    assert "an-calor" in b["grafico"] and b["tabela"]["linhas"][0][0] == "T01 e T03"
    assert dict(b["pares"])["Pares com algum artigo em comum"] == "1"


def test_jaccard_com_par_muito_parecido_diz_que_ha_redundancia():
    d = {"minimo_elegiveis": 5, "n_termos_fora": 0, "termos": ["T01", "T02"], "rotulos": {"T01": "a", "T02": "b"},
         "matriz": [[1.0, 0.9], [0.9, 1.0]], "pares": [{"termo_a": "T01", "termo_b": "T02", "n_a": 10, "n_b": 10, "n_em_comum": 9, "n_uniao": 11,
                                                         "jaccard": 0.9}], "contidos": []}
    assert B.bloco_jaccard(d)["titulo"].startswith("Há termos redundantes: o par mais parecido (T01 e T02) tem 9 de 11")


def test_jaccard_diagonal_nao_achata_as_cores(entradas):
    html = str(B.bloco_jaccard(entradas["rd"])["grafico"])
    assert "100%" not in html                                                  # a diagonal fica vazia, para a escala usar só os pares


def test_jaccard_poucos_termos_e_vazio():
    b = B.bloco_jaccard({"minimo_elegiveis": 5, "termos": ["T01"], "matriz": [[1.0]]})
    assert b["grafico"] is None and "5 artigos elegíveis" in b["aviso"]
    assert B.bloco_jaccard({})["grafico"] is None


def test_contidos_titulos():
    base = {"minimo_elegiveis": 5, "n_termos_fora": 0}
    sem = dict(base, contidos=[{"termo_id": "T23", "n_elegiveis": 6, "contido_em": "T09", "n_contido": 3, "pct_contido": 50.0, "pct_nos_demais": 66.7}])
    assert B.bloco_contidos(sem)["titulo"].startswith("Nenhum termo está quase todo dentro de outro: o maior é T23, com 50% dos elegíveis também em T09 (3 de 6)")
    com = dict(base, contidos=[{"termo_id": "T08", "n_elegiveis": 10, "contido_em": "T05", "n_contido": 9, "pct_contido": 90.0, "pct_nos_demais": 90.0}])
    assert B.bloco_contidos(com)["titulo"] == ("1 termo tem 80% ou mais dos seus artigos elegíveis dentro de outro termo (candidatos a dispensar)")
    assert B.bloco_contidos(dict(base, contidos=[]))["grafico"] is None


def test_dispensaveis_e_insubstituiveis(entradas):
    por = _por_id(B.blocos_redundancia(entradas["rd"], entradas["inc"]))
    d, u = por["termos_dispensaveis"], por["termos_unicos"]
    assert d["titulo"] == "1 dos 4 termos não acrescentaram nenhum artigo elegível ao que os outros já traziam (créditos gastos neles: 1)"
    assert "1 não devolveram resultado algum" in " ".join(d["texto"])
    assert u["titulo"].startswith("3 dos 4 termos trazem artigos elegíveis que mais nenhum termo traz (3 artigos)")
    assert "/literatura/artigos?termo=T01" in u["grafico"]
    assert len(B.blocos_redundancia(entradas["rd"], None)) == 2                  # sem cobertura, só jaccard e contidos


def test_redundancia_vazia_nao_falha():
    blocos = B.blocos_redundancia({}, {})
    assert len(blocos) == 4 and all(b["grafico"] is None for b in blocos)


# ============================== web ==============================
def test_web_blocos_titulos():
    por = _por_id(B.blocos_cobertura_web(WEB))
    assert por["web_precisao"]["titulo"] == "Na busca web, 100% dos resultados do modelo M02 são elegíveis, contra 50% do M01 (n = 3 e 4)"
    assert "Reconhecimento facial · M01" in por["web_precisao"]["grafico"]
    assert por["web_sobreposicao"]["titulo"].startswith("Os modelos M01 e M02 se repetem pouco: só 2 de 3 páginas elegíveis aparecem nos dois (67%)")
    assert por["web_curva"]["titulo"] == ("Com 2 dos 2 pares tecnologia × modelo já se encontram 95% das páginas elegíveis coletadas (3 de 3)")
    assert "Nenhum par é dispensável" in " ".join(por["web_curva"]["texto"])
    assert por["web_curva"]["tabela"]["linhas"][0][1] == "Reconhecimento facial"


def test_web_sem_dados_ou_sem_triagem():
    assert len(B.blocos_cobertura_web({})) == 1 and B.blocos_cobertura_web({})[0]["grafico"] is None
    b = B.blocos_cobertura_web(dict(WEB, tem_triagem=False))
    assert len(b) == 1 and "triar-escopo --fonte web" in b[0]["aviso"]


def test_web_com_um_modelo_so_nao_compara():
    d = dict(WEB, sobreposicao_modelos=[], por_modelo=WEB["por_modelo"][:1])
    por = _por_id(B.blocos_cobertura_web(d))
    assert por["web_sobreposicao"]["grafico"] is None
    assert por["web_precisao"]["titulo"].startswith("Na busca web, ")


# ============================== segurança ==============================
def test_texto_do_termo_e_escapado_no_grafico_e_na_tabela():
    perigo = '<img src=x onerror=alert(1)>"\''
    L = Falso({"T01": {1: 1, 2: 2}, "T02": {2: 1, 3: 2}}, {1: "elegivel", 2: "elegivel", 3: "excluido"},
              {"T01": _t("T01", "pt", "g", perigo), "T02": _t("T02", "en", "g", perigo)}, {"T01": 1, "T02": 1})
    ct, rd, inc = L.analise_cobertura_termos(), L.analise_redundancia_termos(1), L.analise_cobertura_incremental()
    for b in B.blocos_cobertura_termos(ct, inc) + B.blocos_redundancia(rd, inc):
        html = str(b["grafico"] or "") + " ".join(str(c) for l in (b["tabela"] or {"linhas": []})["linhas"] for c in l)
        assert "<img" not in html, b["id"]
    assert str(B._link_termo('T"><b>x')).count("<b>") == 0


def test_blocos_sao_serializaveis_nos_dados_de_entrada(entradas):
    json.dumps(entradas)
