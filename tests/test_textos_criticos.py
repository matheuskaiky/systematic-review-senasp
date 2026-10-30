"""Textos criticos da interface: o rotulo automatico nao e certeza, a mencao a uma tecnologia nao e uso, a ausencia de achado
nao e ausencia de uso, o download ampliado de referencias tem nome descritivo e a interface nao aponta arquivos internos.
"""
from pathlib import Path

import pytest

from painel import analises_blocos as b, rotulos_escopo
from test_painel import cliente_demo, demo  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
MODELOS = RAIZ / "painel" / "templates"

NOVOS = {
    "geral.html": ['("Achado", "Trecho de uma notícia ou página oficial em que o modelo de linguagem identificou menção a uma '
                   'ferramenta de IA na segurança pública: em uso, em piloto, em licitação ou contrato, anunciada, em estudo ou '
                   'apenas citada."),'],
    "triagem_escopo.html": ['<strong>“Excluído pelo modelo” quer dizer: o modelo classificou o item como fora do escopo, com '
                            'confiança alta, e a conferência automática aprovou a resposta. É um rótulo automático, não uma decisão '
                            'de exclusão.</strong> Mesmo assim o item não é apagado: fica oculto por padrão das listas de artigos'],
    "_triagem_artigo.html": ['<strong>Excluído pelo modelo.</strong> O modelo classificou este artigo como fora do escopo, com '
                             'confiança alta; por isso ele fica oculto das listas e da fila de triagem por padrão'],
    "estados.html": ['<li><span class="selo neutro">○ Nenhum achado encontrado</span> nas páginas coletadas (não indica ausência de '
                     'uso)</li>'],
    "estado.html": ['<p class="vazio">Nenhum achado encontrado nas páginas coletadas para este estado, nas execuções do relatório. Isso não '
                    'indica que o estado não use IA: indica apenas que a coleta não encontrou menções.</p>'],
    "referencias.html": ['modelo=erico">Planilha de referências ampliada</a>'],
    "_legenda_referencias.html": ['<dt>Baixar</dt><dd><strong>Planilha de referências ampliada</strong>: a planilha com as abas '
                                  '"Referências ampliadas" e "Esquema de exploração". <strong>Colunas selecionadas</strong>:'],
    "buscar_texto.html": ['<strong>não prova</strong> que a solução não é usada: a busca na web é incompleta e só uma parte das '
                          'páginas foi baixada.\n      Veja a conferência por solução em {% if pode_seguir("/solucoes") %}<a href="/solucoes">'
                          'Soluções conhecidas</a>{% else %}Soluções conhecidas{% endif %}.</li>'],
    "solucoes.html": ['ranking muda a cada execução e só parte das\n  páginas foi baixada. A lista fica em '
                      '<code>config/solucoes_conhecidas.py</code>; para acrescentar uma solução, edite esse arquivo.'],
}

ANTIGOS = ["tem certeza", "inútil", "○ Sem achados", "Nenhum achado para este estado", "Modelo Érico", "CASO_BO_FACIL",
           "possível ferramenta de IA em uso"]


@pytest.mark.parametrize("arquivo,trechos", list(NOVOS.items()))
def test_texto_novo_no_modelo(arquivo, trechos):
    texto = (MODELOS / arquivo).read_text(encoding="utf-8")
    for t in trechos:
        assert texto.count(t) == 1, (arquivo, t[:60])


@pytest.mark.parametrize("arquivo", sorted({*NOVOS, "base.html"}))
def test_texto_antigo_saiu_do_modelo(arquivo):
    texto = (MODELOS / arquivo).read_text(encoding="utf-8")
    assert [a for a in ANTIGOS if a in texto] == []


def test_parametro_da_planilha_ampliada_nao_muda():
    texto = (MODELOS / "referencias.html").read_text(encoding="utf-8")
    assert '<a href="/literatura/referencias.xlsx?{{ base }}{{ \'&\' if base }}modelo=erico">Planilha de referências ampliada</a>' in texto
    assert "modelo=padrao" not in texto                                   # o outro download (catalogo) fica na pagina Literatura


def test_dica_de_comando_do_banco_vies_continua():
    """A dica de comando da faixa do banco e decisao aprovada (D111); esta etapa so mexe em texto."""
    texto = (MODELOS / "base.html").read_text(encoding="utf-8")
    assert '{% if ctx.banco == "vies" %} · comandos: acrescente --banco vies{% endif %}' in texto


def test_explicacao_do_excluido_na_triagem_de_escopo():
    assert rotulos_escopo.STATUS_EXPLICA["excluido"].startswith(
        "O modelo classificou o item como fora do escopo, com confiança alta, e a conferência automática aprovou a resposta. "
        "Fica oculto das listas por padrão (quarentena temporária)")
    assert "certeza" not in rotulos_escopo.STATUS_EXPLICA["excluido"] and "inútil" not in rotulos_escopo.STATUS_EXPLICA["excluido"]


def _maturidade(base):
    d = {"base": base, "n_achados": 3, "n_verificados": 1, "n_descartados": 0, "tem_dados_humanos": True,
            "regioes": {"PI": "Nordeste", "SP": "Sudeste", "AC": "Norte"},
            "celulas": [{"uf": "PI", "regiao": "Nordeste", "tecnologia": "reconhecimento_facial", "status_max": "em_uso",
                         "peso": 5, "por_status": {"em_uso": 2}, "n_achados": 2, "n_verificados": 1},
                        {"uf": "SP", "regiao": "Sudeste", "tecnologia": "leitura_placas", "status_max": "piloto",
                         "peso": 4, "por_status": {"piloto": 1}, "n_achados": 1, "n_verificados": 0}]}
    if base is None:
        del d["base"]                                                     # sem a chave: o titulo da base padrao
    return d


@pytest.mark.parametrize("base,titulo", [
    (None, "1 de 3 UFs com ao menos um achado no estágio “em uso” (estágio do revisor quando ele o registrou; nos demais, o do "
           "modelo)"),
    ("status_final_ou_reportado", "1 de 3 UFs com ao menos um achado no estágio “em uso” (estágio do revisor quando ele o "
                                  "registrou; nos demais, o do modelo)"),
    ("confirmados", "1 de 3 UFs com ao menos um achado confirmado por revisor no estágio “em uso” (estágio do revisor quando ele "
                    "o registrou; nos demais, o do modelo)"),
])
def test_titulo_da_maturidade_diz_de_quem_e_o_estagio(base, titulo):
    assert b.bloco_maturidade(_maturidade(base))["titulo"] == titulo


def test_maturidade_sem_achados_continua():
    assert b.bloco_maturidade({})["titulo"] == "Ainda não há achados para mapear"


def test_legenda_do_relatorio_estatico():
    texto = (RAIZ / "painel" / "relatorio.py").read_text(encoding="utf-8")
    assert ('<li><span class="selo neutro">○ Nenhum achado encontrado</span> nas páginas coletadas (nenhum achado classificado; não '
            'indica ausência de uso)</li></ul></section>') in texto
    assert "○ Sem achados" not in texto


def test_paginas_renderizadas(cliente_demo):  # noqa: F811
    cli, _, _ = cliente_demo
    assert '<span class="selo neutro">○ Nenhum achado encontrado</span> nas páginas coletadas' in cli.get("/estados").text
    h = cli.get("/").text
    assert "identificou menção a uma ferramenta de IA na segurança pública: em uso, em piloto, em licitação ou contrato" in h
    assert "possível ferramenta de IA em uso" not in h


def test_metodologia_cita_o_rotulo_novo_da_legenda():
    texto = (RAIZ / "painel" / "metodologia_texto.py").read_text(encoding="utf-8")
    assert ("“Nenhum achado encontrado” significa que nenhum achado foi classificado nas páginas coletadas, não que a UF não use "
            "a tecnologia.") in texto
    assert "“Sem achados”" not in texto


@pytest.mark.parametrize("arquivo", ["painel/templates/estados.html", "painel/relatorio.py"])
def test_selos_da_legenda_cabem_no_celular(arquivo):
    """Os selos nao quebram linha (`white-space: nowrap`): o texto de cada selo da legenda do mapa fica curto (no maximo 26
    caracteres, o tamanho de "○ Nenhum achado encontrado"); a explicacao vai fora do selo."""
    import re
    texto = (RAIZ / arquivo).read_text(encoding="utf-8")
    legenda = texto[texto.index('<ul class="legenda"><li><span class="selo ok">✔ Confirmado</span>')
                    if arquivo.endswith(".py") else texto.index('<ul class="legenda">'):]
    legenda = legenda[:legenda.index("</ul>")]
    selos = re.findall(r'<span class="selo [^"]+">([^<]*)</span>', legenda)
    assert len(selos) == 3 and max(len(t) for t in selos) <= 26, selos
