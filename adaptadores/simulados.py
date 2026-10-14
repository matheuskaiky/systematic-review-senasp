from dominio.modelos import (RegistroChamada, ResultadoWeb, RespostaBusca, ArtigoAcademico, PaginaAcademica,
                             ArquivoBaixado, TextoExtraido, Achado, ResultadoClassificacao)
from infra.util import agora

# Sample text kept in Portuguese on purpose: the simulated classifier matches "reconhecimento facial".
_TEXTO = ("A Secretaria de Segurança Pública implantou reconhecimento facial nas câmeras da capital "
          "em 2024, com contrato firmado com empresa de tecnologia e atendimento à LGPD.")


def _reg(provedor, op, **kw):
    return RegistroChamada(provedor=provedor, operacao=op, parametros={}, requisitado_em=agora(),
                           http_status=200, latencia_ms=1, **kw)


class BuscaSimulada:
    nome = "simulado"
    def buscar(self, consulta, filtros):
        res = [ResultadoWeb(f"https://exemplo.gov.br/{consulta.uf.lower()}/{n}?utm_source=x",
                            f"Reconhecimento facial {consulta.uf} {n}",
                            "câmeras com reconhecimento facial", None, n) for n in range(1, 4)]
        return RespostaBusca(res, _reg(self.nome, "buscar", raw=b'{"simulado": true}'))


class AcademicoSimulado:
    nome = "simulado"
    def saldo(self): return 999
    def buscar_pagina(self, termo, inicio, filtros):
        arts = [ArtigoAcademico(f"Artigo simulado {termo.id} {inicio + n}", None, "Autor - Revista, 2023",
                                2023, "resumo", n, inicio + n) for n in range(3)]
        return PaginaAcademica(arts, 3, _reg(self.nome, "buscar_pagina", raw=b'{"simulado": true}'))


class FetcherSimulado:
    nome = "simulado"
    def baixar(self, url):
        reg = _reg(self.nome, "baixar", raw=_TEXTO.encode(), raw_ext="html")
        return ArquivoBaixado(url, 200, "text/html", _TEXTO.encode(), False, reg)


class ExtratorSimulado:
    def extrair(self, conteudo, content_type, url):
        return TextoExtraido(conteudo.decode(), "simulado", True)


class ClassificadorSimulado:
    nome = "simulado"
    def classificar(self, entrada, instr):
        reg = _reg(self.nome, "classificar", raw=b'{"simulado": true}', tokens_entrada=100, tokens_saida=20, custo_usd=0.0)
        if "reconhecimento facial" in entrada.texto:
            trecho = "implantou reconhecimento facial nas câmeras da capital"
            a = Achado("reconhecimento_facial", "em_uso", "", True, trecho, "alta")
            return ResultadoClassificacao(True, [a], True, "{}", reg)
        return ResultadoClassificacao(False, [], True, "{}", reg)


POR_PORTA = {"busca_web": BuscaSimulada, "academico": AcademicoSimulado, "fetcher": FetcherSimulado,
             "extrator": ExtratorSimulado, "classificador": ClassificadorSimulado}
