"""Fase 2 / RC13: download e classificacao leem candidatos de VARIAS execucoes de busca, e os filtros de resgate
(`--so-sem-pagina`, `--so-falha`, `--urls`, `--so-nao-classificadas`, `--listar`) nao baixam nem classificam duas vezes.
Tudo offline: adaptadores simulados e bancos temporarios."""
import hashlib
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

import main
from adaptadores import simulados
from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada, ClassificadorSimulado, ExtratorSimulado, FetcherSimulado, _reg
from aplicacao import busca_web, classificacao, download
from aplicacao.planejamento import planejar_classificacao, planejar_download
from config import consultas as C, vocabulario as V
from dominio.entrada import separar_runs, juntar_runs, motivo_falha_download_valido
from dominio.esquemas import esquema_classificacao
from dominio.modelos import ArquivoBaixado, ParametrosClassificacao, RegistroChamada, RespostaBusca, ResultadoWeb, TextoExtraido
from dominio.servicos import gerar_consultas_web
from infra.util import agora
from test_painel import _app

UFS = ("PI", "CE")


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(tmp_path / "simulado.db")


@pytest.fixture
def bruto(tmp_path):
    return BrutoLocal(tmp_path / "raw")


class BuscaOutra(BuscaSimulada):
    """Segunda rodada de busca: uma URL em comum com BuscaSimulada (a /pi/3, agora na posicao 1 e com outro titulo)
    e URLs novas (/outro/...)."""
    def buscar(self, consulta, filtros):
        uf = consulta.uf.lower()
        res = [ResultadoWeb(f"https://exemplo.gov.br/{uf}/3", f"Reconhecimento facial {consulta.uf} 3 (rodada B)",
                            "câmeras com reconhecimento facial", None, 1),
               ResultadoWeb(f"https://exemplo.gov.br/outro/{uf}/1", f"Reconhecimento facial {consulta.uf} outro 1",
                            "câmeras com reconhecimento facial", None, 2)]
        return RespostaBusca(res, _reg(self.nome, "buscar", raw=b'{"simulado": true}'))


class FetcherComFalhas(FetcherSimulado):
    """Falha nas URLs cujo texto contem a chave, com o erro e o status dados; as demais baixam normalmente."""
    def __init__(self, falhas):
        self.falhas = falhas

    def baixar(self, url):
        for pedaco, (erro, status) in self.falhas.items():
            if pedaco in url:
                reg = RegistroChamada(provedor=self.nome, operacao="baixar", parametros={}, requisitado_em=agora(),
                                      http_status=status, latencia_ms=1, erro=erro)
                return ArquivoBaixado(url, status, "", b"", False, reg)
        return super().baixar(url)


class FetcherProibido:
    nome = "simulado"

    def baixar(self, url):
        raise AssertionError("o --listar nao pode baixar nada")


class ExtratorSemTexto(ExtratorSimulado):
    def extrair(self, conteudo, content_type, url):
        return TextoExtraido("", "simulado", False, "sem_texto")


def _params(versao="v-teste"):
    return ParametrosClassificacao(
        versao_prompt=versao, sistema="sistema", usuario_template="{nome} {uf} {url} {titulo} {origem} {texto}",
        esquema=esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA),
        tecnologias=tuple(V.TECNOLOGIAS), status=tuple(V.STATUS))


def _novo(repo, origem=None, comando="teste"):
    return repo.iniciar_execucao(comando, "h", "{}", None, run_origem=origem)


def _busca(repo, bruto, busca=None, uf="PI"):
    run = _novo(repo)
    ufs = {k: v for k, v in C.UFS.items() if k in (uf,)}
    busca_web.executar(repo, bruto, busca or BuscaSimulada(), run, gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, ufs),
                       C.PERFIS_BUSCA_WEB, [], 0)
    return run


def _baixar(repo, bruto, origem, fetcher=None, extrator=None, **filtros):
    run = _novo(repo, origem, "baixar")
    download.executar(repo, bruto, fetcher or FetcherSimulado(), extrator or ExtratorSimulado(), run, origem,
                      C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"}, **filtros)
    return run


def _classificar(repo, bruto, origem, versao="v-teste", **filtros):
    run = _novo(repo, origem, "classificar")
    classificacao.executar(repo, bruto, ClassificadorSimulado(), run, origem, _params(versao), C.UFS, [], 0,
                           ufs={"PI"}, **filtros)
    return run


def _n(repo, sql, *args):
    return repo.conn.execute(sql, args).fetchone()[0]


def _url_id(repo, caminho):
    return _n(repo, "SELECT url_id FROM urls WHERE url_original LIKE ?", f"https://exemplo.gov.br{caminho}%")


# ---------- separar_runs ----------
def test_separar_runs_aceita_texto_lista_e_virgulas_sem_repeticao():
    assert separar_runs(None) == [] and separar_runs("") == [] and separar_runs([]) == []
    assert separar_runs("a") == ["a"] and separar_runs("a,b") == ["a", "b"]
    assert separar_runs(["a", "b,c", "a", " d ", ""]) == ["a", "b", "c", "d"]
    assert juntar_runs(["b", "a", "b"]) == "b,a" and juntar_runs([]) is None


def test_motivos_de_falha_validos():
    assert all(motivo_falha_download_valido(m) for m in
               ("robots_inacessivel", "bloqueado_por_robots", "erro_de_rede", "erro_de_leitura", "http_403", "http_404"))
    assert not any(motivo_falha_download_valido(m) for m in ("ok", "http_", "http_99", "tempo", "", None))


# ---------- run_origem separado por virgula ----------
def test_varias_origens_sao_guardadas_em_ordem_e_voltam_como_lista(repo):
    a, b = _novo(repo), _novo(repo)
    run = _novo(repo, [b, a, b])
    assert repo.obter_run_origem(run) == f"{b},{a}"
    assert separar_runs(repo.obter_run_origem(run)) == [b, a]
    assert _novo(repo, f"{a},{b}") and _n(repo, "SELECT COUNT(*) FROM execucoes WHERE run_origem=?", f"{a},{b}") == 1
    assert repo.obter_run_origem(_novo(repo, a)) == a                      # uma so: igual ao formato antigo


def test_retomar_preserva_ou_troca_varias_origens(repo):
    a, b, c = _novo(repo), _novo(repo), _novo(repo)
    run = _novo(repo, [a, b])
    assert repo.iniciar_execucao("teste", "h", "{}", None, retomar=run) == run
    assert repo.obter_run_origem(run) == f"{a},{b}"
    repo.iniciar_execucao("teste", "h", "{}", None, retomar=run, run_origem=[c, a])
    assert repo.obter_run_origem(run) == f"{c},{a}"


def test_cada_origem_precisa_existir_e_nada_e_gravado(repo):
    a = _novo(repo)
    antes = _n(repo, "SELECT COUNT(*) FROM execucoes")
    with pytest.raises(SystemExit) as e:
        _novo(repo, [a, "nao_existe_2"])
    assert "nao_existe_2" in str(e.value) and "--de" in str(e.value)
    assert _n(repo, "SELECT COUNT(*) FROM execucoes") == antes


def test_painel_mostra_cada_origem_com_link_e_alimentou_acha_pela_lista(tmp_path, repo):
    a, b, c = _novo(repo, comando="busca-web"), _novo(repo, comando="busca-web"), _novo(repo, comando="outra")
    d = _novo(repo, [a, b], "baixar")
    banco = tmp_path / "simulado.db"
    leitura = LeituraPainelSQLite(banco)
    assert leitura.execucao(d)["runs_origem"] == [a, b]
    assert leitura.execucao(a)["run_destino"] == [d] and leitura.execucao(b)["run_destino"] == [d]
    assert leitura.execucao(c)["run_destino"] == [] and leitura.execucao(c)["runs_origem"] == []
    assert {e["run_id"]: e["runs_origem"] for e in leitura.execucoes()}[d] == [a, b]
    cli = TestClient(_app(banco, tmp_path / "raw", tmp_path, nome="simulado")[0])
    h = cli.get(f"/execucoes/{d}").text
    assert f'<a href="/execucoes/{a}">' in h and f'<a href="/execucoes/{b}">' in h and f"{a},{b}" not in h
    assert f'<a href="/execucoes/{d}">' in cli.get(f"/execucoes/{b}").text            # "Alimentou"
    lista = cli.get("/execucoes").text
    assert f"entrada: <code>{a}</code>, <code>{b}</code>" in lista and f"{a},{b}" not in lista
    assert cli.get(f"/execucoes/{a},{b}").status_code == 404                            # a virgula nao e um run_id


def test_leitura_de_classificadores_traz_a_lista_de_origens(tmp_path, repo):
    a, b = _novo(repo, comando="baixar"), _novo(repo, comando="baixar")
    k = _novo(repo, [a, b], "classificar")
    leitura = LeituraPainelSQLite(tmp_path / "simulado.db")
    assert leitura.execucao_classificacao(k)["runs_origem"] == [a, b]
    assert {e["run_id"]: e["runs_origem"] for e in leitura.execucoes_classificacao()}[k] == [a, b]


# ---------- candidatos de varias execucoes ----------
def test_candidatos_de_varias_execucoes_sao_unidos_sem_repeticao(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    so_a, so_b = repo.candidatos_download(a), repo.candidatos_download(b)
    uniao = repo.candidatos_download([a, b])
    assert len(so_a) == 3 and len(so_b) == 2 and len(uniao) == 4                       # a /pi/3 e comum
    assert repo.candidatos_download(f"{a},{b}") == uniao == repo.candidatos_download([b, a])
    assert [(c.uf, c.url_id) for c in uniao] == sorted((c.uf, c.url_id) for c in uniao)
    comum = next(c for c in uniao if c.url.endswith("/pi/3?utm_source=x") or c.url.endswith("/pi/3"))
    assert comum.titulo.endswith("(rodada B)")                                         # titulo da ocorrencia mais recente
    assert comum.melhor_posicao == 1                                                    # a menor posicao (A: 3, B: 1)
    ocorrencias = lambda cs: next(x.n_ocorrencias for x in cs if x.url_id == comum.url_id)  # noqa: E731
    assert comum.n_ocorrencias == ocorrencias(so_a) + ocorrencias(so_b)
    # a ordem das execucoes nao muda a decisao: o mais recente e o de maior resultado_id, nao o ultimo da lista
    assert next(c for c in repo.candidatos_download([b, a]) if c.url_id == comum.url_id).titulo == comum.titulo


def test_candidatos_de_origem_vazia_ou_sem_resultados(repo):
    assert repo.candidatos_download([]) == [] and repo.candidatos_download(None) == []
    assert repo.candidatos_download(_novo(repo)) == []


def test_limite_por_uf_vale_para_a_lista_unificada(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    politica = C.POLITICA_DOWNLOAD.__class__(palavras_chave=(), max_urls_por_uf=3)
    _, decisao, _ = planejar_download(repo, [a, b], politica)
    assert sum(ok for _, ok, _ in decisao) == 3
    assert [m for _, ok, m in decisao if not ok] == ["limite_por_uf"]


# ---------- download de duas buscas ----------
def test_baixar_de_duas_buscas_baixa_cada_url_uma_vez(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    d = _baixar(repo, bruto, [a, b])
    assert _n(repo, "SELECT COUNT(*) FROM paginas WHERE run_id=?", d) == 4
    assert _n(repo, "SELECT COUNT(*) FROM selecao_download WHERE run_id=? AND selecionada=1", d) == 4
    assert repo.obter_run_origem(d) == f"{a},{b}"


def test_so_sem_pagina_pula_o_que_ja_tem_texto_em_qualquer_execucao(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    d1 = _baixar(repo, bruto, a)                                         # as 3 de A
    repo.definir_no_relatorio(d1, False, "piloto")                       # fora do relatorio: conta do mesmo jeito
    d2 = _baixar(repo, bruto, [a, b], so_sem_pagina=True)
    assert {l[0] for l in repo.conn.execute("SELECT url_id FROM paginas WHERE run_id=?", (d2,))} == {
        _url_id(repo, "/outro/pi/1")}
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE run_id=? AND etapa='download'", d2) == 1
    d3 = _baixar(repo, bruto, [a, b], so_sem_pagina=True)                # nada novo a baixar
    assert _n(repo, "SELECT COUNT(*) FROM chamadas WHERE run_id=?", d3) == 0


def test_so_sem_pagina_conta_so_candidatos_de_resgate_no_limite_por_uf(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    _baixar(repo, bruto, a)
    politica = C.POLITICA_DOWNLOAD.__class__(palavras_chave=(), max_urls_por_uf=1)
    cands, decisao, _ = planejar_download(repo, [a, b], politica, so_sem_pagina=True)
    assert [c.url.split("/")[-3:] for c in cands] == [["outro", "pi", "1"]]            # so o resgate entra na conta
    assert [ok for _, ok, _ in decisao] == [True]


def test_so_falha_pega_so_a_tentativa_mais_recente_com_o_motivo(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    falhas = {"gov.br/pi/1": ("robots_inacessivel: sem robots.txt", None), "gov.br/pi/2": ("HTTP 403", 403),
              "gov.br/pi/3": ("tempo_excedido", None), "gov.br/outro/pi/1": ("HTTP 404", 404)}
    d1 = _baixar(repo, bruto, [a, b], FetcherComFalhas(falhas))
    assert _n(repo, "SELECT COUNT(*) FROM paginas WHERE run_id=?", d1) == 0
    ids = {fim: _url_id(repo, fim) for fim in ("/pi/1", "/pi/2", "/pi/3", "/outro/pi/1")}

    def escolhidas(motivo, origens=(a, b)):
        return sorted(c.url_id for c in planejar_download(repo, list(origens), C.POLITICA_DOWNLOAD, so_falha=motivo)[0])

    assert escolhidas("robots_inacessivel") == [ids["/pi/1"]]
    assert escolhidas("http_403") == [ids["/pi/2"]]
    assert escolhidas("erro_de_rede") == [ids["/pi/3"]]          # a view junta tempo_excedido e rede em erro_de_rede
    assert escolhidas("http_404") == [ids["/outro/pi/1"]]
    assert escolhidas("http_500") == [] and escolhidas("bloqueado_por_robots") == []
    # a /pi/1 volta a falhar com OUTRO motivo e as demais baixam: so a tentativa mais recente conta
    _baixar(repo, bruto, a, FetcherComFalhas({"gov.br/pi/1": ("HTTP 404", 404)}))
    assert escolhidas("robots_inacessivel") == [] and escolhidas("http_403") == [] and escolhidas("erro_de_rede") == []
    assert sorted(escolhidas("http_404")) == sorted([ids["/pi/1"], ids["/outro/pi/1"]])
    assert _n(repo, "SELECT COUNT(*) FROM paginas WHERE url_id=?", ids["/pi/2"]) == 1


def test_so_falha_com_motivo_invalido_lista_os_validos(repo, bruto):
    a = _busca(repo, bruto)
    with pytest.raises(SystemExit) as e:
        planejar_download(repo, [a], C.POLITICA_DOWNLOAD, so_falha="timeout")
    assert "timeout" in str(e.value) and "robots_inacessivel" in str(e.value) and "http_" in str(e.value)


def test_retomar_com_filtro_nao_muda_a_selecao_ja_feita(repo, bruto):
    """Excluir a propria execucao do filtro: o que ela baixou nao reabre vagas no limite por UF ao ser retomada."""
    a = _busca(repo, bruto)
    politica = C.POLITICA_DOWNLOAD.__class__(palavras_chave=(), max_urls_por_uf=2)
    run = _novo(repo, a, "baixar")
    for _ in range(2):                                                    # a segunda vez e a retomada
        download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run, a, politica, [], 0, ufs={"PI"},
                          so_sem_pagina=True)
    assert _n(repo, "SELECT COUNT(*) FROM selecao_download WHERE run_id=? AND selecionada=1", run) == 2
    assert _n(repo, "SELECT COUNT(*) FROM paginas WHERE run_id=?", run) == 2


def test_urls_restringe_e_exige_um_candidato(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    alvo = _url_id(repo, "/outro/pi/1")
    cands, _, _ = planejar_download(repo, [a, b], C.POLITICA_DOWNLOAD, urls=[alvo])
    assert [c.url_id for c in cands] == [alvo]
    with pytest.raises(SystemExit) as e:
        planejar_download(repo, [a], C.POLITICA_DOWNLOAD, urls=[alvo])               # nao e candidato so em A
    assert str(alvo) in str(e.value)
    with pytest.raises(SystemExit):
        planejar_download(repo, [a, b], C.POLITICA_DOWNLOAD, urls=[99999, 99998])
    d = _baixar(repo, bruto, [a, b], urls=[alvo])
    assert [l[0] for l in repo.conn.execute("SELECT url_id FROM paginas WHERE run_id=?", (d,))] == [alvo]


# ---------- classificacao de varias execucoes de download ----------
def test_itens_de_varias_execucoes_de_download_ficam_com_a_pagina_com_texto_mais_recente(repo, bruto):
    a = _busca(repo, bruto)
    d1 = _baixar(repo, bruto, a)
    d2 = _baixar(repo, bruto, a)                                         # as mesmas paginas, de novo
    itens = repo.itens_para_classificar([d1, d2])
    assert len(itens) == 3 and repo.itens_para_classificar(f"{d1},{d2}") == itens
    assert all(i.pagina_id == _n(repo, "SELECT MAX(pagina_id) FROM paginas WHERE url_id=? AND run_id=?", i.url_id, d2)
               for i in itens)
    # a pagina mais recente sem texto nao esconde a mais antiga com texto
    d3 = _baixar(repo, bruto, a, extrator=ExtratorSemTexto())
    velhos = repo.itens_para_classificar([d1, d2, d3])
    assert all(i.texto_path and i.pagina_id == _n(repo, "SELECT MAX(pagina_id) FROM paginas WHERE url_id=? AND run_id=?",
                                                  i.url_id, d2) for i in velhos)
    assert all(not i.texto_path for i in repo.itens_para_classificar([d3]))
    assert [(i.uf, i.url_id) for i in velhos] == sorted((i.uf, i.url_id) for i in velhos)


def test_classificar_de_duas_execucoes_de_download_une_os_itens(repo, bruto):
    a, b = _busca(repo, bruto), _busca(repo, bruto, BuscaOutra())
    d1 = _baixar(repo, bruto, a)
    d2 = _baixar(repo, bruto, b, so_sem_pagina=True)                     # so a /outro/pi/1 (a /pi/3 ja tem pagina)
    k = _classificar(repo, bruto, [d1, d2])
    assert _n(repo, "SELECT COUNT(*) FROM classificacoes WHERE run_id=?", k) == 4
    assert repo.obter_run_origem(k) == f"{d1},{d2}"


def test_so_nao_classificadas_pula_o_mesmo_prompt_e_reclassifica_prompt_novo(repo, bruto):
    a = _busca(repo, bruto)
    d = _baixar(repo, bruto, a)
    _classificar(repo, bruto, d)
    k2 = _classificar(repo, bruto, d, so_nao_classificadas=True)
    assert _n(repo, "SELECT COUNT(*) FROM classificacoes WHERE run_id=?", k2) == 0
    k3 = _classificar(repo, bruto, d, versao="v-novo", so_nao_classificadas=True)          # outro prompt: refaz
    assert _n(repo, "SELECT COUNT(*) FROM classificacoes WHERE run_id=?", k3) == 3
    k4 = _classificar(repo, bruto, d)                                                       # sem a flag: refaz tudo
    assert _n(repo, "SELECT COUNT(*) FROM classificacoes WHERE run_id=?", k4) == 3


def test_so_nao_classificadas_ignora_execucao_fora_do_relatorio_json_invalido_e_outro_classificador(repo, bruto):
    a = _busca(repo, bruto)
    d = _baixar(repo, bruto, a)
    k = _classificar(repo, bruto, d)
    pendentes = lambda: [i.url_id for i in planejar_classificacao(repo, [d], so_nao_classificadas=True,  # noqa: E731
                                                                  prompt_versao="v-teste", classificador="simulado")]
    assert pendentes() == []
    assert len(planejar_classificacao(repo, [d], so_nao_classificadas=True, prompt_versao="v-teste",
                                      classificador="outro:modelo")) == 3
    repo.definir_no_relatorio(k, False, "piloto")
    assert len(pendentes()) == 3
    repo.definir_no_relatorio(k, True)
    repo.conn.execute("UPDATE classificacoes SET json_valido=0 WHERE run_id=?", (k,))
    repo.conn.commit()
    assert len(pendentes()) == 3


def test_urls_na_classificacao(repo, bruto):
    a = _busca(repo, bruto)
    d = _baixar(repo, bruto, a)
    alvo = _url_id(repo, "/pi/2")
    k = _classificar(repo, bruto, d, urls=[alvo])
    assert [l[0] for l in repo.conn.execute("SELECT url_id FROM classificacoes WHERE run_id=?", (k,))] == [alvo]
    with pytest.raises(SystemExit) as e:
        planejar_classificacao(repo, [d], urls=[12345])
    assert "12345" in str(e.value)


# ---------- pela linha de comando (simulado) ----------
def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


def _banco(tmp_path):
    conn = sqlite3.connect(tmp_path / "data" / "simulado.db")
    conn.row_factory = sqlite3.Row
    return conn


def _c(tmp_path, sql, *args):
    return _banco(tmp_path).execute(sql, args).fetchone()[0]


def _runs(tmp_path, comando=None):
    return [r["run_id"] for r in _banco(tmp_path).execute(
        "SELECT run_id FROM execucoes WHERE comando LIKE ? ORDER BY iniciado_em, rowid", (f"{comando or ''}%",))]


def _duas_buscas(ambiente_cli, monkeypatch):
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "3")
    monkeypatch.setitem(simulados.POR_PORTA, "busca_web", BuscaOutra)
    _rodar(monkeypatch, "busca-web", "--simulado", "--ufs", "PI", "--limite", "3")
    return _runs(ambiente_cli, "busca-web")


def _impressao(tmp_path):
    return hashlib.sha256((tmp_path / "data" / "simulado.db").read_bytes()).hexdigest()


def test_pipeline_simulado_com_duas_buscas(ambiente_cli, monkeypatch):
    a, b = _duas_buscas(ambiente_cli, monkeypatch)
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b)
    d = _runs(ambiente_cli, "baixar")[0]
    assert _c(ambiente_cli, "SELECT run_origem FROM execucoes WHERE run_id=?", d) == f"{a},{b}"
    n_urls = _c(ambiente_cli, "SELECT COUNT(DISTINCT url_id) FROM resultados_web WHERE run_id IN (?,?)", a, b)
    assert n_urls > 3 and _c(ambiente_cli, "SELECT COUNT(*) FROM paginas WHERE run_id=?", d) == n_urls
    _rodar(monkeypatch, "classificar", "--simulado", "--ufs", "PI", "--de", d)
    k = _runs(ambiente_cli, "classificar")[0]
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM classificacoes WHERE run_id=?", k) == n_urls
    # a segunda classificacao, com a flag, nao classifica nada de novo
    _rodar(monkeypatch, "classificar", "--simulado", "--ufs", "PI", "--de", d, "--so-nao-classificadas")
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM classificacoes") == n_urls
    # retomar sem --de guarda as duas origens
    antes = _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas")
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--retomar", d)
    assert _c(ambiente_cli, "SELECT run_origem FROM execucoes WHERE run_id=?", d) == f"{a},{b}"
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM chamadas") == antes


def test_cli_so_sem_pagina_e_urls(ambiente_cli, monkeypatch):
    a, b = _duas_buscas(ambiente_cli, monkeypatch)
    alvo = _c(ambiente_cli, "SELECT url_id FROM urls WHERE url_original LIKE '%/outro/pi/1'")
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b, "--urls", str(alvo))
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM paginas") == 1
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b, "--so-sem-pagina")
    n_urls = _c(ambiente_cli, "SELECT COUNT(DISTINCT url_id) FROM resultados_web")
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM paginas") == n_urls                  # a ja baixada nao se repete
    assert _c(ambiente_cli, "SELECT COUNT(*) FROM paginas WHERE url_id=?", alvo) == 1
    import json
    argumentos = json.loads(_c(ambiente_cli, "SELECT ambiente_json FROM execucoes WHERE run_id=?",
                               _runs(ambiente_cli, "baixar")[-1]))["argumentos"]
    assert argumentos["so_sem_pagina"] is True and argumentos["de"] == [a, b]            # a execucao guarda as flags


def test_cli_erros_de_validacao_nao_criam_execucao(ambiente_cli, monkeypatch):
    a, b = _duas_buscas(ambiente_cli, monkeypatch)
    antes = len(_runs(ambiente_cli))
    for argv, trecho in (
            (("baixar", "--simulado", "--de", a, "nao_existe_9"), "nao_existe_9"),
            (("baixar", "--simulado", "--de", a, "--so-falha", "timeout"), "robots_inacessivel"),
            (("baixar", "--simulado", "--de", a, "--urls", "99999"), "99999"),
            (("baixar", "--simulado", "--de", a, "--listar", "--so-falha", "xpto"), "xpto"),
            (("classificar", "--simulado", "--de", a, "nao_existe_9", "--listar"), "nao_existe_9"),
            (("classificar", "--simulado", "--de", a, "--urls", "99999"), "99999"),
            (("classificar", "--simulado"), "--de")):
        with pytest.raises(SystemExit) as e:
            _rodar(monkeypatch, *argv)
        assert trecho in str(e.value), argv
    assert len(_runs(ambiente_cli)) == antes


def test_cli_listar_nao_baixa_nao_chama_api_e_nao_grava_nada(ambiente_cli, monkeypatch, capsys):
    a, b = _duas_buscas(ambiente_cli, monkeypatch)
    monkeypatch.setitem(simulados.POR_PORTA, "fetcher", FetcherProibido)
    monkeypatch.setitem(simulados.POR_PORTA, "classificador", FetcherProibido)
    antes = _impressao(ambiente_cli)
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b, "--listar")
    saida = capsys.readouterr().out
    assert "Seriam baixadas: 4 páginas" in saida and "Nada foi baixado nem gravado" in saida
    assert "/outro/" not in saida and saida.count("exemplo.gov.br") == 4 and "nunca_tentada" in saida
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b, "--listar", "--limite", "1")
    assert "Seriam baixadas: 1 páginas" in capsys.readouterr().out
    assert _impressao(ambiente_cli) == antes and len(_runs(ambiente_cli, "baixar")) == 0
    # classificar --listar: precisa de uma execucao de download (feita com o fetcher simulado de verdade)
    monkeypatch.setitem(simulados.POR_PORTA, "fetcher", FetcherSimulado)
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b)
    d = _runs(ambiente_cli, "baixar")[0]
    monkeypatch.setitem(simulados.POR_PORTA, "fetcher", FetcherProibido)
    antes = _impressao(ambiente_cli)
    capsys.readouterr()
    _rodar(monkeypatch, "classificar", "--simulado", "--ufs", "PI", "--de", d, "--listar")
    saida = capsys.readouterr().out
    assert "Seriam classificados: 4 itens" in saida and "Nenhuma chamada foi feita" in saida and "pagina" in saida
    _rodar(monkeypatch, "classificar", "--simulado", "--ufs", "PI", "--de", d, "--listar", "--so-nao-classificadas")
    assert "Seriam classificados: 4 itens" in capsys.readouterr().out
    assert _impressao(ambiente_cli) == antes and _runs(ambiente_cli, "classificar") == []


def test_cli_listar_mostra_so_o_resgate(ambiente_cli, monkeypatch, capsys):
    a, b = _duas_buscas(ambiente_cli, monkeypatch)
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a)             # as 3 de A
    capsys.readouterr()
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b, "--so-sem-pagina", "--listar")
    saida = capsys.readouterr().out
    assert "Seriam baixadas: 1 páginas" in saida and "--so-sem-pagina" in saida
    _rodar(monkeypatch, "baixar", "--simulado", "--ufs", "PI", "--de", a, b, "--so-falha", "http_404", "--listar")
    assert "Seriam baixadas: 0 páginas" in capsys.readouterr().out
