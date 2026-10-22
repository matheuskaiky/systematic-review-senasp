"""Regras de domínio para autenticação, controle de acesso e segurança de sessões."""
from datetime import datetime
from functools import lru_cache
import hashlib
import hmac
import re
import secrets


class ContasOcupadas(Exception):
    """O banco de contas está ocupado por outra gravação."""


def ler_instante(texto: str | None) -> datetime | None:
    """Converte string ISO em datetime com fuso horário, ou None se inválido ou ingênuo."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    try:
        dt = datetime.fromisoformat(texto)
        return dt if dt.tzinfo is not None else None
    except Exception:
        return None


PERMISSOES = {
    "ver_painel": "Ver as páginas de leitura (visão geral, estados, achados, literatura, análises, soluções, metodologia, triagem de escopo)",
    "ver_nomes_revisores": "Ver os nomes de quem decidiu (históricos, verificações e concordância)",
    "ver_chamadas": "Ver execuções, chamadas e o conteúdo bruto das APIs",
    "verificar_achados": "Verificar achados e desfazer as próprias decisões",
    "revogar_verificacao": "Revogar verificações de achados",
    "triar_artigos": "Triar artigos por título e resumo",
    "triar_texto_completo": "Triar artigos por texto completo",
    "ver_estatisticas_usuarios": "Ver as estatísticas por usuário",
    "enviar_coletas": "Gerar o próprio token e enviar coletas do computador local para a nuvem",
}

PERMISSOES_ESCRITA = frozenset({"verificar_achados", "revogar_verificacao", "triar_artigos", "triar_texto_completo"})
PERMISSOES_PROIBIDAS_VISITANTE = PERMISSOES_ESCRITA | {"ver_estatisticas_usuarios", "enviar_coletas"}

ACOES_AUDITORIA = (
    "criar_usuario",
    "editar_usuario",
    "redefinir_senha",
    "desativar_usuario",
    "reativar_usuario",
    "salvar_permissoes",
    "criar_grupo",
    "renomear_grupo",
    "gerar_token",
    "revogar_token",
)

GRUPO_ADMIN = "Administrador"
GRUPO_VISITANTE = "Visitante"
SO_ADMIN = "_so_admin"
LOGADO = "_logado"                  # qualquer usuario com sessao (nunca o visitante anonimo)

PREFIXO_TOKEN = "srsp_"
CARACTERES_DO_INICIO = 12           # o que a tela mostra para reconhecer o token (prefixo + 7 caracteres)

GRUPOS_PADRAO = {
    "Administrador": set(PERMISSOES),
    "Visitante": {"ver_painel"},
    "Revisor": {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "verificar_achados", "triar_artigos", "triar_texto_completo"},
    "Leitor": {"ver_painel", "ver_nomes_revisores"},
}

SENHA_MIN = 10
SENHA_MAX = 200
NOME_MAX = 80
PROXIMO_MAX = 2000
FALHAS_ATE_BLOQUEIO = 5
MINUTOS_DE_BLOQUEIO = 5
HORAS_DE_SESSAO = 12
DIAS_MAXIMOS_DE_SESSAO = 7          # validade absoluta: uma sessao em uso continuo tambem expira


def hash_senha(senha: str, sal: bytes | None = None) -> str:
    """Gera hash scrypt da senha com parâmetros fixos e sal de 16 bytes."""
    sal_bytes = sal if sal else secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode("utf-8"), salt=sal_bytes, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${sal_bytes.hex()}${h.hex()}"


def gerar_token_api() -> str:
    """Token de envio: prefixo fixo + 32 bytes aleatorios em base64 de URL (43 caracteres), 48 caracteres no total."""
    return PREFIXO_TOKEN + secrets.token_urlsafe(32)


RE_TOKEN = re.compile(r"srsp_[A-Za-z0-9_-]{43}")


def hash_token(token: str) -> str:
    """SHA-256 do token (o banco guarda so isto, como nas sessoes; o token tem 256 bits aleatorios)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def inicio_do_token(token: str) -> str:
    """O comeco do token que as telas mostram para reconhece-lo, sem revelar o resto."""
    return token[:CARACTERES_DO_INICIO]


@lru_cache(maxsize=1)
def hash_ficticio() -> str:
    """Hash fixo usado quando o login nao existe ou esta inativo: conferir contra ele gasta o mesmo tempo de uma senha
    errada de verdade, para o tempo de resposta nao revelar quais logins existem."""
    return hash_senha("tempo-de-resposta-constante", sal=bytes(16))


def conferir_senha(senha: str, guardado: str | None) -> bool:
    """Confere senha contra hash scrypt armazenado sem lançar exceções."""
    if not isinstance(guardado, str) or not isinstance(senha, str):
        return False
    partes = guardado.split("$")
    if len(partes) != 6:
        return False
    if partes[:4] != ["scrypt", "16384", "8", "1"]:
        return False
    if not re.fullmatch(r"[0-9a-f]{32}", partes[4]):
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", partes[5]):
        return False
    try:
        sal = bytes.fromhex(partes[4])
        h = hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), partes[5])
    except Exception:
        return False


def validar_senha(senha: str) -> list[str]:
    """Valida tamanho da senha em pontos de código sem remover espaços."""
    if not isinstance(senha, str):
        return ["A senha precisa ter pelo menos 10 caracteres."]
    if len(senha) < SENHA_MIN:
        return ["A senha precisa ter pelo menos 10 caracteres."]
    if len(senha) > SENHA_MAX:
        return ["A senha pode ter no máximo 200 caracteres."]
    return []


def validar_login(login: str) -> list[str]:
    """Valida formato e tamanho do identificador de login."""
    if not isinstance(login, str) or not re.fullmatch(r"[a-z0-9._-]{3,40}", login):
        return ["O login deve ter de 3 a 40 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado."]
    return []


def validar_nome(nome: str) -> list[str]:
    """Valida tamanho e preenchimento do nome após remover espaços externos."""
    if not isinstance(nome, str):
        return ["O nome não pode ficar vazio."]
    limpo = nome.strip()
    if not limpo:
        return ["O nome não pode ficar vazio."]
    if len(limpo) > NOME_MAX:
        return ["O nome pode ter no máximo 80 caracteres."]
    return []


def validar_nome_grupo(nome: str) -> list[str]:
    """Valida preenchimento e tamanho do nome do grupo após remover espaços externos."""
    if not isinstance(nome, str):
        return ["O nome do grupo não pode ficar vazio."]
    limpo = nome.strip()
    if not limpo:
        return ["O nome do grupo não pode ficar vazio."]
    if len(limpo) > 40:
        return ["O nome do grupo pode ter no máximo 40 caracteres."]
    return []


def permissao_exigida(metodo: str, caminho: str) -> str | None:
    """Determina a permissão necessária para acessar determinado método e rota."""
    if caminho.startswith("/static/"):
        return None
    if caminho in ("/entrar", "/sair"):
        return None
    if caminho == "/admin" or caminho.startswith("/admin/"):
        return SO_ADMIN
    if caminho == "/conta" and metodo == "GET":
        return LOGADO
    if caminho == "/conta/token" and metodo == "POST":
        return "enviar_coletas"
    if caminho == "/conta/token/revogar" and metodo == "POST":
        return LOGADO                                   # quem perdeu a permissao ainda pode revogar o proprio token
    if metodo == "GET" and (caminho.startswith("/execucoes") or caminho.startswith("/chamadas")):
        return "ver_chamadas"
    if metodo == "GET" and caminho == "/estatisticas-usuarios":
        return "ver_estatisticas_usuarios"
    if metodo == "GET" and caminho == "/literatura/catalogo.xlsx":
        return "triar_artigos"                          # o catalogo leva as notas de leitura: visitante nao baixa
    if metodo == "GET" and caminho == "/achados/casos.xlsx":
        return "verificar_achados"                      # a planilha leva as observacoes da verificacao: visitante nao baixa
    if metodo == "GET":
        return "ver_painel"
    if metodo == "POST" and caminho.endswith(("/sugerir", "/aceitar", "/descartar")):
        if caminho.startswith("/achados/"):
            return "verificar_achados"
        if caminho.startswith("/literatura/artigos/"):
            return "triar_artigos"
    if metodo == "POST" and (caminho.endswith("/verificar") or caminho.endswith("/desfazer")):
        return "verificar_achados"
    if metodo == "POST" and caminho.endswith("/revogar"):
        return "revogar_verificacao"
    if metodo == "POST" and caminho.endswith("/triar"):
        return "triar_artigos"
    return SO_ADMIN


def pode(grupo: str, permissoes: set[str] | list[str], exigida: str | None) -> bool:
    """Verifica se um grupo com dadas permissões tem acesso à permissão exigida."""
    if exigida is None:
        return True
    if grupo == GRUPO_ADMIN:
        return True
    if exigida == LOGADO:
        return grupo != GRUPO_VISITANTE
    if exigida == SO_ADMIN:
        return False
    if grupo == GRUPO_VISITANTE and exigida in PERMISSOES_PROIBIDAS_VISITANTE:
        return False
    return exigida in (permissoes or ())


def proximo_seguro(proximo: str) -> str:
    """Valida caminho relativo seguro para redirecionamento pós-login."""
    if not isinstance(proximo, str):
        return "/"
    if re.fullmatch(r"/(?![/\\])[^\\\x00-\x1f\x7f]{0,1999}", proximo) and not proximo.startswith("/entrar"):
        return proximo
    return "/"


def resumir_atividade(linhas: list[dict], hoje: str) -> tuple[list[dict], list[dict]]:
    """Agrega eventos de decisão por revisor e filtra a janela dos últimos 30 dias."""
    from datetime import date, timedelta
    d_hoje = date.fromisoformat(hoje)
    d_inicio = (d_hoje - timedelta(days=29)).isoformat()

    totais_map = {}
    janela = []
    for linha in linhas:
        rev = linha.get("revisor")
        dia = linha.get("dia")
        achados = int(linha.get("achados") or 0)
        artigos = int(linha.get("artigos") or 0)
        if rev not in totais_map:
            totais_map[rev] = {
                "revisor": rev,
                "achados": 0,
                "artigos": 0,
                "hoje": 0,
                "ultimo_dia": None,
            }
        item = totais_map[rev]
        item["achados"] += achados
        item["artigos"] += artigos
        if dia:
            if dia == hoje:
                item["hoje"] += achados + artigos
            if item["ultimo_dia"] is None or dia > item["ultimo_dia"]:
                item["ultimo_dia"] = dia
            if d_inicio <= dia <= hoje:
                janela.append(dict(linha))

    totais = list(totais_map.values())
    totais.sort(key=lambda t: (-(t["achados"] + t["artigos"]), t["revisor"]))
    return totais, janela
