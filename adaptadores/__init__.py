from adaptadores.busca_perplexity import BuscaPerplexity
from adaptadores.academico_serpapi_scholar import AcademicoSerpApiScholar
from adaptadores.fetcher_requests import FetcherRequests
from adaptadores.extrator_padrao import ExtratorPadrao
from adaptadores.classificador_gemini import ClassificadorGemini
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.bruto_local import BrutoLocal
from adaptadores.exportador_excel import ExportadorExcel

# Completar conforme os adaptadores forem criados; ao final do M7 deve coincidir com a secao 8.1 da especificacao.
REGISTROS = {
    "busca_web": {"perplexity_search": BuscaPerplexity},
    "academico": {"serpapi_scholar": AcademicoSerpApiScholar},
    "fetcher": {"requests": FetcherRequests},
    "extrator": {"padrao": ExtratorPadrao},
    "classificador": {"gemini": ClassificadorGemini},
    "armazenamento": {"sqlite": RepositorioSQLite},
    "bruto": {"local": BrutoLocal},
    "exportador": {"excel": ExportadorExcel},
}
