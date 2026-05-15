"""
Tools MCP para consultar el estado de ArgoCD.
Fase 3: cierra el loop GitOps — desde el commit hasta el pod corriendo.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from server.config import config


def _argocd_headers() -> dict:
    """Headers para la API REST de ArgoCD."""
    return {
        "Authorization": f"Bearer {config.ARGOCD_TOKEN}",
        "Content-Type": "application/json",
    }


def _argocd_base_url() -> str:
    """
    URL base de la API de ArgoCD.
    ArgoCD siempre corre con HTTPS — incluso en instalaciones locales.
    ARGOCD_INSECURE=true desactiva la validación del certificado autofirmado,
    no cambia el protocolo a HTTP.
    """
    return f"https://{config.ARGOCD_SERVER}/api/v1"


def register_argocd_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_argocd_status(app_name: str = "ms-devsecops") -> dict:
        """
        Consulta el estado de sincronización y salud de una aplicación en ArgoCD.
        Muestra si el cluster refleja lo que está en Git (Synced/OutOfSync),
        el estado de salud de los pods (Healthy/Degraded), la imagen desplegada,
        y cuándo fue el último sync exitoso.
        Usar para verificar que un deploy llegó correctamente al cluster.

        Args:
            app_name: nombre de la aplicación en ArgoCD (default: ms-devsecops)
        """
        if not config.ARGOCD_TOKEN:
            return {
                "error": "ARGOCD_TOKEN no configurado",
                "suggestion": "Agrega ARGOCD_TOKEN al .env y reinicia el servidor"
            }

        url = f"{_argocd_base_url()}/applications/{app_name}"

        try:
            # verify=False porque ArgoCD local usa certificado autofirmado
            async with httpx.AsyncClient(
                timeout=30,
                verify=not config.ARGOCD_INSECURE
            ) as client:
                response = await client.get(url, headers=_argocd_headers())
        except httpx.ConnectError:
            return {
                "error": "No se puede conectar a ArgoCD",
                "suggestion": (
                    "Verifica que el port-forward está activo: "
                    "kubectl port-forward svc/argocd-server -n argocd 8080:443"
                )
            }

        if response.status_code == 404:
            return {
                "error": f"Aplicación '{app_name}' no encontrada en ArgoCD",
                "suggestion": "Verifica el nombre con: kubectl get applications -n argocd"
            }

        if response.status_code != 200:
            return {
                "error": f"Error consultando ArgoCD: HTTP {response.status_code}",
                "details": response.text[:300]
            }

        data = response.json()

        # Extraer la información relevante del response de ArgoCD
        # El objeto es grande — filtramos solo lo que Claude necesita
        status = data.get("status", {})
        sync = status.get("sync", {})
        health = status.get("health", {})
        summary = status.get("summary", {})
        operation_state = status.get("operationState", {})

        # Extraer imágenes desplegadas actualmente
        images = summary.get("images", [])

        # Extraer recursos del cluster
        resources = status.get("resources", [])
        pods = [r for r in resources if r.get("kind") == "Pod"]
        deployments = [r for r in resources if r.get("kind") == "Deployment"]

        # Estado del último sync
        last_sync = operation_state.get("finishedAt", "unknown")
        last_sync_message = operation_state.get("message", "")
        last_sync_phase = operation_state.get("phase", "unknown")

        result = {
            "application": app_name,
            "health": {
                "status": health.get("status", "Unknown"),
                # Healthy = todos los pods corriendo
                # Degraded = algún pod en error
                # Progressing = rolling update en curso
                # Missing = recursos no encontrados
                "message": health.get("message", ""),
            },
            "sync": {
                "status": sync.get("status", "Unknown"),
                # Synced = cluster = Git
                # OutOfSync = hay diferencias entre Git y el cluster
                "revision": sync.get("revision", "unknown")[:7],  # SHA corto
                "last_sync_at": last_sync,
                "last_sync_phase": last_sync_phase,
                "last_sync_message": last_sync_message,
            },
            "deployment": {
                "images": images,
                "replicas_desired": deployments[0].get("status", "") if deployments else "unknown",
            },
            "pods": [
                {
                    "name": p.get("name"),
                    "health": p.get("health", {}).get("status"),
                    "status": p.get("status"),
                }
                for p in pods
            ],
            "repo": {
                "url": data.get("spec", {}).get("source", {}).get("repoURL"),
                "branch": data.get("spec", {}).get("source", {}).get("targetRevision"),
                "path": data.get("spec", {}).get("source", {}).get("path"),
            },
        }

        # Guiar a Claude con contexto accionable
        sync_status = result["sync"]["status"]
        health_status = result["health"]["status"]

        if sync_status == "Synced" and health_status == "Healthy":
            result["assessment"] = (
                f"✅ El microservicio {app_name} está correctamente desplegado. "
                f"Cluster sincronizado con Git (rev: {result['sync']['revision']}). "
                f"Todos los pods healthy."
            )
        elif sync_status == "OutOfSync":
            result["assessment"] = (
                f"⚠️ {app_name} está OutOfSync — Git tiene cambios que no "
                f"llegaron al cluster todavía. ArgoCD sincroniza cada 3 minutos "
                f"o puedes forzar el sync desde la UI."
            )
        elif health_status == "Degraded":
            result["assessment"] = (
                f"❌ {app_name} está Degraded — hay pods en error. "
                f"Revisar logs: kubectl logs -n devsecops "
                f"-l app.kubernetes.io/name={app_name}"
            )
        elif health_status == "Progressing":
            result["assessment"] = (
                f"🔄 {app_name} está en rolling update. "
                f"Los pods nuevos están arrancando. Consulta en 30 segundos."
            )
        else:
            result["assessment"] = (
                f"Estado: sync={sync_status}, health={health_status}. "
                f"Consulta la UI de ArgoCD para más detalles."
            )

        return result


    @mcp.tool()
    async def force_argocd_sync(app_name: str = "ms-devsecops") -> dict:
        """
        Fuerza la sincronización inmediata de una aplicación en ArgoCD.
        Útil cuando hay un OutOfSync y no quieres esperar el ciclo automático de 3 minutos.
        ArgoCD aplicará los cambios de Git al cluster inmediatamente.

        Args:
            app_name: nombre de la aplicación en ArgoCD (default: ms-devsecops)
        """
        if not config.ARGOCD_TOKEN:
            return {"error": "ARGOCD_TOKEN no configurado"}

        url = f"{_argocd_base_url()}/applications/{app_name}/sync"

        try:
            async with httpx.AsyncClient(
                timeout=30,
                verify=not config.ARGOCD_INSECURE
            ) as client:
                response = await client.post(
                    url,
                    headers=_argocd_headers(),
                    json={
                        # prune=True elimina recursos que ya no están en Git
                        "prune": True,
                        # dryRun=False aplica los cambios realmente
                        "dryRun": False,
                    }
                )
        except httpx.ConnectError:
            return {
                "error": "No se puede conectar a ArgoCD",
                "suggestion": "Verifica el port-forward: kubectl port-forward svc/argocd-server -n argocd 8080:443"
            }

        if response.status_code == 200:
            return {
                "status": "sync_initiated",
                "application": app_name,
                "message": (
                    f"Sync de {app_name} iniciado. ArgoCD está aplicando "
                    f"los cambios de Git al cluster. "
                    f"Usa get_argocd_status en 30 segundos para verificar."
                )
            }

        return {
            "error": f"Error forzando sync: HTTP {response.status_code}",
            "details": response.text[:300]
        }
    @mcp.tool()
    async def rollback_deployment(
        app_name: str = "ms-devsecops",
        reason: str = "regresión detectada",
    ) -> dict:
        """
        Inicia un rollback del microservicio via Git — NO via API directa de ArgoCD.
        Crea un branch de rollback, revierte el values.yaml al tag anterior
        y abre un PR para aprobación humana.
        Claude propone el rollback — el humano decide si ejecutarlo.
        IMPORTANTE: Con auto-sync habilitado en ArgoCD, el rollback DEBE pasar
        por Git. Un rollback directo via API sería revertido inmediatamente.

        Args:
            app_name: nombre del microservicio (default: ms-devsecops)
            reason: motivo del rollback para documentar en el PR
        """
        import base64
        import re

        # ── 1. Leer el values.yaml actual via GitHub API ──────────────────
        values_path = f"microservice/helm/{app_name}/values.yaml"
        contents_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/contents/{values_path}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            contents_response = await client.get(
                contents_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                }
            )

        if contents_response.status_code != 200:
            return {"error": "No se pudo leer el values.yaml desde GitHub"}

        contents_data = contents_response.json()
        current_content = base64.b64decode(
            contents_data.get("content", "")
        ).decode("utf-8")
        file_sha = contents_data.get("sha")

        # Extraer el tag actual del values.yaml
        current_tag_match = re.search(r'tag:\s*"?(sha-[a-f0-9]+)"?', current_content)
        if not current_tag_match:
            return {"error": "No se encontró el tag de imagen en values.yaml"}

        current_tag = current_tag_match.group(1)

        # ── 2. Obtener historial de commits del values.yaml ───────────────
        commits_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/commits"
            f"?path={values_path}&per_page=5"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            commits_response = await client.get(
                commits_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                }
            )

        if commits_response.status_code != 200:
            return {"error": "No se pudo obtener el historial de commits"}

        commits = commits_response.json()

        if len(commits) < 2:
            return {
                "error": "No hay versión anterior disponible",
                "current_tag": current_tag,
                "suggestion": "Se necesitan al menos 2 deployments para hacer rollback"
            }

        # El segundo commit es el deploy anterior
        previous_commit_sha = commits[1].get("sha")

        # ── 3. Obtener el values.yaml del commit anterior ─────────────────
        prev_contents_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/contents/{values_path}"
            f"?ref={previous_commit_sha}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            prev_response = await client.get(
                prev_contents_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                }
            )

        if prev_response.status_code != 200:
            return {"error": "No se pudo obtener el values.yaml anterior"}

        prev_content = base64.b64decode(
            prev_response.json().get("content", "")
        ).decode("utf-8")

        # Extraer el tag anterior
        prev_tag_match = re.search(r'tag:\s*"?(sha-[a-f0-9]+)"?', prev_content)
        if not prev_tag_match:
            return {"error": "No se encontró el tag anterior en el historial"}

        previous_tag = prev_tag_match.group(1)

        if previous_tag == current_tag:
            return {
                "error": "El tag anterior es el mismo que el actual — no hay cambio que revertir",
                "current_tag": current_tag,
            }

        # ── 4. Crear branch de rollback via GitHub API ────────────────────
        # Primero obtener el SHA del HEAD de master
        ref_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/git/ref/heads/master"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            ref_response = await client.get(
                ref_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                }
            )

        master_sha = ref_response.json().get("object", {}).get("sha")
        branch_name = f"rollback/{previous_tag}"

        # Crear el branch
        create_branch_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/git/refs"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            branch_response = await client.post(
                create_branch_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "ref": f"refs/heads/{branch_name}",
                    "sha": master_sha,
                }
            )

        if branch_response.status_code not in (200, 201, 422):
            return {"error": f"Error creando branch: HTTP {branch_response.status_code}"}

        # ── 5. Actualizar values.yaml en el branch de rollback ────────────
        new_content = current_content.replace(
            f'tag: "{current_tag}"',
            f'tag: "{previous_tag}"'
        )

        import base64 as b64
        update_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/contents/{values_path}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            update_response = await client.put(
                update_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "message": f"fix(rollback): revertir {app_name} a {previous_tag}\n\nMotivo: {reason}",
                    "content": b64.b64encode(new_content.encode()).decode(),
                    "sha": file_sha,
                    "branch": branch_name,
                }
            )

        if update_response.status_code not in (200, 201):
            return {
                "error": f"Error actualizando values.yaml: HTTP {update_response.status_code}",
                "details": update_response.text[:300]
            }

        # ── 6. Abrir PR de rollback ───────────────────────────────────────
        pr_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/pulls"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            pr_response = await client.post(
                pr_url,
                headers={
                    "Authorization": f"Bearer {config.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "title": f"rollback: {app_name} {current_tag} → {previous_tag}",
                    "body": (
                        f"## Rollback solicitado por Claude\n\n"
                        f"**Motivo:** {reason}\n\n"
                        f"**Versión actual:** `{current_tag}`\n"
                        f"**Versión anterior:** `{previous_tag}`\n\n"
                        f"### ¿Qué hace este PR?\n"
                        f"Revierte el `values.yaml` al tag anterior.\n"
                        f"ArgoCD detectará el cambio y hará el rollback automáticamente.\n\n"
                        f"### ⚠️ Acción requerida\n"
                        f"Revisar las métricas antes de aprobar:\n"
                        f"- ¿El problema fue confirmado en producción?\n"
                        f"- ¿El rollback a `{previous_tag}` resuelve el problema?\n\n"
                        f"> Este PR fue generado automáticamente por el agente DevSecOps.\n"
                        f"> La decisión final es del humano."
                    ),
                    "head": branch_name,
                    "base": "master",
                }
            )

        if pr_response.status_code in (200, 201):
            pr_data = pr_response.json()
            return {
                "status": "rollback_pr_opened",
                "strategy": "git_based",
                "application": app_name,
                "current_tag": current_tag,
                "rollback_to": previous_tag,
                "pr_number": pr_data.get("number"),
                "pr_url": pr_data.get("html_url"),
                "reason": reason,
                "message": (
                    f"PR #{pr_data.get('number')} abierto para rollback. "
                    f"Un humano debe revisar y aprobar antes de que ArgoCD ejecute el rollback. "
                    f"Usar: gh pr review {pr_data.get('number')} --approve && "
                    f"gh pr merge {pr_data.get('number')} --merge"
                ),
                "next_action": (
                    "Revisar el PR, aprobar si el rollback es correcto, "
                    "luego usar get_argocd_status para confirmar que ArgoCD sincronizó."
                )
            }

        return {
            "error": f"Error abriendo PR: HTTP {pr_response.status_code}",
            "details": pr_response.text[:300]
        }