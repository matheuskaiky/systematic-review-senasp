import hashlib
import json
from dominio.modelos import (RegistroChamada, ResultadoWeb, RespostaBusca, ArtigoAcademico, PaginaAcademica,
                             ArquivoBaixado, TextoExtraido, Achado, ResultadoClassificacao, ResultadoTriagemLote)
from dominio.triagem_escopo import chave_item
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


class TriadorSimulado:
    """Triador deterministico que obedece ao esquema, com uma mistura de status e categorias (quem decide e o hash da
    chave do item). Serve ao `--simulado` e aos testes. Para exercitar as conferencias:
    `omitir` (chaves de item que a resposta deixa de devolver), `termo_ruim` (devolve um termo fora da lista nos itens
    em quarentena ou excluidos), `falhar_chamadas` (numeros das chamadas, a partir de 1, que falham com HTTP 500),
    `truncar_chamadas` (idem, mas como MAX_TOKENS), `cota_diaria_chamadas` (idem, mas como cota diaria esgotada: HTTP 429 com a marca
    `cota_diaria_esgotada`), `json_invalido` (resposta que nao e JSON) e `custo_por_chamada`."""
    nome = "simulado"

    def __init__(self, omitir=(), termo_ruim=False, falhar_chamadas=(), truncar_chamadas=(), json_invalido=False,
                 custo_por_chamada=0.0, cota_diaria_chamadas=()):
        self.omitir, self.termo_ruim, self.json_invalido = set(omitir), termo_ruim, json_invalido
        self.falhar_chamadas, self.truncar_chamadas = set(falhar_chamadas), set(truncar_chamadas)
        self.cota_diaria_chamadas = set(cota_diaria_chamadas)
        self.custo_por_chamada, self.chamadas = custo_por_chamada, 0

    @staticmethod
    def _veredito(item):
        h = int(hashlib.sha1(chave_item(item).encode()).hexdigest()[:8], 16) % 10
        if h < 4:
            return "elegivel", "media" if h == 0 else "alta", None
        if h < 7:
            return "quarentena", "baixa" if h == 4 else "media", ("AMBIGUIDADE_LEXICAL" if h == 5 else "SEM_IA_OU_TECNOLOGIA")
        if h == 7:
            return "excluido", "media", "FORA_SEGURANCA_PUBLICA"        # sera rebaixado pela regra de seguranca
        if h == 8:
            return "excluido", "alta", "FORA_SEGURANCA_PUBLICA"
        return "quarentena", "media", "FORA_DO_RECORTE_GEOGRAFICO"

    def _objeto(self, item):
        status, conf, cat = self._veredito(item)
        termos = item.get("termos") or []
        palavras = [p for p in (item.get("titulo") or "").split() if len(p) >= 4 and p.isalpha()]
        ruido = status != "elegivel"
        return {"id": chave_item(item), "status": status, "confianca": conf, "categoria_motivo": cat or "NENHUMA",
                "justificativa": "Avaliação simulada, sem leitura do conteúdo.",
                "termo_gerador_ruido": ("termo que nao esta na lista" if self.termo_ruim else termos[0]) if ruido and termos else "",
                "sinal_negativo": palavras[0] if ruido and palavras else "",
                "dominio_tematico": "seguranca_publica" if status == "elegivel" else "outro",
                "escopo_geografico": "internacional" if cat == "FORA_DO_RECORTE_GEOGRAFICO" else "brasil",
                "tipo_documento": "artigo_periodico" if item["fonte"] == "artigo" else "noticia_pagina_institucional"}

    def triar(self, itens, instr):
        self.chamadas += 1
        n_in = len(instr.usuario) // 3 + 100
        if self.chamadas in self.cota_diaria_chamadas:
            reg = _reg(self.nome, "triar_escopo", raw=b'{"error": {"code": 429}}')
            reg.erro, reg.http_status = "HTTP 429", 429
            reg.extras.update({"cota_diaria_esgotada": True, "cota_renova_em_s": 3600.0})
            return ResultadoTriagemLote("", reg)
        if self.chamadas in self.falhar_chamadas:
            reg = _reg(self.nome, "triar_escopo", raw=b'{"simulado": true}', tokens_entrada=n_in, tokens_saida=0,
                       custo_usd=self.custo_por_chamada)
            reg.erro, reg.http_status = "HTTP 500: falha simulada", 500
            return ResultadoTriagemLote("", reg)
        objetos = [self._objeto(i) for i in itens if chave_item(i) not in self.omitir]
        texto = "isto nao e json" if self.json_invalido else json.dumps({"itens": objetos}, ensure_ascii=False)
        reg = _reg(self.nome, "triar_escopo", raw=texto.encode(), tokens_entrada=n_in,
                   tokens_saida=len(texto) // 3, custo_usd=self.custo_por_chamada)
        if self.chamadas in self.truncar_chamadas:
            reg.erro = "resposta_truncada: MAX_TOKENS"
        return ResultadoTriagemLote(texto, reg)


POR_PORTA = {"busca_web": BuscaSimulada, "academico": AcademicoSimulado, "fetcher": FetcherSimulado,
             "extrator": ExtratorSimulado, "classificador": ClassificadorSimulado,
             "triador": TriadorSimulado}
