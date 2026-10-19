"""Teste anti-deriva do tema. Garante que os quatro lugares de troca de tema continuam coerentes, em painel.css e em analises.css.

Os quatro lugares: :root (claro), @media (prefers-color-scheme: dark) { :root } (sistema), e, dentro de @media screen, :root[data-theme="dark"] e
:root[data-theme="light"] (escolha no botão de tema). Em painel.css toda cor é #rrggbb ou var(--primitivo) (no máximo UM salto até o hexadecimal). Os blocos
forçados repetem o texto do claro/escuro do sistema, com uma exceção deliberada: os tokens que os testes do contrato comparam como TEXTO (LITERAIS) são
hexadecimal nos blocos :root simples e var(--primitivo) de igual valor nos blocos do botão de tema, onde hexadecimal é proibido; para esses o teste compara
o valor resolvido. Em analises.css o hexadecimal só pode ficar em :root simples, então as duas paletas de dados ficam guardadas no primeiro :root
(--an-claro-* e --an-escuro-*) e os blocos forçados só apontam para elas por var(): este teste confere que as guardas valem o mesmo que os blocos reais."""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMINHOS = {"painel": str(RAIZ / "painel/static/painel.css"), "analises": str(RAIZ / "painel/static/analises.css")}
# tokens que o contrato de testes compara como texto (mapa de calor, literais de impressão de analises.css, troca no escuro): hexadecimal nos :root simples
LITERAIS = ("--texto", "--superficie", "--acento", "--perigo", "--perigo-fundo", "--ok", "--ok-fundo", "--alerta", "--alerta-fundo",
            "--calor-1", "--calor-2", "--calor-3", "--calor-4")
TROCAM_NO_ESCURO = ("--fundo", "--superficie", "--texto", "--acento", "--ok", "--alerta", "--perigo", "--st-anunciado", "--calor-1", "--marca")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
UM_VAR = re.compile(r"var\((--[\w-]+)\)")


def _css(nome):
    texto = pathlib.Path(CAMINHOS[nome]).read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.S)  # comentários citam `:root {` e enganariam a busca


def _bloco(css, cabeca):
    """Texto entre as chaves do primeiro bloco que começa com `cabeca`."""
    i = css.index(cabeca)
    j = css.index("{", i)
    nivel, k = 1, j + 1
    while nivel:
        nivel += (css[k] == "{") - (css[k] == "}")
        k += 1
    return css[j + 1 : k - 1]


def _decls(bloco):
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", bloco)}


def _quatro(css):
    claro = _decls(_bloco(css, ":root {"))
    sistema = _decls(_bloco(_bloco(css, "@media (prefers-color-scheme: dark)"), ":root"))
    tela = _bloco(css, "@media screen")
    return claro, sistema, _decls(_bloco(tela, ':root[data-theme="dark"]')), _decls(_bloco(tela, ':root[data-theme="light"]'))


def _resolver(token, *camadas):
    env = {}
    for c in camadas:
        env.update(c)
    valor = env.get(token)
    for _ in range(14):
        m = UM_VAR.fullmatch((valor or "").strip())
        if not m:
            return (valor or "").strip().lower()
        valor = env.get(m.group(1))
    return ""


def _mesmo(token, no_botao, no_simples, *camadas):
    """Bloco do botão de tema e bloco simples concordam: texto idêntico ou, nos LITERAIS (hexadecimal no simples, var(--primitivo) no do botão), o mesmo
    hexadecimal depois de resolver."""
    if no_botao == no_simples:
        return True
    if token in LITERAIS and no_simples and HEX.fullmatch(no_simples) and (no_botao or "").startswith("var("):
        return _resolver(token, *camadas) == no_simples.lower()
    return False


def test_painel_css_quatro_lugares_coerentes():
    claro, sistema, f_escuro, f_claro = _quatro(_css("painel"))
    sem_cs = lambda d: {k: v for k, v in d.items() if k != "color-scheme"}
    # escuro escolhido no botão == escuro pedido pelo sistema (mesmos tokens, mesmo valor)
    assert set(sem_cs(f_escuro)) == set(sistema)
    for token, valor in sistema.items():
        assert _mesmo(token, f_escuro.get(token), valor, claro, f_escuro), f"escuro do botão diverge do escuro do sistema: {token} ('{f_escuro.get(token)}' x '{valor}')"
    # claro escolhido no botão restaura exatamente os valores claros dos tokens que o escuro troca
    assert set(sem_cs(f_claro)) == set(sistema)
    for token in sistema:
        assert _mesmo(token, f_claro.get(token), claro[token], claro, f_claro), f"claro do botão diverge do claro: {token} ('{f_claro.get(token)}' x '{claro[token]}')"


def test_painel_css_tokens_comparados_como_texto_sao_literais():
    """Um teste que compara token com token como TEXTO (sem resolver var()) só acerta se estes forem #rrggbb nos blocos :root simples."""
    css = _css("painel")
    claro, sistema, f_escuro, f_claro = _quatro(css)
    impressao = _decls(_bloco(_bloco(css, "@media print"), ":root"))
    for token in LITERAIS:
        for nome, bloco in (("claro", claro), ("escuro do sistema", sistema), ("impressão", impressao)):
            if token in bloco:
                assert HEX.fullmatch(bloco[token]), f"{token} precisa ser #rrggbb no :root {nome} (está '{bloco[token]}')"
        for nome, bloco in (("escuro do botão", f_escuro), ("claro do botão", f_claro)):
            if token in bloco:
                assert bloco[token].startswith("var("), f"{token} no bloco {nome} precisa ser var(--primitivo) (está '{bloco[token]}')"


def test_painel_css_escuro_troca_os_tokens_do_contrato_tambem_como_texto():
    claro, sistema, _, _ = _quatro(_css("painel"))
    for token in TROCAM_NO_ESCURO:
        assert token in sistema, f"o bloco escuro do sistema precisa listar {token}"
        assert sistema[token] != claro[token], f"{token}: o valor escuro é igual ao claro como texto"
        assert _resolver(token, claro, sistema) != _resolver(token, claro), f"{token}: o valor escuro resolvido é igual ao claro"


def test_painel_css_cadeias_de_cor_tem_no_maximo_um_salto():
    """var(--a) -> var(--b) -> #hex derruba um resolvedor que siga só um nível. Todo token de cor aponta direto para um primitivo."""
    css = _css("painel")
    claro, sistema, f_escuro, f_claro = _quatro(css)
    impressao = _decls(_bloco(_bloco(css, "@media print"), ":root"))
    estados = {"claro": claro, "escuro": {**claro, **sistema}, "escuro do botão": {**claro, **f_escuro}, "claro do botão": {**claro, **sistema, **f_claro}, "impressão": {**claro, **impressao}}
    for nome, env in estados.items():
        for token, valor in env.items():
            m = UM_VAR.fullmatch(valor.strip())
            if m:
                alvo = (env.get(m.group(1)) or "").strip()
                assert not UM_VAR.fullmatch(alvo), f"[{nome}] {token} -> {m.group(1)} -> {alvo}: cadeia de dois saltos"


def test_painel_css_blocos_forcados_so_com_var():
    _, _, f_escuro, f_claro = _quatro(_css("painel"))
    for bloco in (f_escuro, f_claro):
        for token, valor in bloco.items():
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", valor), f"hexadecimal em bloco forçado: {token}"


def test_analises_css_quatro_lugares_coerentes():
    claro, sistema, f_escuro, f_claro = _quatro(_css("analises"))
    # o que o escuro do sistema troca (hexadecimal) é o que a guarda --an-escuro-* guarda, e o bloco forçado só aponta para ela
    assert set(f_escuro) == set(sistema) == set(f_claro)
    for token, valor in sistema.items():
        nome = token[len("--an-"):]
        assert claro[f"--an-escuro-{nome}"].lower() == valor.lower(), f"guarda escura diverge do escuro do sistema: {token}"
        assert f_escuro[token] == f"var(--an-escuro-{nome})", f"escuro forçado de {token} precisa ser var(--an-escuro-{nome})"
        assert claro[f"--an-claro-{nome}"].lower() == claro[token].lower(), f"guarda clara diverge do claro: {token}"
        assert f_claro[token] == f"var(--an-claro-{nome})", f"claro forçado de {token} precisa ser var(--an-claro-{nome})"


def test_analises_css_forcados_so_com_var():
    _, _, f_escuro, f_claro = _quatro(_css("analises"))
    for bloco in (f_escuro, f_claro):
        for token, valor in bloco.items():
            assert valor.startswith("var(") and "#" not in valor, f"bloco forçado de analises.css deve ter só var(): {token}: {valor}"


def test_analises_css_impressao_repete_os_literais_claros():
    css = _css("analises")
    claro = _decls(_bloco(css, ":root {"))
    imp = _decls(_bloco(_bloco(css, "@media print"), ":root"))
    # a impressão é sempre clara: cada guarda clara e cada token de dados que ela repete vale o mesmo que no claro
    for token, valor in imp.items():
        if token.startswith("--an-claro-") or token.startswith("--an-escuro-"):
            continue
        base = claro.get(token)
        if base is not None and not base.startswith("var("):
            assert valor.lower() == base.lower(), f"impressão difere do claro: {token}"


def test_analises_css_impressao_vale_o_mesmo_que_painel_css_na_impressao():
    """Os literais de impressão de analises.css (tokens que no claro são var() de painel.css) precisam valer o que painel.css resolve na impressão."""
    painel, analises = _css("painel"), _css("analises")
    p_claro = _decls(_bloco(painel, ":root {"))
    p_imp = _decls(_bloco(_bloco(painel, "@media print"), ":root"))
    a_claro = _decls(_bloco(analises, ":root {"))
    a_imp = _decls(_bloco(_bloco(analises, "@media print"), ":root"))
    conferidos = 0
    for token, valor in a_claro.items():
        m = re.fullmatch(r"var\((--[\w-]+)\)", valor)
        if not m or not token.startswith("--an-"):
            continue
        esperado = _resolver(m.group(1), p_claro, p_imp)
        assert a_imp[token].lower() == esperado, f"{token}: analises.css na impressão '{a_imp[token]}' x painel.css '{esperado}'"
        conferidos += 1
    assert conferidos >= 10


def test_analises_css_repete_calor_e_impressao_de_painel_css_como_texto():
    """O pior caso dos testes do contrato: comparar o TEXTO dos tokens, sem resolver var(). Mapa de calor (claro e escuro) e os 14 pares de impressão."""
    painel, analises = _css("painel"), _css("analises")
    p_claro, p_escuro = _decls(_bloco(painel, ":root {")), _decls(_bloco(_bloco(painel, "@media (prefers-color-scheme: dark)"), ":root"))
    p_imp = _decls(_bloco(_bloco(painel, "@media print"), ":root"))
    a_claro, a_escuro = _decls(_bloco(analises, ":root {")), _decls(_bloco(_bloco(analises, "@media (prefers-color-scheme: dark)"), ":root"))
    a_imp = _decls(_bloco(_bloco(analises, "@media print"), ":root"))
    for i in range(1, 5):
        assert a_claro[f"--an-calor{i}"].lower() == p_claro[f"--calor-{i}"].lower(), f"--an-calor{i} x --calor-{i} (claro)"
        assert a_escuro[f"--an-calor{i}"].lower() == p_escuro[f"--calor-{i}"].lower(), f"--an-calor{i} x --calor-{i} (escuro)"
    pares = {"--an-texto": "--texto", "--an-suave": "--texto-suave", "--an-borda": "--borda", "--an-fundo": "--superficie", "--an-acento": "--acento",
             "--an-perigo": "--perigo", "--an-ok": "--ok", "--an-ok-fundo": "--ok-fundo", "--an-perigo-fundo": "--perigo-fundo", "--an-alerta": "--alerta",
             "--an-alerta-fundo": "--alerta-fundo", "--an-k-quase": "--ok", "--an-cal-alta": "--ok", "--an-descartado-ln": "--perigo"}
    for a, b in pares.items():
        assert a_imp[a].lower() == p_imp[b].lower(), f"impressão: {a} ('{a_imp[a]}') x {b} de painel.css ('{p_imp[b]}')"
    assert p_imp["--ok"] == p_claro["--ok"]
