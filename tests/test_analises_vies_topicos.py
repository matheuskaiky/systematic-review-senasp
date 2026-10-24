"""Topicos do banco `vies` numa lista so: cada topico conta uma vez por obra no escopo, com as variantes juntadas, e o que
tambem e expressao das consultas leva uma marca, sem sair do grafico."""
import unicodedata

import pytest

from dominio import analises_vies as AV
from painel import analises_blocos_vies as bv

CONJ = {"LA1": "A", "LB1": "B"}
TEXTOS = {"LA1": "inteligência artificial viés algorítmico", "LB1": "reconhecimento facial ética"}


def _web(i, url=None):
    return {"referencia_id": i, "dominio": "e.org", "url_original": url or f"https://e.org/{i}", "titulo": f"T{i}",
            "data_pub": "2025-01-01", "consultas": "LA1", "conjuntos": "", "execucoes": "r"}


def _art(i, url=None):
    return {"artigo_id": i, "autores_publicacao": "A - R", "ano": 2024, "titulo": f"Artigo {i}",
            "link": url or f"https://s.org/{i}", "consultas": "LB1", "execucoes": "r"}


def _t(topicos, relevancia="alta"):
    return {"valido": 1, "status_bruto": relevancia, "tipo_fonte": "Artigo científico", "pais_escopo": "Brasil",
            "topicos": topicos, "eixo": None, "confianca": "alta", "recorte": "vies_algoritmico"}


def _itens(web=(), arts=(), tri=None):
    return AV.itens(list(web), list(arts), CONJ, tri or {})


def test_lista_unica_com_marca_de_termo_de_busca_e_variantes():
    nfd = unicodedata.normalize("NFD", "reconhecimento facial")
    lista = _itens([_web(i) for i in range(1, 5)], [], {
        ("referencia", 1): _t(f"Reconhecimento facial; {nfd}; Viés algorítmico; IA"),
        ("referencia", 2): _t("reconhecimento  facial; Vieses algorítmicos; ia"),
        ("referencia", 3): _t("Ética; Policiamento preditivo"),
        ("referencia", 4): _t("zeta", "fora_do_escopo")})
    assert AV.topicos(lista, TEXTOS.values()) == [
        ("IA", 2, False), ("Reconhecimento facial", 2, True), ("Viés algorítmico", 2, True),   # empate: pelo rotulo
        ("Policiamento preditivo", 1, False), ("Ética", 1, True)]          # a ordem de hoje compara o texto: É depois de P


def test_topico_conta_uma_vez_por_obra_mesmo_repetido_ou_em_dois_itens_da_obra():
    lista = _itens([_web(1, url="https://s.org/5")], [_art(5)], {
        ("referencia", 1): _t("Reconhecimento facial; reconhecimento facial"),
        ("artigo", 5): _t("Reconhecimento Facial; RECONHECIMENTO FACIAL")})
    assert AV.topicos(lista, TEXTOS.values()) == [("Reconhecimento Facial", 1, True)]   # a forma escrita da obra (o artigo)


@pytest.mark.parametrize("topico, termo", [
    ("Reconhecimento facial", True), ("reconhecimento facial", True), ("Facial", True), ("Reconhecimento", True),
    ("Reconhecimento facial em vídeo", False),       # expressao maior que a da consulta: nao e termo de busca
    ("Ética da IA", False), ("Inteligência", True), ("Intel", False),
])
def test_coincidencia_com_a_consulta_por_palavra_ou_expressao_inteira(topico, termo):
    lista = _itens([_web(1)], [], {("referencia", 1): _t(topico)})
    (_, _, busca), = AV.topicos(lista, TEXTOS.values())
    assert busca is termo


def test_sem_consultas_nenhum_topico_e_termo_de_busca():
    lista = _itens([_web(1)], [], {("referencia", 1): _t("Reconhecimento facial; IA")})
    assert [b for _, _, b in AV.topicos(lista)] == [False, False]


def test_lista_vazia_e_obras_fora_do_escopo():
    assert AV.topicos([], TEXTOS.values()) == []
    lista = _itens([_web(1)], [], {("referencia", 1): _t("IA", "fora_do_escopo")})
    assert AV.topicos(lista, TEXTOS.values()) == []


def test_ordem_pela_frequencia_e_empate_pelo_rotulo():
    tri = {("referencia", i): _t(t) for i, t in enumerate(["b; a; c", "b; c", "b", "zz"], 1)}
    lista = _itens([_web(i) for i in range(1, 5)], [], tri)
    assert [(t, n) for t, n, _ in AV.topicos(lista)] == [("B", 3), ("C", 2), ("A", 1), ("Zz", 1)]


# ---------- o bloco ----------
def _muitos(n_topicos, termo_no_topo=True):
    """Obras com topicos t00..tNN, o primeiro tambem termo de busca ("Reconhecimento facial") e o mais citado."""
    nomes = ["Reconhecimento facial" if (k == 0 and termo_no_topo) else f"Tópico {k:02d}" for k in range(n_topicos)]
    web = [_web(i) for i in range(1, n_topicos + 1)]
    tri = {("referencia", i): _t("; ".join(nomes[:max(1, n_topicos - i + 1)])) for i in range(1, n_topicos + 1)}
    return _itens(web, [], tri)


def test_grafico_tem_o_termo_de_busca_com_a_marca_e_o_limite_de_20():
    b = bv.bloco_topicos(_muitos(30), list(TEXTOS.values()))
    graf = str(b["grafico"])
    assert "Reconhecimento facial (termo de busca)" in graf
    assert graf.count("<rect") >= 20 and "Tópico 19" in graf and "Tópico 20" not in graf
    assert b["titulo"] == "Os tópicos mais citados são Reconhecimento facial e Tópico 01"


def test_tabela_tem_ate_50_com_a_coluna_de_coincidencia():
    b = bv.bloco_topicos(_muitos(60), list(TEXTOS.values()))
    assert b["tabela"]["cabecalho"] == ["Tópico", "Obras", "Também é termo de busca"]
    assert len(b["tabela"]["linhas"]) == 50
    assert b["tabela"]["linhas"][0] == ["Reconhecimento facial", "60", "sim"]
    assert b["tabela"]["linhas"][1][2] == "não"
    assert b["texto"][-1] == "60 tópicos distintos; a tabela mostra os 50 mais citados."


def test_textos_neutros_e_aviso_do_modelo():
    b = bv.bloco_topicos(_muitos(3), list(TEXTOS.values()))
    assert b["texto"][:3] == [
        "Os tópicos marcados com “(termo de busca)” também são expressões das consultas; contam como os demais.",
        "As contagens descrevem os rótulos que o modelo deu aos resultados recuperados, não a frequência dos temas na "
        "literatura nem a adoção das tecnologias.",
        "Variantes de singular e plural contam juntas (por exemplo, vieses algorítmicos com viés algorítmico)."]
    assert b["texto"][3] == "3 tópicos distintos; a tabela mostra os 3 mais citados."
    assert b["aviso"] == bv.AVISO_MODELO
    assert not any(p in (b["titulo"] + " ".join(b["texto"])) for p in ("Além das palavras", "só repetem", "redundante"))


def test_um_topico_so():
    lista = _itens([_web(1)], [], {("referencia", 1): _t("Reconhecimento facial")})
    b = bv.bloco_topicos(lista, list(TEXTOS.values()))
    assert b["titulo"] == "O tópico mais citado é Reconhecimento facial"
    assert b["texto"][3] == "1 tópico distinto; a tabela mostra o 1 mais citado."


def test_sem_topicos():
    assert bv.bloco_topicos([], list(TEXTOS.values()))["titulo"] == "Sem tópicos para mostrar"
