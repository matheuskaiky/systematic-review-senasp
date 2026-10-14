import hashlib
import json

from dominio.modelos import CandidatoDownload, PoliticaDownload
from dominio.servicos import (normalizar_url, evidencia_confere, eh_oficial, hash_chave,
                              chave_dedup_titulo, ano_do_resumo, selecionar_candidatos,
                              interpretar_json_classificacao)

CERCA = "`" * 3

ACHADO = {"tecnologia": "reconhecimento_facial", "status": "em_uso", "fornecedor": "Acme",
          "menciona_lgpd": True, "evidencia": "implantou reconhecimento facial", "confianca": "alta"}
JSON_OK = json.dumps({"relevante": True, "achados": [ACHADO]})


def test_normalizar_url():
    assert normalizar_url("HTTPS://www.Exemplo.gov.br/a/?utm_source=x&b=2&a=1#frag") == "https://exemplo.gov.br/a?a=1&b=2"


def test_evidencia_literal_confere():
    assert evidencia_confere("implantou  reconhecimento facial", "A Secretaria IMPLANTOU reconhecimento\nfacial em 2024.")


def test_evidencia_inventada_nao_confere():
    assert not evidencia_confere("adquiriu drones", "A Secretaria implantou reconhecimento facial.")


def test_evidencia_vazia_nao_confere():
    assert not evidencia_confere("", "qualquer texto")
    assert not evidencia_confere(None, "qualquer texto")


def test_fonte_oficial():
    assert eh_oficial("ssp.pi.gov.br") and not eh_oficial("exemplo.com.br")


# ---------- hash_chave, chave_dedup_titulo, ano_do_resumo ----------
def test_hash_chave_e_deterministico():
    assert hash_chave("a", 1, "b") == hash_chave("a", 1, "b")
    assert hash_chave("a", 1, "b") == hashlib.sha1(b"a|1|b").hexdigest()
    assert hash_chave("a", 1) != hash_chave("a", 2)


def test_chave_dedup_titulo_ignora_caixa_acento_e_pontuacao():
    base = chave_dedup_titulo("Segurança Pública: Reconhecimento Facial no Brasil")
    assert base == chave_dedup_titulo("seguranca publica - reconhecimento facial no brasil!")
    assert base == chave_dedup_titulo("  SEGURANCA   PUBLICA reconhecimento facial, no Brasil ")
    assert base != chave_dedup_titulo("Segurança Pública: Policiamento Preditivo no Brasil")


def test_ano_do_resumo_pega_o_ultimo_ano():
    assert ano_do_resumo("A Silva, B Souza - Revista X, 2019 - repositorio.edu.br 2023") == 2023
    assert ano_do_resumo("Revista Y, 2021") == 2021


def test_ano_do_resumo_sem_ano():
    assert ano_do_resumo("A Silva - Revista X") is None
    assert ano_do_resumo("") is None
    assert ano_do_resumo(None) is None


# ---------- selecionar_candidatos ----------
def _cand(url_id, uf="PI", dominio="ssp.pi.gov.br", titulo="Reconhecimento facial", snippet="",
          pos=1, n=1, oficial=True):
    return CandidatoDownload(url_id, f"https://{dominio}/{url_id}", uf, dominio, titulo, snippet,
                             pos, n, oficial)


def _por_id(decisoes):
    return {c.url_id: (ok, motivo) for c, ok, motivo in decisoes}


def test_selecionar_aceita_candidato_valido():
    d = _por_id(selecionar_candidatos([_cand(1)], PoliticaDownload(palavras_chave=("reconhecimento facial",))))
    assert d[1] == (True, None)


def test_selecionar_dominio_excluido_inclui_subdominio():
    pol = PoliticaDownload(dominios_excluir=("youtube.com",))
    d = _por_id(selecionar_candidatos(
        [_cand(1, dominio="youtube.com"), _cand(2, dominio="m.youtube.com"), _cand(3, dominio="notyoutube.com")], pol))
    assert d[1] == (False, "dominio_excluido")
    assert d[2] == (False, "dominio_excluido")
    assert d[3] == (True, None)


def test_selecionar_nao_oficial():
    pol = PoliticaDownload(apenas_oficiais=True)
    d = _por_id(selecionar_candidatos([_cand(1, oficial=True), _cand(2, dominio="blog.com", oficial=False)], pol))
    assert d[1] == (True, None)
    assert d[2] == (False, "nao_oficial")


def test_selecionar_prefiltro_palavras():
    pol = PoliticaDownload(palavras_chave=("reconhecimento facial",))
    d = _por_id(selecionar_candidatos([_cand(1), _cand(2, titulo="Receitas de bolo")], pol))
    assert d[1] == (True, None)
    assert d[2] == (False, "prefiltro_palavras")


def test_selecionar_palavras_ignoram_acento_e_caixa():
    pol = PoliticaDownload(palavras_chave=("licitação", "CAMERA"))
    d = _por_id(selecionar_candidatos(
        [_cand(1, titulo="LICITACAO de equipamentos"), _cand(2, titulo="Novas câmeras", snippet=""),
         _cand(3, titulo="Sem relacao")], pol))
    assert d[1] == (True, None)
    assert d[2] == (True, None)
    assert d[3] == (False, "prefiltro_palavras")


def test_selecionar_palavras_olham_titulo_e_snippet():
    pol = PoliticaDownload(palavras_chave=("videomonitoramento",))
    d = _por_id(selecionar_candidatos([_cand(1, titulo="Noticia", snippet="novo videomonitoramento")], pol))
    assert d[1] == (True, None)


def test_selecionar_limite_por_uf_prefere_mais_ocorrencias_e_conta_por_uf():
    pol = PoliticaDownload(max_urls_por_uf=1)
    cands = [_cand(1, n=1, pos=1), _cand(2, n=3, pos=5), _cand(3, uf="CE", n=1, pos=1)]
    d = _por_id(selecionar_candidatos(cands, pol))
    assert d[2] == (True, None)                 # mais ocorrencias entra primeiro
    assert d[1] == (False, "limite_por_uf")
    assert d[3] == (True, None)                 # o limite e por UF


def test_selecionar_registra_todas_as_decisoes():
    pol = PoliticaDownload(palavras_chave=("x",), max_urls_por_uf=1, dominios_excluir=("a.com",))
    cands = [_cand(i) for i in range(5)]
    assert len(selecionar_candidatos(cands, pol)) == 5


# ---------- interpretar_json_classificacao ----------
def test_json_simples():
    relevante, achados, valido = interpretar_json_classificacao(JSON_OK)
    assert (relevante, valido) == (True, True)
    assert len(achados) == 1
    a = achados[0]
    assert (a.tecnologia, a.status, a.fornecedor, a.menciona_lgpd, a.confianca) == \
        ("reconhecimento_facial", "em_uso", "Acme", True, "alta")
    assert a.evidencia_confere is None


def test_json_com_cerca_de_codigo():
    assert interpretar_json_classificacao(f"{CERCA}json\n{JSON_OK}\n{CERCA}")[2] is True
    assert interpretar_json_classificacao(f"{CERCA}\n{JSON_OK}\n{CERCA}")[2] is True


def test_json_com_bloco_think():
    relevante, achados, valido = interpretar_json_classificacao(
        f"<think>vou pensar\n{{\"ruido\": 1}}</think>\n{JSON_OK}")
    assert (relevante, len(achados), valido) == (True, 1, True)


def test_json_cercado_por_texto():
    relevante, achados, valido = interpretar_json_classificacao(f"Segue a resposta: {JSON_OK} Espero ter ajudado.")
    assert (relevante, len(achados), valido) == (True, 1, True)


def test_json_lixo():
    assert interpretar_json_classificacao("isto nao e json") == (False, [], False)
    assert interpretar_json_classificacao("") == (False, [], False)
    assert interpretar_json_classificacao(None) == (False, [], False)
    assert interpretar_json_classificacao("{quebrado: ") == (False, [], False)


def test_json_sem_chave_achados():
    assert interpretar_json_classificacao('{"relevante": true}') == (False, [], False)


def test_json_achados_nao_lista():
    assert interpretar_json_classificacao('{"relevante": true, "achados": "nenhum"}') == (False, [], False)


def test_json_relevante_false_sem_achados_e_valido():
    assert interpretar_json_classificacao('{"relevante": false, "achados": []}') == (False, [], True)


def test_json_relevante_ausente_deriva_dos_achados():
    sem_relevante = json.dumps({"achados": [ACHADO]})
    assert interpretar_json_classificacao(sem_relevante)[0] is True
    assert interpretar_json_classificacao('{"achados": []}')[0] is False


def test_json_ignora_itens_que_nao_sao_objetos_e_normaliza_campos():
    texto = '{"relevante": true, "achados": ["lixo", {"tecnologia": "outra_ia", "status": "piloto"}]}'
    _, achados, valido = interpretar_json_classificacao(texto)
    assert valido and len(achados) == 1
    a = achados[0]
    assert (a.fornecedor, a.menciona_lgpd, a.evidencia, a.confianca) == ("", False, "", "baixa")
