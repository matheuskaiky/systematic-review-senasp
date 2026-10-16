"""Regras puras de dominio/solucoes.py: normalizacao, casamento de palavra inteira, trecho com destaque no texto original, variantes e
situacao de uma solucao conhecida."""
import random

import pytest

from dominio import solucoes as s
from dominio.solucoes import (SolucaoConhecida, casar, explicacao_da_situacao, normalizar, rotulo_da_situacao, situacao_da_solucao,
                              trecho_ao_redor, trechos_ao_redor, variantes_da_solucao)


# ---------- normalizacao ----------
@pytest.mark.parametrize("texto,esperado", [
    ("BO Fácil", " bo facil "), ("  bo-fácil!! ", " bo facil "), ("SÃO  PAULO", " sao paulo "), ("Ação/Reação", " acao reacao "),
    ("é (e com acento solto)", " e e com acento solto "), ("ß", " ss "), ("½", " 1 2 "), ("A_B", " a b "), ("", " "), (None, " "),
    ("!!!", " "), ("   ", " "), ("a b\tc\nd", " a b c d "), ("日本語 IA", " 日本語 ia ")])
def test_normalizar(texto, esperado):
    assert normalizar(texto) == esperado


def test_normalizar_nao_quebra_com_unicode_estranho():
    for t in ("\ud800", "a\ud800b", "\U0001f600 emoji", "\u0000\u0001", "x" * 10 + "‮" + "y", "ﬁnal"):
        assert normalizar(t).startswith(" ") and normalizar(t).endswith(" ")
    assert normalizar("ﬁnal") == " final "          # ligadura fi
    assert trecho_ao_redor("a\ud800b foi aqui", "foi") == ("a\ud800b ", "foi", " aqui")


# ---------- casamento ----------
@pytest.mark.parametrize("texto,termo,casa", [
    ("O SPiA foi lançado", "spia", True), ("o spia", "SPIA", True), ("(SPiA)", "spia", True), ("SPiA-PI", "spia", True),
    ("espionagem digital", "spia", False), ("espiando", "spia", False), ("spiano", "spia", False), ("aspia", "spia", False), ("spias", "spia", False),
    ("BO Fácil do Piauí", "bo facil", True), ("o BO-Fácil", "BO Fácil", True), ("BOFácil", "BO Fácil", False), ("bo", "bo facil", False),
    ("Sistema de Policiamento por Inteligência Artificial", "sistema de policiamento por inteligencia artificial", True),
    ("sistema  de   policiamento por inteligência", "sistema de policiamento por inteligência artificial", False),
    ("qualquer coisa", "", False), ("qualquer coisa", "!!!", False)])
def test_casar_palavra_ou_frase_inteira(texto, termo, casa):
    assert casar(normalizar(texto), normalizar(termo)) is casa


def test_casar_por_trecho_quando_o_termo_perde_os_espacos_das_pontas():
    assert casar(normalizar("espiando"), normalizar("spia").strip())
    assert not casar(normalizar("espiando"), normalizar("spia"))
    assert casar(normalizar("a casa"), "a ca")


# ---------- trecho com destaque no texto original ----------
def test_trecho_devolve_o_texto_original_com_acento_e_caixa():
    texto = "Com o BO Fácil, o cidadão registra a ocorrência pelo WhatsApp."
    antes, achado, depois = trecho_ao_redor(texto, "bo facil")
    assert (antes, achado, depois) == ("Com o ", "BO Fácil", ", o cidadão registra a ocorrência pelo WhatsApp.")
    assert antes + achado + depois == texto


def test_trecho_achado_com_pontuacao_diferente_e_destacado_por_inteiro():
    texto = "serviço bo-fácil (novo)"
    assert trecho_ao_redor(texto, "BO Fácil")[1] == "bo-fácil"
    assert trecho_ao_redor("SPiA!", "spia")[1] == "SPiA"


def test_trecho_respeita_a_largura_e_marca_o_corte():
    texto = "a" * 50 + " BO Fácil " + "b" * 50
    antes, achado, depois = trecho_ao_redor(texto, "bo facil", largura=10)
    assert achado == "BO Fácil" and antes.startswith("…") and depois.endswith("…")
    assert len(antes) <= 11 + 1 and len(depois) <= 11 + 1
    # texto curto: sem reticencias
    assert trecho_ao_redor("o SPiA", "spia", largura=50) == ("o ", "SPiA", "")


def test_trecho_junta_quebras_de_linha_nas_laterais_para_exibir():
    antes, achado, depois = trecho_ao_redor("linha um\n\n  linha dois SPiA\nfim", "spia")
    assert achado == "SPiA" and "\n" not in antes + depois


def test_trecho_nao_acha_e_termo_vazio():
    assert trecho_ao_redor("nada aqui", "spia") is None
    assert trecho_ao_redor("espiando", "spia") is None            # palavra inteira por padrao
    assert trecho_ao_redor("espiando", "spia", inteira=False)[1] == "spia"
    assert trecho_ao_redor("texto", "") is None and trecho_ao_redor("", "x") is None and trechos_ao_redor("texto", "a", maximo=0) == []


def test_varios_trechos_sem_sobreposicao_e_maximo():
    texto = "SPiA aqui. Depois o SPiA de novo. E ainda spia no fim."
    t = trechos_ao_redor(texto, "spia", largura=5, maximo=2)
    assert [x[1] for x in t] == ["SPiA", "SPiA"]
    assert len(trechos_ao_redor(texto, "spia", largura=5, maximo=9)) == 3


def test_destaque_no_texto_original_bate_com_forca_bruta_em_textos_aleatorios():
    """O mapa de posicoes por pedacos (texto grande) tem de dar o mesmo resultado de uma varredura caractere a caractere."""
    random.seed(7)
    alfabeto = list("abcDEF áéíóúçãõ-.,;!\n\t  ½ß ﬁ—…12") + ["́"]
    guardado = s._PEDACO
    try:
        for _ in range(400):
            texto = "".join(random.choice(alfabeto) for _ in range(random.randint(0, 80)))
            s._PEDACO = random.choice([1, 3, 8, 4096])
            norm = normalizar(texto)
            alvos = [i for i, c in enumerate(norm) if c != " "]
            obtido = s._posicoes_originais(texto, alvos)
            mapa, anterior, referencia = [0], True, [" "]
            for i, c in enumerate(texto):
                for n in s._TABELA[ord(c)]:
                    if n == " " and anterior:
                        continue
                    anterior = n == " "
                    referencia.append(n)
                    mapa.append(i)
            assert all(obtido[a] == mapa[a] for a in alvos), (texto, s._PEDACO)
    finally:
        s._PEDACO = guardado


def test_trecho_em_texto_grande_com_o_achado_longe_do_comeco():
    texto = ("palavra comum " * 3000) + "e o BO Fácil aparece aqui" + (" fim" * 3000)
    antes, achado, depois = trecho_ao_redor(texto, "bo facil", largura=20)
    assert achado == "BO Fácil" and antes.endswith("e o ") and depois.startswith(" aparece")


# ---------- variantes ----------
def test_variantes_nome_e_apelidos_normalizados_sem_repeticao():
    sol = SolucaoConhecida("SPiA", "PI", apelidos=("SPIA", "Sistema de Policiamento por Inteligência Artificial", "  ", "!!"))
    assert variantes_da_solucao(sol) == [" spia ", " sistema de policiamento por inteligencia artificial "]
    assert variantes_da_solucao(SolucaoConhecida("BO Fácil", "PI")) == [" bo facil "]


def test_solucao_conhecida_e_imutavel_e_tem_padroes():
    sol = SolucaoConhecida("X", "PI")
    assert sol.apelidos == () and sol.observacao == ""
    with pytest.raises(Exception):
        sol.nome = "Y"


def test_alias_casa_mesmo_quando_o_nome_nao_aparece():
    sol = SolucaoConhecida("SPiA", "PI", apelidos=("Sistema de Policiamento por Inteligência Artificial",))
    texto = normalizar("O Sistema de Policiamento por Inteligência Artificial do Piauí")
    assert any(casar(texto, v) for v in variantes_da_solucao(sol))


# ---------- situacao ----------
@pytest.mark.parametrize("resultados,paginas,achados,esperada", [
    (0, 0, 0, "nao_apareceu_nos_resultados"), (3, 0, 0, "apareceu_nos_resultados_pagina_nao_baixada"),
    (3, 1, 0, "pagina_baixada_nenhum_achado_cita_o_nome"), (0, 2, 0, "pagina_baixada_nenhum_achado_cita_o_nome"),
    (3, 2, 1, "citada_em_achados"), (0, 0, 5, "citada_em_achados")])
def test_situacao_da_solucao(resultados, paginas, achados, esperada):
    assert situacao_da_solucao(resultados, paginas, achados) == esperada


def test_toda_situacao_tem_rotulo_e_explicacao_em_portugues():
    assert set(s.SITUACOES) == {"nao_apareceu_nos_resultados", "apareceu_nos_resultados_pagina_nao_baixada",
                                "pagina_baixada_nenhum_achado_cita_o_nome", "citada_em_achados"}
    rotulos = [rotulo_da_situacao(x) for x in s.SITUACOES]
    assert len(set(rotulos)) == 4 and all(len(r) > 10 for r in rotulos)
    assert all(len(explicacao_da_situacao(x)) > 40 for x in s.SITUACOES)
    assert "NÃO prova" in explicacao_da_situacao("nao_apareceu_nos_resultados")
    assert rotulo_da_situacao("desconhecida") == "desconhecida" and explicacao_da_situacao("desconhecida") == ""
