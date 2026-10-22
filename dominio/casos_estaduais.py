"""Achados das secretarias no modelo de planilha "Casos Estaduais" (D112): uma linha por achado que a verificacao humana
nao descartou, nas 12 colunas do modelo, e um resumo por UF. Sem I/O: recebe as linhas lidas do banco e os rotulos."""
import re

from dominio.catalogo import STATUS_LEITURA_PADRAO
from dominio.servicos import chave_sem_acento

COLUNAS = ("ID", "Categoria", "Autor/Instituicao", "Ano", "Titulo", "Tipo de fonte", "Pais/escopo",
           "Topicos e palavras-chave", "URL", "Prioridade de leitura", "Status de leitura", "Notas")
LARGURAS = (12, 38, 42, 12, 70, 26, 23, 70, 41, 23, 19, 12)
COLUNAS_RESUMO = ("Estado/Caso", "Dados e evidencias de discriminacao")
LARGURAS_RESUMO = (23, 70)
ABA_CASOS, ABA_RESUMO = "Casos Estaduais", "Resumo Casos"
TIPO_OFICIAL = "Notícia oficial / literatura cinzenta"
TIPO_OUTRO = "Reportagem / literatura cinzenta"
LEITURA_VERIFICADO = "Lido"           # um dos status de leitura do catalogo; o nao verificado fica no padrao


def _descartado(l):
    return bool(l["verificado"]) and l["status_final"] == "descartado"


def ano_da_data(texto):
    """O primeiro ano (1900 a 2099) escrito na data do resultado; None quando nao ha."""
    m = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", texto) if isinstance(texto, str) else None
    return int(m.group(0)) if m else None


def linha_do_caso(l, ufs, tecnologias, status):
    """Uma linha do modelo a partir de um achado lido do banco. A situacao e a da verificacao humana quando houver;
    senao, a que o classificador informou."""
    situacao = l["status_final"] if l["verificado"] else l["status_reportado"]
    topicos = [f"fornecedor: {l['fornecedor']}" if l["fornecedor"] else "",
               f"solução: {l['nome_solucao']}" if l["nome_solucao"] else "",
               f"situação: {status.get(situacao, situacao)}" if situacao else ""]
    escopo = f"Brasil/{ufs.get(l['uf'], l['uf'])}" + (f"/{l['cidade']}" if l["cidade"] else "")
    return {
        "ID": l["achado_id"], "Categoria": tecnologias.get(l["tecnologia"], l["tecnologia"] or ""),
        "Autor/Instituicao": l["dominio"] or "", "Ano": ano_da_data(l["data_pub"]), "Titulo": l["titulo"] or "",
        "Tipo de fonte": TIPO_OFICIAL if l["fonte_oficial"] else TIPO_OUTRO, "Pais/escopo": escopo,
        "Topicos e palavras-chave": "; ".join(p for p in topicos if p), "URL": l["url"] or "",
        "Prioridade de leitura": "", "Status de leitura": LEITURA_VERIFICADO if l["verificado"] else STATUS_LEITURA_PADRAO,
        "Notas": (l["observacao"] or "") if l["verificado"] else "",     # verificacao desfeita: a observacao antiga nao vale
    }


def casos(linhas, ufs, tecnologias, status):
    """As linhas da aba de casos: os achados que a verificacao nao descartou, por UF (na ordem de `ufs`), pelo rotulo da
    tecnologia e pelo numero do achado."""
    ordem = {uf: i for i, uf in enumerate(ufs)}
    validas = [l for l in linhas if not _descartado(l)]
    validas.sort(key=lambda l: (ordem.get(l["uf"], len(ordem)), chave_sem_acento(tecnologias.get(l["tecnologia"], l["tecnologia"])),
                                l["achado_id"]))
    return [linha_do_caso(l, ufs, tecnologias, status) for l in validas]


def resumo(linhas, ufs, tecnologias):
    """Uma linha por UF com achado nao descartado: as tecnologias com quantos achados cada (da maior para a menor,
    empate pelo rotulo, sem diferenca de acento) e quantos ja foram verificados. Conta achados, nao paginas."""
    por_uf = {}
    for l in linhas:
        if _descartado(l):
            continue
        d = por_uf.setdefault(l["uf"], {"tec": {}, "n": 0, "v": 0})
        rotulo = tecnologias.get(l["tecnologia"], l["tecnologia"] or "")
        d["tec"][rotulo] = d["tec"].get(rotulo, 0) + 1
        d["n"] += 1
        d["v"] += 1 if l["verificado"] else 0
    saida = []
    for uf in [u for u in ufs if u in por_uf] + sorted(u for u in por_uf if u not in ufs):
        d = por_uf[uf]
        tecs = ", ".join(f"{t} ({n})" for t, n in sorted(d["tec"].items(), key=lambda x: (-x[1], chave_sem_acento(x[0]))))
        saida.append({"Estado/Caso": f"{ufs.get(uf, uf)} ({uf})",
                      "Dados e evidencias de discriminacao": f"{tecs}; {d['v']} verificado(s) de {d['n']}"})
    return saida
