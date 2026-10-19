# tools/: manutenção do CSS do painel (v5 "Observatório")

> **Neste repositório** a raiz é `design/`. Ciclo de uma mudança: `.venv/bin/python design/tools/gerar_painel_css.py design`; copiar os sete `design/build/css/*.css` para `painel/static/`; `.venv/bin/python design/tools/lint_css.py painel/static` (0 falha(s), sem `--original`); `.venv/bin/python design/python/verifica_tema.py painel/static/painel.css` (OK); e a suíte do projeto (`tests/test_observatorio.py` confere que o CSS publicado é a saída do gerador). As referências abaixo a `referencia/`, `harness/`, `canvas/`, aos documentos `02_` a `05_` e a `python/test_*.py` são do pacote original e não foram trazidas.

Para **aplicar** o redesenho você só precisa de `build/css/` (os sete CSS prontos) e dos passos de `02_INTEGRACAO_PASSO_A_PASSO.md`. Esta pasta é para **evoluir** o desenho depois: os CSS prontos são *saída* de um gerador que lê as fontes em `src/`, os tokens de cor em `tools/tokens.py` e o mapa de ícones em `build/icones.json`. Quem edita `build/css/` à mão perde a edição na próxima geração e quebra a garantia de que os quatro lugares de troca de tema (claro, escuro do sistema, botão de tema, impressão) dizem a mesma coisa.

**Onde guardar no repositório.** Copie `src/`, `tools/`, `icons/` e `build/icones.json` para uma pasta própria (por exemplo `design/`), mantendo a estrutura. A "raiz" dos comandos abaixo é essa pasta (neste pacote, a raiz do pacote); o gerador escreve em `<raiz>/build/css/`, de onde você copia os sete arquivos para `painel/static/`.

## 1. O ciclo de uma mudança (quatro comandos)

```
python3 tools/gerar_painel_css.py .                                                                   # gera build/css/*.css
python3 tools/lint_css.py build/css --original referencia/css_original                                # 0 falha(s), 1 nota ("sugerido")
python3 python/verifica_tema.py build/css/painel.css --original referencia/css_original/painel.css    # imprime OK
python3 tools/tokens.py                                                                               # contraste: tudo certo
```

Depois copie `build/css/*.css` para `painel/static/` e rode a suíte do projeto (`python3 -m pytest`), incluindo `python/test_tema_deriva.py`, `python/test_fontes_locais.py` e `python/test_icones.py` colados em `tests/`.

`referencia/css_original` é a cópia dos sete CSS originais do handoff; se você não a levar para o repositório, omita `--original` nos dois comandos (o linter só deixa de checar a cobertura `COB`, e o `verifica_tema.py` a comparação com os nomes de token do original).

A única nota esperada do linter é `[COB] … sem regra na v5: sugerido`: a classe `.btn-status.sugerido` do CSS original fica **sem regra de propósito** (cegueira metodológica: nenhum botão destaca o que o modelo sugere).

## 2. O que cada arquivo é

| Arquivo | Função |
|---|---|
| `src/painel/00_…` a `90_*.css` | Fontes de `painel.css`, concatenadas na ordem do nome: cabeçalho, tokens estáticos (tipografia, espaço, raios, larguras), base, layout (banner, barra lateral, topo), componentes, gráficos, cockpit, impressão, acabamento |
| `src/analises.css`, `solucoes.css`, `classificadores.css`, `metodologia.css`, `relevancia.css`, `triagem_escopo.css` | Fontes dos outros seis CSS |
| `tools/tokens.py` | **Fonte única das cores de `painel.css`**: escalas (`PRIM`), nomes semânticos por tema (`SEM_CLARO`, `SEM_ESCURO`), espelhos (`ESPELHOS`), os treze tokens literais (`LITERAIS`), valores fixos da impressão (`FIXOS_IMPRESSAO`) e do banner (`FIXOS`). Rodar o arquivo imprime o relatório de contraste |
| `tools/tokens_analises.py` | Tokens `--an-*` de `analises.css` (cores de **dados** dos gráficos: Okabe-Ito, estágios, kappa, calor) |
| `tools/gerar_painel_css.py` | O gerador. Tabelas internas: `MENU` (ícone e matiz de cada item do menu), `GRUPOS`, `TOM_DOS_ICONES` (matiz de partida de cada ícone) |
| `tools/lint_css.py` | Linter: refaz, sobre os arquivos, as leituras de CSS do contrato dos testes (famílias `NA`, `AC`, `SV`, `IN`, `DS`, `GA`, `RL`), as regras de desenho da v5 (`V5`) e a cobertura contra o CSS original (`COB`, só com `--original`) |
| `tools/construir_fonte_icones.py` | Constrói a fonte de ícones a partir do Phosphor Icons 2.1.1 (MIT) mais a marca do projeto |
| `icons/lista.txt` | Os ícones da fonte (157 nomes do Phosphor, separados por espaço ou quebra de linha; a marca do projeto é desenhada no próprio construtor). **Só se acrescenta ao fim** |
| `build/icones.json` | Mapa nome do ícone → códigos dos glifos (gerado pelo construtor; lido pelo gerador de CSS) |

## 3. O que o gerador faz

1. Lê `src/painel/*.css` em ordem, troca os marcadores e põe no topo o **bloco de tokens** montado de `tokens.py` (o arquivo gerado abre com o comentário `/* ===== Tokens de design`, como o contrato exige).
2. Marcadores aceitos nas fontes: `%ic(nome)%` (glifo de contorno), `%icf(nome)%` (cheio) e `%icd(nome)%` (camada de fundo do duotone), trocados por `"\eXXX"`; um nome fora da fonte interrompe a geração (`ícone fora da fonte`). Blocos gerados: `/*@GERADO:mapa-icones*/`, `menu`, `tons-de-pagina`, `icones-de-pagina` e `an-tokens`.
3. Todo `content:` que carrega um glifo da fonte de ícones ganha uma **segunda** declaração com texto alternativo vazio (`content: X; content: X / ""`): o leitor de tela não anuncia o glifo; a primeira é a reserva de navegadores antigos.
4. Repete a operação para os outros seis CSS.

## 4. Mudar cores (tokens)

Regras que o linter e o `python/verifica_tema.py` conferem, e o motivo (a suíte real não estava no handoff; os testes podem comparar o **texto** do token ou resolver só **um** nível de `var()`, e o CSS passa nas duas leituras):

- **Cor só por token**, e hexadecimal só em blocos `:root` simples (claro, escuro do sistema e impressão). Nos blocos do botão de tema (`@media screen { :root[data-theme=…] }`) só `var(--primitivo)`.
- **No máximo um salto**: todo token semântico é um `#rrggbb` ou exatamente `var(--primitivo)`, nunca `var()` de outro semântico. Nomes que valem o mesmo que outro (`--ok` = `--inclusao`) são **espelhos**: recebem o mesmo primitivo, não `var(--original)` (`ESPELHOS` em `tokens.py`).
- **Treze tokens literais** (`LITERAIS`: `--texto`, `--superficie`, `--acento`, `--perigo`, `--perigo-fundo`, `--ok`, `--ok-fundo`, `--alerta`, `--alerta-fundo`, `--calor-1` a `--calor-4`) saem como `#rrggbb` nos `:root` simples e como `var(--primitivo)` de igual valor nos blocos do botão de tema.
- O valor escuro de cada token obrigatório tem de **diferir** do claro (`--fundo`, `--superficie`, `--texto`, `--acento`, `--ok`, `--alerta`, `--perigo`, …).

Receitas:

- **Mudar o valor de uma cor** (por exemplo, o cobalto): edite a entrada em `PRIM`; gere; rode o ciclo da §1.
- **Mudar qual primitivo um nome usa**: edite `SEM_CLARO` e `SEM_ESCURO` (o valor é o nome de um primitivo). Se o nome também está em `ESPELHOS`, ele acompanha o original.
- **Token novo**: acrescente em `SEM_CLARO` **e** em `SEM_ESCURO`, com o nome de um primitivo; se um teste puder compará-lo como texto entre arquivos ou blocos, inclua-o em `LITERAIS`; use `var(--novo)` nos `src/`; gere; rode o ciclo. Contraste de texto: acrescente o par a `TEXTO_45` (ou `PROPRIOS_45`) em `tokens.py` para que o relatório o confira nos três temas.
- **Cor de dado de gráfico**: `tools/tokens_analises.py`. O mapa de calor segue `--calor-1…4` de `painel.css` (o teste NA compara).
- **Matiz de um item do menu e da página inteira**: edite `MENU` em `tools/gerar_painel_css.py` (`href`, ícone, matiz) e gere; a página herda o matiz do item atual do menu. As cinco famílias de matiz (`cobalto`, `petroleo`, `violeta`, `ambar`, `rosa`) estão em `tools/tokens.py` (`TONS`).

## 5. Regras de desenho que o linter reprova (família V5)

Nenhuma barra de destaque num lado só: `border-left`/`-right`/`-top`/`-bottom` (e as versões lógicas) de 2px ou mais, ou de cor semântica; `box-shadow` de um eixo só, sem desfoque; tira pseudo-elemento fina colada numa aresta. Use contorno inteiro, anel (`0 0 0 1px`), fundo suave, ladrilho de ícone ou ponto. Também reprova deriva entre os quatro lugares de troca de tema e hexadecimal dentro dos blocos do botão de tema.

## 6. Ícones

Para acrescentar um ícone (e **trocar o nome do arquivo** da fonte, porque o servidor a guarda em cache por um ano) siga a seção 5 de `03_ICONES_E_MATIZES_POR_TELA.md`. Em resumo: nome ao fim de `icons/lista.txt`; `python3 tools/construir_fonte_icones.py <assets> icons/lista.txt static/fonts/observatorio-icones-v2.woff2 build/icones.json` (precisa de `pip install fonttools brotli` e da pasta `assets/` de `@phosphor-icons/core@2.1.1`, com `regular/`, `fill/` e `duotone/`); atualizar o nome em `static/painel_fontes_trecho.js` e em `python/test_fontes_locais.py`; gerar o CSS.

## 7. Bancada de capturas e medições (`harness/`)

Opcional; precisa de `pip install playwright pillow` (com o Chromium do Playwright instalado) e, para o PNG da impressão, do `pdftoppm` (poppler).

| Comando (na raiz do pacote) | O que faz |
|---|---|
| `python3 harness/montar.py` | Monta `harness/srv/` (páginas e CSS servidos) a partir de `contexto_original/amostras_html`, dos exemplos renderizados dos templates e das telas escritas à mão em `harness/paginas/` (marcação aproximada) |
| `python3 harness/telas_de_referencia.py` | Regera `referencia/telas/` (51 capturas e o `INDICE.md`). Precisa de `harness/srv/` (rode `montar.py` antes) e **apaga `referencia/telas/` antes de gerar**. Confere em cada captura: sem rolagem horizontal, as três fontes carregadas, `html.icones-ok`, nenhum erro de console ou de rede |
| `python3 harness/gerar_paginas.py` | Reescreve as telas de marcação aproximada em `harness/paginas/` (moldura do achado renderizado e miolo escrito à mão); depois rode `montar.py` |
| `python3 harness/medir.py <página> <largura> '<seletor>'` | Mede caixas de elementos numa página do harness (`harness/srv`) |
| `python3 harness/sobrepoe_leg.py` | Confere se alguma legenda de gráfico (`text.an-leg`) passa do quadradinho seguinte (folga mínima de 4px); a posição das legendas é calculada em Python com largura de texto **estimada**, e esta bancada mede a real |
| `python3 harness/mapa_de_icones_por_tela.py` | Lista, por tela, os `data-ic`/`data-tom` do patch opcional dos templates (base do documento 03) |
| `python3 harness/tirar.py pagina:largura:altura:tema[:cheia]` | Captura avulsa (`tema` = `light` ou `dark`) em `harness/shots/` |

Os documentos `01_…`, `03_…` e `04_…` trazem tabelas montadas a partir de `tokens.py`, de `tokens_analises.py` e do mapa de ícones **na data da entrega**; o gerador de documentos não faz parte do pacote, então, se você mudar tokens ou ícones, atualize essas tabelas à mão.

## 8. Canvas de design (opcional)

`canvas/` guardava os scripts que geraram o canvas de design; não foi trazido para o repositório e o CSS do site não depende dele.
