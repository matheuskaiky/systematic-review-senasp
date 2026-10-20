"""Testes das fontes locais. Três famílias, todas do próprio servidor: Inter (interface), Source Serif 4 (títulos e leitura) e
Observatorio Icones (subconjunto do Phosphor Icons, MIT, mais a marca do projeto).

NENHUMA usa @font-face: o CSS só nomeia as famílias e painel.js as carrega pela API FontFace (static/painel_fontes_trecho.js). Assim nenhum teste do
contrato precisa ser relaxado: painel.css continua sem `url(`, sem `@import` e sem `http`, e as páginas continuam com um só <link>. A fonte de ícones só
aparece quando o arquivo chega: o script acrescenta a classe `icones-ok` em <html> e TODO o CSS de ícones fica atrás dela."""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMINHOS = {"css": str(RAIZ / "painel/static"), "js": str(RAIZ / "painel/static/painel.js"), "fontes": str(RAIZ / "painel/static/fonts"), "templates": str(RAIZ / "painel/templates")}
LIMITE_BYTES = 150_000  # por arquivo; hoje: Inter ~48 KB, Source Serif 4 ~51 KB, ícones ~26 KB
ARQUIVOS = {
    "Inter": "inter-latin-wght-normal.woff2",
    "Source Serif 4": "source-serif-4-latin-wght-normal.woff2",
    "Observatorio Icones": "observatorio-icones-v2.woff2",
}
TOKENS = {"--fonte-base": "Inter", "--fonte-leitura": "Source Serif 4", "--fonte-icones": "Observatorio Icones"}
FOLHAS = ("painel", "analises", "solucoes", "classificadores", "metodologia", "relevancia", "triagem_escopo")


def _css(nome):
    return pathlib.Path(CAMINHOS["css"], f"{nome}.css").read_text(encoding="utf-8")


def _js():
    return pathlib.Path(CAMINHOS["js"]).read_text(encoding="utf-8")


def _regras(css):
    """[(seletores, corpo)] de todas as regras, descendo em @media."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []

    def varrer(s):
        i = 0
        while True:
            j = s.find("{", i)
            if j < 0:
                return
            pre, d, k = s[i:j].strip(), 1, j + 1
            while d and k < len(s):
                d += (s[k] == "{") - (s[k] == "}")
                k += 1
            corpo = s[j + 1:k - 1]
            if pre.startswith("@"):
                varrer(corpo)
            else:
                out.append(([x.strip() for x in pre.split(",")], corpo))
            i = k

    varrer(css)
    return out


def test_painel_css_continua_sem_funcao_de_endereco_e_sem_font_face():
    for nome in ("painel", "metodologia"):  # os dois que o contrato proíbe (o relatório estático embute metodologia.css)
        css = _css(nome).lower()
        assert "url(" not in css and "@font-face" not in css, nome
        assert "@import" not in css and "http" not in css, nome


def test_nenhuma_folha_usa_font_face():
    for nome in FOLHAS:
        assert "@font-face" not in _css(nome).lower(), nome


def test_familias_nomeadas_no_css_batem_com_as_carregadas_no_js():
    css, js = _css("painel"), _js()
    for token, familia in TOKENS.items():
        assert f'{token}: "{familia}"' in css, token
    for familia, arquivo in ARQUIVOS.items():
        assert f'nome: "{familia}"' in js and f"/static/fonts/{arquivo}" in js, familia


def test_js_de_fontes_respeita_as_proibicoes_de_painel_js():
    js = _js()
    for proibido in ("eval(", "innerHTML", "document.write", "XMLHttpRequest", "fetch(", "import(", "http://", "https://", "jQuery", "require("):
        assert proibido not in js, proibido


def test_js_liga_a_classe_icones_ok_so_quando_a_fonte_de_icones_chega():
    js = _js()
    assert "icones-ok" in js and "FontFace" in js and "classList.add" in js
    # a classe é acrescentada dentro do then() do load(), nunca antes (o nome também aparece no comentário de abertura, por isso
    # a comparação é com a CHAMADA que liga a classe, não com a primeira ocorrência do texto)
    chamada = 'classList.add("icones-ok")'
    assert chamada in js, "painel_fontes_trecho.js deve ligar html.icones-ok com classList.add(\"icones-ok\")"
    assert js.index("face.load()") < js.index(chamada)


def test_todo_css_de_icone_fica_atras_de_icones_ok():
    total = 0
    for nome in FOLHAS:
        for seletores, corpo in _regras(_css(nome)):
            if "font-family: var(--fonte-icones)" in corpo:
                total += 1
                for s in seletores:
                    assert s.startswith("html.icones-ok"), f"{nome}: regra com a fonte de ícones sem a classe icones-ok: {s}"
    assert total >= 20


# Pseudo-elementos que são LADRILHOS coloridos (fundo + borda + tamanho) e por isso existem ANTES da fonte, para a tela não saltar quando ela chega.
# Sem a fonte (JavaScript desligado, arquivo bloqueado) eles seriam quadrados coloridos vazios; a regra `html:not(.icones-ok) <seletor>` os esconde
# com visibility (o espaço continua reservado, então também não há salto de layout).
LADRILHOS = (
    ".menu .marca::before",
    ".menu-lista a::before",
    '.layout:has(.menu-lista a[aria-current="page"]) main > h1::before',
    ".aviso::before",
    ".vazio::before",
    ".solucao-destaque::before",
    ".retorno::before",
)


def test_ladrilhos_de_icone_ficam_invisiveis_sem_a_fonte():
    prefixo = "html:not(.icones-ok) "
    ocultos = set()
    for seletores, corpo in _regras(_css("painel")):
        if re.search(r"visibility\s*:\s*hidden", corpo):
            ocultos.update(s[len(prefixo):].strip() for s in seletores if s.startswith(prefixo))
    faltam = [s for s in LADRILHOS if s not in ocultos]
    assert not faltam, f"ladrilho colorido visível quando a fonte de ícones não chega: {faltam}"


def test_arquivos_de_fonte_existem_sao_woff2_e_leves():
    pasta = pathlib.Path(CAMINHOS["fontes"])
    for arquivo in ARQUIVOS.values():
        f = pasta / arquivo
        assert f.is_file(), f"fonte ausente: {f}"
        assert f.stat().st_size <= LIMITE_BYTES
        assert f.read_bytes()[:4] == b"wOF2"  # assinatura de woff2


def test_fonte_de_icones_tem_versao_no_nome_para_cache_de_um_ano():
    assert re.fullmatch(r"observatorio-icones-v\d+\.woff2", ARQUIVOS["Observatorio Icones"])


def test_licencas_junto_dos_arquivos():
    nomes = {p.name for p in pathlib.Path(CAMINHOS["fontes"]).iterdir()}
    assert any(n.startswith("LICENSE-Inter") for n in nomes)
    assert any(n.startswith("LICENSE-SourceSerif4") for n in nomes)
    assert any(n.startswith("LICENSE-PhosphorIcons") for n in nomes)


def test_nenhum_template_carrega_fonte_por_link():
    for t in pathlib.Path(CAMINHOS["templates"]).glob("*.html"):
        texto = t.read_text(encoding="utf-8").lower()
        assert 'rel="preload"' not in texto and ".woff" not in texto, t.name
