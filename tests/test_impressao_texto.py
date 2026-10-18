"""RB18: no papel, o texto da pagina do achado sai inteiro, mesmo com as regras de tela que vieram depois do @media print."""
from test_painel_navegacao import _blocos, _css, _declaracoes, _impressao

CSS = _css("painel.css")             # sem comentarios, como _blocos exige


def test_texto_da_pagina_sem_altura_maxima_na_impressao():
    regras = {}
    for prefixo, corpo in _blocos(_impressao(CSS)):
        for s in prefixo.split(","):
            regras.setdefault(s.strip(), {}).update(_declaracoes(corpo))
    assert regras[".texto-pagina"]["max-height"] == "none !important"
    assert regras[".texto-pagina"]["overflow"] == "visible !important"
