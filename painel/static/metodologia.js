// Botão "Copiar texto" da página Metodologia. Sem JavaScript a página funciona igual: o botão nasce escondido
// e o texto continua selecionável com o mouse.
(function () {
  var botao = document.getElementById("copiar-texto");
  var aviso = document.getElementById("copiar-aviso");
  var alvo = document.getElementById("texto-metodologia");
  if (!botao || !alvo) { return; }
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
})();
