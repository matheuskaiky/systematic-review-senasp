// Botões "Copiar": copiam o texto de data-texto (ou, sem ele, o do elemento cujo id está em data-copiar) e avisam no
// elemento cujo id está em data-aviso. Sem JavaScript a página funciona igual: o botão nasce escondido e o texto
// continua selecionável com o mouse.
(function () {
  Array.prototype.forEach.call(document.querySelectorAll("button[data-copiar]"), function (botao) {
    var alvo = document.getElementById(botao.getAttribute("data-copiar"));
    var aviso = document.getElementById(botao.getAttribute("data-aviso"));
    if (!alvo) { return; }
    botao.hidden = false;

    function avisar(texto) { if (aviso) { aviso.textContent = texto; } }

    function selecionar() {
      var faixa = document.createRange();
      faixa.selectNodeContents(alvo);
      var selecao = window.getSelection();
      selecao.removeAllRanges();
      selecao.addRange(faixa);
    }

    function copiarSelecionando() {
      selecionar();
      var copiou = false;
      try { copiou = document.execCommand("copy"); } catch (e) { copiou = false; }
      avisar(copiou ? "Texto copiado." : "O texto foi selecionado: pressione Ctrl+C para copiar.");
    }

    botao.addEventListener("click", function () {
      var texto = botao.getAttribute("data-texto") || alvo.innerText;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texto).then(
          function () { avisar("Texto copiado."); },
          copiarSelecionando);
      } else {
        copiarSelecionando();
      }
    });
  });
})();
