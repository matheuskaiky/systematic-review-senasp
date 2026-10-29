"""Apoio dos testes: grava a politica de divulgacao de uma pesquisa direto no banco de contas de teste (nunca nas contas
reais). Uma pesquisa "divulgada" nos testes antigos e a que o Visitante ja via antes do controle (D145)."""
import json


def gravar_politica(contas, banco, publica=True, preliminares=False):
    contas.garantir_padrao()
    with contas._conexao(escrita=True) as conn:
        conn.execute("DELETE FROM configuracoes WHERE chave = ?", (f"divulgacao:{banco}",))
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)",
                     (f"divulgacao:{banco}", json.dumps({"publica": publica, "preliminares": preliminares})))


def cliente_so_painel(painel, login="sopainel"):
    """Cliente logado num grupo so com ver_painel (sem ver_nomes_revisores): o leitor mais restrito que ainda abre as
    paginas com resultados do modelo, depois que elas fecharam para quem nao entrou (D145)."""
    from fastapi.testclient import TestClient
    from test_autenticacao import _criar, _entrar
    cli, contas, _, _ = painel
    gid = contas.criar_grupo("SoPainel", "2026-10-30T00:00:00+00:00")
    contas.definir_permissoes(gid, {"ver_painel"})
    _criar(painel, login, "SoPainel")
    c = TestClient(cli.app)
    assert _entrar(c, login).status_code == 303
    return c, gid
