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
