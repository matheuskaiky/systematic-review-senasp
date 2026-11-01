"""Apresentacao da pesquisa na Visao Geral publica: textos lidos de config/apresentacao.py, uma secao por chave, na ordem fixa,
so para quem nao entrou com a pesquisa divulgada. Secao com o marcador PREENCHA ou com valor fora do formato nao aparece;
com todas as secoes ausentes a pagina publica fica como antes. Quem entrou e o painel sem login nao mudam, e nenhuma rota,
permissao, leitura ou politica de divulgacao muda (D145)."""
import dataclasses
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from apoio_divulgacao import gravar_politica
from config import consultas as C, vocabulario as V
from dominio import apresentacao as AP
from painel.app import Contexto, criar_app
from test_autenticacao import _criar, _entrar
from test_painel import demo  # noqa: F401
from test_validacao_vies import banco  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
DADOS_REAIS = (RAIZ / "data").resolve()
SECOES = ["descricao", "perguntas", "metodo", "abrangencia", "limitacoes", "instituicao"]
TITULOS = {"descricao": "Sobre a pesquisa", "perguntas": "Perguntas de pesquisa", "metodo": "Como a pesquisa é feita",
           "abrangencia": "Abrangência", "limitacoes": "Limitações", "instituicao": "Instituição e contato"}
LISTAS = {"perguntas": "ol", "limitacoes": "ul"}
TEXTOS = {"descricao": ("Descrição de teste da pesquisa.",),
          "perguntas": ("Primeira pergunta de teste?", "Segunda pergunta de teste?"),
          "metodo": ("Primeiro parágrafo do método de teste.", "Segundo parágrafo do método de teste."),
          "abrangencia": ("Abrangência de teste.",),
          "limitacoes": ("Primeira limitação de teste.", "Segunda limitação de teste."),
          "instituicao": ("Instituição de teste.",)}
VAZIO = {"antes": [], "depois": []}


@pytest.fixture(autouse=True)
def _nunca_abre_o_data_real(monkeypatch):
    """Todo teste deste arquivo falha se algo tentar abrir um arquivo SQLite dentro do data/ de verdade (contas reais)."""
    original = sqlite3.connect

    def conectar(caminho, *a, **k):
        alvo = Path(str(caminho)).resolve() if str(caminho) != ":memory:" else None
        if alvo is not None and (alvo == DADOS_REAIS or DADOS_REAIS in alvo.parents):
            raise AssertionError(f"teste tentou abrir {alvo}")
        return original(caminho, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", conectar)


def _secao(sid, paragrafos):
    return {"id": sid, "titulo": TITULOS[sid], "lista": LISTAS.get(sid), "paragrafos": list(paragrafos)}


def _esperado(textos):
    antes = [_secao(s, textos[s]) for s in SECOES[:4] if s in textos]
    depois = [_secao(s, textos[s]) for s in SECOES[4:] if s in textos]
    return {"antes": antes, "depois": depois}


# ======================== regra pura: formato de cada secao ========================
def test_constantes_da_regra():
    assert AP.MARCADOR == "PREENCHA"
    assert AP.SECOES == tuple((s, TITULOS[s]) for s in SECOES)
    assert (AP.MAX_PARAGRAFOS, AP.MAX_CARACTERES) == (10, 2000)


def test_todas_as_secoes_validas_na_ordem_fixa():
    embaralhado = {k: TEXTOS[k] for k in reversed(SECOES)}
    assert AP.secoes_publicas(embaralhado) == _esperado(TEXTOS)


@pytest.mark.parametrize("valor", [
    None, "texto solto", ["lista em vez de tupla"], (), ("PREENCHA",), ("Texto com PREENCHA no meio.",),
    ("Válido.", "PREENCHA"), ("",), ("   \n\t",), ("Válido.", ""), (1,), ("Válido.", None), (("aninhado",),),
    ("x" * 2001,), tuple(f"Parágrafo {i}." for i in range(11)), {"a": "b"}, 7, b"bytes", ("Válido.", b"bytes"),
], ids=["none", "str", "lista", "tupla_vazia", "marcador", "marcador_no_meio", "marcador_no_segundo", "vazio", "so_espacos",
        "segundo_vazio", "numero", "segundo_none", "aninhado", "2001_caracteres", "11_paragrafos", "dict", "int", "bytes",
        "segundo_bytes"])
def test_valor_fora_do_formato_omite_so_a_sua_secao(valor):
    for sid in SECOES:
        textos = dict(TEXTOS)
        textos[sid] = valor
        esperado = _esperado({k: v for k, v in TEXTOS.items() if k != sid})
        assert AP.secoes_publicas(textos) == esperado, sid


@pytest.mark.parametrize("valor", [("x" * 2000,), tuple(f"Parágrafo {i}." for i in range(10)), ("preencha em minúsculas.",),
                                   ("Preencha com maiúscula só no início.",), ("  Espaços nas pontas.  ",), ("Linha 1\nLinha 2",)],
                         ids=["2000_caracteres", "10_paragrafos", "minusculas", "capitalizado", "espacos", "quebra"])
def test_limites_aceitos_e_texto_cru(valor):
    """O marcador e so PREENCHA em maiusculas; o texto livre volta sem strip (so espaco puro e vazio)."""
    textos = dict(TEXTOS, metodo=valor)
    assert AP.secoes_publicas(textos)["antes"][2] == _secao("metodo", valor)


def test_subclasse_de_str_e_tupla_nomeada_sao_recusadas():
    class Texto(str):
        pass
    Par = __import__("collections").namedtuple("Par", "a")
    for valor in ((Texto("Subclasse."),), Par("Tupla nomeada.")):
        assert AP.secoes_publicas(dict(TEXTOS, abrangencia=valor))["antes"] == [
            _secao(s, TEXTOS[s]) for s in SECOES[:4] if s != "abrangencia"]


class _Dicionario(dict):
    pass


@pytest.mark.parametrize("textos", [None, [], "texto", (), 0, {"perguntas": 1}.keys(), _Dicionario(TEXTOS),
                                    __import__("collections").OrderedDict(TEXTOS)],
                         ids=["none", "lista", "str", "tupla", "zero", "keys", "subclasse_de_dict", "ordereddict"])
def test_entrada_que_nao_e_dicionario_nao_mostra_nada(textos):
    """So um dict exatamente (type is dict) e lido; uma subclasse de dict tambem nao mostra nada."""
    assert AP.secoes_publicas(textos) == VAZIO


def test_dicionario_vazio_e_chaves_ausentes():
    assert AP.secoes_publicas({}) == VAZIO
    assert AP.secoes_publicas({"perguntas": TEXTOS["perguntas"]}) == {"antes": [_secao("perguntas", TEXTOS["perguntas"])], "depois": []}
    assert AP.secoes_publicas({"instituicao": TEXTOS["instituicao"]}) == {"antes": [], "depois": [_secao("instituicao", TEXTOS["instituicao"])]}


def test_chave_desconhecida_e_ignorada():
    assert AP.secoes_publicas(dict(TEXTOS, contato=("x",), Perguntas=("y",), **{" perguntas": ("z",)})) == _esperado(TEXTOS)


def test_nao_altera_a_entrada_e_devolve_listas_novas():
    textos = {k: tuple(v) for k, v in TEXTOS.items()}
    copia = dict(textos)
    r = AP.secoes_publicas(textos)
    assert textos == copia
    assert list(r) == ["antes", "depois"]
    r["antes"][0]["paragrafos"].append("mutado")
    r["depois"][0]["paragrafos"].append("mutado")
    r["depois"].append("mutado")
    r["antes"].clear()
    assert AP.secoes_publicas(textos) == _esperado(TEXTOS)
    vazio = AP.secoes_publicas({})
    assert list(vazio) == ["antes", "depois"]
    vazio["antes"].append("mutado")
    vazio["depois"].append("mutado")
    assert AP.secoes_publicas({}) == VAZIO and AP.secoes_publicas(None) == VAZIO


# ======================== o arquivo de configuracao ========================
def test_arquivo_de_configuracao_so_com_o_marcador():
    """Nesta etapa nenhum texto publico existe: as duas pesquisas tem as seis secoes com o marcador, e nada aparece."""
    from config import apresentacao as CA
    assert type(CA.APRESENTACAO) is dict and list(CA.APRESENTACAO) == ["real", "vies"]
    assert all(type(v) is dict for v in CA.APRESENTACAO.values())
    for banco_ in ("real", "vies"):
        assert list(CA.APRESENTACAO[banco_]) == SECOES
        assert all(v == ("PREENCHA",) for v in CA.APRESENTACAO[banco_].values())
        assert AP.secoes_publicas(CA.APRESENTACAO[banco_]) == VAZIO


def test_fonte_do_arquivo_de_configuracao():
    """So constantes: nenhum import (nem dinamico), nenhuma funcao ou classe, a docstring exata e um unico nome."""
    from config import apresentacao as CA
    fonte = (RAIZ / "config" / "apresentacao.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s", fonte, re.M)
    assert CA.__doc__ == ("Textos da apresentação pública de cada pesquisa (Visão Geral para quem não entrou). Cada seção é uma "
                          "tupla de parágrafos; a seção com PREENCHA ou fora do formato não aparece. Os textos são escritos pelo "
                          "pesquisador.")
    assert [n for n in vars(CA) if not (n.startswith("__") and n.endswith("__"))] == ["APRESENTACAO"]
    assert not re.search(r"\bdef\b|\bclass\b|\blambda\b|__import__|\bexec\b|\beval\b", fonte)


def test_camadas():
    """A regra e pura (dominio sem config); o painel nunca le config: os textos chegam pelo Contexto."""
    from test_arquitetura import _viola
    assert not _viola(r"^\s*(from|import)\s+config\b", ["painel"])
    fonte = (RAIZ / "dominio" / "apresentacao.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(?!__future__)", fonte, re.M)


# ======================== a pagina ========================
def _ctx(banco_="real", nome="demo.db", autenticacao=True, apresentacao=None):
    extra = {} if apresentacao is None else {"apresentacao": apresentacao}
    return Contexto(banco=banco_, nome_banco=nome, somente_leitura=False, pasta_backup=Path("/nao-usado"), ufs=dict(C.UFS),
                    status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                    hosts_permitidos=("testserver",), autenticacao=autenticacao, **extra)


@pytest.fixture
def real(demo, tmp_path):  # noqa: F811
    """Banco real de demonstracao com login e a pesquisa divulgada: (app, ctx, contas, contas_db, copia)."""
    db, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(db, copia)
    ctx = _ctx()
    contas = ContasSQLite(tmp_path / "contas.db")
    gravar_politica(contas, "real")
    app = criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas)
    return app, ctx, contas, tmp_path / "contas.db", copia


def _secoes_ap(h):
    return re.findall(r'<section class="cartao" id="vg-ap-([a-z]+)" aria-labelledby="t-vg-ap-\1">', h)


def _sem_apresentacao(h):
    """Tira cada secao da apresentacao com exatamente um LF depois do fechamento (o contrato do modelo)."""
    return re.sub(r'<section class="cartao" id="vg-ap-[a-z]+".*?</section>\n', "", h, flags=re.S)


def _posicoes_exatas(h):
    """As de antes comecam logo depois do titulo; as de depois terminam logo antes do guia de leitura."""
    assert '<h1>Visão geral</h1>\n<section class="cartao" id="vg-ap-descricao" ' in h
    fim = h.index('id="vg-ap-instituicao"')
    assert h[h.index("</section>\n", fim):].startswith('</section>\n\n<section class="guia-interpretacao" aria-labelledby="guia-geral">')
    ultima = max(h.index(f'id="vg-{s}"') for s in re.findall(r'<section class="vg-secao" id="vg-([a-z_]+)"', h))
    assert ultima < h.index('id="vg-ap-limitacoes"')


def test_contexto_comeca_sem_textos():
    a, b = _ctx(), _ctx()
    assert a.apresentacao == {} and type(a.apresentacao) is dict and a.apresentacao is not b.apresentacao
    nomes = [f.name for f in dataclasses.fields(Contexto)]
    assert nomes[nomes.index("aceita_envios") + 1] == "apresentacao"


def test_visitante_ve_as_secoes_na_ordem_com_titulos_e_listas(real):
    app, ctx, *_ = real
    ctx.apresentacao = dict(TEXTOS)
    h = TestClient(app).get("/").text
    assert _secoes_ap(h) == SECOES
    i_h1, i_secoes = h.index("<h1>Visão geral</h1>"), h.index('id="vg-pesquisa"')
    for sid in SECOES[:4]:
        assert i_h1 < h.index(f'id="vg-ap-{sid}"') < i_secoes, sid
    ultima = max(h.index(f'id="vg-{s}"') for s in re.findall(r'<section class="vg-secao" id="vg-([a-z_]+)"', h))
    for sid in SECOES[4:]:
        assert ultima < h.index(f'id="vg-ap-{sid}"') < h.index('id="guia-geral"'), sid
    _posicoes_exatas(h)
    for sid in SECOES:
        i = h.index(f'id="vg-ap-{sid}"')
        trecho = h[i:h.index("</section>", i)]
        assert f'<h2 id="t-vg-ap-{sid}">{TITULOS[sid]}</h2>' in trecho
        tag = LISTAS.get(sid)
        if tag:
            itens = re.findall(rf"<{tag}>(.*?)</{tag}>", trecho, re.S)
            assert len(itens) == 1 and re.findall(r"<li>(.*?)</li>", itens[0], re.S) == list(TEXTOS[sid]), sid
            assert "<p>" not in trecho
        else:
            assert re.findall(r"<p>(.*?)</p>", trecho, re.S) == list(TEXTOS[sid]) and "<li>" not in trecho, sid


def test_a_apresentacao_so_acrescenta_secoes(real):
    """Tirando as secoes da apresentacao, a pagina e a mesma de quando nao ha texto: nada mais muda, nenhum numero."""
    app, ctx, *_ = real
    cli = TestClient(app)
    sem = cli.get("/").text
    ctx.apresentacao = dict(TEXTOS)
    com = cli.get("/").text
    assert com != sem and _sem_apresentacao(com) == sem
    ctx.apresentacao = {k: ("PREENCHA",) for k in SECOES}
    assert cli.get("/").text == sem


def test_secao_invalida_some_e_as_outras_ficam(real):
    app, ctx, *_ = real
    ctx.apresentacao = dict(TEXTOS, perguntas=("PREENCHA",), instituicao=("",))
    assert _secoes_ap(TestClient(app).get("/").text) == ["descricao", "metodo", "abrangencia", "limitacoes"]


def test_texto_e_escapado(real):
    app, ctx, *_ = real
    ctx.apresentacao = {"descricao": ('<script>alert(1)</script> & "aspas" <b>negrito</b>',)}
    h = TestClient(app).get("/").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &#34;aspas&#34; &lt;b&gt;negrito&lt;/b&gt;" in h
    assert "<script>alert(1)" not in h and "<b>negrito" not in h


def test_rota_le_o_contexto_a_cada_visita_pela_regra_do_dominio(real, monkeypatch):
    """A rota chama dominio.apresentacao.secoes_publicas com o valor do Contexto naquela visita (ancora: a regra e uma so)."""
    app, ctx, *_ = real
    vistos = []
    monkeypatch.setattr(AP, "secoes_publicas", lambda textos: vistos.append(textos) or
                        {"antes": [{"id": "metodo", "titulo": "Título trocado", "lista": None, "paragrafos": ["Parágrafo trocado."]}],
                         "depois": []})
    ctx.apresentacao = {"qualquer": ("coisa",)}
    h = TestClient(app).get("/").text
    assert vistos == [{"qualquer": ("coisa",)}]
    assert '<h2 id="t-vg-ap-metodo">Título trocado</h2>' in h and "<p>Parágrafo trocado.</p>" in h


def test_quem_entrou_nao_ve_e_nao_chama_a_regra(real, monkeypatch):
    app, ctx, contas, contas_db, _ = real
    painel = (TestClient(app), contas, None, contas_db)
    for grupo in ("Leitor", "Revisor", "Administrador"):
        _criar(painel, grupo.lower(), grupo)
        cli = TestClient(app)
        assert _entrar(cli, grupo.lower()).status_code == 303
        ctx.apresentacao = {}
        antes = cli.get("/").text
        ctx.apresentacao = dict(TEXTOS)
        chamadas = []
        original = AP.secoes_publicas
        monkeypatch.setattr(AP, "secoes_publicas", lambda t: chamadas.append(t) or original(t))
        assert cli.get("/").text == antes and chamadas == [], grupo
        monkeypatch.setattr(AP, "secoes_publicas", original)


def test_painel_sem_login_nao_muda(demo, tmp_path, monkeypatch):  # noqa: F811
    db, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(db, copia)
    ctx = _ctx(autenticacao=False)
    cli = TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx))
    antes = cli.get("/").text
    ctx.apresentacao = dict(TEXTOS)
    chamadas = []
    original = AP.secoes_publicas
    monkeypatch.setattr(AP, "secoes_publicas", lambda t: chamadas.append(t) or original(t))
    assert cli.get("/").text == antes and "vg-ap-" not in antes and chamadas == []


def test_sem_banco_nao_muda_e_nao_chama_a_regra(tmp_path, monkeypatch):
    """Sem o arquivo do banco, o visitante recebe a pagina de banco ausente de sempre, sem apresentacao e sem chamar a regra."""
    ausente = tmp_path / "nao_existe.db"
    contas = ContasSQLite(tmp_path / "contas.db")
    gravar_politica(contas, "real")
    ctx = _ctx()
    cli = TestClient(criar_app(LeituraPainelSQLite(ausente), lambda: RepositorioSQLite(ausente), BrutoLocal(tmp_path), ctx, contas=contas))
    antes = cli.get("/")
    ctx.apresentacao = dict(TEXTOS)
    chamadas = []
    original = AP.secoes_publicas
    monkeypatch.setattr(AP, "secoes_publicas", lambda t: chamadas.append(t) or original(t))
    depois = cli.get("/")
    assert (depois.status_code, depois.text) == (antes.status_code, antes.text) and "vg-ap-" not in depois.text and chamadas == []
    assert not ausente.exists()


@pytest.mark.parametrize("estado", ["ausente", "fechada", "invalida"])
def test_pesquisa_nao_divulgada_leva_a_entrada_sem_nenhum_texto(demo, tmp_path, estado):  # noqa: F811
    db, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(db, copia)
    ctx = _ctx(apresentacao=dict(TEXTOS))
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    if estado == "fechada":
        gravar_politica(contas, "real", publica=False)
    elif estado == "invalida":
        with contas._conexao(escrita=True) as conn:
            conn.execute("INSERT INTO configuracoes (chave, valor) VALUES ('divulgacao:real', '{\"publica\": 1}')")
    cli = TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas))
    r = cli.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar")
    entrada = cli.get("/entrar").text
    for paragrafos in TEXTOS.values():
        for p in paragrafos:
            assert p not in entrada
    assert "vg-ap-" not in entrada


def test_mesmo_numero_de_consultas_com_e_sem_textos(real, monkeypatch):
    from adaptadores import leitura_sqlite
    app, ctx, *_ = real
    cli = TestClient(app)
    cli.get("/")
    cmds = []
    original = leitura_sqlite.sqlite3.connect

    def conectar(*a, **k):
        c = original(*a, **k)
        c.set_trace_callback(lambda s: cmds.append(s.strip().split()[0].upper()))
        return c
    monkeypatch.setattr(leitura_sqlite.sqlite3, "connect", conectar)
    cli.get("/")
    sem = list(cmds)
    cmds.clear()
    ctx.apresentacao = dict(TEXTOS)
    cli.get("/")
    assert cmds == sem and sem


def test_banco_vies_tambem(banco, tmp_path):  # noqa: F811
    from test_validacao_vies import _contexto
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    contas = ContasSQLite(tmp_path / "contas_vies.db")
    gravar_politica(contas, "vies")
    cli = TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas))
    sem = cli.get("/").text
    ctx.apresentacao = dict(TEXTOS)
    com = cli.get("/").text
    assert _secoes_ap(com) == SECOES and _sem_apresentacao(com) == sem
    _posicoes_exatas(com)


# ======================== a ligacao: main.py passa o texto da pesquisa aberta ========================
MARCADOS = {b: {"descricao": (f"Texto da pesquisa {b}.",)} for b in ("real", "vies", "simulado", "demo")}


@pytest.mark.parametrize("args, esperado", [(["painel", "--somente-leitura"], "real"),
                                            (["painel", "--banco", "vies", "--somente-leitura"], "vies"),
                                            (["painel", "--simulado", "--somente-leitura"], "simulado")])
def test_main_escolhe_o_texto_pela_pesquisa_aberta(ambiente_cli, monkeypatch, args, esperado):
    """O comando painel passa o texto da pesquisa que abriu, lido de config.apresentacao na hora (nunca de outra pesquisa)."""
    import sys
    import uvicorn
    import main
    import painel.app as painel_app
    from config import apresentacao as CA
    import config.settings as S
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", ambiente_cli / "data" / "busca.db")
    monkeypatch.setitem(S.OPCOES["local"], "raiz", ambiente_cli / "data" / "raw")
    monkeypatch.setattr(CA, "APRESENTACAO", MARCADOS)
    capturado = {}
    criar_original = painel_app.criar_app
    monkeypatch.setattr(painel_app, "criar_app", lambda leitura, fab, bruto, contexto, **kw:
                        capturado.update(contexto=contexto) or criar_original(leitura, fab, bruto, contexto, **kw))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: capturado.update(app=app))
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    main.main()
    assert capturado["contexto"].banco == esperado and capturado["contexto"].apresentacao == MARCADOS[esperado]
    monkeypatch.setattr(CA, "APRESENTACAO", {k: v for k, v in MARCADOS.items() if k != esperado})
    main.main()
    assert capturado["contexto"].apresentacao == {}


def test_main_passa_os_textos_da_pesquisa_do_painel(ambiente_cli, monkeypatch):
    """`abrir_painel` le config.apresentacao.APRESENTACAO ao montar o Contexto e passa o valor da pesquisa aberta; pesquisa sem
    chave (demonstracao) recebe {}."""
    import types
    import uvicorn
    import main
    import painel.app as painel_app
    import painel_demo
    from composicao import Fabrica
    from config import apresentacao as CA
    marcado = {"descricao": ("Texto da demonstração.",)}
    monkeypatch.setattr(CA, "APRESENTACAO", {"demo": marcado, "real": {"descricao": ("Outro.",)}})
    capturado = {}
    criar_original = painel_app.criar_app
    monkeypatch.setattr(painel_app, "criar_app", lambda leitura, fab, bruto, contexto, **kw:
                        capturado.update(contexto=contexto) or criar_original(leitura, fab, bruto, contexto, **kw))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: capturado.update(app=app))
    painel_demo.construir(main.S.DATA_DIR)
    a = types.SimpleNamespace(host="127.0.0.1", porta=8000, somente_leitura=True, demo=True, simulado=False)
    main.abrir_painel(a, Fabrica(demo=True))
    assert capturado["contexto"].apresentacao == marcado
    monkeypatch.setattr(CA, "APRESENTACAO", {"real": {"descricao": ("Outro.",)}})
    main.abrir_painel(a, Fabrica(demo=True))
    assert capturado["contexto"].apresentacao == {}
