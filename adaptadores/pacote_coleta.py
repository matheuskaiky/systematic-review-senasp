"""Monta, no banco local, o pacote de uma execucao e o junta no banco da nuvem (D85, D99, D100). O mesmo codigo roda
sobre o SQLite e sobre o PostgreSQL (a conexao compativel traduz o SQL).

Juntar: tudo numa transacao com a trava de escrita; a execucao pertence a quem a enviou primeiro; URLs e artigos sao
achados pela chave natural (a linha da nuvem, se existe, nunca muda); as outras linhas sao achadas pela correspondencia
(execucao, tabela, numero local) -> numero na nuvem: linha nova entra, linha que mudou tem so os campos da coleta
atualizados, e nada e apagado. Os campos de decisao humana nunca sao escritos."""
from contextlib import nullcontext

from dominio import pacote_coleta as P
from dominio.pacote_coleta import ErroPacote


_DA_EXECUCAO = {
    "execucoes": "SELECT {c} FROM execucoes WHERE run_id = ?",
    "execucoes_retomadas": "SELECT {c} FROM execucoes_retomadas WHERE run_id = ? ORDER BY retomada_id",
    "metricas_run": "SELECT {c} FROM metricas_run WHERE run_id = ? ORDER BY chave",
    "saldos": "SELECT {c} FROM saldos WHERE run_id = ? ORDER BY id",
    "chamadas": "SELECT {c} FROM chamadas WHERE run_id = ? ORDER BY chamada_id",
    "ocorrencias": "SELECT {c} FROM ocorrencias WHERE run_id = ? ORDER BY ocorrencia_id",
    "resultados_web": "SELECT {c} FROM resultados_web WHERE run_id = ? ORDER BY resultado_id",
    "selecao_download": "SELECT {c} FROM selecao_download WHERE run_id = ? ORDER BY url_id, uf",
    "paginas": "SELECT {c} FROM paginas WHERE run_id = ? ORDER BY pagina_id",
    "classificacoes": "SELECT {c} FROM classificacoes WHERE run_id = ? ORDER BY classificacao_id",
    "achados": "SELECT {c} FROM achados WHERE classificacao_id IN (SELECT classificacao_id FROM classificacoes WHERE run_id = ?) "
               "ORDER BY achado_id",
    "achados_descartados": "SELECT {c} FROM achados_descartados WHERE classificacao_id IN "
                           "(SELECT classificacao_id FROM classificacoes WHERE run_id = ?) ORDER BY descartado_id",
    "triagem_escopo": "SELECT {c} FROM triagem_escopo WHERE run_id = ? ORDER BY id",
}


def _linhas(conn, sql, args, colunas):
    return [dict(zip(colunas, tuple(r))) for r in conn.execute(sql.format(c=", ".join(colunas)), args).fetchall()]


def montar(conn, run_id):
    """O pacote (dict pronto para JSON) da execucao `run_id` do banco local. ErroPacote se ela nao existe."""
    if conn.execute("SELECT 1 FROM execucoes WHERE run_id = ?", (run_id,)).fetchone() is None:
        raise ErroPacote(f"A execução {run_id} não existe neste banco.")
    tabelas = {t: _linhas(conn, _DA_EXECUCAO[t], (run_id,), P.COLUNAS[t]) for t, _, _, _ in P.DA_EXECUCAO}
    urls, artigos = set(), set()
    for t in ("resultados_web", "selecao_download", "paginas", "classificacoes"):
        urls |= {l["url_id"] for l in tabelas[t]}
    artigos |= {l["artigo_id"] for l in tabelas["ocorrencias"]}
    for l in tabelas["triagem_escopo"]:
        (urls if l["fonte"] == "web" else artigos).add(l["item_id"])
    for l in tabelas["chamadas"]:
        regra = P.RE_ALVO.get(l["etapa"])
        m = regra.fullmatch(l["alvo_id"] or "") if regra else None
        if m and l["etapa"] == "triagem_escopo":
            (urls if m["fonte"] == "web" else artigos).add(int(m["item"]))
        elif m:
            urls.add(int(m["url"]))
    for t, ids in (("urls", urls), ("artigos", artigos)):
        chave, _, colunas = P.COMPARTILHADAS[t]
        tabelas[t] = []
        for lote in _lotes(sorted(ids)):             # um comando por lote, nunca um por linha
            tabelas[t] += _linhas(conn, f"SELECT {{c}} FROM {t} WHERE {chave} IN ({', '.join('?' * len(lote))}) ORDER BY {chave}",
                                  tuple(lote), colunas)
    proprias = {l["pagina_id"] for l in tabelas["paginas"]}
    externas = sorted({l["pagina_id"] for l in tabelas["classificacoes"] if l["pagina_id"] is not None} - proprias)
    paginas_externas = []
    for lote in _lotes(externas):
        paginas_externas += [{"pagina_id": i, "run_id": r} for i, r in conn.execute(
            f"SELECT pagina_id, run_id FROM paginas WHERE pagina_id IN ({', '.join('?' * len(lote))}) ORDER BY pagina_id",
            tuple(lote)).fetchall()]
    return {"versao": P.VERSAO, "run_id": run_id, "tabelas": tabelas, "externas": {"paginas": paginas_externas}}


def juntar(conn, pacote, usuario_id, agora):
    """Junta o pacote (ja conferido por `dominio.pacote_coleta.conferir`) no banco aberto em `conn`, numa transacao.
    Devolve {tabela: {"novas": n, "atualizadas": n, "iguais": n}}. ErroPacote (nada gravado) quando a execucao e de outro
    usuario ou quando uma pagina externa ainda nao foi enviada."""
    erros = P.conferir(pacote)
    if erros:
        raise ErroPacote("Pacote recusado: " + " ".join(erros[:5]) + (f" (e mais {len(erros) - 5})" if len(erros) > 5 else ""))
    run_id, tabelas = pacote["run_id"], pacote["tabelas"]
    if conn.in_transaction:
        raise RuntimeError("A junção precisa de uma conexão sem transação aberta (ela é tudo ou nada).")
    # no PostgreSQL: trava propria dos envios (o painel continua gravando) e sem savepoint por comando (tudo ou nada)
    with (conn.modo_envio() if hasattr(conn, "modo_envio") else nullcontext()):
        conn.execute("BEGIN IMMEDIATE")
        try:
            relatorio = _juntar(conn, run_id, tabelas, pacote["externas"]["paginas"], usuario_id, agora)
            conn.commit()
            return relatorio
        except BaseException:
            conn.rollback()
            raise


def _juntar(conn, run_id, tabelas, paginas_externas, usuario_id, agora):
    dono = conn.execute("SELECT usuario_id FROM envios_execucao WHERE run_id = ?", (run_id,)).fetchone()
    if dono is not None and dono[0] != usuario_id:
        raise ErroPacote(f"A execução {run_id} foi enviada por outro usuário: só quem a enviou primeiro pode reenviá-la.")
    if dono is None and conn.execute("SELECT 1 FROM execucoes WHERE run_id = ?", (run_id,)).fetchone() is not None:
        raise ErroPacote(f"A execução {run_id} já existe neste banco sem registro de envio: não é juntada por envio.")
    relatorio = {t: {"novas": 0, "atualizadas": 0, "iguais": 0} for t in P.TABELAS}
    mapa = {"urls": {}, "artigos": {}}
    for t in ("urls", "artigos"):
        chave, natural, colunas = P.COMPARTILHADAS[t]
        na_base = {}
        for lote in _lotes([l[natural] for l in tabelas[t]]):
            na_base.update((n, i) for i, n in conn.execute(
                f"SELECT {chave}, {natural} FROM {t} WHERE {natural} IN ({', '.join('?' * len(lote))})", tuple(lote)).fetchall())
        for linha in tabelas[t]:
            if linha[natural] in na_base:
                mapa[t][linha[chave]] = na_base[linha[natural]]
                relatorio[t]["iguais"] += 1
                continue
            cols = [c for c in colunas if c != chave]
            cur = conn.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               tuple(linha[c] for c in cols))
            mapa[t][linha[chave]] = cur.lastrowid
            relatorio[t]["novas"] += 1
    mapa["paginas"] = {}
    por_execucao = {}
    for e in paginas_externas:
        por_execucao.setdefault(e["run_id"], []).append(e["pagina_id"])
    achadas = {}
    for outra, ids in por_execucao.items():          # um comando por execucao e lote, nunca um por pagina
        for lote in _lotes(sorted(set(ids))):
            achadas.update(((outra, i), c) for i, c in conn.execute(
                f"SELECT id_local, id_central FROM origem_ids WHERE run_id = ? AND tabela = 'paginas' "
                f"AND id_local IN ({', '.join('?' * len(lote))})", (outra, *lote)).fetchall())
    for e in paginas_externas:                       # a primeira que falta, na ordem do pacote
        if (e["run_id"], e["pagina_id"]) not in achadas:
            raise ErroPacote(f"A execução {run_id} usa a página {e['pagina_id']} da execução {e['run_id']}, que ainda não foi "
                             f"enviada: envie antes a execução {e['run_id']}.")
        mapa["paginas"][e["pagina_id"]] = achadas[(e["run_id"], e["pagina_id"])]
    for t, chave, colunas, referencias in P.DA_EXECUCAO:
        mapa.setdefault(t, {})
        ja_enviadas, atuais, novas_origens, naturais = {}, {}, [], {}
        if chave is None:                            # chave natural (comeca pelo run_id): uma leitura da tabela inteira da execucao
            natural = P.CHAVE_NATURAL[t]
            resto = [c for c in colunas if c not in natural]
            for r in conn.execute(f"SELECT {', '.join(natural + tuple(resto))} FROM {t} WHERE run_id = ?", (run_id,)).fetchall():
                r = tuple(r)
                naturais[r[:len(natural)]] = r[len(natural):]
        if chave is not None:
            ja_enviadas = dict(tuple(r) for r in conn.execute(
                "SELECT id_local, id_central FROM origem_ids WHERE run_id = ? AND tabela = ?", (run_id, t)).fetchall())
            outras = [c for c in colunas if c != chave]
            for lote in _lotes(sorted(ja_enviadas.values())):
                for r in conn.execute(f"SELECT {chave}, {', '.join(outras)} FROM {t} WHERE {chave} IN ({', '.join('?' * len(lote))})",
                                      tuple(lote)).fetchall():
                    atuais[r[0]] = tuple(r)[1:]
        reais = [c for c, tipo in zip(colunas, P.TIPOS[t][0]) if tipo == "r"]
        for linha in tabelas[t]:
            valores = dict(linha)
            for c in reais:                           # real que chegou como inteiro no JSON (1 em vez de 1.0)
                if type(valores[c]) is int:
                    valores[c] = float(valores[c])
            for c, alvo in referencias.items():
                if valores[c] is not None:
                    valores[c] = mapa[alvo.rstrip("?")][valores[c]]
            if t == "chamadas":
                valores["alvo_id"] = _alvo_central(valores["etapa"], valores["alvo_id"], mapa)
            if t == "triagem_escopo":
                valores["item_id"] = mapa[P.FONTE_DO_ITEM[valores["fonte"]]][valores["item_id"]]
            if chave is None:
                _upsert_natural(conn, t, valores, colunas, relatorio[t], naturais)
                continue
            cols = [c for c in colunas if c != chave]
            central = ja_enviadas.get(linha[chave])
            if central is None:
                cur = conn.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                   tuple(valores[c] for c in cols))
                novas_origens.append((run_id, t, linha[chave], cur.lastrowid))
                mapa[t][linha[chave]] = cur.lastrowid
                relatorio[t]["novas"] += 1
                continue
            mapa[t][linha[chave]] = central
            mudou = [c for c, v in zip(cols, atuais[central]) if v != valores[c]]
            if mudou:
                conn.execute(f"UPDATE {t} SET {', '.join(c + ' = ?' for c in mudou)} WHERE {chave} = ?",
                             tuple(valores[c] for c in mudou) + (central,))
                relatorio[t]["atualizadas"] += 1
            else:
                relatorio[t]["iguais"] += 1
        for lote in _lotes(novas_origens):           # um comando por lote (uma ida ao banco por 500 linhas)
            conn.execute("INSERT INTO origem_ids (run_id, tabela, id_local, id_central) VALUES "
                         + ", ".join(["(?, ?, ?, ?)"] * len(lote)), tuple(v for linha in lote for v in linha))
    if conn.execute("SELECT 1 FROM envios_execucao WHERE run_id = ?", (run_id,)).fetchone() is None:
        conn.execute("INSERT INTO envios_execucao (run_id, usuario_id, primeiro_envio_em, ultimo_envio_em, n_envios) "
                     "VALUES (?, ?, ?, ?, 1)", (run_id, usuario_id, agora, agora))
    else:
        conn.execute("UPDATE envios_execucao SET ultimo_envio_em = ?, n_envios = n_envios + 1 WHERE run_id = ?", (agora, run_id))
    return relatorio


TAMANHO_DO_LOTE = 500            # parametros por IN (...): longe do limite do SQLite (32.766) e do PostgreSQL (65.535)


def _lotes(valores):
    return [valores[i:i + TAMANHO_DO_LOTE] for i in range(0, len(valores), TAMANHO_DO_LOTE)]


def _alvo_central(etapa, alvo, mapa):
    regra = P.RE_ALVO.get(etapa)
    if regra is None:
        return alvo
    m = regra.fullmatch(alvo)
    if etapa == "download":
        return str(mapa["urls"][int(m["url"])])
    if etapa == "classificacao":
        return f"{mapa['urls'][int(m['url'])]}:{m['uf']}"
    item = mapa[P.FONTE_DO_ITEM[m["fonte"]]][int(m["item"])]
    return f"{m['fonte']}:{m['n']}:{item}{m['resto'] or ''}"


def _upsert_natural(conn, t, valores, colunas, contagem, naturais):
    """Tabela cuja chave primaria ja e natural (execucoes, metricas_run, selecao_download): acha pela chave entre as linhas
    da execucao ja lidas (`naturais`), insere ou atualiza so as colunas que mudaram."""
    natural = P.CHAVE_NATURAL[t]
    resto = [c for c in colunas if c not in natural]
    onde = " AND ".join(f"{c} = ?" for c in natural)
    chave = tuple(valores[c] for c in natural)
    atual = naturais.get(chave)
    if atual is None:
        conn.execute(f"INSERT INTO {t} ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
                     tuple(valores[c] for c in colunas))
        contagem["novas"] += 1
        return
    mudou = [c for c, v in zip(resto, atual) if v != valores[c]]
    if mudou:
        conn.execute(f"UPDATE {t} SET {', '.join(c + ' = ?' for c in mudou)} WHERE {onde}", tuple(valores[c] for c in mudou) + chave)
        contagem["atualizadas"] += 1
    else:
        contagem["iguais"] += 1
