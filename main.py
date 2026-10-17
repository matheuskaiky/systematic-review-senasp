import argparse
import dataclasses
import hashlib
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
import pandas as pd

import config.settings as S
from config import consultas as C, prompts as P, vocabulario as V, triagem_escopo as TE
from composicao import Fabrica
from dominio.esquemas import esquema_classificacao
from dominio.modelos import ParametrosClassificacao
from dominio.erros import CotaDiariaEsgotada
from dominio.entrada import separar_runs, descricao_motivos_falha_download
from dominio import auditoria_negativos as AN
from dominio.rotulagem import FOLGA_PADRAO as FOLGA_PADRAO_ROTULAGEM
from dominio.servicos import gerar_consultas_web, palavras_chave_tecnologia, dominio_de
from dominio.triagem_escopo import atomo_do_modelo_de_consulta, estimar_custo
from aplicacao import busca_academica, busca_web, download, classificacao, manual, exportacao, rotulagem, triagem_escopo
from aplicacao.planejamento import planejar_download, planejar_classificacao
from infra.log import iniciar_log
from infra.util import coletar_ambiente

ETAPAS = {
    "academico": ["academico"],
    "busca-web": ["busca_web"],
    "baixar": ["download"],
    "classificar": ["classificacao"],
    "pipeline-uf": ["busca_web", "download", "classificacao"],
    "tudo": ["academico", "busca_web", "download", "classificacao"],
}


# arquivos de acompanhamento que nao mudam o comportamento do codigo: nao contam para "arvore suja"
_FORA_DO_CODIGO = (":!DECISIONS.md", ":!.gitignore")


def _git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, cwd=S.RAIZ)


def _commit_git():
    """Commit curto. Com alteracoes nao commitadas (inclusive arquivos novos), acrescenta `+sujo:<hash>` do
    conteudo, para que a execucao nao seja atribuida a um commit cujo codigo ela nao rodou."""
    try:
        commit = _git("rev-parse", "--short", "HEAD").decode().strip()
        status = _git("status", "--porcelain", "--untracked-files=all", "--", ".", *_FORA_DO_CODIGO).decode()
        if not status.strip():
            return commit
        h = hashlib.sha256(status.encode())
        h.update(_git("diff", "HEAD", "--", ".", *_FORA_DO_CODIGO))
        for linha in status.splitlines():
            if linha.startswith("??"):
                try:
                    h.update((Path(S.RAIZ) / linha[3:]).read_bytes())
                except OSError:
                    pass
        return f"{commit}+sujo:{h.hexdigest()[:8]}"
    except Exception:
        return None


def _ambiente(args):
    """Versoes, pausas e argumentos da execucao: ficam em execucoes.ambiente_json, fora do hash da configuracao."""
    lock = Path(S.RAIZ) / "requirements.lock.txt"
    return json.dumps(coletar_ambiente({
        "pausas": S.PAUSAS, "argumentos": vars(args),
        "requirements_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None}),
        ensure_ascii=False, sort_keys=True, default=str)


def _params_classificacao():
    esquema = esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA)
    return ParametrosClassificacao(
        versao_prompt=P.PROMPT_VERSAO, sistema=P.SYSTEM_PROMPT, usuario_template=P.USER_PROMPT,
        esquema=esquema, tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS),
        max_chars=S.CLASSIFICACAO["max_chars_texto"],
        usar_snippet_se_falhar=S.CLASSIFICACAO["usar_snippet_se_falhar"],
        palavras_tecnologia={k: tuple(sorted(palavras_chave_tecnologia(v))) for k, v in V.TECNOLOGIAS.items()})


_AJUDA_TECNOLOGIAS = ("busca só estas tecnologias (chaves de config/vocabulario.py::TECNOLOGIAS: " + ", ".join(V.TECNOLOGIAS)
                      + "); padrão: todas. Serve para amostras pequenas")


def _tecnologias_da_busca(args):
    """RC14: tecnologias que a busca web usa. Sem --tecnologias, todas as de `V.TECNOLOGIAS`; com ele, só as listadas
    (amostra pequena, regra 11). Só restringe a BUSCA: o classificador continua aceitando todas as categorias."""
    pedidas = getattr(args, "tecnologias", None)
    if not pedidas:
        return dict(V.TECNOLOGIAS)
    invalidas = [t for t in pedidas if t not in V.TECNOLOGIAS]
    if invalidas:
        raise SystemExit(f"Tecnologia desconhecida em --tecnologias: {', '.join(invalidas)}. "
                         f"Chaves válidas: {', '.join(V.TECNOLOGIAS)}.")
    return {k: v for k, v in V.TECNOLOGIAS.items() if k in pedidas}


def estimar(args):
    tecnologias = _tecnologias_da_busca(args)
    ufs = {k: v for k, v in C.UFS.items() if not getattr(args, "ufs", None) or k in args.ufs}
    consultas = gerar_consultas_web(C.MODELOS_WEB, tecnologias, ufs, C.MUNICIPIOS, C.MODELOS_WEB_MUNICIPAIS)
    print(f"Academic terms: {len(C.TERMOS)} | pages per term (max.): {C.MAX_PAGINAS_ACADEMICO}")
    print(f"Academic search credits (worst case): {len(C.TERMOS) * C.MAX_PAGINAS_ACADEMICO}")
    print(f"Web queries: {len(consultas)} | estimated cost: US$ {len(consultas) * S.PRECO_BUSCA_WEB_USD:.2f}")
    print(f"Pages to download (ceiling): {C.POLITICA_DOWNLOAD.max_urls_por_uf * len(ufs)}")
    print(f"Classifications (ceiling): {C.POLITICA_DOWNLOAD.max_urls_por_uf * len(ufs)} (cost depends on the model and text sizes)")
    fab = Fabrica(simulado=args.simulado)
    # C9: sem chave (ou sem adaptador) a estimativa continua valendo; so o saldo fica indisponivel.
    # O endpoint de conta da SerpApi e gratuito e nao conta na cota (documentacao, consultada em 14/10/2026).
    try:
        saldo = getattr(fab.academico, "saldo", lambda: None)()
        print(f"Academic provider balance: {saldo}")
    except (Exception, SystemExit) as e:      # a fabrica encerra com SystemExit quando falta a chave
        print(f"Saldo: indisponível ({e})")


def _avisar_cota_diaria(e, cmd, run_id):
    """Mensagem unica para a parada por cota diaria esgotada (sem traceback): a execucao fica interrompida e se retoma."""
    if getattr(e, "motivo", "") == "saldo":
        logging.warning("Parada: %s Depois de colocar crédito no projeto, retome com: python main.py %s ... --retomar %s",
                        e, cmd, run_id)
        return
    logging.warning("Parada: %s Resume com --retomar %s depois que a cota renovar (a cota diária renova à meia-noite no "
                    "horário do Pacífico, 04h no horário de Brasília durante o horário de verão americano e 05h fora "
                    "dele). Comando: python main.py %s ... --retomar %s", e, run_id, cmd, run_id)


def _listar_download(args, repo, de, ufs):
    """--listar de `baixar`: mostra o que SERIA baixado. So le o banco: nada e baixado nem gravado (nem a execucao)."""
    cands, decisao, _ = planejar_download(repo, de, C.POLITICA_DOWNLOAD, set(ufs), 0, "", args.so_sem_pagina,
                                          args.so_falha, args.urls)
    ultimas = repo.ultimas_tentativas_download()
    escolhidas, vistas = [], set()
    for c, ok, _motivo in sorted(decisao, key=lambda d: (d[0].url_id, d[0].uf)):
        if ok:
            if args.limite and c.url_id not in vistas and len(vistas) >= args.limite:
                break
            vistas.add(c.url_id)
            escolhidas.append(c)
    descartes = {}
    for _, ok, motivo in decisao:
        if not ok:
            descartes[motivo] = descartes.get(motivo, 0) + 1
    filtros = [f for f, v in (("--so-sem-pagina", args.so_sem_pagina), (f"--so-falha {args.so_falha}", args.so_falha),
                              ("--urls " + " ".join(str(u) for u in args.urls or []), args.urls)) if v] or ["nenhum"]
    print(f"Execuções de entrada (--de): {', '.join(de)} | filtros de resgate: {', '.join(filtros)}")
    print(f"Candidatos depois dos filtros: {len(cands)} | descartados na seleção: "
          + (", ".join(f"{m} {n}" for m, n in sorted(descartes.items())) or "0"))
    print(f"Seriam baixadas: {len(vistas)} páginas ({len(escolhidas)} pares URL/UF; uma página serve a todas as UFs em que "
          f"aparece; por --limite: {args.limite or 'sem limite'}). Nada foi baixado nem gravado.")
    if args.auditoria:
        print("A amostra de --auditoria depende do run_id da execução e não é mostrada aqui.")
    print("url_id  UF  domínio  motivo  tentativa anterior (resultado:motivo)")
    for c in escolhidas:
        antes = ":".join(ultimas[c.url_id]) if c.url_id in ultimas else "nunca_tentada"
        print(f"{c.url_id:>6}  {c.uf}  {c.dominio}  selecionada  {antes}")


def _listar_classificacao(args, repo, de, ufs, params, classificador_nome):
    """--listar de `classificar`: mostra o que SERIA classificado. So le o banco: nenhuma chamada e nenhuma gravacao."""
    itens = planejar_classificacao(repo, de, set(ufs), args.urls, args.so_nao_classificadas, params.versao_prompt,
                                   classificador_nome)
    linhas, usaveis = [], 0
    for i in itens:
        if i.texto_path:
            motivo = "pagina"
        elif params.usar_snippet_se_falhar and (i.titulo or i.snippet):
            motivo = "snippet"
        else:
            motivo = "sem_texto (seria ignorado)"
        if motivo != "sem_texto (seria ignorado)":
            if args.limite and usaveis >= args.limite:
                break
            usaveis += 1
        linhas.append((i, motivo))
    filtros = [f for f, v in (("--so-nao-classificadas", args.so_nao_classificadas),
                              ("--urls " + " ".join(str(u) for u in args.urls or []), args.urls)) if v] or ["nenhum"]
    print(f"Execuções de entrada (--de): {', '.join(de)} | filtros: {', '.join(filtros)} | prompt {params.versao_prompt}")
    print(f"Seriam classificados: {usaveis} itens (por --limite: {args.limite or 'sem limite'}). "
          "Nenhuma chamada foi feita e nada foi gravado.")
    print("url_id  UF  domínio  motivo (texto enviado)")
    for i, motivo in linhas:
        print(f"{i.url_id:>6}  {i.uf}  {dominio_de(i.url)}  {motivo}")


def rodar(args, etapas):
    tecnologias = _tecnologias_da_busca(args)       # valida antes de abrir o banco ou exigir chave
    fab = Fabrica(simulado=args.simulado)
    repo, snap = fab.repo, S.snapshot_config()
    # C5: na retomada, sem --de, reaproveita o --de guardado na execucao original (uma ou varias execucoes)
    de = separar_runs(args.de) or separar_runs(repo.obter_run_origem(args.retomar) if args.retomar else None)
    # C5: etapa que le o resultado de outra etapa que nao roda no mesmo comando exige --de
    precisa_de = (("download" in etapas and "busca_web" not in etapas)
                  or ("classificacao" in etapas and "download" not in etapas))
    if precisa_de and not de:
        raise SystemExit(f"O comando '{args.cmd}' lê dados de uma etapa anterior que não roda nele: "
                         "informe --de <run_id> com a execução que contém essa entrada.")
    # filtros de resgate e --listar (so `baixar` e `classificar`): validam e mostram antes de criar a execucao
    so_sem_pagina, so_falha, urls = (getattr(args, k, None) for k in ("so_sem_pagina", "so_falha", "urls"))
    so_nao_classificadas, listar = getattr(args, "so_nao_classificadas", False), getattr(args, "listar", False)
    ufs = {k: v for k, v in C.UFS.items() if not args.ufs or k in args.ufs}
    if listar or so_sem_pagina or so_falha or urls or so_nao_classificadas:
        repo.validar_runs_origem(de)
        if etapas == ["download"]:
            if listar:
                return _listar_download(args, repo, de, ufs)
            planejar_download(repo, de, C.POLITICA_DOWNLOAD, set(ufs), 0, "", so_sem_pagina, so_falha, urls)
        elif etapas == ["classificacao"]:
            nome_cl = fab.classificador.nome if so_nao_classificadas else None
            if listar:
                return _listar_classificacao(args, repo, de, ufs, _params_classificacao(), nome_cl)
            planejar_classificacao(repo, de, set(ufs), urls, so_nao_classificadas, P.PROMPT_VERSAO, nome_cl)
    run_id = repo.iniciar_execucao(args.cmd + (" [simulado]" if args.simulado else ""),
                                   snap["hash"], snap["json"], _commit_git(), args.retomar, run_origem=de,
                                   ambiente_json=_ambiente(args))
    iniciar_log(run_id, S.LOG_DIR)
    if args.termos:
        todos_termos = C.TERMOS + C.TERMOS_COMPOSTOS
        termos = [t for t in todos_termos if t.id in args.termos]
    else:
        termos = list(C.TERMOS)
    # where each stage reads from: from the run itself if the previous stage runs together; otherwise from --de
    origem_dl = run_id if "busca_web" in etapas else de
    origem_cl = run_id if "download" in etapas else de
    logging.info("run_id=%s | stages=%s | states=%d | simulated=%s", run_id, etapas, len(ufs), args.simulado)

    status = "concluida"
    try:
        if "academico" in etapas:
            saldo = getattr(fab.academico, "saldo", lambda: None)
            repo.registrar_saldo(run_id, fab.academico.nome, "inicio", saldo())
            filtros_acad = (dataclasses.replace(C.FILTROS_ACADEMICOS, idioma_resultados=args.idioma_resultados)
                            if getattr(args, "idioma_resultados", None) else C.FILTROS_ACADEMICOS)
            busca_academica.executar(repo, fab.bruto, fab.academico, run_id, termos, filtros_acad,
                                     args.paginas or C.MAX_PAGINAS_ACADEMICO, fab.segredos, S.PAUSAS["busca_academica"])
            repo.registrar_saldo(run_id, fab.academico.nome, "fim", saldo())
        if "busca_web" in etapas:
            consultas = [c for c in gerar_consultas_web(C.MODELOS_WEB, tecnologias, ufs, C.MUNICIPIOS, C.MODELOS_WEB_MUNICIPAIS)
                         if not args.perfil or c.perfil == args.perfil]
            busca_web.executar(repo, fab.bruto, fab.busca_web, run_id, consultas, C.PERFIS_BUSCA_WEB,
                               fab.segredos, S.PAUSAS["busca_web"], args.limite)
        if "download" in etapas:
            download.executar(repo, fab.bruto, fab.fetcher, fab.extrator, run_id, origem_dl,
                              C.POLITICA_DOWNLOAD, fab.segredos, S.PAUSAS["download"], args.limite, set(ufs),
                              auditoria=args.auditoria or 0, semente=run_id,
                              max_falhas_por_pagina=S.DOWNLOAD["max_falhas_por_pagina"],
                              so_sem_pagina=bool(so_sem_pagina), so_falha=so_falha, urls=urls)
        if "classificacao" in etapas:
            classificacao.executar(repo, fab.bruto, fab.classificador, run_id, origem_cl, _params_classificacao(),
                                   C.UFS, fab.segredos, S.PAUSAS["classificacao"], args.limite, set(ufs),
                                   max_falhas_por_item=S.CLASSIFICACAO["max_falhas_por_item"],
                                   so_nao_classificadas=so_nao_classificadas, urls=urls)
    except KeyboardInterrupt:
        status = "interrompida"
        logging.warning("Interrupted. Resume with: python main.py %s --retomar %s", args.cmd, run_id)
    except CotaDiariaEsgotada as e:
        status = "interrompida"
        _avisar_cota_diaria(e, args.cmd, run_id)
    except SystemExit:
        # a fabrica encerra com SystemExit (ex.: falta de chave); a execucao nao pode constar como concluida
        status = "falhou"
        raise
    except Exception:
        status = "falhou"
        logging.exception("Run failed")
    finally:
        repo.finalizar_execucao(run_id, status)
        logging.info("Run %s: %s", run_id, status)


def _mapas_termos_triagem():
    """Textos dos termos de cada consulta, para a triagem de escopo (o banco guarda so os ids).

    Artigos: o texto de cada termo do Scholar e das buscas manuais (`config/consultas.py::TERMOS`).
    Resultados web: nao ha um "termo" unico; os termos sao os ATOMOS ALTERAVEIS da consulta: o rotulo da tecnologia
    (`config/vocabulario.py::TECNOLOGIAS`) e as palavras fixas do modelo de consulta (o template sem {tec}, {nome}, {uf} e
    {cidade}). UF, estado e cidade nao entram: nao sao escolhas de redacao da consulta."""
    return {"artigo": {t.id: t.query for t in C.TERMOS + C.TERMOS_COMPOSTOS},
            "web": {"tecnologias": dict(V.TECNOLOGIAS),
                    "modelos": {m.id: atomo_do_modelo_de_consulta(m.template)
                                for m in list(C.MODELOS_WEB) + list(C.MODELOS_WEB_MUNICIPAIS)}}}


def _opcoes_llm():
    """Opcoes do provedor de LLM configurado para o classificador (a triagem usa o mesmo modelo, preco e chave)."""
    return S.OPCOES[S.PROVEDORES["classificador"]]


def _precos_triagem():
    o = _opcoes_llm()
    if o.get("preco_entrada_por_m") is None or o.get("preco_saida_por_m") is None:
        return None
    return {"entrada": o["preco_entrada_por_m"], "saida": o["preco_saida_por_m"]}


def _config_triagem_run(lote):
    """Configuracao da execucao de `triar-escopo`: o snapshot geral (sem alterar `settings.snapshot_config`) mais a
    configuracao da triagem (versao do prompt, prompts, vocabularios, tamanho do lote) e um hash proprio."""
    snap = S.snapshot_config()
    conteudo = json.loads(snap["json"])
    conteudo["triagem_escopo"] = {**TE.CONFIG.como_dict(), "lote": lote, "max_tokens_saida": TE.MAX_TOKENS_SAIDA,
                                  "max_falhas_por_lote": TE.MAX_FALHAS_POR_LOTE}
    texto = json.dumps(conteudo, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode()).hexdigest()[:12], texto


def _imprimir_estimativa(a, fonte, itens, resumo, lote, precos):
    est = estimar_custo(itens, lote, precos, TE.CONFIG) if precos else None
    print(f"Triagem de escopo (prompt {TE.PROMPT_TRIAGEM_VERSAO}) | fonte: {a.fonte}")
    print(f"Itens no banco: {resumo['total']} | na amostra: {resumo['na_amostra']} | já triados com este prompt: "
          f"{resumo['ja_triados']} | a triar: {resumo['a_triar']}")
    if est is None:
        print("Preços do modelo não configurados: custo indisponível.")
        return
    n = est["niveis"]
    print(f"Lote: {lote} | chamadas (requisições): {est['chamadas']} | modelo: {_opcoes_llm()['modelo']} "
          f"(US$/M tokens: entrada {precos['entrada']}, saída {precos['saida']})")
    print(f"Tokens de entrada: {est['tokens_entrada']} no total | por chamada (média): {est['tokens_entrada_por_chamada']} | "
          f"maior chamada: {est['tokens_entrada_maior_chamada']} ({est['pct_janela_contexto']}% da janela de contexto de "
          f"{TE.JANELA_CONTEXTO_TOKENS:,} tokens)".replace(",", "."))
    print(f"Tokens de saída (baixo / médio / alto): {n['baixo']['tokens_saida']} / {n['medio']['tokens_saida']} / "
          f"{n['alto']['tokens_saida']}")
    print(f"Custo estimado (US$): baixo {n['baixo']['custo_usd']:.4f} | médio {n['medio']['custo_usd']:.4f} | "
          f"alto {n['alto']['custo_usd']:.4f}")
    print(f"Nível gratuito: limite de {TE.LIMITE_DIARIO_GRATUITO} requisições por dia por modelo (documentado no erro 429 da "
          f"API); esta execução usaria {100 * est['chamadas'] / TE.LIMITE_DIARIO_GRATUITO:.1f}% da cota diária "
          "(compartilhada com a classificação, que usa o mesmo modelo e a mesma chave).")
    print("Tokens estimados a 3,4 caracteres por token, sem o tokenizador oficial: ordem de grandeza, não valor exato.")


def triar_escopo(a):
    """Triagem de escopo por LLM (so lê o banco e grava `triagem_escopo`). Regra de busca amostral do projeto (regra 11): sem --amostra ou
    --limite o comando recusa, salvo --tudo explicito. --estimar nao chama nada e nao pede chave."""
    lote = TE.LOTE_PADRAO if a.lote is None else a.lote
    if lote < 1 or lote > TE.LOTE_MAXIMO:
        raise SystemExit(f"--lote deve estar entre 1 e {TE.LOTE_MAXIMO} (recebido: {lote}).")
    if not a.estimar and not (a.amostra or a.limite or a.tudo):
        raise SystemExit(
            "Recusado (regra 11 do projeto, busca amostral): a triagem de escopo gasta créditos e, enquanto não houver protocolo final "
            "de busca, deve rodar só sobre uma amostra pequena. Informe --amostra N (com --estratificar para espalhar "
            "por termo e relevância) ou --limite N. Veja o custo antes, sem chamada, com --estimar. Para triar todos os "
            "itens, passe --tudo de forma explícita (o custo estimado será mostrado antes).")
    fonte = "artigo" if a.fonte == "artigos" else "web"
    fab = Fabrica(simulado=a.simulado)
    repo, precos = fab.repo, _precos_triagem()
    mapas = _mapas_termos_triagem()
    itens, resumo = triagem_escopo.selecionar(repo, fonte, mapas, TE.CONFIG, a.amostra, a.estratificar,
                                              a.semente, a.limite, a.refazer)
    if a.estimar or a.tudo:
        _imprimir_estimativa(a, fonte, itens, resumo, lote, precos)
    if a.estimar:
        return
    if not itens:
        print("Nada a triar: todos os itens da seleção já têm triagem com este prompt (use --refazer para repetir).")
        return
    teto = a.max_custo if a.max_custo is not None else TE.MAX_CUSTO_PADRAO_USD
    if precos is None:
        raise SystemExit("Preços do modelo não configurados em config/settings.py: o teto de custo não pode ser aplicado.")
    h, config_json = _config_triagem_run(lote)
    run_id = repo.iniciar_execucao(a.cmd + (" [simulado]" if a.simulado else ""), h, config_json, _commit_git(),
                                   a.retomar, run_origem=None, ambiente_json=_ambiente(a))
    iniciar_log(run_id, S.LOG_DIR)
    logging.info("run_id=%s | triar-escopo fonte=%s | teto US$ %.2f | simulated=%s", run_id, a.fonte, teto, a.simulado)
    status = "concluida"
    try:
        r = triagem_escopo.executar(repo, fab.bruto, fab.triador, run_id, fonte, mapas, TE.CONFIG, precos, fab.segredos,
                                    0 if a.simulado else TE.PAUSA_SEGUNDOS, lote, a.amostra, a.estratificar, a.semente,
                                    a.limite, teto, a.refazer, TE.MAX_FALHAS_POR_LOTE)
        print(f"Execução {run_id}: {r['itens_triados']} itens triados em {r['chamadas']} chamadas "
              f"({r['lotes_falhos']} lotes com falha, {r['itens_sem_resposta']} itens sem resposta) | "
              f"custo US$ {r['custo_usd']:.4f} (teto US$ {teto:.2f})")
        if r["parou_por_custo"]:
            print("PARADA pelo teto de custo antes de terminar; os itens restantes seguem sem triagem (ver metricas_run).")
    except KeyboardInterrupt:
        status = "interrompida"
        logging.warning("Interrupted. Rode de novo o mesmo comando: os itens já triados são pulados.")
    except CotaDiariaEsgotada as e:
        status = "interrompida"
        _avisar_cota_diaria(e, a.cmd, run_id)
    except SystemExit:
        status = "falhou"
        raise
    except Exception:
        status = "falhou"
        logging.exception("Run failed")
    finally:
        repo.finalizar_execucao(run_id, status)
        logging.info("Run %s: %s", run_id, status)


def _avisar_conflitos(repo, rotulo):
    """Linhas ignoradas porque o banco mudou depois da exportacao (painel ou outra planilha): nada foi sobrescrito."""
    conflitos = getattr(repo, "conflitos_importacao", [])
    if conflitos:
        print(f"CONFLITOS: {len(conflitos)} linha(s) ignorada(s), pois o {rotulo} mudou no banco depois que a planilha foi exportada. "
              f"Nada foi sobrescrito; exporte de novo e refaça essas linhas. {rotulo.capitalize()} (linha da planilha): "
              + ", ".join(f"{i} (linha {l})" for i, l in conflitos))


def abrir_painel(a, fab):
    """Liga o painel aos adaptadores e o serve em 127.0.0.1. Importa o servidor so aqui: as demais etapas nao precisam dele."""
    if a.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("O painel só aceita conexões locais (127.0.0.1): ele não tem autenticação.")
    import uvicorn
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from painel.app import Contexto, criar_app
    banco = "demo" if a.demo else "simulado" if a.simulado else "real"
    if a.demo:        # a demonstração tem as suas soluções (fictícias, presentes nos dados dela); a lista real é do pesquisador e vale para o banco real e o simulado
        from painel_demo import SOLUCOES_CONHECIDAS_DEMO as SOLUCOES_CONHECIDAS
    else:
        from config.solucoes_conhecidas import SOLUCOES_CONHECIDAS
    contexto = Contexto(
        banco=banco, nome_banco=fab.caminho_banco.name, somente_leitura=a.somente_leitura,
        pasta_backup=S.DATA_DIR / "backups", ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
        status_definicoes=dict(V.STATUS), termos={t.id: t.query for t in C.TERMOS + C.TERMOS_COMPOSTOS}, bases=tuple(C.BASES_MANUAIS),
        solucoes_conhecidas=tuple(SOLUCOES_CONHECIDAS),
        comando_criar_banco="python main.py painel-demo" if a.demo else
        "python main.py tudo --simulado --ufs PI CE --paginas 1" if a.simulado else "python main.py pipeline-uf --ufs PI --limite 5")
    if not fab.caminho_banco.exists() and a.demo:
        raise SystemExit("O banco de demonstração não existe. Rode antes: python main.py painel-demo")
    if fab.caminho_banco.exists():
        # o painel le o banco sem aplicar o esquema; depois de uma atualizacao do codigo faltariam colunas e views. Aplica-se aqui,
        # uma unica vez (abrir o repositorio so grava se a assinatura do esquema mudou: D55). Em --somente-leitura nao se grava.
        if not a.somente_leitura:
            fab.novo_repositorio().fechar()
        elif not RepositorioSQLite.esquema_atualizado(fab.caminho_banco):
            raise SystemExit("O esquema do banco está desatualizado em relação ao código e --somente-leitura não grava. "
                             "Abra o painel sem essa opção (ou rode qualquer comando de coleta) uma vez para atualizá-lo.")
    app = criar_app(fab.leitura_painel(), fab.novo_repositorio, fab.bruto, contexto)
    print(f"Painel ({banco}): http://{a.host}:{a.porta}   (Ctrl+C para encerrar)")
    uvicorn.run(app, host=a.host, port=a.porta, log_level="warning")


def gerar_relatorio(a, fab):
    """Gera UM arquivo HTML autocontido (CSS e SVG embutidos, sem scripts) com os resultados do banco escolhido.
    Importa o painel so aqui: as demais etapas nao precisam dele."""
    from painel import relatorio
    if a.simulado and a.demo:
        raise SystemExit("Use --simulado ou --demo, não os dois.")
    if not fab.caminho_banco.exists():
        raise SystemExit(f"O banco {fab.caminho_banco.name} ainda não existe: não há o que relatar. "
                         + ("Rode antes: python main.py painel-demo" if a.demo else "Rode antes o pipeline (por exemplo, python main.py pipeline-uf --ufs PI --limite 5)."))
    banco = "demo" if a.demo else "simulado" if a.simulado else "real"
    agora = datetime.now()
    dados = relatorio.coletar_dados(fab.leitura_painel(), dict(C.UFS), {t.id: t.query for t in C.TERMOS + C.TERMOS_COMPOSTOS}, tuple(C.BASES_MANUAIS),
                                    banco, fab.caminho_banco.name, agora.isoformat(timespec="seconds"), a.incluir_nao_verificados)
    estaticos = Path(relatorio.__file__).parent / "static"
    css = "\n".join((estaticos / nome).read_text(encoding="utf-8") for nome in ("painel.css", "metodologia.css"))
    html = relatorio.montar_relatorio(dados, a.incluir_nao_verificados, css)
    prefixo = "demo_" if a.demo else "simulado_" if a.simulado else ""
    saida = Path(a.saida) if a.saida else S.OUT_DIR / f"{prefixo}relatorio_{agora:%Y%m%d_%H%M}.html"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(html, encoding="utf-8")
    print("Generated:", saida)


def auditoria_negativos_modelo(a, fab):
    """Sorteia, entre as paginas que o modelo classificou SEM achados (texto da pagina, classificacao vigente), a amostra que
    uma pessoa vai ler para dizer se havia uma aplicacao de IA que o modelo perdeu. So le o banco; nao grava nada nele."""
    saida = Path(a.saida) if a.saida else S.OUT_DIR / "auditoria_negativos_amostra.csv"
    if saida.exists():
        raise SystemExit(f"{saida} já existe e pode ter respostas: escolha outro nome com --saida ou apague o arquivo")
    candidatos = fab.repo.candidatos_auditoria_negativos()
    amostra = AN.amostrar(candidatos, a.amostra, a.semente)
    saida.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{c: l.get(c) for c in AN.COLUNAS_AMOSTRA} for l in amostra], columns=list(AN.COLUNAS_AMOSTRA))
    df.to_csv(saida, index=False, encoding="utf-8-sig")
    print(f"Páginas sem achado ainda não conferidas: {len(candidatos)} | amostra sorteada: {len(amostra)} (semente {a.semente!r}, "
          f"por UF em proporção ao tamanho de cada UF)")
    print("Gerado:", saida)
    raiz_texto = S.DATA_DIR / "raw_simulado" if a.simulado else S.OPCOES["local"]["raiz"]
    print(f"texto_path é relativo a {raiz_texto}.")
    print("Para cada linha: leia o texto em texto_path (ou a página em url) e preencha revisor, tinha_aplicacao (1 = havia uma "
          "aplicação de IA que o modelo não marcou; 0 = o modelo acertou) e, se 1, tecnologia. Depois: "
          "python main.py auditoria-negativos-importar <arquivo>")


def auditoria_negativos_importar(a, fab):
    df = pd.read_csv(a.arquivo, encoding="utf-8-sig", dtype=str)
    registros, sem_resposta = AN.validar_respostas(df.to_dict("records"), set(V.TECNOLOGIAS))
    r = fab.repo.importar_auditoria_negativos(registros)
    print(f"Respostas novas: {r['novas']} | já gravadas iguais: {r['iguais']} | linhas sem resposta (puladas): {sem_resposta}")
    if r["conflitos"]:
        print(f"CONFLITOS: {len(r['conflitos'])} resposta(s) diferente(s) de uma já gravada para o mesmo revisor; nada foi sobrescrito. "
              "Classificação (revisor, linha): " + ", ".join(f"{c} ({rev}, linha {l})" for c, rev, l in r["conflitos"]))


def rotulagem_modelo(a, fab):
    """Gera, em uma pasta, so as linhas que faltam para destravar H2, H5 e a auditoria dos negativos (ver `aplicacao/rotulagem.py`).
    Com --listar so mostra as contagens. So le o banco; recusa sobrescrever arquivos que ja existam."""
    pasta = Path(a.saida) if a.saida else S.OUT_DIR / "rotulagem"
    try:
        pasta_txt = pasta.relative_to(Path.cwd()).as_posix()
    except ValueError:
        pasta_txt = pasta.as_posix()
    plano = rotulagem.planejar(fab.repo, a.folga, a.semente, a.semente, a.aleatoria, a.h4, a.meta_h4 / 100, pasta_txt)
    print(f"Rotulagem mínima (folga de {a.folga:g}%, semente {plano['parametros']['semente']!r}):")
    print("\n".join(rotulagem.resumo_texto(plano)))
    arquivos = rotulagem.arquivos_do_plano(plano)
    if not arquivos:
        print("Nada a gerar: as três análises já estão destravadas.")
        return
    if a.listar:
        print("Arquivos que seriam gerados em " + pasta_txt + ": " + ", ".join(f"{n} ({k} linhas)" for n, k in arquivos))
        print("Nada foi gravado (--listar). Para gerar: python main.py rotulagem-modelo" + (f" --saida {pasta_txt}" if a.saida else ""))
        return
    alvos = [pasta / n for n, _ in arquivos] + [pasta / rotulagem.ARQ_LEIAME]
    existentes = [str(p) for p in alvos if p.exists()]
    if existentes:
        raise SystemExit("Já existem (podem ter respostas): " + ", ".join(existentes) + ". Escolha outra pasta com --saida ou apague os arquivos.")
    planilhas, csvs = exportacao.tabelas_rotulagem(plano, sorted(set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)))
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, tabelas in planilhas.items():
        fab.exportador.exportar(tabelas, pasta / nome)
    for nome, df in csvs.items():
        df.to_csv(pasta / nome, index=False, encoding="utf-8-sig")
    (pasta / rotulagem.ARQ_LEIAME).write_text("\n".join(rotulagem.leiame_pasta(plano)) + "\n", encoding="utf-8")
    print("Gerado:")
    for p in alvos:
        print("  ", p)
    print(f"Tempo estimado: cerca de {rotulagem.estimativa_horas(plano) / 60:.1f} h (ritmo suposto; veja o LEIA-ME.txt).")
    print("Próximos comandos (depois de preencher cada arquivo):")
    for nome, _ in arquivos:
        imp = {rotulagem.ARQ_ACHADOS: "achados-importar", rotulagem.ARQ_AUDITORIA: "auditoria-negativos-importar"}.get(nome, "triagem-importar")
        print(f"  python main.py {imp} {pasta_txt}/{nome}")


def migrar_robots(a, fab):
    """Reclassifica `bloqueado_por_robots` em `robots_inacessivel` quando o robots.txt nao foi lido (so conta, sem --aplicar)."""
    r = fab.repo.reclassificar_bloqueios_robots(aplicar=a.aplicar, pasta_backup=S.DATA_DIR / "backups")
    c = r["por_classe"]
    print(f"Chamadas de download com 'bloqueado_por_robots': {r['total']}")
    print(f"  robots.txt lido (HTTP 2xx), proibição do site, ficam como estão: {c['status_2xx']}")
    print(f"  robots.txt com erro 5xx, viram 'robots_inacessivel': {c['status_5xx']}")
    print(f"  robots.txt sem resposta (tempo esgotado ou rede), viram 'robots_inacessivel': {c['sem_status']}")
    if c["outro_status"]:
        print(f"  outro status (ficam como estão): {c['outro_status']}")
    if not a.aplicar:
        print(f"Nada foi alterado. Para gravar ({r['para_inacessivel']} chamadas), rode: python main.py migrar-robots --aplicar")
    elif r["atualizadas"]:
        print(f"Cópia de segurança: {r['backup']}")
        print(f"Chamadas atualizadas: {r['atualizadas']} (os arquivos brutos e as outras tabelas não foram tocados).")
    else:
        print("Nada a atualizar: o banco já está migrado.")


def main():
    p = argparse.ArgumentParser(description="Survey automation (AI in Public Security)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("estimar"); s.add_argument("--simulado", action="store_true")
    s.add_argument("--ufs", nargs="*", help="conta só estas UFs (padrão: as 27)")
    s.add_argument("--tecnologias", nargs="+", metavar="TECNOLOGIA", help=_AJUDA_TECNOLOGIAS)
    for nome in ETAPAS:
        s = sub.add_parser(nome)
        s.add_argument("--retomar", help="run_id of an interrupted run (same configuration)")
        multi = nome in ("baixar", "classificar")
        s.add_argument("--de", nargs="+" if multi else None,
                       help="run_id that holds the input data for this stage" + ("; aceita varios (a entrada e a uniao deles, "
                                                                                "sem repeticoes)" if multi else ""))
        s.add_argument("--simulado", action="store_true", help="fake adapters, no cost")
        s.add_argument("--ufs", nargs="*"); s.add_argument("--termos", nargs="*")
        if "busca_web" in ETAPAS[nome]:
            s.add_argument("--tecnologias", nargs="+", metavar="TECNOLOGIA", help=_AJUDA_TECNOLOGIAS)
        s.add_argument("--paginas", type=int); s.add_argument("--perfil")
        s.add_argument("--idioma-resultados", metavar="LR",
                       help="filtro de idioma dos resultados no Scholar (lr, ex. lang_pt)")
        s.add_argument("--limite", type=int, help="max. items per stage (testing)")
        s.add_argument("--auditoria", type=int, default=0,
                       help="N URLs descartadas pelo pre-filtro de palavras-chave tambem sao baixadas e classificadas (auditoria)")
        if nome in ("baixar", "classificar"):
            s.add_argument("--urls", type=int, nargs="+", metavar="URL_ID",
                           help="so estes url_id (erro se nenhum deles for candidato nas execucoes de --de)")
            s.add_argument("--listar", action="store_true",
                           help="mostra o que seria " + ("baixado" if nome == "baixar" else "classificado")
                           + " (quantidade, url_id, UF, dominio e motivo) e sai: sem rede, sem chamada de API e sem gravar nada")
        if nome == "baixar":
            s.add_argument("--so-sem-pagina", action="store_true",
                           help="pula as URLs que ja tem pagina com texto extraido em QUALQUER execucao (dentro ou fora do relatorio)")
            s.add_argument("--so-falha", metavar="MOTIVO",
                           help="so as URLs cuja tentativa de download MAIS RECENTE falhou com este motivo: "
                                + descricao_motivos_falha_download())
        if nome == "classificar":
            s.add_argument("--so-nao-classificadas", action="store_true",
                           help="pula os pares (url_id, UF) que ja tem classificacao valida com o mesmo prompt_versao e o mesmo "
                                "classificador em alguma execucao do relatorio (uma nova versao do prompt reclassifica)")
    s = sub.add_parser("triar-escopo", help="pergunta ao modelo de linguagem, em lotes, se cada resultado coletado esta no escopo (so por amostra)")
    s.add_argument("--fonte", required=True, choices=("artigos", "web"))
    s.add_argument("--amostra", type=int, help="tamanho da amostra deterministica (regra 11: use amostras pequenas)")
    s.add_argument("--estratificar", action="store_true", help="espalha a amostra por relevancia e termo (artigos) ou UF e download (web)")
    s.add_argument("--semente", default="triagem-escopo", help="semente da amostra (a mesma semente repete a mesma amostra)")
    s.add_argument("--lote", type=int, help=f"itens por chamada (padrao {TE.LOTE_PADRAO}, maximo {TE.LOTE_MAXIMO})")
    s.add_argument("--limite", type=int, help="maximo de itens a enviar nesta execucao")
    s.add_argument("--max-custo", type=float, help=f"teto de custo da execucao em US$ (padrao {TE.MAX_CUSTO_PADRAO_USD})")
    s.add_argument("--refazer", action="store_true", help="triar de novo itens que ja tem triagem com este prompt")
    s.add_argument("--estimar", action="store_true", help="mostra itens, chamadas e custo, sem nenhuma chamada e sem chave")
    s.add_argument("--tudo", action="store_true", help="permite rodar sem --amostra nem --limite (mostra a estimativa antes)")
    s.add_argument("--retomar", help="run_id de uma execucao interrompida (mesma configuracao e mesmo --lote)")
    s.add_argument("--simulado", action="store_true", help="triador falso, sem custo")
    # C6: exportacao e importacoes tambem aceitam --simulado (usam o banco simulado)
    s = sub.add_parser("exportar"); s.add_argument("--saida"); s.add_argument("--simulado", action="store_true")
    sub.add_parser("manual-modelo")
    s = sub.add_parser("execucao-excluir", help="tira uma execucao (piloto/teste) das views agregadas do relatorio")
    s.add_argument("run_id"); s.add_argument("--motivo", default=""); s.add_argument("--simulado", action="store_true")
    s = sub.add_parser("execucao-incluir", help="devolve uma execucao as views agregadas do relatorio")
    s.add_argument("run_id"); s.add_argument("--simulado", action="store_true")
    s = sub.add_parser("migrar-robots", help="separa, nas chamadas de download ja gravadas, a proibicao do site da falha de leitura do robots.txt (por padrao so mostra os totais)")
    s.add_argument("--aplicar", action="store_true", help="grava a mudanca (antes faz uma copia de seguranca em data/backups); sem isso nada e alterado")
    s.add_argument("--simulado", action="store_true")
    s = sub.add_parser("auditoria-negativos-modelo",
                       help="sorteia (por UF, reproduzivel) paginas que o modelo classificou sem achado, para uma pessoa conferir se perdeu alguma aplicacao")
    s.add_argument("--amostra", type=int, default=AN.AMOSTRA_PADRAO, help=f"tamanho da amostra (padrao {AN.AMOSTRA_PADRAO})")
    s.add_argument("--semente", default=AN.SEMENTE_PADRAO, help="semente do sorteio (a mesma semente repete a mesma amostra)")
    s.add_argument("--saida", help="arquivo .csv de saida (padrao: outputs/auditoria_negativos_amostra.csv)")
    s.add_argument("--simulado", action="store_true")
    s = sub.add_parser("rotulagem-modelo", help="gera so as linhas que faltam para destravar H2, H5 e a auditoria dos negativos (planilhas e CSV em outputs/rotulagem/)")
    s.add_argument("--saida", help="pasta de saida (padrao: outputs/rotulagem)")
    s.add_argument("--semente", help="semente dos sorteios (a mesma semente repete a mesma selecao); padrao 'rotulagem' (e 'auditoria-negativos' na auditoria)")
    s.add_argument("--folga", type=float, default=FOLGA_PADRAO_ROTULAGEM, help="folga percentual sobre o que falta (padrao 10)")
    s.add_argument("--aleatoria", action="store_true", help="achados: amostra aleatoria simples (serve a precisao global) em vez da enriquecida em provaveis erros")
    s.add_argument("--h4", action="store_true", help="gera tambem rotulagem_triagem_h4.xlsx, com artigos excluidos pelo modelo para a falsa exclusao (H4)")
    s.add_argument("--meta-h4", type=float, default=5.0, choices=(5.0, 2.0), help="meta de falsa exclusao em %% para o tamanho de --h4 (padrao 5)")
    s.add_argument("--listar", "--estimar", dest="listar", action="store_true", help="so mostra as contagens; nao grava nada")
    s.add_argument("--simulado", action="store_true")
    s = sub.add_parser("auditoria-negativos-importar", help="importa o CSV preenchido da auditoria dos negativos do modelo (idempotente)")
    s.add_argument("arquivo"); s.add_argument("--simulado", action="store_true")
    sub.add_parser("manual-artigos-modelo")
    sub.add_parser("painel-demo", help="cria data/demo.db com dados ficticios para conhecer o painel")
    s = sub.add_parser("painel", help="abre o painel de resultados e de revisao no navegador")
    s.add_argument("--simulado", action="store_true"); s.add_argument("--demo", action="store_true")
    s.add_argument("--porta", type=int, default=8000); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--somente-leitura", action="store_true", help="nenhuma decisao pode ser gravada")
    s = sub.add_parser("painel-relatorio", help="gera um arquivo HTML unico (sem scripts) com os resultados do banco")
    s.add_argument("--simulado", action="store_true"); s.add_argument("--demo", action="store_true")
    s.add_argument("--saida", help="arquivo .html de saida (padrao: outputs/relatorio_AAAAMMDD_HHMM.html)")
    s.add_argument("--incluir-nao-verificados", action="store_true",
                   help="acrescenta, em secao separada e marcados, os achados ainda nao verificados por humano")
    for nome in ("manual-importar", "manual-artigos-importar", "triagem-importar", "achados-importar"):
        s = sub.add_parser(nome); s.add_argument("arquivo"); s.add_argument("--simulado", action="store_true")
        if nome in ("triagem-importar", "achados-importar"):
            s.add_argument("--independente", action="store_true",
                           help="revisao independente: so entra no historico, nao altera a decisao final")

    a = p.parse_args()
    fab = Fabrica(simulado=getattr(a, "simulado", False), demo=getattr(a, "demo", False))
    if a.cmd == "estimar":
        estimar(a)
    elif a.cmd in ETAPAS:
        rodar(a, ETAPAS[a.cmd])
    elif a.cmd == "triar-escopo":
        triar_escopo(a)
    elif a.cmd == "exportar":
        tabelas = exportacao.montar_tabelas(fab.repo, C.UFS)
        # C6: com --simulado o arquivo padrao ganha o prefixo "simulado_"
        saida = a.saida or S.OPCOES["excel"]["pasta"] / f"{'simulado_' if a.simulado else ''}resultado_{datetime.now():%Y%m%d_%H%M}.xlsx"
        print("Generated:", fab.exportador.exportar(tabelas, saida))
    elif a.cmd == "manual-modelo":
        S.OUT_DIR.mkdir(parents=True, exist_ok=True)
        caminho = S.OUT_DIR / "buscas_manuais_modelo.csv"
        pd.DataFrame(manual.gerar_modelo_manual(C.TERMOS, C.BASES_MANUAIS)).to_csv(
            caminho, index=False, encoding="utf-8-sig")
        print("Generated:", caminho)
    elif a.cmd == "painel-demo":
        import painel_demo
        print("Generated:", painel_demo.construir(S.DATA_DIR))
    elif a.cmd == "painel":
        abrir_painel(a, fab)
    elif a.cmd == "painel-relatorio":
        gerar_relatorio(a, fab)
    elif a.cmd == "execucao-excluir":
        fab.repo.definir_no_relatorio(a.run_id, False, a.motivo or None)
        print(f"Execução {a.run_id} fora do relatório (os dados continuam no banco; reverta com execucao-incluir).")
    elif a.cmd == "execucao-incluir":
        fab.repo.definir_no_relatorio(a.run_id, True)
        print(f"Execução {a.run_id} dentro do relatório.")
    elif a.cmd == "migrar-robots":
        migrar_robots(a, fab)
    elif a.cmd == "auditoria-negativos-modelo":
        auditoria_negativos_modelo(a, fab)
    elif a.cmd == "rotulagem-modelo":
        rotulagem_modelo(a, fab)
    elif a.cmd == "auditoria-negativos-importar":
        auditoria_negativos_importar(a, fab)
    elif a.cmd == "manual-artigos-modelo":
        S.OUT_DIR.mkdir(parents=True, exist_ok=True)
        caminho = S.OUT_DIR / "artigos_manuais_modelo.csv"
        pd.DataFrame(columns=manual.COLUNAS_ARTIGOS_MANUAIS).to_csv(caminho, index=False, encoding="utf-8-sig")
        print("Generated:", caminho)
    elif a.cmd == "manual-artigos-importar":
        df = pd.read_csv(a.arquivo, encoding="utf-8-sig", dtype=str)
        manual.validar_artigos_manuais(df, C.TERMOS, C.BASES_MANUAIS)
        ocorrencias, novos = fab.repo.importar_artigos_manuais(df)
        print(f"Ocorrências novas: {ocorrencias} | artigos novos: {novos} | linhas no arquivo: {len(df)}")
    elif a.cmd == "manual-importar":
        df = pd.read_csv(a.arquivo, encoding="utf-8-sig")        # C7: o modelo e gravado com BOM
        manual.validar_manuais(df[df["n_resultados"].notna()], C.TERMOS, C.BASES_MANUAIS)
        print("Rows imported:", fab.repo.importar_buscas_manuais(df))
    elif a.cmd == "triagem-importar":
        print("Rows imported:", fab.repo.importar_triagem(pd.read_excel(a.arquivo, sheet_name="Triagem"),
                                                    so_historico=a.independente))
        _avisar_conflitos(fab.repo, "artigo")
    elif a.cmd == "achados-importar":
        permitidos = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
        print("Findings verified:", fab.repo.importar_verificacao_achados(
            pd.read_excel(a.arquivo, sheet_name="Achados"), permitidos, so_historico=a.independente))
        _avisar_conflitos(fab.repo, "achado")


if __name__ == "__main__":
    main()
