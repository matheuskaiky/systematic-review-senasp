"""Terminologia: "usuario" no lugar de "login" em tudo o que a pessoa le (D155, E4). Continuam o campo e o id `login` dos
formularios, a coluna `login`, a opcao --login e as mensagens da linha de comando, e o detalhe gravado na auditoria."""
import re
from pathlib import Path

import pytest

from dominio import autenticacao as A

RAIZ = Path(__file__).resolve().parents[1]
MODELOS = ["painel/templates/entrar.html", "painel/templates/conta.html", "painel/templates/admin_usuarios.html",
           "painel/templates/admin_usuario.html"]
NOVOS = [
    ("painel/templates/entrar.html", '<p class="sub">Use o usuário e a senha enviados pela coordenação da pesquisa.</p>', 1),
    ("painel/templates/entrar.html", "<strong>Usuário ou senha incorretos.</strong>", 1),
    ("painel/templates/entrar.html", '<label for="login">Usuário</label>', 1),
    ("painel/templates/conta.html", "<dt>Usuário</dt>", 1),
    ("painel/templates/conta.html", "Para mudar nome, usuário, grupo ou senha, fale com um administrador do painel.", 1),
    ("painel/templates/admin_usuarios.html", '<th scope="col">Usuário</th>', 1),
    ("painel/templates/admin_usuarios.html", '<label for="login">Usuário</label>', 1),
    ("painel/templates/admin_usuario.html", '<label for="login">Usuário</label>', 1),
    ("adaptadores/contas_sqlite.py", 'raise ValueError(f"Nome de usuário já existe: {login}")', 2),
    ("painel/app.py", '"As sugestões só existem quando o painel exige entrada com usuário e senha."', 1),
]


@pytest.mark.parametrize("arquivo, texto, n", NOVOS, ids=[f"{i:02d}" for i in range(len(NOVOS))])
def test_texto_novo(arquivo, texto, n):
    assert (RAIZ / arquivo).read_text(encoding="utf-8").count(texto) == n


def _visiveis(fonte):
    sem_comentarios = re.sub(r"\{#.*?#\}", "", fonte, flags=re.S)
    sem_codigo = re.sub(r"<code>.*?</code>", "", sem_comentarios, flags=re.S)     # o comando --login da linha de comando fica
    nos = re.findall(r">([^<>]+)<", re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", sem_codigo, flags=re.S))
    literais = [m for bloco in re.findall(r"\{\{(.*?)\}\}", sem_codigo, flags=re.S) for m in re.findall(r'"([^"]*)"', bloco)]
    atributos = re.findall(r'\b(?:placeholder|title|aria-label|alt|value)="([^"]*)"', re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", sem_codigo, flags=re.S))  # atributos que a pessoa le
    return nos + literais + atributos


@pytest.mark.parametrize("arquivo", MODELOS)
def test_nenhum_texto_visivel_com_login(arquivo):
    assert [t for t in _visiveis((RAIZ / arquivo).read_text(encoding="utf-8")) if re.search(r"\blogin\b", t, re.I)] == []


def test_mensagem_de_validacao():
    assert A.validar_login("ab") == ["O nome de usuário deve ter de 3 a 40 caracteres: letras minúsculas, números, ponto, "
                                     "hífen ou sublinhado."]


def test_identificadores_nao_mudam():
    entrada = (RAIZ / "painel/templates/entrar.html").read_text(encoding="utf-8")
    assert 'name="login"' in entrada and 'id="login"' in entrada and "--login" in entrada
    assert re.search(r'f"login: \{alvo\[\'login\'\]\} -> \{login\}"', (RAIZ / "painel/rotas_extras/admin.py").read_text(encoding="utf-8"))
