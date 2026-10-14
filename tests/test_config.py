import config.settings as S
from config import consultas as C, prompts as P, vocabulario as V
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


GRUPOS = {"reconhecimento_identificacao", "video_monitoramento", "analise_preditiva",
          "dados_automacao", "atendimento_triagem", "outras_aplicacoes"}


def test_lista_de_termos_da_pesquisa():
    """docs/termos.md: 21 termos da secao 4.1, 3 desmembrados dos parenteses e 22 equivalentes em ingles."""
    assert [t.id for t in C.TERMOS] == [f"T{n:02d}" for n in range(1, 47)]
    assert {t.grupo for t in C.TERMOS} == GRUPOS
    assert all(t.query.startswith('"') and t.query.endswith('"') for t in C.TERMOS)
    assert len({t.query for t in C.TERMOS}) == len(C.TERMOS) == 46


def test_termos_por_idioma_e_sem_parenteses():
    pt = [t for t in C.TERMOS if t.idioma == "pt"]
    en = [t for t in C.TERMOS if t.idioma == "en"]
    assert (len(pt), len(en)) == (24, 22)
    assert [t.id for t in pt] == [f"T{n:02d}" for n in range(1, 25)]
    assert not any("(" in t.query or ")" in t.query for t in C.TERMOS)


def test_termos_desmembrados_dos_parenteses():
    q = {t.id: t.query for t in C.TERMOS}
    assert q["T11"] == '"mapeamento de pontos quentes"' and q["T22"] == '"hotspots"'
    assert q["T12"] == '"avaliação de risco por algoritmos"' and q["T23"] == '"justiça atuarial"'
    assert q["T21"] == '"centro integrado de comando e controle com IA"' and q["T24"] == '"CICC com IA"'


def test_equivalentes_em_ingles_mantem_o_grupo_do_termo_original():
    por_id = {t.id: t for t in C.TERMOS}
    assert por_id["T25"].query == '"facial recognition"' and por_id["T25"].grupo == por_id["T01"].grupo
    assert por_id["T46"].grupo == por_id["T21"].grupo and por_id["T37"].grupo == por_id["T23"].grupo


def test_27_ufs():
    assert len(C.UFS) == 27


def test_prompts_declaram_entrada_em_en_us_e_saida_em_pt_br():
    assert "pt-BR" in P.SYSTEM_PROMPT and "en-US" in P.SYSTEM_PROMPT
    assert "pt-BR" in P.USER_PROMPT
    assert "evidencia" in P.SYSTEM_PROMPT and "verbatim" in P.USER_PROMPT


def test_prompt_usuario_formata_com_os_campos_esperados():
    texto = P.USER_PROMPT.format(uf="PI", nome="Piauí", url="https://x", titulo="t", origem="pagina", texto="corpo")
    assert "Piauí (PI)" in texto and texto.endswith("TEXT:\ncorpo")


def test_prompt_sistema_inclui_todas_as_definicoes_de_status():
    assert all(f"- {k}: " in P.SYSTEM_PROMPT for k in V.STATUS)


def test_user_agent_usa_marcador_de_email_e_nao_o_endereco():
    assert "{email}" in S.OPCOES["requests"]["user_agent"]
    assert "@" not in S.OPCOES["requests"]["user_agent"]
    assert S.EMAIL_PESQUISADOR_ENV == "RESEARCHER_EMAIL"


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
