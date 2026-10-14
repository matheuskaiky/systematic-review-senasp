from adaptadores.busca_perplexity import BuscaPerplexity
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.bruto_local import BrutoLocal
from adaptadores.exportador_excel import ExportadorExcel

# Completar conforme os adaptadores forem criados; ao final do M7 deve coincidir com a secao 8.1 da especificacao.
REGISTROS = {
    "busca_web": {"perplexity_search": BuscaPerplexity},
    "armazenamento": {"sqlite": RepositorioSQLite},
    "bruto": {"local": BrutoLocal},
    "exportador": {"excel": ExportadorExcel},
}
