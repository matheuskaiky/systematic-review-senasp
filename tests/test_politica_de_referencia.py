"""RB21: o navegador manda Origin de verdade nos formularios do proprio painel. Com Referrer-Policy no-referrer, os navegadores
mandam `Origin: null` ate em envios da mesma pagina, e a conferencia de mesma origem recusava todo envio (inclusive o login)."""
import shutil

import pytest
from fastapi.testclient import TestClient

from test_painel import _app, demo  # noqa: F401


@pytest.fixture
def cli(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    return TestClient(app)


@pytest.mark.parametrize("caminho", ["/", "/achados", "/literatura/artigos"])
def test_politica_de_referencia_same_origin(cli, caminho):
    assert cli.get(caminho).headers["Referrer-Policy"] == "same-origin"


def test_envio_com_origem_do_proprio_painel_passa_e_origem_nula_continua_recusada(cli):
    import re
    csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get("/achados/1").text).group(1)
    base = {"status_final": "em_uso", "revisor": "Ana", "observacao": "", "csrf": csrf}
    r = cli.post("/achados/1/verificar", data=base, headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code != 403 or "Pedido recusado" not in r.text
    r = cli.post("/achados/1/verificar", data=base, headers={"Origin": "null"}, follow_redirects=False)
    assert r.status_code == 403 and "Pedido recusado" in r.text
