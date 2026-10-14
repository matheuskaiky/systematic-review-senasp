from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.bruto_local import BrutoLocal

# Completar conforme os adaptadores forem criados; ao final do M7 deve coincidir com a secao 8.1 da especificacao.
REGISTROS = {
    "armazenamento": {"sqlite": RepositorioSQLite},
    "bruto": {"local": BrutoLocal},
}
