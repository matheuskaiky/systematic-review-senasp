import hashlib
import uuid
from pathlib import Path


class BrutoLocal:
    def __init__(self, raiz):
        self.raiz = Path(raiz)

    def salvar(self, categoria, run_id, chave, dados, ext):
        pasta = self.raiz / categoria / run_id
        pasta.mkdir(parents=True, exist_ok=True)
        # C11: sufixo unico, para que uma nova tentativa nao sobrescreva o arquivo da anterior
        caminho = pasta / f"{chave[:16]}_{uuid.uuid4().hex[:6]}.{ext}"
        caminho.write_bytes(dados)
        return str(caminho.relative_to(self.raiz)), hashlib.sha256(dados).hexdigest()   # RELATIVE path

    def ler(self, caminho):
        return (self.raiz / caminho).read_bytes()
