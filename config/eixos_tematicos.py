"""Eixos tematicos (coluna Eixo tematico). Os 10 primeiros sao o Indice_Tematico das planilhas do professor (docs/modelo-professor/, MASTER_FINAL_IA_SEGURANCA_PUBLICA_ETICA_DISCRIMINACAO.xlsx), copiados literalmente; decisao do pesquisador de 17/10/2026 (no minimo os do professor). Eixos novos entram depois deles."""

EIXOS_TEMATICOS = {
    "Policiamento preditivo": "COMPAS, PSA, HART, RisCanvi, PredPol, Chicago PPA, metricas de equidade, feedback loops, Statewatch 2025",
    "Reconhecimento facial": "Vies demografico, falsos positivos/negativos, testes NIST/NPL, regulamentacoes, proibicoes, 90,5 percent negros Brasil",
    "Investigacao criminal": "IA generativa, NLP, analise de vinculos, redes criminosas, deepfakes, forense digital",
    "Governanca e regulacao": "AI Act (UE), LGPD (BR), PL 2338/2023, auditoria, transparencia, avaliacao de impacto, ANPD Res 17/2025",
    "Brasil e politicas estaduais": "Muralha Paulista, Smart Sampa (SP), Video-Policia (BA), PMERJ (RJ), Paredao (AM), SISFRON, Sistema Pax (GO)",
    "Inteligencia policial": "ILP/POI, CIISP, monitoramento de faccoes (PCC), contrainteligencia, centros de analise telematica",
    "Sul Global e interseccionalidade": "Legado colonial, vigilancia autoritaria, raca, genero, pessoas trans, America Latina, India, Africa",
    "Evidencia e processo penal": "Admissibilidade, contraditorio, opacidade, cadeia de custodia algoritmica, devido processo",
    "Etica e principios": "UNESCO 2023, OECD 2021, ISO/IEC 2023, TJDFT 2025, CFESS 2025, Europol 2025",
    "Discriminacao algoritmica": "Racismo algoritmico, vies racial, genero, classe, 90,5 percent negros Brasil, 10 percent falsos positivos RJ, 23 conduzidas indevidas SP",
}

# Esquema de exploracao da busca de vies algoritmico (D102): os 6 eixos e as perguntas-guia enviados pelo pesquisador em
# 21/10/2026, copiados literalmente. Sao o esquema da aba "Esquema de exploração" da planilha de referencias dessa busca.
EIXOS_EXPLORACAO = {
    "Policiamento preditivo e equidade": "Eficácia vs. equidade; unidades geográficas ou pessoas; ciclos de retroalimentação; critérios e métricas de fairness.",
    "Biometria e vigilância": "Taxas de erro por subgrupo; qualidade de imagem; base de referência; protocolo de uso; revisões humanas.",
    "Investigação e inteligência": "NLP, análise de vínculos, redes criminais, geoprofiling, triagem de evidência digital e risco de viés de automação.",
    "Forense digital e deepfakes": "Validade fora de benchmark; reprodutibilidade; taxas de erro; documentação; admissibilidade e contraditório.",
    "Direitos e governança": "Avaliações de impacto, auditorias externas, transparência contratual, registros de decisão e rotas de contestação.",
    "Brasil e América Latina": "Mapear pesquisas por UF, contratos e políticas; comparar dados de implementação, resultados e impactos distributivos.",
}
