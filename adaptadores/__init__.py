from adaptadores.busca_perplexity import BuscaPerplexity
from adaptadores.busca_serpapi_google import BuscaSerpApiGoogle
from adaptadores.academico_serpapi_scholar import AcademicoSerpApiScholar
from adaptadores.fetcher_requests import FetcherRequests
from adaptadores.extrator_padrao import ExtratorPadrao
from adaptadores.classificador_gemini import ClassificadorGemini
from adaptadores.classificador_openai_compat import ClassificadorOpenAICompat
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.bruto_local import BrutoLocal
from adaptadores.exportador_excel import ExportadorExcel

REGISTROS = {
    "busca_web": {"perplexity_search": BuscaPerplexity, "serpapi_google": BuscaSerpApiGoogle},
    "academico": {"serpapi_scholar": AcademicoSerpApiScholar},
    "fetcher": {"requests": FetcherRequests},
    "extrator": {"padrao": ExtratorPadrao},
    "classificador": {"gemini": ClassificadorGemini, "openai_compat": ClassificadorOpenAICompat},
    "armazenamento": {"sqlite": RepositorioSQLite},
    "bruto": {"local": BrutoLocal},
    "exportador": {"excel": ExportadorExcel},
}
