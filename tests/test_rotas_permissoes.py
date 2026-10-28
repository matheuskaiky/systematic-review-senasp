"""Regra explicita de permissao para cada rota do painel: a tabela de rotas, o catalogo de permissoes, a cobertura de todas as
rotas registradas, HEAD tratado como GET so na autorizacao e o acesso positivo e negativo de cada grupo padrao.
"""
from urllib.parse import urlsplit

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from painel.app import Contexto, criar_app
from test_autenticacao import _criar, _entrar, painel  # noqa: F401
from test_painel import demo  # noqa: F401

ADM, LOG = A.SO_ADMIN, A.LOGADO

REGRAS = (
    ("GET", "/entrar", None),
    ("POST", "/entrar", None),
    ("POST", "/sair", None),
    ("GET", "/", "ver_painel"),
    ("GET", "/estados", "ver_painel"),
    ("GET", "/estados/{uf}", "ver_painel"),
    ("GET", "/execucoes", "ver_chamadas"),
    ("GET", "/execucoes/resultado.xlsx", "ver_chamadas"),
    ("GET", "/execucoes/comparar", "ver_chamadas"),
    ("GET", "/execucoes/{run_id}", "ver_chamadas"),
    ("GET", "/chamadas", "ver_chamadas"),
    ("GET", "/chamadas/{chamada_id}", "ver_chamadas"),
    ("GET", "/chamadas/{chamada_id}/bruto", "ver_chamadas"),
    ("GET", "/literatura", "ver_painel"),
    ("GET", "/literatura/catalogo.xlsx", "triar_artigos"),
    ("GET", "/literatura/referencias", "ver_painel"),
    ("GET", "/literatura/referencias.xlsx", "ver_painel"),
    ("GET", "/literatura/referencias/web/{referencia_id}", "ver_painel"),
    ("GET", "/literatura/artigos", "ver_painel"),
    ("GET", "/literatura/artigos/{artigo_id}", "ver_painel"),
    ("GET", "/literatura/triagem", "ver_painel"),
    ("GET", "/literatura/prisma", "ver_painel"),
    ("GET", "/achados", "ver_painel"),
    ("GET", "/achados/casos.xlsx", "verificar_achados"),
    ("GET", "/achados/{achado_id}", "ver_painel"),
    ("GET", "/revisao/achados", "ver_painel"),
    ("GET", "/analises", "ver_painel"),
    ("GET", "/classificadores", "ver_painel"),
    ("GET", "/metodologia", "ver_painel"),
    ("GET", "/observatorio", "ver_painel"),
    ("GET", "/observatorio/obras", "ver_painel"),
    ("GET", "/sobre", "ver_painel"),
    ("GET", "/buscar-texto", "ver_painel"),
    ("GET", "/solucoes", "ver_painel"),
    ("GET", "/triagem-escopo", "ver_painel"),
    ("GET", "/validacao", "ver_painel"),
    ("GET", "/validacao/{ordem}", "ver_painel"),
    ("GET", "/estatisticas-usuarios", "ver_estatisticas_usuarios"),
    ("GET", "/conta", LOG),
    ("GET", "/admin", ADM),
    ("GET", "/admin/usuarios", ADM),
    ("GET", "/admin/usuarios/{usuario_id}", ADM),
    ("GET", "/admin/grupos", ADM),
    ("GET", "/admin/grupos/{grupo_id:digitos}", ADM),
    ("GET", "/admin/auditoria", ADM),
    ("POST", "/literatura/artigos/{artigo_id}/triar", "triar_artigos"),
    ("POST", "/literatura/artigos/{artigo_id}/sugerir", "triar_artigos"),
    ("POST", "/literatura/artigos/{artigo_id}/sugestoes/{sugestao_id}/{acao}", "triar_artigos"),
    ("POST", "/achados/{achado_id}/verificar", "verificar_achados"),
    ("POST", "/achados/{achado_id}/sugerir", "verificar_achados"),
    ("POST", "/achados/{achado_id}/sugestoes/{sugestao_id}/{acao}", "verificar_achados"),
    ("POST", "/achados/{achado_id}/desfazer", "verificar_achados"),
    ("POST", "/achados/{achado_id}/revogar", "revogar_verificacao"),
    ("POST", "/validacao/sortear", ADM),
    ("POST", "/validacao/{ordem}/triar", "triar_artigos"),
    ("POST", "/conta/token", "enviar_coletas"),
    ("POST", "/conta/token/revogar", LOG),
    ("POST", "/admin/usuarios", ADM),
    ("POST", "/admin/usuarios/{usuario_id}", ADM),
    ("POST", "/admin/grupos", ADM),
    ("POST", "/admin/grupos/novo", ADM),
    ("POST", "/admin/grupos/{grupo_id}/renomear", ADM),
    ("GET", "/api/coletas", ADM),
    ("POST", "/api/coletas", ADM),
    ("PUT", "/api/coletas", ADM),
    ("PATCH", "/api/coletas", ADM),
    ("DELETE", "/api/coletas", ADM),
    ("OPTIONS", "/api/coletas", ADM),
)

MODULOS = {"consulta": "Consulta da pesquisa", "revisao": "Revisão e validação", "acompanhamento": "Acompanhamento",
           "tecnico": "Dados técnicos"}

CATALOGO = {
    "ver_painel": {"modulo": "consulta", "sensibilidade": None, "depende_de": ()},
    "ver_nomes_revisores": {"modulo": "acompanhamento", "sensibilidade": "dados_pessoais", "depende_de": ("ver_painel",)},
    "ver_chamadas": {"modulo": "tecnico", "sensibilidade": "tecnica_restrita", "depende_de": ("ver_painel",)},
    "verificar_achados": {"modulo": "revisao", "sensibilidade": "escrita", "depende_de": ("ver_painel",)},
    "revogar_verificacao": {"modulo": "revisao", "sensibilidade": "supervisao", "depende_de": ("verificar_achados",)},
    "triar_artigos": {"modulo": "revisao", "sensibilidade": "escrita", "depende_de": ("ver_painel",)},
    "triar_texto_completo": {"modulo": "revisao", "sensibilidade": "escrita", "depende_de": ("triar_artigos",)},
    "ver_estatisticas_usuarios": {"modulo": "acompanhamento", "sensibilidade": "dados_pessoais", "depende_de": ("ver_painel",)},
    "enviar_coletas": {"modulo": "tecnico", "sensibilidade": "escrita_externa", "depende_de": ()},
    "ver_registros_revisao": {"modulo": "consulta", "sensibilidade": "dados_revisao", "depende_de": ("ver_painel",)},
    "ver_custos": {"modulo": "tecnico", "sensibilidade": "financeira", "depende_de": ("ver_painel",)},
}


def _exemplo(padrao, valor="1"):
    """Um caminho concreto para o padrao: cada `{parametro}` vira `valor` (`{uf}` vira PI)."""
    partes = []
    for p in padrao.split("/"):
        partes.append(("PI" if p == "{uf}" else valor) if p.startswith("{") else p)
    return "/".join(partes)


# ---------------- tabela e catalogo ----------------
def test_tabela_de_regras_exata():
    assert A.REGRAS_ROTAS == REGRAS


def test_catalogo_de_permissoes_exato():
    assert A.MODULOS_PERMISSAO == MODULOS and list(A.MODULOS_PERMISSAO) == list(MODULOS)
    assert A.CATALOGO_PERMISSOES == CATALOGO and list(A.CATALOGO_PERMISSOES) == list(A.PERMISSOES)
    for chave, meta in A.CATALOGO_PERMISSOES.items():
        assert list(meta) == ["modulo", "sensibilidade", "depende_de"] and isinstance(meta["depende_de"], tuple)
        assert meta["modulo"] in A.MODULOS_PERMISSAO
        assert meta["sensibilidade"] in A.SENSIBILIDADES
        assert all(d in A.PERMISSOES and d != chave for d in meta["depende_de"])
    assert A.SENSIBILIDADES == (None, "escrita", "supervisao", "dados_pessoais", "tecnica_restrita", "escrita_externa", "dados_revisao",
                                "financeira")


def test_permissoes_e_grupos_padrao_exatos():
    """Descricoes, grupos padrao, listas de escrita, de proibidas ao visitante e de acoes auditadas, exatamente. As duas permissoes
    de leitura de registros de revisao e de custos entram no fim, proibidas ao visitante e semeadas no Leitor e no Revisor novos."""
    assert list(A.PERMISSOES.items()) == [
        ("ver_painel", "Ver as páginas de leitura (visão geral, estados, achados, literatura, análises, soluções, metodologia, "
                       "triagem de escopo)"),
        ("ver_nomes_revisores", "Ver os nomes de quem decidiu (históricos, verificações e concordância)"),
        ("ver_chamadas", "Ver execuções, chamadas e o conteúdo bruto das APIs"),
        ("verificar_achados", "Verificar achados e desfazer as próprias decisões"),
        ("revogar_verificacao", "Revogar verificações de achados"),
        ("triar_artigos", "Triar artigos por título e resumo"),
        ("triar_texto_completo", "Triar artigos por texto completo"),
        ("ver_estatisticas_usuarios", "Ver as estatísticas por usuário"),
        ("enviar_coletas", "Gerar o próprio token e enviar coletas do computador local para a nuvem"),
        ("ver_registros_revisao", "Ver observações e motivos das decisões"),
        ("ver_custos", "Ver custos das execuções")]
    assert A.PERMISSOES_ESCRITA == {"verificar_achados", "revogar_verificacao", "triar_artigos", "triar_texto_completo"}
    assert A.PERMISSOES_PROIBIDAS_VISITANTE == A.PERMISSOES_ESCRITA | {"ver_estatisticas_usuarios", "enviar_coletas", "ver_custos",
                                                                      "ver_registros_revisao"}
    assert A.GRUPOS_PADRAO == {
        "Administrador": set(A.PERMISSOES), "Visitante": {"ver_painel"},
        "Leitor": {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"},
        "Revisor": {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "verificar_achados", "triar_artigos", "triar_texto_completo",
                    "ver_registros_revisao", "ver_custos"}}
    assert A.ACOES_AUDITORIA == ("criar_usuario", "editar_usuario", "redefinir_senha", "desativar_usuario", "reativar_usuario",
                                 "salvar_permissoes", "criar_grupo", "renomear_grupo", "gerar_token", "revogar_token")


# ---------------- regra explicita e permissao exigida ----------------
@pytest.mark.parametrize("metodo,padrao,permissao", REGRAS)
def test_cada_regra_casa_com_o_proprio_exemplo(metodo, padrao, permissao):
    caminho = _exemplo(padrao)
    assert A.regra_explicita(metodo, caminho) == (metodo, padrao, permissao)
    assert A.permissao_exigida(metodo, caminho) == permissao


@pytest.mark.parametrize("metodo,caminho,esperado", [
    # o literal vem antes do parametro na tabela: a planilha de casos nao vira uma pagina de achado
    ("GET", "/achados/casos.xlsx", "verificar_achados"), ("GET", "/achados/7", "ver_painel"),
    ("GET", "/execucoes/comparar", "ver_chamadas"), ("GET", "/validacao/sortear", "ver_painel"),
    # HEAD tem a mesma regra do GET, so para a autorizacao
    ("HEAD", "/", "ver_painel"), ("HEAD", "/achados/casos.xlsx", "verificar_achados"), ("HEAD", "/chamadas/3/bruto", "ver_chamadas"),
    ("HEAD", "/admin/usuarios", ADM), ("HEAD", "/entrar", None), ("HEAD", "/conta", LOG), ("HEAD", "/static/painel.css", None),
    ("HEAD", "/nao-existe", "ver_painel"), ("HEAD", "/api/coletas", ADM),
    # o que nao esta na tabela segue as regras de reserva de antes
    ("GET", "/static/painel.css", None), ("GET", "/static/x/y.js", None),
    ("GET", "/sair", None), ("PUT", "/entrar", None), ("DELETE", "/sair", None),           # entrada e saida: livres em qualquer metodo, como antes
    ("GET", "/administracao", "ver_painel"), ("GET", "/entrar/", "ver_painel"), ("GET", "/nao-existe/1", "ver_painel"),
    ("GET", "/admin/qualquer", ADM), ("GET", "/admin/usuarios/1/x", ADM), ("POST", "/admin/x/verificar", ADM),
    ("GET", "/execucoes/x/y", "ver_chamadas"), ("GET", "/chamadas/1/bruto/2", "ver_chamadas"),
    ("POST", "/chamadas/1", ADM), ("POST", "/achados/5/verificar/", ADM), ("PUT", "/achados/5/verificar", ADM),
    ("POST", "/qualquer/outra", ADM), ("DELETE", "/", ADM), ("OPTIONS", "/", ADM),
    # sufixos parecidos fora da tabela nao herdam mais a permissao pelo sufixo
    ("POST", "/execucoes/x/verificar", ADM), ("POST", "/achados/5/sugestoes/2/aceitar/x", ADM),
    # a rota de sugestao aceita qualquer acao (o servidor responde 404 a uma acao invalida): a regra e a da rota inteira
    ("POST", "/achados/5/sugestoes/2/aceitar", "verificar_achados"), ("POST", "/achados/5/sugestoes/2/descartar", "verificar_achados"),
    ("POST", "/achados/5/sugestoes/2/outro", "verificar_achados"), ("POST", "/achados/5/sugestoes/2/verificar", "verificar_achados"),
    ("POST", "/achados/5/sugestoes/2/triar", "verificar_achados"), ("POST", "/achados/5/sugestoes/2/revogar", "verificar_achados"),
    ("POST", "/literatura/artigos/5/sugestoes/2/aceitar", "triar_artigos"),
    ("POST", "/literatura/artigos/5/sugestoes/2/outro", "triar_artigos"), ("POST", "/literatura/artigos/5/sugestoes/2/triar", "triar_artigos"),
    ("POST", "/literatura/artigos/5/sugestoes/2/verificar", "triar_artigos"),
    ("POST", "/literatura/artigos/5/sugestoes/2/desfazer", "triar_artigos"), ("POST", "/achados/5/sugestoes//aceitar", ADM),
    ("POST", "/achados/5/sugestoes/2/desfazer", "verificar_achados"), ("POST", "/achados/5/sugestoes/2/sugerir", "verificar_achados"),
    ("POST", "/literatura/artigos/5/sugestoes/2/descartar", "triar_artigos"),
    ("POST", "/literatura/artigos/5/sugestoes/2/revogar", "triar_artigos"), ("POST", "/literatura/artigos/5/sugestoes/2/sugerir", "triar_artigos"),
    ("POST", "/validacao/1/triar/x", ADM), ("POST", "/literatura/artigos//triar", ADM), ("GET", "/estados//", "ver_painel"),
])
def test_permissao_exigida_fora_da_tabela_e_head(metodo, caminho, esperado):
    assert A.permissao_exigida(metodo, caminho) == esperado


@pytest.mark.parametrize("metodo,caminho", [
    ("GET", "/static/painel.css"), ("GET", "/nao-existe"), ("GET", "/admin/qualquer"), ("POST", "/execucoes/x/verificar"),
    ("GET", "/estados/"), ("GET", "/estados/PI/x"), ("POST", "/literatura/artigos//triar"), ("GET", ""),
    ("TRACE", "/"), ("get", "/"),
])
def test_regra_explicita_ausente(metodo, caminho):
    assert A.regra_explicita(metodo, caminho) is None


@pytest.mark.parametrize("caminho,esperado", [
    ("/estados/São Paulo", ("GET", "/estados/{uf}", "ver_painel")), ("/estados/a.b-c_d", ("GET", "/estados/{uf}", "ver_painel")),
    ("/estados/" + "x" * 300, ("GET", "/estados/{uf}", "ver_painel")), ("/Estados/PI", None), ("/ESTADOS", None),
    ("/estados", ("GET", "/estados", "ver_painel")), ("/literatura/referencias/web/9", ("GET", "/literatura/referencias/web/{referencia_id}", "ver_painel")),
    ("/literatura/referencias/web/", None), ("/literatura/referencias//9", None), ("/achados/CASOS.XLSX", ("GET", "/achados/{achado_id}", "ver_painel")),
])
def test_casamento_de_padroes_nos_limites(caminho, esperado):
    assert A.regra_explicita("GET", caminho) == esperado


@pytest.mark.parametrize("caminho,esperado", [
    ("/achados/1/sugestoes/2/aceitar", ("POST", "/achados/{achado_id}/sugestoes/{sugestao_id}/{acao}", "verificar_achados")),
    ("/achados//sugestoes/2/aceitar", None), ("/achados/1/sugestoes/2/", None), ("/achados/1/Sugestoes/2/aceitar", None),
    ("/literatura/artigos/1/sugestoes/2/x", ("POST", "/literatura/artigos/{artigo_id}/sugestoes/{sugestao_id}/{acao}", "triar_artigos")),
])
def test_varios_parametros_no_mesmo_padrao(caminho, esperado):
    assert A.regra_explicita("POST", caminho) == esperado


def test_a_primeira_regra_da_tabela_vence(monkeypatch):
    """A tabela e lida a cada chamada: com duas regras que casam o mesmo caminho, vale a que vem antes."""
    monkeypatch.setattr(A, "REGRAS_ROTAS", (("GET", "/x/{a}", "ver_painel"), ("GET", "/x/y", ADM)))
    assert A.regra_explicita("GET", "/x/y") == ("GET", "/x/{a}", "ver_painel") and A.permissao_exigida("GET", "/x/y") == "ver_painel"
    monkeypatch.setattr(A, "REGRAS_ROTAS", (("GET", "/x/y", ADM), ("GET", "/x/{a}", "ver_painel")))
    assert A.regra_explicita("GET", "/x/y") == ("GET", "/x/y", ADM) and A.permissao_exigida("GET", "/x/y") == ADM
    assert A.regra_explicita("GET", "/x/z") == ("GET", "/x/{a}", "ver_painel")


def test_parametro_nao_casa_segmento_vazio_nem_barra():
    assert A.regra_explicita("GET", "/estados/PI") == ("GET", "/estados/{uf}", "ver_painel")
    assert A.regra_explicita("GET", "/estados/") is None and A.regra_explicita("GET", "/estados/a/b") is None


# ---------------- cobertura: toda rota registrada tem regra explicita ----------------
@pytest.fixture
def app_completo(demo, tmp_path):
    banco, raw = demo
    ctx = Contexto(banco="real", nome_banco=banco.name, somente_leitura=False, pasta_backup=tmp_path / "backups",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
                   status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",), autenticacao=True, aceita_envios=True)
    return criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(raw), ctx,
                     contas=ContasSQLite(tmp_path / "contas.db"))


def _pares_registrados(app):
    pares = set()
    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue
        pares |= {(metodo, rota.path) for metodo in rota.methods}
    return pares


def test_toda_rota_registrada_tem_regra_explicita(app_completo):
    pares = _pares_registrados(app_completo)
    assert len(pares) == 69                       # os 68 pares da tabela e o HEAD que a rota de envios declara
    sem_regra = sorted((m, p) for m, p in pares if A.regra_explicita("GET" if m == "HEAD" else m, _exemplo(p)) is None)
    assert sem_regra == []


def test_toda_regra_corresponde_a_uma_rota_registrada(app_completo):
    pares = {(m, p) for m, p in _pares_registrados(app_completo) if m != "HEAD"}
    assert {(m, p) for m, p, _ in REGRAS} == pares


def test_rota_nova_sem_regra_e_apontada_pela_cobertura(app_completo):
    @app_completo.get("/rota-nova-de-teste")
    def _nova():
        return {}
    sem_regra = [(m, p) for m, p in _pares_registrados(app_completo) if A.regra_explicita("GET" if m == "HEAD" else m,
                                                                                                _exemplo(p)) is None]
    assert ("GET", "/rota-nova-de-teste") in sem_regra


# ---------------- acesso positivo e negativo de cada grupo padrao ----------------
GRUPOS = ("Visitante", "Leitor", "Revisor", "Administrador")


@pytest.fixture
def clientes(painel):  # noqa: F811
    cli, _, _, _ = painel
    saida = {"Visitante": cli}
    for grupo in GRUPOS[1:]:
        login = grupo.lower()
        _criar(painel, login, grupo)
        c = TestClient(cli.app)
        assert _entrar(c, login).status_code == 303
        saida[grupo] = c
    return saida


def _negado(resposta, grupo):
    """Recusa do controle de acesso: o visitante vai para a entrada (303); quem entrou recebe 403."""
    if grupo == "Visitante":
        return resposta.status_code == 303 and urlsplit(resposta.headers["location"]).path == "/entrar"
    return resposta.status_code == 403


def _concedido(resposta):
    """Passou pelo controle de acesso: sem 401 nem 403, sem ida para a entrada e sem erro do servidor. Um 404 de registro que nao
    existe, um 405 do roteador ou um redirecionamento para outra pagina do painel contam como acesso concedido."""
    if resposta.status_code >= 500 or resposta.status_code in (401, 403):
        return False
    if resposta.status_code in (301, 302, 303, 307, 308):
        return urlsplit(resposta.headers["location"]).path != "/entrar"
    return True


@pytest.mark.parametrize("metodo", ["GET", "HEAD"])
def test_acesso_de_cada_grupo_em_cada_rota_de_leitura(clientes, metodo):
    erros = []
    for m, padrao, permissao in REGRAS:
        if m != "GET" or padrao in ("/entrar", "/api/coletas"):
            continue
        caminho = _exemplo(padrao)
        for grupo in GRUPOS:
            pode = A.pode(grupo, A.GRUPOS_PADRAO[grupo], permissao)
            r = clientes[grupo].request(metodo, caminho, follow_redirects=False)
            if (pode and not _concedido(r)) or (not pode and not _negado(r, grupo)):
                erros.append((metodo, caminho, grupo, pode, r.status_code))
    assert erros == []


def test_escritas_negadas_a_quem_nao_tem_a_permissao(clientes):
    erros = []
    for m, padrao, permissao in REGRAS:
        if m != "POST" or permissao is None or padrao == "/api/coletas":
            continue
        for grupo in GRUPOS:
            if A.pode(grupo, A.GRUPOS_PADRAO[grupo], permissao):
                continue
            r = clientes[grupo].post(_exemplo(padrao), data={}, follow_redirects=False)
            if not _negado(r, grupo):
                erros.append((padrao, grupo, r.status_code))
    assert erros == []


def test_exportacoes_positivas_e_negativas(clientes):
    """As planilhas: o grupo sem a permissao e recusado; o grupo com ela passa pelo controle de acesso (o conteudo de cada
    planilha tem os testes proprios: test_catalogo_painel, test_casos_estaduais, test_resultado_painel)."""
    casos = {"/literatura/catalogo.xlsx": {"Revisor", "Administrador"}, "/achados/casos.xlsx": {"Revisor", "Administrador"},
             "/execucoes/resultado.xlsx": {"Revisor", "Administrador"}, "/literatura/referencias.xlsx": set(GRUPOS)}
    planilha = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    for caminho, autorizados in casos.items():
        for grupo in GRUPOS:
            r = clientes[grupo].get(caminho, follow_redirects=False)
            if grupo in autorizados and caminho == "/literatura/catalogo.xlsx":
                # este painel de teste nao configura os modelos de planilha: o catalogo responde pelo proprio handler, depois
                # das duas conferencias de permissao (middleware e handler), com a pagina de modelo desconhecido
                assert r.status_code == 404 and "Modelo de planilha desconhecido" in r.text, (caminho, grupo, r.status_code)
            elif grupo in autorizados:
                assert r.status_code == 200 and r.headers["content-type"].startswith(planilha), (caminho, grupo, r.status_code)
            else:
                assert _negado(r, grupo), (caminho, grupo, r.status_code)


def test_head_do_visitante_na_visao_geral_nao_vai_mais_para_a_entrada(clientes):
    """HEAD muda so a autorizacao: o visitante passa pelo controle de acesso (a resposta depois dele e a do roteador)."""
    r = clientes["Visitante"].head("/", follow_redirects=False)
    assert r.status_code == 405                   # passou pelo controle; as rotas GET do painel nao declaram HEAD
    r = clientes["Visitante"].head("/chamadas", follow_redirects=False)
    assert _negado(r, "Visitante")
