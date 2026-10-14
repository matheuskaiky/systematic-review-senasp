import config.settings as S
from config import consultas as C, vocabulario as V
from dominio.servicos import gerar_consultas_web


def test_gerar_consultas_web_da_configuracao_entregue_gera_270():
    consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS)
    assert len(consultas) == 27 * 5 * 2 == 270
    assert len({c.id for c in consultas}) == 270


def test_consultas_usam_perfis_existentes_e_preenchem_template():
    consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS)
    assert all(c.perfil in C.PERFIS_BUSCA_WEB for c in consultas)
    assert all("{" not in c.texto for c in consultas)
    m01_pi = next(c for c in consultas if c.id == "M01-PI-reconhecimento_facial")
    assert m01_pi.texto == "reconhecimento facial Secretaria de Segurança Pública Piauí"
    assert m01_pi.uf == "PI" and m01_pi.tecnologia == "reconhecimento_facial"


def test_configuracao_entregue_tem_quatro_termos_de_exemplo_e_27_ufs():
    assert [t.id for t in C.TERMOS] == ["T01", "T02", "T03", "T04"]
    assert len(C.UFS) == 27


def test_provedores_estao_todos_declarados_em_opcoes_ou_sao_conhecidos():
    for porta, nome in S.PROVEDORES.items():
        assert nome in S.OPCOES, f"{porta}: sem OPCOES para '{nome}'"


def test_snapshot_config_tem_hash_estavel():
    a, b = S.snapshot_config(), S.snapshot_config()
    assert a == b
    assert len(a["hash"]) == 12


def test_snapshot_config_nao_contem_caminho_absoluto():
    snap = S.snapshot_config()
    assert str(S.RAIZ) not in snap["json"]
    assert "data/busca.db" in snap["json"]
    assert "data/raw" in snap["json"]


def test_snapshot_config_muda_quando_a_configuracao_muda(monkeypatch):
    antes = S.snapshot_config()["hash"]
    monkeypatch.setitem(S.PROVEDORES, "busca_web", "serpapi_google")
    assert S.snapshot_config()["hash"] != antes
