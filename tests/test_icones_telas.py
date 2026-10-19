"""RB20 (D81): icones (data-ic/data-tom) nos indicadores e titulos de cartao das telas principais. Cada linha: arquivo, trecho de hoje,
trecho com o icone."""
import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "painel" / "templates"
CSS = (TEMPLATES.parent / "static" / "painel.css").read_text(encoding="utf-8")

EDICOES = [
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(r.consultas_web) }}', '<div class="kpi" data-ic="magnifying-glass" data-tom="cobalto"><span class="kpi-valor">{{ fmt.numero(r.consultas_web) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(r.urls_unicas) }}', '<div class="kpi" data-ic="link" data-tom="petroleo"><span class="kpi-valor">{{ fmt.numero(r.urls_unicas) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(r.paginas_com_texto) }}', '<div class="kpi" data-ic="file-text" data-tom="rosa"><span class="kpi-valor">{{ fmt.numero(r.paginas_com_texto) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(r.classificacoes) }}', '<div class="kpi" data-ic="tag" data-tom="violeta"><span class="kpi-valor">{{ fmt.numero(r.classificacoes) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(r.achados) }}', '<div class="kpi" data-ic="binoculars" data-tom="petroleo"><span class="kpi-valor">{{ fmt.numero(r.achados) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.pct(r.evidencia_ok, r.achados) }}', '<div class="kpi" data-ic="seal-check" data-tom="violeta"><span class="kpi-valor">{{ fmt.pct(r.evidencia_ok, r.achados) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.pct(r.verificados, r.achados) }}', '<div class="kpi" data-ic="check-circle" data-tom="cobalto"><span class="kpi-valor">{{ fmt.pct(r.verificados, r.achados) }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ r.ufs_confirmadas }}', '<div class="kpi" data-ic="map-pin" data-tom="petroleo"><span class="kpi-valor">{{ r.ufs_confirmadas }}'),
    ('geral.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.moeda_usd(r.custo_total_usd) }}', '<div class="kpi" data-ic="coins" data-tom="ambar"><span class="kpi-valor">{{ fmt.moeda_usd(r.custo_total_usd) }}'),
    ('geral.html', '<h2>Funil</h2>', '<h2 data-ic="funnel" data-tom="cobalto">Funil</h2>'),
    ('geral.html', '<h2>Progresso da revisão</h2>', '<h2 data-ic="list-checks" data-tom="cobalto">Progresso da revisão</h2>'),
    ('geral.html', '<h2 id="t-prontidao">Prontidão', '<h2 id="t-prontidao" data-ic="gauge" data-tom="violeta">Prontidão'),
    ('geral.html', '<h2>Últimas execuções</h2>', '<h2 data-ic="play-circle" data-tom="ambar">Últimas execuções</h2>'),
    ('estados.html', '<h2>Mapa</h2>', '<h2 data-ic="map-trifold">Mapa</h2>'),
    ('estados.html', '<h2>Tabela</h2>', '<h2 data-ic="table">Tabela</h2>'),
    ('literatura.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(d.n_artigos) }}', '<div class="kpi" data-ic="article" data-tom="rosa"><span class="kpi-valor">{{ fmt.numero(d.n_artigos) }}'),
    ('literatura.html', '<div class="kpi" title="Cada termo do Scholar e cada base manual conta uma vez; é o mesmo critério do filtro “Mais de um termo” da lista de artigos">', '<div class="kpi" title="Cada termo do Scholar e cada base manual conta uma vez; é o mesmo critério do filtro “Mais de um termo” da lista de artigos" data-ic="share-network" data-tom="violeta">'),
    ('literatura.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.pct(tri.incluidos + tri.excluidos, tri.total) }}', '<div class="kpi" data-ic="user-check" data-tom="rosa"><span class="kpi-valor">{{ fmt.pct(tri.incluidos + tri.excluidos, tri.total) }}'),
    ('literatura.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(tri.incluidos) }}', '<div class="kpi" data-ic="check-circle" data-tom="rosa"><span class="kpi-valor">{{ fmt.numero(tri.incluidos) }}'),
    ('literatura.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(tri.pendentes) }}', '<div class="kpi" data-ic="hourglass" data-tom="ambar"><span class="kpi-valor">{{ fmt.numero(tri.pendentes) }}'),
    ('literatura.html', '<h2 id="rel-titulo">Relevância', '<h2 id="rel-titulo" data-ic="star" data-tom="rosa">Relevância'),
    ('literatura.html', '<h2>Artigos por ano</h2>', '<h2 data-ic="calendar-blank" data-tom="rosa">Artigos por ano</h2>'),
    ('literatura.html', '<h2>Artigos mais citados</h2>', '<h2 data-ic="quotes" data-tom="rosa">Artigos mais citados</h2>'),
    ('literatura.html', '<h2>Buscas manuais por base</h2>', '<h2 data-ic="books" data-tom="rosa">Buscas manuais por base</h2>'),
    ('literatura.html', '<h2>Termos em comum</h2>', '<h2 data-ic="share-network" data-tom="rosa">Termos em comum</h2>'),
    ('solucoes.html', '<h2 id="h-resumo">Resumo</h2>', '<h2 id="h-resumo" data-ic="list-bullets">Resumo</h2>'),
    ('solucoes.html', '<h2 id="todas-nomeadas-h">Todas', '<h2 id="todas-nomeadas-h" data-ic="list-magnifying-glass" data-tom="ambar">Todas'),
    ('solucoes.html', '<h3 id="solucao-{{ loop.index }}-resultados">1.', '<h3 id="solucao-{{ loop.index }}-resultados" data-ic="magnifying-glass" data-tom="cobalto">1.'),
    ('solucoes.html', '<h3>2. No texto', '<h3 data-ic="cloud-arrow-down" data-tom="petroleo">2. No texto'),
    ('solucoes.html', '<h3>3. Nos achados', '<h3 data-ic="binoculars" data-tom="petroleo">3. Nos achados'),
    ('triagem_escopo.html', '<h2 id="h-vazio">Ainda', '<h2 id="h-vazio" data-ic="robot" data-tom="violeta">Ainda'),
    ('triagem_escopo.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(resumo.n_validos) }}', '<div class="kpi" data-ic="list-checks" data-tom="violeta"><span class="kpi-valor">{{ fmt.numero(resumo.n_validos) }}'),
    ('triagem_escopo.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(resumo.n_invalidos) }}', '<div class="kpi" data-ic="warning-circle" data-tom="ambar"><span class="kpi-valor">{{ fmt.numero(resumo.n_invalidos) }}'),
    ('triagem_escopo.html', '<div class="kpi"><span class="kpi-valor">{{ fmt.numero(resumo.n_rebaixados) }}', '<div class="kpi" data-ic="shield-warning" data-tom="ambar"><span class="kpi-valor">{{ fmt.numero(resumo.n_rebaixados) }}'),
    ('triagem_escopo.html', '<h2 id="h-ficha">Ficha', '<h2 id="h-ficha" data-ic="table" data-tom="violeta">Ficha'),
    ('triagem_escopo.html', '<h2 id="h-neg">Operadores', '<h2 id="h-neg" data-ic="prohibit">Operadores'),
    ('triagem_escopo.html', '<h2 id="h-lista">Itens', '<h2 id="h-lista" data-ic="list-checks" data-tom="violeta">Itens'),
    ('triagem_escopo.html', '<h2 id="h-execs">Execuções', '<h2 id="h-execs" data-ic="play-circle" data-tom="ambar">Execuções'),
    ('triagem_escopo.html', '<h2 id="h-ler">Como ler esta página</h2>', '<h2 id="h-ler" data-ic="lifebuoy" data-tom="violeta">Como ler esta página</h2>'),
    ('triagem_escopo.html', '<h3>Veredito do modelo</h3>', '<h3 data-ic="robot" data-tom="violeta">Veredito do modelo</h3>'),
    ('triagem_escopo.html', '<h3>Motivo (categoria)</h3>', '<h3 data-ic="tag" data-tom="violeta">Motivo (categoria)</h3>'),
    ('triagem_escopo.html', '<h3>Outros campos</h3>', '<h3 data-ic="list-bullets">Outros campos</h3>'),
    ('prisma.html', '<h2>Motivos de exclusão</h2>', '<h2 data-ic="list-bullets" data-tom="rosa">Motivos de exclusão</h2>'),
    ('execucao.html', '<section class="cartao"><h2>Funil</h2>', '<section class="cartao"><h2 data-ic="funnel">Funil</h2>'),
    ('execucao.html', '<h2>Custo e latência por etapa</h2>', '<h2 data-ic="timer" data-tom="ambar">Custo e latência por etapa</h2>'),
    ('execucao.html', '<h2>Falhas</h2>', '<h2 data-ic="warning-circle" data-tom="ambar">Falhas</h2>'),
    ('execucao.html', '<h3>Páginas que não viraram texto</h3>', '<h3 data-ic="file-dashed">Páginas que não viraram texto</h3>'),
    ('execucao.html', '<h2>O que foi escolhido para baixar</h2>', '<h2 data-ic="cloud-arrow-down">O que foi escolhido para baixar</h2>'),
    ('execucao.html', '<h2>Créditos antes e depois</h2>', '<h2 data-ic="coins" data-tom="ambar">Créditos antes e depois</h2>'),
    ('execucao.html', '<h2>Resumo da execução</h2>', '<h2 data-ic="gear-six">Resumo da execução</h2>'),
    ('comparar.html', '<h2>Funil lado a lado</h2>', '<h2 data-ic="funnel">Funil lado a lado</h2>'),
    ('comparar.html', '<h2>O que mudou na configuração</h2>', '<h2 data-ic="git-diff">O que mudou na configuração</h2>'),
]


@pytest.mark.parametrize("arquivo,antes,depois", EDICOES)
def test_icone_no_lugar(arquivo, antes, depois):
    texto = (TEMPLATES / arquivo).read_text(encoding="utf-8")
    assert texto.count(depois) == 1 and antes not in texto


def test_todo_icone_tem_regra_no_css():
    usados = {n for _, _, d in EDICOES for n in re.findall(r'data-ic="([\w-]+)"', d)}
    assert usados and all(f'[data-ic="{n}"]' in CSS for n in usados), sorted(n for n in usados if f'[data-ic="{n}"]' not in CSS)


def test_telas_fora_do_recorte_sem_icone():
    for nome in ("classificadores.html", "metodologia.html"):
        assert "data-ic=" not in (TEMPLATES / nome).read_text(encoding="utf-8"), nome
