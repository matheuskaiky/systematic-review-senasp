"""Montador da Visao Geral: secoes e blocos declarados, cada indicador com definicao, origem, universo, denominador, estado de
validacao e autorizacao; a mesma funcao para os dois bancos; quem nao entrou nunca recebe resultado automatizado preliminar
(classe C2) nem informacao operacional (C3). Funcao pura: recebe os dados ja lidos e quem ve."""
from urllib.parse import quote

import pytest

from dominio import autenticacao as A
from painel import graficos


class _VG:
    """Importa o montador na hora do uso (cada teste falha sozinho enquanto o modulo nao existe)."""
    def __getattr__(self, nome):
        from painel import visao_geral
        return getattr(visao_geral, nome)


VG = _VG()

PRELIMINAR = ("Resultado preliminar: produzido por processamento automatizado e ainda não validado por pesquisadores. "
              "Interprete como exploratório.")
NAO_DIVULGADO = "Resultados automatizados ainda não divulgados."
ORIGENS = {
    "humana": ("Decisão humana", "Decisão registrada por uma pessoa."),
    "modelo": ("Segundo o modelo", "Saída de um modelo de linguagem; ainda não validada por pesquisadores."),
    "verificacao_automatica": ("Conferência automática", "Conferência automática sobre a saída do modelo, sem leitura humana."),
    "calculada": ("Calculado", "Calculado por regra a partir de decisões humanas."),
    "coleta": ("Coleta", "Contagem do que a busca recuperou; não envolve julgamento."),
    "operacao": ("Operação", "Registro técnico das execuções."),
}
REL = "Execuções marcadas para o relatório."
TODAS = "Todas as execuções registradas."
ITENS = "Referências da web e artigos do Google Scholar das consultas configuradas."
ART = "Artigos exibidos na triagem humana."

# ---------------- dados de exemplo (formas reais das leituras) ----------------
RESUMO_REAL = {"consultas_web": 40, "resultados": 400, "urls_unicas": 300, "selecionadas": 120, "paginas_com_texto": 100,
               "classificacoes": 90, "achados": 30, "verificados": 12, "confirmados": 8, "evidencia_ok": 25, "ufs_confirmadas": 5,
               "custo_total_usd": 1.25, "execucoes_nao_concluidas": 2, "chamadas_com_falha": 3}
REVISAO = {"total": 30, "verificados": 12, "confirmados": 8, "descartados": 4, "pendentes_sem_evidencia": 3}
CARTOES = [{"id": "h2", "titulo": "H2", "comando": "python main.py rotular", "href": "/revisao/achados"},
           {"id": "h5", "titulo": "H5", "comando": None, "href": "/literatura/triagem"}]
EXECUCOES = [{"run_id": "20261028_100000_a1b2", "comando": "pipeline-uf", "status": "concluida", "iniciado_em": "2026-10-28T10:00:00+00:00",
              "finalizado_em": "2026-10-28T10:05:00+00:00", "no_relatorio": 1, "custo_usd": 0.5},
             {"run_id": "x y/z", "comando": "classificar", "status": "falhou", "iniciado_em": "2026-10-27T10:00:00+00:00",
              "finalizado_em": None, "no_relatorio": 0, "custo_usd": 0.0}]
RESUMO_VIES = {"custo_total_usd": 0.75, "execucoes_nao_concluidas": 0, "chamadas_com_falha": 1}
AV = {"n_itens": 200, "n_web": 120, "n_scholar": 80, "n_obras": 190, "n_em_ambas_fontes": 10, "n_triados": 180, "n_alta": 40,
      "n_fora": 60}
TRIAGEM = {"total": 70, "incluidos": 20, "excluidos": 15, "pendentes": 35, "ocultos_llm": 9}
RELEVANCIA = {"titulo": "t", "grafico": "<svg>relevancia</svg>", "aviso": None}


def _real(**k):
    d = {"banco": "real", "resumo": dict(RESUMO_REAL), "revisao": dict(REVISAO), "prontidao": [dict(c) for c in CARTOES],
         "execucoes": [dict(e) for e in EXECUCOES], "ultima_coleta": "2026-10-28T10:05:00+00:00", "n_ufs": 27}
    d.update(k)
    return d


def _vies(**k):
    d = {"banco": "vies", "resumo": dict(RESUMO_VIES), "av": dict(AV), "triagem": dict(TRIAGEM), "relevancia": dict(RELEVANCIA),
         "execucoes": [dict(e) for e in EXECUCOES], "ultima_coleta": None}
    d.update(k)
    return d


def _quem(grupo, perms, logado=True):
    return {"logado": logado, "grupo": grupo, "permissoes": frozenset(perms)}


ANONIMO = _quem("Visitante", {"ver_painel"}, logado=False)
ANONIMO_COM_CHAMADAS = _quem("Visitante", {"ver_painel", "ver_chamadas", "ver_nomes_revisores"}, logado=False)
LEITOR = _quem("Leitor", {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"})
TECNICO = _quem("Tecnicos", {"ver_painel", "ver_chamadas"})
TECNICO_CUSTOS = _quem("Tecnicos", {"ver_painel", "ver_chamadas", "ver_custos"})
VERIFICADOR = _quem("Verificadores", {"ver_painel", "verificar_achados"})
TRIADOR = _quem("Triadores", {"ver_painel", "triar_artigos"})
ADMIN = _quem("Administrador", set())


def _secoes(s):
    return [(x["id"], x["titulo"], [b["id"] for b in x["blocos"]]) for x in s]


def _bloco(s, bid):
    return next(b for x in s for b in x["blocos"] if b["id"] == bid)


def _ind(bloco):
    return {i["id"]: i for i in bloco["indicadores"]}


# ======================== estrutura por leitor ========================
TOPO_REAL = ("pesquisa", "A pesquisa", ["identificacao", "cobertura"])
TOPO_VIES = ("pesquisa", "A pesquisa", ["identificacao", "cobertura"])
APROF = ("aprofundar", "Para aprofundar", ["links"])
CASOS = [
    ("real", ANONIMO, [TOPO_REAL, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                       ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]), APROF]),
    ("real", ANONIMO_COM_CHAMADAS, [TOPO_REAL, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                                    ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]), APROF]),
    ("real", LEITOR, [TOPO_REAL, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                      ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]), APROF]),
    ("real", VERIFICADOR, [TOPO_REAL, ("revisao", "Sua revisão", ["fila"]),
                           ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                           ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]), APROF]),
    ("real", TRIADOR, [TOPO_REAL, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                       ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]), APROF]),
    ("real", TECNICO, [TOPO_REAL, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                       ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]),
                       ("operacao", "Operação técnica", ["execucoes"]), APROF]),
    ("real", ADMIN, [TOPO_REAL, ("revisao", "Sua revisão", ["fila"]),
                     ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                     ("qualidade", "Qualidade dos dados", ["conferencia", "prontidao"]),
                     ("operacao", "Operação técnica", ["execucoes"]), APROF]),
    ("vies", ANONIMO, [TOPO_VIES, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                       ("qualidade", "Qualidade dos dados", ["ocultos"]), APROF]),
    ("vies", TRIADOR, [TOPO_VIES, ("revisao", "Sua revisão", ["fila"]),
                       ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                       ("qualidade", "Qualidade dos dados", ["ocultos"]), APROF]),
    ("vies", VERIFICADOR, [TOPO_VIES, ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                           ("qualidade", "Qualidade dos dados", ["ocultos"]), APROF]),
    ("vies", ADMIN, [TOPO_VIES, ("revisao", "Sua revisão", ["fila"]),
                     ("resultados", "Resultados", ["decisoes_humanas", "segundo_o_modelo"]),
                     ("qualidade", "Qualidade dos dados", ["ocultos"]),
                     ("operacao", "Operação técnica", ["execucoes"]), APROF]),
]


@pytest.mark.parametrize("banco,quem,esperado", CASOS,
                         ids=[f"{c[0]}-{c[1]['grupo']}-{'logado' if c[1]['logado'] else 'anonimo'}-{i}" for i, c in enumerate(CASOS)])
def test_secoes_e_blocos_por_leitor(banco, quem, esperado):
    dados = _real() if banco == "real" else _vies()
    assert _secoes(VG.montar(dados, quem)) == esperado


# ======================== contrato de cada indicador ========================
def _esperado(origem, rotulo, valor, den, universo, definicao, classe, formato="numero", exige=()):
    return {"rotulo": rotulo, "valor": valor, "denominador": den, "formato": formato, "origem": origem,
            "origem_rotulo": ORIGENS[origem][0], "validacao": ORIGENS[origem][1], "universo": universo,
            "definicao": definicao, "classe": classe, "exige": tuple(exige)}


INDICADORES_REAL = {
    "cobertura": {
        "consultas_web": _esperado("coleta", "Consultas web", 40, None, REL, "Buscas na web feitas com sucesso pelo provedor de busca.", "C1"),
        "urls_unicas": _esperado("coleta", "URLs únicas", 300, None, REL, "Endereços distintos devolvidos pelas buscas na web.", "C1"),
        "paginas_com_texto": _esperado("coleta", "Páginas com texto", 100, None, REL, "Páginas baixadas das quais o texto foi extraído.", "C1"),
    },
    "fila": {
        "pendentes": _esperado("modelo", "Achados aguardando verificação humana", 18, 30, REL,
                               "Achados apontados pelo modelo que ainda não foram lidos por uma pessoa.", "C2"),
    },
    "decisoes_humanas": {
        "verificados": _esperado("humana", "Achados verificados", 12, 30, REL, "Achados que uma pessoa leu e classificou.", "C1"),
        "confirmados": _esperado("humana", "Confirmados", 8, 12, REL, "Achados verificados que a pessoa manteve como menção válida.", "C1"),
        "descartados": _esperado("humana", "Descartados", 4, 12, REL, "Achados verificados que a pessoa descartou.", "C1"),
        "ufs_confirmadas": _esperado("humana", "UFs com achado confirmado", 5, 27, REL,
                                     "Unidades da federação com pelo menos um achado confirmado por uma pessoa.", "C1"),
    },
    "segundo_o_modelo": {
        "classificacoes": _esperado("modelo", "Classificações", 90, None, REL, "Páginas que o modelo leu e classificou.", "C2"),
        "achados": _esperado("modelo", "Achados apontados pelo modelo", 30, None, REL,
                             "Trechos em que o modelo identificou menção a uma ferramenta de IA na segurança pública.", "C2"),
    },
    "conferencia": {
        "evidencia": _esperado("verificacao_automatica", "Citação localizada no texto", 25, 30, REL,
                               "Achados cuja citação literal foi encontrada no texto da página por conferência automática.", "C2"),
        "sem_evidencia": _esperado("verificacao_automatica", "Sem verificação humana e com a citação não localizada", 3, None, REL,
                                   "Achados ainda não verificados cuja citação a conferência automática não encontrou no texto.", "C2"),
    },
    "execucoes": {
        "nao_concluidas": _esperado("operacao", "Execuções não concluídas", 2, None, TODAS, "Execuções que não terminaram como concluídas.", "C3"),
        "falhas": _esperado("operacao", "Chamadas externas com falha", 3, None, TODAS, "Chamadas aos provedores registradas sem sucesso.", "C3"),
        "gasto": _esperado("operacao", "Gasto registrado", 1.25, None, TODAS, "Soma do custo registrado das chamadas.", "C3",
                           formato="moeda", exige=("ver_custos",)),
    },
}
INDICADORES_VIES = {
    "cobertura": {
        "n_obras": _esperado("coleta", "Obras distintas", 190, None, ITENS,
                             "Itens contados uma vez quando a mesma obra aparece nas duas fontes.", "C1"),
        "n_web": _esperado("coleta", "Referências da web", 120, None, ITENS, "Itens devolvidos pela busca de literatura na web.", "C1"),
        "n_scholar": _esperado("coleta", "Artigos do Scholar", 80, None, ITENS, "Artigos devolvidos pelo Google Scholar.", "C1"),
        "n_em_ambas_fontes": _esperado("coleta", "Nas duas fontes", 10, None, ITENS,
                                       "Obras encontradas na web e no Scholar (mesmo endereço ou mesmo título).", "C1"),
    },
    "fila": {
        "pendentes": _esperado("humana", "Artigos aguardando triagem humana", 35, 70, ART,
                               "Artigos exibidos na triagem que ainda não têm decisão de uma pessoa.", "C1"),
    },
    "decisoes_humanas": {
        "com_triagem_humana": _esperado("humana", "Artigos com triagem humana", 35, 70, ART,
                                        "Artigos que uma pessoa incluiu ou excluiu.", "C1"),
        "incluidos": _esperado("humana", "Incluídos", 20, 35, ART, "Artigos que a pessoa incluiu.", "C1"),
        "excluidos": _esperado("humana", "Excluídos", 15, 35, ART, "Artigos que a pessoa excluiu.", "C1"),
    },
    "segundo_o_modelo": {
        "n_triados": _esperado("modelo", "Com triagem válida do modelo", 180, 200, ITENS,
                               "Itens que o modelo classificou com uma resposta válida (cada item na sua fonte).", "C2"),
        "n_alta": _esperado("modelo", "Relevância alta segundo o modelo", 40, 180, ITENS,
                            "Itens que o modelo julgou de relevância alta.", "C2"),
        "n_fora": _esperado("modelo", "Fora do escopo segundo o modelo", 60, 180, ITENS,
                            "Itens que o modelo julgou fora do escopo da pesquisa.", "C2"),
    },
    "ocultos": {
        "ocultos_llm": _esperado("modelo", "Artigos ocultos pela triagem do modelo", 9, None, "Todos os artigos.",
                                 "Artigos que o modelo excluiu e que ainda não têm decisão de uma pessoa; não aparecem na triagem por padrão.",
                                 "C2"),
    },
    "execucoes": {
        "nao_concluidas": _esperado("operacao", "Execuções não concluídas", 0, None, TODAS, "Execuções que não terminaram como concluídas.", "C3"),
        "falhas": _esperado("operacao", "Chamadas externas com falha", 1, None, TODAS, "Chamadas aos provedores registradas sem sucesso.", "C3"),
        "gasto": _esperado("operacao", "Gasto registrado", 0.75, None, TODAS, "Soma do custo registrado das chamadas.", "C3",
                           formato="moeda", exige=("ver_custos",)),
    },
}


@pytest.mark.parametrize("banco,tabela", [("real", INDICADORES_REAL), ("vies", INDICADORES_VIES)])
def test_cada_indicador_com_o_contrato_inteiro(banco, tabela):
    s = VG.montar(_real() if banco == "real" else _vies(), ADMIN)
    for bid, esperados in tabela.items():
        obtidos = _ind(_bloco(s, bid))
        assert list(obtidos) == list(esperados), bid                                          # ordem dos indicadores
        for iid, esp in esperados.items():
            assert {k: obtidos[iid][k] for k in esp} == esp, (bid, iid)
            assert set(obtidos[iid]) == set(esp) | {"id"}, (bid, iid)                         # nenhum campo a mais


@pytest.mark.parametrize("banco", ["real", "vies"])
def test_classe_do_indicador_igual_a_do_bloco(banco):
    s = VG.montar(_real() if banco == "real" else _vies(), ADMIN)
    for x in s:
        for b in x["blocos"]:
            assert all(i["classe"] == b["classe"] for i in b["indicadores"]), b["id"]


def test_classes_dos_blocos():
    real = {b["id"]: b["classe"] for x in VG.montar(_real(), ADMIN) for b in x["blocos"]}
    assert real == {"identificacao": "C1", "cobertura": "C1", "fila": "C2", "decisoes_humanas": "C1", "segundo_o_modelo": "C2",
                    "conferencia": "C2", "prontidao": "C1", "execucoes": "C3", "links": "C1"}
    vies = {b["id"]: b["classe"] for x in VG.montar(_vies(), ADMIN) for b in x["blocos"]}
    assert vies == {"identificacao": "C1", "cobertura": "C1", "fila": "C1", "decisoes_humanas": "C1", "segundo_o_modelo": "C2",
                    "ocultos": "C2", "execucoes": "C3", "links": "C1"}


# ======================== textos dos blocos ========================
def test_identificacao_real():
    b = _bloco(VG.montar(_real(), LEITOR), "identificacao")
    assert b["titulo"] == "Secretarias Estaduais de Segurança Pública"
    assert b["texto"] == ["Levantamento nas secretarias estaduais de segurança pública. Os números consideram só as execuções "
                          "marcadas para o relatório."]
    assert b["ultima_coleta"] == "2026-10-28T10:05:00+00:00"


def test_identificacao_vies_sem_coleta():
    b = _bloco(VG.montar(_vies(), LEITOR), "identificacao")
    assert b["titulo"] == "Viés Algorítmico e Inteligência Artificial na Segurança Pública"
    assert b["texto"] == ["Busca de literatura científica e cinzenta sobre viés algorítmico: referências da web e artigos do Google "
                          "Scholar, com a triagem do modelo e a triagem humana."]
    assert b["ultima_coleta"] is None


@pytest.mark.parametrize("bid,titulo", [("cobertura", "Cobertura da coleta"), ("decisoes_humanas", "Decisões humanas"),
                                         ("segundo_o_modelo", "Segundo o modelo (preliminar)"),
                                         ("conferencia", "Conferência das citações"), ("prontidao", "Prontidão metodológica"),
                                         ("execucoes", "Execuções e chamadas"), ("links", "Páginas para aprofundar"),
                                         ("fila", "Achados para verificar")])
def test_titulos_dos_blocos_real(bid, titulo):
    assert _bloco(VG.montar(_real(), ADMIN), bid)["titulo"] == titulo


@pytest.mark.parametrize("bid,titulo", [("fila", "Artigos para triar"), ("ocultos", "Artigos ocultos pelo modelo")])
def test_titulos_dos_blocos_vies(bid, titulo):
    assert _bloco(VG.montar(_vies(), ADMIN), bid)["titulo"] == titulo


def test_nota_de_que_sem_verificacao_nao_e_descartado():
    assert _bloco(VG.montar(_real(), LEITOR), "decisoes_humanas")["texto"] == [
        "Achado ainda não verificado não é achado descartado: falta a leitura de uma pessoa."]
    assert _bloco(VG.montar(_vies(), LEITOR), "decisoes_humanas")["texto"] == [
        "Artigo ainda sem triagem humana não é artigo excluído: falta a decisão de uma pessoa."]


@pytest.mark.parametrize("banco,bid", [("real", "segundo_o_modelo"), ("real", "conferencia"), ("vies", "segundo_o_modelo"),
                                       ("vies", "ocultos")])
def test_blocos_c2_levam_o_aviso_de_preliminar_para_quem_entrou(banco, bid):
    b = _bloco(VG.montar(_real() if banco == "real" else _vies(), LEITOR), bid)
    assert b["aviso"] == PRELIMINAR


def test_prontidao_tem_o_texto_e_os_metadados_dos_cartoes():
    """Os cartoes de prontidao compartilham os metadados do bloco: origem calculada, universo e definicao."""
    b = _bloco(VG.montar(_real(), LEITOR), "prontidao")
    assert b["texto"] == ["O que falta rotular por uma pessoa para destravar cada análise."]
    assert (b["origem"], b["origem_rotulo"], b["validacao"]) == ("calculada", *ORIGENS["calculada"])
    assert b["universo"] == REL
    assert b["definicao"] == ("Cada cartão compara as decisões humanas já registradas com o mínimo que a análise estatística exige.")


@pytest.mark.parametrize("quem,hrefs", [(LEITOR, [None, None]), (VERIFICADOR, ["/revisao/achados", None]),
                                        (TRIADOR, [None, "/literatura/triagem"]), (ADMIN, ["/revisao/achados", "/literatura/triagem"])],
                         ids=["leitor", "verificador", "triador", "admin"])
def test_links_dos_cartoes_seguem_a_regra_das_filas(quem, hrefs):
    assert [c["href"] for c in _bloco(VG.montar(_real(), quem), "prontidao")["cartoes"]] == hrefs


@pytest.mark.parametrize("bid", ["identificacao", "cobertura", "fila", "decisoes_humanas", "segundo_o_modelo", "conferencia",
                                 "execucoes", "links"])
def test_blocos_sem_origem_propria(bid):
    """Origem de bloco so na prontidao (os demais blocos tem a origem em cada indicador)."""
    b = _bloco(VG.montar(_real(), ADMIN), bid)
    assert (b["origem"], b["origem_rotulo"], b["validacao"], b["universo"], b["definicao"]) == (None, None, None, None, None)


# ======================== quem nao entrou: D135 ========================
@pytest.mark.parametrize("banco", ["real", "vies"])
@pytest.mark.parametrize("quem", [ANONIMO, ANONIMO_COM_CHAMADAS], ids=["visitante", "visitante-com-chamadas"])
def test_anonimo_nao_recebe_c2_nem_c3(banco, quem):
    s = VG.montar(_real() if banco == "real" else _vies(), quem)
    for x in s:
        for b in x["blocos"]:
            assert b["classe"] != "C3"
            if b["classe"] == "C2":
                assert (b["indicadores"], b["grafico"], b["vazio"], b["acoes"], b["cartoes"], b["execucoes"], b["texto"]) == (
                    [], None, None, [], None, None, [])
                assert b["aviso"] == NAO_DIVULGADO
            assert all(i["classe"] == "C1" for i in b["indicadores"])


def test_anonimo_ve_as_decisoes_humanas_e_a_prontidao_sem_comando():
    s = VG.montar(_real(), ANONIMO_COM_CHAMADAS)
    assert list(_ind(_bloco(s, "decisoes_humanas"))) == ["verificados", "confirmados", "descartados", "ufs_confirmadas"]
    assert [c["comando"] for c in _bloco(s, "prontidao")["cartoes"]] == [None, None]


# ======================== autorizacao: funcoes do servidor ========================
def test_gasto_so_com_ver_custos():
    assert "gasto" not in _ind(_bloco(VG.montar(_real(), TECNICO), "execucoes"))
    assert "gasto" in _ind(_bloco(VG.montar(_real(), TECNICO_CUSTOS), "execucoes"))


def test_linhas_das_execucoes():
    b = _bloco(VG.montar(_real(), TECNICO_CUSTOS), "execucoes")
    assert b["execucoes"] == [
        {"run_id": "20261028_100000_a1b2", "href": "/execucoes/20261028_100000_a1b2", "comando": "pipeline-uf", "status": "concluida",
         "iniciado_em": "2026-10-28T10:00:00+00:00", "custo_usd": 0.5, "no_relatorio": "dentro"},
        {"run_id": "x y/z", "href": "/execucoes/" + quote("x y/z", safe=""), "comando": "classificar", "status": "falhou",
         "iniciado_em": "2026-10-27T10:00:00+00:00", "custo_usd": 0.0, "no_relatorio": "fora"}]
    sem = _bloco(VG.montar(_real(), TECNICO), "execucoes")
    assert [e["custo_usd"] for e in sem["execucoes"]] == [None, None] and sem["mostrar_custo"] is False
    assert b["mostrar_custo"] is True


@pytest.mark.parametrize("banco,comando", [("real", "python main.py pipeline-uf --ufs PI --limite 5"),
                                           ("vies", "python main.py buscar-literatura --conjunto A --limite 5 --banco vies")])
def test_comando_inicial_so_na_operacao(banco, comando):
    dados = (_real if banco == "real" else _vies)(execucoes=[])
    b = _bloco(VG.montar(dados, TECNICO), "execucoes")
    assert b["execucoes"] == [] and b["comando_inicial"] == comando
    for x in VG.montar(dados, LEITOR):
        for bl in x["blocos"]:
            assert bl.get("comando_inicial") is None


def test_prontidao_com_comando_so_com_ver_chamadas():
    assert [c["comando"] for c in _bloco(VG.montar(_real(), TECNICO), "prontidao")["cartoes"]] == ["python main.py rotular", None]
    assert [c["comando"] for c in _bloco(VG.montar(_real(), LEITOR), "prontidao")["cartoes"]] == [None, None]


def test_dados_de_entrada_nao_sao_alterados():
    dados = _real()
    VG.montar(dados, LEITOR)
    assert dados == _real()


@pytest.mark.parametrize("banco,n,acao,aviso", [
    ("real", None, {"texto": "Continuar a revisão (18)", "href": "/revisao/achados"}, None),
    ("real", 0, None, "Nada pendente."),
    ("vies", None, {"texto": "Continuar a triagem (35)", "href": "/literatura/triagem"}, None),
    ("vies", 0, None, "Nada pendente."),
])
def test_acao_da_fila(banco, n, acao, aviso):
    if banco == "real":
        dados = _real() if n is None else _real(revisao={**REVISAO, "verificados": REVISAO["total"]})
        quem = VERIFICADOR
    else:
        dados = _vies() if n is None else _vies(triagem={**TRIAGEM, "pendentes": 0})
        quem = TRIADOR
    b = _bloco(VG.montar(dados, quem), "fila")
    assert b["acoes"] == ([acao] if acao else []) and b["aviso"] == aviso


def test_acao_da_conferencia():
    b = _bloco(VG.montar(_real(), LEITOR), "conferencia")
    assert b["acoes"] == [{"texto": "Ver esses achados", "href": "/achados?verificacao=pendente&evidencia=0"}]
    b0 = _bloco(VG.montar(_real(revisao={**REVISAO, "pendentes_sem_evidencia": 0}), LEITOR), "conferencia")
    assert b0["acoes"] == []


def test_links_para_aprofundar():
    real = _bloco(VG.montar(_real(), LEITOR), "links")["acoes"]
    assert real == [{"texto": t, "href": h} for t, h in (("PRISMA", "/literatura/prisma"), ("Estados", "/estados"), ("Achados", "/achados"),
                                                        ("Análises", "/analises"), ("Metodologia", "/metodologia"),
                                                        ("Sobre os dados", "/sobre"))]
    vies = _bloco(VG.montar(_vies(), LEITOR), "links")["acoes"]
    assert vies == [{"texto": t, "href": h} for t, h in (("Observatório", "/observatorio"), ("Referências", "/literatura/referencias"),
                                                        ("PRISMA", "/literatura/prisma"), ("Análises", "/analises"),
                                                        ("Validação da triagem", "/validacao"), ("Metodologia", "/metodologia"),
                                                        ("Sobre os dados", "/sobre"))]


def test_acoes_e_blocos_seguem_as_funcoes_do_servidor(monkeypatch):
    """Trocar pode/pode_acessar muda blocos, indicadores e acoes: nenhuma regra copiada."""
    monkeypatch.setattr(A, "pode", lambda grupo, perms, exigida: exigida != "ver_custos")
    s = VG.montar(_real(), TECNICO_CUSTOS)
    assert "gasto" not in _ind(_bloco(s, "execucoes"))
    monkeypatch.setattr(A, "pode", lambda grupo, perms, exigida: True)
    monkeypatch.setattr(A, "pode_acessar", lambda grupo, perms, metodo, caminho: caminho not in ("/estados", "/revisao/achados"))
    s = VG.montar(_real(), LEITOR)
    assert [a["href"] for a in _bloco(s, "links")["acoes"]] == ["/literatura/prisma", "/achados", "/analises", "/metodologia", "/sobre"]
    assert _bloco(s, "fila")["acoes"] == []                       # fila sem o GET da pagina: sem botao
    assert _bloco(s, "execucoes")["execucoes"][0]["href"] == "/execucoes/20261028_100000_a1b2"


def test_fila_exige_tambem_o_post_da_decisao(monkeypatch):
    chamadas = []
    original = A.pode_acessar

    def espiao(grupo, perms, metodo, caminho):
        chamadas.append((metodo, caminho))
        return original(grupo, perms, metodo, caminho)
    monkeypatch.setattr(A, "pode_acessar", espiao)
    VG.montar(_real(), VERIFICADOR)
    assert ("GET", "/revisao/achados") in chamadas and ("POST", "/achados/1/verificar") in chamadas
    chamadas.clear()
    VG.montar(_vies(), TRIADOR)
    assert ("GET", "/literatura/triagem") in chamadas and ("POST", "/literatura/artigos/1/triar") in chamadas
    monkeypatch.setattr(A, "pode_acessar", lambda g, p, metodo, caminho: metodo == "GET")
    assert _bloco(VG.montar(_real(), VERIFICADOR), "fila")["acoes"] == []


def test_link_da_execucao_some_sem_a_rota(monkeypatch):
    monkeypatch.setattr(A, "pode_acessar", lambda g, p, metodo, caminho: not caminho.startswith("/execucoes/"))
    assert [e["href"] for e in _bloco(VG.montar(_real(), TECNICO), "execucoes")["execucoes"]] == [None, None]


def test_toda_acao_e_todo_link_passam_por_pode_seguir(monkeypatch):
    """A regra de seguir um endereco (GET e, nas filas, o POST da decisao) e a do menu: trocar navegacao.pode_seguir muda tudo."""
    from painel import navegacao
    vistos = []

    def nunca(href, pode):
        vistos.append(href)
        return False
    monkeypatch.setattr(navegacao, "pode_seguir", nunca)
    s = VG.montar(_real(), ADMIN)
    for x in s:
        for b in x["blocos"]:
            assert b["acoes"] == [], b["id"]
    assert [c["href"] for c in _bloco(s, "prontidao")["cartoes"]] == [None, None]
    assert [e["href"] for e in _bloco(s, "execucoes")["execucoes"]] == [None, None]
    assert {"/revisao/achados", "/literatura/triagem", "/estados", "/analises", "/execucoes/20261028_100000_a1b2"} <= set(vistos)


@pytest.mark.parametrize("extra", [{}, {"nome": "Fulano"}, {"nome": "Outra Pessoa"}, {"nome": None}])
def test_saida_nao_depende_do_nome(extra):
    """Sem atividade por nome de exibicao (D141, Q-P3): chaves a mais em `quem` nao mudam nada."""
    assert VG.montar(_real(), {**VERIFICADOR, **extra}) == VG.montar(_real(), VERIFICADOR)


def test_nenhum_teste_de_nome_de_grupo(monkeypatch):
    """Um grupo de nome qualquer com as mesmas permissoes recebe a mesma pagina."""
    outro = _quem("Qualquer Nome", TECNICO_CUSTOS["permissoes"])
    assert VG.montar(_real(), outro) == VG.montar(_real(), TECNICO_CUSTOS)


# ======================== graficos: os mesmos de hoje ========================
def test_graficos_do_banco_real_iguais_aos_da_rota_atual():
    s = VG.montar(_real(), LEITOR)
    r, rev = RESUMO_REAL, REVISAO
    etapas = [("Consultas web", r["consultas_web"]), ("Resultados", r["resultados"]), ("URLs únicas", r["urls_unicas"]),
              ("Páginas selecionadas", r["selecionadas"]), ("Páginas com texto", r["paginas_com_texto"]),
              ("Classificações", r["classificacoes"]), ("Achados", r["achados"]), ("Achados verificados", r["verificados"]),
              ("Confirmados", r["confirmados"])]
    from painel import formatacao as fmt
    funil = graficos.barras_horizontais(etapas, "Funil do levantamento nas secretarias",
                                        "Quantidade em cada etapa, da busca web aos achados confirmados", fmt.numero)
    barra = graficos.barra_empilhada([(rev["confirmados"], "be-conf", "Confirmados"), (rev["descartados"], "be-desc", "Descartados")],
                                     rev["total"], f"{rev['confirmados']} confirmados, {rev['descartados']} descartados, "
                                                   f"{rev['total'] - rev['verificados']} pendentes")
    assert _bloco(s, "segundo_o_modelo")["grafico"] == funil
    assert _bloco(s, "decisoes_humanas")["grafico"] == barra


def test_graficos_do_vies():
    s = VG.montar(_vies(), LEITOR)
    t = TRIAGEM
    barra = graficos.barra_empilhada([(t["incluidos"], "be-conf", "Incluídos"), (t["excluidos"], "be-desc", "Excluídos")], t["total"],
                                     f"{t['incluidos']} incluídos, {t['excluidos']} excluídos, {t['pendentes']} pendentes")
    assert _bloco(s, "decisoes_humanas")["grafico"] == barra
    assert _bloco(s, "segundo_o_modelo")["grafico"] == "<svg>relevancia</svg>"
    vazio = VG.montar(_vies(relevancia={"titulo": "t", "grafico": None, "aviso": "Nenhum item com triagem válida."}), LEITOR)
    b = _bloco(vazio, "segundo_o_modelo")
    assert b["grafico"] is None and b["vazio"] == "Nenhum item com triagem válida."


def test_chaves_de_todo_bloco():
    for x in VG.montar(_real(), ADMIN) + VG.montar(_vies(), ADMIN):
        assert set(x) == {"id", "titulo", "blocos"}
        for b in x["blocos"]:
            assert set(b) == {"id", "titulo", "classe", "texto", "indicadores", "grafico", "vazio", "acoes", "aviso", "cartoes",
                              "execucoes", "mostrar_custo", "comando_inicial", "ultima_coleta", "origem", "origem_rotulo",
                              "validacao", "universo", "definicao"}, b["id"]


# ======================== leitura: data da ultima coleta concluida ========================
def _leitura_com(demo, tmp_path, linhas):  # noqa: F811
    import shutil
    import sqlite3
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    banco = tmp_path / "copia.db"
    shutil.copy(demo[0], banco)
    with sqlite3.connect(banco) as conn:
        conn.execute("UPDATE execucoes SET no_relatorio = 0")
        for run_id, status, no_rel, fim in linhas:
            conn.execute("INSERT INTO execucoes (run_id, comando, status, iniciado_em, finalizado_em, no_relatorio, config_hash, config_json) "
                         "VALUES (?, 'teste', ?, '2026-01-01T00:00:00+00:00', ?, ?, 'h', '{}')", (run_id, status, fim, no_rel))
    return LeituraPainelSQLite(banco)


@pytest.mark.parametrize("linhas,esperado", [
    ([], None),
    ([("r1", "concluida", 1, "2026-02-01T10:00:00+00:00")], "2026-02-01T10:00:00+00:00"),
    ([("r1", "concluida", 1, "2026-02-01T10:00:00+00:00"), ("r2", "concluida", 0, "2026-03-01T10:00:00+00:00"),
      ("r3", "falhou", 1, "2026-04-01T10:00:00+00:00"), ("r4", "concluida", 1, None)], "2026-02-01T10:00:00+00:00"),
    ([("r1", "concluida", 1, "2026-02-01T10:00:00+00:00"), ("r2", "concluida", 1, "2026-02-03T09:00:00+00:00")],
     "2026-02-03T09:00:00+00:00"),
], ids=["nenhuma", "uma", "so-concluida-no-relatorio-com-fim", "a-mais-recente"])
def test_ultima_coleta_concluida(demo, tmp_path, linhas, esperado):  # noqa: F811
    assert _leitura_com(demo, tmp_path, linhas).ultima_coleta_concluida() == esperado


from test_painel import demo  # noqa: E402,F401
