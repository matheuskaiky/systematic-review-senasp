// Atalhos de teclado da tela de revisão. Tudo aqui é só atalho para botões e links: sem JavaScript a tela funciona igual.
(function () {
  function irParaEvidencia() {
    // rola só dentro da caixa de texto, para não esconder o topo da página
    var caixa = document.querySelector(".texto-pagina"), marca = document.getElementById("evidencia");
    if (caixa && marca) { caixa.scrollTop = Math.max(marca.offsetTop - caixa.clientHeight / 3, 0); }
  }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var alvo = e.target;
    if (alvo && /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName)) return;
    if (e.key === "e") { irParaEvidencia(); e.preventDefault(); return; }
    var el = document.querySelector('[data-tecla="' + e.key + '"]');
    if (!el) return;
    e.preventDefault();
    if (el.tagName === "BUTTON" && el.form) {
      var nome = document.getElementById("revisor");
      if (nome && !nome.value.trim()) { nome.focus(); return; }
      if (el.form.requestSubmit) { el.form.requestSubmit(el); } else { el.click(); }
    } else {
      el.click();
    }
  });
  window.addEventListener("load", irParaEvidencia);
})();

// Menu lateral: os grupos são <details> nativos e funcionam sem JavaScript (o grupo da página atual já vem aberto do servidor).
// Aqui só se lembra, por visitante, se o leitor abriu ou fechou cada um dos outros grupos. O armazenamento pode falhar (janela anônima, bloqueio): tudo em try/catch.
(function () {
  var PREFIXO = "painel.menu.";
  function ler(id) { try { return window.localStorage.getItem(PREFIXO + id); } catch (e) { return null; } }
  function gravar(id, aberto) { try { window.localStorage.setItem(PREFIXO + id, aberto ? "1" : "0"); } catch (e) { /* sem armazenamento: o menu segue funcionando */ } }
  var grupos = document.querySelectorAll("details.menu-grupo[data-grupo]");
  Array.prototype.forEach.call(grupos, function (grupo) {
    var id = grupo.getAttribute("data-grupo");
    var contemAtual = !!grupo.querySelector('a[aria-current="page"]');
    if (!contemAtual) {
      var salvo = ler(id);
      if (salvo === "1") { grupo.open = true; } else if (salvo === "0") { grupo.open = false; }
    }
    grupo.addEventListener("toggle", function () { if (!contemAtual) { gravar(id, grupo.open); } });
  });
})();

// Ordenação de colunas no navegador (melhoria progressiva). Só tabelas marcadas com `data-ordenavel`; sem JavaScript o cabeçalho segue sendo texto simples e a ordem é a do servidor.
// Cada título de coluna vira um <button> dentro do <th> (operável por teclado) e o <th> ganha `aria-sort`. Clicar alterna: crescente, decrescente, ordem original.
// A chave de ordenação é o `data-valor` da célula (número com ponto decimal ou texto, como uma data ISO) ou, sem ele, o texto visível: números no formato pt-BR
// ("1.234", "12,5%", "US$ 0,0050") valem como número, "—" e célula vazia vão sempre para o fim, o resto compara como texto (pt-BR, "2" antes de "10").
// A ordenação é estável e mexe só nas linhas que estão na tela (não reordena entre páginas da paginação do servidor); os links das linhas seguem intactos, porque as linhas só mudam de lugar.
(function () {
  var colador = (typeof Intl !== "undefined" && Intl.Collator) ? new Intl.Collator("pt-BR", { numeric: true }) : null;
  function compararTexto(a, b) { return colador ? colador.compare(a, b) : a.localeCompare(b, "pt-BR", { numeric: true }); }

  function anunciar(texto) {
    var regiao = document.getElementById("anuncio-ordem");
    if (!regiao) {
      regiao = document.createElement("div");
      regiao.id = "anuncio-ordem"; regiao.className = "so-leitor";
      regiao.setAttribute("role", "status"); regiao.setAttribute("aria-live", "polite"); regiao.setAttribute("aria-atomic", "true");
      document.body.appendChild(regiao);
    }
    regiao.textContent = "";
    window.setTimeout(function () { regiao.textContent = texto; }, 50);   // esvaziar e repor faz o leitor de tela repetir a mesma frase
  }

  function paraNumero(texto) {
    var t = texto.replace(/[\s ]/g, "").replace(/^(US\$|R\$)/, "");
    var m = /^([+-]?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?%?$/.exec(t);
    return m ? parseFloat(m[1] + m[2].replace(/\./g, "") + (m[3] ? "." + m[3] : "")) : null;
  }

  function chave(celula) {
    if (!celula) { return { vazio: true }; }
    var tem = celula.hasAttribute("data-valor");
    var bruto = (tem ? celula.getAttribute("data-valor") : celula.textContent).replace(/[\s ]+/g, " ").trim();
    if (bruto === "" || bruto === "—" || bruto === "-") { return { vazio: true }; }
    var n = tem ? (isFinite(Number(bruto)) ? Number(bruto) : null) : paraNumero(bruto);
    return n === null ? { txt: bruto } : { num: n };
  }

  function comparar(a, b) {
    if (a.num !== undefined && b.num !== undefined) { return a.num - b.num; }
    if (a.num !== undefined) { return -1; }
    if (b.num !== undefined) { return 1; }
    return compararTexto(a.txt, b.txt);
  }

  function preparar(tabela) {
    var cabecalho = tabela.tHead && tabela.tHead.rows[tabela.tHead.rows.length - 1];
    if (!cabecalho) { return false; }
    var corpos = Array.prototype.slice.call(tabela.tBodies);
    var originais = corpos.map(function (c) { return Array.prototype.slice.call(c.rows); });   // ordem do servidor, para voltar a ela
    var colunas = [];
    Array.prototype.forEach.call(cabecalho.cells, function (th) {
      var rotulo = th.textContent.replace(/\s+/g, " ").trim();
      if (!rotulo || th.hasAttribute("data-sem-ordem")) { return; }
      var botao = document.createElement("button"), seta = document.createElement("span");
      botao.type = "button"; botao.className = "ordenar";
      seta.className = "ordenar-seta"; seta.setAttribute("aria-hidden", "true");
      th.textContent = "";
      botao.appendChild(document.createTextNode(rotulo)); botao.appendChild(seta); th.appendChild(botao);
      th.setAttribute("aria-sort", "none");
      colunas.push({ th: th, rotulo: rotulo });
      botao.addEventListener("click", function () { ordenar(th, rotulo); });
    });
    if (!colunas.length) { return false; }

    function ordenar(alvo, rotulo) {
      var atual = alvo.getAttribute("aria-sort");
      var novo = atual === "none" ? "ascending" : atual === "ascending" ? "descending" : "none";
      colunas.forEach(function (c) { c.th.setAttribute("aria-sort", c.th === alvo ? novo : "none"); });
      var indice = alvo.cellIndex, dir = novo === "descending" ? -1 : 1;
      corpos.forEach(function (corpo, k) {
        var linhas = originais[k].map(function (tr, i) { return { tr: tr, i: i, k: chave(tr.cells[indice]) }; });
        linhas.sort(function (x, y) {
          if (novo === "none") { return x.i - y.i; }
          if (x.k.vazio || y.k.vazio) { return x.k.vazio && y.k.vazio ? x.i - y.i : (x.k.vazio ? 1 : -1); }   // vazio fica no fim nos dois sentidos
          return comparar(x.k, y.k) * dir || x.i - y.i;
        });
        linhas.forEach(function (l) { corpo.appendChild(l.tr); });
      });
      anunciar(novo === "none" ? "Tabela na ordem original."
        : "Tabela ordenada por " + rotulo + ", em ordem " + (novo === "ascending" ? "crescente" : "decrescente") + ".");
    }
    return true;
  }

  var algumaPronta = false;
  Array.prototype.forEach.call(document.querySelectorAll("table[data-ordenavel]"), function (t) { if (preparar(t)) { algumaPronta = true; } });
  if (algumaPronta) {   // as dicas só existem para quem tem JavaScript: sem ele a ordenação não funciona, e dizer o contrário seria enganar
    Array.prototype.forEach.call(document.querySelectorAll("[data-dica-ordenar]"), function (d) { d.hidden = false; });
  }
})();

// Atalho "/" para o campo de busca das listas (marcado com `data-atalho-busca`). Ignorado quando a pessoa já digita em um campo ou usa Ctrl/Alt/Cmd.
// "Esc" dentro do campo devolve o foco à página. O atalho não conflita com os da revisão (1 a 6, d, n, u, e, i, x, p), que só existem nas telas de um item.
(function () {
  var campo = document.querySelector("input[data-atalho-busca]");
  if (!campo) { return; }
  var rotulo = campo.closest("label");
  if (rotulo) {   // a dica visual só aparece com JavaScript; o nome acessível do campo não muda (aria-hidden)
    var texto = document.createElement("span"), dica = document.createElement("kbd");   // o texto do rótulo e a dica ficam juntos, na mesma linha do rótulo
    while (rotulo.firstChild && rotulo.firstChild !== campo) { texto.appendChild(rotulo.firstChild); }
    dica.className = "atalho-dica"; dica.setAttribute("aria-hidden", "true"); dica.textContent = "/"; dica.title = "Atalho: tecla /";
    texto.appendChild(document.createTextNode(" ")); texto.appendChild(dica);
    rotulo.insertBefore(texto, campo);
  }
  document.addEventListener("keydown", function (e) {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) { return; }
    var alvo = e.target;
    if (alvo && (/^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName) || alvo.isContentEditable)) { return; }
    e.preventDefault();
    campo.focus(); campo.select();
  });
  campo.addEventListener("keydown", function (e) { if (e.key === "Escape") { e.preventDefault(); campo.blur(); } });   // preventDefault: num campo de busca o Esc nativo apagaria o texto digitado
})();

/* ===== TRECHO PARA COLAR NO FIM DE painel/static/painel.js (não é um arquivo novo: painel.js continua sendo o único script global) =====
   Tema claro/escuro. O que faz:
     • clique em [data-tema-alternar] troca data-theme ("light" | "dark") em <html>;
     • guarda a escolha em localStorage ("painel.tema", dentro de try/catch) e no cookie `tema`, que o servidor lê para já entregar
       <html data-theme="…"> na próxima página (sem piscar o tema errado e sem script inline, compatível com a política de segurança);
     • mantém aria-pressed dos botões em dia ("true" = escuro) e acompanha o sistema operacional enquanto a pessoa não escolheu nada.
   Sem JavaScript o painel continua legível: segue o tema do sistema (@media prefers-color-scheme) ou o último cookie lido no servidor.
   Respeita as restrições de painel.js: sem avaliação dinâmica de código, sem montar HTML por texto, sem requisições, sem endereço absoluto. */
(function () {
  "use strict";

  var CHAVE = "painel.tema";
  var raiz = document.documentElement;

  function valido(v) { return v === "light" || v === "dark" ? v : null; }

  function salvoNoNavegador() {
    try { return valido(window.localStorage.getItem(CHAVE)); } catch (e) { return null; }
  }

  function sistemaEscuro() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  /* Tema em vigor: o atributo (escolha explícita) vence; sem ele, vale o sistema. */
  function atual() {
    return valido(raiz.getAttribute("data-theme")) || (sistemaEscuro() ? "dark" : "light");
  }

  function sincronizarBotoes() {
    var escuro = atual() === "dark" ? "true" : "false";
    var botoes = document.querySelectorAll("[data-tema-alternar]");
    for (var i = 0; i < botoes.length; i++) { botoes[i].setAttribute("aria-pressed", escuro); }
  }

  function gravar(tema) {
    try { window.localStorage.setItem(CHAVE, tema); } catch (e) { /* navegação privativa ou bloqueada: o cookie cobre */ }
    var seguro = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = "tema=" + tema + "; Path=/; Max-Age=31536000; SameSite=Strict" + seguro;
  }

  function alternar() {
    var novo = atual() === "dark" ? "light" : "dark";
    raiz.setAttribute("data-theme", novo);
    gravar(novo);
    sincronizarBotoes();
  }

  /* Primeira carga: se o servidor não escreveu data-theme (sem cookie), mas o navegador lembra da escolha, aplica-a agora. */
  if (!valido(raiz.getAttribute("data-theme"))) {
    var salvo = salvoNoNavegador();
    if (salvo) { raiz.setAttribute("data-theme", salvo); }
  }
  sincronizarBotoes();

  document.addEventListener("click", function (ev) {
    var alvo = ev.target && ev.target.closest ? ev.target.closest("[data-tema-alternar]") : null;
    if (alvo) { ev.preventDefault(); alternar(); }
  });

  /* Sem escolha explícita, o botão acompanha o sistema quando ele muda (por exemplo, modo noturno automático). */
  if (window.matchMedia) {
    var consulta = window.matchMedia("(prefers-color-scheme: dark)");
    var ao_mudar = function () { if (!valido(raiz.getAttribute("data-theme"))) { sincronizarBotoes(); } };
    if (consulta.addEventListener) { consulta.addEventListener("change", ao_mudar); }
    else if (consulta.addListener) { consulta.addListener(ao_mudar); }
  }
})();

/* ===== TRECHO PARA COLAR NO FIM DE painel/static/painel.js — fontes locais e ícones, SEM @font-face e SEM função de endereço no CSS =====
   Por quê: os testes proíbem a função de endereço em painel.css (o relatório estático embute esse arquivo) e só admitem um link de folha nas páginas.
   Então o CSS só NOMEIA as famílias ("Inter" em --fonte-base, "Source Serif 4" em --fonte-leitura e "Observatorio Icones" em --fonte-icones, com pilha de
   sistema como reserva das duas primeiras) e este trecho carrega os arquivos pela API de fontes do navegador (FontFace), do PRÓPRIO servidor (/static/fonts/).
   Nenhuma requisição escrita à mão, nenhum endereço absoluto, nenhum preload. Sem JavaScript (ou se o arquivo falhar), a tela usa a fonte de sistema,
   fica sem os ícones e continua inteira e legível.
   Ícones: só quando o arquivo da fonte de ícones chega o script acrescenta a classe icones-ok em html; todo o CSS de ícones está atrás dessa classe.
   Ao trocar um arquivo de fonte, troque também o NOME dele (o servidor pode guardar em cache por um ano). */
(function () {
  "use strict";

  if (!window.FontFace || !document.fonts) { return; }

  var FAMILIAS = [
    { nome: "Inter", arquivo: "/static/fonts/inter-latin-wght-normal.woff2", peso: "100 900", icones: false },
    { nome: "Source Serif 4", arquivo: "/static/fonts/source-serif-4-latin-wght-normal.woff2", peso: "200 900", icones: false },
    { nome: "Observatorio Icones", arquivo: "/static/fonts/observatorio-icones-v1.woff2", peso: "400", icones: true }
  ];

  FAMILIAS.forEach(function (f) {
    try {
      var face = new window.FontFace(f.nome, "url(" + f.arquivo + ") format(\"woff2\")", { weight: f.peso, style: "normal", display: "swap" });
      face.load().then(function (carregada) {
        document.fonts.add(carregada);
        if (f.icones) { document.documentElement.classList.add("icones-ok"); }
      }, function () { /* sem a fonte: segue a de sistema (e sem ícones) */ });
    } catch (e) { /* navegador sem suporte: segue a de sistema */ }
  });
})();

/* ===== TRECHO PARA COLAR NO FIM DE painel/static/painel.js (não é um arquivo novo: painel.js continua sendo o único script global) =====
   Telas de triagem (artigo e achado). Melhoria progressiva: sem JavaScript, tudo continua sendo formulário POST comum e links comuns.
   O que faz:
     • mostra os chips de motivo de exclusão ([data-motivos], que nascem com `hidden`) e, ao clicar, acrescenta o motivo ao campo #motivo;
     • lembra se a gaveta de critérios (details.escopo-guia) está aberta ou recolhida (localStorage, em try/catch);
     • centraliza o item aberto na fila lateral (.fila-lista).
   Os atalhos de teclado (i, x, p, n, 1–6, d, u, e) NÃO estão aqui: já existem em painel.js e continuam como estão.
   Restrições de painel.js respeitadas: sem avaliação dinâmica de código, sem montar HTML por texto, sem requisições, sem endereço absoluto. */
(function () {
  "use strict";

  var tela = document.querySelector(".triagem");
  if (!tela) { return; }

  /* ---- Motivos em um toque (só na triagem de artigos) ---- */
  var blocos = tela.querySelectorAll("[data-motivos]");
  var campo = document.getElementById("motivo");
  if (blocos.length && campo) {
    for (var i = 0; i < blocos.length; i++) { blocos[i].hidden = false; }
    tela.addEventListener("click", function (ev) {
      var chip = ev.target && ev.target.closest ? ev.target.closest(".chip-motivo") : null;
      var motivo = chip ? chip.getAttribute("data-motivo") : null;
      if (!motivo) { return; }
      var atual = campo.value.trim();
      if (atual.indexOf(motivo) === -1) {
        campo.value = atual ? atual.replace(/[;.\s]+$/, "") + "; " + motivo : motivo;
      }
      campo.dispatchEvent(new Event("input", { bubbles: true }));
      campo.focus();
    });
  }

  /* ---- Gaveta de critérios de escopo ---- */
  var gaveta = tela.querySelector("details.escopo-guia");
  if (gaveta) {
    var CHAVE = "painel.escopo-aberto";
    try {
      var salvo = window.localStorage.getItem(CHAVE);
      if (salvo === "0") { gaveta.open = false; } else if (salvo === "1") { gaveta.open = true; }
    } catch (e) { /* armazenamento bloqueado: a gaveta funciona igual, só não lembra */ }
    gaveta.addEventListener("toggle", function () {
      try { window.localStorage.setItem(CHAVE, gaveta.open ? "1" : "0"); } catch (e) { /* idem */ }
    });
  }

  /* ---- Fila lateral: centraliza o item aberto (lista vertical no cockpit largo, faixa horizontal abaixo disso) ---- */
  var lista = tela.querySelector(".fila-lista");
  var ativo = lista ? lista.querySelector('[aria-current="true"]') : null;
  if (ativo) {
    var item = ativo.parentNode;
    if (lista.scrollHeight > lista.clientHeight + 1) {
      lista.scrollTop = Math.max(0, item.offsetTop - Math.round((lista.clientHeight - item.offsetHeight) / 2));
    } else {
      lista.scrollLeft = Math.max(0, item.offsetLeft - Math.round((lista.clientWidth - item.offsetWidth) / 2));
    }
  }
})();
