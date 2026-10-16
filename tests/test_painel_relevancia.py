"""Relevancia Brasil + tema no painel: selos, filtro, ordenacao, fila de triagem, cartao da visao geral e seguranca."""
import hashlib
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401

from dominio.relevancia import pontuar_relevancia  # noqa: E402

# (titulo, snippet, autores, link) semeados nos primeiros artigos da copia; o resto da demonstracao so tem tema (media)
SEMENTES = [
    ("Reconhecimento facial na segurança pública: desafios para a Polícia Militar", "Estudo de caso no Brasil.", "A Silva - Revista Exemplo", "https://revista-1.example/a"),
    ("Policiamento preditivo no Brasil: análise de dados criminais em São Paulo", "", "B Souza", "https://revista-2.example/b"),
    ("Computer vision for facial recognition: advances and risks", "A benchmark.", "J Smith - Journal of Vision", "https://revista-3.example/c"),
    ("Automatic detection of people with reduced mobility using YOLOv5", "", "K Lee", "https://revista-4.example/d"),
    ("Aprendizado de máquina para o reconhecimento facial aplicado a fechaduras inteligentes", "", "C Lima", "http://repositorio.unesc.net/handle/1/9"),
    ("Predictive policing in the United States: a review", "", "D Brown", "https://revista-5.example/e"),
    ("Detecção de objetos com redes convolucionais", "", "E Rocha", "https://repositorio.exemplo.br/f"),
]


@pytest.fixture
def ctx(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    conn = sqlite3.connect(copia)
    ids = [l[0] for l in conn.execute("SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT ?", (len(SEMENTES),))]
    for i, (t, s, a, l) in zip(ids, SEMENTES):
        conn.execute("UPDATE artigos SET titulo=?, snippet=?, autores_publicacao=?, link=?, chave_dedup=? WHERE artigo_id=?",
                     (t, s, a, l, hashlib.sha1(t.encode()).hexdigest(), i))
    conn.commit()
    conn.close()
    app, c = _app(copia, raw, tmp_path)
    c.termos = {"T01": '"reconhecimento facial"'}
    c.bases = ("IEEE", "ACM", "Scopus", "SBC OpenLib")
    return TestClient(app), copia, ids


def _linhas(copia):
    c = sqlite3.connect(copia)
    c.row_factory = sqlite3.Row
    return [dict(l) for l in c.execute("SELECT * FROM r_artigos ORDER BY artigo_id")]


def _niveis(copia):
    return {l["artigo_id"]: pontuar_relevancia(l["titulo"], l["snippet"], l["autores_publicacao"], l["link"])["nivel"] for l in _linhas(copia)}


def _total(cli, rota):
    return int(re.search(r"<strong>([\d.]+)</strong> artigo", cli.get(rota).text).group(1).replace(".", ""))


def _ids_da_pagina(html):
    return [int(i) for i in re.findall(r'<td><a href="/literatura/artigos/(\d+)">', html)]


def _hash(copia):
    return hashlib.sha256(Path(copia).read_bytes()).hexdigest()


def test_lista_mostra_o_selo_com_texto_e_icone(ctx):
    cli, copia, ids = ctx
    h = cli.get("/literatura/artigos?ordem=relevancia").text
    assert "<th>Relevância</th>" in h
    assert "Alta · Brasil + tema" in h and "Média · só Brasil" in h and "Média · só tema" in h
    assert "Baixa" in cli.get("/literatura/artigos?rel=baixa").text
    assert 'class="selo rel-alta"' in h and 'aria-hidden="true">▲' in h
    assert '<link rel="stylesheet" href="/static/relevancia.css">' in h
    assert cli.get("/static/relevancia.css").status_code == 200


def test_lista_traz_selects_e_a_regra_com_as_listas_de_marcadores(ctx):
    cli, _, _ = ctx
    h = cli.get("/literatura/artigos?rel=media&ordem=relevancia").text
    assert '<select name="rel">' in h and '<select name="ordem">' in h
    assert re.search(r'<option value="media" selected>', h) and re.search(r'<option value="relevancia" selected>', h)
    assert "mais relevantes primeiro" in h and "padrão da triagem" in h
    assert "<details" in h and "Como a relevância é calculada" in h
    for esperado in ("polícia militar", "segurança pública", "brasileir*", "law enforcement", "unesc.net"):
        assert esperado in h


def test_filtro_rel_confere_com_recalculo_em_python(ctx):
    cli, copia, _ = ctx
    niveis = _niveis(copia)
    for nivel in ("alta", "media", "baixa"):
        esperado = sum(1 for n in niveis.values() if n == nivel)
        assert _total(cli, f"/literatura/artigos?rel={nivel}") == esperado, nivel
    assert {n for n in niveis.values()} == {"alta", "media", "baixa"}
    assert sum(_total(cli, f"/literatura/artigos?rel={n}") for n in ("alta", "media", "baixa")) == _total(cli, "/literatura/artigos")


def test_filtro_rel_so_lista_artigos_do_nivel_e_pagina(ctx):
    cli, copia, _ = ctx
    niveis = _niveis(copia)
    media = [i for i, n in niveis.items() if n == "media"]
    assert len(media) > 50           # a demonstracao tem so tema: duas paginas
    p1 = _ids_da_pagina(cli.get("/literatura/artigos?rel=media").text)
    p2 = _ids_da_pagina(cli.get("/literatura/artigos?rel=media&p=2").text)
    assert len(p1) == 50 and set(p1 + p2) <= set(media) and not set(p1) & set(p2)
    assert len(p1) + len(p2) == min(len(media), 100)


def test_filtro_rel_combina_com_os_filtros_sql(ctx):
    cli, copia, _ = ctx
    niveis = _niveis(copia)
    c = sqlite3.connect(copia)
    com_termo = {l[0] for l in c.execute("SELECT DISTINCT artigo_id FROM r_ocorrencias WHERE termo_id='T01'")}
    esperado = sum(1 for i, n in niveis.items() if n == "media" and i in com_termo)
    assert _total(cli, "/literatura/artigos?rel=media&termo=T01") == esperado


def test_ordem_relevancia_poe_alta_primeiro_e_respeita_a_media(ctx):
    cli, copia, ids = ctx
    niveis = _niveis(copia)
    lista = _ids_da_pagina(cli.get("/literatura/artigos?ordem=relevancia").text)
    assert {niveis[i] for i in lista[:2]} == {"alta"} and niveis[lista[2]] == "media"
    linhas = {l["artigo_id"]: pontuar_relevancia(l["titulo"], l["snippet"], l["autores_publicacao"], l["link"])["pontos"] for l in _linhas(copia)}
    pontos = [linhas[i] for i in lista]
    assert pontos == sorted(pontos, reverse=True)
    # sem a ordenacao, a ordem continua a da triagem
    assert _ids_da_pagina(cli.get("/literatura/artigos").text) != lista


def test_ordem_relevancia_total_e_o_mesmo_e_empates_seguem_a_triagem(ctx):
    cli, _, _ = ctx
    assert _total(cli, "/literatura/artigos?ordem=relevancia") == _total(cli, "/literatura/artigos")
    # na demonstracao, os artigos de relevancia "so tema" empatam em pontos: a ordem de triagem desempata
    rotas = ("/literatura/artigos?rel=baixa", "/literatura/artigos?rel=baixa&ordem=relevancia")
    assert _ids_da_pagina(cli.get(rotas[0]).text) == _ids_da_pagina(cli.get(rotas[1]).text)


def test_fila_de_triagem_respeita_rel_e_ordem(ctx):
    cli, copia, _ = ctx
    niveis = _niveis(copia)
    c = sqlite3.connect(copia)
    triados = {l[0] for l in c.execute("SELECT artigo_id FROM triagem WHERE decisao<>'pendente'")}
    alta_pendentes = [i for i, n in niveis.items() if n == "alta" and i not in triados]
    assert alta_pendentes, "a semente precisa deixar artigos de relevancia alta pendentes"
    r = cli.get("/literatura/triagem?rel=alta", follow_redirects=False)
    assert r.status_code == 303
    destino = r.headers["location"]
    assert int(re.search(r"/artigos/(\d+)", destino).group(1)) in alta_pendentes and "rel=alta" in destino and "fila=1" in destino
    pagina = cli.get(destino).text
    assert f"{len(alta_pendentes)} pendente(s)" in pagina
    # ordenando por relevancia, a fila comeca por um artigo pendente de relevancia alta
    r = cli.get("/literatura/triagem?ordem=relevancia", follow_redirects=False)
    assert int(re.search(r"/artigos/(\d+)", r.headers["location"]).group(1)) in alta_pendentes
    # sem pendentes para os filtros, a fila mostra a tela de fila vazia
    assert "Nenhum artigo pendente" in cli.get("/literatura/triagem?rel=alta&termo=T99").text


def test_link_triar_pendentes_da_lista_leva_o_filtro(ctx):
    cli, _, _ = ctx
    h = cli.get("/literatura/artigos?rel=alta&ordem=relevancia").text
    assert re.search(r'href="/literatura/triagem\?[^"]*rel=alta', h) and "ordem=relevancia" in re.search(r'href="(/literatura/triagem\?[^"]*)"', h).group(1)


def test_rel_desconhecido_e_ignorado_sem_erro(ctx):
    cli, _, _ = ctx
    todos = _total(cli, "/literatura/artigos")
    for lixo in ("rel=xyz", "rel=ALTA", "rel=", "ordem=qualquer", "rel=alta%27%20OR%201%3D1", "rel=%00"):
        r = cli.get(f"/literatura/artigos?{lixo}")
        assert r.status_code == 200, lixo
        assert _total(cli, f"/literatura/artigos?{lixo}") == todos, lixo
    assert cli.get("/literatura/triagem?rel=xyz", follow_redirects=False).status_code == 303


def test_pagina_invalida_continua_404(ctx):
    cli, _, _ = ctx
    for p in ("abc", "0", "-1", "99999999999999999999"):
        assert cli.get(f"/literatura/artigos?rel=alta&p={p}").status_code == 404, p
    r = cli.get("/literatura/artigos?rel=alta&p=999")
    assert r.status_code == 200 and "Não há artigos nesta página" in r.text


def test_pagina_do_artigo_mostra_selo_sinais_e_explicacao(ctx):
    cli, copia, ids = ctx
    h = cli.get(f"/literatura/artigos/{ids[0]}").text
    assert "Alta · Brasil + tema" in h and "sinais encontrados" in h
    for sinal in ("polícia militar", "segurança pública"):
        assert sinal in h
    assert "heurística de apoio à triagem, não uma decisão" in h
    h2 = cli.get(f"/literatura/artigos/{ids[3]}").text
    assert "Baixa" in h2 and "nenhum sinal encontrado" in h2
    h3 = cli.get(f"/literatura/artigos/{ids[4]}").text
    assert "Média · só Brasil" in h3 and "unesc.net" in h3
    h4 = cli.get(f"/literatura/artigos/{ids[5]}").text
    assert "Média · só tema" in h4 and "policing" in h4


def test_visao_geral_tem_o_cartao_com_os_numeros_certos(ctx):
    cli, copia, _ = ctx
    niveis = list(_niveis(copia).values())
    h = cli.get("/literatura").text
    assert "Relevância para Brasil + segurança pública" in h
    for nivel in ("alta", "media", "baixa"):
        n = niveis.count(nivel)
        assert re.search(rf'href="/literatura/artigos\?rel={nivel}"><strong>{n}</strong>', h), nivel
    assert sum(niveis.count(n) for n in ("alta", "media", "baixa")) == len(niveis)


def test_xss_no_titulo_continua_escapado_na_lista_e_no_artigo(ctx):
    cli, copia, ids = ctx
    c = sqlite3.connect(copia)
    c.execute("UPDATE artigos SET titulo=?, snippet=?, autores_publicacao=? WHERE artigo_id=?",
              ("<script>alert(1)</script> Polícia no Brasil", "<img src=x onerror=alert(2)> crime", '"><b>autor</b>', ids[6]))
    c.commit()
    c.close()
    for rota in ("/literatura/artigos?rel=alta", "/literatura/artigos?ordem=relevancia", f"/literatura/artigos/{ids[6]}"):
        h = cli.get(rota).text
        assert "<script>alert(1)" not in h and "<img src=x" not in h and "<b>autor</b>" not in h, rota
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in cli.get(f"/literatura/artigos/{ids[6]}").text
    # parametros refletidos tambem saem escapados
    h = cli.get("/literatura/artigos?q=%3Cscript%3Ex%3C/script%3E&rel=%3Cb%3E").text
    assert "<script>x" not in h and "<b>" not in h


def test_paginas_nao_tem_script_nem_estilo_inline(ctx):
    cli, _, ids = ctx
    for rota in ("/literatura", "/literatura/artigos?rel=alta", f"/literatura/artigos/{ids[0]}"):
        h = cli.get(rota).text
        assert not re.search(r"<script(?![^>]*\bsrc=)", h) and "style=" not in h, rota


def test_nenhuma_pagina_de_leitura_grava_no_banco(ctx):
    cli, copia, ids = ctx
    antes = _hash(copia)
    for rota in ("/literatura", "/literatura/artigos", "/literatura/artigos?rel=alta", "/literatura/artigos?rel=baixa&ordem=relevancia&p=2",
                 f"/literatura/artigos/{ids[0]}", f"/literatura/artigos/{ids[0]}?fila=1&rel=alta", "/literatura/triagem?rel=media&ordem=relevancia",
                 "/literatura/artigos?rel=zzz"):
        cli.get(rota, follow_redirects=False)
    assert _hash(copia) == antes


def test_tamanho_maximo_da_pagina_e_respeitado_com_pontuacao(demo):
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    leitura = LeituraPainelSQLite(demo[0])
    res = leitura.artigos({"ordem": "relevancia"}, 1, 10_000)
    assert res["por_pagina"] == 200 and len(res["itens"]) <= 200
    assert all("relevancia" in i and i["relevancia"]["nivel"] in ("alta", "media", "baixa") for i in res["itens"])
    sem = leitura.artigos({}, 1, 5)
    assert len(sem["itens"]) == 5 and all("relevancia" in i for i in sem["itens"])
    assert leitura.artigo(sem["itens"][0]["artigo_id"])["relevancia"]["nivel"] in ("alta", "media", "baixa")
