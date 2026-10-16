"""Pagina /analises: o plano de analise de dados e o plano de visualizacao no painel.

Cinco abas (`?secao=`): visao, adocao, busca, literatura, auditoria, operacao. Cada aba so le o que mostra, para a pagina
abrir rapido mesmo com o banco em /mnt/c. So le o banco; nenhum numero daqui e gravado. Os blocos vem de
`painel/analises_blocos.py` (funcoes puras)."""
from fastapi import Request
from fastapi.responses import HTMLResponse

from painel import analises_blocos as b

ABAS = (
    ("visao", "Visão geral"), ("adocao", "Adoção por UF"), ("busca", "Eficiência da busca"),
    ("literatura", "Literatura"), ("auditoria", "Confiança na IA"), ("operacao", "Operação"),
)
CHAVES = {chave for chave, _ in ABAS}


def montar(leitura, secao):
    """Devolve (blocos, resumo). `resumo` so e lido nas abas que precisam dele (e a leitura mais cara)."""
    resumo = leitura.analise_resumo() if secao in ("visao", "auditoria") else None
    if secao == "visao":
        funil = leitura.analise_funil_por_provedor()
        return [b.bloco_hipoteses(resumo, funil)], resumo
    if secao == "adocao":
        m = leitura.analise_maturidade_uf_tecnologia()
        return [b.bloco_maturidade(m), b.bloco_regiao_tecnologia(m), b.bloco_lgpd(leitura.analise_lgpd_por_tecnologia()),
                b.bloco_fornecedores(leitura.analise_fornecedores())], resumo
    if secao == "busca":
        return [b.bloco_funil(leitura.analise_funil_por_provedor()),
                b.bloco_posicao_web(leitura.analise_retorno_por_posicao("web")),
                b.bloco_posicao_scholar(leitura.analise_retorno_por_posicao("scholar")),
                b.bloco_saturacao(leitura.analise_saturacao())], resumo
    if secao == "literatura":
        return [b.bloco_temporal(leitura.analise_literatura_temporal()), b.bloco_multitermo(leitura.analise_multitermo())], resumo
    if secao == "auditoria":
        return [b.bloco_calibracao(leitura.analise_calibracao_confianca()),
                b.bloco_falsa_exclusao(leitura.analise_falsa_exclusao())], resumo
    return [b.bloco_opacidade(leitura.analise_opacidade_dominios()), b.bloco_tokens(leitura.analise_calibracao_tokens()),
            b.bloco_tamanho(leitura.analise_tamanho_texto_achados())], resumo


def registrar(c):
    app, leitura = c.app, c.leitura

    @app.get("/analises", response_class=HTMLResponse)
    def analises(request: Request):
        if not leitura.existe():
            return c.sem_banco(request)
        secao = (request.query_params.get("secao") or "visao").strip().lower()
        if secao not in CHAVES:
            return c.erro(request, 404, "Aba inválida", "Escolha uma das abas da página de análises.")
        blocos, resumo = montar(leitura, secao)
        return c.pagina(request, "analises.html", secao=secao, abas=ABAS, blocos=blocos, resumo=resumo)
