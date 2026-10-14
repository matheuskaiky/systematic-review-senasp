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
