import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from dominio.modelos import Achado, ConsultaWeb, Termo

_RASTREIO = ("fbclid", "gclid", "mc_cid", "mc_eid")   # tracking parameters
_CERCA = "`" * 3                                      # markdown code fence


def hash_chave(*partes):
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()


def normalizar_url(url):
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    caminho = p.path.rstrip("/") or "/"
    consulta = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                      if not (k.startswith("utm_") or k in _RASTREIO))
    return urlunsplit(((p.scheme or "https").lower(), host, caminho, urlencode(consulta), ""))


def dominio_de(url):
    return urlsplit(url).netloc.lower().removeprefix("www.")


def eh_oficial(dominio, sufixos=(".gov.br",)):
    return any(dominio == s.lstrip(".") or dominio.endswith(s) for s in sufixos)


def normalizar_texto(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def normalizar_status_final(valor, permitidos):
    """Regra unica (painel e importacao da planilha): espacos e maiusculas nao contam. None se vazio ou fora do vocabulario."""
    if valor is None:
        return None
    v = str(valor).strip().lower()
    return v if v in permitidos else None


def evidencia_confere(evidencia, texto):
    """True if the excerpt cited by the LLM literally (normalized) exists in the text that was sent."""
    e = normalizar_texto(evidencia)
    return bool(e) and e in normalizar_texto(texto)


def chave_dedup_titulo(titulo):
    t = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode().lower()
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", " ", t).strip().encode()).hexdigest()


def ano_do_resumo(resumo):
    anos = re.findall(r"\b(?:19|20)\d{2}\b", resumo or "")
    return int(anos[-1]) if anos else None


def gerar_consultas_web(modelos, tecnologias, ufs):
    saida = []
    for m in modelos:
        for uf, nome in ufs.items():
            for chave_tec, rotulo in tecnologias.items():
                saida.append(ConsultaWeb(
                    id=f"{m.id}-{uf}-{chave_tec}",
                    texto=m.template.format(tec=rotulo, nome=nome, uf=uf),
                    idioma=m.idioma, uf=uf, tecnologia=chave_tec,
                    modelo_id=m.id, perfil=m.perfil))
    return saida


def selecionar_candidatos(candidatos, politica):
    """Returns [(candidate, selected: bool, discard_reason | None)]. Records EVERY decision."""
    palavras = [normalizar_texto(p) for p in politica.palavras_chave]
    por_uf, saida = {}, []
    for c in sorted(candidatos, key=lambda c: (c.uf, -c.n_ocorrencias, c.melhor_posicao)):
        motivo = None
        if any(c.dominio == d or c.dominio.endswith("." + d) for d in politica.dominios_excluir):
            motivo = "dominio_excluido"
        elif politica.apenas_oficiais and not c.fonte_oficial:
            motivo = "nao_oficial"
        elif palavras and not any(p in normalizar_texto(f"{c.titulo} {c.snippet}") for p in palavras):
            motivo = "prefiltro_palavras"
        elif por_uf.get(c.uf, 0) >= politica.max_urls_por_uf:
            motivo = "limite_por_uf"
        if motivo is None:
            por_uf[c.uf] = por_uf.get(c.uf, 0) + 1
        saida.append((c, motivo is None, motivo))
    return saida


def interpretar_json_classificacao(texto):
    """Converts the LLM output into (relevant, [Achado], json_valid). Tolerant of code fences and <think>."""
    t = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S).strip()
    t = re.sub(rf"^{_CERCA}(?:json)?\s*|\s*{_CERCA}$", "", t, flags=re.M).strip()
    dados = None
    try:
        dados = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if m:
            try:
                dados = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    if not isinstance(dados, dict) or not isinstance(dados.get("achados"), list):
        return False, [], False
    achados = [
        Achado(tecnologia=str(a.get("tecnologia", "")), status=str(a.get("status", "")),
               fornecedor=str(a.get("fornecedor") or ""), menciona_lgpd=bool(a.get("menciona_lgpd")),
               evidencia=str(a.get("evidencia") or ""), confianca=str(a.get("confianca", "baixa")))
        for a in dados["achados"] if isinstance(a, dict)
    ]
    return bool(dados.get("relevante", bool(achados))), achados, True


def termo_composto(id, pai, contexto, operador="AND"):
    """Consulta combinada: o termo `pai` ligado a um contexto (ex.: '"public security" OR police').

    O contexto vai entre parenteses; o termo composto herda idioma e grupo do pai e guarda o id dele em `pai`.
    """
    return Termo(id, f"{pai.query} {operador} ({contexto})", pai.idioma, pai.grupo, pai.id)


def escolher_auditoria(decisoes, n, semente):
    """Amostra reprodutivel de itens descartados pelo pre-filtro de palavras-chave, para auditar o filtro.

    `decisoes` e a saida de selecionar_candidatos. A ordem vem de hash_chave(semente, url_id, uf), sem aleatoriedade
    externa: a mesma semente e os mesmos candidatos dao sempre a mesma amostra.
    """
    if n <= 0:
        return []
    descartados = [d for d in decisoes if d[2] == "prefiltro_palavras"]
    descartados.sort(key=lambda d: hash_chave(semente, d[0].url_id, d[0].uf))
    return descartados[:n]


_PALAVRAS_VAZIAS = {"de", "da", "do", "das", "dos", "para", "com", "em", "por", "uma", "como"}
_LGPD = re.compile(r"\blgpd\b|lei geral de protecao de dados|protecao de dados|dados pessoais")


def palavras_chave_tecnologia(rotulo):
    """Palavras do rotulo de uma tecnologia (config/vocabulario.TECNOLOGIAS), normalizadas e sem o plural final.

    Heuristica de priorizacao da revisao, nao decisao: e o que o proprio vocabulario da pesquisa diz sobre a tecnologia.
    """
    palavras = {w for w in normalizar_texto(rotulo).split() if len(w) >= 4 and w not in _PALAVRAS_VAZIAS}
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in palavras}


def evidencia_cita_termo(evidencia, palavras):
    """True se o trecho citado pelo modelo contem alguma das palavras (comparacao normalizada, sem acento)."""
    e = normalizar_texto(evidencia)
    return any(p in e for p in palavras)


def evidencia_cita_lgpd(evidencia):
    """True se o trecho cita LGPD, a lei geral de protecao de dados ou protecao de dados (o criterio do prompt)."""
    return bool(_LGPD.search(normalizar_texto(evidencia)))
