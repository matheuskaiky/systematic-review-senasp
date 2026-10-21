from collections import OrderedDict
from io import BytesIO
import re
import pandas as pd

from aplicacao import rotulagem as RT
from dominio import auditoria_negativos as AN
from dominio.planilha import celula_segura
from dominio.catalogo import SIGNIFICADO_COLUNAS, STATUS_LEITURA_PADRAO, validar_leitura


def montar_tabelas(repo, ufs):
    return _com_resumo_uf(repo.tabelas_para_exportacao(), ufs)


def montar_tabelas_painel(leitura, ufs):
    """As mesmas abas de `montar_tabelas`, lidas pelo painel (SQLite ou PostgreSQL) para o download pelo navegador."""
    brutas = leitura.tabelas_para_exportacao()
    return _com_resumo_uf({aba: pd.DataFrame.from_records(linhas, columns=colunas, coerce_float=True)
                           for aba, (colunas, linhas) in brutas.items()}, ufs)


def _com_resumo_uf(tabelas, ufs):
    resumo = tabelas.pop("Resumo_UF_bruto")
    todas = pd.DataFrame({"uf": list(ufs), "nome": list(ufs.values())})
    tabelas["Resumo_UF"] = todas.merge(resumo, on="uf", how="left").fillna(0)   # includes states with no findings
    return tabelas


def tabelas_rotulagem(plano, status_validos):
    """Planilhas da rotulagem mínima: {nome do arquivo .xlsx: {aba: DataFrame}} (aba de dados mais a aba LEIA-ME) para o exportador,
    e {nome do .csv: DataFrame} da auditoria em `csvs`. Só as partes com linhas aparecem. Devolve (planilhas, csvs)."""
    leiame = lambda linhas: pd.DataFrame({"LEIA-ME": linhas})
    planilhas, csvs = {}, {}
    if plano["achados"]["linhas"]:
        planilhas[RT.ARQ_ACHADOS] = {"Achados": pd.DataFrame(plano["achados"]["linhas"]),
                                     "LEIA-ME": leiame(RT.leiame_achados(plano, status_validos))}
    if plano["triagem"]["linhas"]:
        planilhas[RT.ARQ_TRIAGEM] = {"Triagem": pd.DataFrame(plano["triagem"]["linhas"]), "LEIA-ME": leiame(RT.leiame_triagem(plano))}
    h4 = plano["triagem"]["h4"]
    if h4 and h4["linhas"]:
        planilhas[RT.ARQ_TRIAGEM_H4] = {"Triagem": pd.DataFrame(h4["linhas"]), "LEIA-ME": leiame(RT.leiame_triagem(plano, h4=True))}
    if plano["auditoria"]["linhas"]:
        csvs[RT.ARQ_AUDITORIA] = pd.DataFrame(plano["auditoria"]["linhas"], columns=list(AN.COLUNAS_AMOSTRA))
    return planilhas, csvs


def planilhas_referencias(catalogo, modelo, categorias, eixos):
    """Retorna um OrderedDict aba -> DataFrame com as abas do modelo informado."""
    abas = OrderedDict()
    headers = [c for c, _ in modelo.colunas]

    for nome_aba, filtro in modelo.abas:
        if filtro == "brasil":
            filtrados = [r for r in catalogo if r["pais_escopo"] == "Brasil"]
        elif filtro == "internacional":
            filtrados = [r for r in catalogo if r["pais_escopo"] == "Internacional"]
        elif isinstance(filtro, tuple) and filtro[0] == "categoria":
            filtrados = [r for r in catalogo if r["categoria"] == filtro[1]]
        else:
            filtrados = list(catalogo)

        linhas_aba = [{cabecalho: r[campo] for cabecalho, campo in modelo.colunas} for r in filtrados]
        abas[nome_aba] = pd.DataFrame(linhas_aba, columns=headers)

    abas["Legenda"] = pd.DataFrame(
        [{"Categoria": k, "Descricao": v} for k, v in categorias.items()],
        columns=["Categoria", "Descricao"],
    )

    abas["Indice_Tematico"] = pd.DataFrame(
        [{"Eixo tematico": k, "Topicos relacionados": v} for k, v in eixos.items()],
        columns=["Eixo tematico", "Topicos relacionados"],
    )

    if modelo.explicar_colunas:
        abas["Colunas"] = pd.DataFrame(
            [{"Coluna": c, "Significado": SIGNIFICADO_COLUNAS.get(c, "")} for c in headers],
            columns=["Coluna", "Significado"],
        )

    return abas


def planilha_xlsx(abas):
    """As abas (nome -> DataFrame) num arquivo .xlsx em memoria, na ordem recebida, com as celulas de texto pela regra C3
    (download pelo painel e comando exportar-referencias: o mesmo arquivo)."""
    saida = BytesIO()
    with pd.ExcelWriter(saida) as w:
        for nome_aba, df in abas.items():
            df.map(celula_segura).to_excel(w, sheet_name=nome_aba, index=False)
    return saida.getvalue()


def _celula_para_texto(v):
    if v is None or pd.isna(v):
        return ""
    if isinstance(v, str):
        return v
    if type(v) is int:
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return str(v)
    return str(v)


def ler_leituras(caminho, modelo, categorias, eixos):
    """Le a primeira aba da planilha e extrai os campos preenchidos pelo pesquisador."""
    df = pd.read_excel(caminho, sheet_name=modelo.abas[0][0], dtype=object)
    campo_para_cabecalho = {campo: cabecalho for cabecalho, campo in modelo.colunas}

    erros = []
    campos_obrigatorios = ("id", "categoria", "eixo", "prioridade", "status_leitura", "notas")
    for campo in campos_obrigatorios:
        cabecalho = campo_para_cabecalho.get(campo)
        if cabecalho is not None and cabecalho not in df.columns:
            erros.append(f"Coluna '{cabecalho}' nao encontrada na planilha")

    col_id = campo_para_cabecalho.get("id")
    col_cat = campo_para_cabecalho.get("categoria")
    col_eixo = campo_para_cabecalho.get("eixo")
    col_prio = campo_para_cabecalho.get("prioridade")
    col_st = campo_para_cabecalho.get("status_leitura")
    col_notas = campo_para_cabecalho.get("notas")

    ids_vistos = set()
    ids_ordem = []
    ids_repetidos = set()
    linhas_validas = []

    for idx, row in df.iterrows():
        linha = idx + 2

        id_txt = _celula_para_texto(row.get(col_id)) if (col_id and col_id in df.columns) else ""
        cat_txt = _celula_para_texto(row.get(col_cat)) if (col_cat and col_cat in df.columns) else ""
        eixo_txt = _celula_para_texto(row.get(col_eixo)) if (col_eixo and col_eixo in df.columns) else ""
        prio_txt = _celula_para_texto(row.get(col_prio)) if (col_prio and col_prio in df.columns) else ""
        st_txt = _celula_para_texto(row.get(col_st)) if (col_st and col_st in df.columns) else ""
        notas_txt = _celula_para_texto(row.get(col_notas)) if (col_notas and col_notas in df.columns) else ""

        if (id_txt.strip() == "" and
            cat_txt.strip() == "" and
            eixo_txt.strip() == "" and
            prio_txt.strip() == "" and
            st_txt.strip() == "" and
            notas_txt.strip() == ""):
            continue

        t = id_txt.strip()
        if not (re.fullmatch(r"[0-9]+", t) and len(t.lstrip("0")) <= 19 and int(t.lstrip("0") or "0") <= 9223372036854775807):
            erros.append(f"Linha {linha}: ID invalido: '{id_txt}'")
            continue

        artigo_id = int(t.lstrip("0") or "0")

        if artigo_id in ids_vistos:
            ids_repetidos.add(artigo_id)
        else:
            ids_vistos.add(artigo_id)
            ids_ordem.append(artigo_id)

        cat = cat_txt.strip()
        eixo = eixo_txt.strip()
        prio = prio_txt.strip()
        st = st_txt.strip()
        notas = notas_txt

        linha_val = {
            "id": artigo_id,
            "categoria": cat,
            "eixo": eixo,
            "prioridade": prio,
            "status_leitura": st,
        }
        erros_val = validar_leitura(linha_val, categorias, eixos)
        if erros_val:
            erros.extend(erros_val)

        linhas_validas.append({
            "artigo_id": artigo_id,
            "categoria": cat if cat != "" else None,
            "eixo": eixo if eixo != "" else None,
            "prioridade": prio if prio != "" else None,
            "status_leitura": st if st != "" else STATUS_LEITURA_PADRAO,
            "notas": notas if notas != "" else None,
        })

    erros_repeticao = [f"ID {artigo_id}: repetido na planilha" for artigo_id in ids_ordem if artigo_id in ids_repetidos]
    todos_erros = erros + erros_repeticao
    if todos_erros:
        raise ValueError("\n".join(todos_erros))

    return linhas_validas
