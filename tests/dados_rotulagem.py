"""Banco montado a mao para os testes de prontidao e de rotulagem: achados, artigos com veredito do modelo e paginas sem achado.
Uma conexao so, com insercoes em lote (centenas de linhas em milissegundos)."""
import sqlite3

from adaptadores.repositorio_sqlite import RepositorioSQLite

UFS = ("PI", "CE", "BA", "SP", "RS", "AM")
TECS = ("reconhecimento_facial", "leitura_placas", "videomonitoramento_inteligente")
RUN = "R1"


def construir(caminho, n_achados=0, n_artigos=0, n_negativos=0, *, confere0=0, cita0=0, snippet=0, verificados=(), decisoes=(),
              escopo=None):
    """Cria o banco (esquema completo) com uma execucao no relatorio e devolve o caminho.

    - `n_achados`: achados vigentes, cada um em sua pagina (url e classificacao proprias); os `confere0` primeiros tem
      evidencia_confere = 0, os `cita0` seguintes evidencia_cita_tecnologia = 0 e os `snippet` seguintes origem_texto = 'snippet'
      (confianca baixa); os demais estao "limpos". `verificados` = [(posicao 0-based, status_final)] marca esses achados como verificados.
    - `n_artigos`: artigos (titulo com marcadores de Brasil e tema nos pares) em r_artigos; `escopo` = [(posicao, status)] da
      triagem de escopo (valida); `decisoes` = [(posicao, 'incluir' | 'excluir')] da triagem humana.
    - `n_negativos`: classificacoes de JSON valido sobre o texto da pagina, sem achado."""
    caminho = str(caminho)
    RepositorioSQLite(caminho).fechar()
    c = sqlite3.connect(caminho)
    c.execute("INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, no_relatorio) VALUES (?,?,?,?,1)",
              (RUN, "2026-01-01T00:00:00", "h", "{}"))
    chamadas = {}
    for etapa in ("classificacao", "busca_academica", "download"):
        chamadas[etapa] = c.execute(
            """INSERT INTO chamadas (run_id, etapa, provedor, alvo_id, parametros_json, chave_idempotencia, requisitado_em, sucesso)
               VALUES (?,?,?,?,?,?,?,1)""", (RUN, etapa, "p", "x", "{}", f"k-{etapa}", "2026-01-01T00:00:00")).lastrowid

    def pagina(i, uf, origem):
        url = c.execute("INSERT INTO urls (url_normalizada, url_original, dominio, fonte_oficial) VALUES (?,?,?,1)",
                        (f"https://x.gov.br/{i}", f"https://x.gov.br/{i}", "x.gov.br")).lastrowid
        pid = None
        if origem == "pagina":
            pid = c.execute("INSERT INTO paginas (run_id, url_id, chamada_id, extracao_ok, texto_path) VALUES (?,?,?,1,?)",
                            (RUN, url, chamadas["download"], f"texto/{RUN}/{i}.txt")).lastrowid
        return url, pid

    verificados = dict(verificados)
    for i in range(n_achados):
        uf, tec = UFS[i % len(UFS)], TECS[i % len(TECS)]
        so_snippet = confere0 + cita0 <= i < confere0 + cita0 + snippet
        url, pid = pagina(f"a{i}", uf, "snippet" if so_snippet else "pagina")
        k = c.execute("""INSERT INTO classificacoes (chamada_id, run_id, url_id, pagina_id, uf, origem_texto, classificador, relevante,
                             json_valido, n_achados) VALUES (?,?,?,?,?,?,?,1,1,1)""",
                      (chamadas["classificacao"], RUN, url, pid, uf, "snippet" if so_snippet else "pagina", "gemini")).lastrowid
        final = verificados.get(i)
        c.execute("""INSERT INTO achados (classificacao_id, uf, tecnologia, status_reportado, evidencia, evidencia_confere, confianca,
                         evidencia_cita_tecnologia, evidencia_cita_lgpd, verificado, status_final) VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
                  (k, uf, tec, "em_uso", f"trecho {i}", 0 if i < confere0 else 1, "baixa" if so_snippet else "alta",
                   0 if confere0 <= i < confere0 + cita0 else 1, 1 if final else 0, final))
    for j in range(n_negativos):
        uf = UFS[j % len(UFS)]
        url, pid = pagina(f"n{j}", uf, "pagina")
        c.execute("""INSERT INTO classificacoes (chamada_id, run_id, url_id, pagina_id, uf, origem_texto, classificador, relevante,
                         json_valido, n_achados) VALUES (?,?,?,?,?,?,?,0,1,0)""",
                  (chamadas["classificacao"], RUN, url, pid, uf, "pagina", "gemini"))
    escopo, decisoes = dict(escopo or {}), dict(decisoes)
    for i in range(n_artigos):
        brasil_tema = i % 2 == 0
        titulo = (f"Reconhecimento facial na polícia militar de São Paulo, Brasil {i}" if brasil_tema else f"Deep learning for images {i}")
        aid = c.execute("INSERT INTO artigos (chave_dedup, titulo, link, snippet, ano, citacoes) VALUES (?,?,?,?,?,?)",
                        (f"art{i}", titulo, f"https://exemplo.org/{i}", "resumo", 2020 + i % 5, i)).lastrowid
        c.execute("INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?,?,?,?,?)",
                  (chamadas["busca_academica"], aid, "t1", RUN, i + 1))
        if i in escopo:
            c.execute("""INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, status, status_bruto, valido, prompt_versao, criado_em)
                         VALUES (?,?,?,?,?,?,1,'t1','2026-01-01T00:00:00')""", (RUN, "artigo", aid, "", escopo[i], escopo[i]))
        if i in decisoes:
            c.execute("INSERT INTO triagem (artigo_id, decisao, revisor, revisado_em) VALUES (?,?,?,?)",
                      (aid, decisoes[i], "Ana", "2026-01-02T00:00:00"))
    c.commit()
    c.close()
    return caminho
