"""Regras de domínio para autenticação, controle de acesso e segurança de sessões."""
from datetime import datetime
from functools import lru_cache
import hashlib
import hmac
import json
import re
import secrets
import sys
import unicodedata


class ContasOcupadas(Exception):
    """O banco de contas está ocupado por outra gravação."""


class PermissoesAlteradas(Exception):
    """As permissões de algum grupo mudaram desde que a página foi aberta."""


class AlteracaoRecusada(Exception):
    """Uma alteração de permissões foi recusada por inconsistência ou regra de negócio."""

    def __init__(self, erros: list[str]):
        super().__init__(erros)
        self.erros = list(erros)


def versao_permissoes(estado: dict[int, set[str] | list[str] | tuple[str, ...]]) -> str:
    """Calcula o hash SHA-256 do estado das permissões dos grupos."""
    linhas = []
    for gid in sorted(estado):
        linhas.append(f"{gid}")
        linhas += [f"{gid}\t{p}" for p in sorted(set(estado[gid]))]
    return hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()


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
    "ver_registros_revisao": "Ver observações e motivos das decisões",
    "ver_custos": "Ver custos das execuções",
}

PERMISSOES_ESCRITA = frozenset({"verificar_achados", "revogar_verificacao", "triar_artigos", "triar_texto_completo"})
PERMISSOES_PROIBIDAS_VISITANTE = PERMISSOES_ESCRITA | {"ver_estatisticas_usuarios", "enviar_coletas", "ver_custos", "ver_registros_revisao"}

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
    "Revisor": {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "verificar_achados", "triar_artigos", "triar_texto_completo", "ver_registros_revisao", "ver_custos"},
    "Leitor": {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"},
}

MODULOS_PERMISSAO = {
    "consulta": "Consulta da pesquisa",
    "revisao": "Revisão e validação",
    "acompanhamento": "Acompanhamento",
    "tecnico": "Dados técnicos",
}

SENSIBILIDADES = (None, "escrita", "supervisao", "dados_pessoais", "tecnica_restrita", "escrita_externa", "dados_revisao", "financeira")

CATALOGO_PERMISSOES = {
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

ROTULOS_SENSIBILIDADE = {
    "supervisao": "supervisão",
    "dados_pessoais": "dados pessoais",
    "tecnica_restrita": "técnica restrita",
    "escrita_externa": "escrita externa",
    "dados_revisao": "dados de revisão",
    "financeira": "financeira",
}

EXIGENCIAS_EXPORTACOES = {
    "/execucoes/resultado.xlsx": ("ver_chamadas", "ver_nomes_revisores", "ver_custos", "ver_registros_revisao"),
    "/literatura/catalogo.xlsx": ("triar_artigos", "ver_registros_revisao"),
    "/achados/casos.xlsx": ("verificar_achados", "ver_registros_revisao"),
}

PERMISSOES_NOVAS = ("ver_registros_revisao", "ver_custos")
GRUPOS_EQUIVALENTES = ("Leitor", "Revisor")

REGRAS_ROTAS = (
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
    ("GET", "/conta", LOGADO),
    ("GET", "/admin", SO_ADMIN),
    ("GET", "/admin/usuarios", SO_ADMIN),
    ("GET", "/admin/usuarios/{usuario_id}", SO_ADMIN),
    ("GET", "/admin/grupos", SO_ADMIN),
    ("GET", "/admin/grupos/{grupo_id:digitos}", SO_ADMIN),
    ("GET", "/admin/grupos/{grupo_id}/editar", SO_ADMIN),
    ("GET", "/admin/auditoria", SO_ADMIN),
    ("POST", "/literatura/artigos/{artigo_id}/triar", "triar_artigos"),
    ("POST", "/literatura/artigos/{artigo_id}/sugerir", "triar_artigos"),
    ("POST", "/literatura/artigos/{artigo_id}/sugestoes/{sugestao_id}/{acao}", "triar_artigos"),
    ("POST", "/achados/{achado_id}/verificar", "verificar_achados"),
    ("POST", "/achados/{achado_id}/sugerir", "verificar_achados"),
    ("POST", "/achados/{achado_id}/sugestoes/{sugestao_id}/{acao}", "verificar_achados"),
    ("POST", "/achados/{achado_id}/desfazer", "verificar_achados"),
    ("POST", "/achados/{achado_id}/revogar", "revogar_verificacao"),
    ("POST", "/validacao/sortear", SO_ADMIN),
    ("POST", "/validacao/{ordem}/triar", "triar_artigos"),
    ("POST", "/conta/token", "enviar_coletas"),
    ("POST", "/conta/token/revogar", LOGADO),
    ("POST", "/admin/usuarios", SO_ADMIN),
    ("POST", "/admin/usuarios/{usuario_id}", SO_ADMIN),
    ("POST", "/admin/grupos/novo", SO_ADMIN),
    ("POST", "/admin/grupos/{grupo_id}/renomear", SO_ADMIN),
    ("POST", "/admin/grupos/{grupo_id}/revisar", SO_ADMIN),
    ("POST", "/admin/grupos/{grupo_id}/permissoes", SO_ADMIN),
    ("GET", "/api/coletas", SO_ADMIN),
    ("POST", "/api/coletas", SO_ADMIN),
    ("PUT", "/api/coletas", SO_ADMIN),
    ("PATCH", "/api/coletas", SO_ADMIN),
    ("DELETE", "/api/coletas", SO_ADMIN),
    ("OPTIONS", "/api/coletas", SO_ADMIN),
)

SENHA_MIN = 10
SENHA_MAX = 200
NOME_MAX = 80
PROXIMO_MAX = 2000
FALHAS_ATE_BLOQUEIO = 5
MINUTOS_DE_BLOQUEIO = 5
HORAS_DE_SESSAO = 12
DIAS_MAXIMOS_DE_SESSAO = 7          # validade absoluta: uma sessao em uso continuo tambem expira
TOLERANCIA_RELOGIO_NA_CRIACAO_SEGUNDOS = 2  # sessao nunca renovada (ultimo uso igual a criacao): relogio do servidor ate 2 s atrasado no pedido seguinte nao a invalida (RI38)


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


def regra_explicita(metodo: str, caminho: str) -> tuple | None:
    """Retorna a primeira regra explícita em REGRAS_ROTAS que casa com o método e o caminho.

    Toda nova rota do painel precisa ter uma linha em REGRAS_ROTAS (o teste de cobertura falha caso contrário).
    """
    c_partes = caminho.split("/")
    for regra in REGRAS_ROTAS:
        r_metodo, r_padrao, _ = regra
        if r_metodo != metodo:
            continue
        p_partes = r_padrao.split("/")
        if len(p_partes) != len(c_partes):
            continue
        if all(bool(c) if (p.startswith("{") and p.endswith("}")) else (p == c) for p, c in zip(p_partes, c_partes)):
            return regra
    return None


def permissao_exigida(metodo: str, caminho: str) -> str | None:
    """Determina a permissão necessária para acessar determinado método e rota."""
    if metodo == "HEAD":
        metodo = "GET"
    if caminho.startswith("/static/"):
        return None
    if caminho in ("/entrar", "/sair"):
        return None
    regra = regra_explicita(metodo, caminho)
    if regra is not None:
        return regra[2]
    if caminho == "/admin" or caminho.startswith("/admin/"):
        return SO_ADMIN
    if metodo == "GET" and (caminho.startswith("/execucoes") or caminho.startswith("/chamadas")):
        return "ver_chamadas"
    if metodo == "GET":
        return "ver_painel"
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


def ve_detalhes_tecnicos(logado: bool, grupo: str, permissoes) -> bool:
    """Indica se o usuário autenticado pode ver detalhes operacionais e técnicos."""
    if not logado:
        return False
    return bool(pode(grupo, permissoes, "ver_chamadas"))


def pode_acessar(grupo: str, permissoes: set[str] | list[str], metodo: str, caminho: str) -> bool:
    """Verifica se um grupo com dadas permissões tem acesso para executar o método no caminho."""
    if not pode(grupo, permissoes, permissao_exigida(metodo, caminho)):
        return False
    # Planilhas restritas: protege chamadas, nomes, custos, triagem, verificação e registros de revisão
    if metodo in ("GET", "HEAD") and caminho in EXIGENCIAS_EXPORTACOES:
        return all(pode(grupo, permissoes, p) for p in EXIGENCIAS_EXPORTACOES[caminho])
    return True


def resumo_do_grupo(grupo: str, permissoes: set[str] | frozenset[str]) -> dict:
    """Calcula resumo das capacidades efetivas do grupo."""
    _pode = sys.modules[__name__].pode
    hab = [p for p in PERMISSOES if _pode(grupo, permissoes, p)]
    modulos = [m for m in MODULOS_PERMISSAO if any(CATALOGO_PERMISSOES[p]["modulo"] == m for p in hab)]
    sens = [p for p in hab if CATALOGO_PERMISSOES[p]["sensibilidade"] in ROTULOS_SENSIBILIDADE]
    return {
        "habilitadas": hab,
        "total": len(PERMISSOES),
        "modulos_com_acesso": modulos,
        "sensiveis_habilitadas": sens,
    }


def _normalizar_texto(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_combinantes = "".join(ch for ch in nfkd if unicodedata.combining(ch) == 0)
    return sem_combinantes.casefold()


def filtrar_permissoes(
    grupo: str,
    permissoes: set[str] | frozenset[str],
    busca: str,
    filtro: str,
    modulo: str,
) -> list[str]:
    """Filtra permissões do catálogo segundo busca de texto, estado/sensibilidade e módulo."""
    b = busca.strip()
    if len(b) > 100:
        return []
    b_norm = _normalizar_texto(b)

    _pode = sys.modules[__name__].pode
    resultado = []
    for chave in PERMISSOES:
        meta = CATALOGO_PERMISSOES[chave]
        if modulo in MODULOS_PERMISSAO and meta["modulo"] != modulo:
            continue
        if filtro == "habilitadas" and not _pode(grupo, permissoes, chave):
            continue
        elif filtro == "desabilitadas" and _pode(grupo, permissoes, chave):
            continue
        elif filtro == "sensiveis" and meta["sensibilidade"] not in ROTULOS_SENSIBILIDADE:
            continue

        if b_norm:
            desc_norm = _normalizar_texto(PERMISSOES[chave])
            chave_norm = _normalizar_texto(chave)
            if b_norm not in desc_norm and b_norm not in chave_norm:
                continue

        resultado.append(chave)
    return resultado


def pode_desfazer_decisao(grupo: str | None, nome: str | None, autor: str | None) -> bool:
    """Verifica se o usuário pode desfazer a decisão tomada por autor."""
    return grupo == GRUPO_ADMIN or (bool(nome) and bool(autor) and nome == autor)


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


def plano_permissoes_novas(grupos: list[dict] | tuple[dict, ...], aprovados: tuple[str, ...] | list[str] = ()) -> dict:
    """Calcula o plano de concessão das permissões novas aos grupos existentes."""
    mapa_grupos = {g["nome"]: g for g in grupos}

    # Validação de aprovados na ordem informada
    for nome in aprovados:
        if nome not in mapa_grupos:
            raise ValueError(f"Grupo não encontrado: {nome}")
        if nome in (GRUPO_ADMIN, GRUPO_VISITANTE):
            raise ValueError(f"O grupo {nome} não recebe permissões por este comando.")
        if "ver_painel" not in mapa_grupos[nome]["permissoes"]:
            raise ValueError(f"O grupo {nome} não tem ver_painel: não via esses dados e não recebe as permissões novas.")

    conceder = []
    incertos = []
    completos = []
    fora = []

    aprovados_set = set(aprovados)
    conjunto_permissoes = set(PERMISSOES)

    for g in grupos:
        nome = g["nome"]
        perms = g["permissoes"]
        gid = g["grupo_id"]

        if nome == GRUPO_ADMIN:
            fora.append((nome, "tem todas pelo nome"))
        elif nome == GRUPO_VISITANTE:
            fora.append((nome, "proibidas ao visitante"))
        elif "ver_painel" not in perms:
            fora.append((nome, "sem ver_painel"))
        else:
            faltam = [p for p in PERMISSOES_NOVAS if p not in perms]
            if not faltam:
                completos.append(nome)
            elif nome in GRUPOS_EQUIVALENTES or nome in aprovados_set:
                desconhecidas = sorted(perms - conjunto_permissoes)
                if desconhecidas:
                    raise ValueError(
                        f"O grupo {nome} tem permissões desconhecidas gravadas ({', '.join(desconhecidas)}): "
                        "corrija antes de atribuir."
                    )
                motivo = "equivalente" if nome in GRUPOS_EQUIVALENTES else "aprovado"
                conceder.append({
                    "grupo_id": gid,
                    "nome": nome,
                    "atuais": sorted(perms),
                    "adicionar": faltam,
                    "motivo": motivo,
                })
            else:
                incertos.append({
                    "grupo_id": gid,
                    "nome": nome,
                    "adicionar": faltam,
                })

    if conceder:
        linhas = [f"{c['grupo_id']}\t{c['nome']}\t{','.join(c['atuais'])}\t{','.join(c['adicionar'])}" for c in conceder]
        codigo = hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()[:12]
    else:
        codigo = None

    return {
        "conceder": conceder,
        "incertos": incertos,
        "completos": completos,
        "fora": fora,
        "codigo": codigo,
    }


JUSTIFICATIVA_MAX = 500


def revisar_alteracao(grupo: str, atuais, marcadas, exibidas) -> dict:
    """Revisa a alteração de permissões de um grupo, calculando diferenças e inconsistências."""
    if grupo == GRUPO_ADMIN:
        return {
            "antes": sorted(atuais),
            "depois": sorted(atuais),
            "concedidas": [],
            "retiradas": [],
            "sensiveis": [],
            "exige_justificativa": False,
            "erros": ["O grupo Administrador tem acesso integral e não pode ser alterado."],
        }

    if (
        not isinstance(marcadas, (list, tuple))
        or not isinstance(exibidas, (list, tuple))
        or any(type(x) is not str for x in marcadas)
        or any(type(x) is not str for x in exibidas)
        or not any(x in CATALOGO_PERMISSOES for x in exibidas)
    ):
        return {
            "antes": sorted(atuais),
            "depois": sorted(atuais),
            "concedidas": [],
            "retiradas": [],
            "sensiveis": [],
            "exige_justificativa": False,
            "erros": ["O formulário veio incompleto. Abra o grupo de novo e refaça as alterações."],
        }

    atuais_set = set(atuais)
    E = {p for p in exibidas if p in CATALOGO_PERMISSOES}
    M = set(marcadas)
    depois_set = (atuais_set - E) | (M & E)
    depois = sorted(depois_set)
    concedidas_set = depois_set - atuais_set
    retiradas_set = atuais_set - depois_set

    concedidas = [p for p in CATALOGO_PERMISSOES if p in concedidas_set]
    retiradas = [p for p in CATALOGO_PERMISSOES if p in retiradas_set]
    sensiveis = [
        p for p in concedidas
        if CATALOGO_PERMISSOES[p].get("sensibilidade") in ROTULOS_SENSIBILIDADE
    ]
    exige_justificativa = bool(
        sensiveis
        or any(CATALOGO_PERMISSOES[p].get("sensibilidade") == "supervisao" for p in retiradas)
    )

    erros: list[str] = []

    # 1. Chaves desconhecidas contadas sem ecoar
    desconhecidas = (set(exibidas) | M) - set(CATALOGO_PERMISSOES)
    n_desc = len(desconhecidas)
    if n_desc == 1:
        erros.append("O formulário trouxe 1 permissão desconhecida.")
    elif n_desc > 1:
        erros.append(f"O formulário trouxe {n_desc} permissões desconhecidas.")

    # 2. Marcadas fora da lista exibida
    for p in CATALOGO_PERMISSOES:
        if p in M and p not in E:
            erros.append(f"«{PERMISSOES[p]}» foi marcada, mas não fazia parte do formulário.")

    # 3. Recusas de quem não entrou (Visitante)
    if grupo == GRUPO_VISITANTE:
        for p in concedidas:
            desc = PERMISSOES[p]
            if p in PERMISSOES_PROIBIDAS_VISITANTE:
                erros.append(f"«{desc}» não pode ser dada a quem não entrou.")
            elif p in sensiveis:
                erros.append(
                    f"«{desc}» não pode ser dada a quem não entrou enquanto não houver política de divulgação pública."
                )

    # 4. Dependências no estado final
    for p in CATALOGO_PERMISSOES:
        if p in depois_set:
            for d in CATALOGO_PERMISSOES[p].get("depende_de", ()):
                if d not in depois_set:
                    erros.append(
                        f"«{PERMISSOES[p]}» precisa de «{PERMISSOES[d]}»: marque as duas ou desmarque «{PERMISSOES[p]}»."
                    )

    return {
        "antes": sorted(atuais),
        "depois": depois,
        "concedidas": concedidas,
        "retiradas": retiradas,
        "sensiveis": sensiveis,
        "exige_justificativa": exige_justificativa,
        "erros": erros,
    }


def pendencias_da_gravacao(revisao: dict, confirmado: bool, justificativa: str) -> list[str]:
    """Verifica pendências que impedem a gravação das permissões revisadas."""
    pendencias: list[str] = []
    if revisao.get("sensiveis") and not confirmado:
        pendencias.append("Marque a confirmação das permissões sensíveis antes de gravar.")
    if revisao.get("exige_justificativa") and not justificativa.strip():
        pendencias.append(
            "Escreva a justificativa: ela é obrigatória ao conceder permissões sensíveis ou retirar uma permissão de supervisão."
        )
    if len(justificativa) > JUSTIFICATIVA_MAX:
        pendencias.append(f"A justificativa tem {len(justificativa)} caracteres; o máximo é {JUSTIFICATIVA_MAX}.")
    return pendencias


def detalhe_auditoria(revisao: dict, justificativa: str, origem: str = "edicao") -> str:
    """Gera o detalhe JSON para a linha de auditoria da alteração de permissões."""
    dados = {
        "antes": sorted(revisao["antes"]),
        "depois": sorted(revisao["depois"]),
        "concedidas": sorted(revisao["concedidas"]),
        "retiradas": sorted(revisao["retiradas"]),
        "justificativa": justificativa if justificativa.strip() else "",
        "origem": origem,
    }
    return json.dumps(dados, ensure_ascii=False)


def resumo_detalhe_auditoria(texto: str | None) -> str | None:
    """Gera um resumo legível do detalhe JSON de auditoria da alteração de permissões."""
    if not isinstance(texto, str):
        return None
    try:
        dados = json.loads(texto)
    except (ValueError, RecursionError, TypeError):
        return None
    if not isinstance(dados, dict):
        return None
    if set(dados.keys()) != {"antes", "depois", "concedidas", "retiradas", "justificativa", "origem"}:
        return None
    for k in ("antes", "depois", "concedidas", "retiradas"):
        v = dados[k]
        if not isinstance(v, list) or any(type(x) is not str for x in v):
            return None
    if type(dados["justificativa"]) is not str or type(dados["origem"]) is not str:
        return None

    concedidas_str = ", ".join(dados["concedidas"]) or "nenhuma"
    retiradas_str = ", ".join(dados["retiradas"]) or "nenhuma"
    resumo = f"Concedidas: {concedidas_str}. Retiradas: {retiradas_str}."
    justificativa = dados["justificativa"]
    if justificativa:
        resumo += f" Justificativa: {justificativa}"
    return resumo

