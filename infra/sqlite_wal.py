"""Modo WAL do SQLite: quem lê não espera quem grava (continua valendo um escritor por vez).

O modo fica gravado no próprio arquivo do banco, então ele é ligado uma única vez: a troca precisa do banco sem outra conexão
segurando uma leitura. Se a troca não pegar (painel aberto em outro processo, sistema de arquivos sem memória compartilhada),
o banco segue no modo antigo, com um aviso no log, e a próxima abertura tenta de novo."""
import logging
import sqlite3


def ligar_wal(conn, caminho):
    """Liga o WAL se o banco ainda não estiver nele e devolve o modo final ("wal" quando deu certo)."""
    modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if modo == "wal":
        return modo
    try:
        modo = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    except sqlite3.OperationalError as e:
        logging.warning("SQLite: não foi possível ligar o modo WAL em %s (%s); o banco segue no modo %s.", caminho, e, modo)
        return modo
    if modo != "wal":
        logging.warning("SQLite: não foi possível ligar o modo WAL em %s; o banco segue no modo %s.", caminho, modo)
    return modo
