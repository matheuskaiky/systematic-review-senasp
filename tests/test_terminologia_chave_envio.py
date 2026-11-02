"""Terminologia: "chave de envio" no lugar de "token" em toda tela e mensagem sobre o envio de coletas (D155, E4). O termo
"token" fica so entre parenteses no titulo da pagina Minha conta, e continuam como estao os identificadores (rotas, campos,
acoes gravadas, variaveis de ambiente, o cabecalho Authorization) e os tokens do modelo de linguagem nas paginas tecnicas."""
import re
from pathlib import Path

import pytest

from dominio import autenticacao as A
from painel import rotulos
from painel.rotas_extras import api, conta

RAIZ = Path(__file__).resolve().parents[1]
MODELOS = ["painel/templates/conta.html", "painel/templates/admin_usuario.html", "painel/templates/admin_usuarios.html"]
NOVOS = [
    ("painel/templates/conta.html", '<h2 data-ic="lock" data-tom="cobalto">Chave de envio (token)</h2>'),
    ("painel/templates/conta.html", "A chave de envio permite que a coleta executada no seu computador envie os resultados para esta "
                                    "plataforma. Ela vale como a sua senha para esse envio: guarde-a só no seu computador e não a "
                                    "mande a ninguém."),
    ("painel/templates/conta.html", "Copie a chave agora: ela não aparece de novo."),
    ("painel/templates/conta.html", "Não recarregue esta página: recarregar gera outra chave. Se perder, gere outra (a atual deixa de valer)."),
    ("painel/templates/conta.html", ">Copiar a chave</button>"),
    ("painel/templates/conta.html", "<dt>Situação</dt><dd>Ativa, começa com <code>{{ token.inicio }}</code></dd>"),
    ("painel/templates/conta.html", "<dt>Criada em</dt><dd>{{ fmt.data_hora(token.criado_em) }}</dd>"),
    ("painel/templates/conta.html", 'if token.ultimo_uso else "nunca usada" }}'),
    ("painel/templates/conta.html", "<p>Você não tem chave de envio ativa.</p>"),
    ("painel/templates/conta.html", '{{ "Gerar outra chave (a atual deixa de valer)" if token else "Gerar a chave de envio" }}'),
    ("painel/templates/conta.html", "Seu grupo não tem mais a permissão de enviar coletas: a chave não envia nada. Você pode revogá-la."),
    ("painel/templates/conta.html", '<button class="botao perigo" type="submit">Revogar a chave</button>'),
    ("painel/templates/admin_usuario.html", "O usuário não tinha chave de envio ativa."),
    ("painel/templates/admin_usuario.html", '<h2 data-ic="lock" data-tom="cobalto">Chave de envio</h2>'),
    ("painel/templates/admin_usuario.html", "<dt>Situação</dt><dd>Ativa, começa com <code>{{ alvo.token.inicio }}</code></dd>"),
    ("painel/templates/admin_usuario.html", "<dt>Criada em</dt><dd>{{ fmt.data_hora(alvo.token.criado_em) }}</dd>"),
    ("painel/templates/admin_usuario.html", 'if alvo.token.ultimo_uso else "nunca usada" }}'),
    ("painel/templates/admin_usuario.html", '<button class="botao perigo" type="submit">Revogar a chave</button>'),
    ("painel/templates/admin_usuario.html", "<p>Sem chave de envio ativa. Conta desativada: não pode ter chave de envio.</p>"),
    ("painel/templates/admin_usuario.html", "<p>Sem chave de envio ativa. Gere a sua na página"),
    ("painel/templates/admin_usuario.html", "<p>Sem chave de envio ativa. O próprio usuário gera a chave na página Minha conta, se o "
                                            "grupo dele tiver a permissão de enviar coletas.</p>"),
    ("painel/templates/admin_usuarios.html", '<th scope="col">Chave de envio</th>'),
]


@pytest.mark.parametrize("arquivo, texto", NOVOS, ids=[f"{i:02d}" for i in range(len(NOVOS))])
def test_texto_novo(arquivo, texto):
    assert (RAIZ / arquivo).read_text(encoding="utf-8").count(texto) == 1


def _visiveis(fonte):
    """Textos entre tags e literais entre aspas dentro de {{ }} (o que a pessoa le), sem atributos, rotas nem variaveis."""
    sem_comentarios = re.sub(r"\{#.*?#\}", "", fonte, flags=re.S)
    nos = re.findall(r">([^<>]+)<", re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", sem_comentarios, flags=re.S))
    literais = [m for bloco in re.findall(r"\{\{(.*?)\}\}", sem_comentarios, flags=re.S) for m in re.findall(r'"([^"]*)"', bloco)]
    return nos + literais


@pytest.mark.parametrize("arquivo", MODELOS)
def test_nenhum_texto_visivel_com_token(arquivo):
    textos = [t for t in _visiveis((RAIZ / arquivo).read_text(encoding="utf-8")) if re.search(r"token", t, re.I)]
    assert textos == (["Chave de envio (token)"] if arquivo.endswith("conta.html") else []), textos


def test_mensagens_do_servidor():
    assert conta.AVISOS == {"revogado": "Chave de envio revogada: ela não envia mais nada.",
                            "sem-token": "Você não tinha chave de envio ativa."}
    assert api.SEM_TOKEN == "Chave de envio ausente: mande o cabeçalho Authorization: Bearer <chave>."
    assert api.TOKEN_INVALIDO == "Chave de envio inválida ou revogada: gere outra na página Minha conta."
    assert A.PERMISSOES["enviar_coletas"] == "Gerar a própria chave de envio e enviar coletas do computador local para a nuvem"
    assert (rotulos.ACOES_AUDITORIA["gerar_token"], rotulos.ACOES_AUDITORIA["revogar_token"]) == (
        "Geração de chave de envio", "Revogação de chave de envio")
    fonte = (RAIZ / "painel" / "rotas_extras" / "conta.py").read_text(encoding="utf-8")
    assert '"Esta conta foi desativada e não pode ter chave de envio."' in fonte and "não pode ter token" not in fonte
    app = (RAIZ / "painel" / "app.py").read_text(encoding="utf-8")
    assert '"A verificação de segurança do formulário falhou. Recarregue a página e tente de novo."' in app
    assert "token de segurança" not in app


def test_identificadores_nao_mudam():
    assert ("POST", "/conta/token", "enviar_coletas") in A.REGRAS_ROTAS and ("POST", "/conta/token/revogar", A.LOGADO) in A.REGRAS_ROTAS
    assert {"gerar_token", "revogar_token"} <= set(rotulos.ACOES_AUDITORIA)
