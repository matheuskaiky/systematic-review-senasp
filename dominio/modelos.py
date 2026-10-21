import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RegistroChamada:
    """Metrics and raw payload of ANY external call. Every adapter returns one."""
    provedor: str
    operacao: str
    parametros: dict
    requisitado_em: str
    http_status: Optional[int] = None
    latencia_ms: Optional[int] = None
    tentativas: int = 1
    erro: Optional[str] = None
    raw: Optional[bytes] = None
    raw_ext: str = "json"
    id_externo: Optional[str] = None
    tokens_entrada: Optional[int] = None
    tokens_saida: Optional[int] = None
    custo_usd: Optional[float] = None
    extras: dict = field(default_factory=dict)

    @property
    def sucesso(self) -> bool:
        return self.erro is None


# ----- typed configuration -----
@dataclass(frozen=True)
class Termo:
    id: str
    query: str
    idioma: str
    grupo: str
    pai: str = ""        # id do termo de que esta consulta combinada deriva ("" = termo original)


@dataclass(frozen=True)
class ModeloConsultaWeb:
    id: str
    template: str
    perfil: str
    idioma: str = "pt"


@dataclass(frozen=True)
class ConsultaWeb:
    id: str
    texto: str
    idioma: str
    uf: str
    tecnologia: str
    modelo_id: str
    perfil: str
    cidade: str = ""          # vazio = secretaria estadual; preenchido = secretaria municipal da cidade


@dataclass(frozen=True)
class FiltrosBusca:
    dominios_incluir: tuple = ()
    dominios_excluir: tuple = ()
    max_resultados: int = 10
    idiomas: tuple = ()       # codigos ISO 639-1 dos resultados (ex. ("pt",)); vazio = sem filtro de idioma
    pais: str = ""            # codigo ISO 3166-1 alfa-2 (ex. "BR"); vazio = sem filtro de pais

    def __post_init__(self):
        # um perfil invalido nao chega a existir: a chave de idempotencia e o pedido usam os mesmos valores conferidos aqui
        if not (isinstance(self.idiomas, tuple)
                and all(isinstance(i, str) and re.fullmatch(r"[a-z]{2}", i) for i in self.idiomas)):
            raise ValueError("FiltrosBusca: idiomas precisa ser uma tupla de códigos ISO 639-1 de duas letras minúsculas")
        if not (isinstance(self.pais, str) and (self.pais == "" or re.fullmatch(r"[A-Z]{2}", self.pais))):
            raise ValueError("FiltrosBusca: pais precisa ser vazio ou um código ISO 3166-1 de duas letras maiúsculas")


@dataclass(frozen=True)
class FiltrosAcademicos:
    ano_inicial: Optional[int] = None
    ano_final: Optional[int] = None
    por_pagina: int = 20
    idioma_resultados: Optional[str] = None  # filtro de idioma dos resultados no Scholar (lr, ex. "lang_pt"); None = sem filtro


@dataclass(frozen=True)
class ModeloPlanilhaReferencias:
    nome: str
    arquivo: str                 # nome do arquivo .xlsx gerado em outputs/
    colunas: tuple               # ((cabecalho, campo), ...) na ordem das colunas; campo em dominio.catalogo.CAMPOS_CATALOGO
    abas: tuple                  # ((nome_da_aba, filtro), ...); filtro: None (todas), "brasil", "internacional" ou ("categoria", nome)
    explicar_colunas: bool = False   # True acrescenta a aba "Colunas" (cabecalho e significado)


@dataclass(frozen=True)
class PoliticaDownload:
    palavras_chave: tuple = ()
    max_urls_por_uf: int = 40
    dominios_excluir: tuple = ()
    apenas_oficiais: bool = False


@dataclass(frozen=True)
class Instrucoes:
    versao: str
    sistema: str
    usuario: str
    esquema: dict


@dataclass(frozen=True)
class ParametrosClassificacao:
    versao_prompt: str
    sistema: str
    usuario_template: str
    esquema: dict
    tecnologias: tuple
    status: tuple
    max_chars: int = 60_000
    usar_snippet_se_falhar: bool = True
    palavras_tecnologia: dict = field(default_factory=dict)   # tecnologia -> palavras do rotulo (checagem da evidencia)


# ----- results returned by the adapters -----
@dataclass
class ResultadoWeb:
    url: str
    titulo: Optional[str]
    snippet: Optional[str]
    data: Optional[str]
    posicao: int


@dataclass
class RespostaBusca:
    resultados: list
    chamada: RegistroChamada


@dataclass
class ArtigoAcademico:
    titulo: str
    link: Optional[str]
    autores_publicacao: Optional[str]
    ano: Optional[int]
    snippet: Optional[str]
    citacoes: Optional[int]
    posicao: int


@dataclass
class PaginaAcademica:
    artigos: list
    total_reportado: Optional[int]
    chamada: RegistroChamada


@dataclass
class ArquivoBaixado:
    url_final: str
    http_status: Optional[int]
    content_type: str
    conteudo: bytes
    truncado: bool
    chamada: RegistroChamada


@dataclass
class TextoExtraido:
    texto: str
    extrator: str
    ok: bool
    motivo_falha: Optional[str] = None


@dataclass(frozen=True)
class EntradaClassificacao:
    uf: str
    url: str
    titulo: str
    texto: str
    origem: str          # "pagina" | "snippet"
    truncado: bool


@dataclass(frozen=True)
class Achado:
    tecnologia: str
    status: str
    fornecedor: str
    menciona_lgpd: bool
    evidencia: str
    confianca: str
    evidencia_confere: Optional[bool] = None
    confianca_original: Optional[str] = None     # confianca devolvida pelo modelo, antes de qualquer ajuste
    evidencia_cita_tecnologia: Optional[bool] = None   # o trecho cita um termo da tecnologia? (heuristica, sem LLM)
    evidencia_cita_lgpd: Optional[bool] = None         # o trecho cita a LGPD ou protecao de dados? (heuristica)
    nome_solucao: str = ""                             # nome proprio da solucao, so se aparece no texto enviado ("" = sem nome)


@dataclass
class ResultadoClassificacao:
    relevante: bool
    achados: list
    json_valido: bool
    texto_resposta: str
    chamada: RegistroChamada


@dataclass
class ResultadoTriagemLote:
    """Resposta de UMA chamada de triagem de escopo: o texto bruto do modelo (a validacao e do dominio) e o registro."""
    texto_resposta: str
    chamada: RegistroChamada


# ----- items that circulate between stages (read from the database) -----
@dataclass(frozen=True)
class CandidatoDownload:
    url_id: int
    url: str
    uf: str
    dominio: str
    titulo: str
    snippet: str
    melhor_posicao: int
    n_ocorrencias: int
    fonte_oficial: bool
    cidade: str = ""


@dataclass(frozen=True)
class ItemClassificacao:
    url_id: int
    uf: str
    url: str
    titulo: Optional[str]
    snippet: Optional[str]
    pagina_id: Optional[int]
    texto_path: Optional[str]
    cidade: str = ""
