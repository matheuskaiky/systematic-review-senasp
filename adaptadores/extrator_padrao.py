import io
from dominio.modelos import TextoExtraido


class ExtratorPadrao:
    def __init__(self, min_chars=200):
        self._min = min_chars

    def extrair(self, conteudo, content_type, url):
        # C10: PDF servido como application/octet-stream (ou sem tipo) e reconhecido pelo cabecalho do arquivo
        if conteudo[:5] == b"%PDF-" or "pdf" in content_type or url.lower().split("?")[0].endswith(".pdf"):
            return self._pdf(conteudo)
        if "html" in content_type or content_type == "":
            return self._html(conteudo)
        return TextoExtraido("", "nenhum", False, f"tipo_nao_suportado:{content_type}")

    def _finalizar(self, texto, extrator):
        texto = (texto or "").strip()
        if len(texto) < self._min:
            return TextoExtraido(texto, extrator, False, "texto_insuficiente")  # JS, scanned PDF, empty page
        return TextoExtraido(texto, extrator, True)

    def _html(self, conteudo):
        import trafilatura            # late import: the lib is only required if used
        try:
            return self._finalizar(trafilatura.extract(
                conteudo, include_comments=False, include_tables=True, favor_recall=True), "trafilatura")
        except Exception as e:
            return TextoExtraido("", "trafilatura", False, f"erro:{e!r}")

    def _pdf(self, conteudo):
        from pypdf import PdfReader
        try:
            leitor = PdfReader(io.BytesIO(conteudo))
            return self._finalizar("\n".join((p.extract_text() or "") for p in leitor.pages), "pypdf")
        except Exception as e:
            return TextoExtraido("", "pypdf", False, f"erro:{e!r}")
