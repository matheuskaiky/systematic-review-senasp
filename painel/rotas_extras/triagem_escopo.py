"""Pagina Triagem de escopo (LLM): o que o modelo achou de cada item e o que isso ensina sobre as consultas.

Mostra a ficha de ruido de cada termo, os operadores negativos que o modelo sugeriu (validados contra os itens bons) e a lista
de itens com o veredito. So le o banco. O veredito do modelo e uma opiniao: `excluido` fica oculto por padrao nas listas
(quarentena temporaria), nunca e apagado, e a decisao de uma pessoa sempre vence."""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from dominio import refinamento_busca as refino
from painel import rotulos, rotulos_escopo

MAX_PAGINA = 1_000_000
MAX_RUN_ID = 120
POR_PAGINA_PADRAO = 50
POR_PAGINA_MAXIMO = 200
LIMITE_NEGATIVOS = 100               # linhas da tabela de operadores (os mais uteis primeiro)
FONTES = {"artigo": "Artigos (Google Scholar)", "web": "Resultados da busca web"}
_ALIAS_FONTE = {"artigos": "artigo", "artigo": "artigo", "web": "web"}
FILTROS_LISTA = ("status", "categoria_motivo", "termo", "dominio_tematico", "escopo_geografico", "confianca", "valido")
# palavras centrais do tema: um operador negativo que as contenha e sempre `perigoso`, mesmo sem dano colateral medido
PALAVRAS_CENTRAIS_EXTRAS = ("segurança pública", "inteligência artificial", "polícia", "policiamento")
COMANDO_ESTIMAR = "python main.py triar-escopo --fonte artigos --amostra 60 --estratificar --estimar"


def palavras_centrais():
    """Rotulos das tecnologias da pesquisa (menos 'outra IA') e as palavras centrais extras, para proteger os operadores."""
    protegidas = list(PALAVRAS_CENTRAIS_EXTRAS)
    for chave, rotulo in rotulos.TECNOLOGIAS.items():
        if chave != "outra_ia":
            protegidas += [p.strip() for p in rotulo.split("/")]
    return tuple(protegidas)


def _numero_positivo(valor, padrao, maximo):
    """Vazio -> padrao; texto, zero, negativo ou acima de `maximo` -> None."""
    if valor in (None, ""):
        return padrao
    texto = str(valor).strip()
    if not texto.isdigit() or not 1 <= int(texto) <= maximo:
        return None
    return int(texto)


def registrar(c):
    app, leitura = c.app, c.leitura
    c.modelos.env.globals["rotulos_escopo"] = rotulos_escopo

    @app.get("/triagem-escopo", response_class=HTMLResponse)
    def triagem_escopo(request: Request):
        if not leitura.existe():
            return c.sem_banco(request)
        q = request.query_params
        n = _numero_positivo(q.get("p"), 1, MAX_PAGINA)
        if n is None:
            return c.erro(request, 404, "Página inválida", "O número da página não é válido.")
        tam = _numero_positivo(q.get("tam"), POR_PAGINA_PADRAO, POR_PAGINA_MAXIMO) or POR_PAGINA_PADRAO
        execucoes = leitura.execucoes_triagem_escopo()
        contagem_fontes = leitura.fontes_com_triagem_escopo()
        vazio = {"comando_estimar": COMANDO_ESTIMAR, "fontes": FONTES, "contagem_fontes": contagem_fontes, "execucoes": execucoes}
        if not execucoes:
            return c.pagina(request, "triagem_escopo.html", vazio=True, fonte="artigo", **vazio)
        fonte = _ALIAS_FONTE.get((q.get("fonte") or "").strip().lower())
        if fonte is None:
            fonte = "artigo" if contagem_fontes.get("artigo") or not contagem_fontes.get("web") else "web"
        run = (q.get("run") or "").strip()[:MAX_RUN_ID]
        if run not in {e["run_id"] for e in execucoes}:
            run = ""                                       # execucao desconhecida: vale o padrao (a mais recente de cada item)
        linhas = leitura.veredictos(fonte, run or None)
        opcoes = leitura.opcoes_triagem_escopo(fonte, run or None)
        # filtros da lista: valor desconhecido e ignorado
        filtros = {}
        for chave, validos in (("status", set(rotulos_escopo.FILTRO_STATUS) - {""}), ("categoria_motivo", opcoes["categorias"]),
                               ("termo", opcoes["termos"]), ("dominio_tematico", opcoes["dominios"]),
                               ("escopo_geografico", opcoes["escopos"]), ("confianca", opcoes["confiancas"]), ("valido", {"0", "1"})):
            valor = (q.get(chave) or "").strip()
            if valor in validos:
                filtros[chave] = valor
        resumo = leitura.resumo_triagem_escopo(fonte, run or None)
        fichas = refino.ficha_por_termo(linhas)
        avaliacao = refino.avaliar_negativos(linhas, leitura.corpus_triagem_escopo(fonte), palavras_centrais())
        negativos = avaliacao["negativos"]
        ligacoes = {}
        if fonte == "web":                                 # artigo tem pagina propria; o item web liga para o endereco externo
            ligacoes = leitura.itens_por_chaves(
                fonte, {(x["id"], x["uf"]) for neg in negativos[:LIMITE_NEGATIVOS] for x in neg["colaterais"]})
        res = leitura.itens_triagem_escopo(fonte, filtros, n, tam, run or None)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)

        atual = {"fonte": fonte, "run": run, **filtros, **({"tam": tam} if tam != POR_PAGINA_PADRAO else {})}

        def url(**mudancas):
            """Endereco desta pagina com os parametros atuais, trocando os informados (valor vazio ou None remove)."""
            novos = {**atual, **mudancas}
            return "/triagem-escopo?" + urlencode({k: v for k, v in novos.items() if v not in (None, "")})

        return c.pagina(request, "triagem_escopo.html", vazio=False, fonte=fonte, run=run, filtros=filtros, opcoes=opcoes,
                        resumo=resumo, fichas=fichas, por_termo=avaliacao["por_termo"], negativos=negativos[:LIMITE_NEGATIVOS],
                        n_negativos=len(negativos), ligacoes=ligacoes, res=res, n=n, paginas=paginas, url=url,
                        n_perigosos=sum(1 for x in negativos if x["veredito"] == "perigoso"), limite_negativos=LIMITE_NEGATIVOS,
                        **vazio)
