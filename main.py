import argparse
import hashlib
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
import pandas as pd

import config.settings as S
from config import consultas as C, prompts as P, vocabulario as V
from composicao import Fabrica
from dominio.esquemas import esquema_classificacao
from dominio.modelos import ParametrosClassificacao
from dominio.servicos import gerar_consultas_web, palavras_chave_tecnologia
from aplicacao import busca_academica, busca_web, download, classificacao, manual, exportacao
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


def estimar(args):
    consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS, C.MUNICIPIOS, C.MODELOS_WEB_MUNICIPAIS)
    print(f"Academic terms: {len(C.TERMOS)} | pages per term (max.): {C.MAX_PAGINAS_ACADEMICO}")
    print(f"Academic search credits (worst case): {len(C.TERMOS) * C.MAX_PAGINAS_ACADEMICO}")
    print(f"Web queries: {len(consultas)} | estimated cost: US$ {len(consultas) * S.PRECO_BUSCA_WEB_USD:.2f}")
    print(f"Pages to download (ceiling): {C.POLITICA_DOWNLOAD.max_urls_por_uf * len(C.UFS)}")
    print(f"Classifications (ceiling): {C.POLITICA_DOWNLOAD.max_urls_por_uf * len(C.UFS)} (cost depends on the model and text sizes)")
    fab = Fabrica(simulado=args.simulado)
    # C9: sem chave (ou sem adaptador) a estimativa continua valendo; so o saldo fica indisponivel.
    # O endpoint de conta da SerpApi e gratuito e nao conta na cota (documentacao, consultada em 14/10/2026).
    try:
        saldo = getattr(fab.academico, "saldo", lambda: None)()
        print(f"Academic provider balance: {saldo}")
    except (Exception, SystemExit) as e:      # a fabrica encerra com SystemExit quando falta a chave
        print(f"Saldo: indisponível ({e})")


def rodar(args, etapas):
    fab = Fabrica(simulado=args.simulado)
    repo, snap = fab.repo, S.snapshot_config()
    # C5: na retomada, sem --de, reaproveita o --de guardado na execucao original
    de = args.de or (repo.obter_run_origem(args.retomar) if args.retomar else None)
    # C5: etapa que le o resultado de outra etapa que nao roda no mesmo comando exige --de
    precisa_de = (("download" in etapas and "busca_web" not in etapas)
                  or ("classificacao" in etapas and "download" not in etapas))
    if precisa_de and not de:
        raise SystemExit(f"O comando '{args.cmd}' lê dados de uma etapa anterior que não roda nele: "
                         "informe --de <run_id> com a execução que contém essa entrada.")
    run_id = repo.iniciar_execucao(args.cmd + (" [simulado]" if args.simulado else ""),
                                   snap["hash"], snap["json"], _commit_git(), args.retomar, run_origem=de,
                                   ambiente_json=_ambiente(args))
    iniciar_log(run_id, S.LOG_DIR)
    ufs = {k: v for k, v in C.UFS.items() if not args.ufs or k in args.ufs}
    termos = [t for t in C.TERMOS if not args.termos or t.id in args.termos]
    # where each stage reads from: from the run itself if the previous stage runs together; otherwise from --de
    origem_dl = run_id if "busca_web" in etapas else de
    origem_cl = run_id if "download" in etapas else de
    logging.info("run_id=%s | stages=%s | states=%d | simulated=%s", run_id, etapas, len(ufs), args.simulado)

    status = "concluida"
    try:
        if "academico" in etapas:
            saldo = getattr(fab.academico, "saldo", lambda: None)
            repo.registrar_saldo(run_id, fab.academico.nome, "inicio", saldo())
            busca_academica.executar(repo, fab.bruto, fab.academico, run_id, termos, C.FILTROS_ACADEMICOS,
                                     args.paginas or C.MAX_PAGINAS_ACADEMICO, fab.segredos, S.PAUSAS["busca_academica"])
            repo.registrar_saldo(run_id, fab.academico.nome, "fim", saldo())
        if "busca_web" in etapas:
            consultas = [c for c in gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, ufs, C.MUNICIPIOS, C.MODELOS_WEB_MUNICIPAIS)
                         if not args.perfil or c.perfil == args.perfil]
            busca_web.executar(repo, fab.bruto, fab.busca_web, run_id, consultas, C.PERFIS_BUSCA_WEB,
                               fab.segredos, S.PAUSAS["busca_web"], args.limite)
        if "download" in etapas:
            download.executar(repo, fab.bruto, fab.fetcher, fab.extrator, run_id, origem_dl,
                              C.POLITICA_DOWNLOAD, fab.segredos, S.PAUSAS["download"], args.limite, set(ufs),
                              auditoria=args.auditoria or 0, semente=run_id)
        if "classificacao" in etapas:
            classificacao.executar(repo, fab.bruto, fab.classificador, run_id, origem_cl, _params_classificacao(),
                                   C.UFS, fab.segredos, S.PAUSAS["classificacao"], args.limite, set(ufs),
                                   max_falhas_por_item=S.CLASSIFICACAO["max_falhas_por_item"])
    except KeyboardInterrupt:
        status = "interrompida"
        logging.warning("Interrupted. Resume with: python main.py %s --retomar %s", args.cmd, run_id)
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


def abrir_painel(a, fab):
    """Liga o painel aos adaptadores e o serve em 127.0.0.1. Importa o servidor so aqui: as demais etapas nao precisam dele."""
    if a.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("O painel só aceita conexões locais (127.0.0.1): ele não tem autenticação.")
    import uvicorn
    from painel.app import Contexto, criar_app
    banco = "demo" if a.demo else "simulado" if a.simulado else "real"
    contexto = Contexto(
        banco=banco, nome_banco=fab.caminho_banco.name, somente_leitura=a.somente_leitura,
        pasta_backup=S.DATA_DIR / "backups", ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
        status_definicoes=dict(V.STATUS), termos={t.id: t.query for t in C.TERMOS}, bases=tuple(C.BASES_MANUAIS),
        comando_criar_banco="python main.py painel-demo" if a.demo else
        "python main.py tudo --simulado --ufs PI CE --paginas 1" if a.simulado else "python main.py pipeline-uf --ufs PI --limite 5")
    if not fab.caminho_banco.exists() and a.demo:
        raise SystemExit("O banco de demonstração não existe. Rode antes: python main.py painel-demo")
    app = criar_app(fab.leitura_painel(), fab.novo_repositorio, fab.bruto, contexto)
    print(f"Painel ({banco}): http://{a.host}:{a.porta}   (Ctrl+C para encerrar)")
    uvicorn.run(app, host=a.host, port=a.porta, log_level="warning")


def main():
    p = argparse.ArgumentParser(description="Survey automation (AI in Public Security)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("estimar"); s.add_argument("--simulado", action="store_true")
    for nome in ETAPAS:
        s = sub.add_parser(nome)
        s.add_argument("--retomar", help="run_id of an interrupted run (same configuration)")
        s.add_argument("--de", help="run_id that holds the input data for this stage")
        s.add_argument("--simulado", action="store_true", help="fake adapters, no cost")
        s.add_argument("--ufs", nargs="*"); s.add_argument("--termos", nargs="*")
        s.add_argument("--paginas", type=int); s.add_argument("--perfil")
        s.add_argument("--limite", type=int, help="max. items per stage (testing)")
        s.add_argument("--auditoria", type=int, default=0,
                       help="N URLs descartadas pelo pre-filtro de palavras-chave tambem sao baixadas e classificadas (auditoria)")
    # C6: exportacao e importacoes tambem aceitam --simulado (usam o banco simulado)
    s = sub.add_parser("exportar"); s.add_argument("--saida"); s.add_argument("--simulado", action="store_true")
    sub.add_parser("manual-modelo")
    s = sub.add_parser("execucao-excluir", help="tira uma execucao (piloto/teste) das views agregadas do relatorio")
    s.add_argument("run_id"); s.add_argument("--motivo", default=""); s.add_argument("--simulado", action="store_true")
    s = sub.add_parser("execucao-incluir", help="devolve uma execucao as views agregadas do relatorio")
    s.add_argument("run_id"); s.add_argument("--simulado", action="store_true")
    sub.add_parser("manual-artigos-modelo")
    sub.add_parser("painel-demo", help="cria data/demo.db com dados ficticios para conhecer o painel")
    s = sub.add_parser("painel", help="abre o painel de resultados e de revisao no navegador")
    s.add_argument("--simulado", action="store_true"); s.add_argument("--demo", action="store_true")
    s.add_argument("--porta", type=int, default=8000); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--somente-leitura", action="store_true", help="nenhuma decisao pode ser gravada")
    for nome in ("manual-importar", "manual-artigos-importar", "triagem-importar", "achados-importar"):
        s = sub.add_parser(nome); s.add_argument("arquivo"); s.add_argument("--simulado", action="store_true")
        if nome == "triagem-importar":
            s.add_argument("--independente", action="store_true",
                           help="revisao independente: so entra no historico, nao altera a decisao final")

    a = p.parse_args()
    fab = Fabrica(simulado=getattr(a, "simulado", False), demo=getattr(a, "demo", False))
    if a.cmd == "estimar":
        estimar(a)
    elif a.cmd in ETAPAS:
        rodar(a, ETAPAS[a.cmd])
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
    elif a.cmd == "execucao-excluir":
        fab.repo.definir_no_relatorio(a.run_id, False, a.motivo or None)
        print(f"Execução {a.run_id} fora do relatório (os dados continuam no banco; reverta com execucao-incluir).")
    elif a.cmd == "execucao-incluir":
        fab.repo.definir_no_relatorio(a.run_id, True)
        print(f"Execução {a.run_id} dentro do relatório.")
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
    elif a.cmd == "achados-importar":
        permitidos = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
        print("Findings verified:", fab.repo.importar_verificacao_achados(
            pd.read_excel(a.arquivo, sheet_name="Achados"), permitidos))


if __name__ == "__main__":
    main()
