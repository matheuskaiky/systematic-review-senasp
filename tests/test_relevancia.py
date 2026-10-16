"""Relevancia Brasil + tema: funcao pura, com casos escritos a mao (inclusive titulos da coleta real)."""
import pytest

from dominio import relevancia as R
from dominio.relevancia import pontuar_relevancia as pontuar


def _nivel(titulo, snippet="", autores="", link=""):
    return pontuar(titulo, snippet, autores, link)["nivel"]


# ---------- titulos da coleta real (calibracao) ----------
CASOS_REAIS = [
    ("Reconhecimento facial na segurança pública: desafios para a Polícia Militar", "", "", "", "alta"),
    # so o host brasileiro (unesc.net, sem .br) sinaliza Brasil: o assunto e generico
    ("Aprendizado de máquina para o reconhecimento facial aplicado a fechaduras inteligentes", "", "",
     "http://repositorio.unesc.net/handle/1/1234", "media"),
    ("Percepção dos Profissionais da TI sobre o Racismo Algorítmico em Tecnologias de Reconhecimento Facial", "", "",
     "https://aisel.aisnet.org/sbes/2022/1", "baixa"),
    ("Computer vision for facial recognition: advances and risks", "", "", "", "baixa"),
    ("Policiamento preditivo no Brasil: análise de dados criminais em São Paulo", "", "", "", "alta"),
    ("Automatic detection of people with reduced mobility using YOLOv5", "", "", "", "baixa"),
    ("Predictive policing in the United States: a review", "", "", "", "media"),
]


@pytest.mark.parametrize("titulo,snippet,autores,link,esperado", CASOS_REAIS)
def test_casos_da_coleta_real(titulo, snippet, autores, link, esperado):
    assert _nivel(titulo, snippet, autores, link) == esperado


def test_lado_certo_da_media_e_dos_sinais_nos_casos_reais():
    brasil_so = pontuar(*CASOS_REAIS[1][:4])
    assert brasil_so["brasil"] and not brasil_so["tema"]
    tema_so = pontuar(*CASOS_REAIS[6][:4])
    assert tema_so["tema"] and not tema_so["brasil"] and tema_so["sinais"] == ["policing"]


# ---------- niveis ----------
def test_titulo_brasileiro_sobre_policia_e_alta():
    r = pontuar("Câmeras corporais na Polícia Militar do Piauí", "", "", "")
    assert (r["brasil"], r["tema"], r["nivel"]) == (True, True, "alta")
    assert "polícia militar" in r["sinais"]


def test_artigo_americano_de_reconhecimento_facial_e_baixo():
    r = pontuar("Face recognition accuracy across demographic groups",
                "We evaluate commercial face recognition systems on a new benchmark.",
                "J Smith - Journal of Machine Learning, Stanford University, 2021 - mit.edu", "https://cs.stanford.edu/paper.pdf")
    assert r["nivel"] == "baixa" and r["sinais"] == [] and r["pontos"] == 0


def test_repositorio_br_com_assunto_generico_e_media_so_pelo_dominio():
    r = pontuar("Detecção de objetos em imagens com redes convolucionais", "Avaliamos várias arquiteturas.", "",
                "https://repositorio.ufsc.br/handle/123/456")
    assert (r["brasil"], r["tema"], r["nivel"]) == (True, False, "media")
    assert r["sinais"] == [".br"]


def test_dominio_br_so_conta_como_sinal_de_brasil():
    r = pontuar("Generic study", "", "", "https://www.scielo.br/j/x/a/y")
    assert r["brasil"] and not r["tema"]


def test_dominio_br_no_texto_de_autores_e_publicacao():
    r = pontuar("Estudo", "", "A Silva - Revista de Computação, 2020 - sol.sbc.org.br", "")
    assert r["brasil"] and ".br" in r["sinais"]


def test_dominio_br_nao_casa_dentro_de_outras_palavras():
    assert not pontuar("Estudo", "", "", "https://example.com/brochure.html")["brasil"]
    assert not pontuar("Estudo", "", "", "https://abr.org/x")["brasil"]
    assert not pontuar("Estudo", "", "J Doe - Lib.brx Press, 2020", "")["brasil"]


def test_host_conhecido_sem_br_so_vale_como_host():
    assert pontuar("Estudo", "", "", "https://revistas.unesc.net/x")["brasil"]
    assert not pontuar("Estudo sobre unesc.net", "", "", "")["brasil"]  # no titulo, o host em texto livre nao conta


def test_seguranca_sozinha_nao_e_tema_mas_seguranca_publica_e():
    assert not pontuar("Segurança da informação em redes", "", "", "")["tema"]
    assert not pontuar("Cybersecurity and security of IoT devices", "", "", "")["tema"]
    assert pontuar("Segurança pública e dados", "", "", "")["tema"]
    assert pontuar("Public security and AI", "", "", "")["tema"]
    assert pontuar("Public safety analytics", "", "", "")["tema"]


def test_tecnologias_sozinhas_nao_sao_o_tema():
    for t in ("Machine learning for image classification", "Reconhecimento facial com redes neurais", "Deep learning e visão computacional"):
        assert not pontuar(t, "", "", "")["tema"], t


def test_policy_nao_casa_com_policia():
    assert not pontuar("Privacy policy and policies for data sharing", "", "", "")["tema"]


# ---------- normalizacao e palavra inteira ----------
def test_acentos_e_maiusculas_sao_ignorados():
    a = pontuar("POLÍCIA CIVIL E SEGURANÇA PÚBLICA NO BRASIL", "", "", "")
    b = pontuar("policia civil e seguranca publica no brasil", "", "", "")
    assert a["nivel"] == b["nivel"] == "alta" and a["sinais"] == b["sinais"]
    assert pontuar("Vigilância em São Paulo", "", "", "")["nivel"] == "alta"
    assert pontuar("Ceará", "", "", "")["brasil"]


def test_palavra_inteira_pm_e_br_nao_casam_dentro_de_palavras():
    r = pontuar("ampm abrir libre cobra brave bremen pmcid", "abrasivo ebr bro", "", "")
    assert r["sinais"] == [] and r["nivel"] == "baixa"
    # "br" e "pm" soltos tambem nao sao marcadores
    assert pontuar("PM e BR", "", "", "")["nivel"] == "baixa"


def test_estados_ambiguos_nao_sao_marcadores():
    # "para" (preposicao) e "acre" (unidade de area) nao podem sinalizar Brasil
    assert not pontuar("Uma proposta para o ensino, 12 acre de terra", "", "", "")["brasil"]
    assert pontuar("Pesquisa no estado do Pará", "", "", "")["brasil"]


def test_radicais_casam_variacoes_e_nao_prefixos_de_outras_palavras():
    assert pontuar("Estudos brasileiros", "", "", "")["sinais"] == ["brasileiros"]
    assert pontuar("Criminalidade e crimes", "", "", "")["tema"]
    assert pontuar("Forensic analysis", "", "", "")["tema"]
    assert pontuar("Sistema prisional", "", "", "")["tema"]
    assert pontuar("Brasileirismo", "", "", "")["brasil"]  # o radical casa o inicio da palavra
    assert pontuar("Brasilia", "", "", "")["sinais"] == ["brasília"]  # com acento ou sem, a cidade e reconhecida


# ---------- entradas vazias ----------
@pytest.mark.parametrize("args", [(None, None, None, None), ("", "", "", ""), (None, "", None, ""), ("   ", None, "  ", None)])
def test_entradas_vazias_ou_none_sao_baixa(args):
    r = pontuar(*args)
    assert r == {"brasil": False, "tema": False, "nivel": "baixa", "sinais": [], "sinais_brasil": [], "sinais_tema": [], "pontos": 0}


def test_link_malformado_nao_levanta():
    assert pontuar("Estudo", "", "", "http://[::1")["nivel"] == "baixa"
    assert pontuar("Estudo", "", "", "scielo.br/x")["brasil"]  # link sem esquema tambem vale


# ---------- sinais e pontos ----------
def test_sinais_sem_repeticao_e_na_ordem_brasil_depois_tema():
    r = pontuar("Polícia, polícia e mais POLÍCIA no Brasil", "Brasil brasil BRASIL; crime, Crime", "", "https://x.gov.br")
    assert r["sinais"] == list(dict.fromkeys(r["sinais"]))
    assert r["sinais_brasil"] == list(dict.fromkeys(r["sinais_brasil"]))
    assert r["sinais"].count("brasil") == 1 and r["sinais"].count("polícia") == 1 and r["sinais"].count("crime") == 1
    assert r["sinais"].index("brasil") < r["sinais"].index("polícia")


def test_pontos_ordenam_alta_acima_de_media_acima_de_baixa():
    alta = pontuar("Policiamento no Brasil", "", "", "")["pontos"]
    media_brasil = pontuar("Estudo no Brasil", "", "", "")["pontos"]
    media_tema = pontuar("Policiamento preditivo", "", "", "")["pontos"]
    baixa = pontuar("Estudo genérico", "", "", "")["pontos"]
    assert alta > max(media_brasil, media_tema) > baixa == 0


def test_mais_sinais_e_sinal_no_titulo_pontuam_mais():
    so_snippet = pontuar("Estudo", "polícia no Brasil", "", "")["pontos"]
    no_titulo = pontuar("Polícia no Brasil", "", "", "")["pontos"]
    mais_sinais = pontuar("Polícia e crime no Brasil", "", "", "")["pontos"]
    assert so_snippet < no_titulo < mais_sinais


# ---------- as listas sao visiveis e coerentes ----------
def test_listas_de_marcadores_sao_publicas_e_de_tamanho_razoavel():
    for lista in (R.MARCADORES_BRASIL, R.MARCADORES_TEMA):
        assert isinstance(lista, tuple) and 30 <= len(lista) <= 100
        assert len(set(lista)) == len(lista)
    assert R.NIVEIS == ("alta", "media", "baixa")


def test_marcadores_proibidos_ficam_de_fora():
    tema = {m.lower() for m in R.MARCADORES_TEMA}
    for proibido in ("security", "segurança", "seguranca", "machine learning", "reconhecimento facial", "pm", "br"):
        assert proibido not in tema
    brasil = {m.lower() for m in R.MARCADORES_BRASIL}
    assert not {"pm", "br", "para", "acre", "natal", "salvador"} & brasil


def test_cada_marcador_casa_com_ele_mesmo():
    """Auditoria das listas: todo marcador, escrito como esta (ou com um sufixo, se for radical), e reconhecido."""
    for m in R.MARCADORES_BRASIL:
        texto = m.rstrip("*") + ("s" if m.endswith("*") else "")
        assert pontuar(texto, "", "", "")["brasil"], m
    for m in R.MARCADORES_TEMA:
        texto = m.rstrip("*") + ("s" if m.endswith("*") else "")
        assert pontuar(texto, "", "", "")["tema"], m
