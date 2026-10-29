"""Painel de resultados (FastAPI + Jinja2, HTML no servidor). Recebe leitura, fabrica de repositorio e armazenamento
bruto por parametro; nao importa adaptadores, composicao, sqlite3, requests nem le o ambiente."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import mimetypes
import re
import secrets
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit

from typing import Annotated

from fastapi import FastAPI, Form, Path as ParametroDeCaminho, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.templating import Jinja2Templates

from aplicacao import catalogo as catalogo_uc, exportacao, revisao, sugestoes as sugestoes_uc
from dominio.sugestoes import CAMPOS_ACHADO, chave_autor, ficha_da_decisao
from dominio import autenticacao, referencias_busca, relevancia as relev
from dominio.erros import BancoIndisponivel
from dominio.servicos_painel import diff_config, localizar_evidencia, mascarar_segredos, trecho_mais_parecido
from painel import (
    analises_blocos,
    formatacao as fmt,
    mapa_ufs,
    navegacao,
    rotulos,
    visao_geral,
    visao_geral_vies,
)
from painel.entidades import Entidades, explicacao_da_entidade, link_entidade
from painel.graficos import barra_empilhada, barras_horizontais, colunas, mapa_do_brasil, mapa_de_calor

AQUI = Path(__file__).parent
AVISO_BRUTO = "O arquivo bruto não foi encontrado em data/raw."
AVISO_BRUTO_NUVEM = "O arquivo bruto fica no computador onde a coleta rodou: ele não é enviado para a nuvem."
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
FILTROS_CHAMADAS = ("run", "etapa", "provedor", "uf", "resultado", "q")
FILTROS_ARTIGOS = ("q", "decisao", "multi", "termo", "base", "ano_de", "ano_ate", "rel", "brasil", "ordem", "llm")
FILTROS = ("uf", "esfera", "cidade", "tecnologia", "status", "confianca", "evidencia", "oficial", "origem", "solucao", "verificacao", "q")
JANELA_CONTEXTO = 2500            # caracteres de cada lado da evidencia na visao resumida
LIMITE_TEXTO = 200_000            # o visor nunca mostra mais que isto
MAX_PAGINA = 1_000_000            # teto do ?p= (o OFFSET do SQLite estoura acima de 2**63)
MAX_BUSCA = 200
MAX_ENTIDADES_NO_RESUMO = 12      # entidades listadas no resumo de /achados (as demais estao no filtro e em /solucoes)
LIMITE_BRUTO = 200_000            # o visor de arquivos brutos mostra no maximo isto; o arquivo inteiro vai por download
TEMAS_VALIDOS = {"light", "dark"}  # mesmos valores do atributo data-theme; qualquer outra coisa no cookie e ignorada
JANELA_FILA = 15


def _janela(ids, atual):
    """Janela de até 15 itens da fila, centrada no item aberto."""
    if not ids:
        return []
    k = ids.index(atual) if atual in ids else 0
    inicio = max(0, min(k - JANELA_FILA // 2, len(ids) - JANELA_FILA))
    return ids[inicio:inicio + JANELA_FILA]


mimetypes.add_type("font/woff2", ".woff2")  # garante o tipo certo em qualquer sistema; X-Content-Type-Options: nosniff ja esta ligado


class StaticComCache(StaticFiles):
    """Fontes tem nome com o conteudo congelado (versao no nome), entao podem ficar um ano em cache.
    Troque o nome do arquivo ao trocar a fonte. CSS e JS continuam como hoje (sem esta politica)."""

    async def get_response(self, path, scope):
        resposta = await super().get_response(path, scope)
        if path.replace("\\", "/").startswith("fonts/") and resposta.status_code == 200:   # 200 tambem cobre pedidos parciais (206 sai depois)
            resposta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resposta


# o Firebase Hosting so repassa ao Cloud Run o cookie com este nome (os demais sao descartados); por isso um cookie so leva o
# token de CSRF e, com login, o de sessao: "<csrf>" ou "<csrf>.<sessao>"
COOKIE = "__session"
_PARTE_DO_COOKIE = re.compile(r"[A-Za-z0-9_-]{1,128}")   # alfabeto de secrets.token_urlsafe


def ler_cookie(request):
    """(csrf, sessao) do cookie `__session`; sessao e None sem login. Qualquer outro formato, ou o cookie repetido no cabecalho
    (outro subdominio ou outro caminho gravou um igual), vale como cookie ausente: (None, None)."""
    repetidos = [c for c in request.headers.get("cookie", "").split(";") if c.strip().startswith(COOKIE + "=")]
    if len(repetidos) > 1:
        return None, None
    partes = request.cookies.get(COOKIE, "").split(".")
    if len(partes) > 2 or not all(_PARTE_DO_COOKIE.fullmatch(p) for p in partes):
        return None, None
    return partes[0], (partes[1] if len(partes) == 2 else None)


def gravar_cookie(resposta, csrf, sessao, https):
    """Grava `__session` com o token de CSRF e, se houver, o de sessao (sessao None = sem login)."""
    valor = csrf + ("." + sessao if sessao else "")
    resposta.set_cookie(COOKIE, valor, httponly=True, samesite="strict", secure=https, path="/")


def tema_do_cookie(request):
    """Le o cookie `tema` com lista fechada de valores. Valor desconhecido vira None (= seguir o sistema)."""
    valor = request.cookies.get("tema")
    return valor if valor in TEMAS_VALIDOS else None


# numero de linha no banco no caminho do endereco: fora de 1..2^63-1 o SQLite nao aceita o valor (OverflowError, erro 500);
# a validacao do FastAPI responde "Endereco invalido" (404) antes de qualquer consulta
IdDoBanco = Annotated[int, ParametroDeCaminho(ge=1, le=9223372036854775807)]


def _lista_json(texto):
    """'["a", "b"]' -> 'a, b' (os problemas da triagem gravados em JSON); outro texto volta como esta."""
    try:
        v = json.loads(texto) if isinstance(texto, str) else texto
    except ValueError:
        return texto
    return ", ".join(str(x) for x in v) if isinstance(v, list) else texto


def _inteiro(valor, padrao, minimo=1, maximo=MAX_PAGINA):
    """Parametro numerico da URL: vazio usa o padrao; texto ou fora da faixa devolve None (a rota responde 404)."""
    if valor in (None, ""):
        return padrao
    try:
        n = int(str(valor).strip())
    except ValueError:
        return None
    return n if minimo <= n <= maximo else None


@dataclass
class Contexto:
    banco: str                                # "real" | "simulado" | "demo"
    nome_banco: str
    somente_leitura: bool
    pasta_backup: Path
    ufs: dict                                 # sigla -> nome
    status_permitidos: set
    status_definicoes: dict                   # chave -> definicao (vem de config/vocabulario)
    comando_criar_banco: str = "python main.py pipeline-uf --ufs PI --limite 5"
    termos: dict = field(default_factory=dict)      # id -> consulta (so para exibir)
    bases: tuple = ()                               # bases das buscas manuais
    solucoes_conhecidas: tuple = ()                 # SolucaoConhecida (config/solucoes_conhecidas.py), para a pagina /solucoes
    hosts_permitidos: tuple = ("127.0.0.1", "localhost")   # DNS rebinding: qualquer outro Host e recusado
    origens_publicas: tuple = ()        # "https://<dominio>" de um proxy na frente do painel (Firebase Hosting): Origin aceito alem do proprio
    exige_https: bool = False           # no servidor: o proprio endereco so vale em https e os cookies sao sempre Secure
    backup_feito: bool = field(default=False)
    autenticacao: bool = field(default=False)
    modelos_referencias: dict = field(default_factory=dict)      # nome -> ModeloPlanilhaReferencias (config/modelos_exportacao.py)
    categorias_referencias: dict = field(default_factory=dict)   # config/categorias_referencias.py
    eixos_tematicos: dict = field(default_factory=dict)          # config/eixos_tematicos.py
    conjunto_da_consulta: dict = field(default_factory=dict)     # id da consulta da busca de vies -> conjunto (A, B)
    eixos_exploracao: dict = field(default_factory=dict)         # esquema de exploracao da busca de vies (D102)
    versao_triagem_vies: str = ""                                # versao do prompt da triagem da busca de vies (D116)
    versoes_triagem_vies: tuple = ()                             # todas as versoes desse prompt (o cartao do artigo reconhece cada uma)
    recortes_vies: dict = field(default_factory=dict)            # chave -> rotulo do recorte da triagem v2 (D120)
    consultas_literatura: dict = field(default_factory=dict)     # id -> texto das consultas dos conjuntos (so para exibir)
    brutos_aqui: bool = True                                     # False na nuvem: os arquivos brutos ficam no computador da coleta (D99)
    aceita_envios: bool = False                                  # True so no painel da nuvem (PostgreSQL): POST /api/coletas (D98)


def _filtros(params):
    return {k: str(params[k])[:MAX_BUSCA] for k in FILTROS if params.get(k) not in (None, "")}


def _filtros_sql(filtros, ent):
    """Filtros para a leitura: `solucao=<nome canonico>` vira a lista de grafias brutas (nome, uf) da entidade (RC23); `nomeada`, vazio e nome desconhecido nao filtram por entidade."""
    nome = filtros.get("solucao")
    pares = ent.pares_do_canonico(nome) if nome not in (None, "", "nomeada") else []
    return {**filtros, "solucao_pares": pares} if pares else filtros       # nome que nao e de nenhuma entidade nao filtra (como antes)


CONFERENCIAS_SIMULTANEAS = 4   # conferencias de senha (scrypt) ao mesmo tempo no login


def criar_app(leitura, repositorio_fabrica, bruto, contexto, contas=None):
    if contexto.autenticacao and contas is None:
        raise ValueError("criar_app: contas é obrigatório com autenticação")
    if contexto.autenticacao:
        autenticacao.hash_ficticio()   # calculado na partida: o primeiro login inexistente nao paga duas conferencias
        conferencias = threading.BoundedSemaphore(CONFERENCIAS_SIMULTANEAS)
        contas.garantir_padrao()

    app = FastAPI(title="Painel de resultados", docs_url=None, redoc_url=None, openapi_url=None)
    modelos = Jinja2Templates(directory=str(AQUI / "templates"))
    modelos.env.filters["url_segura"] = lambda u: u if str(u or "").lower().startswith(("http://", "https://")) else "#"
    modelos.env.filters["lista_json"] = _lista_json
    modelos.env.globals.update(fmt=fmt, rotulos=rotulos, ctx=contexto, quote=quote, urlencode=urlencode, menu_grupos=navegacao.grupos,
                               link_entidade=link_entidade, dica_entidade=explicacao_da_entidade)
    entidades = Entidades(leitura, contexto)            # nomes de solucao unificados em entidades (RC23), com cache por conjunto de nomes
    app.mount("/static", StaticComCache(directory=str(AQUI / "static")), name="static")

    def _ver_nomes(request):
        if not contexto.autenticacao:
            return True
        if getattr(request.state, "contas_indisponiveis", False):
            return False
        v = getattr(request.state, "ver_nomes", None)
        if v is not None:
            return v
        usuario = getattr(request.state, "usuario", None)
        if usuario:
            return autenticacao.pode(usuario["grupo"], usuario["permissoes"], "ver_nomes_revisores")
        try:
            return autenticacao.pode(autenticacao.GRUPO_VISITANTE, contas.permissoes_do_grupo(autenticacao.GRUPO_VISITANTE), "ver_nomes_revisores")
        except autenticacao.ContasOcupadas:
            return False

    def _perms(request):
        if not contexto.autenticacao:
            return frozenset(autenticacao.PERMISSOES)
        return getattr(request.state, "perms", frozenset())

    def _pode_estatisticas(request):
        if not contexto.autenticacao or getattr(request.state, "contas_indisponiveis", False):
            return False
        usuario = getattr(request.state, "usuario", None)
        if usuario:
            return autenticacao.pode(usuario["grupo"], usuario["permissoes"], "ver_estatisticas_usuarios")
        return False

    def _pode_rota(request):
        def pode_rota(metodo: str, caminho: str) -> bool:
            if metodo == "POST" and contexto.somente_leitura:
                return False
            if not contexto.autenticacao:
                return True
            if getattr(request.state, "contas_indisponiveis", False):
                return False
            grupo = getattr(request.state, "grupo_acesso", None)
            permissoes = getattr(request.state, "permissoes_acesso", None)
            if grupo is None or permissoes is None:
                return False
            return autenticacao.pode_acessar(grupo, permissoes, metodo, caminho)

        return pode_rota

    def _pode_seguir(request):
        """Devolve uma função que verifica se o usuário da requisição pode seguir o endereço dado."""
        pode = _pode_rota(request)

        def seguir(href: str) -> bool:
            return navegacao.pode_seguir(href, pode)

        return seguir

    def _pode_desfazer(request, achado_id, historico):
        """Verifica se o usuário pode desfazer a decisão do achado indicado."""
        usuario = getattr(request.state, "usuario", None)
        grupo = usuario["grupo"] if usuario else None
        nome = usuario["nome"] if usuario else None
        autor = next((h["verificado_por"] for h in historico if not h["desfeita"]), None)
        return bool(
            _pode_rota(request)("POST", f"/achados/{achado_id}/desfazer")
            and leitura.tem_decisao_para_desfazer(achado_id)
            and "verificar_achados" in _perms(request)
            and (not contexto.autenticacao or autenticacao.pode_desfazer_decisao(grupo, nome, autor))
        )

    def pagina(request, modelo, status=200, **dados):
        usuario = getattr(request.state, "usuario", None)
        revisor = usuario["nome"] if usuario else unquote(request.cookies.get("revisor", ""))
        ver_nomes = _ver_nomes(request)
        pode_estatisticas = _pode_estatisticas(request)
        pode_rota = _pode_rota(request)
        pode_seguir = _pode_seguir(request)
        if not contexto.autenticacao:
            ver_detalhes_tecnicos = True
        elif getattr(request.state, "contas_indisponiveis", False):
            ver_detalhes_tecnicos = False
        else:
            grupo_acesso = getattr(request.state, "grupo_acesso", None)
            permissoes_acesso = getattr(request.state, "permissoes_acesso", None)
            if grupo_acesso is None or permissoes_acesso is None:
                ver_detalhes_tecnicos = False
            else:
                ver_detalhes_tecnicos = autenticacao.ve_detalhes_tecnicos(usuario is not None, grupo_acesso, permissoes_acesso)
        return modelos.TemplateResponse(request, modelo, {"revisor": revisor, "csrf": getattr(request.state, "csrf", ""),
                                                          "tema": tema_do_cookie(request),
                                                          "usuario": usuario, "ver_nomes": ver_nomes,
                                                          "pode_estatisticas": pode_estatisticas,
                                                          "ver_custos": "ver_custos" in _perms(request),
                                                          "perms": _perms(request),
                                                          "pode_rota": pode_rota,
                                                          "pode_abrir": lambda c: pode_rota("GET", c),
                                                          "pode_enviar": lambda c: pode_rota("POST", c),
                                                          "pode_seguir": pode_seguir,
                                                          "caminho": request.url.path, **dados,
                                                          "ver_detalhes_tecnicos": ver_detalhes_tecnicos,
                                                          "nome_pesquisa": rotulos.NOMES_PESQUISA.get(contexto.banco)}, status_code=status)

    def erro(request, status, titulo, texto):
        return pagina(request, "erro.html", status=status, titulo=titulo, texto=texto)

    def sem_banco(request):
        return pagina(request, "sem_banco.html", status=503)

    def contas_ocupadas(request):
        """A unica resposta para o banco de contas ocupado (usada aqui e nas rotas extras)."""
        request.state.usuario = None
        request.state.contas_indisponiveis = True
        return erro(
            request,
            503,
            "Banco de contas ocupado",
            "O banco de contas está ocupado. Tente de novo em alguns segundos.",
        )

    # ---------- controle de acesso (quando autenticacao esta ligada) ----------
    if contexto.autenticacao:
        _erro_contas_ocupadas = contas_ocupadas

        @app.middleware("http")
        async def acesso(request: Request, call_next):
            if request.url.path.startswith("/static/"):
                return await call_next(request)
            if request.url.path == "/api/coletas" and contexto.aceita_envios:   # autentica pelo token de envio (D98)
                request.state.usuario, request.state.perms = None, frozenset()
                return await call_next(request)

            agora = datetime.now(timezone.utc).isoformat()
            token = ler_cookie(request)[1]
            usuario = None
            try:
                if token:
                    token_hash = hashlib.sha256(token.encode()).hexdigest()
                    usuario = contas.usuario_da_sessao(token_hash, agora)
                request.state.usuario = usuario
                if usuario:
                    grupo = usuario["grupo"]
                    permissoes = usuario["permissoes"]
                else:
                    grupo = autenticacao.GRUPO_VISITANTE
                    permissoes = contas.permissoes_do_grupo(autenticacao.GRUPO_VISITANTE)
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            request.state.grupo_acesso = grupo
            request.state.permissoes_acesso = permissoes
            request.state.ver_nomes = autenticacao.pode(grupo, permissoes, "ver_nomes_revisores")
            request.state.perms = frozenset(p for p in autenticacao.PERMISSOES if autenticacao.pode(grupo, permissoes, p))

            if autenticacao.pode_acessar(grupo, permissoes, request.method, request.url.path):
                return await call_next(request)
            elif not usuario:
                if request.method == "GET":
                    alvo = request.url.path + ("?" + request.url.query if request.url.query else "")
                else:
                    alvo = "/"
                destino = "/entrar?proximo=" + quote(alvo, safe="")
                sessao_vencida = bool(ler_cookie(request)[1])
                if sessao_vencida:
                    destino += "&aviso=expirada"  # havia sessao, mas ela venceu ou foi encerrada
                resposta = RedirectResponse(destino, status_code=303)
                if sessao_vencida:
                    gravar_cookie(resposta, request.state.csrf, None, _https(request))  # o recado aparece uma vez so
                return resposta
            else:
                return erro(request, 403, "Sem permissão", "Seu grupo não tem permissão para esta página ou ação.")

    # ---------- seguranca: cabecalhos, CSRF (cookie duplicado no formulario) e cookies SameSite=Strict ----------
    @app.middleware("http")
    async def seguranca(request: Request, call_next):
        csrf = ler_cookie(request)[0]
        token = csrf or secrets.token_urlsafe(32)
        request.state.csrf = token
        resposta = await call_next(request)
        estatico = request.url.path.startswith("/static/")
        if not csrf and not estatico and not any(v.startswith(COOKIE + "=") for v in resposta.headers.getlist("set-cookie")):
            gravar_cookie(resposta, token, None, _https(request))
        if resposta.headers.getlist("set-cookie"):
            # nenhum cache guarda uma resposta que grava o cookie: o CDN do Firebase usa `__session` na chave do cache, mas quem
            # chega sem ele receberia o token de outra pessoa (o CDN guarda ate respostas 404 por 10 minutos)
            resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["Content-Security-Policy"] = CSP
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "same-origin"
        if request.url.path == "/entrar":
            resposta.headers["Cache-Control"] = "no-store"  # a pagina de entrada leva token e motivo de recusa
        if resposta.headers.get("content-type", "").startswith("text/html"):
            resposta.headers.append("Vary", "Cookie")  # so as paginas dependem do cookie `tema`; estaticos e redirecionamentos nao
        return resposta

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(contexto.hosts_permitidos))

    origens_publicas = frozenset(contexto.origens_publicas)

    def _https(request):
        return contexto.exige_https or request.url.scheme == "https"

    def _mesma_origem(request):
        """Origin (ou, sem ele, Referer) tem de ser uma origem deste painel: a do proprio pedido (esquema + Host, com a porta;
        no servidor so em https) ou uma de PAINEL_ORIGENS (proxy na frente, como o Firebase Hosting, que chama o Cloud Run com
        outro Host). Comparacao exata, sem curinga. Havendo Origin, o Referer e ignorado. Sem nenhum dos dois (cliente que nao
        e navegador) nao ha o que conferir; o token de CSRF continua exigido. X-Forwarded-Host e X-Fh-Requested-Host nunca contam."""
        origem = request.headers.get("origin")
        if origem is None:
            referer = request.headers.get("referer")
            if referer is None:
                return True
            try:
                partes = urlsplit(referer)
            except ValueError:
                return False
            if "@" in partes.netloc:
                return False
            origem = f"{partes.scheme}://{partes.netloc}"
        host = request.headers.get("host", "")
        if host and (request.url.scheme == "https" or not contexto.exige_https) and origem == f"{request.url.scheme}://{host}":
            return True
        return origem in origens_publicas

    def checar_escrita(request, csrf):
        if contexto.somente_leitura:
            return erro(request, 403, "Modo somente leitura", "O painel foi iniciado com --somente-leitura; nenhuma decisão é gravada.")
        if not _mesma_origem(request):
            return erro(request, 403, "Pedido recusado", "O pedido veio de outro site ou de outra porta, não deste painel.")
        if not csrf or not hmac.compare_digest(csrf.encode("utf-8"), (ler_cookie(request)[0] or "").encode("utf-8")):
            return erro(request, 403, "Formulário recusado", "O token de segurança não confere. Recarregue a página e tente de novo.")
        return None

    @app.exception_handler(RequestValidationError)
    async def parametro_invalido(request, exc):
        return erro(request, 404, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido.")

    @app.exception_handler(404)
    async def nao_encontrado(request, exc):
        return erro(request, 404, "Página não encontrada", "O endereço não existe neste painel.")

    @app.exception_handler(405)
    async def metodo_nao_permitido(request, exc):
        # endereco que so recebe formulario (POST) aberto pela barra de enderecos: pagina de erro do painel, nao JSON cru
        resposta = erro(request, 405, "Endereço só para formulários",
                        "Este endereço só recebe o envio de um formulário. Volte à página anterior e use o botão.")
        resposta.headers.update(getattr(exc, "headers", None) or {})       # mantem o Allow exigido pelo HTTP
        return resposta

    if contexto.autenticacao:
        def _pagina_entrar(request, status, proximo, erro, aviso, login_digitado):
            try:
                sem_admin = not contas.existe_admin_ativo()
                visitante = contas.permissoes_do_grupo(autenticacao.GRUPO_VISITANTE)
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)
            return pagina(
                request,
                "entrar.html",
                status=status,
                proximo=proximo,
                erro=erro,
                aviso=aviso,
                login_digitado=login_digitado,
                sem_admin=sem_admin,
                simulado=(contexto.banco == "simulado"),
                acesso_publico=autenticacao.pode(autenticacao.GRUPO_VISITANTE, visitante, autenticacao.permissao_exigida("GET", "/")),
                minutos_bloqueio=autenticacao.MINUTOS_DE_BLOQUEIO,
                falhas_bloqueio=autenticacao.FALHAS_ATE_BLOQUEIO,
            )

        @app.get("/entrar", response_class=HTMLResponse)
        def entrar_form(request: Request):
            proximo = autenticacao.proximo_seguro(request.query_params.get("proximo") or "/")
            aviso = request.query_params.get("aviso")
            if aviso not in ("expirada", "saiu") or getattr(request.state, "usuario", None):
                aviso = None  # lista fechada; quem ja entrou nao recebe recado de saida nem de sessao vencida
            return _pagina_entrar(request, 200, proximo, None, aviso, "")

        @app.post("/entrar")
        def entrar(request: Request, login: str = Form(""), senha: str = Form(""), proximo: str = Form(""), csrf: str = Form("")):
            bloqueio = checar_escrita(request, csrf)
            if bloqueio:
                return bloqueio

            prox_seguro = autenticacao.proximo_seguro(proximo or "/")
            agora_dt = datetime.now(timezone.utc)
            agora = agora_dt.isoformat()

            l = login.strip()

            def _form_erro(motivo: str, status: int):
                return _pagina_entrar(request, status, prox_seguro, motivo, None, l[:200])

            if autenticacao.validar_login(l) or senha == "" or len(senha) > autenticacao.SENHA_MAX:
                return _form_erro("credenciais", 400)

            try:
                tentativa = contas.reservar_tentativa(l, agora)   # bloqueio conferido e tentativa contada numa transacao so
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            if tentativa["situacao"] == "bloqueado":
                return _form_erro("limite", 429)
            u = tentativa["usuario"]
            # login inexistente ou inativo confere contra o hash ficticio: mesmo tempo de uma senha errada. No maximo
            # CONFERENCIAS_SIMULTANEAS conferencias (scrypt: CPU e ~16 MB cada) rodam ao mesmo tempo; as outras esperam
            with conferencias:
                certa = autenticacao.conferir_senha(senha, u["senha_hash"] if u else autenticacao.hash_ficticio())
            if not u or not certa:
                return _form_erro("credenciais", 400)          # a tentativa ja foi contada na reserva

            try:
                old_token = ler_cookie(request)[1]
                if old_token:
                    contas.fechar_sessao(hashlib.sha256(old_token.encode()).hexdigest())

                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode()).hexdigest()
                aberta = contas.abrir_sessao(u["usuario_id"], token_hash, agora, senha_hash=u["senha_hash"])
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)
            if not aberta:
                return _form_erro("credenciais", 400)          # a senha mudou (ou a conta foi desativada) durante o login

            resposta = RedirectResponse(prox_seguro, status_code=303)
            gravar_cookie(resposta, secrets.token_urlsafe(32), token, _https(request))   # token de CSRF novo a cada entrada
            return resposta

        @app.post("/sair")
        def sair(request: Request, csrf: str = Form("")):
            bloqueio = checar_escrita(request, csrf)
            if bloqueio:
                return bloqueio
            token = ler_cookie(request)[1]
            if token:
                try:
                    contas.fechar_sessao(hashlib.sha256(token.encode()).hexdigest())
                except autenticacao.ContasOcupadas:
                    return _erro_contas_ocupadas(request)
            resposta = RedirectResponse("/entrar?aviso=saiu", status_code=303)
            gravar_cookie(resposta, secrets.token_urlsafe(32), None, _https(request))   # token de CSRF novo ao sair
            return resposta

    # ---------- visao geral ----------
    @app.get("/", response_class=HTMLResponse)
    def geral(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        if contexto.autenticacao:
            logado = request.state.usuario is not None
            grupo = request.state.grupo_acesso
            permissoes = frozenset(request.state.permissoes_acesso)
        else:
            logado = True
            grupo = autenticacao.GRUPO_ADMIN
            permissoes = frozenset(autenticacao.PERMISSOES)
        quem = {
            "logado": logado,
            "grupo": grupo,
            "permissoes": permissoes,
            "pode_rota": _pode_rota(request),
        }
        if contexto.banco == "vies":
            with leitura.instantaneo() as l:
                dados = visao_geral.ler_dados(l, contexto, quem)
        else:
            dados = visao_geral.ler_dados(leitura, contexto, quem)
        secoes = visao_geral.montar(dados, quem)
        return pagina(request, "geral.html", secoes=secoes, banco=contexto.banco)

    # ---------- estados ----------
    def _linhas_ufs():
        por_uf = {l["uf"]: l for l in leitura.resumo_ufs()}
        vazio = {"n_achados": 0, "n_verificados": 0, "n_confirmados": 0, "n_evidencia_ok": 0, "n_fonte_oficial": 0}
        return [{"uf": uf, "nome": nome, **{**vazio, **por_uf.get(uf, {})}} for uf, nome in contexto.ufs.items()]

    @app.get("/estados", response_class=HTMLResponse)
    def estados(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        linhas = _linhas_ufs()
        blocos = {}
        for l in linhas:
            if l["n_confirmados"]:
                blocos[l["uf"]] = ("confirmado", f"{l['n_confirmados']} achado(s) confirmado(s)")
            elif l["n_achados"]:
                blocos[l["uf"]] = ("classificado", f"{l['n_achados']} achado(s), nenhum confirmado ainda")
            else:
                blocos[l["uf"]] = ("sem-achados", "nenhum achado")
        mapa = mapa_do_brasil(blocos, "Situação por estado", "Mapa do Brasil: cada estado é pintado conforme tenha achado confirmado, só classificado ou nenhum; clique abre a página da UF")
        return pagina(request, "estados.html", linhas=linhas, mapa=mapa, credito_mapa=mapa_ufs.CREDITO)

    @app.get("/estados/{uf}", response_class=HTMLResponse)
    def estado(request: Request, uf: str):
        uf = uf.upper()
        if uf not in contexto.ufs:
            return erro(request, 404, "Estado não encontrado", f"“{uf}” não é uma UF conhecida.")
        if not leitura.existe():
            return sem_banco(request)
        res = leitura.achados({"uf": uf}, 1, 200)
        itens = res["itens"]
        grupos = {}
        for a in itens:
            grupos.setdefault(a["tecnologia"], []).append(a)
        return pagina(request, "estado.html", uf=uf, nome=contexto.ufs[uf], grupos=grupos, total=res["total"],
                      mostrados=len(itens), ent=entidades.obter())

    # ---------- execucoes ----------
    def _json(texto):
        try:
            return json.loads(texto) if texto else {}
        except ValueError:
            return {}

    def _arredondar(d):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}

    @app.get("/execucoes", response_class=HTMLResponse)
    def execucoes(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        return pagina(request, "execucoes.html", itens=leitura.execucoes())

    uma_planilha_por_vez = threading.Lock()          # a planilha completa cabe na memoria uma vez; duas ao mesmo tempo, talvez nao

    @app.get("/execucoes/resultado.xlsx")
    def resultado_xlsx(request: Request):
        """A planilha completa de resultados (as mesmas abas do comando `exportar`), lida do banco do painel."""
        if not set(autenticacao.EXIGENCIAS_EXPORTACOES["/execucoes/resultado.xlsx"]) <= _perms(request):  # protege chamadas, nomes, custos e registros de revisão
            return erro(request, 403, "Sem permissão", "Seu grupo não tem permissão para esta página ou ação.")
        if not leitura.existe():
            return sem_banco(request)
        if not uma_planilha_por_vez.acquire(blocking=False):
            return erro(request, 503, "Planilha em preparo",
                        "Outra planilha completa está sendo gerada agora. Tente de novo em alguns segundos.")
        try:
            abas = exportacao.montar_tabelas_painel(leitura, contexto.ufs)
            conteudo = exportacao.planilha_xlsx(abas)
        except BancoIndisponivel:                     # banco ocupado ou fora do ar (SQLite ou PostgreSQL)
            return erro(request, 503, "Banco indisponível",
                        "O banco não respondeu a tempo para gerar a planilha completa. Tente de novo em alguns segundos.")
        finally:
            uma_planilha_por_vez.release()
        prefixo = "" if contexto.banco == "real" else f"{contexto.banco}_"      # C6: simulado e demo nao passam por reais
        nome = f"{prefixo}resultado_{datetime.now():%Y%m%d_%H%M}.xlsx"
        return Response(conteudo,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})

    @app.get("/execucoes/comparar", response_class=HTMLResponse)
    def comparar(request: Request, a: str = "", b: str = ""):
        if not leitura.existe():
            return sem_banco(request)
        todas = leitura.execucoes()
        ea, eb = (leitura.execucao(a) if a else None), (leitura.execucao(b) if b else None)
        if (a and ea is None) or (b and eb is None):
            return erro(request, 404, "Execução não encontrada", "Uma das execuções escolhidas não existe.")
        diferencas = []
        if ea and eb:
            diferencas = diff_config(mascarar_segredos(_json(ea["config_json"])), mascarar_segredos(_json(eb["config_json"])))
        campos = [("consultas_web_ok", "Consultas web"), ("resultados", "Resultados"), ("urls_unicas", "URLs únicas"),
                  ("pares_url_uf_selecionados", "Páginas selecionadas"), ("paginas_baixadas", "Páginas baixadas"),
                  ("paginas_com_texto", "Páginas com texto"), ("classificacoes", "Classificações"), ("achados", "Achados"),
                  ("achados_evidencia_ok", "Achados com evidência"), ("achados_verificados", "Achados verificados")]
        soma = lambda e: sum((c["custo_usd"] or 0) for c in e["custos"]) if e else 0       # download nao tem custo (nulo)
        return pagina(request, "comparar.html", todas=todas, a=a, b=b, ea=ea, eb=eb, diferencas=diferencas, campos=campos,
                      custo_a=soma(ea), custo_b=soma(eb))

    @app.get("/execucoes/{run_id}", response_class=HTMLResponse)
    def execucao(request: Request, run_id: str):
        if not leitura.existe():
            return sem_banco(request)
        e = leitura.execucao(run_id)
        if e is None:
            return erro(request, 404, "Execução não encontrada", f"Não existe a execução “{run_id[:60]}”.")
        f = e["funil"]
        etapas = [("Consultas web", f.get("consultas_web_ok")), ("Resultados", f.get("resultados")), ("URLs únicas", f.get("urls_unicas")),
                  ("Páginas selecionadas", f.get("pares_url_uf_selecionados")), ("Páginas baixadas", f.get("paginas_baixadas")),
                  ("Páginas com texto", f.get("paginas_com_texto")), ("Classificações", f.get("classificacoes")), ("Achados", f.get("achados")),
                  ("Achados verificados", f.get("achados_verificados"))]
        etapas = [(r, v) for r, v in etapas if v]
        funil = barras_horizontais(etapas, f"Funil da execução {run_id}", "Quantidade em cada etapa desta execução", fmt.numero)
        metricas = _arredondar(_json(e["metricas_json"]))
        # Custo da execução só é entregue a quem tem permissão ver_custos
        if "ver_custos" not in _perms(request):
            metricas.pop("custo_usd", None)
        return pagina(request, "execucao.html", e=e, funil=funil, metricas=metricas,
                      abrir_configuracao=request.query_params.get("configuracao") == "1",
                      cfg=mascarar_segredos(_json(e["config_json"])), ambiente=mascarar_segredos(_json(e["ambiente_json"])),
                      custo_total=sum((c["custo_usd"] or 0) for c in e["custos"]))

    # ---------- chamadas ----------
    @app.get("/chamadas", response_class=HTMLResponse)
    def chamadas(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = {k: str(request.query_params[k])[:MAX_BUSCA] for k in FILTROS_CHAMADAS if request.query_params.get(k)}
        n = _inteiro(request.query_params.get("p"), 1)
        if n is None:
            return erro(request, 404, "Página inválida", "O número da página não é válido.")
        res = leitura.chamadas(filtros, n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        return pagina(request, "chamadas.html", res=res, filtros=filtros, n=n, paginas=paginas, base=urlencode(filtros),
                      opcoes=leitura.opcoes_chamadas())

    def _extensao(c):
        return (str(c.get("raw_path") or "").rsplit(".", 1)[-1] if "." in str(c.get("raw_path") or "") else "bin")[:8]

    def _bruto(c):
        """Resposta bruta da chamada para exibir: JSON vira arvore (com segredos mascarados); o resto, texto escapado."""
        if not c.get("raw_path"):
            return {"existe": False}
        try:
            dados = bruto.ler(c["raw_path"])
        except (OSError, ValueError):
            return {"existe": False, "aviso": AVISO_BRUTO if contexto.brutos_aqui else AVISO_BRUTO_NUVEM}
        out = {"existe": True, "tamanho": len(dados), "cortado": len(dados) > LIMITE_BRUTO, "arvore": None, "texto": None}
        amostra = dados[:LIMITE_BRUTO]
        if not out["cortado"]:
            try:
                out["arvore"] = mascarar_segredos(json.loads(dados.decode("utf-8")))
                return out
            except (ValueError, UnicodeDecodeError):
                pass
        if _extensao(c) in ("bin", "pdf") or b"\x00" in amostra[:2000]:
            out["binario"] = True
        else:
            out["texto"] = amostra.decode("utf-8", "replace")
        return out

    @app.get("/chamadas/{chamada_id}", response_class=HTMLResponse)
    def chamada(request: Request, chamada_id: IdDoBanco):
        if not leitura.existe():
            return sem_banco(request)
        c = leitura.chamada(chamada_id)
        if c is None:
            return erro(request, 404, "Chamada não encontrada", f"Não existe a chamada nº {chamada_id}.")
        return pagina(request, "chamada.html", c=c, parametros=mascarar_segredos(_json(c["parametros_json"])),
                      extras=mascarar_segredos(_json(c["extras_json"])), bruto=_bruto(c))

    @app.get("/chamadas/{chamada_id}/bruto")
    def chamada_bruto(request: Request, chamada_id: IdDoBanco):
        c = leitura.chamada(chamada_id) if leitura.existe() else None
        if c is None or not c.get("raw_path"):
            return erro(request, 404, "Arquivo não encontrado", "Esta chamada não tem resposta bruta guardada.")
        try:
            dados = bruto.ler(c["raw_path"])
        except (OSError, ValueError):
            return erro(request, 404, "Arquivo não encontrado", AVISO_BRUTO if contexto.brutos_aqui else AVISO_BRUTO_NUVEM)
        return Response(dados, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="chamada_{chamada_id}.{_extensao(c)}"'})

    # ---------- literatura ----------
    def _filtros_artigos(params):
        return {k: str(params[k])[:MAX_BUSCA] for k in FILTROS_ARTIGOS if params.get(k) not in (None, "")}

    @app.get("/literatura", response_class=HTMLResponse)
    def literatura_geral(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        d = leitura.literatura()
        anos = [(str(l["ano"]), l["n_artigos"]) for l in d["por_ano"]]
        grafico_anos = colunas(anos, "Artigos por ano", "Quantidade de artigos únicos encontrados, por ano de publicação", "ano", "artigos")
        termos = [l["termo_id"] for l in d["por_termo"]]
        valores = {(l["termo_a"], l["termo_b"]): l["n_em_comum"] for l in d["sobreposicao"]}
        valores.update({(l["termo_id"], l["termo_id"]): l["n_artigos"] for l in d["por_termo"]})
        calor = mapa_de_calor(termos, valores, "Artigos em comum entre termos", "Cada célula é o número de artigos encontrados pelos dois termos",
                              {t: contexto.termos.get(t, "") for t in termos})
        return pagina(request, "literatura.html", d=d, grafico_anos=grafico_anos, calor=calor, tri=leitura.contagem_triagem(),
                      rel=leitura.contagem_relevancia())

    @app.get("/literatura/catalogo.xlsx")
    def catalogo_xlsx(request: Request, modelo: str = ""):
        """Catalogo de referencias num modelo de planilha (o mesmo arquivo de `python main.py exportar-referencias`)."""
        if not set(autenticacao.EXIGENCIAS_EXPORTACOES["/literatura/catalogo.xlsx"]) <= _perms(request):  # protege triagem e registros de revisão
            return erro(request, 403, "Sem permissão", "Seu grupo não tem permissão para esta página ou ação.")
        if not leitura.existe():
            return sem_banco(request)
        escolhido = contexto.modelos_referencias.get(modelo)
        if escolhido is None:
            return erro(request, 404, "Modelo de planilha desconhecido",
                        "Use um dos modelos: " + ", ".join(sorted(contexto.modelos_referencias)) + ".")
        cat = catalogo_uc.montar_catalogo(leitura.linhas_catalogo())
        abas = exportacao.planilhas_referencias(cat, escolhido, contexto.categorias_referencias, contexto.eixos_tematicos)
        return Response(exportacao.planilha_xlsx(abas),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{escolhido.arquivo}"', "Cache-Control": "no-store"})

    def _referencias_da_busca(request):
        """(linhas, filtros, colunas) da tela Referencias com os filtros e as colunas escolhidas da URL; (None, None,
        None) quando um filtro ou uma coluna nao e um dos valores aceitos."""
        q = request.query_params
        conjunto, fonte, texto = q.get("conjunto", ""), q.get("fonte", ""), q.get("q", "").strip()
        recorte, idioma = q.get("recorte", ""), q.get("idioma", "")
        colunas = referencias_busca.colunas_escolhidas(q.getlist("colunas"))
        if conjunto not in ("",) + tuple(sorted(set(contexto.conjunto_da_consulta.values()))) or \
                fonte not in ("", referencias_busca.FONTE_WEB, referencias_busca.FONTE_SCHOLAR) or \
                recorte not in ("",) + tuple(contexto.recortes_vies) or \
                idioma not in ("",) + tuple(referencias_busca.IDIOMAS_DA_BUSCA) or colunas is None:
            return None, None, None
        todas = referencias_busca.referencias(leitura.linhas_referencias_web(),
                                              leitura.linhas_artigos_das_consultas(list(contexto.conjunto_da_consulta)),
                                              contexto.conjunto_da_consulta, leitura.triagens_vies(contexto.versao_triagem_vies),
                                              contexto.recortes_vies)
        filtros = {k: v for k, v in (("conjunto", conjunto), ("fonte", fonte), ("recorte", recorte), ("idioma", idioma),
                                     ("q", texto)) if v}
        return (referencias_busca.filtrar(todas, conjunto, fonte, texto, contexto.recortes_vies.get(recorte, ""),
                                          referencias_busca.IDIOMAS_DA_BUSCA.get(idioma, "")), filtros, colunas)

    def _base_referencias(filtros, colunas):
        """A parte da URL que repete os filtros e, quando nao sao todas, as colunas escolhidas."""
        pares = list(filtros.items())
        if colunas != list(referencias_busca.COLUNAS_TELA):
            pares += [("colunas", c) for c in colunas]
        return urlencode(pares)

    @app.get("/literatura/referencias", response_class=HTMLResponse)
    def referencias(request: Request):
        """As referencias da busca de vies algoritmico nas colunas do modelo de referencias (D103)."""
        if not leitura.existe():
            return sem_banco(request)
        linhas, filtros, colunas = _referencias_da_busca(request)
        n = _inteiro(request.query_params.get("p"), 1)
        if linhas is None or n is None:
            return erro(request, 404, "Filtro inválido", "Um dos filtros da página não é um valor aceito.")
        paginas = max((len(linhas) + 49) // 50, 1)
        return pagina(request, "referencias.html", linhas=linhas[(n - 1) * 50:n * 50], total=len(linhas), n=n, paginas=paginas,
                      filtros=filtros, base=_base_referencias(filtros, colunas), colunas=colunas,
                      todas_colunas=referencias_busca.COLUNAS_TELA, idiomas_da_busca=referencias_busca.IDIOMAS_DA_BUSCA,
                      textos_das_consultas=lambda cs: referencias_busca.textos_das_consultas(cs, contexto.consultas_literatura))

    @app.get("/literatura/referencias.xlsx")
    def referencias_xlsx(request: Request):
        """As mesmas linhas da tela (com os filtros dela): `modelo=erico` (o padrao) no modelo de referencias, com o
        esquema de exploracao; `modelo=colunas`, uma aba so com as colunas escolhidas na tela, na ordem dela."""
        if not leitura.existe():
            return sem_banco(request)
        linhas, _, colunas = _referencias_da_busca(request)
        modelo = request.query_params.get("modelo", "erico")
        if linhas is None or modelo not in ("erico", "colunas"):
            return erro(request, 404, "Filtro inválido", "Um dos filtros da página não é um valor aceito.")
        prefixo = "" if contexto.banco == "real" else f"{contexto.banco}_"      # C6
        nome = f"{prefixo}referencias_{datetime.now():%Y%m%d_%H%M}.xlsx"
        conteudo = (exportacao.planilha_referencias_colunas(linhas, colunas, contexto.consultas_literatura) if modelo == "colunas"
                    else exportacao.planilha_referencias_busca(linhas, contexto.eixos_exploracao))
        return Response(conteudo,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})

    @app.get("/literatura/referencias/web/{referencia_id}", response_class=HTMLResponse)
    def referencia_web(request: Request, referencia_id: IdDoBanco):
        """Uma referencia da busca de literatura na web: as consultas que a acharam, por extenso, e a triagem do modelo."""
        if not leitura.existe():
            return sem_banco(request)
        r = leitura.referencia_web(referencia_id)
        if r is None:
            return erro(request, 404, "Referência não encontrada", f"Não existe a referência W-{referencia_id}.")
        return pagina(request, "referencia_web.html", r=r, llm=leitura.veredito_referencia(referencia_id))

    @app.get("/literatura/artigos", response_class=HTMLResponse)
    def artigos(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros_artigos(request.query_params)
        n = _inteiro(request.query_params.get("p"), 1)
        if n is None:
            return erro(request, 404, "Página inválida", "O número da página não é válido.")
        res = leitura.artigos(filtros, n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        return pagina(request, "artigos.html", res=res, filtros=filtros, n=n, paginas=paginas, base=urlencode(filtros),
                      marcadores=relev.MARCADORES_BRASIL, marcadores_tema=relev.MARCADORES_TEMA, dominios_br=relev.DOMINIOS_BRASIL_SEM_BR)

    def _query_triagem(request):
        return urlencode({k: v for k, v in request.query_params.items() if k in FILTROS_ARTIGOS or k == "fila"})

    def _sugestoes_ctx(request, alvo_tipo, alvo_id, decidido, valor_atual, autor_decisao, ficha):
        """O que o cartao "Sugestoes" precisa (D78). Sem autenticacao, nada aparece."""
        vazio = {"sugestoes": [], "pode_sugerir": False, "pode_resolver": False, "estado_decisao": "", "opcoes_sugestao": [],
                 "base_sugestoes": ""}
        if not contexto.autenticacao:
            return vazio
        usuario = getattr(request.state, "usuario", None)
        permissao = "verificar_achados" if alvo_tipo == "achado" else "triar_artigos"
        pode_escrever = bool(usuario) and permissao in _perms(request) and not contexto.somente_leitura
        eu = chave_autor(usuario["nome"]) if usuario else None
        do_autor = bool(usuario) and eu == chave_autor(autor_decisao)
        if alvo_tipo == "achado":
            opcoes = [(k, rotulos.rotulo(rotulos.STATUS, k)) for k in list(contexto.status_definicoes) + sorted(contexto.status_permitidos - set(contexto.status_definicoes))]
            rotulo_de = lambda v: rotulos.rotulo(rotulos.STATUS, v)
        else:
            opcoes = [("incluir", "Incluir"), ("excluir", "Excluir")]
            rotulo_de = {"incluir": "Incluir", "excluir": "Excluir"}.get
        # Protege os registros de revisão: o motivo da sugestão só sai para quem pode sugerir ou tem permissão
        ve_motivo = pode_escrever or "ver_registros_revisao" in _perms(request)
        lista = []
        for sg in leitura.sugestoes_abertas(alvo_tipo, alvo_id):
            item = dict(sg)
            if not ve_motivo:
                item["motivo"] = None
            item["rotulo"] = rotulo_de(sg["valor"]) or sg["valor"]
            item["vencida"] = sg["estado_alvo"] != ficha
            item["minha"] = pode_escrever and eu == chave_autor(sg["autor"])
            lista.append(item)
        return {"sugestoes": lista,
                "pode_sugerir": pode_escrever and decidido and not do_autor,
                "pode_resolver": pode_escrever and (usuario["grupo"] == autenticacao.GRUPO_ADMIN or do_autor) if usuario else False,
                "estado_decisao": ficha or "",
                "opcoes_sugestao": [(v, r) for v, r in opcoes if v != valor_atual],
                "base_sugestoes": ("/achados/%d" % alvo_id) if alvo_tipo == "achado" else ("/literatura/artigos/%d" % alvo_id)}

    @app.get("/literatura/artigos/{artigo_id}", response_class=HTMLResponse)
    def artigo(request: Request, artigo_id: IdDoBanco, ok: int = 0):
        if not leitura.existe():
            return sem_banco(request)
        a = leitura.artigo(artigo_id)
        if a is None:
            return erro(request, 404, "Artigo não encontrado", f"Não existe o artigo nº {artigo_id} nas buscas do relatório.")
        em_fila = "fila" in request.query_params
        ids = leitura.ids_fila_triagem(_filtros_artigos(request.query_params)) if em_fila else []
        proximo = next((i for i in ids if i != artigo_id), None)
        fila_itens = None
        if em_fila:
            janela = _janela(ids, artigo_id)
            t = leitura.titulos_artigos(janela)
            fila_itens = [{"id": i, "titulo": (t.get(i) or "").strip() or f"Artigo nº {i}", "estado": "pendente"} for i in janela]
        sug_ctx = _sugestoes_ctx(request, "artigo", artigo_id, a["decisao"] in ("incluir", "excluir") and a["decisao_texto_completo"] == "pendente",
                                 a["decisao"], a["revisor"], leitura.estado_decisao("artigo", artigo_id))
        # Motivos de triagem só chegam ao modelo para quem tem a permissão ou pode decidir o item
        pode_ver_registros = "ver_registros_revisao" in _perms(request) or _pode_rota(request)("POST", f"/literatura/artigos/{artigo_id}/triar")
        if not pode_ver_registros:
            a_exibir = dict(a)
            a_exibir["motivo"] = None
            a_exibir["motivo_texto_completo"] = None
            if "historico" in a:
                a_exibir["historico"] = [{**h, "motivo": None, "motivo_texto_completo": None} for h in a["historico"]]
        else:
            a_exibir = a
        return pagina(request, "artigo.html", a=a_exibir, em_fila=em_fila, restantes=len(ids), proximo=proximo, tri=leitura.contagem_triagem(),
                      query=_query_triagem(request), ok=ok if 0 <= ok <= MAX_PAGINA * 1000 else 0, fila_itens=fila_itens,
                      **sug_ctx)

    @app.get("/literatura/triagem", response_class=HTMLResponse)
    def fila_triagem(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros_artigos(request.query_params)
        ids = leitura.ids_fila_triagem(filtros)
        if ids:
            return RedirectResponse("/literatura/artigos/%d?%s" % (ids[0], urlencode({**filtros, "fila": 1})), status_code=303)
        return pagina(request, "triagem_vazia.html", tri=leitura.contagem_triagem(), filtros=filtros)

    @app.post("/literatura/artigos/{artigo_id}/triar")
    def triar(request: Request, artigo_id: IdDoBanco, decisao: str = Form(""), revisor: str = Form(""), motivo: str = Form(""),
              base: str = Form(""), link: str = Form(""), etapa: str = Form("titulo_resumo"), versao: str = Form(None),
              csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        usuario = getattr(request.state, "usuario", None)
        if contexto.autenticacao and etapa == "texto_completo":
            grupo = usuario["grupo"] if usuario else autenticacao.GRUPO_VISITANTE
            permissoes = usuario["permissoes"] if usuario else contas.permissoes_do_grupo(autenticacao.GRUPO_VISITANTE)
            if not autenticacao.pode(grupo, permissoes, "triar_texto_completo"):
                return erro(request, 403, "Sem permissão", "Seu grupo não tem permissão para esta página ou ação.")
        if usuario:
            revisor = usuario["nome"]
        if leitura.artigo(artigo_id) is None:
            return erro(request, 404, "Artigo não encontrado", f"Não existe o artigo nº {artigo_id}.")
        if base and contexto.bases and base not in contexto.bases:
            return erro(request, 400, "Decisão não gravada", f"Base desconhecida: {base[:60]}")
        try:
            _escrever(lambda repo: revisao.decidir_triagem(repo, artigo_id, decisao, revisor, motivo, base, link, etapa, versao))
        except SystemExit as e:
            if _conflito(str(e)):
                msg = str(e) if _ver_nomes(request) else "Este artigo foi alterado por outra pessoa depois que você abriu a página. Recarregue e decida de novo."
                return erro(request, 409, "Artigo alterado", msg)
            return erro(request, 400, "Decisão não gravada", str(e))
        if "fila" in request.query_params:
            filtros = _filtros_artigos(request.query_params)
            ids = leitura.ids_fila_triagem(filtros)
            proximo = next((i for i in ids if i != artigo_id), None)
            destino = ("/literatura/artigos/%d?%s&ok=%d" % (proximo, urlencode({**filtros, "fila": 1}), artigo_id) if proximo
                       else "/literatura/triagem?" + urlencode(filtros))
        else:
            destino = "/literatura/artigos/%d?ok=%d" % (artigo_id, artigo_id)
        resposta = RedirectResponse(destino, status_code=303)
        if not usuario:
            resposta.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta

    @app.get("/literatura/prisma", response_class=HTMLResponse)
    def prisma(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        d = leitura.prisma()
        fases = {}
        for c in d["caixas"]:
            fases.setdefault(c["fase"], []).append(c)
        valores = {c["metrica"]: c["valor"] for c in d["caixas"]}
        informados = valores.get("buscas manuais: selecionados (contagem informada)")
        importados = valores.get("buscas manuais: artigos importados (por base)")
        aviso_manual = None
        if d["n_buscas_manuais"] and informados is not None and importados is not None and informados != importados:
            aviso_manual = (informados, importados)
        return pagina(request, "prisma.html", d=d, fases=fases, aviso_manual=aviso_manual)

    # ---------- achados ----------
    @app.get("/achados", response_class=HTMLResponse)
    def achados(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros(request.query_params)
        n = _inteiro(request.query_params.get("p"), 1)
        if n is None:
            return erro(request, 404, "Página inválida", "O número da página não é válido.")
        ent = entidades.obter()
        res = leitura.achados(_filtros_sql(filtros, ent), n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        base = urlencode(filtros)
        nomeadas = ent.entidades
        resumo = {"n_entidades": len(nomeadas), "n_achados": ent.n_achados, "topo": nomeadas[:MAX_ENTIDADES_NO_RESUMO]} if nomeadas else None
        nomes = list(dict.fromkeys(e.canonico for e in nomeadas))
        return pagina(request, "achados.html", res=res, filtros=filtros, paginas=paginas, base=base, n=n,
                      cidades=leitura.cidades(), ent=ent, entidades_resumo=resumo, nomes_canonicos=nomes,
                      entidade_atual=ent.entidades_do_nome(filtros.get("solucao", "")) if filtros.get("solucao") not in (None, "", "nomeada") else [])

    def _texto_enviado(a):
        """Texto que foi enviado ao classificador: a pagina extraida (cortada no que foi enviado) ou titulo + snippet."""
        aviso = None
        if a["origem_texto"] == "pagina" and a["texto_path"]:
            try:
                texto = bruto.ler(a["texto_path"]).decode("utf-8", "replace")
            except (OSError, ValueError):
                texto, aviso = "", ("O arquivo do texto extraído não foi encontrado em data/raw." if contexto.brutos_aqui else
                                    "O texto extraído fica no computador onde a coleta rodou: ele não é enviado para a nuvem.")
        else:
            texto = f"{a['titulo'] or ''}\n{a['snippet'] or ''}"
        if a["n_chars_enviados"]:
            texto = texto[:a["n_chars_enviados"]]
        return texto[:LIMITE_TEXTO], aviso

    def _contexto_evidencia(a, completo):
        texto, aviso = _texto_enviado(a)
        par = localizar_evidencia(a["evidencia"], texto)
        aprox = None
        if par is None:
            aprox = trecho_mais_parecido(a["evidencia"], texto)
            par = aprox[:2] if aprox else None
        out = {"aviso": aviso, "encontrada": aprox is None and par is not None, "similaridade": aprox[2] if aprox else None,
               "n_texto": len(texto), "recortado": False, "antes": texto, "trecho": "", "depois": ""}
        if par:
            ini, fim = par
            a0, b0 = (0, len(texto)) if completo else (max(ini - JANELA_CONTEXTO, 0), min(fim + JANELA_CONTEXTO, len(texto)))
            out.update(antes=texto[a0:ini], trecho=texto[ini:fim], depois=texto[fim:b0], recortado=(a0 > 0 or b0 < len(texto)),
                       prefixo=a0 > 0, sufixo=b0 < len(texto))
        elif len(texto) > 4000 and not completo:
            out.update(antes=texto[:4000], recortado=True, sufixo=True)
        return out

    def _query_fila(request):
        q = {k: v for k, v in request.query_params.items() if k in FILTROS or k == "fila"}
        return urlencode(q)

    def _proximo(ids, atual):
        if not ids:
            return None
        if atual in ids:
            i = ids.index(atual)
            return ids[(i + 1) % len(ids)] if len(ids) > 1 else None
        return ids[0]

    @app.get("/achados/casos.xlsx")
    def casos_xlsx(request: Request):
        """Os achados no modelo de planilha "Casos Estaduais" (D112), o mesmo arquivo de `python main.py exportar-casos`."""
        if not set(autenticacao.EXIGENCIAS_EXPORTACOES["/achados/casos.xlsx"]) <= _perms(request):  # protege verificação e registros de revisão
            return erro(request, 403, "Sem permissão", "Seu grupo não tem permissão para esta página ou ação.")
        if not leitura.existe():
            return sem_banco(request)
        conteudo = exportacao.planilha_casos_estaduais(leitura.linhas_casos_estaduais(), contexto.ufs, rotulos.TECNOLOGIAS,
                                                       rotulos.STATUS)
        prefixo = "" if contexto.banco == "real" else f"{contexto.banco}_"      # C6
        nome = f"{prefixo}casos_estaduais_{datetime.now():%Y%m%d_%H%M}.xlsx"
        return Response(conteudo, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})

    @app.get("/achados/{achado_id}", response_class=HTMLResponse)
    def achado(request: Request, achado_id: IdDoBanco, completo: int = 0, ok: int = 0):
        ok = ok if 0 <= ok <= MAX_PAGINA * 1000 else 0
        if not leitura.existe():
            return sem_banco(request)
        a = leitura.achado(achado_id)
        if a is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        em_fila = "fila" in request.query_params
        ent = entidades.obter()
        ids = leitura.ids_fila_revisao(_filtros_sql(_filtros(request.query_params), ent)) if em_fila else []
        rev = leitura.contagem_revisao()
        proximo = _proximo(ids, achado_id)
        fila_itens = None
        if em_fila:
            janela = _janela(ids, achado_id)
            r = leitura.resumo_achados(janela)
            fila_itens = [{
                "id": i,
                "titulo": (rotulos.rotulo(rotulos.TECNOLOGIAS, r[i]["tecnologia"]) + " · " + (r[i]["cidade"] or r[i]["uf"])) if i in r else f"Achado nº {i}",
                "estado": "pendente",
            } for i in janela]
        historico = leitura.historico_achado(achado_id)
        pode_desfazer = _pode_desfazer(request, achado_id, historico)
        pode_desfazer_ok = False
        if ok and ok > 0:
            pode_desfazer_ok = pode_desfazer if ok == achado_id else _pode_desfazer(request, ok, leitura.historico_achado(ok))
        sug_ctx = _sugestoes_ctx(request, "achado", achado_id, bool(a["verificado"]), a["status_final"], a["verificado_por"],
                                 ficha_da_decisao(tuple(a[c] for c in CAMPOS_ACHADO)))
        # Observações só chegam ao modelo para quem tem a permissão ou pode decidir o item
        pode_ver_registros = "ver_registros_revisao" in _perms(request) or _pode_rota(request)("POST", f"/achados/{achado_id}/verificar")
        if not pode_ver_registros:
            a_exibir = dict(a)
            a_exibir["observacao"] = None
            hist_exibir = [{**h, "observacao": None} for h in historico]
        else:
            a_exibir = a
            hist_exibir = historico
        return pagina(request, "achado.html", a=a_exibir, ev=_contexto_evidencia(a, bool(completo)), completo=bool(completo), ent=ent,
                      historico=hist_exibir, em_fila=em_fila, rev=rev, proximo=proximo,
                      query=_query_fila(request), ok=ok, restantes=len(ids),
                      pode_desfazer=pode_desfazer, pode_desfazer_ok=pode_desfazer_ok, fila_itens=fila_itens,
                      **sug_ctx,
                      status_opcoes=[(k, contexto.status_definicoes[k]) for k in contexto.status_definicoes])

    @app.get("/revisao/achados", response_class=HTMLResponse)
    def fila(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros(request.query_params)
        ids = leitura.ids_fila_revisao(_filtros_sql(filtros, entidades.obter()))
        if ids:
            return RedirectResponse("/achados/%d?%s" % (ids[0], urlencode({**filtros, "fila": 1})), status_code=303)
        return pagina(request, "fila_vazia.html", rev=leitura.contagem_revisao(), filtros=filtros)

    def _voltar(request, achado_id, ok=None):
        filtros = _filtros(request.query_params)
        ids = leitura.ids_fila_revisao(_filtros_sql(filtros, entidades.obter()))
        q = urlencode({**filtros, "fila": 1})
        if ids:
            return "/achados/%d?%s&ok=%d" % (ids[0], q, ok or 0)
        return "/revisao/achados?" + urlencode(filtros)

    def _antes_de_escrever():
        """Copia de seguranca uma vez por sessao do painel, antes da primeira gravacao."""
        if not contexto.backup_feito:
            repo = repositorio_fabrica()
            try:
                repo.copia_de_seguranca(contexto.pasta_backup)
            finally:
                repo.fechar()
            contexto.backup_feito = True

    def _escrever(acao):
        _antes_de_escrever()
        repo = repositorio_fabrica()
        try:
            acao(repo)
        finally:
            repo.fechar()

    def _conflito(texto):
        return "mudou depois" in texto or "alterado depois" in texto

    @app.post("/achados/{achado_id}/verificar")
    def verificar(request: Request, achado_id: IdDoBanco, status_final: str = Form(""), revisor: str = Form(""),
                  observacao: str = Form(""), versao: str = Form(None), csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        usuario = getattr(request.state, "usuario", None)
        if usuario:
            revisor = usuario["nome"]
        if leitura.achado(achado_id) is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        try:
            _escrever(lambda repo: revisao.verificar_achado(repo, achado_id, status_final, revisor, observacao,
                                                            contexto.status_permitidos, versao))
        except SystemExit as e:
            if _conflito(str(e)):
                msg = str(e) if _ver_nomes(request) else "Este achado foi alterado por outra pessoa depois que você abriu a página. Recarregue e decida de novo."
                return erro(request, 409, "Achado alterado", msg)
            return erro(request, 400, "Decisão não gravada", str(e))
        destino = (_voltar(request, achado_id, achado_id) if "fila" in request.query_params
                   else "/achados/%d?ok=%d" % (achado_id, achado_id))
        resposta = RedirectResponse(destino, status_code=303)
        if not usuario:
            resposta.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta

    def _destino_item(request, alvo_tipo, base):
        q = _query_fila(request) if alvo_tipo == "achado" else _query_triagem(request)
        return base + ("?" + q if q else "")

    MSG_CONFLITO_SEM_NOMES = "A decisão deste item mudou depois que a página foi aberta. Recarregue a página."

    def _sugestoes_desligadas(request):
        return erro(request, 404, "Sugestões indisponíveis", "As sugestões só existem quando o painel usa login.")

    def _sugerir(request, alvo_tipo, alvo_id, valor, motivo, estado, csrf):
        if not contexto.autenticacao:
            return _sugestoes_desligadas(request)
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        base = ("/achados/%d" % alvo_id) if alvo_tipo == "achado" else ("/literatura/artigos/%d" % alvo_id)
        if (leitura.achado(alvo_id) if alvo_tipo == "achado" else leitura.artigo(alvo_id)) is None:
            return erro(request, 404, "Item não encontrado", f"Não existe o {'achado' if alvo_tipo == 'achado' else 'artigo'} nº {alvo_id}.")
        usuario = getattr(request.state, "usuario", None)
        motivo = (motivo or "").replace("\r\n", "\n")              # o navegador manda CRLF; o limite conta como o campo mostrou
        try:
            _escrever(lambda repo: sugestoes_uc.criar(repo, alvo_tipo, alvo_id, valor, motivo, usuario["nome"] if usuario else "", estado,
                                                     contexto.status_permitidos))
        except SystemExit as e:
            if _conflito(str(e)):
                return erro(request, 409, "Decisão alterada", str(e) if _ver_nomes(request) else MSG_CONFLITO_SEM_NOMES)
            return erro(request, 400, "Sugestão não gravada", str(e))
        return RedirectResponse(_destino_item(request, alvo_tipo, base), status_code=303)

    def _resolver(request, alvo_tipo, alvo_id, sugestao_id, acao, csrf):
        if not contexto.autenticacao:
            return _sugestoes_desligadas(request)
        if acao not in ("aceitar", "descartar"):
            return erro(request, 404, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido.")
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        base = ("/achados/%d" % alvo_id) if alvo_tipo == "achado" else ("/literatura/artigos/%d" % alvo_id)
        a = leitura.achado(alvo_id) if alvo_tipo == "achado" else leitura.artigo(alvo_id)
        if a is None:
            return erro(request, 404, "Item não encontrado", f"Não existe o {'achado' if alvo_tipo == 'achado' else 'artigo'} nº {alvo_id}.")
        sg = leitura.sugestao(sugestao_id)
        if sg is None or (sg["alvo_tipo"], sg["alvo_id"]) != (alvo_tipo, alvo_id):
            return erro(request, 404, "Sugestão não encontrada", f"Não existe a sugestão nº {sugestao_id} neste item.")
        usuario = getattr(request.state, "usuario", None)
        autor_decisao = a["verificado_por"] if alvo_tipo == "achado" else a["revisor"]
        eu = chave_autor(usuario["nome"]) if usuario else None
        pode = bool(usuario) and (usuario["grupo"] == autenticacao.GRUPO_ADMIN or eu == chave_autor(autor_decisao)
                                  or (acao == "descartar" and eu == chave_autor(sg["autor"])))
        if not pode:
            return erro(request, 403, "Sem permissão", "Só quem tomou a decisão ou um administrador resolve sugestões.")
        try:
            if acao == "aceitar":
                _escrever(lambda repo: sugestoes_uc.aceitar(repo, sugestao_id, usuario["nome"], contexto.status_permitidos))
            else:
                _escrever(lambda repo: sugestoes_uc.descartar(repo, sugestao_id, usuario["nome"]))
        except SystemExit as e:
            if "já foi resolvida" in str(e):
                return erro(request, 409, "Sugestão já resolvida", str(e))
            if "já mudou" in str(e) or _conflito(str(e)):
                return erro(request, 409, "Sugestão vencida", str(e) if _ver_nomes(request) else MSG_CONFLITO_SEM_NOMES)
            return erro(request, 400, "Sugestão não resolvida", str(e))
        return RedirectResponse(_destino_item(request, alvo_tipo, base), status_code=303)

    @app.post("/achados/{achado_id}/sugerir")
    def sugerir_achado(request: Request, achado_id: IdDoBanco, valor: str = Form(""), motivo: str = Form(""), estado: str = Form(""),
                       csrf: str = Form("")):
        return _sugerir(request, "achado", achado_id, valor, motivo, estado, csrf)

    @app.post("/literatura/artigos/{artigo_id}/sugerir")
    def sugerir_artigo(request: Request, artigo_id: IdDoBanco, valor: str = Form(""), motivo: str = Form(""), estado: str = Form(""),
                       csrf: str = Form("")):
        return _sugerir(request, "artigo", artigo_id, valor, motivo, estado, csrf)

    @app.post("/achados/{achado_id}/sugestoes/{sugestao_id}/{acao}")
    def resolver_achado(request: Request, achado_id: IdDoBanco, sugestao_id: IdDoBanco, acao: str, csrf: str = Form("")):
        return _resolver(request, "achado", achado_id, sugestao_id, acao, csrf)

    @app.post("/literatura/artigos/{artigo_id}/sugestoes/{sugestao_id}/{acao}")
    def resolver_artigo(request: Request, artigo_id: IdDoBanco, sugestao_id: IdDoBanco, acao: str, csrf: str = Form("")):
        return _resolver(request, "artigo", artigo_id, sugestao_id, acao, csrf)

    @app.post("/achados/{achado_id}/desfazer")
    def desfazer(request: Request, achado_id: IdDoBanco, csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        usuario = getattr(request.state, "usuario", None)
        if contexto.autenticacao:
            autor = next((h["verificado_por"] for h in leitura.historico_achado(achado_id) if not h["desfeita"]), None)
            if not (usuario and autenticacao.pode_desfazer_decisao(usuario.get("grupo"), usuario.get("nome"), autor)):
                return erro(request, 403, "Sem permissão", "Só quem tomou a decisão ou um administrador pode desfazê-la. Registre uma sugestão.")
        try:
            _escrever(lambda repo: revisao.desfazer_decisao(repo, achado_id))
        except SystemExit as e:
            if _conflito(str(e)):
                msg = str(e) if _ver_nomes(request) else "Este achado foi alterado por outra pessoa depois que você abriu a página. Recarregue e decida de novo."
                return erro(request, 409, "Não foi possível desfazer", msg)
            return erro(request, 400, "Não foi possível desfazer", str(e))
        return RedirectResponse("/achados/%d?%s" % (achado_id, _query_fila(request)), status_code=303)

    @app.post("/achados/{achado_id}/revogar")
    def revogar(request: Request, achado_id: IdDoBanco, revisor: str = Form(""), motivo: str = Form(""),
                versao: str = Form(None), csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        usuario = getattr(request.state, "usuario", None)
        if usuario:
            revisor = usuario["nome"]
        if leitura.achado(achado_id) is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        try:
            _escrever(lambda repo: revisao.revogar_verificacao(repo, achado_id, revisor, motivo, versao))
        except SystemExit as e:
            if _conflito(str(e)):
                msg = str(e) if _ver_nomes(request) else "Este achado foi alterado por outra pessoa depois que você abriu a página. Recarregue e decida de novo."
                return erro(request, 409, "Verificação não revogada", msg)
            return erro(request, 400, "Verificação não revogada", str(e))
        resposta = RedirectResponse("/achados/%d?%s" % (achado_id, _query_fila(request)), status_code=303)
        if not usuario:
            resposta.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta

    from painel import rotas_extras
    rotas_extras.registrar_todas(SimpleNamespace(app=app, leitura=leitura, bruto=bruto, contexto=contexto, modelos=modelos, entidades=entidades,
                                                 pagina=pagina, erro=erro, sem_banco=sem_banco, checar_escrita=checar_escrita, contas=contas,
                                                 contas_ocupadas=contas_ocupadas, novo_repositorio=repositorio_fabrica, escrever=_escrever,
                                                 pode_seguir=_pode_seguir, perms=_perms))
    return app
