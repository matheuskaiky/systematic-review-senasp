"""A triagem da busca de viés no painel (D116): as colunas do modelo preenchidas na tela Referências, o cartão na página
do artigo e a página de cada referência da web, com as consultas por extenso e a triagem do modelo."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, triagem_escopo as TE, vocabulario as V
from config.eixos_tematicos import EIXOS_EXPLORACAO
from dominio import referencias_busca as RB
from painel.app import Contexto, criar_app
from test_triagem_vies import construir_vies

CONJUNTO = {t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts}
TERMOS = {t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts}
EIXO = next(iter(EIXOS_EXPLORACAO))


def _linha(fonte, item_id, **kw):
    l = {"item_id": item_id, "fonte": fonte, "uf": "", "provedor": None, "termos_consulta": [], "status": "elegivel",
         "status_bruto": "alta", "confianca": "alta", "categoria_motivo": None, "justificativa": "trata de viés",
         "termo_gerador": None, "sinal_negativo": None, "dominio_tematico": None, "escopo_geografico": None,
         "tipo_documento": None, "tipo_fonte": "Relatório técnico / literatura cinzenta", "pais_escopo": "Brasil / SP",
         "topicos": "Reconhecimento facial; viés racial", "eixo": EIXO, "valido": True, "problemas": []}
    l.update(kw)
    return l


@pytest.fixture
def banco(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    return tmp_path / "busca.db"


def _triar(banco, linhas, versao=TE.PROMPT_TRIAGEM_VIES_VERSAO, run=None):
    repo = RepositorioSQLite(banco)
    try:
        run = run or repo.iniciar_execucao("triar-escopo", "h", "{}", "c")
        repo.salvar_triagem_escopo(run, None, versao, linhas)
        repo.confirmar()
        return run
    finally:
        repo.fechar()


def _ids(banco):
    con = sqlite3.connect(banco)
    ref = con.execute("SELECT referencia_id FROM referencias_web WHERE url_original = 'https://comum.org/x'").fetchone()[0]
    art = con.execute("SELECT MIN(artigo_id) FROM artigos").fetchone()[0]
    return ref, art


def _cli(banco, tmp_path, **kw):
    ctx = Contexto(banco="vies", nome_banco="busca.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   consultas_literatura=dict(TERMOS), conjunto_da_consulta=dict(CONJUNTO), eixos_exploracao=dict(EIXOS_EXPLORACAO),
                   versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO,
                   versoes_triagem_vies=TE.VERSOES_TRIAGEM_VIES, **kw)
    return TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx))


# ---------- domínio ----------
@pytest.mark.parametrize("triagem, esperado", [
    ({"valido": 1, "tipo_fonte": "Livro", "pais_escopo": "EUA", "topicos": "IA; raça"}, ("Livro", "EUA", "IA; raça")),
    ({"valido": 0, "tipo_fonte": "Livro", "pais_escopo": "EUA", "topicos": "IA"}, ("", "", "")),     # conferência falhou
    ({"valido": 1, "tipo_fonte": None, "pais_escopo": "EUA"}, ("", "EUA", "")),                   # campo nulo ou ausente
    ({"valido": 1}, ("", "", "")), (None, ("", "", "")), ({}, ("", "", "")),
])
def test_colunas_do_modelo_vem_da_triagem_valida(triagem, esperado):
    base = RB.linha_web({"referencia_id": 1, "dominio": "d", "url_original": "https://d/", "titulo": "t", "data_pub": None,
                         "conjuntos": "A", "execucoes": "r"})
    linha = RB.com_triagem(base, triagem)
    assert (linha["Tipo de fonte"], linha["País/escopo"], linha["Tópicos e palavras-chave"]) == esperado
    fora = set(RB.COLUNAS_DA_TRIAGEM) | set(RB.COLUNAS_TRIAGEM_TELA)            # recorte e local tambem vem da triagem
    assert {k: v for k, v in linha.items() if k not in fora} == {k: v for k, v in base.items() if k not in fora}   # nada mais muda


# ---------- leitura ----------
def test_leitura_pega_a_triagem_mais_recente_da_versao_do_vies(banco):
    ref, art = _ids(banco)
    _triar(banco, [_linha("referencia", ref, topicos="antigo")])
    _triar(banco, [_linha("referencia", ref, topicos="novo"), _linha("artigo", art)])
    _triar(banco, [_linha("referencia", ref, topicos="de outro prompt")], versao="t2")
    _triar(banco, [_linha("web", ref, uf="SP", topicos="web")])
    t = LeituraPainelSQLite(banco).triagens_vies(TE.PROMPT_TRIAGEM_VIES_VERSAO)
    assert set(t) == {("referencia", ref), ("artigo", art)} and t[("referencia", ref)]["topicos"] == "novo"
    assert LeituraPainelSQLite(banco).triagens_vies("") == {}


def test_banco_sem_as_colunas_novas_nao_quebra_a_leitura(banco):
    ref, _ = _ids(banco)
    _triar(banco, [_linha("referencia", ref)])
    con = sqlite3.connect(banco)
    for c in ("tipo_fonte", "pais_escopo", "topicos", "eixo"):
        con.execute(f"ALTER TABLE triagem_escopo DROP COLUMN {c}")
    con.commit()
    leitura = LeituraPainelSQLite(banco)
    linha = leitura.triagens_vies(TE.PROMPT_TRIAGEM_VIES_VERSAO)[("referencia", ref)]
    assert "tipo_fonte" not in linha.keys() and leitura.veredito_referencia(ref)["status_bruto"] == "alta"


def test_referencia_web_traz_as_ocorrencias_da_mais_recente_para_a_mais_antiga(banco):
    ref, _ = _ids(banco)
    r = LeituraPainelSQLite(banco).referencia_web(ref)
    assert r["url_original"] == "https://comum.org/x" and [o["consulta_id"] for o in r["ocorrencias"]] == ["LB1", "LA2", "LA1"]
    assert LeituraPainelSQLite(banco).referencia_web(999999) is None


# ---------- tela Referências ----------
def test_tela_e_download_mostram_as_colunas_da_triagem(banco, tmp_path):
    import io
    import openpyxl
    ref, art = _ids(banco)
    _triar(banco, [_linha("referencia", ref), _linha("artigo", art, tipo_fonte="Artigo científico", pais_escopo="EUA",
                                                      topicos="Policiamento preditivo", valido=False)])
    cli = _cli(banco, tmp_path)
    html = cli.get("/literatura/referencias").text
    linha = re.search(rf'<tr><td><a href="/literatura/referencias/web/{ref}">W-{ref}</a></td>.*?</tr>', html, re.S).group(0)
    assert "<td>Relatório técnico / literatura cinzenta</td><td>Brasil / SP</td><td>Reconhecimento facial; viés racial</td>" in linha
    assert "Policiamento preditivo" not in html                       # a triagem do artigo falhou na conferência
    assert EIXO not in html and "trata de viés" not in html             # eixo e justificativa ficam fora da tela
    wb = openpyxl.load_workbook(io.BytesIO(cli.get("/literatura/referencias.xlsx").content))
    linhas = {l[0].value: [c.value for c in l] for l in wb["Referências ampliadas"].iter_rows(min_row=2)}
    assert linhas[f"W-{ref}"][4:7] == ["Relatório técnico / literatura cinzenta", "Brasil / SP", "Reconhecimento facial; viés racial"]


# ---------- página da referência da web ----------
def test_pagina_da_referencia_mostra_consultas_por_extenso_e_a_triagem(banco, tmp_path):
    ref, _ = _ids(banco)
    run = _triar(banco, [_linha("referencia", ref, status_bruto="media")])
    r = _cli(banco, tmp_path).get(f"/literatura/referencias/web/{ref}")
    assert r.status_code == 200
    html = r.text
    assert '<p class="trilha"><a href="/literatura">Literatura</a> › <a href="/literatura/referencias">referências</a> › W-' in html
    for cid in ("LA1", "LA2", "LB1"):
        assert f"<td>{TERMOS[cid]} <small><code>{cid}</code></small></td>" in html
    assert '<a href="https://comum.org/x" rel="noopener noreferrer" target="_blank">https://comum.org/x</a>' in html
    for rotulo, valor in (("Relevância", "Média"), ("Tipo de fonte", "Relatório técnico / literatura cinzenta"),
                          ("País/escopo", "Brasil / SP"), ("Tópicos e palavras-chave", "Reconhecimento facial; viés racial"),
                          ("Eixo de exploração", EIXO), ("Justificativa", "trata de viés")):
        assert f"<dt>{rotulo}</dt><dd>{valor}</dd>" in html
    assert f'<a href="/execucoes/{run}?configuracao=1#configuracao"><code>{run}</code></a> · prompt v2' in html


def test_referencia_sem_triagem_e_inexistente(banco, tmp_path):
    ref, _ = _ids(banco)
    cli = _cli(banco, tmp_path)
    assert "Esta referência ainda não foi avaliada pelo modelo." in cli.get(f"/literatura/referencias/web/{ref}").text
    assert cli.get("/literatura/referencias/web/999999").status_code == 404
    assert cli.get("/literatura/referencias/web/abc").status_code == 404
    assert cli.get("/literatura/referencias/web/99999999999999999999999").status_code == 404


def test_referencia_com_texto_perigoso_e_url_que_nao_e_http(banco, tmp_path):
    ref, _ = _ids(banco)
    con = sqlite3.connect(banco)
    con.execute("UPDATE ocorrencias_web SET snippet = '<script>x</script>' WHERE referencia_id = ?", (ref,))
    con.execute("UPDATE referencias_web SET url_original = 'javascript:alert(1)' WHERE referencia_id = ?", (ref,))
    con.commit()
    html = _cli(banco, tmp_path).get(f"/literatura/referencias/web/{ref}").text
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript' not in html and "javascript:alert(1) <small>(endereço não é http/https)</small>" in html


def test_triagem_que_falhou_mostra_os_problemas(banco, tmp_path):
    ref, _ = _ids(banco)
    _triar(banco, [_linha("referencia", ref, valido=False, problemas=["topicos_invalidos"], topicos=None)])
    html = _cli(banco, tmp_path).get(f"/literatura/referencias/web/{ref}").text
    assert "conferência falhou" in html and "<dt>Conferência</dt><dd>falhou: topicos_invalidos</dd>" in html
    assert "<dt>Tópicos e palavras-chave</dt><dd>—</dd>" in html


# ---------- página do artigo ----------
def test_artigo_mostra_o_cartao_da_triagem_vies_e_o_antigo_continua(banco, tmp_path):
    _, art = _ids(banco)
    _triar(banco, [_linha("artigo", art, tipo_fonte="Artigo científico")])
    html = _cli(banco, tmp_path).get(f"/literatura/artigos/{art}").text
    assert "<dt>Tipo de fonte</dt><dd>Artigo científico</dd>" in html and "Área temática" not in html
    assert '<details class="cartao apoio-pos-decisao" open>' in html          # no banco vies a opinião do modelo vem aberta
    _triar(banco, [_linha("artigo", art, dominio_tematico="seguranca_publica", tipo_fonte=None)], versao="t2")
    html = _cli(banco, tmp_path).get(f"/literatura/artigos/{art}").text
    assert "Área temática" in html and "<dt>Tipo de fonte</dt>" not in html      # a triagem t2 mais recente vale


def test_artigo_com_triagem_vies_da_versao_anterior_mostra_a_ficha_do_vies(banco, tmp_path):
    _, art = _ids(banco)
    _triar(banco, [_linha("artigo", art, tipo_fonte="Artigo científico")], versao="v1")
    html = _cli(banco, tmp_path).get(f"/literatura/artigos/{art}").text
    assert "<dt>Tipo de fonte</dt><dd>Artigo científico</dd>" in html and "Termo gerador" not in html


# ---------- página da execução ----------
def test_bloco_da_configuracao_diz_abrir_ou_fechar(banco, tmp_path):
    run = _triar(banco, [])
    for rota in (f"/execucoes/{run}?configuracao=1", f"/execucoes/{run}"):
        assert "Configuração desta execução <small>(clique para abrir ou fechar)</small>" in _cli(banco, tmp_path).get(rota).text


# ---------- PostgreSQL ----------
def test_postgres_igual_ao_sqlite(banco, tmp_path, pg_url):
    from adaptadores import migrador_postgres as M
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres import importador as I
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    ref, art = _ids(banco)
    _triar(banco, [_linha("referencia", ref, topicos="antigo"), _linha("artigo", art, topicos="antigo")])
    _triar(banco, [_linha("referencia", ref), _linha("artigo", art)])          # a mais recente vence também no PostgreSQL
    M.aplicar(pg_url)
    I.importar(banco, pg_url)
    pool = criar_pool(pg_url, maximo=2)
    try:
        sq, pg = LeituraPainelSQLite(banco), LeituraPainelPostgres(pool, chaves_do_banco(pool))

        def plano(d):
            return {k: {c: v for c, v in dict(l).items() if c not in ("id", "criado_em")} for k, l in d.items()}
        assert plano(pg.triagens_vies(TE.PROMPT_TRIAGEM_VIES_VERSAO)) == plano(sq.triagens_vies(TE.PROMPT_TRIAGEM_VIES_VERSAO))
        assert pg.triagens_vies(TE.PROMPT_TRIAGEM_VIES_VERSAO)[("referencia", ref)]["topicos"] == "Reconhecimento facial; viés racial"
        assert pg.veredito_referencia(ref)["topicos"] == sq.veredito_referencia(ref)["topicos"]
        a, b = dict(sq.referencia_web(ref)), dict(pg.referencia_web(ref))
        assert [dict(o) for o in a.pop("ocorrencias")] == [dict(o) for o in b.pop("ocorrencias")] and a == b
    finally:
        pool.close()


# ---------- números de linha no endereço ----------
G = "99999999999999999999999"


@pytest.mark.parametrize("rota", [
    f"/literatura/referencias/web/{G}", f"/literatura/artigos/{G}", f"/achados/{G}", f"/chamadas/{G}",
    "/chamadas/9223372036854775808/bruto", "/literatura/referencias/web/0", "/literatura/artigos/-1", "/achados/0",
])
def test_numero_fora_do_que_o_banco_aceita_e_endereco_invalido(rota, banco, tmp_path):
    r = TestClient(_cli(banco, tmp_path).app, raise_server_exceptions=False).get(rota)
    assert r.status_code == 404 and "Endereço inválido" in r.text


def test_o_maior_numero_aceito_so_nao_existe(banco, tmp_path):
    r = _cli(banco, tmp_path).get("/literatura/artigos/9223372036854775807")
    assert r.status_code == 404 and "Artigo não encontrado" in r.text


@pytest.mark.parametrize("rota", [
    f"/literatura/artigos/{G}/triar", f"/achados/{G}/verificar", f"/achados/{G}/desfazer", f"/achados/{G}/revogar",
    f"/achados/{G}/sugerir", f"/literatura/artigos/{G}/sugerir", f"/achados/1/sugestoes/{G}/aceitar",
    f"/literatura/artigos/1/sugestoes/{G}/aceitar",
])
def test_gravacao_com_numero_grande_tambem_e_endereco_invalido(rota, banco, tmp_path):
    r = TestClient(_cli(banco, tmp_path).app, raise_server_exceptions=False).post(rota, data={"decisao": "incluir"})
    assert r.status_code == 404 and "Endereço inválido" in r.text


def test_no_banco_real_a_opiniao_do_modelo_continua_recolhida(banco, tmp_path):
    _, art = _ids(banco)
    ctx = Contexto(banco="real", nome_banco="busca.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",))
    html = TestClient(criar_app(LeituraPainelSQLite(banco), lambda: None, BrutoLocal(tmp_path), ctx)).get(f"/literatura/artigos/{art}").text
    assert '<details class="cartao apoio-pos-decisao">' in html


def test_artigo_excluido_pela_triagem_vies_mostra_o_aviso(banco, tmp_path):
    _, art = _ids(banco)
    _triar(banco, [_linha("artigo", art, status="excluido", status_bruto="fora_do_escopo")])
    html = _cli(banco, tmp_path).get(f"/literatura/artigos/{art}").text
    assert "<strong>Excluído pelo modelo.</strong>" in html and "<dt>Relevância</dt><dd>Fora do escopo</dd>" in html


def test_artigo_com_triagem_vies_invalida_mostra_a_falha(banco, tmp_path):
    _, art = _ids(banco)
    _triar(banco, [_linha("artigo", art, valido=False, problemas=["eixo_invalido", "pais_escopo_invalido"], eixo=None)])
    html = _cli(banco, tmp_path).get(f"/literatura/artigos/{art}").text
    assert "<dt>Conferência</dt><dd>falhou: eixo_invalido, pais_escopo_invalido</dd>" in html and "<dt>Eixo de exploração</dt><dd>nenhum</dd>" in html


def test_consulta_desconhecida_e_campos_nulos(banco, tmp_path):
    ref, _ = _ids(banco)
    con = sqlite3.connect(banco)
    con.execute("UPDATE ocorrencias_web SET consulta_id = 'ZZ9', posicao = NULL, titulo = NULL, data_pub = NULL "
                "WHERE referencia_id = ?", (ref,))
    con.commit()
    html = _cli(banco, tmp_path).get(f"/literatura/referencias/web/{ref}").text
    assert "<td><code>ZZ9</code></td>" in html and "ZZ9 <small>" not in html
    assert "<h1>comum.org</h1>" in html                                    # sem título: o domínio, nunca a URL longa


def test_paginas_abrem_em_banco_sem_as_colunas_novas_e_sem_a_tabela(banco, tmp_path):
    ref, art = _ids(banco)
    _triar(banco, [_linha("referencia", ref), _linha("artigo", art)])
    con = sqlite3.connect(banco)
    for c in ("tipo_fonte", "pais_escopo", "topicos", "eixo"):
        con.execute(f"ALTER TABLE triagem_escopo DROP COLUMN {c}")
    con.commit()
    cli = _cli(banco, tmp_path)
    for rota in (f"/literatura/referencias/web/{ref}", f"/literatura/artigos/{art}", "/literatura/referencias"):
        assert cli.get(rota).status_code == 200
    con.execute("DROP TABLE triagem_escopo")
    con.commit()
    for rota in (f"/literatura/referencias/web/{ref}", f"/literatura/artigos/{art}", "/literatura/referencias"):
        assert cli.get(rota).status_code == 200


def test_sem_permissao_de_ver_execucoes_o_numero_da_execucao_e_so_texto(banco, tmp_path):
    from adaptadores.contas_sqlite import ContasSQLite
    from dominio import autenticacao as A
    ref, _ = _ids(banco)
    run = _triar(banco, [_linha("referencia", ref)])
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    grupos = {g["nome"]: g["grupo_id"] for g in contas.grupos()}
    contas.criar_usuario("leitor", "leitor", grupos["Leitor"], A.hash_senha("senha-de-teste-123"), "2026-10-22T00:00:00+00:00")
    ctx = Contexto(banco="vies", nome_banco="busca.db", somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   consultas_literatura=dict(TERMOS), versao_triagem_vies="v1", autenticacao=True)
    cli = TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas))
    csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get("/entrar").text).group(1)
    assert cli.post("/entrar", data={"login": "leitor", "senha": "senha-de-teste-123", "proximo": "/", "csrf": csrf},
                    follow_redirects=False).status_code == 303
    html = cli.get(f"/literatura/referencias/web/{ref}").text
    assert f"<code>{run}</code>" in html and 'href="/execucoes/' not in html.replace('href="/execucoes/comparar"', "")
