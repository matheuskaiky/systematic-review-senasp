"""Pacote de uma execucao enviada do computador local para a nuvem (D85, D99, D100): o formato e a conferencia, sem I/O.

O pacote leva so os dados da coleta de uma execucao (nunca os arquivos brutos nem as decisoes humanas), com os numeros
locais de cada linha; a nuvem renumera ao juntar. Uma classificacao pode usar a pagina baixada noutra execucao (--de):
essa pagina vai em `externas`, com a execucao dela, e a nuvem a acha pela correspondencia daquela execucao. Formato estrito: as tabelas e as colunas sao exatamente as listadas
aqui; o que faltar ou sobrar e recusado, nunca adivinhado."""
import math
import re

class ErroPacote(Exception):
    """Pacote recusado, com a mensagem para quem enviou (nada foi gravado)."""


VERSAO = 2                       # 2: leva a busca de literatura na web (referencias_web e ocorrencias_web)
MAX_TEXTO = 5_000_000            # caracteres por campo de texto (a maior resposta do classificador hoje fica muito abaixo)
RE_RUN_ID = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{6}")
MAIOR_ID = 9223372036854775807

# campos de decisao humana dentro de tabelas da coleta: nunca saem do local nem sao tocados na nuvem
CAMPOS_HUMANOS = {
    "execucoes": ("no_relatorio", "motivo_exclusao", "excluida_em"),
    "achados": ("verificado", "status_final", "verificado_por", "verificado_em", "observacao"),
}
# colunas so da triagem da busca de vies (D116): o banco `vies` nunca e enviado, e o pacote versao 2 continua com o
# formato de antes (a nuvem com o codigo anterior aceita os pacotes de agora)
CAMPOS_SO_DO_VIES = {"triagem_escopo": ("tipo_fonte", "pais_escopo", "topicos", "eixo")}

# compartilhadas entre execucoes: juntadas pela chave natural; a da nuvem, se existe, nunca muda (D100)
COMPARTILHADAS = {
    "urls": ("url_id", "url_normalizada",
             ("url_id", "url_normalizada", "url_original", "dominio", "fonte_oficial", "primeira_vez_run", "primeira_vez_em")),
    "artigos": ("artigo_id", "chave_dedup",
                ("artigo_id", "chave_dedup", "titulo", "link", "autores_publicacao", "ano", "snippet", "citacoes",
                 "primeira_vez_run", "primeira_vez_em")),
    "referencias_web": ("referencia_id", "url_normalizada",
                        ("referencia_id", "url_normalizada", "url_original", "dominio", "primeira_vez_run", "primeira_vez_em")),
}

# tabelas da execucao, na ordem em que a nuvem as junta (pai antes do filho): (tabela, chave, colunas, referencias).
# chave: o numero local da linha (renumerado na nuvem) ou None quando a chave primaria ja e natural (tabela, colunas).
# referencias: coluna -> tabela do pacote a que ela aponta (None permitido so nas marcadas com "?").
DA_EXECUCAO = (
    ("execucoes", None, ("run_id", "iniciado_em", "finalizado_em", "comando", "config_hash", "config_json", "commit_git",
                         "status", "metricas_json", "run_origem", "ambiente_json"), {}),
    ("execucoes_retomadas", "retomada_id", ("retomada_id", "run_id", "retomado_em", "commit_git", "ambiente_json"), {}),
    ("metricas_run", None, ("run_id", "chave", "valor"), {}),
    ("saldos", "id", ("id", "run_id", "provedor", "momento", "valor", "registrado_em"), {}),
    ("chamadas", "chamada_id", ("chamada_id", "run_id", "etapa", "provedor", "operacao", "alvo_tipo", "alvo_id", "uf", "pagina",
                                "parametros_json", "chave_idempotencia", "requisitado_em", "http_status", "sucesso",
                                "tentativas", "latencia_ms", "id_externo", "total_reportado", "n_retornados", "n_novos",
                                "tokens_entrada", "tokens_saida", "custo_usd", "erro", "raw_path", "raw_sha256",
                                "extras_json"), {}),
    ("ocorrencias", "ocorrencia_id", ("ocorrencia_id", "chamada_id", "artigo_id", "termo_id", "run_id", "posicao",
                                      "citacoes_no_momento"), {"chamada_id": "chamadas", "artigo_id": "artigos"}),
    ("ocorrencias_web", "ocorrencia_id", ("ocorrencia_id", "chamada_id", "run_id", "conjunto", "consulta_id", "referencia_id",
                                          "posicao", "titulo", "snippet", "data_pub"),
     {"chamada_id": "chamadas", "referencia_id": "referencias_web"}),
    ("resultados_web", "resultado_id", ("resultado_id", "chamada_id", "run_id", "consulta_id", "uf", "tecnologia", "perfil",
                                        "url_id", "posicao", "titulo", "snippet", "data_pub", "cidade"),
     {"chamada_id": "chamadas", "url_id": "urls"}),
    ("selecao_download", None, ("run_id", "url_id", "uf", "selecionada", "motivo", "auditoria"), {"url_id": "urls"}),
    ("paginas", "pagina_id", ("pagina_id", "run_id", "url_id", "chamada_id", "url_final", "http_status", "content_type",
                              "n_bytes", "truncado", "texto_path", "n_chars", "extrator", "extracao_ok", "motivo_falha",
                              "dominio_final", "fonte_oficial_final"), {"url_id": "urls", "chamada_id": "chamadas"}),
    ("classificacoes", "classificacao_id", ("classificacao_id", "chamada_id", "run_id", "url_id", "pagina_id", "uf",
                                            "origem_texto", "texto_truncado", "n_chars_enviados", "classificador", "cidade",
                                            "prompt_versao", "relevante", "json_valido", "n_achados", "n_achados_invalidos",
                                            "resposta_texto"),
     {"chamada_id": "chamadas", "url_id": "urls", "pagina_id": "paginas?"}),
    ("achados", "achado_id", ("achado_id", "classificacao_id", "uf", "tecnologia", "status_reportado", "fornecedor",
                              "menciona_lgpd", "evidencia", "evidencia_confere", "confianca", "confianca_original",
                              "evidencia_cita_tecnologia", "evidencia_cita_lgpd", "nome_solucao"),
     {"classificacao_id": "classificacoes"}),
    ("achados_descartados", "descartado_id", ("descartado_id", "classificacao_id", "uf", "tecnologia", "status", "fornecedor",
                                              "menciona_lgpd", "evidencia", "confianca", "motivo"),
     {"classificacao_id": "classificacoes"}),
    ("triagem_escopo", "id", ("id", "run_id", "chamada_id", "fonte", "item_id", "uf", "provedor", "termos_consulta", "status",
                              "status_bruto", "confianca", "categoria_motivo", "justificativa", "termo_gerador",
                              "sinal_negativo", "dominio_tematico", "escopo_geografico", "tipo_documento", "valido",
                              "problemas", "prompt_versao", "criado_em"), {"chamada_id": "chamadas?"}),
)
TABELAS = tuple(t for t, _, _, _ in DA_EXECUCAO) + tuple(COMPARTILHADAS)
COLUNAS = {t: c for t, _, c, _ in DA_EXECUCAO} | {t: c for t, (_, _, c) in COMPARTILHADAS.items()}
CHAVE = {t: k for t, k, _, _ in DA_EXECUCAO} | {t: k for t, (k, _, _) in COMPARTILHADAS.items()}
REFERENCIAS = {t: r for t, _, _, r in DA_EXECUCAO}
CHAVE_NATURAL = {"execucoes": ("run_id",), "metricas_run": ("run_id", "chave"), "selecao_download": ("run_id", "url_id", "uf")}

# tipo de cada coluna, na ordem de COLUNAS (t texto, i inteiro, r real), e as que nao podem ser vazias (NOT NULL do esquema)
TIPOS = {
    "execucoes": ("ttttttttttt", ("iniciado_em", "config_hash", "config_json", "status")),
    "execucoes_retomadas": ("itttt", ("run_id", "retomado_em")),
    "metricas_run": ("ttr", ("run_id", "chave")),
    "saldos": ("itttrt", ("run_id", "provedor", "momento")),
    "chamadas": ("itttttttitttiiiitiiiiirtttt", ("run_id", "etapa", "provedor", "parametros_json", "chave_idempotencia",
                                                 "requisitado_em", "sucesso")),
    "ocorrencias": ("iiittii", ("chamada_id", "artigo_id", "termo_id", "run_id")),
    "ocorrencias_web": ("iitttiittt", ("chamada_id", "run_id", "conjunto", "consulta_id", "referencia_id")),
    "resultados_web": ("iitttttiitttt", ("chamada_id", "run_id", "consulta_id", "uf", "url_id")),
    "selecao_download": ("tititi", ("run_id", "url_id", "uf", "selecionada", "auditoria")),
    "paginas": ("itiititiitititti", ("run_id", "url_id", "chamada_id")),
    "classificacoes": ("iitiittiitttiiiit", ("chamada_id", "run_id", "url_id", "uf")),
    "achados": ("iittttitittiit", ("classificacao_id", "uf")),
    "achados_descartados": ("iittttittt", ("classificacao_id",)),
    "triagem_escopo": ("itititttttttttttttittt", ("run_id", "fonte", "item_id", "uf", "status", "valido", "criado_em")),
    "urls": ("itttitt", ("url_normalizada", "url_original")),
    "artigos": ("ittttititt", ("chave_dedup", "titulo")),
    "referencias_web": ("ittttt", ("url_normalizada", "url_original", "dominio", "primeira_vez_run", "primeira_vez_em")),
}


def _valor_ok(tipo, v):
    """Texto: str sem NUL, codificavel em UTF-8 e ate MAX_TEXTO; inteiro: int (nunca bool) em 64 bits; real: int ou float
    finito (nunca bool)."""
    if tipo == "t":
        if not isinstance(v, str) or len(v) > MAX_TEXTO or "\x00" in v:
            return False
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if type(v) is bool:
        return False
    if tipo == "i":
        return type(v) is int and -MAIOR_ID - 1 <= v <= MAIOR_ID
    return (type(v) is int and abs(v) <= MAIOR_ID) or (type(v) is float and math.isfinite(v))


# chamadas.alvo_id leva numeros locais nestas etapas (a nuvem os renumera); nas outras e texto da configuracao
RE_ALVO = {
    "download": re.compile(r"(?P<url>[1-9][0-9]{0,18})"),
    "classificacao": re.compile(r"(?P<url>[1-9][0-9]{0,18}):(?P<uf>[A-Z]{2})"),
    "triagem_escopo": re.compile(r"(?P<fonte>web|artigo):(?P<n>[0-9]{1,9}):(?P<item>[1-9][0-9]{0,18})(?P<resto>-[A-Z]{2})?"),
}
FONTE_DO_ITEM = {"web": "urls", "artigo": "artigos"}


def _id_valido(v):
    return type(v) is int and 1 <= v <= MAIOR_ID


def conferir(pacote):
    """Lista de erros do pacote (vazia = aceito), na ordem: estrutura; linhas na ordem das tabelas e das linhas; paginas
    externas; repeticoes (pela primeira aparicao); referencias. Uma linha com chave invalida nao tem os outros campos
    conferidos; uma chave valida conta como presente mesmo se a linha tem outro erro (sem erro em cascata)."""
    if not isinstance(pacote, dict) or set(pacote) != {"versao", "run_id", "tabelas", "externas"}:
        return ["O pacote precisa ser um objeto JSON com as chaves versao, run_id, tabelas e externas."]
    if type(pacote["versao"]) is not int or pacote["versao"] != VERSAO:
        return [f"Versão do pacote não suportada: {pacote['versao']!r} (esta nuvem aceita {VERSAO})."]
    run_id = pacote["run_id"]
    if not isinstance(run_id, str) or not RE_RUN_ID.fullmatch(run_id):
        return [f"run_id inválido: {run_id!r}."]
    tabelas = pacote["tabelas"]
    if not isinstance(tabelas, dict):
        return ["tabelas precisa ser um objeto com uma lista de linhas por tabela."]
    erros = []
    faltam = [t for t in TABELAS if t not in tabelas]
    sobram = sorted(t for t in tabelas if t not in TABELAS)
    if faltam:
        erros.append("Tabelas faltando no pacote: " + ", ".join(faltam) + ".")
    if sobram:
        erros.append("Tabelas desconhecidas no pacote: " + ", ".join(sobram) + ".")
    erros += [f"{t}: deve ser uma lista de linhas." for t in TABELAS if t in tabelas and not isinstance(tabelas[t], list)]
    if erros:
        return erros
    if len(tabelas["execucoes"]) != 1:
        return ["execucoes: o pacote precisa de exatamente uma linha."]
    externas = pacote["externas"]
    if not isinstance(externas, dict) or set(externas) != {"paginas"} or not isinstance(externas["paginas"], list):
        return ["externas precisa ser um objeto só com a lista paginas."]

    validas = {t: [] for t in TABELAS}
    declaradas = {t: set() for t in TABELAS}         # chaves validas, mesmo de linha com outro erro: sem erro em cascata
    for t in TABELAS:
        colunas = set(COLUNAS[t])
        for i, linha in enumerate(tabelas[t], 1):
            onde = f"{t}, linha {i}"
            if not isinstance(linha, dict):
                erros.append(f"{onde}: deve ser um objeto.")
                continue
            k = CHAVE[t]
            if k is not None and k in linha and _id_valido(linha[k]):
                declaradas[t].add(linha[k])
            falta, sobra = [c for c in COLUNAS[t] if c not in linha], sorted(c for c in linha if c not in colunas)
            if falta or sobra:
                partes = ([f"colunas faltando: {', '.join(falta)}"] if falta else []) + \
                         ([f"colunas desconhecidas: {', '.join(sobra)}"] if sobra else [])
                erros.append(f"{onde}: " + "; ".join(partes) + ".")
                continue
            if k is not None and not _id_valido(linha[k]):
                erros.append(f"{onde}: {k} deve ser um número inteiro positivo.")
                continue
            tipos, obrigatorias = TIPOS[t]
            vazias = [c for c in obrigatorias if linha[c] is None]
            if vazias:
                erros.append(f"{onde}: não pode ficar vazio: " + ", ".join(vazias) + ".")
                continue
            ruins = [c for c, tipo in zip(COLUNAS[t], tipos) if linha[c] is not None and not _valor_ok(tipo, linha[c])]
            if ruins:
                erros.append(f"{onde}: valor inválido em " + ", ".join(ruins) + " (tipo errado, fora do limite, NaN ou texto com NUL).")
                continue
            if "run_id" in colunas and t not in COMPARTILHADAS and linha["run_id"] != run_id:
                erros.append(f"{onde}: run_id diferente do do pacote.")
                continue
            ref_ruim = [c for c, alvo in REFERENCIAS.get(t, {}).items()
                        if not (linha[c] is None and alvo.endswith("?")) and not _id_valido(linha[c])]
            if ref_ruim:
                erros.append(f"{onde}: " + ", ".join(ref_ruim) + " deve ser um número inteiro positivo.")
                continue
            if t == "chamadas" and linha["etapa"] in RE_ALVO and not (
                    isinstance(linha["alvo_id"], str) and RE_ALVO[linha["etapa"]].fullmatch(linha["alvo_id"])):
                erros.append(f"{onde}: alvo_id {linha['alvo_id']!r} fora do formato da etapa {linha['etapa']}.")
                continue
            if t == "triagem_escopo" and (linha["fonte"] not in FONTE_DO_ITEM or not _id_valido(linha["item_id"])):
                erros.append(f"{onde}: fonte deve ser web ou artigo e item_id um número inteiro positivo.")
                continue
            validas[t].append((i, linha))

    paginas_externas, repetidas_ext = set(), []
    for i, e in enumerate(externas["paginas"], 1):
        pid = e.get("pagina_id") if isinstance(e, dict) else None
        if _id_valido(pid):
            if pid in paginas_externas and pid not in repetidas_ext:
                repetidas_ext.append(pid)
            paginas_externas.add(pid)
        if not (isinstance(e, dict) and set(e) == {"pagina_id", "run_id"} and _id_valido(pid)
                and isinstance(e["run_id"], str) and RE_RUN_ID.fullmatch(e["run_id"]) and e["run_id"] != run_id):
            erros.append(f"externas.paginas, linha {i}: precisa de pagina_id (número inteiro positivo) e run_id de outra execução.")
    erros += [f"externas.paginas: pagina_id {p} repetido." for p in repetidas_ext]

    for t in TABELAS:
        vistos, repetidos = set(), []
        chave = (CHAVE[t],) if CHAVE[t] else CHAVE_NATURAL[t]
        for _, linha in validas[t]:
            valor = tuple(linha[c] for c in chave)
            if valor in vistos and valor not in repetidos:
                repetidos.append(valor)
            vistos.add(valor)
        for valor in repetidos:
            erros.append(f"{t}: {', '.join(chave)} {', '.join(map(str, valor))} repetido.")
        if t in COMPARTILHADAS:
            natural, vistos_n, rep_n = COMPARTILHADAS[t][1], set(), []
            for _, linha in validas[t]:
                if linha[natural] in vistos_n and linha[natural] not in rep_n:
                    rep_n.append(linha[natural])
                vistos_n.add(linha[natural])
            erros += [f"{t}: {natural} {v!r} repetido." for v in rep_n]
        unicas = {"chamadas": ("chave_idempotencia",), "triagem_escopo": ("fonte", "item_id", "uf")}.get(t)
        if unicas:                                   # restricoes UNIQUE da base (chamadas: so entre as de sucesso)
            vistos_u, rep_u = set(), []
            for _, linha in validas[t]:
                if t == "chamadas" and linha["sucesso"] != 1:
                    continue
                valor = tuple(linha[c] for c in unicas)
                if valor in vistos_u and valor not in rep_u:
                    rep_u.append(valor)
                vistos_u.add(valor)
            erros += [f"{t}: {', '.join(unicas)} {', '.join(map(str, v))} repetido." for v in rep_u]

    ids = {t: declaradas[t] for t in TABELAS if CHAVE[t]}
    ids["paginas"] = ids["paginas"] | paginas_externas
    for t in TABELAS:
        for i, linha in validas[t]:
            for c, alvo in REFERENCIAS.get(t, {}).items():
                pai = alvo.rstrip("?")
                if linha[c] is not None and linha[c] not in ids[pai]:
                    erros.append(f"{t}, linha {i}: {c} {linha[c]} não está no pacote ({pai}).")
            if t == "chamadas" and linha["etapa"] in RE_ALVO:
                m = RE_ALVO[linha["etapa"]].fullmatch(linha["alvo_id"])
                pai, n = (FONTE_DO_ITEM[m["fonte"]], int(m["item"])) if linha["etapa"] == "triagem_escopo" else ("urls", int(m["url"]))
                if n not in ids[pai]:
                    erros.append(f"{t}, linha {i}: alvo_id {linha['alvo_id']!r} aponta para {pai} {n}, que não está no pacote.")
            if t == "triagem_escopo" and linha["item_id"] not in ids[FONTE_DO_ITEM[linha["fonte"]]]:
                erros.append(f"{t}, linha {i}: item_id {linha['item_id']} não está no pacote ({FONTE_DO_ITEM[linha['fonte']]}).")
    return erros
