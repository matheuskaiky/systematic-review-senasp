"""As views de metricas do relatorio, conferidas contra bancos sinteticos (ver tests/dados_metricas.py)."""
import logging

import pytest

from dados_metricas import _id_artigo, _novo_run, construir_academico, construir_web


@pytest.fixture(scope="module")
def ac(tmp_path_factory):
    repo, _ = construir_academico(tmp_path_factory.mktemp("ac") / "ac.db")
    return repo


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    logging.disable(logging.CRITICAL)
    try:
        repo, _ = construir_web(tmp_path_factory.mktemp("web"))
    finally:
        logging.disable(logging.NOTSET)
    return repo


def _linhas(repo, view, where="", ordem=""):
    sql = f"SELECT * FROM {view} {where} {ordem}"
    return [dict(r) for r in repo.conn.execute(sql).fetchall()]


def _um(repo, view, where):
    linhas = _linhas(repo, view, where)
    assert len(linhas) == 1, linhas
    return linhas[0]


# ---------- termos ----------
def test_v_termos_vem_do_snapshot(ac):
    t = _um(ac, "v_termos", "WHERE termo_id='T25'")
    assert (t["idioma"], t["query"], t["grupo"]) == ("en", '"facial recognition"', "reconhecimento_identificacao")
    assert _um(ac, "v_termos", "WHERE termo_id='T05'")["idioma"] == "pt"
    assert len(_linhas(ac, "v_termos")) == 46


def test_rendimento_termo_traz_resultados_exclusivos_e_precisao(ac):
    t01 = _um(ac, "v_rendimento_termo", "WHERE termo_id='T01'")
    assert (t01["n_requisicoes"], t01["n_paginas"], t01["total_reportado_aprox"]) == (2, 2, 1500)
    assert (t01["n_artigos"], t01["n_exclusivos"], t01["pct_exclusivos"]) == (8, 6, 75.0)
    assert (t01["n_incluidos"], t01["n_excluidos"], t01["n_pendentes"]) == (2, 3, 3)
    assert t01["taxa_inclusao_pct"] == 40.0 and t01["cobertura_pct"] == 0.53
    assert t01["n_incluidos_exclusivos"] == 0            # tudo que T01 inclui outro termo tambem traz
    assert (t01["idioma"], t01["grupo"]) == ("pt", "reconhecimento_identificacao")


def test_rendimento_termo_demais_termos(ac):
    por_termo = {r["termo_id"]: r for r in _linhas(ac, "v_rendimento_termo")}
    assert (por_termo["T02"]["n_artigos"], por_termo["T02"]["n_incluidos"], por_termo["T02"]["taxa_inclusao_pct"],
            por_termo["T02"]["n_incluidos_exclusivos"]) == (3, 3, 100.0, 1)
    assert (por_termo["T05"]["n_incluidos"], por_termo["T05"]["taxa_inclusao_pct"], por_termo["T05"]["n_pendentes"]) == (0, 0.0, 1)
    assert (por_termo["T25"]["n_artigos"], por_termo["T25"]["n_incluidos"], por_termo["T25"]["taxa_inclusao_pct"],
            por_termo["T25"]["n_incluidos_exclusivos"]) == (3, 2, 66.7, 1)


def test_rendimento_termo_ordena_pelos_incluidos(ac):
    assert [r["termo_id"] for r in _linhas(ac, "v_rendimento_termo")] == ["T02", "T25", "T01", "T05"]


def test_pares_de_termos_normalizam_a_sobreposicao(ac):
    p = _um(ac, "v_pares_termos", "WHERE termo_a='T01' AND termo_b='T02'")
    assert (p["n_a"], p["n_b"], p["n_em_comum"], p["n_uniao"]) == (8, 3, 2, 9)
    assert p["jaccard"] == 0.222 and p["pct_do_menor_contido"] == 66.7
    assert (p["n_incluidos_em_comum"], p["n_incluidos_uniao"]) == (2, 3)     # A1 A2 | A1 A2 A9
    outro = _um(ac, "v_pares_termos", "WHERE termo_a='T05' AND termo_b='T25'")
    assert (outro["jaccard"], outro["pct_do_menor_contido"], outro["n_incluidos_em_comum"]) == (0.25, 50.0, 0)
    assert len(_linhas(ac, "v_pares_termos")) == 4                        # so pares que se sobrepoem
    assert _linhas(ac, "v_pares_termos")[0]["termo_a"] == "T05"           # maior Jaccard primeiro


def test_ganho_por_idioma(ac):
    g = {r["achado_por"]: r for r in _linhas(ac, "v_ganho_por_idioma")}
    assert (g["apenas_pt"]["n_artigos"], g["apenas_pt"]["n_incluidos"]) == (9, 2)
    assert (g["apenas_en"]["n_artigos"], g["apenas_en"]["n_incluidos"]) == (1, 1)
    assert (g["ambos"]["n_artigos"], g["ambos"]["n_incluidos"], g["ambos"]["n_excluidos"]) == (2, 1, 1)


def test_rendimento_por_pagina(ac):
    p1, p2 = _linhas(ac, "v_rendimento_por_pagina")
    assert (p1["pagina"], p1["n_ocorrencias"], p1["n_artigos"], p1["n_incluidos"], p1["n_excluidos"]) == (1, 14, 10, 7, 5)
    assert p1["taxa_inclusao_pct"] == 58.3
    assert (p2["pagina"], p2["n_ocorrencias"], p2["n_incluidos"], p2["taxa_inclusao_pct"]) == (2, 2, 0, None)


def test_curva_de_descoberta_acumula_os_artigos_novos(ac):
    linhas = _linhas(ac, "v_curva_descoberta", ordem="ORDER BY chamada_id")
    assert [l["n_novos"] for l in linhas] == [6, 2, 1, 2, 1]
    assert [l["novos_acumulado"] for l in linhas] == [6, 8, 9, 11, 12]
    assert [l["pct_novos"] for l in linhas] == [100.0, 100.0, 33.3, 100.0, 33.3]


# ---------- PRISMA e registro de buscas ----------
def test_prisma(ac):
    v = {r["metrica"]: r["valor"] for r in _linhas(ac, "v_prisma")}
    assert v["execucoes de busca academica"] == 1
    assert v["Google Scholar: registros retornados"] == 16
    assert v["Google Scholar: duplicatas entre termos removidas"] == 4 and v["Google Scholar: artigos unicos"] == 12
    assert v["buscas manuais: registros retornados (contagem informada)"] == 150
    assert v["buscas manuais: apos filtro da base (contagem informada)"] == 60
    assert v["buscas manuais: selecionados (contagem informada)"] == 15
    assert v["buscas manuais: artigos importados (por base)"] == 0
    assert v["registros (artigo x fonte) apos remover duplicatas entre termos"] == 12
    assert v["duplicatas entre fontes removidas"] == 0 and v["artigos unicos para triagem"] == 12
    assert v["avaliados por titulo e resumo"] == 8 and v["excluidos por titulo e resumo"] == 4
    assert v["incluidos por titulo e resumo"] == 4 and v["pendentes de titulo e resumo"] == 4
    assert v["avaliados por texto completo"] == 0 and v["aguardando texto completo"] == 4
    assert v["incluidos no estudo (texto completo)"] == 0
    assert v[REMOVIDOS] == 0                       # sem veredito da triagem de escopo nada e removido por ferramenta automatica


# ---------- PRISMA: removidos por ferramenta automatica (triagem de escopo do modelo) ----------
REMOVIDOS = "removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)"


@pytest.fixture
def fluxo(tmp_path):
    """Banco do Scholar com 12 artigos unicos: 4 incluidos, 4 excluidos e 1 pendente por pessoa; 3 sem linha de triagem."""
    repo, run_id = construir_academico(tmp_path / "fluxo.db")
    return repo, run_id


def _veredito(repo, run_id, n, status, valido=1, fonte="artigo"):
    item = _id_artigo(repo, n) if fonte == "artigo" else n
    repo.salvar_triagem_escopo(run_id, None, "v-teste", [{"fonte": fonte, "item_id": item, "uf": "", "status": status, "valido": valido}])
    repo.confirmar()


def _fluxo(repo):
    return {r["metrica"]: r["valor"] for r in _linhas(repo, "v_prisma")}


def _confere_aritmetica(v):
    """O fluxo fecha: unicos = removidos + para triagem; para triagem = avaliados + pendentes; avaliados = incluidos + excluidos."""
    assert v["registros (artigo x fonte) apos remover duplicatas entre termos"] - v["duplicatas entre fontes removidas"] == \
        v[REMOVIDOS] + v["artigos unicos para triagem"]
    assert v["artigos unicos para triagem"] == v["avaliados por titulo e resumo"] + v["pendentes de titulo e resumo"]
    assert v["avaliados por titulo e resumo"] == v["incluidos por titulo e resumo"] + v["excluidos por titulo e resumo"]


def test_prisma_sem_veredito_do_modelo_nao_remove_ninguem(fluxo):
    v = _fluxo(fluxo[0])
    assert v[REMOVIDOS] == 0 and v["artigos unicos para triagem"] == 12 and v["pendentes de titulo e resumo"] == 4
    _confere_aritmetica(v)


def test_prisma_excluido_pelo_modelo_sem_decisao_humana_sai_da_base_da_triagem(fluxo):
    repo, run_id = fluxo
    for n in (7, 8, 6):                  # 7 e 8 sem linha de triagem; 6 com linha `pendente`: nenhuma decisao humana
        _veredito(repo, run_id, n, "excluido")
    v = _fluxo(repo)
    assert v[REMOVIDOS] == 3
    assert v["Google Scholar: artigos unicos"] == 12 and v["artigos unicos para triagem"] == 9
    assert v["avaliados por titulo e resumo"] == 8 and v["pendentes de titulo e resumo"] == 1
    _confere_aritmetica(v)
    ordens = {r["metrica"]: r["ordem"] for r in _linhas(repo, "v_prisma")}
    assert ordens["duplicatas entre fontes removidas"] < ordens[REMOVIDOS] < ordens["artigos unicos para triagem"]
    fases = {r["metrica"]: r["fase"] for r in _linhas(repo, "v_prisma")}
    assert fases[REMOVIDOS] == "identificacao" and fases["artigos unicos para triagem"] == "triagem"
    assert sorted(ordens.values()) == list(range(1, 21))


def test_prisma_excluido_pelo_modelo_com_decisao_humana_nao_e_removido(fluxo):
    repo, run_id = fluxo
    _veredito(repo, run_id, 1, "excluido")      # incluido por uma pessoa
    _veredito(repo, run_id, 3, "excluido")      # excluido por uma pessoa
    _veredito(repo, run_id, 7, "excluido")      # sem decisao humana
    v = _fluxo(repo)
    assert v[REMOVIDOS] == 1 and v["artigos unicos para triagem"] == 11
    assert v["avaliados por titulo e resumo"] == 8 and v["incluidos por titulo e resumo"] == 4 and v["pendentes de titulo e resumo"] == 3
    _confere_aritmetica(v)


def test_prisma_so_vale_o_veredito_atual_valido_de_artigo(fluxo):
    repo, run_id = fluxo
    _veredito(repo, run_id, 7, "excluido", valido=0)        # conferencia falhou: nao vale
    _veredito(repo, run_id, 8, "quarentena")
    _veredito(repo, run_id, 11, "elegivel")
    _veredito(repo, run_id, 5, "excluido", fonte="web")     # veredito de resultado web nao pertence a artigo
    assert _fluxo(repo)[REMOVIDOS] == 0
    # o veredito mais recente (maior id) vale: um artigo excluido que depois ficou elegivel volta
    _veredito(repo, run_id, 7, "excluido")                  # mesma execucao: substitui a linha invalida
    assert _fluxo(repo)[REMOVIDOS] == 1
    outra = _novo_run(repo, "triar-escopo")
    _veredito(repo, outra, 7, "elegivel")
    assert _fluxo(repo)[REMOVIDOS] == 0
    _confere_aritmetica(_fluxo(repo))


def test_prisma_ignora_veredito_de_artigo_de_execucao_fora_do_relatorio(fluxo):
    repo, run_id = fluxo
    _veredito(repo, run_id, 7, "excluido")
    assert _fluxo(repo)[REMOVIDOS] == 1
    repo.conn.execute("UPDATE execucoes SET no_relatorio = 0 WHERE run_id = ?", (run_id,))
    repo.confirmar()
    v = _fluxo(repo)                                         # os artigos sumiram do relatorio: nada a remover
    assert v[REMOVIDOS] == 0 and v["artigos unicos para triagem"] == 0


def test_prisma_banco_vazio(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    repo = RepositorioSQLite(tmp_path / "vazio.db")
    assert all(r["valor"] == 0 for r in _linhas(repo, "v_prisma"))
    for view in ("v_rendimento_termo", "v_pares_termos", "v_curva_descoberta", "v_registro_buscas",
                 "v_rendimento_busca_web", "v_precisao_llm", "v_qualidade_classificacao", "v_extracao"):
        assert _linhas(repo, view) == []
    e = _linhas(repo, "v_eficiencia")[0]
    assert e["custo_total_usd"] == 0 and e["custo_por_fonte_confirmada_usd"] is None


def test_motivos_de_exclusao(ac):
    assert {(r["etapa"], r["motivo"]): r["n"] for r in _linhas(ac, "v_motivos_exclusao")} == {
        ("titulo_resumo", "fora do escopo"): 2, ("titulo_resumo", "sem IA"): 2}


def test_registro_de_buscas(ac):
    linhas = _linhas(ac, "v_registro_buscas")
    scholar = [l for l in linhas if l["fonte"].startswith("Google Scholar")]
    assert len(scholar) == 5 and len(linhas) == 7
    t25 = next(l for l in scholar if l["termo_id"] == "T25")
    assert t25["string_busca"] == '"facial recognition"'
    assert t25["filtros"] == "idioma=en; por_pagina=20; ano_inicial=2019; ano_final="
    assert (t25["pagina"], t25["n_resultados"], t25["total_reportado_aprox"], t25["sucesso"]) == (1, 3, 300, 1)
    assert t25["config_hash"] and t25["run_id"] and t25["data_busca"]
    manuais = {l["fonte"]: l for l in linhas if not l["fonte"].startswith("Google Scholar")}
    assert manuais["IEEE"]["n_resultados"] == 100 and manuais["ACM"]["string_busca"] == '"facial recognition"'


# ---------- busca web ----------
def test_rendimento_busca_web_por_modelo_perfil_tecnologia(web):
    linhas = _linhas(web, "v_rendimento_busca_web")
    assert len(linhas) == 12                                                   # 2 modelos x 6 tecnologias (RC14)
    m01 = _um(web, "v_rendimento_busca_web", "WHERE modelo_id='M01' AND tecnologia='reconhecimento_facial'")
    assert m01["perfil"] == "oficial"
    assert (m01["n_consultas_com_resultado"], m01["n_urls"], m01["pct_oficiais"]) == (1, 3, 100.0)
    assert (m01["n_urls_com_achado"], m01["n_urls_verificadas"], m01["n_urls_confirmadas"]) == (3, 3, 2)
    m02 = _um(web, "v_rendimento_busca_web", "WHERE modelo_id='M02' AND tecnologia='reconhecimento_facial'")
    assert m02["perfil"] == "geral"
    assert (m02["n_urls"], m02["pct_oficiais"], m02["n_urls_com_achado"]) == (2, 50.0, 2)
    assert (m02["n_urls_verificadas"], m02["n_urls_confirmadas"]) == (1, 1)


def test_sobreposicao_entre_modelos_de_consulta(web):
    s = _um(web, "v_sobreposicao_modelos", "")
    assert (s["modelo_a"], s["modelo_b"], s["n_urls_a"], s["n_urls_b"]) == ("M01", "M02", 3, 2)
    assert (s["n_em_comum"], s["n_uniao"], s["jaccard"]) == (1, 4, 0.25)
    assert (s["confirmadas_so_em_a"], s["confirmadas_so_em_b"]) == (1, 0)       # gov/1 so no M01; blog/4 nao verificado


def test_rendimento_por_posicao(web):
    p = {r["posicao"]: r for r in _linhas(web, "v_rendimento_por_posicao")}
    assert (p[1]["n_resultados"], p[1]["n_verificados"], p[1]["n_confirmados"], p[1]["taxa_confirmacao_pct"]) == (12, 12, 12, 100.0)   # RC14: 12 consultas (6 tecnologias)
    assert (p[2]["n_resultados"], p[2]["n_verificados"], p[2]["n_confirmados"], p[2]["taxa_confirmacao_pct"]) == (12, 6, 0, 0.0)
    assert (p[3]["n_resultados"], p[3]["taxa_confirmacao_pct"]) == (6, 100.0)


def test_status_por_url(web):
    s = {(r["n_achados"], r["verificado"], r["confirmado"]) for r in _linhas(web, "v_status_url")}
    assert s == {(1, 1, 1), (1, 1, 0), (1, 0, 0)}                               # confirmado, descartado, nao verificado


def test_consultas_vazias(web):
    linhas = _linhas(web, "v_consultas_vazias")
    assert len(linhas) == 12 and all(l["n_sem_resultado"] == 0 and l["n_consultas"] == 1 for l in linhas)
    assert {l["modelo_id"] for l in linhas} == {"M01", "M02"}
    assert "reconhecimento_facial" in {l["tecnologia"] for l in linhas}


def test_cobertura_uf_tecnologia(web):
    linhas = _linhas(web, "v_cobertura_uf_tecnologia")
    assert [(l["uf"], l["tecnologia"], l["status_final"], l["n_fontes"], l["n_fontes_oficiais"]) for l in linhas] == [
        ("PI", "reconhecimento_facial", "em_uso", 1, 1), ("PI", "reconhecimento_facial", "piloto", 1, 1)]


# ---------- qualidade da classificacao ----------
def test_precisao_do_llm_por_faixa(web):
    por = {(r["confianca"], r["origem_texto"], r["evidencia_confere"], r["fonte_oficial"]): r for r in _linhas(web, "v_precisao_llm")}
    pagina = por[("alta", "pagina", 1, 1)]
    assert (pagina["n_achados"], pagina["n_verificados"], pagina["n_confirmados"], pagina["taxa_confirmacao_pct"]) == (3, 3, 2, 66.7)
    snippet = por[("baixa", "snippet", 0, 0)]                                  # blog: extracao falhou, texto do snippet
    assert (snippet["n_achados"], snippet["n_verificados"], snippet["taxa_confirmacao_pct"]) == (1, 0, None)


def test_correcoes_humanas(web):
    c = {(r["status_reportado"], r["status_final"]): (r["manteve"], r["n"]) for r in _linhas(web, "v_correcoes_humanas")}
    assert c == {("em_uso", "em_uso"): (1, 1), ("em_uso", "descartado"): (0, 1), ("em_uso", "piloto"): (0, 1)}


def test_qualidade_da_classificacao_por_origem(web):
    q = {r["origem_texto"]: r for r in _linhas(web, "v_qualidade_classificacao")}
    assert (q["pagina"]["n_classificacoes"], q["pagina"]["pct_json_valido"], q["pagina"]["pct_relevante"]) == (3, 100.0, 100.0)
    assert (q["pagina"]["achados_por_classificacao"], q["pagina"]["pct_achados_evidencia_ok"]) == (1.0, 100.0)
    assert (q["snippet"]["n_classificacoes"], q["snippet"]["pct_achados_evidencia_ok"]) == (1, 0.0)
    assert (q["pagina"]["tokens_entrada"], q["pagina"]["tokens_saida"], q["pagina"]["custo_usd"]) == (300, 60, 0.0)
    assert q["pagina"]["classificador"] == "simulado" and q["pagina"]["prompt_versao"] == "v-teste"


def test_extracao_por_tipo_de_fonte(web):
    e = {(r["resultado"], r["motivo"], r["fonte_oficial"]): r for r in _linhas(web, "v_extracao")}
    assert (e[("ok", "ok", 1)]["n_urls"], e[("ok", "ok", 1)]["pct"]) == (3, 75.0)
    assert (e[("falha_extracao", "texto_insuficiente", 0)]["n_urls"], e[("falha_extracao", "texto_insuficiente", 0)]["pct"]) == (1, 25.0)


def test_eficiencia(web):
    e = _linhas(web, "v_eficiencia")[0]
    assert e["custo_total_usd"] == pytest.approx(0.06) and e["requisicoes_busca_web"] == 12
    assert e["fontes_confirmadas"] == 2 and e["custo_por_fonte_confirmada_usd"] == 0.03
    assert e["creditos_scholar"] == 0 and e["artigos_incluidos"] == 0 and e["creditos_por_artigo_incluido"] is None


def test_toda_view_de_metrica_vira_aba_da_exportacao(ac, web):
    esperadas = {"Termos_rendimento", "Termos_pares", "Termos_idioma", "Termos_pagina", "Curva_descoberta", "PRISMA",
                 "Motivos_exclusao", "Registro_buscas", "Web_rendimento", "Web_modelos", "Web_posicao",
                 "Web_consultas_vazias", "UF_tecnologia", "Precisao_LLM", "Correcoes_humanas",
                 "Qualidade_classif", "Extracao", "Eficiencia"}
    for repo in (ac, web):
        tabelas = repo.tabelas_para_exportacao()
        assert esperadas <= set(tabelas)
        assert all(len(nome) <= 31 for nome in tabelas)             # limite de nome de aba do Excel
    assert list(ac.tabelas_para_exportacao()["PRISMA"].columns) == ["fase", "metrica", "valor"]
    assert len(ac.tabelas_para_exportacao()["Registro_buscas"]) == 7
