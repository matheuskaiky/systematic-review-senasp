"""Banco de demonstracao do painel: dados FICTICIOS, gravados pelas mesmas etapas do pipeline com adaptadores falsos.
Nunca toca `busca.db` nem `simulado.db`. Hosts ficticios: `*.exemplo.gov.br` (oficial) e `*.example` (nao oficial).
Fica na raiz, como `composicao.py`: liga `aplicacao/` a `adaptadores/`, o que o painel proprio nao pode fazer."""
import hashlib
import json
import logging
import random
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_academica, busca_web, classificacao, download
import pandas as pd
from config import consultas as C, vocabulario as V
from dominio.esquemas import esquema_classificacao
from dominio.modelos import (Achado, ArtigoAcademico, ModeloConsultaWeb, PaginaAcademica, ArquivoBaixado, ParametrosClassificacao, RegistroChamada, ResultadoClassificacao,
                             ResultadoWeb, RespostaBusca, TextoExtraido)
from dominio.servicos import gerar_consultas_web, palavras_chave_tecnologia
from dominio.solucoes import SolucaoConhecida
from infra.util import agora

SEMENTE = 2026
RECLASSIFICADAS_DEMO = 4              # paginas reclassificadas com outro prompt (achado antigo substituido pelo novo)
# cidades FICTICIAS: a demonstracao nao usa nomes de municipios nem de orgaos reais
MUNICIPIOS_DEMO = {"SP": ["Vila Modelo", "Porto Exemplo"], "PE": ["Campo Demo"]}
MODELOS_MUNICIPAIS_DEMO = [ModeloConsultaWeb("M11", "{tec} Secretaria Municipal de Segurança {cidade} {uf}", perfil="oficial")]
FORNECEDORES = ["Alfa Soluções Digitais", "Beta Vigilância S.A.", "Consórcio Gama Segurança", "Delta Analytics", ""]
# cobertura desigual de proposito: algumas UFs sem nenhum achado
UFS_RICAS = ["SP", "RJ", "MG", "BA", "PE", "CE", "RS", "PR", "GO", "DF"]
UFS_MEDIAS = ["ES", "SC", "MT", "MS", "PA", "AM", "MA"]
FRASES = {
    "reconhecimento_facial": "implantou o sistema de reconhecimento facial nas câmeras das estações",
    "leitura_placas": "opera a leitura automática de placas de veículos nas rodovias estaduais",
    "videomonitoramento_inteligente": "ampliou o videomonitoramento inteligente com câmeras analíticas no centro da capital",
    "analise_preditiva": "testa um modelo de análise preditiva para planejar o policiamento",
    "outra_ia": "contratou uma plataforma de inteligência artificial para triagem de ocorrências",
    # RC14: delegacia virtual / chatbot (nome da solucao ficticio abaixo)
    "atendimento_virtual": "lançou um atendimento virtual por WhatsApp, com assistente de inteligência artificial, para registrar boletim de ocorrência online",
}
# nomes proprios FICTICIOS de solucoes: aparecem no texto de parte das paginas e o classificador demonstrativo os devolve em `nome_solucao`
NOMES_SOLUCAO_DEMO = {"reconhecimento_facial": "Rosto Seguro", "leitura_placas": "Placa Atenta", "videomonitoramento_inteligente": "Olho Central",
                      "analise_preditiva": "Rota Prevista", "outra_ia": "Atende Mais",
                      "atendimento_virtual": "Delegacia Virtual Modelo"}
NOME_INVENTADO_DEMO = "Plataforma Fantasma"      # o "modelo" devolve este nome sem que o texto o cite: o sistema o descarta


# Variantes do MESMO sistema, como o modelo as copia do texto (a pagina cita cada grafia): a demonstracao as forca em URLs fixas, para a tela mostrar
# grafias diferentes do mesmo nome (como "BO Facil" e "B.O. Facil" na coleta real). `.exemplo.gov.br`: nomes e orgaos ficticios.
VARIANTES_FORCADAS_DEMO = {
    "https://ssp.sp.exemplo.gov.br/noticias/reconhecimento_facial-1": "Rosto Seguro",
    "https://ssp.sp.exemplo.gov.br/noticias/reconhecimento_facial-2": "Rosto-Seguro",
    "https://ssp.rj.exemplo.gov.br/noticias/leitura_placas-1": "Placa Atenta",
    "https://ssp.rj.exemplo.gov.br/noticias/leitura_placas-2": "P. Atenta",
    # RC23, entidades de nome_solucao fora do cadastro (cada uma mostra uma camada em /solucoes e em /achados):
    "https://ssp.ba.exemplo.gov.br/noticias/videomonitoramento_inteligente-1": "Sistema de Triagem Inteligente de Ocorrências",  # camada 2: o nome por extenso ...
    "https://ssp.ba.exemplo.gov.br/noticias/outra_ia-2": "STIO",                                                # ... e a sigla formada pelas iniciais
    "https://ssp.go.exemplo.gov.br/noticias/analise_preditiva-1": "SIPAT - Sistema Integrado de Patrulhamento",  # camada 2: formato "SIGLA - Nome"
    "https://ssp.go.exemplo.gov.br/noticias/analise_preditiva-2": "SIPAT",
    "https://ssp.pr.exemplo.gov.br/noticias/leitura_placas-1": "Placa Atenta",                                  # outra UF: nao e a solucao do cadastro do RJ
    "https://ssp.pr.exemplo.gov.br/noticias/leitura_placas-2": "PlacaAtenta",                                   # camada 3: mesma grafia sem espaco
}
# O nome aparece no TEXTO desta pagina, mas o classificador demonstrativo nao o devolve (so aparece na etapa "paginas baixadas" de /solucoes)
NOME_SO_NA_PAGINA_DEMO = {"https://ssp.pe.exemplo.gov.br/noticias/videomonitoramento_inteligente-1": "Guardião Digital"}
# O nome aparece so no resumo (snippet) de um resultado nao oficial, que nunca e baixado (etapa "resultados de busca" de /solucoes)
NOME_SO_NO_RESULTADO_DEMO = {("CE", "analise_preditiva"): "Vigia Nuvem"}


def _nome_demo(url, tec):
    """Nome fiel ao texto (a pagina o cita) em parte das URLs; nada nas demais. Nas URLs de `VARIANTES_FORCADAS_DEMO` e sempre a grafia forcada."""
    if url in VARIANTES_FORCADAS_DEMO:
        return VARIANTES_FORCADAS_DEMO[url]
    if url in NOME_SO_NA_PAGINA_DEMO:
        return ""
    return NOMES_SOLUCAO_DEMO.get(tec, "") if _h(url + "|nome", 4) == 0 else ""


# Solucoes conhecidas da DEMONSTRACAO (o painel com --demo usa esta lista, nao a real de config/solucoes_conhecidas.py). Cobrem os quatro
# vereditos de /solucoes; os nomes sao ficticios e existem nos dados da demonstracao.
SOLUCOES_CONHECIDAS_DEMO = (
    SolucaoConhecida("Rosto Seguro", "SP", apelidos=("Rosto-Seguro",),
                     observacao="Demonstração: citada na evidência de achados (duas grafias do mesmo nome)."),
    SolucaoConhecida("Placa Atenta", "RJ", apelidos=("P. Atenta",),
                     observacao="Demonstração: citada em achados; o apelido cobre a grafia abreviada."),
    SolucaoConhecida("Guardião Digital", "PE", observacao="Demonstração: a página baixada cita o nome, mas nenhum achado o cita."),
    SolucaoConhecida("Vigia Nuvem", "CE", observacao="Demonstração: só um resultado de busca cita o nome; a página nunca foi baixada."),
    SolucaoConhecida("Sentinela Norte", "AM", observacao="Demonstração: o nome não aparece em nada que a coleta trouxe."),
)


PREAMBULO = ("Notícias da Secretaria. {a}\n\nA pasta informou que o investimento segue o planejamento do exercício. "
             "O secretário destacou a integração entre as forças de segurança e a transparência das ações.\n\n")
POSFACIO = ("\n\nAs informações detalhadas constam no portal da transparência. Outras ações incluem capacitação de equipes, "
            "campanhas de prevenção e manutenção da frota. Mais detalhes em nota técnica a ser publicada.")


def _h(texto, n):
    return int(hashlib.sha1(texto.encode()).hexdigest(), 16) % n


def _reg(prov, op, **kw):
    return RegistroChamada(provedor=prov, operacao=op, parametros={}, requisitado_em=agora(), http_status=kw.pop("http_status", 200),
                           latencia_ms=kw.pop("latencia_ms", 120), **kw)


class BuscaDemo:
    nome = "demo_busca"

    def buscar(self, consulta, filtros):
        uf, tec = consulta.uf, consulta.tecnologia
        res = []
        if consulta.cidade:                                       # secretaria municipal: sempre 2 resultados oficiais
            host = f"guarda-{consulta.cidade.lower().replace(' ', '-')}.{uf.lower()}.exemplo.gov.br"
            for n in (1, 2):
                res.append(ResultadoWeb(f"https://{host}/noticias/{tec}-{n}", f"{tec.replace('_', ' ').capitalize()} na guarda municipal de {consulta.cidade}",
                                        f"A prefeitura {FRASES[tec]}.", None, n))
            return RespostaBusca(res, _reg(self.nome, "buscar", custo_usd=0.005, raw=b'{"demo": true}'))
        if uf in UFS_RICAS or (uf in UFS_MEDIAS and _h(uf + tec, 3) == 0):
            for n in (1, 2):
                res.append(ResultadoWeb(f"https://ssp.{uf.lower()}.exemplo.gov.br/noticias/{tec}-{n}",
                                        f"{FRASES[tec].split(' ', 1)[0].capitalize()} {tec.replace('_', ' ')} em {uf}",
                                        f"A secretaria {FRASES[tec]}.", "2025-0%d-1%d" % (1 + _h(uf + tec, 8), n), len(res) + 1))
            extra = NOME_SO_NO_RESULTADO_DEMO.get((uf, tec))
            res.append(ResultadoWeb(f"https://noticias-{uf.lower()}.example/materia/{tec}", f"Reportagem: {tec.replace('_', ' ')} em {uf}",
                                    f"Segundo a imprensa, {FRASES[tec]}." + (f" A reportagem cita o sistema {extra}." if extra else ""), None, len(res) + 1))
        res.append(ResultadoWeb(f"https://ssp.{uf.lower()}.exemplo.gov.br/institucional/{_h(consulta.id, 3)}", "Institucional",
                                "Conheça a estrutura da secretaria.", None, len(res) + 1))
        if _h(consulta.id, 11) == 0:
            res.append(ResultadoWeb(f"https://www.youtube.com/watch?v={_h(consulta.id, 999)}", "Vídeo institucional", "monitoramento", None, len(res) + 1))
        return RespostaBusca(res, _reg(self.nome, "buscar", custo_usd=0.005, raw=b'{"demo": true}'))


class FetcherDemo:
    nome = "demo_fetcher"

    def baixar(self, url):
        sorteio = _h(url, 20)
        if sorteio == 0:
            # das paginas que falham no download: algumas viram robots.txt (lido e proibindo, ou inacessivel), as outras HTTP 404
            motivo = _h(url + "|robots", 3)
            if motivo == 1:
                return ArquivoBaixado(url, None, "", b"", False, _reg(
                    self.nome, "baixar", http_status=None, erro="bloqueado_por_robots",
                    extras={"robots_permitido": False, "robots_status": 200, "robots_inacessivel": False, "robots_tentativas": 1}))
            if motivo == 2:
                return ArquivoBaixado(url, None, "", b"", False, _reg(
                    self.nome, "baixar", http_status=None, erro="robots_inacessivel",
                    extras={"robots_permitido": False, "robots_status": 503, "robots_inacessivel": True, "robots_tentativas": 3}))
            return ArquivoBaixado(url, 404, "text/html", b"", False, _reg(self.nome, "baixar", http_status=404, erro="HTTP 404"))
        if sorteio == 1:
            return ArquivoBaixado(url, 200, "application/zip", b"PK", False, _reg(self.nome, "baixar", raw=b"PK", raw_ext="bin"))
        if sorteio == 2:
            corpo = b"<html><body>Carregando...</body></html>"
            return ArquivoBaixado(url, 200, "text/html", corpo, False, _reg(self.nome, "baixar", raw=corpo, raw_ext="html"))
        tec = next((t for t in FRASES if t in url), None)
        uf = url.split(".")[1].upper() if "exemplo.gov.br" in url else "UF"
        frase = FRASES.get(tec, "mantém suas ações institucionais")
        nome = _nome_demo(url, tec)
        citacao = f"A ferramenta, batizada de {nome}, foi apresentada à imprensa. " if nome else ""    # o nome fica fora do trecho da evidencia
        if url in NOME_SO_NA_PAGINA_DEMO:
            citacao = f"A nota menciona ainda o sistema {NOME_SO_NA_PAGINA_DEMO[url]}, sem detalhar seu uso. "
        corpo = (PREAMBULO.format(a=f"A Secretaria de Segurança Pública do estado {frase}.") + f"Contexto: {frase}, segundo nota oficial de {uf}. "
                 + citacao + "Texto de relleno. " * 12 + POSFACIO).encode()
        return ArquivoBaixado(url, 200, "text/html", corpo, False, _reg(self.nome, "baixar", raw=corpo, raw_ext="html", latencia_ms=300 + _h(url, 900)))


class ExtratorDemo:
    def extrair(self, conteudo, content_type, url):
        if not content_type.startswith("text/"):
            return TextoExtraido("", "nenhum", False, f"tipo_nao_suportado:{content_type}")
        texto = conteudo.decode("utf-8", "replace")
        if len(texto) < 200:
            return TextoExtraido(texto, "demo", False, "texto_insuficiente")
        return TextoExtraido(texto, "demo", True)


class ClassificadorDemo:
    def __init__(self, nome="demo:modelo-a", vies=0):
        self.nome, self._vies = nome, vies

    def classificar(self, entrada, instr):
        u = entrada.url
        reg = _reg(self.nome, "classificar", raw=b'{"demo": true}', tokens_entrada=900 + _h(u, 800), tokens_saida=120 + _h(u, 200),
                   latencia_ms=900 + _h(u, 1500))
        reg.custo_usd = (reg.tokens_entrada * 0.3 + reg.tokens_saida * 2.5) / 1e6
        if _h(u, 40) == 0:
            reg.erro = "HTTP 503: modelo indisponível (demonstração)"
            return ResultadoClassificacao(False, [], False, "", reg)
        tec = next((t for t in FRASES if t in u), None)
        if tec is None or "institucional" in u:
            return ResultadoClassificacao(False, [], True, "{}", reg)
        n = _h(u + self.nome, 100)
        status = list(V.STATUS)[(_h(u, 100) + self._vies) % 100 * 6 // 100]
        trecho = f"{FRASES[tec]}"
        achados = []
        if n % 5 == 0:                                         # ~20%: o modelo parafraseou, a evidencia nao confere
            trecho = "informou que usa tecnologia de IA em diversas frentes de policiamento"
        if "nao" not in u:
            nome = _nome_demo(u, tec) or (NOME_INVENTADO_DEMO if _h(u + "|inventado", 15) == 0 else "")
            achados.append(Achado(tec, status, FORNECEDORES[n % len(FORNECEDORES)], n % 7 == 0 and "lgpd" in trecho.lower(),
                                  trecho, ("alta", "media", "baixa")[n % 3], nome_solucao=nome))
        if n % 9 == 0:                                         # alguns achados extras na mesma pagina
            outra = list(FRASES)[(list(FRASES).index(tec) + 1) % len(FRASES)]
            achados.append(Achado(outra, "apenas_citado", "", False, FRASES[outra], "baixa"))
        return ResultadoClassificacao(bool(achados), achados, True, "{}", reg)


N_ARTIGOS = 140
TEMAS = ["policiamento", "câmeras urbanas", "biometria", "análise de dados criminais", "atendimento ao cidadão", "ética e viés"]


def _titulo(n):
    return f"Estudo demonstrativo {n:03d} sobre {TEMAS[n % len(TEMAS)]}"


def _artigo(n, posicao):
    ano = 2019 + n % 8
    return ArtigoAcademico(_titulo(n), f"https://revista-{n % 9}.example/artigo/{n}", f"Autora {n % 11} et al. - Revista Exemplo, {ano}", ano,
                           f"Resumo fictício do estudo {n}: discute {TEMAS[n % len(TEMAS)]} no contexto da segurança pública.",
                           None if n % 6 == 0 else (n * 37) % 400, posicao)


class AcademicoDemo:
    """Artigos tem chance diferente de aparecer em cada termo: ha os achados por um so termo e os achados por varios."""
    nome = "demo_scholar"

    def saldo(self):
        return 200

    def buscar_pagina(self, termo, inicio, filtros):
        k = int(termo.id[1:])
        achados = [n for n in range(1, N_ARTIGOS + 1) if _h(f"{n}-{k}", 100) < 1 + (n % 6) * 2]
        pagina = achados[inicio:inicio + filtros.por_pagina]
        return PaginaAcademica([_artigo(n, i + 1) for i, n in enumerate(pagina)], len(achados),
                               _reg(self.nome, "buscar_pagina", raw=b'{"demo": true}', latencia_ms=1500 + _h(termo.id, 1500)))


def _literatura(repo, bruto, rnd):
    run = _run(repo, "academico")
    repo.registrar_saldo(run, "demo_scholar", "inicio", 200)
    busca_academica.executar(repo, bruto, AcademicoDemo(), run, C.TERMOS, C.FILTROS_ACADEMICOS, 3, [], 0)
    feitas = repo.conn.execute("SELECT COUNT(*) FROM chamadas WHERE run_id=? AND sucesso=1", (run,)).fetchone()[0]
    repo.registrar_saldo(run, "demo_scholar", "fim", 200 - feitas)
    repo.finalizar_execucao(run, "concluida")
    # buscas manuais (SBC OpenLib fica sem informar de proposito: o PRISMA mostra o que falta)
    cols = ["base", "termo_id", "string_base", "filtros", "n_resultados", "n_apos_filtro", "n_selecionados", "data_busca", "observacao"]
    repo.importar_buscas_manuais(pd.DataFrame([("IEEE", "T01", '"reconhecimento facial"', "2019-2026", 212, 80, 12, "2026-10-02", None),
                                               ("IEEE", "T03", '"biometria facial"', "2019-2026", 95, 40, 6, "2026-10-02", None),
                                               ("ACM", "T01", '"reconhecimento facial"', "2019-2026", 150, 60, 9, "2026-10-03", None),
                                               ("Scopus", "T05", '"videomonitoramento inteligente"', "", 41, 41, 5, "2026-10-04", "sem filtro")], columns=cols))
    novos = [(b, "T01" if i % 2 else "T05", _titulo(n), f"https://revista-{n % 9}.example/artigo/{n}", f"Autora {n % 11} et al.", 2019 + n % 8, None, i + 1, "2026-10-02")
             for i, (b, n) in enumerate([("IEEE", 3), ("IEEE", 10), ("ACM", 17), ("ACM", 24), ("Scopus", 31), ("Scopus", 38)])]
    novos += [(b, "T01", f"Estudo manual {i} (fictício, só nas bases)", f"https://base-{b.lower()}.example/{i}", "Autor Demo et al.", 2023, 5 * i, i + 1, "2026-10-03")
              for i, b in enumerate(["IEEE", "ACM", "Scopus", "ACM"], start=1)]
    repo.importar_artigos_manuais(pd.DataFrame(novos, columns=["base", "termo_id", "titulo", "link", "autores_publicacao", "ano", "citacoes", "posicao", "data_busca"]))
    # triagem em andamento: ~45% dos artigos decididos, alguns incluidos ja com texto completo
    ids = [r[0] for r in repo.conn.execute("""SELECT a.artigo_id FROM r_artigos a ORDER BY (SELECT COUNT(*) FROM r_ocorrencias o WHERE o.artigo_id=a.artigo_id) DESC,
                                              COALESCE(a.citacoes, 0) DESC, a.artigo_id""")]
    motivos = ["fora do escopo (não trata de segurança pública)", "sem IA", "texto indisponível", "duplicata de outro estudo"]
    for i in ids[: int(len(ids) * 0.45)]:
        if rnd.random() < 0.5:
            repo.registrar_triagem(i, "incluir", "Revisora Demo", None, "IEEE" if rnd.random() < 0.3 else None, None)
            if rnd.random() < 0.5:
                repo.registrar_triagem(i, rnd.choice(["incluir", "excluir"]), "Revisora Demo", rnd.choice(motivos), etapa="texto_completo")
        else:
            repo.registrar_triagem(i, "excluir", "Revisora Demo", rnd.choice(motivos))


def _params():
    return ParametrosClassificacao(
        versao_prompt="v3-demo", sistema="(demonstração)", usuario_template="{nome} {uf} {url} {titulo} {origem} {texto}",
        esquema=esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA),
        tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS),
        palavras_tecnologia={k: palavras_chave_tecnologia(v) for k, v in V.TECNOLOGIAS.items()})


def _run(repo, comando, origem=None):
    snap = S.snapshot_config()
    return repo.iniciar_execucao(comando, snap["hash"], snap["json"], "demo", run_origem=origem)


def _reclassificar(repo, bruto, run_b, run_c):
    """Le de novo, com outra versao do prompt e na mesma execucao, as ultimas `RECLASSIFICADAS_DEMO` paginas classificadas com texto completo:
    a classificacao nova vira a vigente e a antiga (que ninguem verificou) abre com o aviso "substituido por uma classificacao mais recente".
    Fica na execucao `run_c` (e nao numa execucao nova) para a demonstracao continuar com so duas execucoes de classificacao."""
    metrica = lambda: (repo.conn.execute("SELECT valor FROM metricas_run WHERE run_id=? AND chave='classificacao_nome_solucao_descartado'",
                                         (run_c,)).fetchone() or [0])[0]
    antes = metrica()
    alvos = [r[0] for r in repo.conn.execute("""SELECT DISTINCT k.url_id FROM classificacoes k JOIN achados a ON a.classificacao_id=k.classificacao_id
             WHERE k.run_id=? AND k.origem_texto='pagina' ORDER BY k.url_id DESC LIMIT ?""", (run_c, RECLASSIFICADAS_DEMO))]
    classificacao.executar(repo, bruto, ClassificadorDemo(), run_c, run_b, replace(_params(), versao_prompt="v4-demo"), C.UFS, [], 0, urls=alvos)
    repo.registrar_metrica(run_c, "classificacao_nome_solucao_descartado", antes + metrica())     # a segunda leitura nao apaga a conta da primeira
    repo.confirmar()


def construir(pasta_dados=None):
    """Recria `demo.db` e `raw_demo/` do zero (sempre os mesmos dados) e devolve o caminho do banco."""
    pasta = Path(pasta_dados or S.DATA_DIR)
    banco, raw = pasta / "demo.db", pasta / "raw_demo"
    for alvo in (banco, Path(str(banco) + "-wal"), Path(str(banco) + "-shm")):
        alvo.unlink(missing_ok=True)
    shutil.rmtree(raw, ignore_errors=True)
    logging.disable(logging.CRITICAL)
    try:
        repo, bruto = RepositorioSQLite(banco), BrutoLocal(raw)
        consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS, MUNICIPIOS_DEMO, MODELOS_MUNICIPAIS_DEMO)
        run_a = _run(repo, "busca-web")
        busca_web.executar(repo, bruto, BuscaDemo(), run_a, consultas, C.PERFIS_BUSCA_WEB, [], 0)
        repo.finalizar_execucao(run_a, "concluida")
        run_b = _run(repo, "baixar", run_a)
        download.executar(repo, bruto, FetcherDemo(), ExtratorDemo(), run_b, run_a, C.POLITICA_DOWNLOAD, [], 0)
        repo.finalizar_execucao(run_b, "concluida")
        run_c = _run(repo, "classificar", run_b)
        classificacao.executar(repo, bruto, ClassificadorDemo(), run_c, run_b, _params(), C.UFS, [], 0)
        _reclassificar(repo, bruto, run_b, run_c)
        repo.finalizar_execucao(run_c, "concluida")
        # um segundo modelo sobre as mesmas paginas (comparacao): fora do relatorio para nao contar em dobro
        run_d = _run(repo, "classificar", run_b)
        classificacao.executar(repo, bruto, ClassificadorDemo("demo:modelo-b", 3), run_d, run_b, _params(), C.UFS, [], 0, limite=15)
        repo.finalizar_execucao(run_d, "concluida")
        repo.definir_no_relatorio(run_d, False, "comparação de classificadores (demonstração)")
        run_e = _run(repo, "busca-web")                       # uma execucao que parou no meio
        busca_web.executar(repo, bruto, BuscaDemo(), run_e, consultas[:7], C.PERFIS_BUSCA_WEB, [], 0)
        repo.finalizar_execucao(run_e, "interrompida")
        repo.definir_no_relatorio(run_e, False, "execução interrompida (demonstração)")
        run_f = _run(repo, "busca-web")
        repo.finalizar_execucao(run_f, "falhou")
        repo.definir_no_relatorio(run_f, False, "execução com falha (demonstração)")
        _literatura(repo, bruto, random.Random(SEMENTE + 1))
        # verificacao humana de parte dos achados, para a revisao ja comecar andando
        permitidos = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
        rnd = random.Random(SEMENTE)
        ids = [r[0] for r in repo.conn.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k
                 ON k.classificacao_id=a.classificacao_id WHERE k.run_id=?
                 AND k.classificacao_id IN (SELECT classificacao_id FROM r_classificacoes) ORDER BY a.achado_id""", (run_c,))]
        for i in ids:
            if rnd.random() < 0.3:
                r = repo.conn.execute("SELECT status_reportado, evidencia_confere FROM achados WHERE achado_id=?", (i,)).fetchone()
                final = "descartado" if not r["evidencia_confere"] and rnd.random() < 0.7 else r["status_reportado"]
                repo.verificar_achado(i, final, "Revisora Demo", None, permitidos)
        repo.fechar()
    finally:
        logging.disable(logging.NOTSET)
    return banco


# ============================== banco grande, so para medir desempenho ==============================
GRANDE = {"resultados": 3000, "classificacoes": 1000, "achados": 2000, "artigos": 1500, "textos_reais": 24}


def _inserir_lote(conn, tabela, colunas, linhas):
    conn.executemany(f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})", linhas)


def construir_grande(pasta_dados=None):
    """Recria `demo_grande.db` e `raw_demo_grande/` (mesmos dados sempre) e devolve o caminho do banco.

    Banco ficticio em escala de uma coleta completa (cerca de 3.000 resultados web, 1.000 classificacoes, 2.000 achados,
    1.500 artigos e mais de 2.000 chamadas), gravado em lote direto no SQLite: existe so para medir o tempo das paginas.
    Nunca toca `busca.db`, `simulado.db` nem `demo.db`. Hosts ficticios: `*.exemplo.gov.br` e `*.example`."""
    pasta = Path(pasta_dados or S.DATA_DIR)
    banco, raw = pasta / "demo_grande.db", pasta / "raw_demo_grande"
    for alvo in (banco, Path(str(banco) + "-wal"), Path(str(banco) + "-shm")):
        alvo.unlink(missing_ok=True)
    shutil.rmtree(raw, ignore_errors=True)
    RepositorioSQLite(banco).fechar()                              # aplica o schema
    bruto, rnd = BrutoLocal(raw), random.Random(SEMENTE + 7)
    snap = S.snapshot_config()
    conn = sqlite3.connect(banco)
    try:
        _povoar_grande(conn, bruto, rnd, snap)
        conn.commit()
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()
    return banco


def _povoar_grande(conn, bruto, rnd, snap):
    tecs, ufs, termos = list(V.TECNOLOGIAS), list(C.UFS), [t.id for t in C.TERMOS]
    inicio = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)

    def quando(n):
        return (inicio + timedelta(seconds=7 * n)).isoformat(timespec="seconds")

    runs = {k: f"20261001_{9 + i:02d}0000_g{i:05d}" for i, k in enumerate(["web", "baixar", "classif", "classif_b", "acad", "parada", "falha"])}
    comandos = {"web": "busca-web", "baixar": "baixar", "classif": "classificar", "classif_b": "classificar", "acad": "academico",
                "parada": "busca-web", "falha": "busca-web"}
    status = {"parada": "interrompida", "falha": "falhou"}
    cols_exec = ["run_id", "iniciado_em", "finalizado_em", "comando", "config_hash", "config_json", "commit_git", "status", "metricas_json",
                 "run_origem", "no_relatorio", "motivo_exclusao"]
    origem = {"baixar": "web", "classif": "baixar", "classif_b": "baixar"}
    fora = {"classif_b": "comparação de classificadores (demonstração)", "parada": "execução interrompida (demonstração)",
            "falha": "execução com falha (demonstração)"}
    _inserir_lote(conn, "execucoes", cols_exec, [
        (runs[k], quando(i * 1000), quando(i * 1000 + 600), comandos[k], snap["hash"], snap["json"], "demo", status.get(k, "concluida"),
         json.dumps({"itens": 1000 + i}), runs.get(origem.get(k)), 0 if k in fora else 1, fora.get(k)) for i, k in enumerate(runs)])

    # ---- chamadas (id explicito para ligar as demais tabelas) ----
    cols_ch = ["chamada_id", "run_id", "etapa", "provedor", "operacao", "alvo_tipo", "alvo_id", "uf", "pagina", "parametros_json",
               "chave_idempotencia", "requisitado_em", "http_status", "sucesso", "tentativas", "latencia_ms", "total_reportado",
               "n_retornados", "n_novos", "tokens_entrada", "tokens_saida", "custo_usd", "erro", "raw_path", "raw_sha256", "extras_json"]
    chamadas, proximo = [], [1]

    def chamada(run, etapa, prov, op, tipo, alvo, uf=None, pagina=None, ok=True, erro=None, **kw):
        cid = proximo[0]
        proximo[0] += 1
        chamadas.append((cid, runs[run], etapa, prov, op, tipo, alvo, uf, pagina, "{}", f"{etapa}:{alvo}:{pagina}:{cid}", quando(cid), 200 if ok else 503,
                         int(ok), 1, 100 + (cid * 37) % 2400, kw.get("total"), kw.get("n"), kw.get("novos"), kw.get("te"), kw.get("ts"),
                         kw.get("custo"), erro, kw.get("raw"), kw.get("sha"), "{}"))
        return cid

    # busca web: 27 UFs x tecnologias do vocabulario (seis, com atendimento_virtual)
    consultas = [(f"M01-{uf}-{t}", uf, t) for uf in ufs for t in tecs]
    cham_web = {c[0]: chamada("web", "busca_web", "demo_busca", "buscar", "consulta_web", c[0], c[1], custo=0.005, n=22) for c in consultas}
    bruto_ids = []
    for cid, run, etapa, *_ in list(chamadas)[:12]:                  # alguns arquivos brutos reais, para a tela de uma chamada
        caminho, sha = bruto.salvar("web", runs["web"], f"c{cid}", json.dumps({"demo": True, "chamada": cid}).encode(), "json")
        chamadas[cid - 1] = chamadas[cid - 1][:23] + (caminho, sha, "{}")
        bruto_ids.append(cid)

    # urls e resultados (3.000, com repeticao de URLs entre consultas)
    n_urls = 2400
    urls = []
    for i in range(1, n_urls + 1):
        oficial = i % 5 < 2
        uf_u = ufs[i % len(ufs)].lower()
        host = f"ssp.{uf_u}.exemplo.gov.br" if oficial else f"noticias-{i % 90}.example"
        u = f"https://{host}/materia/{i}"
        urls.append((i, u, u, host, int(oficial), runs["web"], quando(i)))
    _inserir_lote(conn, "urls", ["url_id", "url_normalizada", "url_original", "dominio", "fonte_oficial", "primeira_vez_run", "primeira_vez_em"], urls)
    resultados, pares = [], {}
    for n in range(GRANDE["resultados"]):
        cons = consultas[n % len(consultas)]
        url_id = 1 + (n * 7 + rnd.randrange(n_urls)) % n_urls
        tec = cons[2]
        resultados.append((cham_web[cons[0]], runs["web"], cons[0], cons[1], tec, "oficial", url_id, 1 + n // len(consultas),
                           f"{tec.replace('_', ' ').capitalize()} em {cons[1]} (matéria {n})", f"A secretaria {FRASES[tec]}.",
                           None, None if n % 25 else "Vila Modelo"))
        pares.setdefault((url_id, cons[1]), tec)
    _inserir_lote(conn, "resultados_web", ["chamada_id", "run_id", "consulta_id", "uf", "tecnologia", "perfil", "url_id", "posicao", "titulo",
                                           "snippet", "data_pub", "cidade"], resultados)

    # selecao (todas as decisoes) e paginas das selecionadas
    selecionadas, selecao = [], []
    for k, ((url_id, uf), tec) in enumerate(sorted(pares.items())):
        oficial = urls[url_id - 1][4]
        sel = bool(oficial) and len(selecionadas) < GRANDE["classificacoes"] and k % 2 == 0
        if sel:
            selecionadas.append((url_id, uf, tec))
        motivo = None if sel else (("dominio_excluido" if k % 7 == 0 else "nao_oficial") if not oficial
                                   else ("prefiltro_palavras" if k % 3 else "limite_por_uf"))
        selecao.append((runs["baixar"], url_id, uf, int(sel), motivo))
    _inserir_lote(conn, "selecao_download", ["run_id", "url_id", "uf", "selecionada", "motivo"], selecao)
    while len(selecionadas) < GRANDE["classificacoes"]:                 # garante o numero pedido de classificacoes
        url_id = 1 + len(selecionadas) % n_urls
        selecionadas.append((url_id, ufs[len(selecionadas) % len(ufs)], tecs[len(selecionadas) % len(tecs)]))
    selecionadas = selecionadas[:GRANDE["classificacoes"]]

    paginas, cham_pag, textos_reais = [], {}, {}
    for i, (url_id, uf, tec) in enumerate(selecionadas, start=1):
        sorteio = i % 20
        ok = sorteio >= 3
        cid = chamada("baixar", "download", "demo_fetcher", "baixar", "url", str(url_id), uf, ok=sorteio != 0, erro=None if sorteio else "HTTP 404", n=4000)
        texto_path = None
        if ok and len(textos_reais) < GRANDE["textos_reais"]:
            corpo = (PREAMBULO.format(a=f"A Secretaria do estado {FRASES[tec]}.") + f"Contexto: {FRASES[tec]}, segundo nota oficial de {uf}. "
                     + "Texto de preenchimento para dar volume à página. " * 400 + POSFACIO)
            texto_path, _ = bruto.salvar("texto", runs["baixar"], f"p{i}", corpo.encode(), "txt")
            textos_reais[i] = corpo
        paginas.append((i, runs["baixar"], url_id, cid, urls[url_id - 1][1], 200 if sorteio else 404, "text/html", 4000, 0, texto_path,
                        4000 if ok else 0, "demo", int(ok), None if ok else ("texto_insuficiente" if sorteio == 1 else "tipo_nao_suportado:application/zip" if sorteio == 2 else None),
                        urls[url_id - 1][3], urls[url_id - 1][4]))
        cham_pag[i] = cid
    _inserir_lote(conn, "paginas", ["pagina_id", "run_id", "url_id", "chamada_id", "url_final", "http_status", "content_type", "n_bytes", "truncado",
                                    "texto_path", "n_chars", "extrator", "extracao_ok", "motivo_falha", "dominio_final", "fonte_oficial_final"], paginas)

    # classificacoes e achados
    cls, achados = [], []
    for i, (url_id, uf, tec) in enumerate(selecionadas, start=1):
        com_texto = (i % 20) >= 3
        origem_t = "pagina" if com_texto else "snippet"
        cid = chamada("classif", "classificacao", "demo:modelo-a", "classificar", "item", f"{url_id}:{uf}", uf, ok=i % 40 != 0,
                      erro=None if i % 40 else "HTTP 503: modelo indisponível (demonstração)", te=900 + i % 800, ts=120 + i % 200,
                      custo=(900 + i % 800) * 0.3e-6 + (120 + i % 200) * 2.5e-6)
        n_ach = [0, 2, 2, 3, 2, 2, 3, 2][i % 8]
        cls.append((i, cid, runs["classif"], url_id, i, uf, origem_t, 0, 3000, "demo:modelo-a", None if i % 30 else "Vila Modelo", "v3-demo",
                    int(n_ach > 0), 1, n_ach, 0, "{}"))
        for j in range(n_ach):
            t = tecs[(tecs.index(tec) + j) % len(tecs)]
            conf = "baixa" if origem_t == "snippet" else ("alta", "media", "baixa")[(i + j) % 3]
            confere = int((i + j) % 5 != 0)
            if i in textos_reais:
                evidencia = FRASES[tec] if confere and t == tec else "informou que usa tecnologia de IA em diversas frentes"
            else:
                evidencia = FRASES[t]
            ver = int((i * 3 + j) % 10 < 3)
            achados.append((i, uf, t, list(V.STATUS)[(i + j) % 6], FORNECEDORES[(i + j) % 5], 0, evidencia, confere, conf, conf, int(confere), 0,
                            ver, list(V.STATUS)[(i + j) % 6] if ver else None, "Revisora Demo" if ver else None, quando(i) if ver else None))
    _inserir_lote(conn, "classificacoes", ["classificacao_id", "chamada_id", "run_id", "url_id", "pagina_id", "uf", "origem_texto", "texto_truncado",
                                           "n_chars_enviados", "classificador", "cidade", "prompt_versao", "relevante", "json_valido", "n_achados",
                                           "n_achados_invalidos", "resposta_texto"], cls)
    _inserir_lote(conn, "achados", ["classificacao_id", "uf", "tecnologia", "status_reportado", "fornecedor", "menciona_lgpd", "evidencia",
                                    "evidencia_confere", "confianca", "confianca_original", "evidencia_cita_tecnologia", "evidencia_cita_lgpd",
                                    "verificado", "status_final", "verificado_por", "verificado_em"], achados)

    # literatura: 1.500 artigos, ocorrencias do Scholar e das bases manuais, triagem
    arts = [(n, hashlib.sha1(f"grande-{n}".encode()).hexdigest(), _titulo(n), f"https://revista-{n % 9}.example/artigo/{n}",
             f"Autora {n % 11} et al. - Revista Exemplo, {2019 + n % 8}", 2019 + n % 8, f"Resumo fictício do estudo {n}.",
             None if n % 6 == 0 else (n * 37) % 400, runs["acad"], quando(n)) for n in range(1, GRANDE["artigos"] + 1)]
    _inserir_lote(conn, "artigos", ["artigo_id", "chave_dedup", "titulo", "link", "autores_publicacao", "ano", "snippet", "citacoes",
                                    "primeira_vez_run", "primeira_vez_em"], arts)
    cham_ac = {t: [chamada("acad", "busca_academica", "demo_scholar", "buscar_pagina", "termo", t, pagina=p, total=60, n=20, novos=10) for p in (1, 2, 3)]
               for t in termos}
    ocorr = []
    for n in range(1, GRANDE["artigos"] + 1):
        for k in range(1 + n % 3):                                      # 1 a 3 termos por artigo: ha sobreposicao entre termos
            t = termos[(n * 5 + k * 13) % len(termos)]
            ocorr.append((cham_ac[t][n % 3], n, t, runs["acad"], 1 + n % 20, None if n % 6 == 0 else (n * 37) % 400))
    _inserir_lote(conn, "ocorrencias", ["chamada_id", "artigo_id", "termo_id", "run_id", "posicao", "citacoes_no_momento"], ocorr)
    bases = list(C.BASES_MANUAIS)
    _inserir_lote(conn, "ocorrencias_manuais", ["artigo_id", "base", "termo_id", "data_busca", "posicao", "importado_em"],
                  [(n, bases[n % 4], termos[n % 8], "2026-10-02", n, quando(n)) for n in range(1, 301)])
    _inserir_lote(conn, "buscas_manuais", ["base", "termo_id", "string_base", "filtros", "n_resultados", "n_apos_filtro", "n_selecionados", "data_busca"],
                  [(bases[i % 4], termos[i % 8], f'"{termos[i % 8]}"', "2019-2026", 100 + i, 50 + i, 10 + i, "2026-10-02") for i in range(12)])
    triagem = []
    for n in range(1, GRANDE["artigos"] + 1):
        d = "pendente" if n % 100 >= 45 else ("incluir" if n % 2 else "excluir")
        tf = "incluir" if d == "incluir" and n % 4 == 1 else None
        triagem.append((n, d, None if d != "excluir" else "fora do escopo (não trata de segurança pública)", None, None,
                        "Revisora Demo" if d != "pendente" else None, quando(n) if d != "pendente" else None, tf, None))
    _inserir_lote(conn, "triagem", ["artigo_id", "decisao", "motivo", "confirmado_em_base", "link_confirmado", "revisor", "revisado_em",
                                    "decisao_texto_completo", "motivo_texto_completo"], triagem)
    _inserir_lote(conn, "triagem_revisoes", ["artigo_id", "revisor", "decisao", "motivo", "importado_em", "independente"],
                  [(n, r, "incluir" if (n + k) % 3 else "excluir", None, quando(n), 1) for n in range(1, 401) for k, r in enumerate(["Revisora A", "Revisora B"])])
    _inserir_lote(conn, "saldos", ["run_id", "provedor", "momento", "valor", "registrado_em"],
                  [(runs["web"], "demo_busca", "inicio", 1000, quando(1)), (runs["web"], "demo_busca", "fim", 1000 - 135 * 0.005 * 200, quando(2))])
    _inserir_lote(conn, "chamadas", cols_ch, chamadas)
