import argparse
import logging
import subprocess
from datetime import datetime
import pandas as pd

import config.settings as S
from config import consultas as C, prompts as P, vocabulario as V
from composicao import Fabrica
from dominio.esquemas import esquema_classificacao
from dominio.modelos import ParametrosClassificacao
from dominio.servicos import gerar_consultas_web
from aplicacao import busca_academica, busca_web, download, classificacao, manual, exportacao
from infra.log import iniciar_log

ETAPAS = {
    "academico": ["academico"],
    "busca-web": ["busca_web"],
    "baixar": ["download"],
    "classificar": ["classificacao"],
    "pipeline-uf": ["busca_web", "download", "classificacao"],
    "tudo": ["academico", "busca_web", "download", "classificacao"],
}


def _commit_git():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def _params_classificacao():
    esquema = esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA)
    return ParametrosClassificacao(
        versao_prompt=P.PROMPT_VERSAO, sistema=P.PROMPT_SISTEMA, usuario_template=P.PROMPT_USUARIO,
        esquema=esquema, tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS),
        max_chars=S.CLASSIFICACAO["max_chars_texto"],
        usar_snippet_se_falhar=S.CLASSIFICACAO["usar_snippet_se_falhar"])


def estimar(args):
    consultas = gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS)
    print(f"Academic terms: {len(C.TERMOS)} | pages per term (max.): {C.MAX_PAGINAS_ACADEMICO}")
    print(f"Academic search credits (worst case): {len(C.TERMOS) * C.MAX_PAGINAS_ACADEMICO}")
    print(f"Web queries: {len(consultas)} | estimated cost: US$ {len(consultas) * S.PRECO_BUSCA_WEB_USD:.2f}")
    print(f"Pages to download (ceiling): {C.POLITICA_DOWNLOAD.max_urls_por_uf * len(C.UFS)}")
    print(f"Classifications (ceiling): {C.POLITICA_DOWNLOAD.max_urls_por_uf * len(C.UFS)} (cost depends on the model and text sizes)")
    fab = Fabrica(simulado=args.simulado)
    # C9: sem chave (ou sem adaptador) a estimativa continua valendo; so o saldo fica indisponivel.
    # TODO(verificar): se o endpoint de conta da SerpApi (saldo) consome creditos
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
                                   snap["hash"], snap["json"], _commit_git(), args.retomar, run_origem=de)
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
            consultas = [c for c in gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, ufs)
                         if not args.perfil or c.perfil == args.perfil]
            busca_web.executar(repo, fab.bruto, fab.busca_web, run_id, consultas, C.PERFIS_BUSCA_WEB,
                               fab.segredos, S.PAUSAS["busca_web"], args.limite)
        if "download" in etapas:
            download.executar(repo, fab.bruto, fab.fetcher, fab.extrator, run_id, origem_dl,
                              C.POLITICA_DOWNLOAD, fab.segredos, S.PAUSAS["download"], args.limite, set(ufs))
        if "classificacao" in etapas:
            classificacao.executar(repo, fab.bruto, fab.classificador, run_id, origem_cl, _params_classificacao(),
                                   C.UFS, fab.segredos, S.PAUSAS["classificacao"], args.limite, set(ufs))
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
    # C6: exportacao e importacoes tambem aceitam --simulado (usam o banco simulado)
    s = sub.add_parser("exportar"); s.add_argument("--saida"); s.add_argument("--simulado", action="store_true")
    sub.add_parser("manual-modelo")
    for nome in ("manual-importar", "triagem-importar", "achados-importar"):
        s = sub.add_parser(nome); s.add_argument("arquivo"); s.add_argument("--simulado", action="store_true")

    a = p.parse_args()
    fab = Fabrica(simulado=getattr(a, "simulado", False))
    if a.cmd == "estimar":
        estimar(a)
    elif a.cmd in ETAPAS:
        rodar(a, ETAPAS[a.cmd])
    elif a.cmd == "exportar":
        tabelas = exportacao.montar_tabelas(fab.repo, C.UFS)
        # C6: com --simulado o arquivo padrao ganha o prefixo "simulado_"
        saida = a.saida or S.OUT_DIR / f"{'simulado_' if a.simulado else ''}resultado_{datetime.now():%Y%m%d_%H%M}.xlsx"
        print("Generated:", fab.exportador.exportar(tabelas, saida))
    elif a.cmd == "manual-modelo":
        S.OUT_DIR.mkdir(parents=True, exist_ok=True)
        caminho = S.OUT_DIR / "buscas_manuais_modelo.csv"
        pd.DataFrame(manual.gerar_modelo_manual(C.TERMOS, C.BASES_MANUAIS)).to_csv(
            caminho, index=False, encoding="utf-8-sig")
        print("Generated:", caminho)
    elif a.cmd == "manual-importar":
        df = pd.read_csv(a.arquivo)
        manual.validar_manuais(df[df["n_resultados"].notna()], C.TERMOS, C.BASES_MANUAIS)
        print("Rows imported:", fab.repo.importar_buscas_manuais(df))
    elif a.cmd == "triagem-importar":
        print("Rows imported:", fab.repo.importar_triagem(pd.read_excel(a.arquivo, sheet_name="Triagem")))
    elif a.cmd == "achados-importar":
        permitidos = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
        print("Findings verified:", fab.repo.importar_verificacao_achados(
            pd.read_excel(a.arquivo, sheet_name="Achados"), permitidos))


if __name__ == "__main__":
    main()
