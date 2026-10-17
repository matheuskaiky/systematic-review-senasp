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


# =====================================================================================================================
# RC23: resolucao de entidades de nome_solucao (dominio/entidades_solucao.py). Regras puras, deterministicas, sem rede.
# =====================================================================================================================
from dominio.entidades_solucao import (LIMIAR_SEMELHANCA, ROTULO_CAMADA, chave, resolver_entidades)

BO = SolucaoConhecida("BO Fácil", "PI", apelidos=("B.O. Fácil",))
SPIA = SolucaoConhecida("SPiA", "PI", apelidos=("SPIA", "Sistema de Policiamento por Inteligência Artificial"))
CADASTRO = (BO, SPIA)


def _uns(*nomes, uf="PI", n=1):
    return {(nome, uf): n for nome in nomes}


def _grupos(resolucao, uf=None):
    """{canonico: conjunto de grafias brutas} (de uma UF, se informada) para comparar sem depender da ordem."""
    return {e.canonico: {v.bruto for v in e.variantes if uf is None or v.uf == uf}
            for e in resolucao.entidades if uf is None or uf in e.ufs}


def _juntas(resolucao, *nomes, uf="PI"):
    e = {resolucao.entidade_de(n, uf) for n in nomes}
    return len(e) == 1 and None not in e


# ---------- chave (normalizacao para comparar) ----------
@pytest.mark.parametrize("nome", ["B.O. Fácil", "B.O Fácil", "BO Facil", "BO Fácil", "bo-facil", "  BO   FÁCIL!! ", "b.o.   facil"])
def test_chave_ignora_pontuacao_de_sigla_acento_e_caixa(nome):
    assert chave(nome) == "bo facil"


def test_chave_de_sigla_com_pontos_e_de_palavras_comuns():
    assert chave("S.P.I.A.") == chave("SPiA") == "spia"
    assert chave("Dr. Silva") == "dr silva" and chave("Delegacia Virtual 4.0") == "delegacia virtual 4 0"
    assert chave("") == "" and chave(None) == ""


# ---------- camada 1: cadastro ----------
def test_camada_1_funde_nome_e_apelidos_do_cadastro_e_usa_o_nome_oficial():
    r = resolver_entidades(_uns("BO Fácil", "B.O. Fácil", "B.O Fácil", "BO Facil", "SPIA", "SPiA", "Sistema de Policiamento por Inteligência Artificial"), CADASTRO)
    assert _grupos(r) == {"BO Fácil": {"BO Fácil", "B.O. Fácil", "B.O Fácil", "BO Facil"},
                          "SPiA": {"SPIA", "SPiA", "Sistema de Policiamento por Inteligência Artificial"}}
    assert all(e.conhecida in CADASTRO for e in r.entidades)
    assert r.camada_por_bruto[("SPiA", "PI")] == 0 and r.camada_por_bruto[("SPIA", "PI")] == 1       # a forma igual ao nome oficial nao precisou de fusao
    assert r.camada_por_bruto[("B.O Fácil", "PI")] == 1 and "cadastro" in next(
        v for v in r.entidade_de("B.O Fácil", "PI").variantes if v.bruto == "B.O Fácil").motivo


def test_camada_1_o_nome_oficial_vence_mesmo_que_outra_grafia_seja_mais_frequente():
    r = resolver_entidades({("SPIA", "PI"): 50, ("SPiA", "PI"): 1}, CADASTRO)
    assert [e.canonico for e in r.entidades] == ["SPiA"] and r.entidades[0].n == 51


def test_camada_1_tolera_uf_no_fim_e_os_formatos_nome_sigla():
    r = resolver_entidades(_uns("SPIA PI", "SPiA - PI", "SPIA (Sistema de Policiamento por Inteligência Artificial)", "BO Fácil - PI"), CADASTRO)
    assert _grupos(r) == {"SPiA": {"SPIA PI", "SPiA - PI", "SPIA (Sistema de Policiamento por Inteligência Artificial)"}, "BO Fácil": {"BO Fácil - PI"}}


def test_regra_da_uf_o_cadastro_do_pi_nao_absorve_o_mesmo_nome_de_outra_uf():
    r = resolver_entidades({("BO Fácil", "PI"): 3, ("BO Fácil", "TO"): 2, ("B.O. Fácil", "TO"): 1, ("BO Fácil", ""): 1}, CADASTRO)
    pi = r.entidade_de("BO Fácil", "PI")
    assert pi.conhecida == BO and pi.ufs == ("", "PI") and pi.n == 4                    # UF desconhecida (vazia) e compativel com o cadastro
    to = r.entidade_de("BO Fácil", "TO")
    assert to.conhecida is None and to is r.entidade_de("B.O. Fácil", "TO") and to.n == 3 and to.ufs == ("TO",)
    assert to is not pi


def test_regra_da_uf_outras_ufs_do_cadastro_liga_ufs_e_asterisco_liga_todas():
    nacional = SolucaoConhecida("Córtex", "DF", apelidos=("Cortex",), outras_ufs=("PI", "SP"))
    r = resolver_entidades({("Cortex", "PI"): 1, ("Córtex", "SP"): 2, ("Córtex", "DF"): 1, ("Cortex", "AC"): 1}, (nacional,))
    assert r.entidade_de("Cortex", "PI") is r.entidade_de("Córtex", "SP") is r.entidade_de("Córtex", "DF")
    assert r.entidade_de("Cortex", "AC") is not r.entidade_de("Cortex", "PI")           # AC nao esta na lista
    todas = SolucaoConhecida("Córtex", "DF", outras_ufs=("*",))
    r = resolver_entidades({("Cortex", "AC"): 1, ("Córtex", "RS"): 1}, (todas,))
    assert len(r.entidades) == 1 and r.entidades[0].canonico == "Córtex"


def test_dois_cadastros_diferentes_nunca_se_fundem():
    a, b = SolucaoConhecida("Alerta Mulher", "PI", apelidos=("Alerta",)), SolucaoConhecida("Alerta Idoso", "PI", apelidos=("Alerta",))
    r = resolver_entidades(_uns("Alerta", "Alerta Mulher", "Alerta Idoso"), (a, b))
    assert len(r.entidades) == 2
    assert {e.canonico for e in r.entidades} == {"Alerta Mulher", "Alerta Idoso"}
    assert r.entidade_de("Alerta", "PI").canonico == "Alerta Mulher"                    # o primeiro do cadastro vence o desempate


# ---------- camada 2: sigla e nome por extenso ----------
EXTENSO = "Sistema de Policiamento por Inteligência Artificial"


@pytest.mark.parametrize("sigla", ["SPiA", "SPIA", "S.P.I.A.", "spia"])
def test_camada_2_sigla_e_nome_por_extenso_viram_a_mesma_entidade(sigla):
    r = resolver_entidades(_uns(sigla, EXTENSO))
    assert _juntas(r, sigla, EXTENSO) and len(r.entidades) == 1
    v = next(v for v in r.entidades[0].variantes if v.camada)
    assert v.camada == 2 and "sigla e nome por extenso" in v.motivo and "SPIA" in v.motivo


def test_camada_2_spia_spia_e_nome_por_extenso_juntos_sem_cadastro():
    r = resolver_entidades({("SPiA", "PI"): 2, ("SPIA", "PI"): 7, (EXTENSO, "PI"): 1})
    assert len(r.entidades) == 1
    e = r.entidades[0]
    assert e.canonico == "SPIA" and e.n == 10 and e.camada_max == 2                      # mais frequente; a mais fraca ligacao e a da camada 2
    assert e.outras_grafias == ["SPiA", EXTENSO]


def test_camada_2_iniciais_sem_o_prefixo_generico_e_com_sigla_dentro_do_nome():
    r = resolver_entidades(_uns("PIA", "Sistema de Policiamento por Inteligência Artificial"))          # sem "Sistema"
    assert len(r.entidades) == 1
    r = resolver_entidades(_uns("SPIA", "Sistema de Policiamento por IA"))                              # "IA" entra inteira
    assert len(r.entidades) == 1
    r = resolver_entidades(_uns("PVIA", "Projeto Vigilância Inteligente Avançada"))                     # com o prefixo generico: P-V-I-A
    assert len(r.entidades) == 1


def test_camada_2_a_sigla_precisa_ter_de_3_a_8_caracteres_e_o_nome_nao_pode_ser_sigla_de_si_mesmo():
    assert len(resolver_entidades(_uns("BF", "BO Fácil")).entidades) == 2                  # duas letras: ambigua demais
    assert len(resolver_entidades(_uns("SIGLAGRANDEDEMAIS", "Sistema Integrado Geral Local Avançado Geral Alerta Digital Eletronico Maximo Anos")).entidades) == 2
    assert len(resolver_entidades(_uns("SPIAX", EXTENSO)).entidades) == 2                  # sigla que nao e a das iniciais


@pytest.mark.parametrize("bruto", [
    "Sistema de Policiamento por Inteligência Artificial (SPIA)", "SPIA - Sistema de Policiamento por Inteligência Artificial",
    "SPIA – Sistema de Policiamento por Inteligência Artificial", "SPIA — Sistema de Policiamento por Inteligência Artificial",
    "Sistema de Policiamento por Inteligência Artificial - SPIA", "SPIA: Sistema de Policiamento por Inteligência Artificial",
    "Sistema de Policiamento por Inteligência Artificial ( SPIA )"])
def test_camada_2_formatos_nome_com_sigla_ligam_o_valor_ao_nome_e_a_sigla_soltos(bruto):
    r = resolver_entidades(_uns(bruto, "SPIA", EXTENSO))
    assert len(r.entidades) == 1, _grupos(r)
    assert next(v for v in r.entidades[0].variantes if v.bruto == bruto).camada == 2


def test_camada_2_formato_nome_sigla_liga_mesmo_quando_as_iniciais_nao_batem():
    r = resolver_entidades(_uns("Boletim Eletrônico Policial (BOLEP)", "BOLEP"))
    assert len(r.entidades) == 1
    assert "formato Nome (SIGLA)" in next(v for v in r.entidades[0].variantes if v.camada).motivo


def test_camada_2_formato_so_vale_para_sigla_de_verdade():
    # "Teresina" nao e sigla (uma maiuscula so); "PI" e UF; "versão 2" tem duas palavras; "WhatsApp" tem poucas maiusculas
    for bruto in ("Delegacia Digital - Teresina", "Delegacia Digital (PI)", "Delegacia Digital (versão 2)", "Delegacia Digital - WhatsApp"):
        r = resolver_entidades(_uns(bruto, "Teresina", "WhatsApp", "Delegacia Digital"))
        assert not _juntas(r, bruto, "Teresina"), bruto
        assert not _juntas(r, bruto, "WhatsApp"), bruto


def test_camada_2_dois_formatos_que_compartilham_a_sigla_se_fundem():
    r = resolver_entidades(_uns("SPIA - Sistema de Policiamento por Inteligência Artificial", "Sistema de Policiamento por Inteligência Artificial (SPIA)"))
    assert len(r.entidades) == 1


def test_camada_2_uf_no_fim_e_tolerada_mas_so_a_do_proprio_achado():
    r = resolver_entidades({("SPIA PI", "PI"): 1, ("SPIA", "PI"): 1, ("Sistema de Policiamento por Inteligência Artificial PI", "PI"): 1})
    assert len(r.entidades) == 1
    r = resolver_entidades({("SPIA SP", "PI"): 1, ("SPIA", "PI"): 1})                       # "SP" nao e a UF do achado: faz parte do nome
    assert len(r.entidades) == 2


# ---------- camada 3: semelhanca ----------
@pytest.mark.parametrize("grafias", [
    ("BO Fácil", "B.O. Fácil", "B.O Fácil", "BO Facil", "bo-facil", "BOFácil", "BO  FÁCIL"),
    ("Cell Guard", "CellGuard", "CELLGUARD", "cell-guard"),
    ("Cérebro", "Cerebro", "CÉREBRO"),
    ("Policiamento Preditivo Inteligente", "Policiamento Preditivo Inteligentes", "Policiamnto Preditivo Inteligente"),
    ("Delegacia Virtual do Piauí", "Delegacia Virtual Piauí", "Delegacia Virtual da Piauí")])
def test_camada_3_pontuacao_acento_caixa_espacos_plural_e_erro_de_digitacao(grafias):
    r = resolver_entidades(_uns(*grafias))
    assert len(r.entidades) == 1, _grupos(r)
    assert all(v.camada in (0, 3) for v in r.entidades[0].variantes)


def test_camada_3_e_marcada_como_semelhanca_e_explica_o_motivo():
    r = resolver_entidades(_uns("BO Fácil", "B.O. Fácil"))
    v = next(v for v in r.entidades[0].variantes if v.camada)
    assert v.camada == 3 and v.rotulo_camada == "unificado por semelhança" and "grafia equivalente" in v.motivo
    r = resolver_entidades(_uns("Policiamento Preditivo Inteligente", "Policiamnto Preditivo Inteligente"))
    assert "semelhança lexical 0,9" in next(v for v in r.entidades[0].variantes if v.camada).motivo


def test_camada_3_prefixos_genericos_a_decisao_projeto_vigia_e_vigia_sao_a_mesma_entidade():
    assert _juntas(resolver_entidades(_uns("Projeto Vigia", "Vigia")), "Projeto Vigia", "Vigia")
    assert _juntas(resolver_entidades(_uns("Sistema SPiA", "SPiA")), "Sistema SPiA", "SPiA")
    assert _juntas(resolver_entidades(_uns("Plataforma Alerta Mulher", "Alerta Mulher", "App Alerta Mulher")), "Plataforma Alerta Mulher", "App Alerta Mulher")
    assert _juntas(resolver_entidades(_uns("Aplicativo Rota Segura", "Rota Segura")), "Aplicativo Rota Segura", "Rota Segura")
    assert _juntas(resolver_entidades(_uns("Programa Mulher Segura", "Mulher Segura")), "Programa Mulher Segura", "Mulher Segura")
    assert len(resolver_entidades(_uns("Operação Paz", "Paz")).entidades) == 2             # "Paz" tem so 3 letras: nome curto nao se funde por prefixo


def test_camada_3_dois_prefixos_genericos_diferentes_nao_se_fundem_diretamente():
    r = resolver_entidades(_uns("Operação Verão", "Programa Verão"))
    assert len(r.entidades) == 2


def test_camada_3_palavras_curtas_que_diferem_numa_letra_sao_nomes_diferentes():
    for a, b in (("Vigia Norte", "Vigia Sorte"), ("Vigia Nuvem", "Vigia Nuven"), ("Alerta Rio", "Alerta Rua"), ("Radar Sul", "Radar Sol")):
        assert len(resolver_entidades(_uns(a, b)).entidades) == 2, (a, b)


# ---------- protecao contra falsos positivos ----------
@pytest.mark.parametrize("a,b", [
    ("Operação Paz I", "Operação Paz II"), ("Operação Paz II", "Operação Paz III"), ("Operação Paz", "Operação Paz II"),
    ("Operação Paz 2", "Operação Paz 3"), ("Delegacia Virtual 4.0", "Delegacia Virtual 3.0"), ("Delegacia Virtual 4.0", "Delegacia Virtual"),
    ("Delegacia Virtual 2.0", "Delegacia Virtual 2.1"), ("Vigia 360", "Vigia 180"), ("Fase IV", "Fase VI")])
def test_numerais_e_romanos_diferentes_nunca_se_fundem(a, b):
    assert len(resolver_entidades(_uns(a, b)).entidades) == 2


def test_numerais_iguais_em_arabico_e_romano_se_fundem_e_a_ordem_importa():
    assert len(resolver_entidades(_uns("Operação Paz II", "Operação Paz 2", "Operação Paz ii")).entidades) == 1
    assert len(resolver_entidades(_uns("Fase 1 Etapa 2", "Fase 2 Etapa 1")).entidades) == 2


def test_nunca_funde_ufs_diferentes_mesmo_com_nome_identico():
    r = resolver_entidades({("Delegacia Virtual", "PI"): 3, ("Delegacia Virtual", "TO"): 2, ("Delegacia Virtual PI", "TO"): 1})
    assert len(r.entidades) == 3                                                         # "PI" no fim so e tolerado quando e a UF do proprio achado
    assert sorted(e.ufs for e in r.entidades) == [("PI",), ("TO",), ("TO",)]
    r = resolver_entidades({("Delegacia Virtual", "PI"): 3, ("Delegacia Virtual", "TO"): 2, ("Delegacia Virtual TO", "TO"): 1})
    assert len(r.entidades) == 2 and {e.ufs for e in r.entidades} == {("PI",), ("TO",)}
    assert r.entidade_de("Delegacia Virtual", "PI") is not r.entidade_de("Delegacia Virtual", "TO")
    assert r.entidade_de("Delegacia Virtual", "PI").n == 3
    assert sorted(r.variantes_por_canonico["Delegacia Virtual"]) == sorted([("Delegacia Virtual", 3), ("Delegacia Virtual", 2), ("Delegacia Virtual TO", 1)])
    sigla_pi = resolver_entidades({("SPIA", "PI"): 1, (EXTENSO, "SP"): 1})                   # sigla e extenso so se ligam na mesma UF
    assert len(sigla_pi.entidades) == 2


def test_sistemas_parecidos_mas_distintos_nao_se_fundem():
    r = resolver_entidades(_uns("Vigia Nuvem", "Vigia Digital", "Vigia Norte", "Vigia", "Radar Cidadão", "Radar Cidade"))
    assert not _juntas(r, "Vigia Nuvem", "Vigia Digital") and not _juntas(r, "Vigia Nuvem", "Vigia Norte")
    assert not _juntas(r, "Vigia", "Vigia Nuvem")                                           # numero de palavras diferente
    assert not _juntas(r, "Radar Cidadão", "Radar Cidade")


@pytest.mark.parametrize("a,b", [("IA", "Sistema IA"), ("BO", "BOs"), ("SP", "SP1"), ("APP", "App Policial"), ("IA", "I.A. Digital")])
def test_nome_muito_curto_so_se_funde_por_grafia_identica(a, b):
    assert len(resolver_entidades(_uns(a, b)).entidades) == 2
    assert len(resolver_entidades(_uns("IA", "I.A.", "ia")).entidades) == 1                 # identica depois de normalizar


def test_nome_curto_sem_par_e_nome_em_branco_e_ignorado_sem_quebrar():
    r = resolver_entidades({("", "PI"): 3, ("   ", "PI"): 1, (None, "PI"): 1, ("IA", "PI"): 2, ("IA", None): 1})
    assert sorted((e.canonico, e.ufs, e.n) for e in r.entidades) == [("IA", ("",), 1), ("IA", ("PI",), 2)]      # UF desconhecida nunca se mistura com outra
    assert resolver_entidades({}).entidades == () and resolver_entidades({}, CADASTRO).entidades == ()
    assert resolver_entidades({("SPIA", "PI"): 1}, CADASTRO).entidades[0].canonico == "SPiA"


def test_nenhum_nome_some_cada_bruto_aparece_em_exatamente_uma_entidade():
    nomes = ["BO Fácil", "B.O. Fácil", "SPIA", EXTENSO, "Operação Paz I", "Operação Paz II", "CellGuard", "Projeto Vigia", "XYZ Raro"]
    r = resolver_entidades({(n, "PI"): i + 1 for i, n in enumerate(nomes)}, CADASTRO)
    todas = [(v.bruto, v.uf) for e in r.entidades for v in e.variantes]
    assert sorted(todas) == sorted((n, "PI") for n in nomes) and sum(e.n for e in r.entidades) == sum(range(1, len(nomes) + 1)) == r.n_achados
    assert r.entidade_de("XYZ Raro", "PI").canonico == "XYZ Raro" and r.entidade_de("nao existe", "PI") is None
    assert r.canonico_de("nao existe", "PI") == "nao existe"


def test_diagnostico_lista_os_quase_acertos_recusados_com_o_motivo():
    r = resolver_entidades(_uns("Operação Paz I", "Operação Paz II", "Vigia Norte", "Vigia Sorte", "Operação Verão", "Programa Verão"), diagnostico=True)
    motivos = {(a, b): m for a, b, _, _, m in r.recusados}
    assert "numerais diferentes" in motivos[("Operação Paz I", "Operação Paz II")]
    assert "palavras diferentes" in motivos[("Vigia Norte", "Vigia Sorte")]
    assert "prefixos genéricos" in motivos[("Operação Verão", "Programa Verão")]
    assert resolver_entidades(_uns("Operação Paz I", "Operação Paz II")).recusados == ()


# ---------- nome canonico ----------
def test_canonico_a_forma_mais_frequente_quando_nao_ha_cadastro():
    r = resolver_entidades({("BO Fácil", "PI"): 2, ("B.O. Fácil", "PI"): 5, ("bo facil", "PI"): 3})
    assert [e.canonico for e in r.entidades] == ["B.O. Fácil"]


def test_canonico_empate_bem_formatada_depois_acentuada_depois_curta_depois_alfabetica():
    assert resolver_entidades(_uns("bo facil", "BO Fácil")).entidades[0].canonico == "BO Fácil"          # tudo minusculo perde
    assert resolver_entidades(_uns("BO FACIL", "BO Facil")).entidades[0].canonico == "BO Facil"           # tudo maiusculo longo perde
    assert resolver_entidades(_uns("Cerebro", "Cérebro")).entidades[0].canonico == "Cérebro"              # a acentuada e a grafia correta
    assert resolver_entidades(_uns("B.O. Fácil", "BO Fácil")).entidades[0].canonico == "BO Fácil"         # mais curta
    assert resolver_entidades(_uns("SPIA", "SPiA")).entidades[0].canonico == "SPIA"                       # sigla curta em maiusculas e bem formatada
    assert resolver_entidades(_uns("Bo Fácil", "Bo Fácil.")).entidades[0].canonico == "Bo Fácil"
    assert resolver_entidades(_uns("Cell Guard", "CellGuard", "cell guard")).entidades[0].canonico in ("Cell Guard", "CellGuard")


def test_canonico_usa_a_soma_das_ufs_da_mesma_grafia():
    r = resolver_entidades({("Cerebro", "PI"): 2, ("Cérebro", "PI"): 3})
    assert r.entidades[0].canonico == "Cérebro" and r.entidades[0].n == 5


# ---------- estabilidade, ordem e idempotencia ----------
BASE_ESTAVEL = {
    ("SPiA", "PI"): 2, ("SPIA", "PI"): 7, (EXTENSO, "PI"): 1, ("BO Fácil", "PI"): 6, ("B.O Fácil", "PI"): 2, ("B.O. Fácil", "PI"): 2,
    ("Sistema SPiA", "PI"): 1, ("Projeto Vigia", "PI"): 2, ("Vigia", "PI"): 1, ("CellGuard", "PI"): 1, ("Cell Guard", "PI"): 1,
    ("Operação Paz I", "PI"): 1, ("Operação Paz II", "PI"): 2, ("Delegacia Virtual", "PI"): 2, ("Delegacia Virtual", "TO"): 3,
    ("Delegacia Virtual 4.0", "TO"): 1, ("Delegacia Virtual 3.0", "TO"): 1, ("Vigia Nuvem", "CE"): 1, ("Vigia Digital", "CE"): 1,
    ("Rota Segura (RS)", "RS"): 1, ("RS - Rota Segura", "RS"): 1, ("Rota Segura", "RS"): 2, ("IA", "SP"): 1, ("I.A.", "SP"): 1,
}


def _assinatura(r):
    return sorted((e.canonico, e.ufs, e.n, tuple((v.bruto, v.uf, v.n, v.camada, v.motivo) for v in e.variantes)) for e in r.entidades)


@pytest.mark.parametrize("conhecidas", [(), CADASTRO])
def test_resultado_independe_da_ordem_de_entrada(conhecidas):
    itens = list(BASE_ESTAVEL.items())
    referencia = _assinatura(resolver_entidades(dict(itens), conhecidas))
    rng = random.Random(23)
    for _ in range(40):
        rng.shuffle(itens)
        assert _assinatura(resolver_entidades(dict(itens), conhecidas)) == referencia
        assert _assinatura(resolver_entidades(iter(itens), conhecidas)) == referencia       # tambem aceita um iteravel de pares


@pytest.mark.parametrize("conhecidas", [(), CADASTRO])
def test_acrescentar_nomes_nunca_separa_uma_entidade_existente(conhecidas):
    """Propriedade: os grupos de qualquer subconjunto continuam inteiros dentro dos grupos do conjunto maior."""
    cheio = resolver_entidades(BASE_ESTAVEL, conhecidas)
    chaves = sorted(BASE_ESTAVEL)
    rng = random.Random(7)
    for _ in range(40):
        parte = {k: BASE_ESTAVEL[k] for k in rng.sample(chaves, rng.randint(1, len(chaves)))}
        pequeno = resolver_entidades(parte, conhecidas)
        for e in pequeno.entidades:
            destino = {id(cheio.entidade_de(v.bruto, v.uf)) for v in e.variantes}
            assert len(destino) == 1, (e.canonico, [v.bruto for v in e.variantes])


def test_chegada_de_um_nome_novo_so_acrescenta():
    antes = resolver_entidades({("SPiA", "PI"): 2, ("SPIA", "PI"): 7, ("CellGuard", "PI"): 1}, ())
    depois = resolver_entidades({("SPiA", "PI"): 2, ("SPIA", "PI"): 7, ("CellGuard", "PI"): 1, (EXTENSO, "PI"): 1, ("Cell Guard", "PI"): 1}, ())
    assert len(antes.entidades) == 2 and len(depois.entidades) == 2
    assert _juntas(depois, "SPiA", "SPIA", EXTENSO) and _juntas(depois, "CellGuard", "Cell Guard")


@pytest.mark.parametrize("conhecidas", [(), CADASTRO])
def test_idempotente_resolver_os_nomes_canonicos_nao_funde_nem_separa_nada(conhecidas):
    r = resolver_entidades(BASE_ESTAVEL, conhecidas)
    canonicos = {(e.canonico, uf): 1 for e in r.entidades for uf in e.ufs}
    r2 = resolver_entidades(canonicos, conhecidas)
    assert sorted((e.canonico, e.ufs) for e in r2.entidades) == sorted((e.canonico, e.ufs) for e in r.entidades)
    assert r.canonico_por_bruto == resolver_entidades(BASE_ESTAVEL, conhecidas).canonico_por_bruto        # determinismo


def test_desempenho_com_centenas_de_nomes():
    import time
    nomes = {(f"Sistema {a} {b}", "PI"): 1 for a in ("Alfa", "Beta", "Gama", "Delta", "Omega") for b in ("Norte", "Sul", "Leste", "Oeste", "Centro", "Plus")}
    nomes.update({(f"Nome Único {i:03d}", uf): 1 for i in range(120) for uf in ("PI", "CE", "SP")})
    inicio = time.perf_counter()
    r = resolver_entidades(nomes, CADASTRO)
    assert time.perf_counter() - inicio < 15
    assert sum(e.n for e in r.entidades) == len(nomes) and len(r.entidades) <= len(nomes)


def test_api_de_resumo_e_rotulos():
    r = resolver_entidades({("SPiA", "PI"): 2, ("SPIA", "PI"): 7, (EXTENSO, "PI"): 1, ("BO Fácil", "PI"): 3}, CADASTRO)
    assert r.canonico_por_bruto[("SPIA", "PI")] == "SPiA" and r.canonico_por_bruto[("BO Fácil", "PI")] == "BO Fácil"
    assert r.variantes_por_canonico["SPiA"] == [("SPIA", 7), ("SPiA", 2), (EXTENSO, 1)]
    assert r.camada_por_bruto[(EXTENSO, "PI")] == 1 and r.pares_do_canonico("SPiA") == [("SPIA", "PI"), ("SPiA", "PI"), (EXTENSO, "PI")]
    assert r.entidade_da_conhecida(SPIA).canonico == "SPiA" and r.entidade_da_conhecida(SolucaoConhecida("Z", "PI")) is None
    assert [e.canonico for e in r.entidades] == ["SPiA", "BO Fácil"]                                    # do mais citado ao menos
    assert set(ROTULO_CAMADA) == {0, 1, 2, 3} and LIMIAR_SEMELHANCA == 0.88
    e = r.entidade_de("SPIA", "PI")
    assert e.unificada and e.outras_grafias == ["SPIA", EXTENSO]
    assert not resolver_entidades({("Sozinho", "PI"): 1}).entidades[0].unificada


def test_solucao_conhecida_aceita_outras_ufs_com_padrao_vazio():
    assert SolucaoConhecida("X", "PI").outras_ufs == () and SolucaoConhecida("X", "PI", outras_ufs=("SP",)).outras_ufs == ("SP",)


def test_modulo_de_entidades_so_importa_biblioteca_padrao_e_dominio():
    import ast
    import pathlib
    import sys
    fonte = (pathlib.Path(__file__).resolve().parent.parent / "dominio" / "entidades_solucao.py").read_text(encoding="utf-8")
    nomes = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            nomes |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            nomes.add((no.module or "").split(".")[0])
    assert nomes <= set(sys.stdlib_module_names) | {"dominio"}, nomes
    assert {"re", "unicodedata", "difflib", "dataclasses"} <= nomes
