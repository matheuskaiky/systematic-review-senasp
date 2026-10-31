"""Regras de domínio da política de divulgação pública por pesquisa (D145)."""
import hashlib
import json

ROTAS_PUBLICAS = frozenset({"/", "/sobre", "/literatura/prisma", "/metodologia", "/buscar-texto"})
INVALIDA = "Configuração de divulgação inválida."
PRELIMINARES = "A divulgação de resultados preliminares ainda não está disponível."
PESQUISAS = frozenset({"real", "vies", "demo", "simulado"})


class DivulgacaoAlterada(Exception):
    """A linha de configuração gravada mudou desde a leitura."""


def chave(banco: str) -> str:
    """Devolve a chave da configuração de divulgação para o banco informado."""
    return f"divulgacao:{banco}"


def versao(valor) -> str:
    """Calcula a versão SHA-256 do valor bruto gravado."""
    return hashlib.sha256(repr(valor).encode("utf-8", "surrogatepass")).hexdigest()


def validar_nova(nova) -> list[str]:
    """Valida uma nova configuração de divulgação para gravação."""
    if not isinstance(nova, dict):
        return [INVALIDA]
    if set(nova.keys()) != {"publica", "preliminares"}:
        return [INVALIDA]
    if type(nova["publica"]) is not bool or type(nova["preliminares"]) is not bool:
        return [INVALIDA]
    if nova["preliminares"] is True:
        return [PRELIMINARES]
    return []


def nova_do_formulario(publica: list[str], preliminares: list[str]) -> tuple[dict | None, list[str]]:
    """Lê os campos da política enviados pelo formulário com validação estrita."""
    erros: list[str] = []
    pub_val = None
    if not isinstance(publica, list):
        erros.append(INVALIDA)
    elif len(publica) == 1 and publica[0] in ("0", "1"):
        pub_val = publica[0] == "1"
    else:
        erros.append(INVALIDA)

    if not isinstance(preliminares, list):
        erros.append(INVALIDA)
    elif preliminares in ([], ["0"]):
        pass
    elif preliminares == ["1"]:
        erros.append(PRELIMINARES)
    else:
        erros.append(INVALIDA)

    if erros:
        return (None, erros)
    return ({"publica": pub_val, "preliminares": False}, [])


def revisar(antes: dict, nova: dict, situacao: str = "valida") -> dict:
    """Resume o efeito da alteração de política e define frases e confirmação."""
    if situacao == "invalida" and not nova["publica"]:
        muda = True
        amplia = False
        frase = ("A configuração inválida será trocada por «não divulgada»: quem não entrou continua sendo levado à tela de entrada.")
        confirmacao = "Entendo que a pesquisa continua fechada para quem não entrou."
    else:
        muda = antes["publica"] != nova["publica"]
        amplia = muda and nova["publica"]
        if muda:
            if amplia:
                frase = ("Quem não entrou passará a ver a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e "
                         "a busca no texto, sem resultados automatizados.")
                confirmacao = ("Entendo que qualquer pessoa na internet passará a ver: a Visão Geral, Sobre os dados, "
                               "o PRISMA, a Metodologia e a busca no texto, sem resultados automatizados.")
            else:
                frase = ("Quem não entrou passará a ser levado à tela de entrada em todas as páginas desta "
                         "pesquisa.")
                confirmacao = "Entendo que quem não entrou deixará de ver as páginas desta pesquisa."
        else:
            frase = "Nada muda: a divulgação já está assim."
            confirmacao = None
    return {
        "antes": antes,
        "depois": nova,
        "muda": muda,
        "amplia": amplia,
        "confirmacao": confirmacao,
        "frase": frase,
    }


def resumo_auditoria(detalhe) -> str | None:
    """Devolve o resumo textual de uma entrada de auditoria de divulgação."""
    if not isinstance(detalhe, str):
        return None
    try:
        obj = json.loads(detalhe, object_pairs_hook=_pares_sem_repeticao)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    situacao_antes = obj.get("situacao_antes")
    if situacao_antes not in ("ausente", "invalida", "valida"):
        return None
    depois = obj.get("depois")
    if not isinstance(depois, dict) or type(depois.get("publica")) is not bool:
        return None
    depois_txt = "Divulgada" if depois["publica"] else "Não divulgada"
    if situacao_antes == "ausente":
        antes_txt = "Não configurada"
    elif situacao_antes == "invalida":
        antes_txt = "Configuração inválida"
    else:
        antes = obj.get("antes")
        if not isinstance(antes, dict) or type(antes.get("publica")) is not bool:
            return None
        antes_txt = "Divulgada" if antes["publica"] else "Não divulgada"
    return f"{antes_txt} → {depois_txt}"


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


def plano_inicial(banco: str, estado: dict, visitante_ve_painel: bool) -> dict:
    """Calcula o plano para inicialização da política de divulgação de uma pesquisa."""
    if estado["situacao"] != "ausente":
        return {"acao": "nada", "motivo": "configurada", "nova": None, "codigo": None}
    if not visitante_ve_painel:
        return {"acao": "nada", "motivo": "fechada", "nova": None, "codigo": None}
    codigo = hashlib.sha256(f"divulgacao-inicial|{banco}|{estado['versao']}|1".encode("utf-8")).hexdigest()[:12]
    return {
        "acao": "gravar",
        "motivo": "proposta",
        "nova": {"publica": True, "preliminares": False},
        "codigo": codigo,
    }
