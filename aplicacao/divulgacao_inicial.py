"""Aplicação para o comando de inicialização da divulgação pública (D145, Q-P8-2 a)."""
from dominio import autenticacao, divulgacao

CAB = "Estado inicial da divulgação pública da pesquisa {banco}."
CONFIGURADA = (
    "A divulgação desta pesquisa já está configurada ({situacao}): este comando nunca muda uma configuração que "
    "existe. Para alterá-la, use a tela Divulgação pública do painel. Nada a gravar."
)
FECHADA = (
    "O grupo Visitante não vê o painel nas contas desta pesquisa: ela continua não divulgada, como hoje. "
    "Nada a gravar."
)
PROPOSTA = (
    "O grupo Visitante vê o painel nas contas desta pesquisa. Para preservar o acesso de hoje, a proposta é gravar "
    "«divulgada», sem resultados preliminares."
)
EFEITO = (
    "Efeito: quem não entrou passará a ver a Visão Geral, Sobre os dados, o PRISMA, a Metodologia e a busca no texto, sem "
    "resultados automatizados."
)
GRAVADO = "Gravado: divulgada, sem resultados preliminares. A alteração está no registro de administração."


def _validar_banco(banco: str) -> None:
    if type(banco) is not str or banco not in divulgacao.PESQUISAS:
        raise ValueError("Pesquisa inválida.")


def prever(contas, banco: str) -> list[str]:
    """Gera a prévia da inicialização da divulgação pública sem gravar nada."""
    _validar_banco(banco)
    try:
        estado = contas.estado_divulgacao(banco)
        perms = contas.permissoes_do_grupo(autenticacao.GRUPO_VISITANTE)
    except autenticacao.ContasOcupadas:
        raise ValueError("O banco de contas está ocupado. Tente de novo em alguns segundos.")

    ve_painel = "ver_painel" in perms
    plano = divulgacao.plano_inicial(banco, estado, ve_painel)

    if plano["acao"] == "nada":
        if plano["motivo"] == "configurada":
            situacao = "válida" if estado["situacao"] == "valida" else "inválida"
            return [CAB.format(banco=banco), CONFIGURADA.format(situacao=situacao)]
        return [CAB.format(banco=banco), FECHADA]

    codigo = plano["codigo"]
    return [
        CAB.format(banco=banco),
        PROPOSTA,
        EFEITO,
        f"Nada foi gravado. Código desta prévia: {codigo}",
    ]


def confirmar(contas, banco: str, codigo: str | None, agora: str) -> list[str]:
    """Confirma e grava a divulgação inicial com o código previsto."""
    _validar_banco(banco)
    try:
        estado = contas.estado_divulgacao(banco)
        perms = contas.permissoes_do_grupo(autenticacao.GRUPO_VISITANTE)
    except autenticacao.ContasOcupadas:
        raise ValueError("O banco de contas está ocupado. Tente de novo em alguns segundos.")

    ve_painel = "ver_painel" in perms
    plano = divulgacao.plano_inicial(banco, estado, ve_painel)

    if plano["acao"] == "nada":
        if plano["motivo"] == "configurada":
            situacao = "válida" if estado["situacao"] == "valida" else "inválida"
            return [CAB.format(banco=banco), CONFIGURADA.format(situacao=situacao)]
        return [CAB.format(banco=banco), FECHADA]

    if codigo != plano["codigo"]:
        raise ValueError(
            f"A situação mudou desde a prévia (código atual: {plano['codigo']}). Rode a prévia de novo."
        )

    try:
        contas.alterar_divulgacao(
            banco,
            plano["nova"],
            estado["versao"],
            True,
            ("linha-de-comando", agora),
        )
    except autenticacao.ContasOcupadas:
        raise ValueError("O banco de contas está ocupado. Tente de novo em alguns segundos.")
    except divulgacao.DivulgacaoAlterada:
        raise ValueError(
            "A configuração desta pesquisa mudou durante a gravação: nada foi gravado por este comando. "
            "Rode a prévia de novo."
        )

    return [CAB.format(banco=banco), GRAVADO]
