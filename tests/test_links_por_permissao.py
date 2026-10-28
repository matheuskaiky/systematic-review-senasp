"""Links no corpo das paginas (execucoes, chamadas e as duas filas de decisao) seguem a mesma regra que o servidor aplica: so viram
link para quem o servidor aceitaria. Um valor (numero, identificador de execucao, dominio) fica como texto sem link; um rotulo que so
existe para levar ao destino ("Ver execucoes.", "revisar esta fila") some. A regra e uma so, `navegacao.pode_seguir`, a mesma do menu.
"""
import copy
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from dominio import autenticacao as A
from painel import analises_blocos as b, metodologia_texto as MT, navegacao
from painel.analises_blocos_vies import ABAS_VIES
from painel.rotas_extras.analises import ABAS
from test_autenticacao import painel  # noqa: F401
from test_menu_e_acoes_por_permissao import GRUPOS, clientes, somente_leitura, vies  # noqa: F401
from test_painel import demo  # noqa: F401
from test_validacao_vies import _cli as _cli_sem_login, _post, banco  # noqa: F401

FILAS = {"/literatura/triagem": ("POST", "/literatura/artigos/1/triar"), "/revisao/achados": ("POST", "/achados/1/verificar")}
RESTRITOS = ("/execucoes", "/chamadas")
PULAR = (".xlsx", ".csv", ".json", ".md", ".docx", ".zip", "/bruto")
NENHUM = "zzzz-nenhum-resultado"
SEMENTES_REAL = ([f"/revisao/achados?q={NENHUM}", f"/literatura/triagem?q={NENHUM}", "/buscar-texto?q=reconhecimento", "/metodologia"]
                 + [f"/analises?secao={k}" for k, _ in ABAS])
SEMENTES_VIES = [f"/literatura/triagem?q={NENHUM}", "/metodologia", "/validacao"] + [f"/analises?secao={k}" for k, _ in ABAS_VIES]
# paginas que, nos dados de demonstracao, tem link para execucoes ou chamadas (garante que o percurso nao passa vazio)
COM_RESTRITOS_REAL = {"/", "/metodologia", "/classificadores", "/buscar-texto", "/literatura/artigos/{artigo_id}", "/analises?secao=operacao"}
COM_FILA_REAL = {"/", "/achados", "/literatura/artigos", "/analises?secao=visao", "/revisao/achados", "/literatura/triagem"}
COM_RESTRITOS_VIES = {"/metodologia", "/literatura/artigos/{artigo_id}", "/triagem-escopo"}
COM_FILA_VIES = {"/literatura/artigos", "/literatura/triagem"}


def _corpo(html):
    i = html.find('<main id="conteudo"')
    return html[i:html.index("</main>", i)] if i >= 0 else ""


def _links(html):
    return [unescape(h) for h in re.findall(r'<a\b[^>]*\bhref="(/(?!/)[^"]*)"', _corpo(html))]


def _caminho(href):
    return unquote(urlsplit(href).path)


def _segue(aceita, href):
    c = _caminho(href)
    return aceita("GET", c) and (c not in FILAS or aceita(*FILAS[c]))


def _aceita_do_grupo(grupo):
    return lambda m, c: A.pode_acessar(grupo, A.GRUPOS_PADRAO[grupo], m, c)


def _menu(html):
    return re.findall(r'<a [^>]*href="([^"]+)"', html[html.index("<nav"):html.index("</nav>")])


def _percorrer(cli, extras, limite=90):
    """Visita uma pagina por regra de rota (e por aba de /analises), partindo das sementes e do menu.
    Devolve {chave da pagina: links do corpo}."""
    fila, vistos, paginas = list(extras) + ["/"] + _menu(cli.get("/").text), set(), {}
    while fila and len(vistos) < limite:
        href = fila.pop(0)
        c = _caminho(href)
        if c.startswith("/static/") or c in ("/sair", "/entrar") or c.endswith(PULAR):
            continue
        regra = A.regra_explicita("GET", c)
        aba = parse_qs(urlsplit(href).query).get("secao", [""])[-1]
        chave = (regra[1] if regra else c) + (f"?secao={aba}" if c == "/analises" and aba else "")
        if chave in vistos:
            continue
        vistos.add(chave)
        r = cli.get(href, follow_redirects=False)
        if r.status_code != 200:
            continue
        paginas[chave] = _links(r.text)
        fila += paginas[chave]
    return paginas


def _conferir(paginas, aceita, com_restritos, com_fila):
    assert len(paginas) >= 15
    ruins = {k: sorted({_caminho(x) for x in ls if not _segue(aceita, x)}) for k, ls in paginas.items()}
    assert {k: v for k, v in ruins.items() if v} == {}
    restritos = {k for k, ls in paginas.items() if any(_caminho(x).startswith(RESTRITOS) for x in ls)}
    filas = {k for k, ls in paginas.items() if any(_caminho(x) in FILAS for x in ls)}
    assert com_restritos <= restritos if aceita("GET", "/execucoes") else not restritos
    decide = all(aceita("GET", f) and aceita(*FILAS[f]) for f in FILAS)
    assert com_fila <= filas if decide else not filas


# ---------------- a regra (funcao pura) ----------------
@pytest.mark.parametrize("href,negados,esperado,chamadas", [
    ("/execucoes/r1", set(), True, [("GET", "/execucoes/r1")]),
    ("/execucoes/r1", {("GET", "/execucoes/r1")}, False, [("GET", "/execucoes/r1")]),
    ("/execucoes/r1?configuracao=1#configuracao", set(), True, [("GET", "/execucoes/r1")]),
    ("/execucoes/a%20b%2Fc", set(), True, [("GET", "/execucoes/a b/c")]),
    ("/chamadas?etapa=download&q=x", set(), True, [("GET", "/chamadas")]),
    ("/", set(), True, [("GET", "/")]),
    ("/revisao/achados?uf=PI", set(), True, [("GET", "/revisao/achados"), ("POST", "/achados/1/verificar")]),
    ("/revisao/achados", {("POST", "/achados/1/verificar")}, False, [("GET", "/revisao/achados"), ("POST", "/achados/1/verificar")]),
    ("/revisao/achados", {("GET", "/revisao/achados")}, False, [("GET", "/revisao/achados")]),
    ("/literatura/triagem?q=x", {("POST", "/literatura/artigos/1/triar")}, False,
     [("GET", "/literatura/triagem"), ("POST", "/literatura/artigos/1/triar")]),
    ("/literatura/triagem/", set(), True, [("GET", "/literatura/triagem/")]),       # so o caminho exato e fila
    ("", set(), False, []),
    ("   ", set(), False, []),
    ("execucoes", set(), False, []),
    ("#ressalvas", set(), False, []),
    ("//exemplo.org/execucoes", set(), False, []),
    ("https://exemplo.org/execucoes", set(), False, []),
    (None, set(), False, []),
    (7, set(), False, []),
])
def test_pode_seguir(href, negados, esperado, chamadas):
    feitas = []

    def pode(m, c):
        feitas.append((m, c))
        return (m, c) not in negados
    assert navegacao.pode_seguir(href, pode) is esperado
    assert feitas == chamadas


def test_menu_usa_pode_seguir(monkeypatch):
    vistos = []
    monkeypatch.setattr(navegacao, "pode_seguir", lambda h, p: vistos.append(h) or h != "/estados")
    hrefs = [i["href"] for g in navegacao.grupos("/", banco="real", pode=lambda m, c: True) for i in g["itens"]]
    assert "/estados" not in hrefs and "/estados" in vistos and "/" in hrefs
    assert navegacao.grupos("/", banco="real") == navegacao.grupos("/", banco="real", pode=None)


# ---------------- o painel inteiro, por grupo ----------------
@pytest.mark.parametrize("grupo", GRUPOS)
def test_nenhum_link_do_corpo_leva_a_recusa_no_real(clientes, grupo):
    _conferir(_percorrer(clientes[grupo], SEMENTES_REAL), _aceita_do_grupo(grupo), COM_RESTRITOS_REAL, COM_FILA_REAL)


@pytest.mark.parametrize("grupo", GRUPOS)
def test_nenhum_link_do_corpo_leva_a_recusa_no_vies(vies, grupo):
    _conferir(_percorrer(vies[grupo], SEMENTES_VIES), _aceita_do_grupo(grupo), COM_RESTRITOS_VIES, COM_FILA_VIES)


def test_somente_leitura_mostra_execucoes_e_nenhuma_fila(somente_leitura):
    _conferir(_percorrer(somente_leitura, SEMENTES_REAL), lambda m, c: m == "GET", COM_RESTRITOS_REAL, COM_FILA_REAL)


def test_paginas_usam_a_mesma_regra(clientes, monkeypatch):
    original = navegacao.pode_seguir
    vistos = []

    def falsa(href, pode):
        vistos.append(href)
        return not _caminho(href).startswith(RESTRITOS) and _caminho(href) not in FILAS and original(href, pode)
    monkeypatch.setattr(navegacao, "pode_seguir", falsa)
    paginas = _percorrer(clientes["Administrador"], SEMENTES_REAL)
    assert [x for ls in paginas.values() for x in ls if _caminho(x).startswith(RESTRITOS) or _caminho(x) in FILAS] == []
    assert any(_caminho(h).startswith("/execucoes/") for h in vistos) and any(_caminho(h) == "/chamadas" for h in vistos)


@pytest.mark.parametrize("qual", ["real", "vies"])
def test_a_regra_recebe_o_href_exato_de_cada_link(clientes, vies, qual, monkeypatch):  # noqa: F811
    original = navegacao.pode_seguir
    vistos = set()
    monkeypatch.setattr(navegacao, "pode_seguir", lambda href, pode: vistos.add(href) or original(href, pode))
    cli, sementes = (clientes["Administrador"], SEMENTES_REAL) if qual == "real" else (vies["Administrador"], SEMENTES_VIES)
    paginas = _percorrer(cli, sementes)
    alvos = {x for k, ls in paginas.items() if not k.startswith(RESTRITOS)          # paginas de quem ja ve chamadas: fora
             for x in ls if _caminho(x).startswith(RESTRITOS) or _caminho(x) in FILAS}
    assert any("?" in x for x in alvos) and any(_caminho(x).startswith("/execucoes/") for x in alvos)
    assert sorted(alvos - vistos) == []


def test_visao_geral_do_vies_usa_a_mesma_regra(vies, monkeypatch):  # noqa: F811
    monkeypatch.setattr(LeituraPainelSQLite, "contagem_triagem",
                        lambda self: {"total": 5, "incluidos": 1, "excluidos": 1, "pendentes": 3})
    h = _corpo(vies["Administrador"].get("/").text)
    assert 'href="/literatura/triagem">Continuar a triagem (3)</a>' in h
    monkeypatch.setattr(navegacao, "pode_seguir", lambda href, pode: _caminho(href) not in FILAS)
    h = _corpo(vies["Administrador"].get("/").text)
    assert 'href="/literatura/triagem' not in h and "Artigos aguardando triagem humana" in h      # o numero fica, o botao some


# ---------------- o valor fica, o rotulo some ----------------
def _sem_tags(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html))).strip()


def test_identificador_da_execucao_fica_como_texto(clientes):
    adm, leitor = clientes["Administrador"], clientes["Leitor"]
    artigo = re.search(r'href="/literatura/artigos/(\d+)"', adm.get("/literatura/artigos").text).group(1)
    for url in ("/classificadores", "/buscar-texto?q=reconhecimento", f"/literatura/artigos/{artigo}"):
        a, l = _corpo(adm.get(url).text), _corpo(leitor.get(url).text)
        runs = set(re.findall(r'<a href="/execucoes/([^"?#]+)[^"]*"><code>', a))
        assert runs, url
        for run in runs:
            assert f"<code>{run}</code>" in l and f'href="/execucoes/{run}' not in l, (url, run)
    l = _corpo(leitor.get("/").text)                     # na Visao Geral, as execucoes so aparecem a quem tem ver_chamadas
    assert re.search(r'<a href="/execucoes/[^"]+"><code>', _corpo(adm.get("/").text))
    assert "Execuções e chamadas" not in l and not re.search(r"<code>\d{8}_\d{6}_", l)


def test_metodologia_mantem_os_numeros_e_tira_os_rotulos(clientes):
    a, l = _corpo(clientes["Administrador"].get("/metodologia").text), _corpo(clientes["Leitor"].get("/metodologia").text)
    for run in set(re.findall(r'<a href="/execucoes/([^"?#]+)">', a)):
        assert run in l and f'href="/execucoes/{run}"' not in l
    leitor = _aceita_do_grupo("Leitor")
    sem_rotulos = re.sub(r'<a href="([^"]*)">([^<]*)</a>',
                         lambda x: "" if unescape(x.group(2)) in MT.ROTULOS_DE_LINK and not _segue(leitor, unescape(x.group(1))) else x.group(0), a)
    assert _sem_tags(l) == _sem_tags(sem_rotulos)
    assert "Os números com link levam à página do painel que os justifica." in a and "Cada número é um link" not in a


def test_cartoes_de_prontidao_e_rotulos_das_analises(clientes):
    for grupo, cli in clientes.items():
        decide = all(_aceita_do_grupo(grupo)(*FILAS[f]) for f in FILAS)
        ve = _aceita_do_grupo(grupo)("GET", "/chamadas")
        h = _corpo(cli.get("/analises?secao=visao").text)
        assert "H2: regressão logística da confirmação" in h and "H5: citações e posição × inclusão" in h
        assert ('>Verificar achados</a>' in h) is decide and ('>Triar artigos</a>' in h) is decide, grupo
        op = _corpo(cli.get("/analises?secao=operacao").text)
        assert ("Ver as chamadas com este motivo" in op) is ve, grupo
        assert ("Ver as chamadas de download com robots.txt inacessível" in op) is ve, grupo


def test_entradas_das_filas_no_corpo(clientes):
    for grupo, cli in clientes.items():
        decide = all(_aceita_do_grupo(grupo)(*FILAS[f]) for f in FILAS)
        h = _corpo(cli.get("/achados").text)
        assert ("revisar esta fila" in h) is decide, grupo
        if not decide:
            assert re.search(r"<strong>[\d.]+</strong> achado\(s\)</p>", h), grupo
        h = _corpo(cli.get("/literatura/artigos").text)
        assert ("triar os pendentes desta lista" in h) is decide, grupo
        if not decide:
            assert re.search(r"<strong>[\d.]+</strong> artigo\(s\)</p>", h), grupo
        h = _corpo(cli.get(f"/revisao/achados?q={NENHUM}").text)
        assert "Nenhum achado pendente com estes filtros." in h
        assert ("Ver a fila completa" in h) is decide, grupo
        h = _corpo(cli.get(f"/literatura/triagem?q={NENHUM}").text)
        assert "Nenhum artigo pendente com estes filtros." in h
        assert ("Ver a fila completa" in h) is decide, grupo


# ---------------- validacao: conferir o proximo item ----------------
def test_conferir_o_proximo_item_so_para_quem_decide(vies, banco, tmp_path, monkeypatch):  # noqa: F811
    assert _post(_cli_sem_login(banco, tmp_path), "/validacao/sortear").status_code == 303
    for grupo, cli in vies.items():
        decide = _aceita_do_grupo(grupo)("POST", "/validacao/1/triar")
        assert ('href="/validacao/1">Conferir o próximo item</a>' in cli.get("/validacao").text) is decide, grupo
    original = A.pode_acessar
    for negado in (("POST", "/validacao/1/triar"), ("GET", "/validacao/1")):
        monkeypatch.setattr(A, "pode_acessar", lambda g, p, m, c, n=negado: False if (m, c) == n else original(g, p, m, c))
        assert "Conferir o próximo item" not in vies["Administrador"].get("/validacao").text, negado
    sem_login = _cli_sem_login(banco, tmp_path)
    assert "Conferir o próximo item" in sem_login.get("/validacao").text
    assert "Conferir o próximo item" not in _cli_sem_login(banco, tmp_path, somente_leitura=True).get("/validacao").text


# ---------------- tabela de opacidade (funcao pura) ----------------
OPACIDADE = {"n_tentadas": 100, "n_ok": 40, "n_robots": 10, "n_http_bloqueio": 5, "n_robots_inacessivel": 30, "n_outros": 15,
             "pct_bloqueado": 15.0, "pct_inacessivel": 30.0, "n_dominios": 2,
             "dominios": [{"dominio": "ssp.xx.gov.br", "n_tentadas": 50, "n_robots": 10, "n_http_bloqueio": 5, "n_robots_inacessivel": 30},
                          {"dominio": "pc.yy.gov.br", "n_tentadas": 50, "n_robots": 0, "n_http_bloqueio": 0}]}


def test_opacidade_com_e_sem_regra():
    livre = str(b.bloco_opacidade(OPACIDADE)["grafico"])
    assert livre.count('href="/chamadas?') == 2
    assert str(b.bloco_opacidade(OPACIDADE, seguir=None)["grafico"]) == livre
    vistos = []
    assert str(b.bloco_opacidade(OPACIDADE, seguir=lambda h: vistos.append(h) or True)["grafico"]) == livre
    assert vistos == ["/chamadas?etapa=download&q=ssp.xx.gov.br", "/chamadas?etapa=download&q=pc.yy.gov.br"]
    negado = str(b.bloco_opacidade(OPACIDADE, seguir=lambda h: False)["grafico"])
    assert 'href="/chamadas' not in negado and "ssp.xx.gov.br" in negado and "pc.yy.gov.br" in negado
    assert b.bloco_opacidade({"n_tentadas": 0}, seguir=lambda h: False)["titulo"] == "Sem downloads registrados"


# ---------------- metodologia (funcao pura) ----------------
def _m():
    return {"secoes": [{"id": "s", "titulo": "T", "blocos": [
                {"tipo": "p", "seg": [("Foram ", None), ("12", "/chamadas?etapa=x"), (" em ", None), ("r1", "/execucoes/r1"), (".", None)]},
                {"tipo": "ul", "itens": [[("PI", "/estados/PI")], [("3", "/execucoes")], [("Ver execuções.", "/execucoes")]]}]}],
            "ressalvas": [[("Algo. ", None), ("Ver execuções.", "/execucoes")],
                          [("Retomadas: ", None), ("r2", "/execucoes/r2"), (".", None)],
                          [("Pendentes. ", None), ("Ver pendentes.", "/achados?verificacao=pendente")],
                          [("Comece a revisão.", "/revisao/achados")]],
            "vazio": False, "texto": "T\n\nForam 12 em r1.\n"}


def _nega_restritos(h):
    return not _caminho(h).startswith(RESTRITOS) and _caminho(h) not in FILAS


def test_filtrar_links_da_metodologia():
    m, antes = _m(), _m()
    vistos = []
    saida = MT.filtrar_links(m, lambda h: vistos.append(h) or _nega_restritos(h))
    assert m == antes                                                   # a entrada nao muda
    assert saida["secoes"][0]["blocos"] == [
        {"tipo": "p", "seg": [("Foram ", None), ("12", None), (" em ", None), ("r1", None), (".", None)]},
        {"tipo": "ul", "itens": [[("PI", "/estados/PI")], [("3", None)]]}]
    assert saida["ressalvas"] == [[("Algo. ", None)], [("Retomadas: ", None), ("r2", None), (".", None)],
                                  [("Pendentes. ", None), ("Ver pendentes.", "/achados?verificacao=pendente")]]
    assert (saida["vazio"], saida["texto"], saida["secoes"][0]["id"], saida["secoes"][0]["titulo"]) == (False, m["texto"], "s", "T")
    assert vistos == ["/chamadas?etapa=x", "/execucoes/r1", "/estados/PI", "/execucoes", "/execucoes", "/execucoes",
                      "/execucoes/r2", "/achados?verificacao=pendente", "/revisao/achados"]
    assert MT.filtrar_links(_m(), lambda h: True) == _m()


def test_rotulos_de_link_sao_os_do_gerador():
    assert set(MT.ROTULOS_DE_LINK) == {"Comece a revisão.", "Ver pendentes.", "Ver o PRISMA.", "Ver execuções.", "Ver as chamadas.",
                                       "Ver classificadores."}
    fonte = Path(MT.__file__).read_text(encoding="utf-8")
    assert set(re.findall(r'\("((?:Ver|Comece)[^"]*\.)", ', fonte)) <= set(MT.ROTULOS_DE_LINK)


def test_rota_da_metodologia_filtra_pela_regra_do_pedido(clientes, monkeypatch):
    chamadas = []
    original = MT.filtrar_links
    monkeypatch.setattr(MT, "filtrar_links", lambda m, seguir: chamadas.append(seguir) or original(m, seguir))
    assert clientes["Leitor"].get("/metodologia").status_code == 200
    assert len(chamadas) == 1
    assert chamadas[0]("/execucoes") is False and chamadas[0]("/estados") is True and chamadas[0]("/revisao/achados") is False
    assert clientes["Revisor"].get("/metodologia").status_code == 200 and chamadas[1]("/execucoes") is True


# ---------------- uma regra so nos modelos ----------------
SO_DE_QUEM_VE_CHAMADAS = {"execucao.html", "execucoes.html", "chamadas.html", "chamada.html", "comparar.html"}


def _sem_marcas(texto):
    return re.sub(r'[\s()"~\']', "", texto)


def _argumento_de_pode_seguir(condicao):
    """O argumento da primeira chamada pode_seguir(...) da condicao, ate o parentese que a fecha, sem espacos, aspas,
    parenteses e `~`; None se nao houver chamada."""
    i = condicao.find("pode_seguir(")
    if i < 0:
        return None
    nivel, k = 1, i + len("pode_seguir(")
    while k < len(condicao) and nivel:
        nivel += {"(": 1, ")": -1}.get(condicao[k], 0)
        k += 1
    return _sem_marcas(condicao[i + len("pode_seguir("):k - 1])


def test_todo_link_literal_para_destino_restrito_passa_pela_regra():
    pasta = Path("painel/templates")
    sem_condicao = []
    for arq in sorted(pasta.glob("*.html")):
        if arq.name in SO_DE_QUEM_VE_CHAMADAS or arq.name == "base.html":
            continue
        s = arq.read_text(encoding="utf-8")
        for m in re.finditer(r'href="(/execucoes|/chamadas|/revisao/achados|/literatura/triagem)', s):
            antes = s[:m.start()]
            se = antes.rfind("{% if")
            condicao = antes[se:antes.index("%}", se)] if se >= 0 else ""
            fechado = "{% endif %}" in antes[se:] if se >= 0 else True
            href = s[m.start() + 6:s.index('"', m.start() + 6)]
            partes = [x for x in re.split(r"\{\{(.*?)\}\}", href) if x.strip()]      # trechos literais e expressoes, alternados
            exato = _argumento_de_pode_seguir(condicao) == _sem_marcas("".join(partes))
            if fechado or not exato:
                sem_condicao.append(f"{arq.name}:{s.count(chr(10), 0, m.start()) + 1}")
    assert sem_condicao == []
    assert [a.name for a in pasta.glob("*.html") if '"ver_chamadas" in perms' in a.read_text(encoding="utf-8")] == []
