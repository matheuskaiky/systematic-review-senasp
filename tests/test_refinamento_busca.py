"""Refinamento da busca (dominio puro): ficha de ruido por termo, matriz, validacao de operadores negativos e payload da sintese.
Todos os numeros esperados foram calculados a mao a partir das linhas escritas em cada teste."""
import json

from dominio import refinamento_busca as R


def L(item_id, termos, status, uf="", valido=1, **kw):
    """Uma linha da triagem de escopo, so com o que a funcao le."""
    return {"item_id": item_id, "uf": uf, "termos_consulta": json.dumps(termos), "status": status, "valido": valido, **kw}


def C(id_, titulo, resumo="", humano=False, uf=""):
    return {"id": id_, "uf": uf, "titulo": titulo, "resumo": resumo, "incluido_humano": humano}


# ============================== ficha por termo ==============================
LINHAS = [
    L(1, ["A", "B"], "elegivel", escopo_geografico="brasil"),
    L(2, ["A"], "excluido", categoria_motivo="SEM_IA_OU_TECNOLOGIA", dominio_tematico="saude", escopo_geografico="internacional", termo_gerador="A"),
    L(3, ["A"], "quarentena", categoria_motivo="AMBIGUIDADE_LEXICAL", dominio_tematico="educacao", escopo_geografico="internacional", termo_gerador="A"),
    L(4, ["A", "B"], "excluido", categoria_motivo="SEM_IA_OU_TECNOLOGIA", dominio_tematico="saude", escopo_geografico="brasil", termo_gerador="B"),
    L(5, ["B"], "excluido", valido=0, categoria_motivo="RUIDO_WEB", dominio_tematico="outro", escopo_geografico="internacional"),
    L(6, ["A"], "elegivel", escopo_geografico="brasil"),
]


def test_ficha_conta_cada_item_uma_vez_por_termo_e_so_as_linhas_validas():
    fichas = {f["termo"]: f for f in R.ficha_por_termo(LINHAS)}
    a, b = fichas["A"], fichas["B"]
    # termo A: itens 1, 2, 3, 4, 6 (5 nao e de A): 2 elegiveis, 1 quarentena, 2 excluidos
    assert (a["n_itens"], a["n_elegivel"], a["n_quarentena"], a["n_excluido"], a["n_invalidos"]) == (5, 2, 1, 2, 0)
    assert (a["pct_elegivel"], a["pct_quarentena"], a["pct_excluido"], a["pct_ruido"]) == (40.0, 20.0, 40.0, 60.0)
    assert a["categoria_top"] == "SEM_IA_OU_TECNOLOGIA" and a["categorias"] == {"SEM_IA_OU_TECNOLOGIA": 2, "AMBIGUIDADE_LEXICAL": 1}
    assert a["dominios"] == {"saude": 2, "educacao": 1} and a["dominio_top"] == "saude"
    assert (a["n_internacional"], a["pct_internacional"]) == (2, 40.0)       # itens 2 e 3, de 5
    assert (a["termo_gerador_top"], a["termo_gerador_top_n"]) == ("A", 2)    # A gerou 2 e 3; B gerou 4
    # termo B: itens 1 e 4 validos, o 5 e invalido e fica fora dos percentuais
    assert (b["n_itens"], b["n_invalidos"], b["n_elegivel"], b["n_excluido"]) == (2, 1, 1, 1)
    assert (b["pct_ruido"], b["pct_internacional"], b["termo_gerador_top"]) == (50.0, 0.0, "B")


def test_ficha_ordena_pelo_ruido_e_desempata_pelo_numero_de_itens():
    assert [f["termo"] for f in R.ficha_por_termo(LINHAS)] == ["A", "B"]             # 60% antes de 50%
    mais = [L(1, ["X"], "excluido"), L(2, ["Y"], "excluido"), L(3, ["Y"], "excluido"), L(4, ["Z"], "elegivel")]
    assert [f["termo"] for f in R.ficha_por_termo(mais)] == ["Y", "X", "Z"]           # 100% (2 itens), 100% (1 item), 0%


def test_ficha_termo_so_com_linhas_invalidas_nao_divide_por_zero():
    f = R.ficha_por_termo([L(1, ["Q"], "excluido", valido=0)])[0]
    assert (f["n_itens"], f["n_invalidos"], f["pct_ruido"], f["categoria_top"], f["termo_gerador_top"]) == (0, 1, None, None, None)


def test_termos_da_linha_aceita_lista_json_texto_e_ignora_lixo():
    assert R.termos_da_linha({"termos_consulta": '["a", " a ", "b", ""]'}) == ["a", "b"]
    assert R.termos_da_linha({"termos_consulta": "consulta solta"}) == ["consulta solta"]
    assert R.termos_da_linha({"termos_consulta": '"so um"'}) == ["so um"]
    assert R.termos_da_linha({"termos_consulta": None}) == [] and R.termos_da_linha({}) == []
    assert R.termos_da_linha({"termos_consulta": ["x", None]}) == ["x"]
    assert R.ficha_por_termo([{"status": "excluido", "valido": 1}]) == []           # sem termo nao entra na ficha


def test_empate_na_categoria_mais_frequente_e_resolvido_pelo_texto():
    linhas = [L(1, ["T"], "excluido", categoria_motivo="B"), L(2, ["T"], "excluido", categoria_motivo="A")]
    assert R.ficha_por_termo(linhas)[0]["categoria_top"] == "A"
    assert R.ficha_por_termo(list(reversed(linhas)))[0]["categoria_top"] == "A"


# ============================== matriz de ruido ==============================
def test_matriz_ruido_conta_so_nao_elegiveis_validos():
    m = R.matriz_ruido(LINHAS)
    # nao elegiveis validos: 2 (A, SEM_IA, saude), 3 (A, AMBIG, educacao), 4 (B, SEM_IA, saude); o 5 e invalido
    assert len(m) == 3 and all(x["n"] == 1 for x in m)
    assert {(x["termo_gerador"], x["categoria_motivo"], x["dominio_tematico"]) for x in m} == {
        ("A", "SEM_IA_OU_TECNOLOGIA", "saude"), ("A", "AMBIGUIDADE_LEXICAL", "educacao"), ("B", "SEM_IA_OU_TECNOLOGIA", "saude")}
    mais = LINHAS + [L(7, ["A"], "excluido", categoria_motivo="SEM_IA_OU_TECNOLOGIA", dominio_tematico="saude", termo_gerador="A")]
    topo = R.matriz_ruido(mais)[0]
    assert (topo["termo_gerador"], topo["categoria_motivo"], topo["dominio_tematico"], topo["n"]) == ("A", "SEM_IA_OU_TECNOLOGIA", "saude", 2)


# ============================== operadores negativos ==============================
def _excluido(i, sinal, termos=("B",), **kw):
    return L(i, list(termos), "excluido", sinal_negativo=sinal, categoria_motivo="FORA_SEGURANCA_PUBLICA", **kw)


def test_normalizacao_e_casamento_por_palavra_inteira():
    assert R.normalizar_texto("  Veículo, AUTÔNOMO!  ") == "veiculo autonomo"
    assert R.contem_frase("o hospital central", "hospital") and not R.contem_frase("hospitalidade turistica", "hospital")
    assert R.contem_frase("um veiculo autonomo novo", "veiculo autonomo") and not R.contem_frase("veiculo e autonomo", "veiculo autonomo")


def test_negativo_seguro_sem_dano_colateral_e_ganho_por_termo():
    linhas = [_excluido(12, "veículo autônomo"), L(13, ["A"], "elegivel"), _excluido(14, "Veiculo Autonomo", termos=("A", "B"))]
    corpus = [C(12, "Veículo autônomo para entrega"), C(13, "Reconhecimento em estádios", "um veículo qualquer"),
              C(14, "VEICULO AUTONOMO e logística"), C(15, "Outro assunto")]
    r = R.avaliar_negativos(linhas, corpus)
    (n,) = r["negativos"]
    assert n["veredito"] == "seguro" and n["sinal"] in ("veículo autônomo", "Veiculo Autonomo")
    assert (n["n_sugerido_por"], n["n_no_corpus"], n["n_excluidos_atingidos"], n["n_colateral"]) == (2, 2, 2, 0)
    assert n["ids_colaterais"] == [] and n["pct_colateral"] == 0.0 and not n["protegida"]
    # por termo: B tem os itens 12 e 14 (ganho 2); A so o 14 (ganho 1); nenhum elegivel perdido
    assert {t: (x[0]["ganho"], x[0]["perda_elegivel"], x[0]["seguro_no_termo"]) for t, x in r["por_termo"].items()} == {"B": (2, 0, True), "A": (1, 0, True)}


def test_dano_colateral_conta_elegivel_quarentena_e_incluido_pelo_humano_sem_duplicar():
    linhas = [_excluido(1, "hospital"), _excluido(2, "hospital"), L(3, ["A"], "elegivel"), L(4, ["A"], "quarentena")]
    corpus = [C(1, "Hospital X"), C(2, "hospital y"), C(3, "Reconhecimento facial no hospital"), C(4, "Câmera no hospital municipal"),
              C(5, "Hospital central", humano=True),                       # sem veredito, mas incluido pelo humano
              C(3, "x", humano=False), C(6, "Hospitalidade turística"), C(7, "Sem relação")]
    # o item 3 aparece duas vezes no corpus de proposito: a segunda ocorrencia nao contem a palavra e nao conta
    (n,) = R.avaliar_negativos(linhas, corpus)["negativos"]
    assert n["n_no_corpus"] == 5                                               # 1, 2, 3, 4 e 5 (hospitalidade nao casa)
    assert (n["n_colateral_elegivel"], n["n_colateral_quarentena"], n["n_colateral_humano"], n["n_colateral"]) == (1, 1, 1, 3)
    assert n["ids_colaterais"] == [3, 4, 5] and n["pct_colateral"] == 60.0
    assert [c["status"] for c in n["colaterais"]] == ["elegivel", "quarentena", None]
    assert n["colaterais"][2]["incluido_humano"] is True
    assert n["veredito"] == "perigoso" and n["n_excluidos_atingidos"] == 2


def test_item_elegivel_que_tambem_foi_incluido_pelo_humano_conta_uma_vez():
    linhas = [_excluido(1, "ruido"), L(2, ["A"], "elegivel")]
    corpus = [C(1, "ruido"), C(2, "tem ruido", humano=True)]
    (n,) = R.avaliar_negativos(linhas, corpus)["negativos"]
    assert n["n_colateral"] == 1 and n["n_colateral_elegivel"] == 1 and n["n_colateral_humano"] == 1


def _cenario_com_n_itens(n_excluidos, n_quarentena):
    linhas = [_excluido(i, "agricultura") for i in range(n_excluidos)]
    linhas += [L(1000 + i, ["C"], "quarentena") for i in range(n_quarentena)]
    corpus = [C(i, "IA na agricultura") for i in range(n_excluidos)] + [C(1000 + i, "Drones na agricultura") for i in range(n_quarentena)]
    return R.avaliar_negativos(linhas, corpus)["negativos"][0]


def test_limites_do_veredito_arriscado_e_perigoso_a_5_por_cento():
    n = _cenario_com_n_itens(19, 1)                                            # 1 de 20 = 5%: ainda arriscado
    assert (n["n_no_corpus"], n["n_colateral"], n["pct_colateral"], n["veredito"]) == (20, 1, 5.0, "arriscado")
    n = _cenario_com_n_itens(20, 2)                                            # 2 de 22 = 9,1%: perigoso
    assert (n["n_no_corpus"], n["n_colateral"], n["pct_colateral"], n["veredito"]) == (22, 2, 9.1, "perigoso")
    n = _cenario_com_n_itens(3, 1)                                             # 1 de 4 = 25%
    assert n["veredito"] == "perigoso"
    assert _cenario_com_n_itens(5, 0)["veredito"] == "seguro"


def test_ids_colaterais_ate_cinco():
    n = _cenario_com_n_itens(1, 8)
    assert n["n_colateral"] == 8 and len(n["ids_colaterais"]) == 5 and len(n["colaterais"]) == 5


def test_palavra_central_do_tema_e_sempre_perigosa_mesmo_sem_dano():
    protegidos = ("reconhecimento facial", "Policiamento preditivo", "Leitura de placas de veículos")
    linhas = [_excluido(1, "reconhecimento facial"), _excluido(2, "facial"), _excluido(3, "placas de circuito"), _excluido(4, "de"),
              _excluido(5, "agricultura"), _excluido(6, "preditivo")]
    corpus = [C(1, "reconhecimento facial para diagnóstico"), C(2, "análise facial de pele"), C(3, "placas de circuito impresso"),
              C(4, "de"), C(5, "agricultura"), C(6, "modelo preditivo de safra")]
    r = R.avaliar_negativos(linhas, corpus, protegidos)
    por_chave = {n["chave"]: n for n in r["negativos"]}
    for chave in ("reconhecimento facial", "facial", "placas de circuito", "preditivo"):
        assert por_chave[chave]["protegida"] and por_chave[chave]["veredito"] == "perigoso" and por_chave[chave]["n_colateral"] == 0, chave
    assert por_chave["agricultura"]["veredito"] == "seguro"
    assert not por_chave["de"]["protegida"]                                    # preposicao nao protege nada
    assert [n["chave"] for n in r["negativos"]][0] in ("agricultura", "de")    # os seguros vem antes dos perigosos
    assert all(x["chave"] not in {"facial", "preditivo", "reconhecimento facial"} for lista in r["por_termo"].values() for x in lista)


def test_sem_protegidos_a_mesma_frase_e_segura():
    r = R.avaliar_negativos([_excluido(1, "reconhecimento facial")], [C(1, "reconhecimento facial para diagnóstico")])
    assert r["negativos"][0]["veredito"] == "seguro"


def test_linhas_invalidas_e_sinais_vazios_sao_ignorados():
    linhas = [_excluido(1, "ruido", valido=0), _excluido(2, ""), _excluido(3, None), L(4, ["A"], "quarentena", sinal_negativo="x")]
    assert R.avaliar_negativos(linhas, [C(1, "ruido"), C(2, "a"), C(3, "b"), C(4, "x")]) == {"negativos": [], "por_termo": {}}


def test_ganho_e_perda_por_termo_misturam_excluido_quarentena_e_elegivel():
    # o operador "esporte" aparece nos itens de A e de B; em B so ha ruido, em A ha um item bom que se perderia
    linhas = [_excluido(1, "esporte", termos=("A",)), _excluido(2, "esporte", termos=("B",)), L(3, ["B"], "quarentena"),
              L(4, ["A"], "elegivel")] + [_excluido(10 + i, "esporte", termos=("B",)) for i in range(40)]
    corpus = [C(1, "esporte"), C(2, "esporte"), C(3, "esporte"), C(4, "esporte e policia")] + [C(10 + i, "esporte") for i in range(40)]
    r = R.avaliar_negativos(linhas, corpus)
    (n,) = r["negativos"]
    # corpus: 44 itens contem "esporte"; colateral: o quarentena (3) e o elegivel (4) = 2, ou seja 4,5%: arriscado
    assert (n["n_no_corpus"], n["n_colateral"], n["veredito"]) == (44, 2, "arriscado")
    b, a = r["por_termo"]["B"][0], r["por_termo"]["A"][0]
    assert (b["ganho_excluido"], b["ganho_quarentena"], b["ganho"], b["perda_elegivel"], b["seguro_no_termo"]) == (41, 1, 42, 0, True)
    assert (a["ganho"], a["perda_elegivel"], a["seguro_no_termo"], a["veredito"]) == (1, 1, False, "arriscado")


def test_por_termo_ordena_os_sem_perda_primeiro_e_depois_pelo_ganho():
    linhas = ([_excluido(i, "alfa", termos=("T",)) for i in range(3)] + [_excluido(10 + i, "beta", termos=("T",)) for i in range(5)]
              + [L(20, ["T"], "elegivel")])
    corpus = [C(i, "alfa") for i in range(3)] + [C(10 + i, "beta") for i in range(5)] + [C(20, "beta e outras coisas")]
    # beta: 6 itens contem, 1 colateral = 16,7%: perigoso (nao entra); alfa: seguro
    r = R.avaliar_negativos(linhas, corpus)
    assert [n["chave"] for n in r["negativos"]] == ["alfa", "beta"] and r["negativos"][1]["veredito"] == "perigoso"
    assert [x["chave"] for x in r["por_termo"]["T"]] == ["alfa"]


# ============================== payload da sintese ==============================
def test_payload_so_tem_numeros_e_no_maximo_cinco_exemplos_curtos():
    ficha = {f["termo"]: f for f in R.ficha_por_termo(LINHAS)}["A"]
    negs = [{"sinal": "hospital", "ganho": 7, "perda_elegivel": 0, "seguro_no_termo": True, "veredito": "seguro"},
            {"sinal": "esporte", "ganho": 3, "perda_elegivel": 1, "seguro_no_termo": False, "veredito": "arriscado"}]
    exemplos = [{"titulo": "T" * 300, "status": "excluido", "categoria_motivo": "RUIDO_WEB", "justificativa": "j " * 100, "extra": "x"}
                for _ in range(9)]
    p = R.payload_sintese_termo("A", ficha, negs, exemplos)
    assert p["termo"] == "A" and p["n_itens"] == 5 and p["contagens"] == {"elegivel": 2, "quarentena": 1, "excluido": 2}
    assert p["pct_ruido"] == 60.0 and p["pct_internacional"] == 40.0 and p["termo_gerador_top"] == "A"
    assert p["categorias"] == {"SEM_IA_OU_TECNOLOGIA": 2, "AMBIGUIDADE_LEXICAL": 1} and p["dominios"] == {"saude": 2, "educacao": 1}
    assert p["negativos_seguros"] == [{"sinal": "hospital", "ganho": 7, "perda_elegivel": 0}]   # o que perde elegivel nao entra
    assert len(p["exemplos"]) == 5 and all(len(e["titulo"]) <= R.TAMANHO_EXEMPLO and len(e["justificativa"]) <= R.TAMANHO_EXEMPLO
                                           and set(e) == {"titulo", "status", "categoria_motivo", "justificativa"} for e in p["exemplos"])
    assert len(json.dumps(p, ensure_ascii=False)) < 2500                                      # compacto
    assert R.payload_sintese_termo("Z", None, None, None)["n_itens"] == 0
