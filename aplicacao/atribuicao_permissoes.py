"""Atribuição das permissões novas (ver_registros_revisao, ver_custos) aos grupos existentes.

Gera a prévia sem gravar nada e confirma a gravação atômica por meio de código SHA-256 verificado.
"""
import unicodedata

from dominio import autenticacao

NADA = "Nada a gravar: nenhum grupo precisa das permissões novas."


def nome_exibido(nome: str) -> str:
    """Substitui caracteres de controle Unicode (categoria C) por caractere de substituição."""
    return "".join("\ufffd" if unicodedata.category(ch).startswith("C") else ch for ch in nome)


def prever(contas, aprovados: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Gera o texto da prévia da atribuição de permissões novas aos grupos existentes."""
    grupos = contas.grupos()
    plano = autenticacao.plano_permissoes_novas(grupos, aprovados)

    if not plano["conceder"] and not plano["incertos"]:
        return [NADA]

    linhas = []
    # 1. Cabeçalho das permissões novas
    descricoes = [f"{p} ({autenticacao.PERMISSOES[p]})" for p in autenticacao.PERMISSOES_NOVAS]
    linhas.append(f"Permissões novas: {' e '.join(descricoes)}.")

    # Contagem de usuários ativos por grupo
    usuarios = contas.listar_usuarios()
    ativos = {}
    for u in usuarios:
        if u.get("ativo", 0) == 1:
            ativos[u["grupo_id"]] = ativos.get(u["grupo_id"], 0) + 1

    # 2. Recebem com --confirmar
    if plano["conceder"]:
        linhas.append("Recebem com --confirmar:")
        for c in plano["conceder"]:
            n = ativos.get(c["grupo_id"], 0)
            motivo_desc = "acesso equivalente ao de hoje" if c["motivo"] == "equivalente" else "aprovado com --grupo"
            nome = nome_exibido(c["nome"])
            adicionar = ", ".join(c["adicionar"])
            linhas.append(f"  {nome}: + {adicionar} ({n} usuário(s) ativo(s); {motivo_desc})")

    # 3. Precisam de aprovação individual
    if plano["incertos"]:
        linhas.append("Precisam de aprovação individual (acrescente --grupo NOME para incluir):")
        for inc in plano["incertos"]:
            n = ativos.get(inc["grupo_id"], 0)
            nome = nome_exibido(inc["nome"])
            adicionar = ", ".join(inc["adicionar"])
            linhas.append(f"  {nome}: + {adicionar} ({n} usuário(s) ativo(s))")

    # 4. Já têm as permissões novas
    if plano["completos"]:
        nomes = ", ".join(nome_exibido(n) for n in plano["completos"])
        linhas.append(f"Já têm as permissões novas: {nomes}")

    # 5. Não recebem
    if plano["fora"]:
        fora_desc = ", ".join(f"{nome_exibido(nome)} ({motivo})" for nome, motivo in plano["fora"])
        linhas.append(f"Não recebem: {fora_desc}")

    # 6. Linha final
    if plano["codigo"] is not None:
        linhas.append(f"Nada foi gravado. Código desta prévia: {plano['codigo']}")
    else:
        linhas.append("Nada foi gravado: só há grupos que precisam de aprovação individual.")

    return linhas


def confirmar(contas, aprovados: tuple[str, ...] | list[str], codigo: str | None, agora: str) -> list[str]:
    """Grava as permissões novas aos grupos elegíveis após conferência do código da prévia."""
    grupos = contas.grupos()
    plano = autenticacao.plano_permissoes_novas(grupos, aprovados)

    if not plano["conceder"]:
        return [NADA]

    if codigo != plano["codigo"]:
        raise ValueError(f"A situação mudou desde a prévia (código atual: {plano['codigo']}). Rode a prévia de novo.")

    permissoes_por_grupo = {c["grupo_id"]: set(c["atuais"]) | set(c["adicionar"]) for c in plano["conceder"]}
    estado_anterior = {c["grupo_id"]: set(c["atuais"]) for c in plano["conceder"]}
    versao_esperada = autenticacao.versao_permissoes(estado_anterior)
    detalhes = {
        c["grupo_id"]: (
            f"antes: {', '.join(sorted(c['atuais']))}; "
            f"depois: {', '.join(sorted(set(c['atuais']) | set(c['adicionar'])))}"
        )
        for c in plano["conceder"]
    }

    try:
        contas.definir_matriz(
            permissoes_por_grupo,
            auditoria=("linha-de-comando", agora),
            versao_esperada=versao_esperada,
            detalhes=detalhes,
        )
    except autenticacao.PermissoesAlteradas:
        raise ValueError("As permissões mudaram durante a gravação. Rode a prévia de novo.")

    linhas = ["Gravado:"]
    for c in plano["conceder"]:
        linhas.append(f"  {nome_exibido(c['nome'])}: + {', '.join(c['adicionar'])}")
    linhas.append("Registrado na auditoria (salvar_permissoes, por linha-de-comando).")
    return linhas
