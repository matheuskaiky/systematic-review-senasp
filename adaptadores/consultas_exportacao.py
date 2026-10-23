"""Consultas da planilha completa de resultados (comando `exportar` e download pelo painel): uma aba por consulta,
na ordem do dicionario. As duas leituras usam este mesmo dicionario, para os dois arquivos terem as mesmas abas."""

CONSULTAS_EXPORTACAO = {
    "Execucoes": "SELECT * FROM execucoes ORDER BY iniciado_em, rowid",
    "Funil": "SELECT * FROM v_funil",
    "Custos": "SELECT * FROM v_custos",
    "Falhas": "SELECT * FROM v_falhas",
    "Descartes": "SELECT * FROM v_descartes",
    "Dominios": "SELECT * FROM v_dominios LIMIT 300",
    "Busca_web": "SELECT * FROM v_metricas_busca_web",
    "Achados": "SELECT * FROM v_achados_revisao",
    "Resumo_UF_bruto": "SELECT * FROM v_resumo_uf",
    "Secretarias": "SELECT * FROM v_secretarias_confirmadas",
    "Municipios": "SELECT * FROM v_resumo_municipio",
    "Chamadas": "SELECT * FROM chamadas ORDER BY requisitado_em, chamada_id",
    "Metricas_termo": "SELECT * FROM v_metricas_por_termo",
    "Artigos": "SELECT * FROM artigos ORDER BY COALESCE(citacoes,0) DESC, artigo_id",
    "Artigos_ano": "SELECT * FROM v_artigos_por_ano",
    "Multi_termo": "SELECT * FROM v_artigos_multi_termo",
    "Sobreposicao": "SELECT * FROM v_sobreposicao_termos",
    "Triagem": """SELECT a.artigo_id, a.titulo, a.ano, a.link, a.citacoes,
                         (SELECT e.status || CASE WHEN e.categoria_motivo IS NOT NULL
                                                  THEN ': ' || e.categoria_motivo ELSE '' END
                          FROM triagem_escopo e WHERE e.fonte='artigo' AND e.item_id=a.artigo_id AND e.uf=''
                          ORDER BY e.criado_em DESC, e.id DESC LIMIT 1) AS triagem_llm,
                         COALESCE(t.decisao,'pendente') AS decisao, t.motivo,
                         t.confirmado_em_base, t.link_confirmado, t.revisor, t.revisado_em,
                         t.decisao_texto_completo, t.motivo_texto_completo
                  FROM artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id
                  ORDER BY COALESCE(a.citacoes,0) DESC, a.artigo_id""",
    # opiniao do modelo (a ultima por item), sem esconder nada: `excluido` e `quarentena` aparecem junto com os demais
    "Triagem_escopo": """SELECT e.fonte, e.item_id, e.uf,
                                CASE e.fonte WHEN 'artigo' THEN (SELECT a.titulo FROM artigos a WHERE a.artigo_id=e.item_id)
                                             WHEN 'referencia' THEN (SELECT r.url_original FROM referencias_web r
                                                                     WHERE r.referencia_id=e.item_id)
                                             ELSE (SELECT u.url_original FROM urls u WHERE u.url_id=e.item_id) END AS item,
                                e.status, e.status_bruto, e.confianca, e.categoria_motivo, e.justificativa,
                                e.termo_gerador, e.sinal_negativo, e.dominio_tematico, e.escopo_geografico,
                                e.tipo_documento, e.valido, e.problemas, e.termos_consulta, e.provedor,
                                e.prompt_versao, e.run_id, e.chamada_id, e.criado_em, e.tipo_fonte, e.pais_escopo,
                                e.topicos, e.eixo, e.recorte
                         FROM triagem_escopo e
                         WHERE e.id = (SELECT x.id FROM triagem_escopo x
                                       WHERE x.fonte=e.fonte AND x.item_id=e.item_id AND x.uf=e.uf
                                       ORDER BY x.criado_em DESC, x.id DESC LIMIT 1)
                         ORDER BY e.fonte, e.item_id, e.uf""",
    "Buscas_manuais": "SELECT * FROM buscas_manuais ORDER BY base, termo_id",
    "Manuais_resumo": "SELECT * FROM v_manuais_resumo",
    # metricas para o relatorio (protocolo e justificativas)
    "Termos_rendimento": "SELECT * FROM v_rendimento_termo",
    "Termos_pares": "SELECT * FROM v_pares_termos",
    "Termos_idioma": "SELECT * FROM v_ganho_por_idioma",
    "Termos_pagina": "SELECT * FROM v_rendimento_por_pagina",
    "Curva_descoberta": ("SELECT v.* FROM v_curva_descoberta v JOIN chamadas c ON c.chamada_id = v.chamada_id "
                         "ORDER BY c.requisitado_em, v.chamada_id"),
    "PRISMA": "SELECT fase, metrica, valor FROM v_prisma ORDER BY ordem",
    "Motivos_exclusao": "SELECT * FROM v_motivos_exclusao",
    "Registro_buscas": "SELECT * FROM v_registro_buscas",
    "Web_rendimento": "SELECT * FROM v_rendimento_busca_web",
    "Web_modelos": "SELECT * FROM v_sobreposicao_modelos",
    "Web_posicao": "SELECT * FROM v_rendimento_por_posicao",
    "Web_consultas_vazias": "SELECT * FROM v_consultas_vazias",
    "UF_tecnologia": "SELECT * FROM v_cobertura_uf_tecnologia",
    "Precisao_LLM": "SELECT * FROM v_precisao_llm",
    "Correcoes_humanas": "SELECT * FROM v_correcoes_humanas",
    "Qualidade_classif": "SELECT * FROM v_qualidade_classificacao",
    "Extracao": "SELECT * FROM v_extracao",
    "Eficiencia": "SELECT * FROM v_eficiencia",
    "Classif_invalidas": "SELECT * FROM v_classificacoes_invalidas",
    "Consistencia_evidencia": "SELECT * FROM v_consistencia_evidencia",
    "Gasto_real": "SELECT * FROM v_gasto_real",
    "Saldos": "SELECT * FROM v_saldos",
    "Metricas_run": "SELECT * FROM metricas_run",
    "Download_resultado": "SELECT * FROM v_resultado_download",
    "Classif_resultado": "SELECT * FROM v_resultado_classificacao",
    "Achados_descartados": "SELECT * FROM v_achados_descartados",
    "Confianca_ajustada": "SELECT * FROM v_confianca_ajustada",
    "Auditoria_prefiltro": "SELECT * FROM v_auditoria_prefiltro",
    "Fontes": "SELECT * FROM v_rendimento_fonte",
    "Fontes_sobreposicao": "SELECT * FROM v_sobreposicao_fontes",
    "Termos_fonte": "SELECT * FROM v_rendimento_termo_fonte",
    "Termos_total_estabilidade": "SELECT * FROM v_total_reportado_estabilidade",
    "Ganho_contexto": "SELECT * FROM v_ganho_contexto",
    "Revisores_kappa": "SELECT * FROM v_concordancia_revisores",
    "Discordancias": "SELECT * FROM v_discordancias_triagem",
    "Revisores_kappa_achados": "SELECT * FROM v_concordancia_revisores_achados",
    "Discordancias_achados": "SELECT * FROM v_discordancias_achados",
    "Auditoria_negativos": "SELECT * FROM v_auditoria_negativos",
    "Passadas": "SELECT * FROM v_passadas ORDER BY run_id, passada",
    "Historico_triagem": "SELECT * FROM triagem_revisoes ORDER BY revisao_id",
    "Historico_achados": "SELECT * FROM achados_revisoes ORDER BY revisao_id",
}


def ler_tabelas(conn):
    """{aba: (colunas, linhas)} de cada consulta, na conexao recebida (SQLite ou a conexao compativel do PostgreSQL)."""
    tabelas = {}
    for aba, sql in CONSULTAS_EXPORTACAO.items():
        cur = conn.execute(sql)
        tabelas[aba] = ([d[0] for d in cur.description], [tuple(l) for l in cur.fetchall()])
    return tabelas
