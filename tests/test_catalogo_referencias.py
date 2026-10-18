"""RD14 e RD16: catalogo de referencias exportavel em mais de um modelo de planilha (um deles no formato das planilhas do
professor, docs/modelo-professor/), eixos tematicos em configuracao propria e campos de leitura que voltam por importacao.

Tudo offline: a linha de comando roda com --simulado sobre o banco simulado de tmp_path.
"""
import sqlite3
import sys

import pandas as pd
import pytest

import main
import config.settings as S
from config import categorias_referencias as K, eixos_tematicos as E, modelos_exportacao as M
from dominio.catalogo import autor_de, rotulo_pais, rotulo_tipo

CABECALHOS_PROFESSOR = ["ID", "Categoria", "Autor/Instituicao", "Ano", "Titulo", "Tipo de fonte", "Pais/escopo",
                        "Topicos e palavras-chave", "URL", "Prioridade de leitura", "Status de leitura", "Notas"]
# Indice_Tematico do professor (MASTER_FINAL_IA_SEGURANCA_PUBLICA_ETICA_DISCRIMINACAO.xlsx), decisao do pesquisador (D18)
EIXOS_PROFESSOR = ["Policiamento preditivo", "Reconhecimento facial", "Investigacao criminal", "Governanca e regulacao",
                   "Brasil e politicas estaduais", "Inteligencia policial", "Sul Global e interseccionalidade",
                   "Evidencia e processo penal", "Etica e principios", "Discriminacao algoritmica"]
# Legenda do professor (mesma planilha), sem a contagem "(N refs)" do acervo dele; decisao do pesquisador de 17/10/2026
CATEGORIAS_PROFESSOR = {
    "Geral": "IA, seguranca publica, vies algoritmico e investigacao criminal: literatura global e classicos",
    "Brasil": "Contexto brasileiro: reconhecimento facial, LGPD, politicas estaduais, estudos empiricos",
    "Inteligencia Policial": "ILP/POI, CIISP, centros de analise, tecnologias preditivas, contrainteligencia",
    "Internacional": "Estudos comparados: Europa, EUA, India, Sul Global, genero, ferramentas de risco",
    "Brasil_Etica": "Brasil: etica, discriminacao, vies algoritmico, principios eticos, governanca",
    "Brasil_Casos": "Casos estaduais: SP (Smart Sampa), BA (Video-Policia), RJ (PMERJ), PE",
    "Internacional_Etica": "Internacional: Europa (AI Act), EUA (COMPAS), Sul Global, reconhecimento facial",
}
ABAS_PADRAO = ["Referencias", "Referencias_Brasil", "Referencias_Internacional", "Legenda", "Indice_Tematico", "Colunas"]
ABAS_PROFESSOR = ["Todas as Referencias", "Brasil", "Internacional", "Legenda", "Indice_Tematico"]


# ====================== configuracao ======================
def test_categorias_comecam_pelos_7_grupos_do_professor():
    assert list(K.CATEGORIAS_REFERENCIAS.items())[:7] == list(CATEGORIAS_PROFESSOR.items())


def test_eixos_tematicos_tem_no_minimo_os_do_professor():
    nomes = list(E.EIXOS_TEMATICOS)
    assert nomes[:len(EIXOS_PROFESSOR)] == EIXOS_PROFESSOR
    assert all(isinstance(t, str) and t.strip() for t in E.EIXOS_TEMATICOS.values())      # topicos de cada eixo


def test_modelo_professor_reproduz_colunas_e_abas():
    m = M.MODELOS_REFERENCIAS["professor"]
    assert [c for c, _ in m.colunas] == CABECALHOS_PROFESSOR
    assert [a for a, _ in m.abas] == ["Todas as Referencias", "Brasil", "Internacional"]


def test_ha_mais_de_um_modelo_e_o_padrao_e_o_do_projeto():
    assert {"padrao", "professor"} <= set(M.MODELOS_REFERENCIAS)
    assert M.MODELO_REFERENCIAS_PADRAO == "padrao"
    m = M.MODELOS_REFERENCIAS["padrao"]
    assert [c for c, _ in m.colunas] == CABECALHOS_PROFESSOR + ["Eixo tematico", "Citacoes", "Termos", "Triagem do modelo",
                                                                "Decisao humana"]
    assert [a for a, _ in m.abas] == ["Referencias", "Referencias_Brasil", "Referencias_Internacional"]
    assert m.explicar_colunas and not M.MODELOS_REFERENCIAS["professor"].explicar_colunas


def test_todo_campo_dos_modelos_existe_no_catalogo():
    from dominio.catalogo import CAMPOS_CATALOGO
    for m in M.MODELOS_REFERENCIAS.values():
        assert {campo for _, campo in m.colunas} <= set(CAMPOS_CATALOGO)
        assert {filtro for _, filtro in m.abas} <= {None, "brasil", "internacional"}


# ====================== dominio ======================
def test_autor_e_a_parte_antes_do_veiculo():
    assert autor_de("A Silva, B Souza - Revista X, 2019 - exemplo.edu") == "A Silva, B Souza"
    assert autor_de("Autor Unico") == "Autor Unico"
    assert autor_de(None) == ""


def test_rotulos_legiveis():
    assert (rotulo_pais("brasil"), rotulo_pais("internacional"), rotulo_pais(None)) == ("Brasil", "Internacional", "Indeterminado")
    assert rotulo_tipo("artigo_periodico") == "Artigo cientifico"
    assert rotulo_tipo("relatorio_tecnico") == "Relatorio tecnico"
    assert rotulo_tipo(None) == "Indeterminado"


# ====================== banco simulado ======================
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def _banco(tmp):
    return sqlite3.connect(tmp / "data" / "simulado.db")


@pytest.fixture
def com_artigos(ambiente_cli, monkeypatch):
    """Banco simulado com os artigos de 2 termos; o 1o artigo e Brasil, o 2o internacional, o 3o excluido pelo modelo."""
    _rodar(monkeypatch, "academico", "--simulado", "--termos", "T01", "T25", "--paginas", "1")
    c = _banco(ambiente_cli)
    run_id = c.execute("SELECT run_id FROM execucoes").fetchone()[0]
    ids = [r[0] for r in c.execute("SELECT artigo_id FROM artigos ORDER BY artigo_id")]
    for item, status, escopo, tipo in ((ids[0], "elegivel", "brasil", "artigo_periodico"),
                                       (ids[1], "quarentena", "internacional", "relatorio_tecnico"),
                                       (ids[2], "excluido", "brasil", "artigo_periodico")):
        c.execute("INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, status, escopo_geografico, tipo_documento, "
                  "dominio_tematico, valido, criado_em) VALUES (?, 'artigo', ?, '', ?, ?, ?, 'seguranca_publica', 1, "
                  "'2026-10-17T00:00:00')", (run_id, item, status, escopo, tipo))
    c.commit()
    return ambiente_cli, ids


def _planilha(tmp, modelo):
    return tmp / "outputs" / M.MODELOS_REFERENCIAS[modelo].arquivo


def test_tabela_leitura_referencias(com_artigos):
    tmp, _ = com_artigos
    cols = [r[1] for r in _banco(tmp).execute("PRAGMA table_info(leitura_referencias)")]
    assert {"artigo_id", "categoria", "eixo", "prioridade", "status_leitura", "notas", "atualizado_em"} <= set(cols)


def test_exporta_no_modelo_do_professor(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    _rodar(monkeypatch, "exportar-referencias", "--simulado", "--modelo", "professor")
    abas = pd.read_excel(_planilha(tmp, "professor"), sheet_name=None)
    assert list(abas) == ABAS_PROFESSOR
    todas = abas["Todas as Referencias"]
    assert list(todas.columns) == CABECALHOS_PROFESSOR
    assert ids[2] not in set(todas["ID"])                                  # excluido pelo modelo nao entra
    assert ids[0] in set(abas["Brasil"]["ID"]) and ids[0] not in set(abas["Internacional"]["ID"])
    assert ids[1] in set(abas["Internacional"]["ID"])
    linha = todas[todas["ID"] == ids[0]].iloc[0]
    assert (linha["Pais/escopo"], linha["Tipo de fonte"], linha["Status de leitura"]) == ("Brasil", "Artigo cientifico", "Nao iniciado")
    assert linha["Autor/Instituicao"] == "Autor"                         # "Autor - Revista, 2023" no simulado
    assert '"reconhecimento facial"' in linha["Topicos e palavras-chave"]
    assert list(abas["Indice_Tematico"].columns) == ["Eixo tematico", "Topicos relacionados"]
    assert list(abas["Indice_Tematico"]["Eixo tematico"])[:len(EIXOS_PROFESSOR)] == EIXOS_PROFESSOR
    assert list(abas["Legenda"].columns) == ["Categoria", "Descricao"]
    assert dict(zip(abas["Legenda"]["Categoria"], abas["Legenda"]["Descricao"])) == {**CATEGORIAS_PROFESSOR, **dict(
        list(K.CATEGORIAS_REFERENCIAS.items())[7:])}


def test_exporta_no_modelo_padrao_sem_flag(com_artigos, monkeypatch):
    tmp, _ = com_artigos
    _rodar(monkeypatch, "exportar-referencias", "--simulado")
    abas = pd.read_excel(_planilha(tmp, "padrao"), sheet_name=None)
    assert list(abas) == ABAS_PADRAO
    colunas = abas["Colunas"]
    assert list(colunas.columns) == ["Coluna", "Significado"]
    assert list(colunas["Coluna"]) == list(abas["Referencias"].columns)
    assert colunas["Significado"].notna().all()
    linha = abas["Referencias"].iloc[0]
    assert linha["Decisao humana"] == "pendente" and linha["Termos"] in ("T01", "T25")


def test_leitura_ida_e_volta(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    _rodar(monkeypatch, "exportar-referencias", "--simulado", "--modelo", "professor")
    arq = _planilha(tmp, "professor")
    abas = pd.read_excel(arq, sheet_name=None, dtype=object)
    todas = abas["Todas as Referencias"]
    i = todas.index[todas["ID"] == ids[0]][0]
    todas.loc[i, ["Categoria", "Prioridade de leitura", "Status de leitura", "Notas"]] = \
        ["Brasil_Casos", "Alta", "Lido", "caso SP"]
    with pd.ExcelWriter(arq) as w:
        for nome, df in abas.items():
            (todas if nome == "Todas as Referencias" else df).to_excel(w, sheet_name=nome, index=False)
    _rodar(monkeypatch, "leitura-importar", str(arq), "--simulado", "--modelo", "professor")
    assert _banco(tmp).execute("SELECT categoria, eixo, prioridade, status_leitura, notas FROM leitura_referencias "
                               "WHERE artigo_id=?", (int(ids[0]),)).fetchone() == ("Brasil_Casos", None, "Alta", "Lido", "caso SP")
    _rodar(monkeypatch, "exportar-referencias", "--simulado", "--modelo", "professor")
    de_novo = pd.read_excel(arq, sheet_name="Todas as Referencias", dtype=object)
    assert de_novo[de_novo["ID"] == ids[0]].iloc[0]["Status de leitura"] == "Lido"


@pytest.mark.parametrize("coluna,valor", [("Status de leitura", "Quase lido"), ("Prioridade de leitura", "Urgente"),
                                          ("Categoria", "Categoria que nao existe")])
def test_valor_invalido_aborta_sem_gravar(com_artigos, monkeypatch, coluna, valor):
    tmp, ids = com_artigos
    _rodar(monkeypatch, "exportar-referencias", "--simulado", "--modelo", "professor")
    arq = _planilha(tmp, "professor")
    todas = pd.read_excel(arq, sheet_name="Todas as Referencias", dtype=object)
    todas.loc[todas["ID"] == ids[0], coluna] = valor
    todas.to_excel(arq, sheet_name="Todas as Referencias", index=False)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "leitura-importar", str(arq), "--simulado", "--modelo", "professor")
    assert valor in str(e.value)
    assert _banco(tmp).execute("SELECT COUNT(*) FROM leitura_referencias").fetchone()[0] == 0


def test_planilha_intacta_nao_muda_nada(com_artigos, monkeypatch, capsys):
    tmp, _ = com_artigos
    _rodar(monkeypatch, "exportar-referencias", "--simulado", "--modelo", "professor")
    _rodar(monkeypatch, "leitura-importar", str(_planilha(tmp, "professor")), "--simulado", "--modelo", "professor")
    assert "Leituras alteradas: 0" in capsys.readouterr().out
    assert _banco(tmp).execute("SELECT COUNT(*) FROM leitura_referencias").fetchone()[0] == 0


def test_eixo_no_modelo_padrao_ida_e_volta_e_invalido(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    _rodar(monkeypatch, "exportar-referencias", "--simulado")
    arq = _planilha(tmp, "padrao")
    abas = pd.read_excel(arq, sheet_name=None, dtype=object)
    ref = abas["Referencias"]
    ref.loc[ref["ID"] == ids[0], "Eixo tematico"] = "Eixo que nao existe"
    with pd.ExcelWriter(arq) as w:
        for nome, df in abas.items():
            (ref if nome == "Referencias" else df).to_excel(w, sheet_name=nome, index=False)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "leitura-importar", str(arq), "--simulado")
    assert "Eixo que nao existe" in str(e.value)
    ref.loc[ref["ID"] == ids[0], "Eixo tematico"] = "Reconhecimento facial"
    with pd.ExcelWriter(arq) as w:
        for nome, df in abas.items():
            (ref if nome == "Referencias" else df).to_excel(w, sheet_name=nome, index=False)
    _rodar(monkeypatch, "leitura-importar", str(arq), "--simulado")
    assert _banco(tmp).execute("SELECT eixo, status_leitura FROM leitura_referencias WHERE artigo_id=?",
                               (int(ids[0]),)).fetchone() == ("Reconhecimento facial", "Nao iniciado")


# ====================== retrabalho R1 (laudo de 17/10/2026) ======================
def _editar_professor(tmp, monkeypatch, mudar):
    """Exporta no modelo do professor, aplica `mudar(df)` na aba principal e regrava so essa aba."""
    _rodar(monkeypatch, "exportar-referencias", "--simulado", "--modelo", "professor")
    arq = _planilha(tmp, "professor")
    df = pd.read_excel(arq, sheet_name="Todas as Referencias", dtype=object)
    df = mudar(df)
    df.to_excel(arq, sheet_name="Todas as Referencias", index=False)
    return arq


def _importar_falha(monkeypatch, arq):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "leitura-importar", str(arq), "--simulado", "--modelo", "professor")
    return str(e.value)


def _nada_gravado(tmp):
    return _banco(tmp).execute("SELECT COUNT(*) FROM leitura_referencias").fetchone()[0] == 0


@pytest.mark.parametrize("valor", ["abc", "1.9", ""])
def test_r1_id_invalido_aborta(com_artigos, monkeypatch, valor):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[1], "Categoria"] = "Brasil"                    # linha valida: nao pode ser gravada
        df.loc[df["ID"] == ids[0], "Categoria"] = "Geral"
        df.loc[df["ID"] == ids[0], "ID"] = valor
        return df
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert f"ID invalido: '{valor}'" in msg and "Linha 2" in msg
    assert _nada_gravado(tmp)


def test_r1_linha_toda_vazia_e_ignorada(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Status de leitura"] = "Lido"
        vazia = pd.DataFrame([{c: None for c in df.columns}])
        return pd.concat([df, vazia], ignore_index=True)
    arq = _editar_professor(tmp, monkeypatch, mudar)
    _rodar(monkeypatch, "leitura-importar", str(arq), "--simulado", "--modelo", "professor")
    assert _banco(tmp).execute("SELECT COUNT(*) FROM leitura_referencias").fetchone()[0] == 1


def test_r1_id_inteiro_vindo_como_numero_decimal_e_aceito(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Status de leitura"] = "Lido"
        df.loc[df["ID"] == ids[0], "ID"] = float(ids[0])
        return df
    _rodar(monkeypatch, "leitura-importar", str(_editar_professor(tmp, monkeypatch, mudar)), "--simulado",
           "--modelo", "professor")
    assert _banco(tmp).execute("SELECT status_leitura FROM leitura_referencias WHERE artigo_id=?",
                               (int(ids[0]),)).fetchone() == ("Lido",)


def test_r1_coluna_do_modelo_ausente_aborta(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Categoria"] = "Brasil"
        return df.drop(columns=["Notas"])
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert "Coluna 'Notas' nao encontrada na planilha" in msg
    assert _nada_gravado(tmp)


def test_r1_id_repetido_aborta(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Categoria"] = "Brasil"
        return pd.concat([df, df[df["ID"] == ids[0]]], ignore_index=True)
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert f"ID {ids[0]}: repetido na planilha" in msg
    assert _nada_gravado(tmp)


def test_r1_espacos_nos_campos_de_lista_e_notas_intactas(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], ["Categoria", "Prioridade de leitura", "Status de leitura", "Notas"]] = \
            [" Brasil ", "  ", " Lido", "  0012 anotacao  "]
        return df
    _rodar(monkeypatch, "leitura-importar", str(_editar_professor(tmp, monkeypatch, mudar)), "--simulado",
           "--modelo", "professor")
    assert _banco(tmp).execute("SELECT categoria, prioridade, status_leitura, notas FROM leitura_referencias "
                               "WHERE artigo_id=?", (int(ids[0]),)).fetchone() == ("Brasil", None, "Lido", "  0012 anotacao  ")


def test_r1_notas_numericas_em_texto_preservadas(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Notas"] = "0012"
        return df
    _rodar(monkeypatch, "leitura-importar", str(_editar_professor(tmp, monkeypatch, mudar)), "--simulado",
           "--modelo", "professor")
    assert _banco(tmp).execute("SELECT notas FROM leitura_referencias WHERE artigo_id=?",
                               (int(ids[0]),)).fetchone() == ("0012",)


def test_r1_autor_corta_antes_de_limpar():
    assert autor_de(" - Revista") == ""
    assert autor_de("Autor - ") == "Autor"
    assert autor_de("  Autor A - Revista - site ") == "Autor A"


def test_r1_topicos_junta_so_o_que_existe():
    from aplicacao.catalogo import montar_catalogo
    base = {"artigo_id": 1, "titulo": "t", "ano": 2024, "link": None, "autores_publicacao": None, "citacoes": None,
            "status_escopo": None, "tipo_documento": None, "escopo_geografico": None, "categoria": None, "eixo": None,
            "prioridade": None, "status_leitura": None, "notas": None}
    casos = [("a; b", "seguranca_publica", "a; b; seguranca_publica"), ("", "seguranca_publica", "seguranca_publica"),
             ("a", None, "a"), (None, None, "")]
    for consultas, dominio, esperado in casos:
        item = montar_catalogo([{**base, "consultas": consultas, "dominio_tematico": dominio, "termos": None,
                                 "decisao": None}])[0]
        assert item["topicos"] == esperado
        assert (item["termos"], item["decisao_humana"]) == ("", "pendente")


def test_r1_catalogo_da_aplicacao_nao_usa_pandas():
    """Regra de dependencias: em aplicacao/, pandas so em exportacao.py."""
    import ast, pathlib
    arvore = ast.parse(pathlib.Path("aplicacao/catalogo.py").read_text(encoding="utf-8"))
    nomes = {a.name.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.Import) for a in n.names}
    nomes |= {(n.module or "").split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom)}
    assert "pandas" not in nomes


# ====================== retrabalho R2 (laudo de 17/10/2026) ======================
def test_r2_coluna_ausente_tambem_mostra_os_erros_das_linhas(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Categoria"] = "Categoria que nao existe"
        return df.drop(columns=["Notas"])
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert "Coluna 'Notas' nao encontrada na planilha" in msg
    assert "Categoria que nao existe" in msg
    assert msg.index("Coluna 'Notas'") < msg.index("Categoria que nao existe")
    assert _nada_gravado(tmp)


def test_r2_linha_com_id_invalido_gera_so_o_erro_do_id(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], ["Categoria", "Status de leitura"]] = ["Categoria que nao existe", "Quase lido"]
        df.loc[df["ID"] == ids[0], "ID"] = "abc"
        return df
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert "Linha 2: ID invalido: 'abc'" in msg
    assert "Categoria que nao existe" not in msg and "Quase lido" not in msg


@pytest.mark.parametrize("valor", ["9223372036854775808", "99999999999999999999999"])
def test_r2_id_acima_do_limite_do_banco_e_invalido(com_artigos, monkeypatch, valor):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Status de leitura"] = "Lido"
        df.loc[df["ID"] == ids[0], "ID"] = valor
        return df
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert f"ID invalido: '{valor}'" in msg
    assert _nada_gravado(tmp)


def test_r2_repetidos_saem_depois_dos_demais_erros(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Categoria"] = "Categoria que nao existe"
        return pd.concat([df, df[df["ID"] == ids[0]]], ignore_index=True)
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert msg.index("Categoria que nao existe") < msg.index(f"ID {ids[0]}: repetido na planilha")


# ====================== retrabalho R3 (decisao do pesquisador de 17/10/2026) ======================
@pytest.mark.parametrize("valor", ["9" * 4301, "1" + "0" * 30], ids=["4301_noves", "31_digitos"])
def test_r3_id_com_digitos_demais_e_invalido_sem_quebrar(com_artigos, monkeypatch, valor):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Status de leitura"] = "Lido"
        df.loc[df["ID"] == ids[0], "ID"] = valor
        return df.drop(columns=["Notas"])
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert "Coluna 'Notas' nao encontrada na planilha" in msg                       # os demais erros continuam reunidos
    assert f"Linha 2: ID invalido: '{valor}'" in msg
    assert _nada_gravado(tmp)


def test_r3_zeros_a_esquerda_nao_contam_no_limite(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Status de leitura"] = "Lido"
        df.loc[df["ID"] == ids[0], "ID"] = "0" * 40 + str(ids[0])
        return df
    _rodar(monkeypatch, "leitura-importar", str(_editar_professor(tmp, monkeypatch, mudar)), "--simulado",
           "--modelo", "professor")
    assert _banco(tmp).execute("SELECT status_leitura FROM leitura_referencias WHERE artigo_id=?",
                               (int(ids[0]),)).fetchone() == ("Lido",)


def test_r3_repetidos_na_ordem_da_primeira_aparicao(com_artigos, monkeypatch):
    tmp, ids = com_artigos
    a, b = ids[0], ids[1]
    def mudar(df):
        linha = lambda i: df[df["ID"] == i]
        return pd.concat([linha(a), linha(b), linha(b), linha(a)], ignore_index=True)
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert msg.index(f"ID {a}: repetido na planilha") < msg.index(f"ID {b}: repetido na planilha")


# ====================== retrabalho R4 (decisao do pesquisador de 17/10/2026) ======================
@pytest.mark.parametrize("valor,valido", [("0" * 4300 + "1", True), ("0" * 4301, False)], ids=["4300_zeros_e_1", "4301_zeros"])
def test_r4_zeros_a_esquerda_em_excesso_nao_quebram(com_artigos, monkeypatch, valor, valido):
    """4.300 zeros + 1 e o ID 1 (valido, mas pode nao existir); 4.301 zeros e o ID 0 (nao existe): erro formatado, nunca a excecao do Python."""
    tmp, ids = com_artigos
    def mudar(df):
        df.loc[df["ID"] == ids[0], "Status de leitura"] = "Lido"
        df.loc[df["ID"] == ids[0], "ID"] = valor
        return df.drop(columns=["Notas"])
    msg = _importar_falha(monkeypatch, _editar_professor(tmp, monkeypatch, mudar))
    assert "Coluna 'Notas' nao encontrada na planilha" in msg
    assert "Exceeds the limit" not in msg and "integer string conversion" not in msg
    assert _nada_gravado(tmp)
