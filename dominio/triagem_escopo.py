"""Triagem de escopo por LLM: parte pura (sem I/O).

Contem o esquema da resposta, a mensagem do usuario, as conferencias automaticas depois de cada resposta, a estimativa de
custo e a escolha deterministica de amostras. Os textos do prompt e os vocabularios ficam em `config/triagem_escopo.py`
e chegam aqui por um `ConfigTriagem`.

Um "item" e um dicionario simples (o repositorio devolve assim):
    comuns:  item_id, fonte ("artigo" | "web"), uf ("" para artigo), provedor, titulo, resumo, host, termos (lista de textos)
    artigo:  autores_publicacao, ano, link, termos_ids, origens_manuais
    web:     url, tecnologia, tecnologias, modelos_ids, selecionado (bool), motivo_descarte
"""
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field

from dominio.relevancia import NIVEIS, pontuar_relevancia

ELEGIVEL, QUARENTENA, EXCLUIDO = "elegivel", "quarentena", "excluido"
CONFIANCA_ALTA = "alta"
SEM_CATEGORIA = "NENHUMA"            # valor do enum quando nao ha categoria (o esquema nao usa null)
CATEGORIA_GEOGRAFICA = "FORA_DO_RECORTE_GEOGRAFICO"
CATEGORIA_TEMPORAL = "FORA_DO_RECORTE_TEMPORAL"
MAX_PALAVRAS_SINAL = 3
RELEVANCIAS_CURTA = ("alta", "media", "baixa")
STATUS_DA_RELEVANCIA = {"alta": ELEGIVEL, "media": QUARENTENA, "baixa": EXCLUIDO}   # triagem curta (D80)
FONTES = ("artigo", "web")
# Avisos sobre campos AUXILIARES (termo gerador e sinal negativo): o campo vira nulo e o aviso fica em `problemas`, mas o
# veredito (status, motivo) segue valido. Os demais problemas (enum, id, categoria, recorte) invalidam a linha.
AVISOS_DE_CAMPO_AUXILIAR = frozenset({"termo_gerador_fora_da_lista", "sinal_negativo_longo", "sinal_negativo_nao_literal"})


@dataclass(frozen=True)
class ConfigTriagem:
    versao: str
    sistema_artigo: str
    sistema_web: str
    usuario_template: str
    origem_artigo: str
    origem_web: str
    status: tuple
    confianca: tuple
    categorias_motivo: tuple
    dominios_tematicos: tuple
    escopos_geograficos: tuple
    tipos_documento: tuple
    lote_padrao: int = 10
    lote_maximo: int = 50
    janela_contexto_tokens: int = 1_048_576
    ano_minimo: int = 2022
    snippet_max_chars: int = 1200
    max_custo_padrao_usd: float = 0.20
    caracteres_por_token: float = 3.4
    tokens_metadados_por_item: int = 50
    tokens_fixos_por_chamada: int = 1500
    saida_por_item: dict = field(default_factory=lambda: {"baixo": 90, "medio": 120, "alto": 160})
    raciocinio_por_chamada: dict = field(default_factory=lambda: {"baixo": 100, "medio": 300, "alto": 600})
    curta: bool = False

    def como_dict(self):
        """Tudo que define a triagem, para gravar no config_json da execucao."""
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


# ---------------------------------------------------------------- utilidades
def _norm(texto):
    """Minusculas, sem acentos, tudo que nao for letra ou numero vira espaco (comparacao tolerante)."""
    if texto is None:
        return ""
    sem = "".join(c for c in unicodedata.normalize("NFKD", str(texto).lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem).strip()


def chave_item(item):
    """Identificador do item dentro de um lote (ecoado pelo modelo): `item_id` para artigo, `item_id-UF` para web."""
    return f"{item['item_id']}-{item['uf']}" if item.get("uf") else str(item["item_id"])


def rotulo_fonte(provedor):
    """Nome da fonte que o modelo ve: o proprio nome do provedor, sem lista de provedores no dominio (trocar de provedor
    nao exige mudar este arquivo). Item sem provedor, ou de busca manual, vira `manual`."""
    return "manual" if provedor in (None, "", "manual") else str(provedor)


def atomo_do_modelo_de_consulta(template):
    """Palavras fixas de um modelo de consulta web: o template sem os marcadores ({tec}, {nome}, {uf}, {cidade}).
    Sao os trechos que o pesquisador pode trocar; UF, estado e cidade nao sao 'termos'."""
    sem = re.sub(r"\{[a-z_]+\}", " ", template or "")
    return re.sub(r"\s+", " ", sem).strip()


def montar_termos(item, mapas):
    """Textos das consultas que acharam o item, na ordem em que apareceram.

    `mapas`: {"artigo": {termo_id: texto}, "web": {"tecnologias": {chave: rotulo}, "modelos": {modelo_id: atomo}}}.
    Artigo: o texto de cada termo (Scholar ou busca manual). Web: os 'atomos' alteraveis da consulta, isto e, o rotulo de
    cada tecnologia que achou a URL e as palavras fixas de cada modelo de consulta (nao UF, estado ou cidade)."""
    if item["fonte"] == "artigo":
        m = mapas.get("artigo", {})
        textos = [m.get(t, t) for t in item.get("termos_ids", [])]
    else:
        m = mapas.get("web", {})
        tec = [m.get("tecnologias", {}).get(t, t) for t in item.get("tecnologias", [])]
        mod = [m.get("modelos", {}).get(t, t) for t in item.get("modelos_ids", [])]
        textos = tec + mod
    return list(dict.fromkeys(t for t in textos if t))


def enriquecer_termos(itens, mapas):
    """Copia dos itens com a lista `termos` preenchida."""
    return [{**i, "termos": montar_termos(i, mapas)} for i in itens]


def resumo_enviado(item, config):
    return (item.get("resumo") or "")[:config.snippet_max_chars]


# ---------------------------------------------------------------- esquema e mensagem
def montar_esquema(config, ids=None):
    """JSON Schema NEUTRO da resposta: um objeto `{"itens": [...]}` com um objeto por item e vocabularios fechados.
    A raiz e um objeto (como no classificador, que ja foi aceito pela API); a lista fica em `itens`. Com `ids`, o campo
    `id` tambem e um enum fechado (so os ids do lote). Nada e `null`: onde nao ha valor, texto vazio (ou `NENHUMA`).
    Na triagem curta (config.curta), cada objeto tem so id, relevancia, confianca e escopo_geografico."""
    id_prop = {"type": "string", "description": "the item id, copied unchanged"}
    if ids:
        id_prop["enum"] = [str(i) for i in ids]
    if config.curta:
        objeto = {
            "type": "object",
            "properties": {"id": id_prop,
                           "relevancia": {"type": "string", "enum": list(RELEVANCIAS_CURTA)},
                           "confianca": {"type": "string", "enum": list(config.confianca)},
                           "escopo_geografico": {"type": "string", "enum": list(config.escopos_geograficos)}},
            "required": ["id", "relevancia", "confianca", "escopo_geografico"]}
    else:
        objeto = {
            "type": "object",
            "properties": {
                "id": id_prop,
                "status": {"type": "string", "enum": list(config.status)},
                "confianca": {"type": "string", "enum": list(config.confianca)},
                "categoria_motivo": {"type": "string", "enum": list(config.categorias_motivo) + [SEM_CATEGORIA]},
                "justificativa": {"type": "string", "description": "at most 20 words, in Brazilian Portuguese"},
                "termo_gerador_ruido": {"type": "string",
                                        "description": "one of the item's query_terms, copied exactly; empty string if none"},
                "sinal_negativo": {"type": "string",
                                   "description": "at most 3 words copied literally from title or snippet; empty string if none"},
                "dominio_tematico": {"type": "string", "enum": list(config.dominios_tematicos)},
                "escopo_geografico": {"type": "string", "enum": list(config.escopos_geograficos)},
                "tipo_documento": {"type": "string", "enum": list(config.tipos_documento)},
            },
            "required": ["id", "status", "confianca", "categoria_motivo", "justificativa", "termo_gerador_ruido",
                         "sinal_negativo", "dominio_tematico", "escopo_geografico", "tipo_documento"],
        }
    return {"type": "object", "properties": {"itens": {"type": "array", "items": objeto}}, "required": ["itens"]}


def linha_do_item(item, config):
    """O que o modelo ve de um item (um objeto JSON por linha)."""
    if config.curta:
        return {"id": chave_item(item), "titulo": item.get("titulo") or "", "resumo": resumo_enviado(item, config),
                "ano": item.get("ano")}
    base = {"id": chave_item(item), "fonte": rotulo_fonte(item.get("provedor")), "query_terms": list(item.get("termos", [])),
            "titulo": item.get("titulo") or "", "resumo": resumo_enviado(item, config)}
    if item["fonte"] == "artigo":
        base.update({"autores_publicacao": item.get("autores_publicacao") or "", "ano": item.get("ano"),
                     "host": item.get("host") or ""})
    else:
        base.update({"uf": item.get("uf"), "tecnologia": item.get("tecnologia") or "", "url": item.get("url") or "",
                     "host": item.get("host") or ""})
    return base


def sistema_da_fonte(fonte, config):
    return config.sistema_artigo if fonte == "artigo" else config.sistema_web


def montar_mensagem_usuario(itens, config):
    fonte = itens[0]["fonte"]
    linhas = "\n".join(json.dumps(linha_do_item(i, config), ensure_ascii=False) for i in itens)
    origem = config.origem_artigo if fonte == "artigo" else config.origem_web
    return config.usuario_template.format(n=len(itens), origem=origem, linhas=linhas)


# ---------------------------------------------------------------- conferencias automaticas
def _vazio(v):
    return v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none"))


def _lista_de_itens(resposta):
    """Aceita o texto JSON ou o objeto ja lido; a lista pode estar na raiz ou em `itens`. None se nao for lista."""
    if isinstance(resposta, (str, bytes)):
        try:
            resposta = json.loads(resposta)
        except ValueError:
            return None
    if isinstance(resposta, dict):
        resposta = resposta.get("itens")
    return resposta if isinstance(resposta, list) else None


def _ano(item):
    try:
        return int(item.get("ano")) if item.get("ano") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def fora_do_recorte_temporal(item, config):
    """O artigo tem ano conhecido anterior a `config.ano_minimo`? Esses vao para a triagem curta (D80)."""
    ano = _ano(item)
    return ano is not None and ano < config.ano_minimo


def _linha_base(item):
    return {"item_id": item["item_id"], "fonte": item["fonte"], "uf": item.get("uf") or "",
            "provedor": item.get("provedor"), "termos_consulta": list(item.get("termos", [])),
            "status": QUARENTENA, "status_bruto": None, "confianca": None, "categoria_motivo": None,
            "justificativa": None, "termo_gerador": None, "sinal_negativo": None, "dominio_tematico": None,
            "escopo_geografico": None, "tipo_documento": None, "valido": False, "problemas": []}


def _conferir(item, obj, config):
    linha = _linha_base(item)
    problemas = linha["problemas"]
    bruto = obj.get("status")
    if isinstance(bruto, str):
        bruto = bruto.strip().lower()
    if bruto in config.status:
        linha["status_bruto"] = status = bruto
    else:
        linha["status_bruto"] = bruto if isinstance(bruto, str) and bruto else None
        status = QUARENTENA
        problemas.append("status_invalido")
    conf = obj.get("confianca")
    conf = conf.strip().lower() if isinstance(conf, str) else conf
    if conf in config.confianca:
        linha["confianca"] = conf
    else:
        problemas.append("confianca_invalida")
    for campo, vocab in (("dominio_tematico", config.dominios_tematicos),
                         ("escopo_geografico", config.escopos_geograficos), ("tipo_documento", config.tipos_documento)):
        v = obj.get(campo)
        v = v.strip().lower() if isinstance(v, str) else v
        if v in vocab:
            linha[campo] = v
        else:
            problemas.append(f"{campo}_invalido")
    just = obj.get("justificativa")
    linha["justificativa"] = just.strip() if isinstance(just, str) and just.strip() else None

    cat = obj.get("categoria_motivo")
    cat = cat.strip() if isinstance(cat, str) else cat
    if _vazio(cat) or cat == SEM_CATEGORIA:
        cat = None
    elif cat not in config.categorias_motivo:
        problemas.append("categoria_motivo_invalida")
        cat = None

    # ---- regras de seguranca e recortes ----
    ano = _ano(item)
    if status == EXCLUIDO:
        if cat == CATEGORIA_TEMPORAL:
            # a regra da data satisfaz a exigencia de certeza, desde que o ano seja conhecido e anterior ao minimo
            if ano is None:
                status = QUARENTENA
                problemas.append("recorte_temporal_sem_ano")
            elif ano >= config.ano_minimo:
                status = QUARENTENA
                problemas.append("recorte_temporal_incoerente_com_o_ano")
            elif linha["confianca"] != CONFIANCA_ALTA:
                status = QUARENTENA
        elif linha["confianca"] != CONFIANCA_ALTA:
            status = QUARENTENA
        elif cat == CATEGORIA_GEOGRAFICA:
            status = QUARENTENA
    elif cat == CATEGORIA_TEMPORAL and ano is not None and ano >= config.ano_minimo:
        problemas.append("recorte_temporal_incoerente_com_o_ano")     # a conferencia vale para qualquer status
    if status == EXCLUIDO and cat is None:
        status = QUARENTENA                    # exclusao sem categoria valida nao e certeza: fica em quarentena
    linha["status"] = status

    if status == ELEGIVEL:
        if cat is not None:
            problemas.append("categoria_motivo_com_elegivel")
            cat = None
    elif cat is None and "categoria_motivo_invalida" not in problemas:
        problemas.append("categoria_motivo_ausente")
    linha["categoria_motivo"] = cat

    # ---- termo gerador: precisa ser um dos termos DESTE item ----
    termo = obj.get("termo_gerador_ruido")
    if status != ELEGIVEL and not _vazio(termo):
        por_norm = {_norm(t): t for t in item.get("termos", [])}
        achado = por_norm.get(_norm(termo)) if isinstance(termo, str) else None
        if achado is None:
            problemas.append("termo_gerador_fora_da_lista")
        linha["termo_gerador"] = achado

    # ---- sinal negativo: ate 3 palavras, literal no titulo ou resumo enviados ----
    sinal = obj.get("sinal_negativo")
    if status != ELEGIVEL and not _vazio(sinal):
        s = _norm(sinal) if isinstance(sinal, str) else ""
        texto = " " + _norm(f"{item.get('titulo') or ''} {resumo_enviado(item, config)}") + " "
        if not s or len(s.split()) > MAX_PALAVRAS_SINAL:
            problemas.append("sinal_negativo_longo")
        elif f" {s} " not in texto:
            problemas.append("sinal_negativo_nao_literal")
        else:
            linha["sinal_negativo"] = sinal.strip()
    linha["valido"] = not [p for p in problemas if p not in AVISOS_DE_CAMPO_AUXILIAR]
    return linha


def _conferir_curta(item, obj, config):
    """Triagem curta (D80): a relevancia vira o status (alta: elegivel; media: quarentena; baixa: excluido, so com confianca
    alta, como no t2); quarentena e excluido levam o motivo FORA_DO_RECORTE_TEMPORAL. Os demais campos ficam nulos."""
    linha = _linha_base(item)
    problemas = linha["problemas"]
    rel = obj.get("relevancia")
    rel = rel.strip().lower() if isinstance(rel, str) else None
    if rel in STATUS_DA_RELEVANCIA:
        linha["status_bruto"] = status = STATUS_DA_RELEVANCIA[rel]
    else:
        linha["status_bruto"] = rel or None
        status = QUARENTENA
        problemas.append("relevancia_invalida")
    conf = obj.get("confianca")
    conf = conf.strip().lower() if isinstance(conf, str) else None
    if conf in config.confianca:
        linha["confianca"] = conf
    else:
        problemas.append("confianca_invalida")
    esc = obj.get("escopo_geografico")
    esc = esc.strip().lower() if isinstance(esc, str) else None
    if esc in config.escopos_geograficos:
        linha["escopo_geografico"] = esc
    else:
        problemas.append("escopo_geografico_invalido")
    if status == EXCLUIDO and linha["confianca"] != CONFIANCA_ALTA:
        status = QUARENTENA                  # regra de seguranca do t2: excluir exige confianca alta
    if fora_do_recorte_temporal(item, config):
        linha["categoria_motivo"] = None if status == ELEGIVEL else CATEGORIA_TEMPORAL
    else:
        status = QUARENTENA
        problemas.append("triagem_curta_fora_do_recorte")
    linha["status"] = status
    linha["valido"] = not problemas
    return linha


def validar_resposta(itens, resposta_json, config):
    """Confere a resposta de UM lote. Devolve `(linhas, extras)`: uma linha por item de entrada, na ordem da entrada
    (itens que o modelo nao devolveu viram linhas invalidas em quarentena, nunca somem) e `extras`
    = {"json_valido": bool, "ids_ausentes": [...], "ids_duplicados": [...], "ids_desconhecidos": [...]}.

    As linhas seguem as colunas de `triagem_escopo` (`valido` e booleano e `problemas` e uma lista de codigos)."""
    objs = _lista_de_itens(resposta_json)
    extras = {"json_valido": objs is not None, "ids_ausentes": [], "ids_duplicados": [], "ids_desconhecidos": []}
    chaves = [chave_item(i) for i in itens]
    por_id, vistos = {}, set()
    for o in objs or []:
        if not isinstance(o, dict):
            continue
        ident = str(o.get("id", "")).strip()
        if ident not in chaves:
            extras["ids_desconhecidos"].append(ident)
        elif ident in por_id:
            if ident not in extras["ids_duplicados"]:
                extras["ids_duplicados"].append(ident)
        else:
            por_id[ident] = o
    linhas = []
    for item, chave in zip(itens, chaves):
        if chave not in por_id:
            linha = _linha_base(item)
            linha["problemas"].append("resposta_json_invalida" if objs is None else "id_ausente_na_resposta")
            extras["ids_ausentes"].append(chave)
        else:
            linha = (_conferir_curta if config.curta else _conferir)(item, por_id[chave], config)
            if chave in extras["ids_duplicados"]:
                linha["problemas"].append("id_duplicado_na_resposta")
                linha["valido"] = False
        linhas.append(linha)
    return linhas, extras


# ---------------------------------------------------------------- custo
def _tokens_item(item, config):
    chars = len(item.get("titulo") or "") + len(resumo_enviado(item, config))
    if not config.curta:
        chars += len(item.get("autores_publicacao") or "") + sum(len(t) for t in item.get("termos", []))
    return math.ceil(chars / config.caracteres_por_token) + config.tokens_metadados_por_item


def lotes(itens, tamanho):
    return [itens[i:i + tamanho] for i in range(0, len(itens), tamanho)]


def tokens_entrada_lote(itens_do_lote, config):
    return config.tokens_fixos_por_chamada + sum(_tokens_item(i, config) for i in itens_do_lote)


def custo_lote_usd(itens_do_lote, precos, config, nivel="alto"):
    """Custo estimado de UMA chamada (ordem de grandeza). `precos`: {"entrada": US$/M, "saida": US$/M}."""
    t_in = tokens_entrada_lote(itens_do_lote, config)
    t_out = config.saida_por_item[nivel] * len(itens_do_lote) + config.raciocinio_por_chamada[nivel]
    return (t_in * precos["entrada"] + t_out * precos["saida"]) / 1_000_000


def estimar_custo(itens, lote, precos, config):
    """Chamadas, tokens e custo (baixo, medio e alto). Sem nenhuma chamada. Tokens a `caracteres_por_token` (sem o
    tokenizador oficial), mais `tokens_metadados_por_item` por item e `tokens_fixos_por_chamada` por chamada."""
    grupos = lotes(list(itens), lote)
    entrada = [tokens_entrada_lote(g, config) for g in grupos]
    saida = {n: sum(config.saida_por_item[n] * len(g) + config.raciocinio_por_chamada[n] for g in grupos)
             for n in ("baixo", "medio", "alto")}
    t_in = sum(entrada)
    maior = max(entrada, default=0)
    return {"itens": len(itens), "lote": lote, "chamadas": len(grupos), "tokens_entrada": t_in,
            "tokens_entrada_por_chamada": round(t_in / len(grupos)) if grupos else 0,
            "tokens_entrada_maior_chamada": maior,
            "pct_janela_contexto": round(100 * maior / config.janela_contexto_tokens, 2),
            "niveis": {n: {"tokens_saida": saida[n],
                           "custo_usd": (t_in * precos["entrada"] + saida[n] * precos["saida"]) / 1_000_000}
                       for n in saida}}


# ---------------------------------------------------------------- amostra
def _h(semente, chave):
    return hashlib.sha1(f"{semente}|{chave}".encode("utf-8")).hexdigest()


def _estratos(item, fonte):
    """(estrato principal, estrato secundario) de um item, para espalhar a amostra."""
    if fonte == "artigo":
        nivel = pontuar_relevancia(item.get("titulo"), item.get("resumo"), item.get("autores_publicacao"),
                                   item.get("link"))["nivel"]
        termos = item.get("termos_ids") or item.get("termos") or [""]
        return NIVEIS.index(nivel), str(termos[0])
    return (0 if item.get("selecionado") else 1), f"{item.get('uf')}|{item.get('tecnologia')}"


def escolher_amostra(itens, n, estratificar, semente):
    """Amostra DETERMINISTICA de `n` itens (sem aleatoriedade: ordena por hash de `semente` e da chave do item).
    Mesma entrada e mesma semente dao a mesma amostra; outra semente, outra amostra. Devolve na ordem do hash.

    Com `estratificar`: artigos, por nivel de relevancia (alta, media, baixa, cotas iguais) e, dentro de cada nivel, em
    rodizio entre os termos; web, por selecionado para download ou descartado (metade para cada) e, dentro, em rodizio entre
    UF e tecnologia. Um estrato com poucos itens cede a sobra aos demais."""
    itens = list(itens)
    ordenados = sorted(itens, key=lambda i: _h(semente, chave_item(i) + "|" + i["fonte"]))
    if n is None or n >= len(ordenados):
        return ordenados
    if not estratificar or not ordenados:
        return ordenados[:n]
    fonte = ordenados[0]["fonte"]
    grupos = {}
    for i in ordenados:
        p, s = _estratos(i, fonte)
        grupos.setdefault(p, {}).setdefault(s, []).append(i)
    # cotas iguais por estrato principal (a sobra de um estrato pequeno passa aos outros), em ordem de chave
    cota = {p: 0 for p in grupos}
    tamanho = {p: sum(len(v) for v in g.values()) for p, g in grupos.items()}
    restante = n
    while restante > 0:
        abertos = [p for p in sorted(grupos) if cota[p] < tamanho[p]]
        if not abertos:
            break
        for p in abertos:
            if restante == 0:
                break
            cota[p] += 1
            restante -= 1
    escolhidos = []
    for p in sorted(grupos):
        filas = [list(v) for _, v in sorted(grupos[p].items(), key=lambda kv: _h(semente, "estrato|" + kv[0]))]
        pegos = 0
        while pegos < cota[p]:
            for f in filas:
                if f and pegos < cota[p]:
                    escolhidos.append(f.pop(0))
                    pegos += 1
    return sorted(escolhidos, key=lambda i: _h(semente, chave_item(i) + "|" + i["fonte"]))
