"""Pagina /analises: o plano de analise de dados e o plano de visualizacao no painel.

Oito abas (`?secao=`): visao, adocao, busca, literatura, termos, web, auditoria, operacao. Cada aba so le o que mostra, para a pagina
abrir rapido mesmo com o banco em /mnt/c. So le o banco; nenhum numero daqui e gravado. Os blocos vem de
`painel/analises_blocos.py` (funcoes puras)."""
from fastapi import Request
from fastapi.responses import HTMLResponse

from datetime import datetime

from dominio import analises_ferramentas as AF, analises_vies as AV
from painel import analises_blocos as b, analises_blocos_cobertura as bc, analises_blocos_ferramentas as bf
from painel import analises_blocos_ruido as br, analises_blocos_vies as bv, visao_geral_vies

ABAS = (
    ("visao", "Visão geral"), ("adocao", "Adoção por UF"), ("busca", "Eficiência da busca"),
    ("literatura", "Literatura"), ("termos", "Termos dos artigos"), ("web", "Consultas e filtro da web"),
    ("auditoria", "Confiança na IA"), ("operacao", "Operação"),
)
CHAVES = {chave for chave, _ in ABAS}


def anonimizar_revisores(d):
    """Substitui nomes de revisores por pseudônimos ordenados por primeira aparição."""
    if not d or not d.get("pares"):
        return d
    d_novo = dict(d)
    mapa = {}
    pares_novos = []
    for par in d["pares"]:
        p = dict(par)
        for campo in ("revisor_a", "revisor_b"):
            nome = par.get(campo)
            if nome is not None:
                if nome not in mapa:
                    mapa[nome] = f"Revisor {len(mapa) + 1}"
                p[campo] = mapa[nome]
        pares_novos.append(p)
    d_novo["pares"] = pares_novos
    return d_novo


def montar(leitura, secao, ver_nomes=True, ferramentas=None):
    """Devolve (blocos, resumo). `resumo` so e lido nas abas que precisam dele (e a leitura mais cara). `ferramentas`: as
    linhas de `dominio.analises_ferramentas.linhas`, se quem chama ja as leu."""
    resumo = leitura.analise_resumo() if secao in ("visao", "auditoria") else None
    if secao == "visao":
        funil = leitura.analise_funil_por_provedor()
        return [b.bloco_prontidao(leitura.analise_prontidao()), b.bloco_hipoteses(resumo, funil, leitura.analise_falsa_exclusao())], resumo
    if secao == "adocao":
        m = leitura.analise_maturidade_uf_tecnologia()
        return [b.bloco_maturidade(m), b.bloco_regiao_tecnologia(m), b.bloco_lgpd(leitura.analise_lgpd_por_tecnologia()),
                b.bloco_fornecedores(leitura.analise_fornecedores())], resumo
    if secao == "busca":
        ferramentas = ferramentas if ferramentas is not None else AF.linhas(leitura.analise_ferramentas())
        return [bf.bloco_ferramentas_busca(ferramentas), bf.bloco_custos(ferramentas),
                b.bloco_funil(leitura.analise_funil_por_provedor()),
                b.bloco_posicao_web(leitura.analise_retorno_por_posicao("web")),
                b.bloco_posicao_scholar(leitura.analise_retorno_por_posicao("scholar")),
                b.bloco_saturacao(leitura.analise_saturacao())], resumo
    if secao == "literatura":
        return [b.bloco_temporal(leitura.analise_literatura_temporal()), b.bloco_multitermo(leitura.analise_multitermo())], resumo
    if secao == "termos":
        cobertura = leitura.analise_cobertura_incremental()
        return (bc.blocos_cobertura_termos(leitura.analise_cobertura_termos(), cobertura)
                + bc.blocos_redundancia(leitura.analise_redundancia_termos(), cobertura)
                + br.blocos_ruido_termos(leitura.analise_ruido_por_termo())
                + br.blocos_simulacao(leitura.analise_simulacao_contexto())), resumo
    if secao == "web":
        return (bc.blocos_cobertura_web(leitura.analise_cobertura_web())
                + br.blocos_prefiltro(leitura.analise_prefiltro_web())), resumo
    if secao == "auditoria":
        d = leitura.analise_concordancia_achados()
        if not ver_nomes:
            d = anonimizar_revisores(d)
        return [b.bloco_calibracao(leitura.analise_calibracao_confianca()),
                b.bloco_falsa_exclusao(leitura.analise_falsa_exclusao()),
                b.bloco_auditoria_negativos(leitura.analise_auditoria_negativos()),
                b.bloco_concordancia_achados(d)], resumo
    return [b.bloco_opacidade(leitura.analise_opacidade_dominios()), b.bloco_nao_verificaveis(leitura.analise_nao_verificaveis()),
            b.bloco_tokens(leitura.analise_calibracao_tokens()),
            b.bloco_tamanho(leitura.analise_tamanho_texto_achados())], resumo


def montar_vies(leitura, contexto, secao, ferramentas):
    """Os blocos do banco `vies` (busca de vies algoritmico) e os numeros do panorama: so as analises do tipo de informacao
    desta busca (fonte, relevancia, ferramentas, tipo de fonte, eixo, topicos, ano, pais, consultas, conjuntos e sites)."""
    conjunto = contexto.conjunto_da_consulta
    itens = visao_geral_vies.itens(leitura, contexto)
    ids_por_conjunto = {}
    for cid, nome in conjunto.items():
        ids_por_conjunto.setdefault(nome, []).append(cid)
    textos = contexto.consultas_literatura
    resumo = AV.resumo(itens)
    blocos = {"panorama": lambda: [bv.bloco_relevancia(itens), bv.bloco_sobreposicao(resumo),
                                   bv.bloco_identidade(itens, contexto.recortes_vies)],
              "ferramentas": lambda: [bv.bloco_ferramentas_relevancia(AV.relevancia_por_ferramenta(ferramentas, itens)),
                                      bf.bloco_ferramentas_busca(ferramentas), bf.bloco_custos(ferramentas)],
              "tipos": lambda: [bv.bloco_grupos(itens), bv.bloco_relevancia_por_grupo(itens), bv.bloco_tipos(itens)],
              "temas": lambda: [bv.bloco_eixos(itens, tuple(contexto.eixos_exploracao)), bv.bloco_eixo_relevancia(itens),
                                bv.bloco_topicos(itens, list(textos.values()))],
              "tempo": lambda: [bv.bloco_anos(itens, datetime.now().year), bv.bloco_paises(itens)],
              "consultas": lambda: [bv.bloco_consultas(itens, ids_por_conjunto, textos), bv.bloco_conjuntos(itens, tuple(ids_por_conjunto)),
                                bv.bloco_origem_angulo(itens, tuple(ids_por_conjunto), contexto.recortes_vies)],
              "web": lambda: [bv.bloco_dominios(itens)]}[secao]()
    return blocos, (resumo if secao == "panorama" else None)


def registrar(c):
    app, leitura = c.app, c.leitura

    @app.get("/analises", response_class=HTMLResponse)
    def analises(request: Request):
        if not leitura.existe():
            return c.sem_banco(request)
        vies = c.contexto.banco == "vies"            # o banco da busca de vies tem as analises dela, nao as da Tarefa 1
        abas = bv.ABAS_VIES if vies else ABAS
        secao = (request.query_params.get("secao") or abas[0][0]).strip().lower()
        if secao not in {chave for chave, _ in abas}:
            return c.erro(request, 404, "Aba inválida", "Escolha uma das abas da página de análises.")
        if vies:
            with leitura.instantaneo() as l:
                ferramentas = AF.linhas(l.analise_ferramentas())
                blocos, resumo_vies = montar_vies(l, c.contexto, secao, ferramentas)
            return c.pagina(request, "analises.html", secao=secao, abas=abas, blocos=blocos, resumo=None, resumo_vies=resumo_vies,
                            ferramentas=ferramentas)
        ferramentas = AF.linhas(leitura.analise_ferramentas())      # tambem para a legenda do fim da pagina
        ver_nomes = getattr(request.state, "ver_nomes", True)
        blocos, resumo = montar(leitura, secao, ver_nomes=ver_nomes, ferramentas=ferramentas)
        return c.pagina(request, "analises.html", secao=secao, abas=abas, blocos=blocos, resumo=resumo, ferramentas=ferramentas)
