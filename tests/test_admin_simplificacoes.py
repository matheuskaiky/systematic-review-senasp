"""RB16: o formulario de renomear grupo guarda o nome so pela chave inteira, e a pagina de usuarios nao cobre a falta do grupo Revisor
(grupo fixo, que as telas nao deixam apagar nem renomear)."""
from pathlib import Path

ADMIN = (Path(__file__).resolve().parent.parent / "painel" / "rotas_extras" / "admin.py").read_text(encoding="utf-8")


def test_renomear_guarda_so_a_chave_inteira():
    assert 'form = {"novo": "", "renomear": {gid: nome.strip()}}' in ADMIN
    assert "str(gid): nome.strip()" not in ADMIN


def test_revisor_sem_valor_padrao_inalcancavel():
    assert 'revisor_id = next(str(g["grupo_id"]) for g in grupos if g["nome"] == "Revisor")' in ADMIN
    assert '== "Revisor"), "")' not in ADMIN
