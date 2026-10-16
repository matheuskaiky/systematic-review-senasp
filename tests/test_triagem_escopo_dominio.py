"""Triagem de escopo: parte pura (esquema, mensagem, conferencias, custo, amostra), com casos calculados a mao."""
import json

from config.triagem_escopo import CONFIG
from dominio.relevancia import pontuar_relevancia
from dominio.triagem_escopo import (CATEGORIA_TEMPORAL, atomo_do_modelo_de_consulta, chave_item, enriquecer_termos,
                                    escolher_amostra, estimar_custo, montar_esquema, montar_mensagem_usuario,
                                    montar_termos, validar_resposta)

TERMOS = ['"reconhecimento facial"', "predictive policing"]


def _artigo(n=1, ano=2023, titulo="Reconhecimento facial na Polícia Militar de Teresina", resumo="Estudo de caso no Brasil.",
            termos=None):
    return {"item_id": n, "fonte": "artigo", "uf": "", "provedor": "serpapi_scholar", "titulo": titulo,
            "resumo": resumo, "autores_publicacao": "A Silva - Revista, 2023", "ano": ano, "link": "https://x.org/a",
            "host": "x.org", "termos_ids": ["T01"], "termos": TERMOS if termos is None else termos}


def _web(n=7, uf="PI"):
    return {"item_id": n, "fonte": "web", "uf": uf, "provedor": "perplexity_search", "titulo": "Cameras",
            "resumo": "Edital de cameras", "url": "https://pi.gov.br/x", "host": "pi.gov.br", "tecnologia": "leitura_placas",
            "tecnologias": ["leitura_placas"], "modelos_ids": ["M01"], "selecionado": True, "termos": ["leitura de placas"]}


def _obj(item, **kw):
    base = {"id": chave_item(item), "status": "elegivel", "confianca": "alta", "categoria_motivo": "NENHUMA",
            "justificativa": "Trata de reconhecimento facial policial.", "termo_gerador_ruido": "", "sinal_negativo": "",
            "dominio_tematico": "seguranca_publica", "escopo_geografico": "brasil", "tipo_documento": "artigo_periodico"}
    base.update(kw)
    return base


def _validar(itens, objetos):
    return validar_resposta(itens, json.dumps({"itens": objetos}), CONFIG)


# ---------------------------------------------------------------- esquema e mensagem
def test_esquema_tem_enums_fechados_e_ids_do_lote():
    e = montar_esquema(CONFIG, ["1", "2-PI"])
    item = e["properties"]["itens"]["items"]
    assert e["required"] == ["itens"] and e["properties"]["itens"]["type"] == "array"
    assert item["properties"]["id"]["enum"] == ["1", "2-PI"]
    assert item["properties"]["status"]["enum"] == ["elegivel", "quarentena", "excluido"]
    assert item["properties"]["categoria_motivo"]["enum"][-1] == "NENHUMA" and len(item["properties"]["categoria_motivo"]["enum"]) == 8
    assert len(item["properties"]["dominio_tematico"]["enum"]) == 14
    assert set(item["required"]) == set(item["properties"])


def test_chave_do_item_artigo_e_web():
    assert chave_item(_artigo(12)) == "12" and chave_item(_web(7, "PI")) == "7-PI"


def test_mensagem_usuario_uma_linha_json_por_item_e_resumo_cortado():
    longo = _artigo(1, resumo="x" * 5000)
    msg = montar_mensagem_usuario([longo, _artigo(2)], CONFIG)
    linhas = msg.splitlines()[2:]
    assert msg.startswith("Screen the following 2 items")
    assert len(linhas) == 2
    primeira = json.loads(linhas[0])
    assert primeira["id"] == "1" and len(primeira["resumo"]) == CONFIG.snippet_max_chars
    assert primeira["fonte"] == "serpapi_scholar" and primeira["query_terms"] == TERMOS and primeira["ano"] == 2023
    web = json.loads(montar_mensagem_usuario([_web()], CONFIG).splitlines()[2])
    assert web["id"] == "7-PI" and web["uf"] == "PI" and web["url"] == "https://pi.gov.br/x" and web["fonte"] == "perplexity_search"
    assert "ano" not in web


def test_termos_de_artigo_e_atomos_da_consulta_web():
    assert atomo_do_modelo_de_consulta("{tec} Secretaria de Segurança Pública {nome}") == "Secretaria de Segurança Pública"
    assert atomo_do_modelo_de_consulta("{tec} segurança pública {nome} {uf}") == "segurança pública"
    mapas = {"artigo": {"T01": '"reconhecimento facial"', "T02": "b"},
             "web": {"tecnologias": {"leitura_placas": "leitura de placas"}, "modelos": {"M01": "Secretaria", "M02": "segurança pública"}}}
    assert montar_termos({"fonte": "artigo", "termos_ids": ["T02", "T01", "T02"]}, mapas) == ["b", '"reconhecimento facial"']
    web = {"fonte": "web", "tecnologias": ["leitura_placas"], "modelos_ids": ["M01", "M02"]}
    assert montar_termos(web, mapas) == ["leitura de placas", "Secretaria", "segurança pública"]
    assert enriquecer_termos([web], mapas)[0]["termos"] == ["leitura de placas", "Secretaria", "segurança pública"]


# ---------------------------------------------------------------- conferencias
def test_resposta_correta_gera_uma_linha_valida_por_item():
    itens = [_artigo(1), _artigo(2)]
    linhas, extras = _validar(itens, [_obj(itens[1]), _obj(itens[0])])
    assert [l["item_id"] for l in linhas] == [1, 2]            # ordem da entrada, nao da resposta
    assert all(l["valido"] and l["problemas"] == [] and l["status"] == "elegivel" for l in linhas)
    assert linhas[0]["categoria_motivo"] is None and linhas[0]["termos_consulta"] == TERMOS
    assert extras == {"json_valido": True, "ids_ausentes": [], "ids_duplicados": [], "ids_desconhecidos": []}


def test_id_ausente_vira_linha_invalida_em_quarentena():
    itens = [_artigo(1), _artigo(2), _artigo(3)]
    linhas, extras = _validar(itens, [_obj(itens[0]), _obj(itens[2])])
    assert len(linhas) == 3 and extras["ids_ausentes"] == ["2"]
    l = linhas[1]
    assert l["status"] == "quarentena" and l["status_bruto"] is None and l["valido"] is False
    assert l["problemas"] == ["id_ausente_na_resposta"]


def test_id_duplicado_e_desconhecido():
    itens = [_artigo(1), _artigo(2)]
    linhas, extras = _validar(itens, [_obj(itens[0]), _obj(itens[0], status="quarentena"), _obj(itens[1]),
                                      {**_obj(itens[1]), "id": "99"}])
    assert extras["ids_duplicados"] == ["1"] and extras["ids_desconhecidos"] == ["99"]
    assert linhas[0]["status"] == "elegivel"                   # vale a primeira ocorrencia
    assert "id_duplicado_na_resposta" in linhas[0]["problemas"] and linhas[0]["valido"] is False
    assert linhas[1]["valido"] is True


def test_json_invalido_deixa_todos_sem_resposta():
    itens = [_artigo(1), _artigo(2)]
    linhas, extras = validar_resposta(itens, "isto nao e json", CONFIG)
    assert extras["json_valido"] is False and extras["ids_ausentes"] == ["1", "2"]
    assert [l["problemas"] for l in linhas] == [["resposta_json_invalida"]] * 2
    assert all(l["status"] == "quarentena" and l["status_bruto"] is None for l in linhas)


def test_resposta_aceita_lista_na_raiz():
    it = _artigo(1)
    linhas, extras = validar_resposta([it], json.dumps([_obj(it)]), CONFIG)
    assert extras["json_valido"] and linhas[0]["valido"]


def test_enum_invalido_e_sinalizado_e_status_invalido_vai_para_quarentena():
    it = _artigo(1)
    l = _validar([it], [_obj(it, status="talvez", confianca="muita", dominio_tematico="astronomia",
                             escopo_geografico="marte", tipo_documento="blog")])[0][0]
    assert l["status"] == "quarentena" and l["status_bruto"] == "talvez" and l["confianca"] is None
    assert l["dominio_tematico"] is None and l["escopo_geografico"] is None and l["tipo_documento"] is None
    assert l["problemas"] == ["status_invalido", "confianca_invalida", "dominio_tematico_invalido",
                              "escopo_geografico_invalido", "tipo_documento_invalido", "categoria_motivo_ausente"]
    assert l["valido"] is False


def test_regra_de_seguranca_excluido_sem_confianca_alta_vira_quarentena():
    it = _artigo(1)
    for conf in ("media", "baixa"):
        l = _validar([it], [_obj(it, status="excluido", confianca=conf, categoria_motivo="FORA_SEGURANCA_PUBLICA")])[0][0]
        assert l["status"] == "quarentena" and l["status_bruto"] == "excluido" and l["valido"] is True
    l = _validar([it], [_obj(it, status="excluido", confianca="alta", categoria_motivo="FORA_SEGURANCA_PUBLICA")])[0][0]
    assert l["status"] == "excluido" and l["status_bruto"] == "excluido"


def test_exclusao_sem_categoria_nao_e_certeza():
    it = _artigo(1)
    l = _validar([it], [_obj(it, status="excluido", confianca="alta")])[0][0]
    assert l["status"] == "quarentena" and l["status_bruto"] == "excluido" and l["problemas"] == ["categoria_motivo_ausente"]


def test_categoria_obrigatoria_se_nao_elegivel_e_nula_se_elegivel():
    it = _artigo(1)
    l = _validar([it], [_obj(it, status="quarentena", confianca="baixa")])[0][0]
    assert l["problemas"] == ["categoria_motivo_ausente"] and l["valido"] is False
    l = _validar([it], [_obj(it, categoria_motivo="SEM_IA_OU_TECNOLOGIA")])[0][0]
    assert l["status"] == "elegivel" and l["categoria_motivo"] is None and l["problemas"] == ["categoria_motivo_com_elegivel"]
    l = _validar([it], [_obj(it, status="quarentena", categoria_motivo="INVENTADA")])[0][0]
    assert l["problemas"] == ["categoria_motivo_invalida"]


def test_fora_do_recorte_geografico_excluido_vira_quarentena():
    it = _artigo(1)
    l = _validar([it], [_obj(it, status="excluido", confianca="alta", categoria_motivo="FORA_DO_RECORTE_GEOGRAFICO")])[0][0]
    assert l["status"] == "quarentena" and l["status_bruto"] == "excluido" and l["valido"] is True


def test_termo_gerador_precisa_ser_um_dos_termos_do_item_comparacao_normalizada():
    it = _artigo(1)
    ok = _validar([it], [_obj(it, status="quarentena", categoria_motivo="AMBIGUIDADE_LEXICAL",
                              termo_gerador_ruido="  Reconhecimento  FACIAL ")])[0][0]
    assert ok["termo_gerador"] == '"reconhecimento facial"' and ok["valido"] is True      # devolve o texto do termo
    ruim = _validar([it], [_obj(it, status="quarentena", categoria_motivo="AMBIGUIDADE_LEXICAL",
                                termo_gerador_ruido="machine learning")])[0][0]
    assert ruim["termo_gerador"] is None and ruim["problemas"] == ["termo_gerador_fora_da_lista"] and ruim["valido"] is True
    elegivel = _validar([it], [_obj(it, termo_gerador_ruido="machine learning")])[0][0]
    assert elegivel["termo_gerador"] is None and elegivel["valido"] is True               # elegivel nao tem termo gerador


def test_sinal_negativo_literal_ate_tres_palavras_sem_acento_nem_caixa():
    it = _artigo(1, titulo="Reconhecimento facial em Saúde Pública", resumo="Análise de hospitais e clínicas.")
    base = dict(status="quarentena", categoria_motivo="FORA_SEGURANCA_PUBLICA")
    ok = _validar([it], [_obj(it, sinal_negativo="SAUDE publica", **base)])[0][0]
    assert ok["sinal_negativo"] == "SAUDE publica" and ok["valido"]
    parte = _validar([it], [_obj(it, sinal_negativo="hospital", **base)])[0][0]       # "hospitais": nao e palavra inteira
    assert parte["sinal_negativo"] is None and parte["problemas"] == ["sinal_negativo_nao_literal"] and parte["valido"] is True
    longo = _validar([it], [_obj(it, sinal_negativo="análise de hospitais e", **base)])[0][0]
    assert longo["sinal_negativo"] is None and longo["problemas"] == ["sinal_negativo_longo"] and longo["valido"] is True
    no_resumo = _validar([it], [_obj(it, sinal_negativo="hospitais e clínicas", **base)])[0][0]
    assert no_resumo["sinal_negativo"] == "hospitais e clínicas"
    cortado = _artigo(2, resumo="x" * 1300 + " hospital")
    fora = _validar([cortado], [_obj(cortado, sinal_negativo="hospital", **base)])[0][0]   # alem do corte: o modelo nao viu
    assert fora["problemas"] == ["sinal_negativo_nao_literal"]


# ---------------------------------------------------------------- recorte temporal (2022)
def test_recorte_temporal_excluido_com_confianca_alta_e_ano_antigo_e_valido():
    it = _artigo(1, ano=2020)
    l = _validar([it], [_obj(it, status="excluido", confianca="alta", categoria_motivo=CATEGORIA_TEMPORAL)])[0][0]
    assert l["status"] == "excluido" and l["status_bruto"] == "excluido" and l["valido"] is True and l["problemas"] == []


def test_recorte_temporal_sem_confianca_alta_vira_quarentena_sem_invalidar():
    it = _artigo(1, ano=2021)
    l = _validar([it], [_obj(it, status="excluido", confianca="media", categoria_motivo=CATEGORIA_TEMPORAL)])[0][0]
    assert l["status"] == "quarentena" and l["status_bruto"] == "excluido" and l["valido"] is True


def test_recorte_temporal_com_ano_a_partir_de_2022_e_invalido_e_rebaixado():
    for ano in (2022, 2025):
        it = _artigo(1, ano=ano)
        l = _validar([it], [_obj(it, status="excluido", confianca="alta", categoria_motivo=CATEGORIA_TEMPORAL)])[0][0]
        assert l["status"] == "quarentena" and l["status_bruto"] == "excluido" and l["valido"] is False
        assert l["problemas"] == ["recorte_temporal_incoerente_com_o_ano"]
    it = _artigo(1, ano=2023)
    q = _validar([it], [_obj(it, status="quarentena", confianca="baixa", categoria_motivo=CATEGORIA_TEMPORAL)])[0][0]
    assert q["status"] == "quarentena" and q["problemas"] == ["recorte_temporal_incoerente_com_o_ano"]


def test_recorte_temporal_sem_ano_conhecido_nao_exclui():
    it = _artigo(1, ano=None)
    l = _validar([it], [_obj(it, status="excluido", confianca="alta", categoria_motivo=CATEGORIA_TEMPORAL)])[0][0]
    assert l["status"] == "quarentena" and l["problemas"] == ["recorte_temporal_sem_ano"]
    web = _web()
    w = _validar([web], [_obj(web, status="excluido", confianca="alta", categoria_motivo=CATEGORIA_TEMPORAL)])[0][0]
    assert w["status"] == "quarentena"


def test_ano_antigo_com_outra_categoria_e_mantido_e_excecao_elegivel_vale():
    it = _artigo(1, ano=2018)
    outra = _validar([it], [_obj(it, status="excluido", confianca="alta", categoria_motivo="FORA_SEGURANCA_PUBLICA")])[0][0]
    assert outra["status"] == "excluido" and outra["valido"] is True
    excecao = _validar([it], [_obj(it, status="elegivel", justificativa="Estudo brasileiro fundamental, útil apesar do ano.")])[0][0]
    assert excecao["status"] == "elegivel" and excecao["valido"] is True


# ---------------------------------------------------------------- custo
def _item_tamanho(n, titulo, resumo, autores, termos):
    return {"item_id": n, "fonte": "artigo", "uf": "", "titulo": titulo, "resumo": resumo,
            "autores_publicacao": autores, "termos": termos}


PRECOS = {"entrada": 0.3, "saida": 2.5}


def test_estimar_custo_calculado_a_mao():
    # 25 itens de 340 caracteres (100 titulo + 200 resumo + 30 autores + 10 termo) = 100 tokens + 50 = 150 tokens cada
    itens = [_item_tamanho(i, "t" * 100, "r" * 200, "a" * 30, ["k" * 10]) for i in range(25)]
    e = estimar_custo(itens, 10, PRECOS, CONFIG)
    assert e["chamadas"] == 3 and e["itens"] == 25
    assert e["tokens_entrada"] == 3 * 1500 + 25 * 150 == 8250
    assert e["tokens_entrada_por_chamada"] == 2750 and e["tokens_entrada_maior_chamada"] == 1500 + 10 * 150
    assert e["pct_janela_contexto"] == round(100 * 3000 / 1_048_576, 2) == 0.29
    n = e["niveis"]
    assert [n[k]["tokens_saida"] for k in ("baixo", "medio", "alto")] == [25 * 90 + 3 * 100, 25 * 120 + 3 * 300, 25 * 160 + 3 * 600]
    assert abs(n["medio"]["custo_usd"] - (8250 * 0.3 + 3900 * 2.5) / 1e6) < 1e-12           # 0,0122250
    assert abs(n["baixo"]["custo_usd"] - (8250 * 0.3 + 2550 * 2.5) / 1e6) < 1e-12
    assert abs(n["alto"]["custo_usd"] - (8250 * 0.3 + 5800 * 2.5) / 1e6) < 1e-12


def test_estimar_custo_corta_o_resumo_no_limite_e_aceita_lista_vazia():
    longo = [_item_tamanho(1, "", "r" * 5000, "", [])]
    # 1200 caracteres / 3,4 = 352,9 -> 353 tokens + 50 + 1500 de instrucoes
    assert estimar_custo(longo, 10, PRECOS, CONFIG)["tokens_entrada"] == 1500 + 353 + 50
    vazio = estimar_custo([], 10, PRECOS, CONFIG)
    assert vazio["chamadas"] == 0 and vazio["tokens_entrada"] == 0 and vazio["niveis"]["alto"]["custo_usd"] == 0


# ---------------------------------------------------------------- amostra
def _lote_artigos():
    itens = []
    n = 0
    for termo in ("T01", "T02", "T03", "T04"):
        for nivel in ("alta", "media", "baixa"):
            for k in range(6):
                n += 1
                if nivel == "alta":
                    t, r = "Reconhecimento facial na Polícia Militar do Brasil", "policiamento no Brasil"
                elif nivel == "media":
                    t, r = "Reconhecimento facial na Polícia", "sem pais"
                else:
                    t, r = f"Cultivo de soja {n}", "agricultura"
                itens.append({"item_id": n, "fonte": "artigo", "uf": "", "titulo": f"{t} {n}", "resumo": r,
                              "autores_publicacao": "", "link": "", "termos_ids": [termo], "ano": 2023})
    return itens


def test_amostra_e_deterministica_e_depende_da_semente():
    itens = _lote_artigos()
    a = escolher_amostra(itens, 10, False, "s1")
    assert [i["item_id"] for i in a] == [i["item_id"] for i in escolher_amostra(list(reversed(itens)), 10, False, "s1")]
    assert len(a) == 10 and len({i["item_id"] for i in a}) == 10
    assert [i["item_id"] for i in a] != [i["item_id"] for i in escolher_amostra(itens, 10, False, "s2")]
    assert len(escolher_amostra(itens, 1000, True, "s1")) == len(itens)       # n maior que o total: todos


def test_amostra_estratificada_artigos_cotas_iguais_por_nivel_e_espalhada_por_termo():
    itens = _lote_artigos()
    a = escolher_amostra(itens, 12, True, "s1")
    niveis = [pontuar_relevancia(i["titulo"], i["resumo"], i["autores_publicacao"], i["link"])["nivel"] for i in a]
    assert {n: niveis.count(n) for n in ("alta", "media", "baixa")} == {"alta": 4, "media": 4, "baixa": 4}
    por_nivel = {}
    for i, n in zip(a, niveis):
        por_nivel.setdefault(n, []).append(i["termos_ids"][0])
    assert all(sorted(t) == ["T01", "T02", "T03", "T04"] for t in por_nivel.values())      # 4 por nivel, um de cada termo
    assert [i["item_id"] for i in a] == [i["item_id"] for i in escolher_amostra(itens, 12, True, "s1")]


def test_amostra_estratificada_cede_a_sobra_de_estrato_pequeno():
    itens = [i for i in _lote_artigos() if not (i["titulo"].startswith("Reconhecimento facial na Polícia Militar") and i["item_id"] > 2)]
    a = escolher_amostra(itens, 15, True, "s")
    niveis = [pontuar_relevancia(i["titulo"], i["resumo"], i["autores_publicacao"], i["link"])["nivel"] for i in a]
    assert niveis.count("alta") == 2 and niveis.count("media") + niveis.count("baixa") == 13 and len(a) == 15


def test_amostra_web_metade_selecionados_metade_descartados_e_espalhada():
    itens = []
    for n in range(40):
        itens.append({"item_id": n, "fonte": "web", "uf": ("PI", "CE")[n % 2], "tecnologia": ("a", "b")[(n // 2) % 2],
                      "selecionado": n < 10, "titulo": "t", "resumo": ""})
    a = escolher_amostra(itens, 8, True, "x")
    assert sum(1 for i in a if i["selecionado"]) == 4 and sum(1 for i in a if not i["selecionado"]) == 4
    assert {(i["uf"], i["tecnologia"]) for i in a if not i["selecionado"]} == {("PI", "a"), ("PI", "b"), ("CE", "a"), ("CE", "b")}


def test_problema_estrutural_continua_invalidando_a_linha():
    it = _artigo(1)
    # categoria invalida, status invalido e recorte temporal incoerente com o ano invalidam (nao sao campo auxiliar)
    assert not _validar([it], [_obj(it, status="quarentena", categoria_motivo="INVENTADA")])[0][0]["valido"]
    assert not _validar([it], [_obj(it, status="talvez")])[0][0]["valido"]
    recente = _artigo(2, ano=2024)
    assert not _validar([recente], [_obj(recente, status="excluido", confianca="alta", categoria_motivo="FORA_DO_RECORTE_TEMPORAL")])[0][0]["valido"]
