"""Texto de metodologia: funcao pura, testada com fatos montados a mao (completos, parciais e vazios)."""
import copy
import re

from painel import formatacao as fmt
from painel.metodologia_texto import gerar_metodologia, para_texto


def _fatos():
    """Fatos completos, com numeros todos diferentes entre si para que um erro de troca apareca."""
    exec_ok = {"comando": "pipeline-uf", "status": "concluida", "iniciado_em": "2026-03-02T10:00:00", "finalizado_em": "2026-03-02T11:00:00",
               "config_hash": "aaaabbbbccccdddd", "commit_git": "deadbeef", "no_relatorio": 1, "motivo_exclusao": None}
    return {
        "banco": "real", "bases_esperadas": ["IEEE", "ACM"],
        "execucoes": [{**exec_ok, "run_id": "RUN_A"}, {**exec_ok, "run_id": "RUN_B", "comando": "academico"},
                      {**exec_ok, "run_id": "RUN_FORA", "no_relatorio": 0, "motivo_exclusao": "piloto"}],
        "retomadas": [],
        "academico": {"n_requisicoes": 31, "n_ok": 29, "n_falhas": 2, "n_termos": 4, "n_retornados": 1234, "n_artigos_scholar": 987,
                      "primeira": "2026-02-01T09:00:00", "ultima": "2026-02-05T09:00:00", "provedores": ["serpapi_scholar"], "run_ids": ["RUN_B"],
                      "termos": [{"termo_id": "T01", "query": '"reconhecimento facial"', "idioma": "pt", "n_requisicoes": 7, "n_artigos": 321},
                                 {"termo_id": "T02", "query": '"facial recognition"', "idioma": "en", "n_requisicoes": 8, "n_artigos": 654}]},
        "manuais": [{"base": "IEEE", "n_buscas": 3, "total_resultados": 450, "total_apos_filtro": 210, "total_selecionados": 55,
                     "primeira": "2026-02-10", "ultima": "2026-02-12", "n_artigos_importados": 44},
                    {"base": "ACM", "n_buscas": 1, "total_resultados": 90, "total_apos_filtro": 60, "total_selecionados": 12,
                     "primeira": "2026-02-10", "ultima": "2026-02-10", "n_artigos_importados": 11}],
        "literatura": {"n_artigos": 1000, "n_artigos_manuais": 55, "triagem": {"total": 1000, "incluidos": 140, "excluidos": 360, "pendentes": 500},
                       "prisma": {19: 33}},
        "web": {"n_requisicoes": 700, "n_ok": 690, "n_falhas": 10, "primeira": "2026-03-02T10:00:00", "ultima": "2026-03-03T10:00:00",
                "provedores": ["perplexity"], "run_ids": ["RUN_A"], "modelos_consulta": ["M01", "M02"], "urls_oficiais": 2100,
                "descartes": [{"motivo": "nao_oficial", "n": 800}, {"motivo": "limite_por_uf", "n": 150}],
                "funil": {"consultas_web": 690, "resultados": 6900, "urls_unicas": 4321, "selecionadas": 1500, "paginas": 1400,
                          "paginas_com_texto": 1300}},
        "classificacao": {"provedores": ["gemini"], "run_ids": ["RUN_A"], "n_invalidas": 0, "n_fora_vocabulario": 17, "n_so_snippet": 0,
                          "classificadores": [{"classificador": "gemini:modelo-x", "prompt_versao": "v3", "n_classificacoes": 1300,
                                               "n_json_valido": 1290, "n_achados": 200, "n_evidencia_ok": 150}]},
        "achados": {"total": 200, "evidencia_ok": 150, "verificados": 50, "confirmados": 40, "descartados": 10, "pendentes_sem_evidencia": 25,
                    "n_revisores": 2, "confirmados_por_tecnologia": [{"tecnologia": "reconhecimento_facial", "n": 25},
                                                                     {"tecnologia": "leitura_placas", "n": 15}]},
        "ufs": {"uf_confirmada": 9, "uf_so_classificado": 5, "uf_sem_achados": 13, "n_ufs": 27, "confirmadas": ["PI", "CE"]},
        "municipal": {"n_cidades": 0, "n_achados": 0, "n_confirmados": 0, "cidades": []},
        "custos": {"por_etapa": [{"etapa": "busca_academica", "provedor": "serpapi_scholar", "n_chamadas": 31, "n_ok": 29, "n_com_custo": 29,
                                  "custo_usd": 1.5, "n_ok_sem_custo": 0},
                                 {"etapa": "busca_web", "provedor": "perplexity", "n_chamadas": 700, "n_ok": 690, "n_com_custo": 690,
                                  "custo_usd": 3.5, "n_ok_sem_custo": 0},
                                 {"etapa": "classificacao", "provedor": "gemini", "n_chamadas": 1300, "n_ok": 1290, "n_com_custo": 1290,
                                  "custo_usd": 7.25, "n_ok_sem_custo": 0}],
                   "gasto_real": [{"provedor": "perplexity", "no_relatorio": 1, "n_chamadas": 700, "n_ok": 690, "custo_registrado_usd": 3.5, "n_ok_sem_custo": 0},
                                  {"provedor": "perplexity", "no_relatorio": 0, "n_chamadas": 20, "n_ok": 20, "custo_registrado_usd": 0.1, "n_ok_sem_custo": 0}]},
    }


def _texto(fatos, **kw):
    return gerar_metodologia(fatos, **kw)["texto"]


def _segmentos(res):
    for s in res["secoes"]:
        for b in s["blocos"]:
            if b["tipo"] == "p":
                yield b["seg"]
            else:
                yield from b["itens"]
    yield from res["ressalvas"]


def _hrefs(res):
    return {h for seg in _segmentos(res) for _, h in seg if h}


# ---------- estrutura e fidelidade dos numeros ----------
def test_fatos_completos_geram_todas_as_secoes_e_cada_numero_do_dado_aparece():
    res = gerar_metodologia(_fatos())
    texto = res["texto"]
    assert [s["id"] for s in res["secoes"]] == ["literatura", "web", "classificacao", "verificacao", "ufs", "custos", "reprodutibilidade"]
    for esperado in ("31", "29", "1.234", "987", "4", "321", "654", "450", "210", "55", "44", "90", "60", "12", "1.000", "140", "360", "500",
                     "700", "690", "6.900", "4.321", "1.500", "1.400", "1.300", "2.100", "800", "150", "200", "17", "40", "25", "15", "33",
                     "US$ 1,50", "US$ 3,50", "US$ 7,25", "US$ 12,25"):
        assert esperado in texto, esperado
    for esperado in ("serpapi_scholar", "perplexity", "gemini:modelo-x", "v3", "RUN_A", "RUN_B", "RUN_FORA", "aaaabbbbcccc", "deadbeef", "M01", "M02",
                     "T01", "T02", '"reconhecimento facial"', "IEEE", "ACM", "02/03/2026", "entre 01/02/2026 e 05/02/2026"):
        assert esperado in texto, esperado


def test_nenhum_numero_no_texto_vem_de_fora_dos_fatos():
    f = _fatos()
    texto = _texto(f)
    # tira o que nao e quantidade: datas, ids de termo e de modelo, hash e porcentagens (conferidas a parte)
    limpo = re.sub(r"\d{2}/\d{2}/\d{4}", "", texto)
    limpo = re.sub(r"\b[TM]\d+\b|\bv3\b|\bUS\$ ", "", limpo)
    permitidos = {"31", "29", "2", "1.234", "987", "4", "7", "321", "8", "654", "450", "210", "55", "44", "90", "60", "12", "1.000", "140",
                  "360", "500", "700", "690", "10", "6.900", "4.321", "1.500", "1.400", "1.300", "1.290", "2.100", "800", "150", "200", "17",
                  "27", "40", "25", "15", "33", "9", "5", "13", "1", "3", "1,50", "3,50", "7,25", "12,25", "0,10", "50", "11",
                  "3,60"}      # 3,60 = 3,50 + 0,10: soma do gasto real; 500 = 140 + 360: avaliados na triagem
    pcts = set(re.findall(r"\d+,\d%", limpo))
    achados = set(re.findall(r"\d+(?:\.\d{3})*(?:,\d+)?", re.sub(r"\d+,\d%", "", limpo)))
    assert achados - permitidos == set(), achados - permitidos
    assert pcts == {"75,0%", "25,0%", "80,0%"}, pcts


def test_os_tres_percentuais_do_texto_sao_os_dos_fatos():
    t = _texto(_fatos())
    assert "(75,0%)" in t        # evidencia confere: 150 de 200
    assert "(25,0%)" in t        # verificados: 50 de 200
    assert "taxa de confirmação foi de 80,0%" in t        # 40 de 50


def test_cada_numero_aponta_para_a_pagina_que_o_justifica():
    res = gerar_metodologia(_fatos())
    por_texto = {}
    for seg in _segmentos(res):
        for t, h in seg:
            por_texto.setdefault(t, set()).add(h)
    assert "/achados?verificacao=confirmado" in por_texto["40"]
    assert "/achados?verificacao=descartado" in por_texto["10"]
    assert "/achados?verificacao=pendente" in por_texto["150"]
    assert "/achados?verificacao=pendente&evidencia=0" in por_texto["25"] and "/achados?evidencia=1" in por_texto["150"]
    assert "/estados" in por_texto["9"] and "/estados/PI" in por_texto["PI"]
    assert "/chamadas?etapa=busca_academica" in por_texto["1.234"] and "/chamadas?etapa=busca_web&resultado=ok" in por_texto["690"]
    assert "/chamadas?etapa=busca_web&resultado=falha" in por_texto["10"]
    assert "/execucoes/RUN_A" in por_texto["RUN_A"]
    assert "/literatura/prisma" in por_texto["33"] and "/literatura/artigos?decisao=incluir" in por_texto["140"]
    assert "/literatura/artigos?base=IEEE" in por_texto["IEEE"] and "/literatura/artigos?termo=T01" in por_texto["T01"]
    assert "/achados?verificacao=confirmado&tecnologia=reconhecimento_facial" in por_texto["25"]
    assert all(h.startswith("/") for h in _hrefs(res))


def test_texto_puro_e_a_juncao_dos_segmentos_sem_links():
    res = gerar_metodologia(_fatos())
    for seg in _segmentos(res):
        assert para_texto(seg) in res["texto"]
    assert "href" not in res["texto"] and "/achados?" not in res["texto"]


# ---------- integridade: verificado x apenas classificado ----------
def test_confirmados_e_apenas_classificados_aparecem_separados_e_o_resto_nao_e_resultado():
    t = _texto(_fatos())
    assert "tratados como hipóteses: nenhum conta como resultado antes da verificação humana" in t
    assert "9 de 27 UFs têm ao menos um achado confirmado" in t
    assert "5 só têm achados classificados pelo modelo, ainda sem confirmação humana" in t
    assert "150 ainda não foram verificados e, por isso, não entram nos resultados" in t
    assert "não que a UF não use a tecnologia" in t


def test_sem_nenhuma_verificacao_o_texto_avisa_que_nada_e_resultado():
    f = _fatos()
    f["achados"].update(verificados=0, confirmados=0, descartados=0, confirmados_por_tecnologia=[])
    f["ufs"].update(uf_confirmada=0, uf_so_classificado=14, confirmadas=[])
    res = gerar_metodologia(f)
    r = " ".join(para_texto(x) for x in res["ressalvas"])
    assert "Nenhum achado foi verificado por humano ainda" in r and "hipóteses do classificador" in r
    assert "0 de 27 UFs têm ao menos um achado confirmado" in res["texto"]


def test_com_achados_pendentes_a_ressalva_traz_o_numero():
    r = " ".join(para_texto(x) for x in gerar_metodologia(_fatos())["ressalvas"])
    assert "150 achados ainda não foram verificados" in r


# ---------- ressalvas por dado faltante ----------
def _ressalvas(f):
    return " | ".join(para_texto(x) for x in gerar_metodologia(f)["ressalvas"])


def test_fatos_completos_e_limpos_so_tem_as_ressalvas_esperadas():
    r = _ressalvas(_fatos())
    for nao_esperada in ("Nenhuma busca", "Custo não calculado", "+sujo", "fictícios", "Nada foi coletado", "sem JSON válido"):
        assert nao_esperada not in r, nao_esperada
    assert "fora do relatório" in r        # RUN_FORA
    assert "triagem está incompleta" in r  # 500 pendentes


def test_custo_sem_preco_vira_ressalva_e_nao_entra_no_total():
    f = _fatos()
    web = next(e for e in f["custos"]["por_etapa"] if e["etapa"] == "busca_web")
    web.update(n_com_custo=0, custo_usd=0, n_ok_sem_custo=690)
    res = gerar_metodologia(f)
    assert "Custo não calculado: preços não informados para busca web (perplexity)" in " | ".join(para_texto(x) for x in res["ressalvas"])
    assert "busca web (perplexity): 700 chamadas, custo não calculado (preço não informado)" in res["texto"]
    assert "US$ 8,75" in res["texto"]            # 1,50 + 7,25: o custo da busca web nao entra


def test_chamadas_sem_custo_em_provedor_que_tem_custo_geram_ressalva_de_subestimativa():
    f = _fatos()
    f["custos"]["por_etapa"][2]["n_ok_sem_custo"] = 5
    assert "o custo total está subestimado" in _ressalvas(f)


def test_commit_sujo_e_ausente_geram_ressalvas():
    f = _fatos()
    f["execucoes"][0]["commit_git"] = "deadbeef+sujo:cafe0000"
    f["execucoes"][1]["commit_git"] = None
    r = _ressalvas(f)
    assert "+sujo" in r and "RUN_A" in r and "não reproduz exatamente o código" in r
    assert "Commit do código não registrado em: RUN_B" in r


def test_execucao_nao_concluida_e_configuracoes_diferentes_e_retomadas():
    f = _fatos()
    f["execucoes"][1].update(status="interrompida", config_hash="zzzzyyyyxxxx")
    f["retomadas"] = [{"run_id": "RUN_A", "n": 1}]
    r = _ressalvas(f)
    assert "não terminaram como concluídas: RUN_B" in r
    assert "2 configurações diferentes" in r
    assert "retomadas (--retomar)" in r


def test_sem_busca_manual_diz_quais_bases_faltam():
    f = _fatos()
    f["manuais"] = []
    f["literatura"]["n_artigos_manuais"] = 0
    res = gerar_metodologia(f)
    assert "Nenhuma busca manual foi importada: as bases IEEE, ACM não têm contagens no banco" in " | ".join(para_texto(x) for x in res["ressalvas"])
    assert "Nenhuma busca manual nas bases (IEEE, ACM) foi importada até agora" in res["texto"]


def test_base_manual_parcial_e_contagem_nao_informada():
    f = _fatos()
    f["manuais"] = [{"base": "IEEE", "n_buscas": 2, "total_resultados": 450, "total_apos_filtro": None, "total_selecionados": None,
                     "primeira": None, "ultima": None, "n_artigos_importados": 4}]
    res = gerar_metodologia(f)
    r = " | ".join(para_texto(x) for x in res["ressalvas"])
    assert "Sem busca manual registrada em: ACM" in r and "incompletas (não informadas) em: IEEE" in r
    assert "após o filtro da base: contagem não informada" in res["texto"] and "selecionados: contagem não informada" in res["texto"]


def test_triagem_incompleta_e_so_snippet_e_json_invalido():
    f = _fatos()
    f["classificacao"].update(n_so_snippet=22, n_invalidas=3)
    r = _ressalvas(f)
    assert "A triagem está incompleta: 500 de 1.000 artigos aguardam decisão" in r
    assert "22 classificações usaram só o snippet" in r
    assert "3 classificações sem JSON válido" in r and "“sem achados”" in r


def test_escopo_municipal_so_aparece_quando_ha_cidade():
    f = _fatos()
    assert "Não há achados de secretarias municipais" in _texto(f)
    f["municipal"] = {"n_cidades": 3, "n_achados": 21, "n_confirmados": 8, "cidades": []}
    t = _texto(f)
    assert "21 achados em secretarias municipais de 3 cidades, dos quais 8 confirmados" in t
    assert "Não há achados de secretarias municipais" not in t


def test_banco_demo_e_simulado_avisam_que_os_dados_nao_sao_de_pesquisa():
    f = _fatos()
    f["banco"] = "demo"
    assert "fictícios (demonstração)" in _ressalvas(f)
    f["banco"] = "simulado"
    assert "simulados (teste, sem chamadas reais)" in _ressalvas(f)


def test_termo_sem_texto_na_configuracao_e_prompt_sem_versao():
    f = _fatos()
    f["academico"]["termos"][0]["query"] = None
    f["classificacao"]["classificadores"][0]["prompt_versao"] = None
    res = gerar_metodologia(f)
    r = " | ".join(para_texto(x) for x in res["ressalvas"])
    assert "O texto do termo não foi encontrado na configuração gravada para: T01" in r
    assert "A versão do prompt não está registrada" in r
    assert "(versão não registrada)" in res["texto"]


def test_mais_de_um_classificador_gera_ressalva():
    f = _fatos()
    f["classificacao"]["classificadores"].append({"classificador": "outro:modelo", "prompt_versao": "v4", "n_classificacoes": 5, "n_json_valido": 5,
                                                  "n_achados": 1, "n_evidencia_ok": 1})
    r = _ressalvas(f)
    assert "Há 2 combinações de classificador e versão do prompt" in r


# ---------- parcial e vazio ----------
def test_dados_parciais_so_com_busca_web_nao_inventam_o_resto():
    f = {"execucoes": _fatos()["execucoes"][:1], "web": _fatos()["web"]}
    res = gerar_metodologia(f)
    t = res["texto"]
    assert "Nenhuma busca no Google Scholar consta" in t and "Nenhuma classificação consta" in t
    assert "Ainda não há achados para verificar" in t
    assert "Nenhuma chamada externa consta" in t
    assert "690 consultas bem-sucedidas" in t
    r = " | ".join(para_texto(x) for x in res["ressalvas"])
    for esperado in ("Nenhuma busca no Google Scholar", "Nenhuma classificação", "Nenhuma busca manual foi importada"):
        assert esperado in r


def test_fatos_vazios_dizem_que_nada_foi_coletado():
    for vazio in ({}, None, {"execucoes": [], "academico": {}, "manuais": [], "achados": {"total": 0}}):
        res = gerar_metodologia(vazio)
        assert res["vazio"] is True
        assert [s["id"] for s in res["secoes"]] == ["situacao"]
        assert "Nada foi coletado ainda" in res["texto"]
        assert any("Nada foi coletado ainda" in para_texto(r) for r in res["ressalvas"])
        assert not re.search(r"\d", " ".join(para_texto(x) for x in _segmentos(res)).replace("python main.py pipeline-uf --ufs PI --limite 5", ""))


def test_nao_altera_os_fatos_recebidos():
    f = _fatos()
    antes = copy.deepcopy(f)
    gerar_metodologia(f)
    assert f == antes


def test_singular_e_plural():
    f = _fatos()
    f["academico"].update(n_requisicoes=1, n_ok=1, n_falhas=0, n_termos=1)
    f["achados"].update(total=1, verificados=0, confirmados=0, descartados=0, evidencia_ok=1, n_revisores=0, pendentes_sem_evidencia=0,
                        confirmados_por_tecnologia=[])
    t = _texto(f)
    assert "com 1 termo de busca, em 1 requisição (1 bem-sucedida e 0 com falha)" in t
    assert "(75,0%)" not in t
