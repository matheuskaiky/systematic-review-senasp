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
