"""Relatorio estatico (painel-relatorio): um arquivo, sem scripts nem recursos externos, so achados confirmados por padrao,
numeros iguais aos das views, texto coletado escapado e o comando de linha de comando."""
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

import config.settings as S
import main
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C
from painel import formatacao as fmt, relatorio
from painel.metodologia_texto import gerar_metodologia, para_texto
from test_painel import demo  # noqa: F401

ESTATICOS = Path(relatorio.__file__).parent / "static"
CSS = "\n".join((ESTATICOS / n).read_text(encoding="utf-8") for n in ("painel.css", "metodologia.css"))
UNICA_CONFIRMADA = "EVIDENCIA-UNICA-CONFIRMADA-7391"
UNICA_PENDENTE = "EVIDENCIA-UNICA-PENDENTE-4825"


def _html(banco, incluir=False, nome="demo.db", tipo="demo"):
    dados = relatorio.coletar_dados(LeituraPainelSQLite(banco), dict(C.UFS), {t.id: t.query for t in C.TERMOS}, tuple(C.BASES_MANUAIS),
                                    tipo, nome, "2026-10-15T14:30:00", incluir)
    return relatorio.montar_relatorio(dados, incluir, CSS), dados


def _sql(banco, sql, *a):
    conn = sqlite3.connect(banco)
    try:
        return conn.execute(sql, a).fetchone()[0]
    finally:
        conn.close()


def _exec(banco, sql, *a):
    conn = sqlite3.connect(banco)
    conn.execute(sql, a)
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def banco_demo(demo):
    return demo[0]


@pytest.fixture
def copia(demo, tmp_path):
    """Copia do banco com uma evidencia unica num achado confirmado e noutro pendente (a demo repete as mesmas frases)."""
    destino = tmp_path / "demo.db"
    shutil.copy(demo[0], destino)
    conf = _sql(destino, "SELECT achado_id FROM v_secretarias_confirmadas ORDER BY achado_id LIMIT 1")
    pend = _sql(destino, "SELECT achado_id FROM r_achados WHERE verificado=0 ORDER BY achado_id LIMIT 1")
    _exec(destino, "UPDATE achados SET evidencia=? WHERE achado_id=?", UNICA_CONFIRMADA, conf)
    _exec(destino, "UPDATE achados SET evidencia=? WHERE achado_id=?", UNICA_PENDENTE, pend)
    return destino


# ---------- autocontido: sem scripts e sem recurso externo ----------
@pytest.mark.parametrize("incluir", [False, True])
def test_arquivo_sem_script_sem_recurso_externo_e_sem_http_fora_dos_links_de_fonte(banco_demo, incluir):
    html, _ = _html(banco_demo, incluir)
    baixo = html.lower()
    assert "<script" not in baixo and "javascript:" not in baixo and "onclick" not in baixo and "onerror" not in baixo
    assert "src=" not in baixo and "<link" not in baixo and "@import" not in baixo and "url(" not in baixo
    assert "<iframe" not in baixo and "<img" not in baixo and "<object" not in baixo
    sem_fontes = re.sub(r'href="https?://[^"]*"', 'href=""', html)
    assert "http" not in sem_fontes.lower()
    # os unicos href que restam sao ancoras internas do indice e links de fonte
    assert all(h.startswith("#") or h.startswith("http") for h in re.findall(r'href="([^"]*)"', html))
    assert "/estados/" not in html                    # o mapa nao aponta para paginas do painel
    assert '<style>' in html and html.startswith("<!doctype html>")


def test_links_de_fonte_abrem_com_noopener_e_so_http(banco_demo):
    html, _ = _html(banco_demo, True)
    links = re.findall(r'<a href="(https?://[^"]*)"([^>]*)>', html)
    assert links
    assert all('target="_blank" rel="noopener noreferrer"' in resto for _, resto in links)


def test_tema_escuro_nao_vai_no_arquivo(banco_demo):
    html, _ = _html(banco_demo)
    assert "prefers-color-scheme" not in html
    assert "@media print" in html and "color-scheme: light" in html


def test_remocao_do_tema_escuro_preserva_o_resto_do_css():
    css = "a{x:1} @media (prefers-color-scheme: dark) { :root{--a:1} @media x {b{y:2}} } c{z:3} @media (max-width: 9px) { d{w:4} }"
    saida = relatorio._sem_tema_escuro(css)
    assert "dark" not in saida and "a{x:1}" in saida and "c{z:3}" in saida and "@media (max-width: 9px) { d{w:4} }" in saida


# ---------- so o que um humano confirmou ----------
def test_por_padrao_so_achados_confirmados_e_nenhum_nao_verificado(copia):
    html, dados = _html(copia, incluir=False)
    assert UNICA_CONFIRMADA in html and UNICA_PENDENTE not in html
    assert 'class="aviso-nv"' not in html and "Achados NÃO verificados" not in html
    assert relatorio.AVISO_NAO_VERIFICADO not in html.split('id="achados-confirmados"', 1)[1].split("</section>", 1)[0]
    assert dados["nao_verificados"] == []
    assert "somente achados confirmados por humano" in html


def test_com_a_opcao_cada_nao_verificado_carrega_o_aviso_escrito(copia):
    html, dados = _html(copia, incluir=True)
    assert UNICA_CONFIRMADA in html and UNICA_PENDENTE in html
    pendentes = _sql(copia, "SELECT COUNT(*) FROM v_achados_revisao WHERE verificado=0")
    assert pendentes > 20 and len(dados["nao_verificados"]) == pendentes
    secao = html.split('id="achados-nao-verificados"', 1)[1].split("</section>", 1)[0]
    linhas = [l for l in re.findall(r'<tr class="nv">.*?</tr>', secao, re.S)]
    assert len(linhas) == pendentes
    assert all(relatorio.AVISO_NAO_VERIFICADO in l and 'class="aviso-nv"' in l for l in linhas)
    # nenhuma linha de achado confirmado leva o aviso e nenhuma de nao verificado se passa por confirmada
    conf = html.split('id="achados-confirmados"', 1)[1].split("</section>", 1)[0]
    assert 'class="aviso-nv"' not in conf and 'class="ver-ok"' not in secao
    assert "Hipótese do modelo, não é resultado" in secao
    assert html.count('class="aviso-nv"') == pendentes


def test_os_descartados_nunca_aparecem(copia):
    descartado = _sql(copia, "SELECT achado_id FROM r_achados WHERE verificado=1 AND status_final='descartado' ORDER BY achado_id LIMIT 1")
    _exec(copia, "UPDATE achados SET evidencia='EVIDENCIA-DESCARTADA-5555' WHERE achado_id=?", descartado)
    for incluir in (False, True):
        assert "EVIDENCIA-DESCARTADA-5555" not in _html(copia, incluir)[0]


# ---------- numeros iguais aos das views ----------
def test_numeros_do_relatorio_sao_os_das_views(banco_demo):
    html, d = _html(banco_demo)
    conf = _sql(banco_demo, "SELECT COUNT(*) FROM v_secretarias_confirmadas")
    ufs_conf = _sql(banco_demo, "SELECT COUNT(DISTINCT uf) FROM v_secretarias_confirmadas")
    ach = _sql(banco_demo, "SELECT COUNT(*) FROM r_achados")
    ok = _sql(banco_demo, "SELECT COUNT(*) FROM r_achados WHERE evidencia_confere=1")
    ver = _sql(banco_demo, "SELECT COUNT(*) FROM r_achados WHERE verificado=1")
    urls = _sql(banco_demo, "SELECT COUNT(DISTINCT url_id) FROM r_resultados_web")
    com_texto = _sql(banco_demo, "SELECT COUNT(*) FROM r_paginas WHERE extracao_ok=1")
    classif = _sql(banco_demo, "SELECT COUNT(*) FROM r_classificacoes")
    for valor, rotulo in ((conf, "Achados confirmados por humano"), (ach, "Achados (classificados pelo modelo)"),
                          (fmt.pct(ok, ach), "Evidência confere"), (fmt.pct(ver, ach), "Verificados por humano"),
                          (f"{ufs_conf} <small>de 27</small>", "UFs com achado confirmado")):
        assert f'<span class="kpi-valor">{valor}</span><span class="kpi-rotulo">{rotulo}</span>' in html, rotulo
    assert urls and com_texto and classif
    assert f'<span class="kpi-valor">{fmt.numero(urls)}</span><span class="kpi-rotulo">URLs únicas</span>' in html
    assert f'<span class="kpi-valor">{fmt.numero(com_texto)}</span><span class="kpi-rotulo">Páginas com texto</span>' in html
    assert f'<span class="kpi-valor">{fmt.numero(classif)}</span><span class="kpi-rotulo">Classificações</span>' in html
    # uma linha por achado confirmado, agrupadas por UF
    secao = html.split('id="achados-confirmados"', 1)[1].split("</section>", 1)[0]
    assert secao.count('class="ver-ok"') == conf
    assert len(re.findall(r'<tr class="grupo-uf">', secao)) == ufs_conf
    por_uf = dict(sqlite3.connect(banco_demo).execute("SELECT uf, COUNT(*) FROM v_secretarias_confirmadas GROUP BY uf").fetchall())
    for uf, n in por_uf.items():
        assert re.search(rf'<th colspan="6" scope="colgroup">{uf} — [^<]+ <small>\({n}\)</small>', secao), uf
    # mapa: cada UF na classe certa, segundo a especificacao (secao 16)
    c, s, z = sqlite3.connect(banco_demo).execute("""SELECT SUM(CASE WHEN n_confirmados > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN n_achados > 0 AND n_confirmados = 0 THEN 1 ELSE 0 END), 27 - COUNT(*) FROM v_resumo_uf""").fetchone()
    assert html.count('class="bloco confirmado"') == c and html.count('class="bloco classificado"') == s
    assert html.count('class="bloco sem-achados"') == z
    # PRISMA: cada caixa traz o valor da view
    for ordem, valor in sqlite3.connect(banco_demo).execute("SELECT ordem, valor FROM v_prisma").fetchall():
        assert f'<span class="num-prisma">{fmt.numero(valor)}</span>' in html, ordem
    assert f'<span class="kpi-valor">{fmt.numero(_sql(banco_demo, "SELECT COUNT(*) FROM r_artigos"))}</span><span class="kpi-rotulo">Artigos únicos' in html
    assert "removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)" in html
    assert "Removidos por ferramenta automática" in html and "PRISMA 2020" in html
    assert 'kpi-rotulo">Achados por 2 ou mais termos ou bases<' in html


def test_texto_de_metodologia_e_o_mesmo_da_pagina_e_traz_as_ressalvas(banco_demo):
    html, d = _html(banco_demo)
    m = gerar_metodologia(d["fatos"], d["ufs"])
    import html as h
    for secao in m["secoes"]:
        assert f"<h3>{h.escape(secao['titulo'])}</h3>" in html
        for b in secao["blocos"]:
            if b["tipo"] == "p":
                assert h.escape(para_texto(b["seg"])) in html
    assert m["ressalvas"] and all(h.escape(para_texto(r)) in html for r in m["ressalvas"])
    assert 'id="ressalvas-dados"' in html and "ler antes de citar estes números" in html
    assert "Estes dados são fictícios (demonstração)" in html


def test_visao_geral_avisa_das_paginas_nao_verificadas_sem_chamar_de_proibicao(banco_demo):
    html, d = _html(banco_demo)
    nv = d["fatos"]["web"]["nao_verificaveis"]
    assert nv["nao_verificavel_robots"] > 0
    visao = html.split('id="visao-geral"', 1)[1].split('id="mapa"', 1)[0]
    assert f"{nv['nao_verificavel_robots']} páginas não puderam ser verificadas porque o robots.txt do site estava inacessível" in visao
    assert "Isso não é o mesmo que o site proibir a leitura" in visao and "pode ter deixado de ver conteúdo" in visao
    assert "não puderam ser verificadas" in html.split('id="metodologia"', 1)[1]                       # tambem no texto de metodologia


def test_sem_paginas_nao_verificaveis_o_relatorio_nao_traz_o_aviso(tmp_path):
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    html, d = _html(vazio, nome="simulado.db", tipo="simulado")
    assert d["fatos"]["web"]["nao_verificaveis"]["nao_verificavel_robots"] == 0 and "não puderam ser verificadas" not in html


def test_rodape_traz_execucoes_hash_commit_e_data_de_geracao(banco_demo):
    html, _ = _html(banco_demo)
    rodape = html.split('id="rodape"', 1)[1]
    runs = [l[0] for l in sqlite3.connect(banco_demo).execute("SELECT run_id FROM execucoes WHERE no_relatorio=1").fetchall()]
    assert runs and all(r in rodape for r in runs)
    fora = sqlite3.connect(banco_demo).execute("SELECT run_id FROM execucoes WHERE no_relatorio=0").fetchall()
    assert fora and all(f[0] not in rodape for f in fora)
    h = _sql(banco_demo, "SELECT config_hash FROM execucoes WHERE no_relatorio=1 LIMIT 1")
    assert h[:12] in rodape and "<code>demo</code>" in rodape
    assert "Relatório gerado em 15/10/2026 14:30 a partir do banco" in rodape
    assert "3 execuções estão fora do relatório" in rodape


def test_commit_sujo_aparece_no_rodape(copia):
    _exec(copia, "UPDATE execucoes SET commit_git='abc1234+sujo:deadbeef' WHERE no_relatorio=1")
    html, _ = _html(copia)
    assert "execuções com commit “+sujo” rodaram com código ainda não commitado" in html.split('id="rodape"', 1)[1]


def test_banner_de_dados_ficticios_so_na_demo(banco_demo):
    assert "DADOS FICTÍCIOS" in _html(banco_demo)[0]
    html, _ = _html(banco_demo, tipo="simulado")
    assert "DADOS FICTÍCIOS" not in html and "SIMULADO" in html
    assert 'class="banner' not in _html(banco_demo, tipo="real")[0]


# ---------- texto coletado e escapado ----------
def test_texto_coletado_e_escapado_e_urls_perigosas_nao_viram_link(copia):
    xss = "<script>alert(1)</script>"
    conf = _sql(copia, "SELECT achado_id FROM v_secretarias_confirmadas ORDER BY achado_id LIMIT 1")
    pend = _sql(copia, "SELECT achado_id FROM r_achados WHERE verificado=0 ORDER BY achado_id LIMIT 1")
    _exec(copia, "UPDATE achados SET evidencia=?, fornecedor=? WHERE achado_id IN (?, ?)", xss, "<img src=x onerror=alert(1)>", conf, pend)
    _exec(copia, "UPDATE achados SET observacao=? WHERE achado_id=?", '"><svg onload=alert(2)>', conf)
    _exec(copia, "UPDATE urls SET url_original='javascript:alert(3)', dominio='<b>dom</b>' WHERE url_id=(SELECT url_id FROM classificacoes "
                 "WHERE classificacao_id=(SELECT classificacao_id FROM achados WHERE achado_id=?))", conf)
    _exec(copia, "UPDATE artigos SET titulo=?, link='data:text/html,<script>alert(4)</script>'", "<iframe src=x>titulo")
    _exec(copia, "UPDATE classificacoes SET classificador=?", "<u onmouseover=alert(5)>cl</u>")
    _exec(copia, "UPDATE buscas_manuais SET base=?", "<marquee>base</marquee>")
    conf_cfg = json.loads(sqlite3.connect(copia).execute("SELECT config_json FROM execucoes LIMIT 1").fetchone()[0])
    conf_cfg["termos"][0]["query"] = "<script>alert(6)</script>"
    _exec(copia, "UPDATE execucoes SET config_json=?, comando='<i onclick=alert(7)>x</i>'", json.dumps(conf_cfg))
    for incluir in (False, True):
        html, _ = _html(copia, incluir)
        for perigoso in ("<script", "<img", "<svg onload", "<iframe", "<b>dom", "<u ", "<marquee", "<i onclick", 'href="javascript', 'href="data:'):
            assert perigoso not in html, (perigoso, incluir)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ---------- sem dados ----------
def test_banco_vazio_gera_relatorio_com_avisos_de_nada_ainda(tmp_path):
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    for incluir in (False, True):
        html, _ = _html(vazio, incluir, "vazio.db", "real")
        assert "Nenhum achado foi confirmado por humano ainda" in html
        assert "Nada foi coletado ainda" in html and "Ainda não há artigos no banco" in html
        assert "<script" not in html.lower()


# ---------- linha de comando ----------
def _demo_em_data(demo):
    """Poe uma copia da demo (ja construida pelo fixture do modulo) em S.DATA_DIR, que `ambiente_cli` aponta para tmp_path."""
    S.DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(demo[0], S.DATA_DIR / "demo.db")


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def test_cli_demo_grava_o_arquivo_padrao_em_outputs(ambiente_cli, monkeypatch, capsys, demo):
    _demo_em_data(demo)
    _rodar(monkeypatch, "painel-relatorio", "--demo")
    arquivos = list((ambiente_cli / "outputs").glob("demo_relatorio_*.html"))
    assert len(arquivos) == 1 and re.fullmatch(r"demo_relatorio_\d{8}_\d{4}\.html", arquivos[0].name)
    assert f"Generated: {arquivos[0]}" in capsys.readouterr().out
    html = arquivos[0].read_text(encoding="utf-8")
    assert "DADOS FICTÍCIOS" in html and "<script" not in html and "somente achados confirmados por humano" in html


def test_cli_saida_e_incluir_nao_verificados(ambiente_cli, monkeypatch, demo):
    _demo_em_data(demo)
    alvo = ambiente_cli / "pasta nova" / "meu_relatorio.html"
    _rodar(monkeypatch, "painel-relatorio", "--demo", "--saida", str(alvo), "--incluir-nao-verificados")
    html = alvo.read_text(encoding="utf-8")
    assert not (ambiente_cli / "outputs").exists() or not list((ambiente_cli / "outputs").glob("*relatorio*"))
    assert 'id="achados-nao-verificados"' in html and html.count('class="aviso-nv"') == _sql(S.DATA_DIR / "demo.db",
                                                                                           "SELECT COUNT(*) FROM v_achados_revisao WHERE verificado=0")


def test_cli_simulado_usa_o_prefixo_e_o_banco_simulado(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "pipeline-uf", "--simulado", "--ufs", "PI", "--limite", "2")
    _rodar(monkeypatch, "painel-relatorio", "--simulado")
    arquivos = list((ambiente_cli / "outputs").glob("simulado_relatorio_*.html"))
    assert len(arquivos) == 1
    html = arquivos[0].read_text(encoding="utf-8")
    assert "SIMULADO" in html and "simulado.db" in html and "<script" not in html


def test_cli_sem_banco_ou_com_flags_incompativeis_encerra_com_mensagem(ambiente_cli, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel-relatorio", "--demo")
    assert "painel-demo" in str(e.value)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel-relatorio", "--simulado")
    assert "ainda não existe" in str(e.value)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel-relatorio", "--simulado", "--demo")
    assert "não os dois" in str(e.value)
    assert not (ambiente_cli / "outputs").exists()
