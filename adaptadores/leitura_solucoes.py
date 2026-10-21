"""Leituras da busca no texto das paginas (RC16) e da conferencia das solucoes conhecidas (RC17). Mistura em LeituraPainelSQLite: usa
self._consulta(sql, args). So le; nunca grava. Toda leitura e defensiva: em um banco antigo, sem alguma tabela, devolve lista vazia.

O texto das paginas NAO e lido aqui: a rota recebe o armazenamento bruto (`bruto`) e le cada `texto_path`. Aqui so se decide QUAIS paginas
buscar e se cruzam nomes com titulos, resumos e evidencias.

O casamento de nomes e o de `dominio.solucoes` (sem acento, sem maiuscula, palavra inteira)."""
import sqlite3

from dominio.solucoes import casar, normalizar

LOTE_SQL = 500            # variaveis por consulta (o limite do SQLite e maior, mas isto basta e e portavel)


def _defensivo(vazio):
    """Banco antigo (sem tabela ou coluna): a leitura devolve `vazio()` (list ou dict) em vez de falhar."""
    def decorador(f):
        def interno(self, *a, **k):
            try:
                return f(self, *a, **k)
            except sqlite3.OperationalError:
                return vazio()
        interno.__name__, interno.__doc__ = f.__name__, f.__doc__
        return interno
    return decorador


class LeituraSolucoes:
    def _tem_coluna(self, tabela, coluna):
        return any(l["name"] == coluna for l in self._consulta(f"PRAGMA table_info({tabela})"))

    @_defensivo(list)
    def paginas_para_busca_texto(self, ufs=None):
        """Paginas com texto extraido, uma linha por (url_id, uf) conhecido (de `selecao_download` ou `resultados_web`). Se a URL foi baixada
        mais de uma vez, vale a pagina mais recente. `ufs` (lista de siglas) restringe; None traz todas. Colunas: pagina_id, url_id, uf,
        url, url_final, dominio_final, texto_path, run_id, no_relatorio."""
        filtro, args = "", []
        if ufs:
            ufs = list(ufs)
            filtro = f" AND x.uf IN ({','.join('?' * len(ufs))})"
            args = ufs
        return self._consulta(f"""
            SELECT p.pagina_id, p.url_id, x.uf, u.url_original AS url, p.url_final, p.dominio_final, p.texto_path, p.run_id,
                   COALESCE(e.no_relatorio, 1) AS no_relatorio
            FROM paginas p
            JOIN urls u ON u.url_id = p.url_id
            JOIN (SELECT url_id, uf FROM selecao_download UNION SELECT url_id, uf FROM resultados_web) x ON x.url_id = p.url_id
            LEFT JOIN execucoes e ON e.run_id = p.run_id
            WHERE p.extracao_ok = 1 AND p.texto_path IS NOT NULL AND p.texto_path <> ''
              AND p.pagina_id = (SELECT q.pagina_id FROM paginas q JOIN chamadas c ON c.chamada_id = q.chamada_id
                                 WHERE q.url_id = p.url_id AND q.extracao_ok = 1 AND q.texto_path IS NOT NULL AND q.texto_path <> ''
                                 ORDER BY c.requisitado_em DESC, q.pagina_id DESC LIMIT 1){filtro}
            ORDER BY x.uf, p.url_id""", args)

    @_defensivo(dict)
    def achados_das_urls(self, pares):
        """{(url_id, uf): [achado]} para varios pares de uma vez, do mais antigo ao mais novo (`requisitado_em` da chamada da
        classificacao, empate pelo `achado_id`). Cada achado: achado_id, tecnologia, status_reportado, confianca, run_id e,
        se o banco tem a coluna, nome_solucao."""
        pares = {(int(u), str(f)) for u, f in pares}
        por_url = {}
        for p in pares:
            por_url.setdefault(p[0], set()).add(p[1])
        extra = ", a.nome_solucao" if self._tem_coluna("achados", "nome_solucao") else ""
        saida = {p: [] for p in pares}
        ids = sorted(por_url)
        for i in range(0, len(ids), LOTE_SQL):
            lote = ids[i:i + LOTE_SQL]
            for l in self._consulta(f"""
                SELECT k.url_id, a.uf, a.achado_id, a.tecnologia, a.status_reportado, a.confianca, k.run_id{extra}
                FROM achados a JOIN classificacoes k ON k.classificacao_id = a.classificacao_id
                WHERE k.url_id IN ({','.join('?' * len(lote))})
                ORDER BY (SELECT c.requisitado_em FROM chamadas c WHERE c.chamada_id = k.chamada_id), a.achado_id""", lote):
                if l["uf"] in por_url[l["url_id"]]:
                    saida[(l["url_id"], l["uf"])].append({c: v for c, v in l.items() if c not in ("url_id", "uf")})
        return saida

    def achados_da_url(self, url_id, uf):
        """`[{achado_id, tecnologia, status_reportado, confianca, run_id[, nome_solucao]}]` da URL naquela UF."""
        return self.achados_das_urls([(url_id, uf)]).get((int(url_id), str(uf)), [])

    @_defensivo(list)
    def resultados_busca_que_citam(self, termos_normalizados, uf):
        """Resultados de busca web da UF cujo titulo ou resumo cita algum dos termos. Colunas: resultado_id, run_id, consulta_id, posicao,
        titulo, snippet, url_id, url, no_relatorio (a execucao esta no relatorio), n_paginas (tentativas de download), n_paginas_com_texto,
        selecionada (foi selecionada para download em alguma execucao). Primeiro as execucoes do relatorio e as mais novas."""
        achados = []
        for l in self._consulta("""
            SELECT r.resultado_id, r.run_id, r.consulta_id, r.posicao, r.titulo, r.snippet, r.url_id, u.url_original AS url,
                   COALESCE(e.no_relatorio, 1) AS no_relatorio,
                   (SELECT COUNT(*) FROM paginas p WHERE p.url_id = r.url_id) AS n_paginas,
                   (SELECT COUNT(*) FROM paginas p WHERE p.url_id = r.url_id AND p.extracao_ok = 1) AS n_paginas_com_texto,
                   EXISTS (SELECT 1 FROM selecao_download s WHERE s.url_id = r.url_id AND s.uf = r.uf AND s.selecionada = 1) AS selecionada
            FROM resultados_web r JOIN urls u ON u.url_id = r.url_id LEFT JOIN execucoes e ON e.run_id = r.run_id
            WHERE r.uf = ?""", (uf,)):
            alvos = (normalizar(l["titulo"]), normalizar(l["snippet"]))
            if any(casar(t, termo) for t in alvos for termo in termos_normalizados):
                achados.append(l)
        achados.sort(key=lambda l: (-l["no_relatorio"], _inverter(l["run_id"]), l["posicao"] or 0))
        return achados

    @_defensivo(dict)
    def nomes_solucao_por_uf(self):
        """{(nome_solucao como esta no banco, uf): n} dos achados VIGENTES (`r_achados`) com nome preenchido (RC23). So le: o valor bruto nunca
        e alterado; a resolucao de entidades (dominio/entidades_solucao.py) agrupa em memoria. Banco sem a coluna: dicionario vazio."""
        if not self._tem_coluna("achados", "nome_solucao"):
            return {}
        return {(l["nome_solucao"], l["uf"]): l["n"] for l in self._consulta("""
            SELECT nome_solucao, uf, COUNT(*) AS n FROM r_achados
            WHERE nome_solucao IS NOT NULL AND TRIM(nome_solucao) <> '' GROUP BY nome_solucao, uf""")}

    @_defensivo(list)
    def achados_das_variantes(self, pares):
        """Achados (de qualquer classificacao, como `achados_que_citam`) cujo `nome_solucao` bruto e UF estao em `pares` [(nome, uf)]. Colunas:
        achado_id, url_id, tecnologia, status_reportado, confianca, evidencia, run_id, nome_solucao, citado_em = 'variante'."""
        if not self._tem_coluna("achados", "nome_solucao"):
            return []
        por_uf = {}
        for nome, uf in pares:
            por_uf.setdefault(uf, set()).add(nome)
        saida = []
        for uf, nomes in sorted(por_uf.items()):
            nomes = sorted(nomes)
            for i in range(0, len(nomes), LOTE_SQL):
                lote = nomes[i:i + LOTE_SQL]
                for l in self._consulta(f"""
                    SELECT a.achado_id, k.url_id, a.tecnologia, a.status_reportado, a.confianca, a.evidencia, k.run_id, a.nome_solucao
                    FROM achados a JOIN classificacoes k ON k.classificacao_id = a.classificacao_id
                    WHERE a.uf = ? AND a.nome_solucao IN ({','.join('?' * len(lote))}) ORDER BY a.achado_id""", (uf, *lote)):
                    saida.append({**l, "citado_em": "variante"})
        return sorted(saida, key=lambda l: l["achado_id"])

    @_defensivo(list)
    def achados_que_citam(self, termos_normalizados, uf):
        """Achados da UF cuja evidencia (ou `nome_solucao`, se a coluna existir) cita algum dos termos. Colunas: achado_id, url_id,
        tecnologia, status_reportado, confianca, evidencia, run_id, citado_em ('nome_solucao' ou 'evidencia')."""
        extra = ", a.nome_solucao" if self._tem_coluna("achados", "nome_solucao") else ", NULL AS nome_solucao"
        saida = []
        for l in self._consulta(f"""
            SELECT a.achado_id, k.url_id, a.tecnologia, a.status_reportado, a.confianca, a.evidencia, k.run_id{extra}
            FROM achados a JOIN classificacoes k ON k.classificacao_id = a.classificacao_id
            WHERE a.uf = ? ORDER BY a.achado_id""", (uf,)):
            onde = None
            for campo in ("nome_solucao", "evidencia"):
                n = normalizar(l[campo]) if l[campo] else ""
                if n and any(casar(n, t) for t in termos_normalizados):
                    onde = campo
                    break
            if onde:
                saida.append({**{c: v for c, v in l.items() if c != "nome_solucao"}, "citado_em": onde})
        return saida


def _inverter(texto):
    """Chave de ordenacao decrescente para texto (run_id mais novo primeiro): cada caractere e trocado pelo seu complemento."""
    return tuple(-ord(c) for c in str(texto or ""))
