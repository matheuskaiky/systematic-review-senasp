"""Rotas de administração do painel (usuários, matriz de permissões, auditoria e estatísticas)."""
from datetime import datetime, timezone
import re
from starlette.convertors import Convertor, register_url_convertor
from starlette.responses import RedirectResponse, Response
from fastapi import Form, Request

from dominio import autenticacao
from painel import navegacao


class DigitosConvertor(Convertor[str]):
    regex = "[0-9]+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return str(value)


register_url_convertor("digitos", DigitosConvertor())


def _converter_id(texto: str | None) -> int | None:
    if not isinstance(texto, str):
        return None
    t = texto.strip()
    if bool(
        re.fullmatch(r"[0-9]+", t)
        and len(t.lstrip("0")) <= 19
        and int(t.lstrip("0") or "0") <= 9223372036854775807
    ):
        return int(t.lstrip("0") or "0")
    return None


def _resolver_grupo(
    c, request: Request, grupo_id: str, edicao: bool = False
) -> tuple[dict | None, Response | None]:
    """Resolve o grupo pelo ID na URL, tratando concorrência, validação e integridade das permissões."""
    try:
        grupos = c.contas.grupos()
    except autenticacao.ContasOcupadas:
        return None, c.contas_ocupadas(request)

    gid = _converter_id(grupo_id)
    if gid is None:
        return None, c.erro(
            request,
            404,
            "Endereço inválido",
            "Algum número ou parâmetro do endereço não é válido.",
        )

    grupo = next((g for g in grupos if g["grupo_id"] == gid), None)
    if grupo is None:
        return None, c.erro(
            request,
            404,
            "Grupo não encontrado",
            f"Não existe o grupo nº {gid}.",
        )

    if edicao and any(type(p) is not str for p in grupo.get("permissoes", ())):
        return None, c.erro(
            request,
            409,
            "Permissões gravadas inválidas",
            "As permissões gravadas deste grupo têm um valor inválido. Nada foi alterado.",
        )

    return grupo, None


def _usuarios_ativos(c, gid: int) -> int:
    """Conta os usuários ativos vinculados a um grupo."""
    return sum(
        1
        for u in c.contas.listar_usuarios()
        if u.get("grupo_id") == gid and u.get("ativo") == 1
    )


def registrar(c) -> None:
    """Registra rotas de administração e atividade dos revisores."""
    if not c.contexto.autenticacao:
        return

    app = c.app

    _erro_contas_ocupadas = c.contas_ocupadas

    @app.get("/admin")
    def admin_raiz(request: Request):
        return RedirectResponse("/admin/usuarios", status_code=303)

    @app.get("/admin/usuarios")
    def listar_usuarios_view(request: Request):
        try:
            usuarios = c.contas.listar_usuarios()
            grupos = c.contas.grupos()
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)
        revisor_id = next(str(g["grupo_id"]) for g in grupos if g["nome"] == "Revisor")
        form = {"login": "", "nome": "", "grupo_id": revisor_id}
        return c.pagina(
            request,
            "admin_usuarios.html",
            usuarios=usuarios,
            grupos=grupos,
            form=form,
            ok=(request.query_params.get("ok") == "1"),
        )

    @app.post("/admin/usuarios")
    def criar_usuario_view(
        request: Request,
        login: str = Form(""),
        nome: str = Form(""),
        grupo_id: str = Form(""),
        senha: str = Form(""),
        senha2: str = Form(""),
        csrf: str = Form(""),
    ):
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio

        form = {
            "login": login,
            "nome": nome.strip(),
            "grupo_id": grupo_id,
        }

        erros = []
        erros.extend(autenticacao.validar_login(login))
        erros.extend(autenticacao.validar_nome(nome))
        erros.extend(autenticacao.validar_senha(senha))
        if senha != senha2:
            erros.append("As senhas não conferem.")

        gid = _converter_id(grupo_id)
        grupo_escolhido = None
        try:
            grupos_existentes = c.contas.grupos()
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        if gid is None:
            erros.append("Escolha um grupo válido.")
        else:
            grupo_escolhido = next(
                (g for g in grupos_existentes if g["grupo_id"] == gid and g["nome"] != autenticacao.GRUPO_VISITANTE),
                None,
            )
            if grupo_escolhido is None:
                erros.append("Escolha um grupo válido.")

        if erros:
            try:
                usuarios_existentes = c.contas.listar_usuarios()
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)
            return c.pagina(
                request,
                "admin_usuarios.html",
                status=400,
                erros=erros,
                usuarios=usuarios_existentes,
                grupos=grupos_existentes,
                form=form,
            )

        admin_login = request.state.usuario["login"]
        agora = datetime.now(timezone.utc).isoformat()
        try:
            c.contas.criar_usuario(
                login,
                nome.strip(),
                gid,
                autenticacao.hash_senha(senha),
                agora,
                auditoria=(admin_login, "criar_usuario", login, grupo_escolhido["nome"], agora),
            )
        except ValueError as e:
            try:
                usuarios_existentes = c.contas.listar_usuarios()
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)
            return c.pagina(
                request,
                "admin_usuarios.html",
                status=400,
                erros=[str(e)],
                usuarios=usuarios_existentes,
                grupos=grupos_existentes,
                form=form,
            )
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        return RedirectResponse("/admin/usuarios?ok=1", status_code=303)

    @app.get("/admin/usuarios/{usuario_id}")
    def usuario_detalhe_view(request: Request, usuario_id: str):
        uid = _converter_id(usuario_id)
        if uid is None:
            return c.erro(request, 404, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido.")

        try:
            alvo = c.contas.usuario(uid)
            grupos = c.contas.grupos()
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        if alvo is None:
            return c.erro(request, 404, "Usuário não encontrado", f"Não existe o usuário nº {uid}.")

        form = {
            "login": alvo["login"],
            "nome": alvo["nome"],
            "grupo_id": str(alvo["grupo_id"]),
        }

        return c.pagina(
            request,
            "admin_usuario.html",
            alvo=alvo,
            grupos=grupos,
            form=form,
            ok=(request.query_params.get("ok") == "1"),
            sem_token=(request.query_params.get("ok") == "sem-token"),
        )

    @app.post("/admin/usuarios/{usuario_id}")
    def usuario_acao_view(
        request: Request,
        usuario_id: str,
        acao: str = Form(""),
        login: str = Form(""),
        nome: str = Form(""),
        grupo_id: str = Form(""),
        senha: str = Form(""),
        senha2: str = Form(""),
        csrf: str = Form(""),
    ):
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio

        uid = _converter_id(usuario_id)
        if uid is None:
            return c.erro(request, 404, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido.")

        try:
            alvo = c.contas.usuario(uid)
            grupos = c.contas.grupos()
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        if alvo is None:
            return c.erro(request, 404, "Usuário não encontrado", f"Não existe o usuário nº {uid}.")

        form = {
            "login": login,
            "nome": nome.strip(),
            "grupo_id": grupo_id,
        }

        def _re_render(erros):
            return c.pagina(
                request,
                "admin_usuario.html",
                status=400,
                erros=erros,
                alvo=alvo,
                grupos=grupos,
                form=form,
            )

        if acao not in ("dados", "senha", "desativar", "reativar", "revogar_token"):
            return _re_render(["Ação desconhecida."])

        acting_admin = request.state.usuario
        acting_admin_id = acting_admin["usuario_id"]
        acting_admin_login = acting_admin["login"]
        agora = datetime.now(timezone.utc).isoformat()

        if acao == "dados":
            erros = []
            erros.extend(autenticacao.validar_login(login))
            erros.extend(autenticacao.validar_nome(nome))
            gid = _converter_id(grupo_id)
            novo_grupo = None
            if gid is None:
                erros.append("Escolha um grupo válido.")
            else:
                novo_grupo = next(
                    (g for g in grupos if g["grupo_id"] == gid and g["nome"] != autenticacao.GRUPO_VISITANTE),
                    None,
                )
                if novo_grupo is None:
                    erros.append("Escolha um grupo válido.")

            if erros:
                return _re_render(erros)

            try:
                admins_ativos = c.contas.contar_admins_ativos()
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            if alvo["ativo"] == 1 and alvo["grupo"] == autenticacao.GRUPO_ADMIN and novo_grupo["nome"] != autenticacao.GRUPO_ADMIN:
                if admins_ativos <= 1:
                    return _re_render(["O painel precisa de pelo menos um administrador ativo."])

            mudou_login = (login != alvo["login"])
            mudou_nome = (nome.strip() != alvo["nome"])
            mudou_grupo = (gid != alvo["grupo_id"])

            if not (mudou_login or mudou_nome or mudou_grupo):
                return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

            partes = []
            if mudou_login:
                partes.append(f"login: {alvo['login']} -> {login}")
            if mudou_nome:
                partes.append(f"nome: {alvo['nome']} -> {nome.strip()}")
            if mudou_grupo:
                partes.append(f"grupo: {alvo['grupo']} -> {novo_grupo['nome']}")
            detalhe = "; ".join(partes)

            try:
                c.contas.editar_usuario(
                    uid,
                    login,
                    nome.strip(),
                    gid,
                    auditoria=(acting_admin_login, "editar_usuario", alvo["login"], detalhe, agora),
                )
            except ValueError as e:
                return _re_render([str(e)])
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            if uid == acting_admin_id and mudou_grupo and novo_grupo["nome"] != autenticacao.GRUPO_ADMIN:
                return RedirectResponse("/", status_code=303)

            return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

        elif acao == "senha":
            erros = []
            erros.extend(autenticacao.validar_senha(senha))
            if senha != senha2:
                erros.append("As senhas não conferem.")
            if erros:
                return _re_render(erros)

            try:
                c.contas.redefinir_senha(
                    uid,
                    autenticacao.hash_senha(senha),
                    auditoria=(acting_admin_login, "redefinir_senha", alvo["login"], None, agora),
                )
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            if uid == acting_admin_id:
                resp = RedirectResponse("/entrar", status_code=303)
                resp.delete_cookie("sessao")
                return resp

            return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

        elif acao == "desativar":
            if uid == acting_admin_id:
                return _re_render(["Você não pode desativar a própria conta."])

            try:
                admins_ativos = c.contas.contar_admins_ativos()
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            if alvo["ativo"] == 1 and alvo["grupo"] == autenticacao.GRUPO_ADMIN and admins_ativos <= 1:
                return _re_render(["O painel precisa de pelo menos um administrador ativo."])

            if alvo["ativo"] == 0:
                return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

            try:
                c.contas.definir_ativo(
                    uid,
                    0,
                    auditoria=(acting_admin_login, "desativar_usuario", alvo["login"], None, agora),
                )
            except ValueError as e:
                return _re_render([str(e)])
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

        elif acao == "reativar":
            if alvo["ativo"] == 1:
                return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

            try:
                c.contas.definir_ativo(
                    uid,
                    1,
                    auditoria=(acting_admin_login, "reativar_usuario", alvo["login"], None, agora),
                )
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            return RedirectResponse(f"/admin/usuarios/{uid}?ok=1", status_code=303)

        elif acao == "revogar_token":
            try:
                apagou = c.contas.revogar_token(uid, auditoria=(acting_admin_login, "revogar_token", alvo["login"], None, agora))
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            return RedirectResponse(f"/admin/usuarios/{uid}?ok=" + ("1" if apagou else "sem-token"), status_code=303)

    @app.get("/admin/grupos")
    def listar_grupos_view(request: Request):
        try:
            grupos = c.contas.grupos()
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)
        form = {"novo": "", "renomear": {}}
        return c.pagina(
            request,
            "admin_grupos.html",
            grupos=grupos,
            permissoes=autenticacao.PERMISSOES,
            proibidas_visitante=autenticacao.PERMISSOES_PROIBIDAS_VISITANTE,
            grupos_padrao=autenticacao.GRUPOS_PADRAO,
            form=form,
        )

    @app.get("/admin/grupos/{grupo_id:digitos}")
    def grupo_permissoes_view(request: Request, grupo_id: str):
        grupo, erro = _resolver_grupo(c, request, grupo_id, edicao=False)
        if erro:
            return erro

        gid = grupo["grupo_id"]
        try:
            usuarios_ativos = _usuarios_ativos(c, gid)
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        nome = grupo["nome"]
        permissoes = grupo["permissoes"]

        q = request.query_params.get("q", "")
        filtro = request.query_params.get("filtro", "")
        modulo = request.query_params.get("modulo", "")

        filtro_ativo = filtro if filtro in ("habilitadas", "desabilitadas", "sensiveis") else ""
        modulo_ativo = modulo if modulo in autenticacao.MODULOS_PERMISSAO else ""

        resumo = autenticacao.resumo_do_grupo(nome, permissoes)
        chaves_filtradas = autenticacao.filtrar_permissoes(nome, permissoes, q, filtro, modulo)

        modulos_exibidos = []
        for m_chave, m_rotulo in autenticacao.MODULOS_PERMISSAO.items():
            chaves_modulo_filtradas = [
                k for k in chaves_filtradas if autenticacao.CATALOGO_PERMISSOES[k]["modulo"] == m_chave
            ]
            if not chaves_modulo_filtradas:
                continue

            todas_modulo = [
                k for k in autenticacao.PERMISSOES if autenticacao.CATALOGO_PERMISSOES[k]["modulo"] == m_chave
            ]
            hab_modulo = [k for k in todas_modulo if k in resumo["habilitadas"]]

            itens = []
            for k in chaves_modulo_filtradas:
                meta = autenticacao.CATALOGO_PERMISSOES[k]
                if nome == autenticacao.GRUPO_VISITANTE and k in autenticacao.PERMISSOES_PROIBIDAS_VISITANTE:
                    estado = "Não permitida a quem não entrou"
                elif k in resumo["habilitadas"]:
                    estado = "Habilitada"
                else:
                    estado = "Não habilitada"

                sensivel = autenticacao.ROTULOS_SENSIBILIDADE.get(meta["sensibilidade"])
                dependencias = [autenticacao.PERMISSOES[d] for d in meta["depende_de"]]

                itens.append({
                    "chave": k,
                    "descricao": autenticacao.PERMISSOES[k],
                    "estado": estado,
                    "sensivel": sensivel,
                    "dependencias": dependencias,
                })

            modulos_exibidos.append({
                "chave": m_chave,
                "rotulo": m_rotulo,
                "total_habilitadas": len(hab_modulo),
                "total_modulo": len(todas_modulo),
                "itens": itens,
            })

        previa_menu = navegacao.grupos(
            "/",
            admin=(nome == autenticacao.GRUPO_ADMIN),
            banco=c.contexto.banco,
            pode=lambda m, cam: autenticacao.pode_acessar(nome, permissoes, m, cam),
        )

        return c.pagina(
            request,
            "admin_grupo.html",
            nome=nome,
            grupo_id=gid,
            gravado=request.query_params.get("gravado"),
            usuarios_ativos=usuarios_ativos,
            resumo=resumo,
            q=q,
            filtro_ativo=filtro_ativo,
            modulo_ativo=modulo_ativo,
            modulos_opcoes=list(autenticacao.MODULOS_PERMISSAO.items()),
            modulos_exibidos=modulos_exibidos,
            previa_menu=previa_menu,
        )

    def _calcular_frase_efeito(nome: str, gid: int, r: dict) -> str:
        if r.get("erros") or (not r.get("concedidas") and not r.get("retiradas")):
            return ""
        if nome == autenticacao.GRUPO_VISITANTE:
            return "Efeito imediato: vale para qualquer pessoa que abrir o painel sem entrar."
        n = _usuarios_ativos(c, gid)
        if n == 0:
            return "Efeito imediato: este grupo não tem usuários ativos agora; a mudança vale para quem entrar nele."
        elif n == 1:
            return "Efeito imediato: vale a partir do próximo pedido do 1 usuário ativo deste grupo."
        else:
            return f"Efeito imediato: vale a partir do próximo pedido dos {n} usuários ativos deste grupo."

    @app.get("/admin/grupos/{grupo_id}/editar")
    def editar_grupo_view(request: Request, grupo_id: str):
        grupo, erro = _resolver_grupo(c, request, grupo_id, edicao=True)
        if erro:
            return erro

        gid = grupo["grupo_id"]
        nome = grupo["nome"]
        atuais = set(grupo["permissoes"])
        versao = autenticacao.versao_permissoes({gid: atuais})

        modulos = []
        for m_chave, m_rotulo in autenticacao.MODULOS_PERMISSAO.items():
            itens_modulo = [
                k for k in autenticacao.PERMISSOES if autenticacao.CATALOGO_PERMISSOES[k]["modulo"] == m_chave
            ]
            if not itens_modulo:
                continue

            itens = []
            for k in itens_modulo:
                meta = autenticacao.CATALOGO_PERMISSOES[k]
                desc = autenticacao.PERMISSOES[k]
                sensivel = autenticacao.ROTULOS_SENSIBILIDADE.get(meta["sensibilidade"])
                dependencias = [autenticacao.PERMISSOES[d] for d in meta["depende_de"]]

                bloqueado = False
                estado_texto = ""
                if nome == autenticacao.GRUPO_VISITANTE and k not in atuais:
                    if k in autenticacao.PERMISSOES_PROIBIDAS_VISITANTE:
                        bloqueado = True
                        estado_texto = "Não permitida a quem não entrou"
                    elif meta["sensibilidade"] in autenticacao.ROTULOS_SENSIBILIDADE:
                        bloqueado = True
                        estado_texto = "Só com a política de divulgação pública"

                itens.append({
                    "chave": k,
                    "descricao": desc,
                    "editavel": not bloqueado,
                    "marcada": k in atuais,
                    "estado_texto": estado_texto,
                    "sensivel": sensivel,
                    "dependencias": dependencias,
                })

            modulos.append({
                "chave": m_chave,
                "rotulo": m_rotulo,
                "itens": itens,
            })

        return c.pagina(
            request,
            "admin_grupo_editar.html",
            nome=nome,
            grupo_id=gid,
            atuais=atuais,
            versao=versao,
            modulos=modulos,
        )

    @app.post("/admin/grupos/{grupo_id}/revisar")
    async def revisar_grupo_view(request: Request, grupo_id: str):
        form = await request.form()
        csrf = form.get("csrf", "")
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio

        grupo, erro = _resolver_grupo(c, request, grupo_id, edicao=True)
        if erro:
            return erro

        gid = grupo["grupo_id"]
        nome = grupo["nome"]
        atuais = set(grupo["permissoes"])

        marcadas = list(form.getlist("marcada"))
        exibidas = list(form.getlist("exibida"))
        v_list = form.getlist("versao")
        versao = v_list[0] if v_list and isinstance(v_list[0], str) else ""
        j_list = form.getlist("justificativa")
        justificativa = j_list[0] if j_list and isinstance(j_list[0], str) else ""

        r = autenticacao.revisar_alteracao(nome, atuais, marcadas, exibidas)

        try:
            frase = _calcular_frase_efeito(nome, gid, r)
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        return c.pagina(
            request,
            "admin_grupo_revisar.html",
            nome=nome,
            grupo_id=gid,
            revisao=r,
            marcadas=marcadas,
            exibidas=exibidas,
            versao=versao,
            justificativa=justificativa,
            mensagens_erro=r["erros"],
            frase=frase,
            permissoes=autenticacao.PERMISSOES,
            catalogo=autenticacao.CATALOGO_PERMISSOES,
            rotulos_sensibilidade=autenticacao.ROTULOS_SENSIBILIDADE,
        )

    @app.post("/admin/grupos/{grupo_id}/permissoes")
    async def salvar_permissoes_grupo_view(request: Request, grupo_id: str):
        form = await request.form()
        csrf = form.get("csrf", "")
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio

        grupo, erro = _resolver_grupo(c, request, grupo_id, edicao=True)
        if erro:
            return erro

        gid = grupo["grupo_id"]
        nome = grupo["nome"]
        atuais = set(grupo["permissoes"])

        marcadas = list(form.getlist("marcada"))
        exibidas = list(form.getlist("exibida"))
        v_list = form.getlist("versao")
        versao = v_list[0] if v_list and isinstance(v_list[0], str) else ""
        j_list = form.getlist("justificativa")
        justificativa = j_list[0] if j_list and isinstance(j_list[0], str) else ""
        confirmado = "1" in form.getlist("confirmo")

        admin_login = request.state.usuario["login"]
        agora = datetime.now(timezone.utc).isoformat()

        try:
            r = c.contas.definir_permissoes_do_grupo(
                gid,
                marcadas,
                exibidas,
                versao,
                confirmado,
                justificativa,
                (admin_login, agora),
            )
        except autenticacao.PermissoesAlteradas:
            return c.erro(
                request,
                409,
                "Permissões alteradas",
                "As permissões deste grupo mudaram desde que você abriu a página. Nada foi gravado: abra o grupo de novo e refaça as alterações.",
            )
        except autenticacao.AlteracaoRecusada as e:
            r_rec = autenticacao.revisar_alteracao(nome, atuais, marcadas, exibidas)
            try:
                frase = _calcular_frase_efeito(nome, gid, r_rec)
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)

            return c.pagina(
                request,
                "admin_grupo_revisar.html",
                status=400,
                nome=nome,
                grupo_id=gid,
                revisao=r_rec,
                marcadas=marcadas,
                exibidas=exibidas,
                versao=versao,
                justificativa=justificativa,
                mensagens_erro=e.erros,
                frase=frase,
                permissoes=autenticacao.PERMISSOES,
                catalogo=autenticacao.CATALOGO_PERMISSOES,
                rotulos_sensibilidade=autenticacao.ROTULOS_SENSIBILIDADE,
            )
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        mudancas = bool(r.get("concedidas") or r.get("retiradas"))
        param = "1" if mudancas else "0"
        return RedirectResponse(f"/admin/grupos/{gid}?gravado={param}", status_code=303)

    @app.post("/admin/grupos/novo")
    def criar_grupo_view(request: Request, nome: str = Form(""), csrf: str = Form("")):
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio

        form = {"novo": nome.strip(), "renomear": {}}

        erros = autenticacao.validar_nome_grupo(nome)
        if erros:
            try:
                grupos = c.contas.grupos()
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)
            return c.pagina(
                request,
                "admin_grupos.html",
                status=400,
                erros=erros,
                grupos=grupos,
                permissoes=autenticacao.PERMISSOES,
                proibidas_visitante=autenticacao.PERMISSOES_PROIBIDAS_VISITANTE,
                grupos_padrao=autenticacao.GRUPOS_PADRAO,
                form=form,
            )

        admin_login = request.state.usuario["login"]
        agora = datetime.now(timezone.utc).isoformat()
        try:
            c.contas.criar_grupo(
                nome,
                agora,
                auditoria=(admin_login, "criar_grupo", nome.strip(), None, agora),
            )
        except ValueError as e:
            try:
                grupos = c.contas.grupos()
            except autenticacao.ContasOcupadas:
                return _erro_contas_ocupadas(request)
            return c.pagina(
                request,
                "admin_grupos.html",
                status=400,
                erros=[str(e)],
                grupos=grupos,
                permissoes=autenticacao.PERMISSOES,
                proibidas_visitante=autenticacao.PERMISSOES_PROIBIDAS_VISITANTE,
                grupos_padrao=autenticacao.GRUPOS_PADRAO,
                form=form,
            )
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        return RedirectResponse("/admin/grupos?ok=1", status_code=303)

    @app.post("/admin/grupos/{grupo_id}/renomear")
    def renomear_grupo_view(request: Request, grupo_id: str, nome: str = Form(""), csrf: str = Form("")):
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio

        gid = _converter_id(grupo_id)
        if gid is None:
            return c.erro(request, 404, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido.")

        try:
            grupos = c.contas.grupos()
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        grupo = next((g for g in grupos if g["grupo_id"] == gid), None)
        if grupo is None:
            return c.erro(request, 404, "Grupo não encontrado", f"Não existe o grupo nº {gid}.")

        form = {"novo": "", "renomear": {gid: nome.strip()}}

        erros = autenticacao.validar_nome_grupo(nome)
        if erros:
            return c.pagina(
                request,
                "admin_grupos.html",
                status=400,
                erros=erros,
                grupos=grupos,
                permissoes=autenticacao.PERMISSOES,
                proibidas_visitante=autenticacao.PERMISSOES_PROIBIDAS_VISITANTE,
                grupos_padrao=autenticacao.GRUPOS_PADRAO,
                form=form,
            )

        if grupo["nome"] in autenticacao.GRUPOS_PADRAO or grupo["fixo"] == 1:
            return c.pagina(
                request,
                "admin_grupos.html",
                status=400,
                erros=["Este grupo não pode ser renomeado."],
                grupos=grupos,
                permissoes=autenticacao.PERMISSOES,
                proibidas_visitante=autenticacao.PERMISSOES_PROIBIDAS_VISITANTE,
                grupos_padrao=autenticacao.GRUPOS_PADRAO,
                form=form,
            )

        if nome.strip() == grupo["nome"]:
            return RedirectResponse("/admin/grupos?ok=1", status_code=303)

        admin_login = request.state.usuario["login"]
        agora = datetime.now(timezone.utc).isoformat()
        try:
            c.contas.renomear_grupo(
                gid,
                nome.strip(),
                auditoria=(admin_login, "renomear_grupo", nome.strip(), f"{grupo['nome']} -> {nome.strip()}", agora),
            )
        except ValueError as e:
            return c.pagina(
                request,
                "admin_grupos.html",
                status=400,
                erros=[str(e)],
                grupos=grupos,
                permissoes=autenticacao.PERMISSOES,
                proibidas_visitante=autenticacao.PERMISSOES_PROIBIDAS_VISITANTE,
                grupos_padrao=autenticacao.GRUPOS_PADRAO,
                form=form,
            )
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        return RedirectResponse("/admin/grupos?ok=1", status_code=303)

    @app.get("/admin/auditoria")
    def listar_auditoria_view(request: Request):
        try:
            linhas = c.contas.auditoria(limite=200)
        except autenticacao.ContasOcupadas:
            return _erro_contas_ocupadas(request)

        for l in linhas:
            l["resumo"] = (
                autenticacao.resumo_detalhe_auditoria(l.get("detalhe"))
                if l.get("acao") == "salvar_permissoes"
                else None
            )

        return c.pagina(
            request,
            "admin_auditoria.html",
            linhas=linhas,
            ok=(request.query_params.get("ok") == "1"),
        )

    @app.get("/estatisticas-usuarios")
    def estatisticas_usuarios_view(request: Request):
        if not c.leitura.existe():
            return c.sem_banco(request)

        linhas = c.leitura.atividade_por_revisor()
        hoje = datetime.now(timezone.utc).date().isoformat()
        totais, janela = autenticacao.resumir_atividade(linhas, hoje)

        usuario = getattr(request.state, "usuario", None)
        ver_nomes = bool(
            usuario and autenticacao.pode(usuario["grupo"], usuario["permissoes"], "ver_nomes_revisores")
        )

        if not ver_nomes and totais:
            mapa = {t["revisor"]: f"Revisor {i}" for i, t in enumerate(totais, 1)}
            for t in totais:
                t["revisor"] = mapa[t["revisor"]]
            for j in janela:
                j["revisor"] = mapa[j["revisor"]]

        return c.pagina(
            request,
            "estatisticas_usuarios.html",
            totais=totais,
            janela=janela,
        )
