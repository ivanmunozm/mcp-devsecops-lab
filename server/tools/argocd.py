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