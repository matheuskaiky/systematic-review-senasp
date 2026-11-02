"""Artigos mais citados e a nota de citacoes contam so os artigos visiveis: os que a triagem de escopo do modelo excluiu e
ninguem decidiu ficam fora, como nas outras contagens da pagina; uma decisao humana sempre vence o modelo (D116). Vale na pagina
/literatura e no relatorio estatico."""
import sqlite3

import pytest

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from test_apresentacao_publica import _nunca_abre_o_data_real  # noqa: F401
from test_painel import demo  # noqa: F401
from test_painel_literatura import _veredito_escopo, ctx  # noqa: F401


def _q(copia, sql, *a):
    return sqlite3.connect(copia).execute(sql, a).fetchall()


def _exec(copia, sql, *a):
    c = sqlite3.connect(copia)
    c.execute(sql, a)
    c.commit()
    c.close()


def _preparar(copia):
    """Quatro artigos:
    - pendente com o maior numero de citacoes, excluido pelo modelo -> oculto;
    - pendente sem contagem de citacoes, excluido pelo modelo -> oculto (conta para `sem_citacoes` so se a regra falhar);
    - decidido por uma pessoa, excluido pelo modelo -> continua visivel (a decisao humana vence) e entra no ranking;
    - pendente visivel, empatado em citacoes com o decidido -> o empate sai pela ordem de artigo_id."""
    pend = [r[0] for r in _q(copia, "SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id "
                                    "WHERE COALESCE(t.decisao,'pendente')='pendente' ORDER BY a.artigo_id LIMIT 3")]
    decidido = _q(copia, "SELECT artigo_id FROM triagem WHERE decisao IN ('incluir','excluir') ORDER BY artigo_id LIMIT 1")[0][0]
    oculto, oculto_sem, visivel = pend
    _exec(copia, "UPDATE artigos SET citacoes=999999 WHERE artigo_id=?", oculto)
    _exec(copia, "UPDATE artigos SET citacoes=NULL WHERE artigo_id=?", oculto_sem)
    _exec(copia, "UPDATE artigos SET citacoes=888888 WHERE artigo_id IN (?, ?)", decidido, visivel)
    for i in (oculto, oculto_sem, decidido):
        _veredito_escopo(copia, i)
    return {"oculto": oculto, "oculto_sem": oculto_sem, "decidido": decidido, "visivel": visivel}


def _visiveis(copia):
    """O universo visivel, pela mesma base do leitor (a mesma regra das demais contagens da pagina)."""
    leitura = LeituraPainelSQLite(copia)
    return {r["artigo_id"]: r["citacoes"] for r in leitura._consulta(f"SELECT artigo_id, citacoes FROM ({leitura._BASE_ARTIGOS}) "
                                                                     "WHERE llm_oculto = 0")}


def test_ranking_sem_os_ocultos_com_a_decisao_humana_e_desempate(ctx):  # noqa: F811
    _, copia, _ = ctx
    p = _preparar(copia)
    d = LeituraPainelSQLite(copia).literatura()
    ids = [a["artigo_id"] for a in d["mais_citados"]]
    assert p["oculto"] not in ids
    assert ids[:2] == sorted([p["decidido"], p["visivel"]])                 # empate em 888888: menor artigo_id primeiro
    assert len(ids) == 10
    vis = _visiveis(copia)
    esperado = sorted((i for i, c in vis.items() if c is not None), key=lambda i: (-vis[i], i))[:10]
    assert ids == esperado
    assert all(set(a) == {"artigo_id", "titulo", "ano", "citacoes"} for a in d["mais_citados"])


def test_contagens_de_citacoes_no_universo_visivel(ctx):  # noqa: F811
    _, copia, _ = ctx
    _preparar(copia)
    d = LeituraPainelSQLite(copia).literatura()
    vis = _visiveis(copia)
    assert d.get("com_citacoes") == sum(1 for c in vis.values() if c is not None)
    assert d["sem_citacoes"] == sum(1 for c in vis.values() if c is None)
    assert (d.get("com_citacoes") or 0) + d["sem_citacoes"] == d["n_artigos"] == len(vis)


def _nota(n, com, sem):
    return f"Artigos visíveis: {n}; com contagem de citações: {com}; sem contagem (a fonte não informou): {sem}."


def _cartao_citados(h):
    return h.split("Artigos mais citados")[1].split("</section>")[0]


def test_pagina_mostra_a_nota_dentro_do_cartao(ctx):  # noqa: F811
    cli, copia, _ = ctx
    p = _preparar(copia)
    d = LeituraPainelSQLite(copia).literatura()
    cartao = _cartao_citados(cli.get("/literatura").text)
    assert f"<p><small>{_nota(d['n_artigos'], d.get('com_citacoes'), d['sem_citacoes'])}</small></p>" in cartao
    assert f'href="/literatura/artigos/{p["oculto"]}"' not in cartao and f'href="/literatura/artigos/{p["decidido"]}"' in cartao
    assert "sem contagem de citações (não informada pela fonte)" not in cartao


def test_pagina_formata_os_numeros_da_nota(ctx, monkeypatch):  # noqa: F811
    cli, _copia, _ = ctx
    original = LeituraPainelSQLite.literatura
    monkeypatch.setattr(LeituraPainelSQLite, "literatura",
                        lambda self: {**original(self), "n_artigos": 1240, "com_citacoes": 542, "sem_citacoes": 698})
    assert _nota("1.240", "542", "698") in _cartao_citados(cli.get("/literatura").text)


def test_pagina_sem_artigos_visiveis_nao_mostra_a_nota(ctx, monkeypatch):  # noqa: F811
    cli, _copia, _ = ctx
    original = LeituraPainelSQLite.literatura
    monkeypatch.setattr(LeituraPainelSQLite, "literatura",
                        lambda self: {**original(self), "n_artigos": 0, "com_citacoes": 0, "sem_citacoes": 0, "mais_citados": []})
    assert "Artigos visíveis:" not in cli.get("/literatura").text


@pytest.mark.parametrize("n,com,sem,texto", [(119, 110, 9, ("119", "110", "9")), (1240, 542, 698, ("1.240", "542", "698"))])
def test_relatorio_estatico_usa_o_mesmo_ranking_e_a_mesma_nota(ctx, n, com, sem, texto):  # noqa: F811
    _, copia, _ = ctx
    p = _preparar(copia)
    from painel import relatorio
    titulos = dict(_q(copia, "SELECT artigo_id, titulo FROM artigos WHERE artigo_id IN (?, ?)", p["oculto"], p["decidido"]))
    leitura = LeituraPainelSQLite(copia)
    lit = {**leitura.literatura(), "n_artigos": n, "com_citacoes": com, "sem_citacoes": sem}
    html = relatorio._literatura({"literatura": lit, "triagem": leitura.contagem_triagem(), "termos": {}})
    trecho = html.split("Artigos mais citados")[1].split("<h3>")[0]
    assert titulos[p["decidido"]] in trecho and titulos[p["oculto"]] not in trecho
    assert f"<p><small>{_nota(*texto)}</small></p>" in trecho
