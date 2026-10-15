import random
import string

import pytest

from dominio.servicos import evidencia_confere, normalizar_texto
from dominio.servicos_painel import _normalizar_com_mapa, localizar_evidencia, trecho_mais_parecido


def _trecho(texto, par):
    return texto[par[0]:par[1]]


def test_acentos_espacos_e_quebras_de_linha_apontam_para_o_texto_original():
    t = "Início.  A SSP   do Piauí\nadotou o RECONHECIMENTO   facial em 2024. Fim."
    par = localizar_evidencia("adotou o reconhecimento facial", t)
    assert _trecho(t, par) == "adotou o RECONHECIMENTO   facial"


def test_evidencia_com_acento_em_texto_sem_acento_e_vice_versa():
    t0 = "A policia usa videomonitoramento."
    assert localizar_evidencia("polícia usa", t0) is not None and _trecho(t0, localizar_evidencia("polícia usa", t0)) == "policia usa"
    t = "Sistema de Análise Preditiva implantado"
    assert _trecho(t, localizar_evidencia("analise preditiva", t)) == "Análise Preditiva"


def test_inicio_e_fim_do_texto():
    t = "reconhecimento facial no começo e no fim: leitura de placas"
    assert _trecho(t, localizar_evidencia("reconhecimento facial", t)) == "reconhecimento facial"
    assert _trecho(t, localizar_evidencia("leitura de placas", t)) == "leitura de placas"


def test_ausente_e_vazia():
    assert localizar_evidencia("nada disso", "outro texto") is None
    assert localizar_evidencia("", "texto") is None and localizar_evidencia("   ", "texto") is None
    assert localizar_evidencia("x", "") is None and localizar_evidencia("x", None) is None


def test_espacos_nas_pontas_da_evidencia_e_nbsp():
    t = "uso de câmeras inteligentes hoje"
    assert _trecho(t, localizar_evidencia("  câmeras inteligentes ", t)) == "câmeras inteligentes"


def test_ligatura_e_caracteres_sem_equivalente_ascii():
    t = "o ﬁnanciamento — “câmeras” 自動 do estado"
    par = localizar_evidencia("financiamento", t)
    assert _trecho(t, par) == "ﬁnanciamento"


@pytest.mark.parametrize("semente", range(30))
def test_concorda_com_evidencia_confere_e_o_mapa_reproduz_a_normalizacao(semente):
    rnd = random.Random(semente)
    alfabeto = "aáãçéÉ  \n\t.,-ﬁ xyz"
    texto = "".join(rnd.choice(alfabeto) for _ in range(rnd.randint(0, 60)))
    assert _normalizar_com_mapa(texto)[0] == normalizar_texto(texto)
    inicio = rnd.randint(0, max(0, len(texto) - 1))
    for ev in (texto[inicio:inicio + rnd.randint(1, 12)], "".join(rnd.choice(alfabeto) for _ in range(rnd.randint(0, 6)))):
        par = localizar_evidencia(ev, texto)
        assert (par is not None) == evidencia_confere(ev, texto)
        if par:
            assert normalizar_texto(texto[par[0]:par[1]]) == normalizar_texto(ev)


def test_trecho_mais_parecido_acha_a_frase_adulterada():
    t = "Primeira frase sobre outro assunto.\nA secretaria implantou sistema de reconhecimento facial nas estações de metrô.\nFim do texto."
    par = trecho_mais_parecido("implantou o sistema de reconhecimento facial nas estacoes do metro", t)
    assert par is not None and "reconhecimento facial" in t[par[0]:par[1]] and 0.6 < par[2] <= 1


def test_trecho_mais_parecido_devolve_none_sem_semelhanca():
    assert trecho_mais_parecido("zzzz qqqq wwww", "Texto sobre outra coisa totalmente diferente aqui.") is None
    assert trecho_mais_parecido("", "texto") is None and trecho_mais_parecido("x", "") is None


# ---------- diff_config e mascara de segredos ----------
from dominio.servicos_painel import diff_config, mascarar_segredos


def test_diff_config_iguais_nao_tem_diferenca():
    c = {"a": 1, "b": {"c": [1, 2], "d": "x"}, "t": [{"id": "T01", "q": "x"}]}
    assert diff_config(c, {"a": 1, "b": {"c": [1, 2], "d": "x"}, "t": [{"id": "T01", "q": "x"}]}) == []


def test_diff_config_alterado_adicionado_removido_e_aninhado():
    a = {"prompt_versao": "v2", "opcoes": {"gemini": {"modelo": "m1", "temperatura": 0.0}}, "so_a": 1}
    b = {"prompt_versao": "v3", "opcoes": {"gemini": {"modelo": "m1", "temperatura": 0.2, "novo": True}}, "so_b": 2}
    d = {c: (x, y, t) for c, x, y, t in diff_config(a, b)}
    assert d == {"prompt_versao": ("v2", "v3", "alterado"), "opcoes.gemini.temperatura": (0.0, 0.2, "alterado"),
                 "opcoes.gemini.novo": (None, True, "so_em_b"), "so_a": (1, None, "so_em_a"), "so_b": (None, 2, "so_em_b")}


def test_diff_config_listas_pareiam_por_id_e_por_posicao():
    a = {"termos": [{"id": "T01", "q": "x"}, {"id": "T02", "q": "y"}], "lista": [1, 2, 3]}
    b = {"termos": [{"id": "T02", "q": "y"}, {"id": "T01", "q": "z"}, {"id": "T03", "q": "w"}], "lista": [1, 9]}
    d = {c: t for c, _, _, t in diff_config(a, b)}
    assert d["termos[T01].q"] == "alterado" and d["termos[T03].id"] == "so_em_b" and "termos[T02].q" not in d    # T02 mudou de posicao so
    assert d["lista[1]"] == "alterado" and d["lista[2]"] == "so_em_a"


def test_diff_config_vazios_e_none():
    assert diff_config(None, {"a": 1}) == [("a", None, 1, "so_em_b")]
    assert diff_config({"a": []}, {"a": {}}) == [("a", [], {}, "alterado")]


def test_mascarar_segredos_em_qualquer_nivel_sem_alterar_o_original():
    original = {"api_key": "SEGREDO", "headers": {"Authorization": "Bearer SEGREDO", "x-goog-api-key": "SEGREDO", "Content-Type": "json"},
                "lista": [{"token": "SEGREDO", "ok": 1}], "minha_key": "SEGREDO", "monkeys": "ok", "vazio": {"key": ""}}
    m = mascarar_segredos(original)
    assert "SEGREDO" not in str(m) and m["headers"]["Content-Type"] == "json" and m["lista"][0]["ok"] == 1
    assert m["monkeys"] == "ok" and m["vazio"]["key"] == ""            # nao mascara o que nao e segredo nem o vazio
    assert original["api_key"] == "SEGREDO"
