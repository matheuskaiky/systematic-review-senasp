"""API do painel na nuvem (D98, D99, D100): recebe o pacote de uma execucao coletada no computador local e o junta no
banco. So existe no painel da nuvem (PostgreSQL; `Contexto.aceita_envios`). Autentica pelo token de envio do usuario
(cabecalho Authorization: Bearer), nunca pela sessao; a conta precisa estar ativa e o grupo ter a permissao
enviar_coletas. Um envio por vez neste processo: outro, enquanto isso, recebe "ocupado" na hora, sem pegar conexao do
banco (o painel continua com as dele). Respostas sempre em JSON, sem cache."""
import json
import logging
import threading
import zlib
from datetime import datetime, timezone

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from dominio import autenticacao
from dominio.pacote_coleta import ErroPacote

MAX_CORPO = 16 * 1024 * 1024              # bytes recebidos (a maior execucao real tem 2,3 MB compactada)
MAX_DESCOMPACTADO = 64 * 1024 * 1024      # bytes depois do gzip (a maior tem 12,7 MB em JSON); cabe na memoria da instancia

SEM_TOKEN = "Token ausente: mande o cabeçalho Authorization: Bearer <token>."
TOKEN_INVALIDO = "Token inválido ou revogado: gere outro na página Minha conta."
SEM_PERMISSAO = "Sua conta não tem a permissão de enviar coletas."
CONTAS_OCUPADAS = "O banco de contas está ocupado. Tente de novo em alguns segundos."
GRANDE_DEMAIS = "Pacote grande demais: o limite é 16 MB compactado e 64 MB descompactado."
NAO_JSON = "O corpo precisa ser JSON em UTF-8 (compactado com gzip ou não)."
OCUPADO = "O banco está ocupado (outro envio ou uma gravação do painel). Tente de novo em alguns minutos; reenviar é seguro."
FALHA = "A nuvem não conseguiu gravar o envio; nada foi gravado. Tente de novo; se repetir, avise o administrador."
METODO = "Use POST para enviar uma coleta."

_UM_ENVIO_POR_VEZ = threading.Lock()


def _resposta(status, conteudo):
    return JSONResponse(conteudo, status_code=status, headers={"Cache-Control": "no-store"})


def _erro(status, texto):
    return _resposta(status, {"erro": texto})


class _Grande(Exception):
    pass


async def _receber(request):
    """O corpo recebido, ate MAX_CORPO (para de ler ao passar). _Grande se passar."""
    partes, tamanho = [], 0
    async for pedaco in request.stream():
        tamanho += len(pedaco)
        if tamanho > MAX_CORPO:
            raise _Grande()
        partes.append(pedaco)
    return b"".join(partes)


def _sem_chave_repetida(pares):
    """object_pairs_hook do json: uma chave repetida no mesmo objeto e erro (o json do Python ficaria com a ultima)."""
    objeto = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("chave repetida no JSON")
        objeto[chave] = valor
    return objeto


def _constante_fora_do_json(nome):
    """parse_constant do json: NaN, Infinity e -Infinity nao sao JSON (o json do Python os aceitaria)."""
    raise ValueError("constante fora do JSON")


def _decodificar(corpo, gzipado):
    """bytes -> objeto JSON (fora do laco de eventos: chamado na threadpool). gzip ate MAX_DESCOMPACTADO, sem lixo depois.
    _Grande se passar do limite; ValueError se nao for gzip valido nem JSON em UTF-8, com chave repetida num objeto ou
    com NaN/Infinity ou com um surrogate solto ("\\ud800") em texto ou chave."""
    if gzipado:
        d = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        try:
            corpo = d.decompress(corpo, MAX_DESCOMPACTADO + 1)
        except zlib.error:
            raise ValueError("gzip inválido") from None
        if len(corpo) > MAX_DESCOMPACTADO or d.unconsumed_tail:
            raise _Grande()
        if not d.eof or d.unused_data:
            raise ValueError("gzip incompleto ou com dados depois do fim")
    try:
        objeto = json.loads(corpo.decode("utf-8"), object_pairs_hook=_sem_chave_repetida, parse_constant=_constante_fora_do_json)
        # "\ud800" e JSON valido, mas nao e texto Unicode: o banco recusaria so na gravacao, e reenviar nao resolveria
        json.dumps(objeto, ensure_ascii=False).encode("utf-8")
        return objeto
    except (UnicodeDecodeError, UnicodeEncodeError, RecursionError) as e:
        raise ValueError(str(e)) from None


def registrar(c) -> None:
    if not (c.contexto.autenticacao and c.contexto.aceita_envios):
        return

    @c.app.api_route("/api/coletas", methods=["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def metodo_errado(request: Request):
        # outro metodo: 405 em JSON, sem cache, como as demais respostas da API (nao a pagina de erro do painel)
        return JSONResponse({"erro": METODO}, status_code=405, headers={"Cache-Control": "no-store", "Allow": "POST"})

    @c.app.post("/api/coletas")
    async def receber_coleta(request: Request):
        cabecalho = request.headers.get("authorization", "")
        if not cabecalho.startswith("Bearer "):
            return _erro(401, SEM_TOKEN)
        token = cabecalho[len("Bearer "):].strip()
        if not autenticacao.RE_TOKEN.fullmatch(token):
            return _erro(401, TOKEN_INVALIDO)
        hash_token = autenticacao.hash_token(token)
        try:
            dono = await run_in_threadpool(c.contas.usuario_do_token, hash_token)
        except autenticacao.ContasOcupadas:
            return _erro(503, CONTAS_OCUPADAS)
        if dono is None:
            return _erro(401, TOKEN_INVALIDO)
        if not autenticacao.pode(dono["grupo"], dono["permissoes"], "enviar_coletas"):
            return _erro(403, SEM_PERMISSAO)
        if not _UM_ENVIO_POR_VEZ.acquire(blocking=False):
            return _erro(503, OCUPADO)
        try:
            try:
                corpo = await _receber(request)
                gzipado = request.headers.get("content-encoding", "").strip().lower() == "gzip"
                pacote = await run_in_threadpool(_decodificar, corpo, gzipado)
            except _Grande:
                return _erro(413, GRANDE_DEMAIS)
            except (ValueError, ClientDisconnect):
                return _erro(400, NAO_JSON)
            agora = datetime.now(timezone.utc).isoformat()

            def juntar():
                repo = c.novo_repositorio()
                try:
                    return repo.juntar_pacote(pacote, dono["usuario_id"], agora)
                finally:
                    repo.fechar()
            try:
                relatorio = await run_in_threadpool(juntar)
            except ErroPacote as e:
                return _erro(400, str(e))
            except Exception as e:              # trava ocupada ou banco fora do ar: nada foi gravado (tudo ou nada)
                if "database is locked" in str(e):
                    return _erro(503, OCUPADO)
                # so o numero da execucao e o tipo do erro: o texto de um erro do banco pode trazer dados do pacote
                logging.getLogger(__name__).error("falha ao juntar o envio da execução %s: %s",
                                                  pacote.get("run_id") if isinstance(pacote, dict) else None, type(e).__name__)
                return _erro(503, FALHA)
        finally:
            _UM_ENVIO_POR_VEZ.release()
        try:
            await run_in_threadpool(c.contas.registrar_uso_do_token, hash_token, agora)
        except autenticacao.ContasOcupadas:
            pass                                # o envio ja foi gravado; o ultimo uso fica para o proximo
        return _resposta(200, {"run_id": pacote["run_id"], "tabelas": relatorio})
