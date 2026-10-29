"""Regras de domínio da política de divulgação pública por pesquisa (D145)."""
import json

ROTAS_PUBLICAS = frozenset({"/", "/sobre", "/literatura/prisma"})


def chave(banco: str) -> str:
    """Devolve a chave da configuração de divulgação para o banco informado."""
    return f"divulgacao:{banco}"


def validar_nova(nova) -> list[str]:
    """Valida uma nova configuração de divulgação para gravação."""
    if not isinstance(nova, dict):
        return ["Configuração de divulgação inválida."]
    if set(nova.keys()) != {"publica", "preliminares"}:
        return ["Configuração de divulgação inválida."]
    if type(nova["publica"]) is not bool or type(nova["preliminares"]) is not bool:
        return ["Configuração de divulgação inválida."]
    if nova["preliminares"] is True:
        return ["A divulgação de resultados preliminares ainda não está disponível."]
    return []


def valor(politica: dict) -> str:
    """Serializa uma política válida em JSON para gravação."""
    erros = validar_nova(politica)
    if erros:
        raise ValueError(f"Política inválida: {'; '.join(erros)}")
    return json.dumps({"publica": politica["publica"], "preliminares": politica["preliminares"]})


def _pares_sem_repeticao(pares):
    chaves = [k for k, _ in pares]
    if len(chaves) != len(set(chaves)):
        raise ValueError("Chave repetida no JSON")
    return dict(pares)


def _fechada() -> dict:
    return {"publica": False, "preliminares": False}


def ler_politica(valor) -> tuple[dict, str]:
    """Interpreta o valor gravado da política de divulgação."""
    if valor is None:
        return (_fechada(), "ausente")
    if not isinstance(valor, str):
        return (_fechada(), "invalida")
    if len(valor) > 1000:
        return (_fechada(), "invalida")
    try:
        obj = json.loads(valor, object_pairs_hook=_pares_sem_repeticao)
    except Exception:
        return (_fechada(), "invalida")

    if not isinstance(obj, dict) or set(obj.keys()) != {"publica", "preliminares"}:
        return (_fechada(), "invalida")
    if type(obj["publica"]) is not bool or type(obj["preliminares"]) is not bool:
        return (_fechada(), "invalida")
    if obj["preliminares"] is not False:
        return (_fechada(), "invalida")

    return ({"publica": obj["publica"], "preliminares": False}, "valida")


def decisao_publico(metodo: str, caminho: str, politica) -> str:
    """Decide se uma requisição pública tem acesso liberado ou vai para a entrada."""
    if caminho.startswith("/static/") or caminho in ("/entrar", "/sair", "/api/coletas"):
        return "liberada"
    if validar_nova(politica) != []:
        return "entrada"
    if not politica["publica"]:
        return "entrada"
    if metodo in ("GET", "HEAD") and caminho in ROTAS_PUBLICAS:
        return "liberada"
    return "entrada"
