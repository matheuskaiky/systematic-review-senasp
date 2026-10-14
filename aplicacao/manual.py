def gerar_modelo_manual(termos, bases):
    """One row per term x database combination, to be filled in by hand (IEEE, ACM, Scopus, SBC)."""
    return [{"base": b, "termo_id": t.id, "string_base": t.query, "filtros": "", "n_resultados": "",
             "n_apos_filtro": "", "n_selecionados": "", "data_busca": "", "observacao": ""}
            for t in termos for b in bases]


def validar_manuais(df, termos, bases):
    ids = {t.id for t in termos}
    ruins = df[~df["termo_id"].isin(ids) | ~df["base"].isin(bases)]
    if len(ruins):
        raise SystemExit(f"Invalid termo_id or base in {len(ruins)} row(s)")


# artigos encontrados a mao em cada base (um por linha), para deduplicar contra o Scholar e entre as bases
COLUNAS_ARTIGOS_MANUAIS = ("base", "termo_id", "titulo", "link", "autores_publicacao", "ano", "citacoes",
                           "posicao", "data_busca")


def validar_artigos_manuais(df, termos, bases):
    """Colunas obrigatorias, titulo preenchido, base e termo_id conhecidos. Encerra com mensagem se algo falhar."""
    faltando = [c for c in ("base", "termo_id", "titulo") if c not in df.columns]
    if faltando:
        raise SystemExit(f"Colunas obrigatorias ausentes no arquivo de artigos manuais: {', '.join(faltando)}")
    sem_titulo = df[df["titulo"].isna() | (df["titulo"].astype(str).str.strip() == "")]
    if len(sem_titulo):
        raise SystemExit(f"Titulo vazio em {len(sem_titulo)} linha(s) do arquivo de artigos manuais")
    ruins = df[~df["termo_id"].isin({t.id for t in termos}) | ~df["base"].isin(bases)]
    if len(ruins):
        raise SystemExit(f"termo_id ou base invalido em {len(ruins)} linha(s) do arquivo de artigos manuais")
