"""Banco de demonstracao do painel: dados FICTICIOS, gravados pelas mesmas etapas do pipeline com adaptadores falsos.
Nunca toca `busca.db` nem `simulado.db`. Hosts ficticios: `*.exemplo.gov.br` (oficial) e `*.example` (nao oficial).
Fica na raiz, como `composicao.py`: liga `aplicacao/` a `adaptadores/`, o que o painel proprio nao pode fazer."""
import hashlib
import logging
import random
import shutil
from dataclasses import replace
from pathlib import Path

import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_web, classificacao, download
from config import consultas as C, vocabulario as V
from dominio.esquemas import esquema_classificacao
from dominio.modelos import (Achado, ArquivoBaixado, ParametrosClassificacao, RegistroChamada, ResultadoClassificacao,
                             ResultadoWeb, RespostaBusca, TextoExtraido)
from dominio.servicos import gerar_consultas_web, palavras_chave_tecnologia
from infra.util import agora

SEMENTE = 2026
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
}
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
        if uf in UFS_RICAS or (uf in UFS_MEDIAS and _h(uf + tec, 3) == 0):
            for n in (1, 2):
                res.append(ResultadoWeb(f"https://ssp.{uf.lower()}.exemplo.gov.br/noticias/{tec}-{n}",
                                        f"{FRASES[tec].split(' ', 1)[0].capitalize()} {tec.replace('_', ' ')} em {uf}",
                                        f"A secretaria {FRASES[tec]}.", "2025-0%d-1%d" % (1 + _h(uf + tec, 8), n), len(res) + 1))
            res.append(ResultadoWeb(f"https://noticias-{uf.lower()}.example/materia/{tec}", f"Reportagem: {tec.replace('_', ' ')} em {uf}",
                                    f"Segundo a imprensa, {FRASES[tec]}.", None, len(res) + 1))
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
            return ArquivoBaixado(url, 404, "text/html", b"", False, _reg(self.nome, "baixar", http_status=404, erro="HTTP 404"))
        if sorteio == 1:
            return ArquivoBaixado(url, 200, "application/zip", b"PK", False, _reg(self.nome, "baixar", raw=b"PK", raw_ext="bin"))
        if sorteio == 2:
            corpo = b"<html><body>Carregando...</body></html>"
            return ArquivoBaixado(url, 200, "text/html", corpo, False, _reg(self.nome, "baixar", raw=corpo, raw_ext="html"))
        tec = next((t for t in FRASES if t in url), None)
        uf = url.split(".")[1].upper() if "exemplo.gov.br" in url else "UF"
        frase = FRASES.get(tec, "mantém suas ações institucionais")
        corpo = (PREAMBULO.format(a=f"A Secretaria de Segurança Pública do estado {frase}.") + f"Contexto: {frase}, segundo nota oficial de {uf}. "
                 + "Texto de relleno. " * 12 + POSFACIO).encode()
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
            achados.append(Achado(tec, status, FORNECEDORES[n % len(FORNECEDORES)], n % 7 == 0 and "lgpd" in trecho.lower(),
                                  trecho, ("alta", "media", "baixa")[n % 3]))
        if n % 9 == 0:                                         # alguns achados extras na mesma pagina
            outra = list(FRASES)[(list(FRASES).index(tec) + 1) % len(FRASES)]
            achados.append(Achado(outra, "apenas_citado", "", False, FRASES[outra], "baixa"))
        return ResultadoClassificacao(bool(achados), achados, True, "{}", reg)


def _params():
    return ParametrosClassificacao(
        versao_prompt="v3-demo", sistema="(demonstração)", usuario_template="{nome} {uf} {url} {titulo} {origem} {texto}",
        esquema=esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA),
        tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS),
        palavras_tecnologia={k: palavras_chave_tecnologia(v) for k, v in V.TECNOLOGIAS.items()})


def _run(repo, comando, origem=None):
    snap = S.snapshot_config()
    return repo.iniciar_execucao(comando, snap["hash"], snap["json"], "demo", run_origem=origem)


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
        consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS)
        run_a = _run(repo, "busca-web")
        busca_web.executar(repo, bruto, BuscaDemo(), run_a, consultas, C.PERFIS_BUSCA_WEB, [], 0)
        repo.finalizar_execucao(run_a, "concluida")
        run_b = _run(repo, "baixar", run_a)
        download.executar(repo, bruto, FetcherDemo(), ExtratorDemo(), run_b, run_a, C.POLITICA_DOWNLOAD, [], 0)
        repo.finalizar_execucao(run_b, "concluida")
        run_c = _run(repo, "classificar", run_b)
        classificacao.executar(repo, bruto, ClassificadorDemo(), run_c, run_b, _params(), C.UFS, [], 0)
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
        # verificacao humana de parte dos achados, para a revisao ja comecar andando
        permitidos = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
        rnd = random.Random(SEMENTE)
        ids = [r[0] for r in repo.conn.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k
                 ON k.classificacao_id=a.classificacao_id WHERE k.run_id=? ORDER BY a.achado_id""", (run_c,))]
        for i in ids:
            if rnd.random() < 0.3:
                r = repo.conn.execute("SELECT status_reportado, evidencia_confere FROM achados WHERE achado_id=?", (i,)).fetchone()
                final = "descartado" if not r["evidencia_confere"] and rnd.random() < 0.7 else r["status_reportado"]
                repo.verificar_achado(i, final, "Revisora Demo", None, permitidos)
        repo.fechar()
    finally:
        logging.disable(logging.NOTSET)
    return banco
