"""Glossario "Sobre os dados" por pesquisa: no banco `vies`, as unidades, a triagem pelo modelo (v2) e as regras de
apresentacao desta busca; nos outros bancos, o glossario do estudo das secretarias, sem mudanca. A definicao de cada nivel
de relevancia da v2 tem uma fonte so (`painel.rotulos.RELEVANCIA_V2`), lida pelo glossario e pela legenda das Analises."""
import hashlib
import importlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apoio_divulgacao import gravar_politica
from painel import glossario, rotulos
from test_analises_vies import _cli, banco  # noqa: F401  (fixture do banco vies com triagem)
from test_autenticacao import _criar, _entrar
from test_divulgacao_acesso import _painel
from test_painel import demo  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]

RELEVANCIA_V2 = {
    "alta": ("diretamente sobre IA, algoritmos ou sistemas de decisão automatizada na segurança pública, no policiamento, na "
             "investigação criminal, na perícia ou na justiça criminal, tratando de viés, discriminação, ética, direitos ou "
             "governança, ou de aplicações, implantações, resultados empíricos, soluções tecnológicas ou produtos"),
    "media": ("IA numa área vizinha (justiça em geral, vigilância, cidades inteligentes) que se transfere claramente para a "
              "segurança pública, ou viés e ética da IA em outra área que se transfere claramente para a segurança pública"),
    "baixa": ("só tangencial, inclusive tecnologia de segurança pública sem IA nem decisão automatizada (câmeras comuns, "
              "câmeras corporais, drones sem IA)"),
    "fora_do_escopo": ("sem relação com o tema; o modelo é instruído a usar esta classe só quando tem certeza, e então com "
                       "confiança alta"),
}

SUBTITULO_REAL = ("O que cada número, status e motivo desta ferramenta significa, em linguagem simples. Os mesmos termos aparecem "
                  "nas telas e na planilha Excel exportada.")
SUBTITULO_VIES = ("O que significam as unidades de contagem, os rótulos da triagem pelo modelo e as regras de apresentação "
                  "desta pesquisa, em linguagem simples.")

# entradas reaproveitadas, pelo proprio objeto, da secao de execucoes do glossario do estudo real
EXECUCOES_REUSADAS = ["execucao-concluida", "execucao-em_andamento", "execucao-interrompida", "execucao-falhou", "idempotencia",
                      "config-hash", "commit-git", "chamada-bruta", "custo-estimado"]

ESPERADO = [
    ("unidades", "Unidades de contagem",
     "Cada número desta pesquisa conta uma destas unidades. Números de unidades diferentes não se somam.", [
         ("chamada", "Chamada",
          "Um pedido feito a um provedor externo: uma consulta à busca na web, uma página de resultados de uma consulta no "
          "Google Scholar ou um lote de itens enviado ao modelo da triagem. Cada chamada fica registrada com os parâmetros "
          "enviados e, quando o provedor respondeu, com a resposta bruta e, se o provedor tem preço configurado, com o custo "
          "estimado em dólares. O Google Scholar é contado em créditos do serviço, medidos por execução, sem preço em dólares."),
         ("ocorrencia", "Ocorrência",
          "Um resultado devolvido por uma chamada de busca. O mesmo trabalho pode voltar em várias consultas, e cada volta é "
          "uma ocorrência. Na busca na web, as ocorrências do mesmo endereço formam uma referência da web; no Google Scholar, "
          "as do mesmo título formam um artigo do Scholar."),
         ("artigo-scholar", "Artigo do Scholar",
          "Um trabalho encontrado pelo Google Scholar, contado uma vez mesmo quando várias consultas o devolvem. Dois "
          "resultados são o mesmo artigo quando o título é igual depois de normalizado (sem acentos, maiúsculas nem "
          "pontuação). Apesar do nome, pode ser uma dissertação, um livro, um capítulo ou outro trabalho que o Scholar indexa."),
         ("referencia-web", "Referência da web",
          "Uma página encontrada pela busca na web, contada uma vez mesmo quando várias consultas a devolvem. Dois resultados "
          "são a mesma referência quando o endereço é igual depois de normalizado (sem “www”, sem a barra final e sem "
          "parâmetros de rastreamento). Pode ser um artigo, uma notícia, um relatório, uma norma ou a página de um produto."),
         ("item", "Item",
          "Um artigo do Scholar ou uma referência da web. É a unidade da triagem pelo modelo: o mesmo trabalho encontrado nas "
          "duas fontes são dois itens, cada um com a sua classificação."),
         ("obra", "Obra",
          "O item depois de juntar a referência da web que repete um artigo do Scholar, por ter o mesmo endereço normalizado "
          "ou o mesmo título normalizado. A obra assim juntada conta uma vez, e nas análises por obra vale a classificação do "
          "artigo do Scholar. A junção é um procedimento automático, não uma conferência bibliográfica: títulos escritos de "
          "forma diferente não são reconhecidos como a mesma obra, e possíveis duplicatas que restam ainda não foram "
          "examinadas por uma pessoa."),
     ]),
    ("busca", "Busca",
     "De onde vêm os itens. A Metodologia descreve os filtros, a profundidade e as execuções de cada fonte.", [
         ("conjuntos-consultas", "Conjuntos de consultas A, B e C",
          "As quinze consultas da busca, em português, em três conjuntos de cinco. O conjunto A combina termos de "
          "inteligência artificial, segurança pública, viés algorítmico e investigação criminal; o B, de inteligência "
          "artificial, segurança pública, viés algorítmico, discriminação e ética; o C trata das aplicações da inteligência "
          "artificial na segurança pública, na investigação criminal e no policiamento, inclusive o reconhecimento facial e "
          "as soluções tecnológicas. As mesmas consultas foram usadas na busca na web e no Google Scholar."),
         ("busca-web", "Busca na web",
          "Busca em páginas da internet feita pelo serviço Perplexity, uma chamada por consulta. Devolve o endereço, o "
          "título e um trecho de cada página."),
         ("google-scholar", "Google Scholar",
          "Buscador acadêmico consultado por meio do serviço SerpApi, uma chamada por página de resultados de cada consulta. "
          "Devolve o título, um trecho, os autores e a publicação de cada trabalho e, quando a fonte informa, o número de "
          "citações."),
     ]),
    ("triagem-modelo", "Triagem pelo modelo (versão v2)",
     "Um modelo de linguagem leu cada item e atribuiu os rótulos abaixo. São classificações automatizadas, não decisões "
     "de pesquisadores.", [
         ("triagem-escopo", "Triagem pelo modelo",
          "Classificação de cada item por um modelo de linguagem, com as instruções da versão v2, que cobrem os dois ângulos "
          "da pesquisa: o viés algorítmico e as aplicações tecnológicas da IA na segurança pública. O modelo é instruído a "
          "julgar pelo que o próprio item mostra (título, trecho, autores, ano e endereço), nunca pela consulta que o "
          "encontrou. As classificações de uma versão anterior (v1) continuam guardadas; as análises usam a v2, e a ocultação "
          "usa a classificação mais recente de cada item."),
         ("relevancia", "Relevância",
          "O quanto o item trata do tema da pesquisa, segundo o modelo, em quatro níveis. O modelo é instruído a escolher "
          "entre alta e média pelo que o item mostra e, na dúvida entre manter e excluir, a manter. A relevância é um rótulo "
          "do modelo, não a decisão de uma pessoa de incluir ou excluir o item da revisão; o artigo que o modelo põe fora do "
          "escopo com confiança alta, numa resposta que passou na conferência automática, fica oculto, como explica “Item "
          "oculto pelo modelo”."),
         ("relevancia-alta", "Relevância alta", "Segundo o modelo: " + RELEVANCIA_V2["alta"] + "."),
         ("relevancia-media", "Relevância média", "Segundo o modelo: " + RELEVANCIA_V2["media"] + "."),
         ("relevancia-baixa", "Relevância baixa", "Segundo o modelo: " + RELEVANCIA_V2["baixa"] + "."),
         ("relevancia-fora-do-escopo", "Fora do escopo", "Segundo o modelo: " + RELEVANCIA_V2["fora_do_escopo"] + "."),
         ("confianca-modelo", "Confiança do modelo",
          "O quanto o modelo diz estar seguro da relevância que deu: alta, média ou baixa. É uma declaração do próprio "
          "modelo, não uma medida de acerto."),
         ("elegivel", "Elegível",
          "Relevância alta ou média segundo o modelo. É um rótulo técnico da triagem automática, não a inclusão do item na "
          "revisão."),
         ("no-escopo", "No escopo",
          "Relevância alta, média ou baixa segundo o modelo. Ficam de fora os itens fora do escopo e os que não têm triagem "
          "válida."),
         ("angulo", "Ângulo predominante",
          "O recorte do item, segundo o modelo: viés algorítmico, quando o tema central é viés, discriminação, equidade, "
          "ética, direitos, transparência, responsabilização ou governança da IA ou de algoritmos; ou aplicações "
          "tecnológicas, quando o tema central é o uso, a implantação, o desempenho, os produtos ou as soluções de IA ou de "
          "tecnologia, sem centrar o viés ou a ética. É um só ângulo por item, o que domina o título e o trecho; não quer "
          "dizer que a obra trate só desse tema."),
         ("tipo-fonte", "Tipo de fonte",
          "Um entre 43 tipos fixos (artigo científico, dissertação, relatório, reportagem, norma, solução tecnológica e "
          "outros), escolhido pelo modelo. O sistema acrescenta o grupo: literatura científica, literatura cinzenta ou fonte "
          "primária (normas e regulação)."),
         ("pais-escopo", "País ou escopo",
          "O país ou a abrangência do item segundo o modelo, em texto curto (por exemplo, Brasil, EUA, União Europeia ou "
          "Internacional). Quando o item não mostra, fica “Indeterminado”: o modelo é instruído a não supor Brasil só porque "
          "a busca foi em português."),
         ("topicos", "Tópicos",
          "De um a cinco temas curtos que o modelo tira do item. Nas análises, os tópicos que aparecem como palavra ou "
          "expressão de alguma consulta ficam marcados como “termo de busca” e contam como os demais."),
         ("eixo", "Eixo de exploração",
          "Um dos seis eixos de exploração definidos para a pesquisa, ou nenhum, escolhido pelo modelo. Os eixos foram "
          "pensados para o viés algorítmico, e itens sobre aplicações podem ficar sem eixo."),
         ("justificativa", "Justificativa",
          "Frase curta em que o modelo diz por que deu aquela relevância; ele é instruído a usar até 25 palavras. Aparece na "
          "página de cada item."),
         ("conferencia-automatica", "Conferência automática",
          "Depois de cada resposta, o programa confere, sem usar o modelo, se cada campo está entre as opções e dentro dos "
          "tamanhos permitidos. Uma resposta com algum campo fora disso fica marcada como inválida, e o item conta como sem "
          "triagem válida. A conferência olha o formato da resposta, não se a classificação está certa."),
     ]),
    ("apresentacao", "O que fica oculto e o que é decisão humana",
     "Como as telas tratam a classificação do modelo e a decisão de uma pessoa. Nada é apagado do banco.", [
         ("oculto-pelo-modelo", "Item oculto pelo modelo",
          "Um artigo do Scholar que o modelo pôs fora do escopo, com confiança alta e numa resposta que passou na "
          "conferência automática, fica oculto das listas de artigos enquanto nenhuma pessoa decidir sobre ele. Uma resposta "
          "fora do escopo sem confiança alta não oculta nada. O artigo oculto não é apagado: quem tem acesso pode mostrá-lo "
          "pelo filtro da lista, e a decisão de uma pessoa sempre prevalece. As referências da web não são ocultadas: a tela "
          "Referências mostra todas."),
         ("decisao-humana", "Decisão humana",
          "A decisão de triagem registrada por uma pessoa sobre um artigo do Scholar (incluir ou excluir). É diferente da "
          "classificação do modelo e prevalece sobre ela. As referências da web ainda não passam por triagem humana. "
          "Enquanto não houver decisões humanas, os números da triagem são só do modelo."),
         ("validacao-humana", "Validação humana da triagem",
          "Conferência, por uma pessoa que não vê a resposta do modelo no formulário, de uma amostra de 40 itens com triagem válida e tipo "
          "de fonte, sorteada uma só vez por estratos de relevância. Mede a concordância entre a pessoa e o modelo em quatro "
          "campos (relevância, grupo da fonte, eixo e país) e na elegibilidade; a concordância da elegibilidade para todos os "
          "itens triados é estimada pesando cada estrato pelo seu tamanho, e só quando todos os estratos têm resposta."),
         ("sinais-brasil-tema", "Sinais de Brasil e de tema",
          "Ajuda de priorização nas listas de artigos: uma busca de palavras no título, no resumo, nos autores e no endereço "
          "procura sinais de que o artigo é brasileiro e de que trata de segurança pública. Não é a relevância da triagem "
          "pelo modelo e não oculta nem exclui nada."),
     ]),
    ("execucoes", "Execuções e reprodutibilidade",
     "Cada passagem de uma etapa é uma execução, com situação, configuração e custo próprios.", EXECUCOES_REUSADAS),
]

# o que o glossario do vies nunca diz: termos do estudo das secretarias, a heuristica com o nome de relevancia, o recorte
# temporal do outro estudo, o vocabulario antigo da triagem, comandos e caminhos de arquivo
PROIBIDOS = ["secretaria", "Secretaria", "achado", "Achado", "Brasil + tema", "2022", "config/", ".py", "python", "main.py",
             "achados-importar", "--", "quarentena", "Quarentena", "LLM", "funil", "planilha Excel"]
PROIBIDOS_PALAVRA = ["UF", "UFs", "municipal", "estadual"]


def _vies_ids():
    return [s["id"] for s in glossario.SECOES_VIES] + [e["id"] for s in glossario.SECOES_VIES for e in s["entradas"]]


def _main(html):
    return re.search(r'<main id="conteudo" tabindex="-1">(.*)</main>', html, re.S).group(1)


# ---------------- conteudo ----------------
def test_secoes_do_vies_na_ordem_com_os_textos_exatos():
    assert [(s["id"], s["titulo"], s["intro"]) for s in glossario.SECOES_VIES] == [(i, t, x) for i, t, x, _ in ESPERADO]
    for secao, (_, _, _, entradas) in zip(glossario.SECOES_VIES, ESPERADO):
        if entradas is EXECUCOES_REUSADAS:
            assert [e["id"] for e in secao["entradas"]] == EXECUCOES_REUSADAS
            continue
        assert [(e["id"], e["termo"], e["texto"]) for e in secao["entradas"]] == entradas, secao["id"]
        assert all(set(e) == {"id", "termo", "texto"} for e in secao["entradas"]), secao["id"]


def test_execucoes_sao_as_mesmas_entradas_do_estudo_real_nunca_copias():
    do_real = {e["id"]: e for e in glossario._EXECUCOES}
    secao = next(s for s in glossario.SECOES_VIES if s["id"] == "execucoes")
    assert all(e is do_real[e["id"]] for e in secao["entradas"])


def test_ancoras_do_vies_unicas_e_validas():
    ids = _vies_ids()
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_-]*", i) for i in ids)


@pytest.mark.parametrize("trecho", PROIBIDOS)
def test_glossario_do_vies_sem_termos_do_outro_estudo_nem_comandos(trecho):
    textos = [t for s in glossario.SECOES_VIES for t in (s["titulo"], s["intro"])]
    textos += [t for s in glossario.SECOES_VIES for e in s["entradas"] for t in (e["termo"], e["texto"])]
    assert not [t for t in textos if trecho in t]


@pytest.mark.parametrize("palavra", PROIBIDOS_PALAVRA)
def test_glossario_do_vies_sem_palavras_do_outro_estudo(palavra):
    textos = [t for s in glossario.SECOES_VIES for e in s["entradas"] for t in (s["titulo"], s["intro"], e["termo"], e["texto"])]
    assert not [t for t in textos if re.search(rf"\b{palavra}\b", t)]


# ---------------- fonte unica da relevancia v2 ----------------
def test_relevancia_v2_tem_os_textos_exatos():
    assert rotulos.RELEVANCIA_V2 == RELEVANCIA_V2
    assert list(rotulos.RELEVANCIA_V2) == ["alta", "media", "baixa", "fora_do_escopo"]


def test_glossario_le_a_relevancia_da_fonte_unica(monkeypatch):
    monkeypatch.setattr(rotulos, "RELEVANCIA_V2", {k: f"texto trocado {k}" for k in RELEVANCIA_V2})
    try:
        g = importlib.reload(glossario)
        textos = {e["id"]: e["texto"] for s in g.SECOES_VIES for e in s["entradas"]}
        for k, ancora in (("alta", "relevancia-alta"), ("media", "relevancia-media"), ("baixa", "relevancia-baixa"),
                          ("fora_do_escopo", "relevancia-fora-do-escopo")):
            assert textos[ancora] == f"Segundo o modelo: texto trocado {k}."
    finally:
        monkeypatch.undo()
        importlib.reload(glossario)


def test_legenda_do_template_nao_copia_os_textos_da_relevancia():
    legenda = (RAIZ / "painel" / "templates" / "_legenda_analises.html").read_text(encoding="utf-8")
    for texto in RELEVANCIA_V2.values():
        assert texto not in legenda
        assert texto[:40] not in legenda


# ---------------- pagina /sobre por banco ----------------
def test_secoes_e_subtitulo_por_banco():
    assert glossario.secoes("vies") is glossario.SECOES_VIES and glossario.subtitulo("vies") == SUBTITULO_VIES
    for banco in ("real", "demo", "simulado", None, "", "VIES", "vies "):
        assert glossario.secoes(banco) is glossario.SECOES, banco
        assert glossario.subtitulo(banco) == SUBTITULO_REAL, banco
    assert glossario.ids_de_ancoras() == glossario.ids_de_ancoras("real")
    assert glossario.ids_de_ancoras("vies") == _vies_ids()


def test_glossario_do_estudo_real_nao_mudou():
    """As ancoras e os textos do glossario do estudo real ficam como no F153 (conteudo legitimo preservado)."""
    assert hashlib.sha256(repr(glossario.SECOES).encode()).hexdigest()[:16] == "8188cc5f9a8f0243"


def _confere_vies(html):
    main = _main(html)
    assert f'<p class="sub">{SUBTITULO_VIES}</p>' in main and SUBTITULO_REAL not in main
    for s in glossario.SECOES_VIES:
        assert f'<h2 id="{s["id"]}">{s["titulo"]}</h2>' in main
        for e in s["entradas"]:
            assert f'<h3 id="{e["id"]}">{e["termo"]}</h3>' in main
            assert f'<p>{e["texto"]}</p>' in main, e["id"]
            assert f'<a href="#{e["id"]}">' in main
    for trecho in PROIBIDOS:
        assert trecho not in main, trecho
    for palavra in PROIBIDOS_PALAVRA:
        assert not re.search(rf"\b{palavra}\b", main), palavra
    assert "Números da visão geral e do funil" not in main and "Definição oficial" not in main


def test_pagina_sobre_do_vies(banco, tmp_path):  # noqa: F811
    _confere_vies(_cli(banco, tmp_path).get("/sobre").text)


def test_pagina_sobre_do_vies_sem_banco(tmp_path):
    cli = _cli(tmp_path / "naoexiste.db", tmp_path)
    r = cli.get("/sobre")
    assert r.status_code == 200
    _confere_vies(r.text)
    assert not (tmp_path / "naoexiste.db").exists()


def test_conteudo_do_sobre_do_vies_igual_para_todo_visitante(demo, tmp_path):  # noqa: F811
    """O conteudo da pagina (o <main>) e o mesmo para quem nao entrou e para cada grupo; o menu em volta muda com as permissoes."""
    app, contas, contas_db, _ = _painel(demo, tmp_path, banco="vies")
    painel = (TestClient(app), contas, None, contas_db)
    gravar_politica(contas, "vies", publica=True)
    visitante = TestClient(app).get("/sobre")
    assert visitante.status_code == 200
    _confere_vies(visitante.text)
    for grupo in ("Administrador", "Revisor", "Leitor"):
        _criar(painel, "u" + grupo.lower(), grupo)
        cli = TestClient(app)
        _entrar(cli, "u" + grupo.lower())
        logado = cli.get("/sobre")
        assert logado.status_code == 200, grupo
        assert _main(logado.text) == _main(visitante.text), grupo


@pytest.mark.parametrize("nome", ["real", "demo", "simulado"])
def test_pagina_sobre_dos_outros_bancos_com_o_glossario_do_estudo_real(nome, demo, tmp_path):  # noqa: F811
    from test_painel import _app
    db, raw = demo
    main = _main(TestClient(_app(db, raw, tmp_path, nome=nome)[0]).get("/sobre").text)
    assert f'<p class="sub">{SUBTITULO_REAL}</p>' in main and SUBTITULO_VIES not in main
    assert "Números da visão geral e do funil" in main and '<h3 id="obra">' not in main


# ---------------- links para o glossario ----------------
def _ancoras_linkadas():
    achadas = set()
    for p in list((RAIZ / "painel" / "templates").glob("*.html")) + list((RAIZ / "painel").glob("*.py")):
        achadas |= set(re.findall(r"/sobre#([a-z][a-z0-9_-]*)", p.read_text(encoding="utf-8")))
    return achadas


def test_todo_link_para_o_glossario_existe_nos_dois_glossarios():
    linkadas = _ancoras_linkadas()
    assert {"relevancia", "triagem-escopo"} <= linkadas
    assert not linkadas - set(glossario.ids_de_ancoras("real"))
    assert not linkadas - set(glossario.ids_de_ancoras("vies"))
