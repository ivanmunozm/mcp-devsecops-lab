# server/tools/github_actions.py
"""
Tools MCP para orquestar el pipeline DevSecOps en GitHub Actions.
Cada tool es una operación discreta que Claude puede invocar.
"""

import json
import zipfile
import io
from typing import Optional
import httpx
from mcp import FastMCP
from server.config import config


def _github_headers() -> dict:
    """
    Headers estándar para la API de GitHub.
    Por qué función separada:
      - Un solo lugar si el token o versión de API cambia
      - Más fácil de debuggear — agregamos logging aquí si hace falta
    """
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        # application/vnd.github+json es el media type recomendado por GitHub
        # Garantiza que usamos la versión estable de la API
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def register_github_actions_tools(mcp: FastMCP) -> None:
    """Registra todas las tools de GitHub Actions en la instancia MCP."""

    @mcp.tool()
    async def trigger_pipeline(
        branch: str = "main",
        scan_level: str = "quick",
    ) -> dict:
        """
        Triggerear el pipeline DevSecOps completo en GitHub Actions.
        Ejecuta SAST (Semgrep + CodeQL), SCA (Trivy) y DAST (OWASP ZAP).
        Retorna el run_id para hacer seguimiento con get_pipeline_status.

        Args:
            branch: Branch a analizar. Default: main
            scan_level: Nivel de escaneo — 'quick' (2-5 min) o 'full' (10-15 min)
        """
        # Validar inputs antes de llamar la API
        # Mejor fallar aquí con mensaje claro que recibir un 422 de GitHub
        if scan_level not in ("quick", "full"):
            return {
                "error": f"scan_level inválido: '{scan_level}'. Use 'quick' o 'full'"
            }

        url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/workflows"
            f"/{config.WORKFLOW_FILE}/dispatches"
        )

        payload = {
            # ref es el branch/tag donde se ejecuta el workflow
            "ref": branch,
            # inputs deben coincidir exactamente con los inputs
            # definidos en el workflow_dispatch del YAML
            "inputs": {
                "target_branch": branch,
                "scan_level": scan_level,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=_github_headers(),
                json=payload,
            )

        # GitHub retorna 204 No Content en éxito para workflow_dispatch
        # No hay body — el run_id lo obtenemos consultando los runs
        if response.status_code == 204:
            # Obtener el run_id del run recién creado
            # Hay una race condition pequeña aquí — el run puede tardar
            # 1-2 segundos en aparecer en la API después del dispatch
            import asyncio
            await asyncio.sleep(2)

            runs_url = (
                f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
                f"/{config.GITHUB_REPO}/actions/runs"
                f"?branch={branch}&per_page=1"
            )

            async with httpx.AsyncClient(timeout=30) as client:
                runs_response = await client.get(
                    runs_url, headers=_github_headers()
                )

            if runs_response.status_code == 200:
                runs_data = runs_response.json()
                latest_run = runs_data.get("workflow_runs", [{}])[0]
                return {
                    "status": "triggered",
                    "run_id": latest_run.get("id"),
                    "run_number": latest_run.get("run_number"),
                    "run_url": latest_run.get("html_url"),
                    "branch": branch,
                    "scan_level": scan_level,
                    "message": (
                        "Pipeline iniciado. Usa get_pipeline_status con "
                        "este run_id para hacer seguimiento."
                    ),
                }

        # Manejo de errores comunes de la API de GitHub
        error_messages = {
            401: "Token inválido o expirado — verifica GITHUB_TOKEN en .env",
            403: "Sin permisos — el token necesita scope 'workflow'",
            404: "Repo o workflow no encontrado — verifica GITHUB_OWNER, GITHUB_REPO",
            422: "Inputs inválidos — verifica que el branch existe",
        }

        return {
            "error": error_messages.get(
                response.status_code,
                f"Error inesperado: HTTP {response.status_code}"
            ),
            "details": response.text[:500],
        }


    @mcp.tool()
    async def get_pipeline_status(run_id: int) -> dict:
        """
        Consulta el estado actual de un run del pipeline DevSecOps.
        Usar periódicamente hasta que status sea 'completed'.
        El pipeline completo tarda aproximadamente 8-15 minutos.

        Args:
            run_id: ID numérico del run, obtenido de trigger_pipeline
        """
        url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=_github_headers())

        if response.status_code != 200:
            return {
                "error": f"No se pudo obtener el run {run_id}",
                "http_status": response.status_code,
            }

        run = response.json()

        # Obtener estado de cada job individual
        jobs_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}/jobs"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            jobs_response = await client.get(jobs_url, headers=_github_headers())

        jobs_summary = []
        if jobs_response.status_code == 200:
            jobs = jobs_response.json().get("jobs", [])
            for job in jobs:
                jobs_summary.append({
                    "name": job.get("name"),
                    # status: queued | in_progress | completed
                    "status": job.get("status"),
                    # conclusion: success | failure | skipped | cancelled
                    "conclusion": job.get("conclusion"),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                })

        # status global del run
        overall_status = run.get("status")
        conclusion = run.get("conclusion")

        result = {
            "run_id": run_id,
            "status": overall_status,
            "conclusion": conclusion,
            "run_url": run.get("html_url"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "jobs": jobs_summary,
        }

        # Agregar mensaje de contexto para que Claude sepa qué hacer
        if overall_status == "completed":
            if conclusion == "success":
                result["next_action"] = (
                    "Pipeline completado exitosamente. "
                    "Usa get_security_report para obtener los hallazgos."
                )
            else:
                result["next_action"] = (
                    f"Pipeline terminó con conclusión '{conclusion}'. "
                    "Revisa los jobs fallidos arriba."
                )
        else:
            result["next_action"] = (
                f"Pipeline en curso (status: {overall_status}). "
                "Consulta nuevamente en 60 segundos."
            )

        return result


    @mcp.tool()
    async def get_security_report(run_id: int) -> dict:
        """
        Descarga y retorna el reporte consolidado de seguridad de un run completado.
        Incluye hallazgos de SAST, SCA y DAST con severidad y descripción.
        Solo disponible cuando get_pipeline_status retorna status 'completed'.

        Args:
            run_id: ID numérico del run completado
        """
        # Primero verificar que el run está completado
        status_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            status_response = await client.get(
                status_url, headers=_github_headers()
            )

        if status_response.status_code == 200:
            run_data = status_response.json()
            if run_data.get("status") != "completed":
                return {
                    "error": "El pipeline aún no ha terminado",
                    "current_status": run_data.get("status"),
                    "suggestion": "Usa get_pipeline_status para hacer seguimiento",
                }

        # Obtener lista de artefactos del run
        artifacts_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}/artifacts"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            artifacts_response = await client.get(
                artifacts_url, headers=_github_headers()
            )

        if artifacts_response.status_code != 200:
            return {"error": "No se pudieron obtener los artefactos del run"}

        artifacts = artifacts_response.json().get("artifacts", [])

        # Buscar el artefacto security-report específicamente
        security_artifact = next(
            (a for a in artifacts if a.get("name") == "security-report"),
            None,
        )

        if not security_artifact:
            return {
                "error": "Artefacto 'security-report' no encontrado",
                "available_artifacts": [a.get("name") for a in artifacts],
            }

        # Descargar el artefacto — GitHub retorna un ZIP
        download_url = security_artifact.get("archive_download_url")

        async with httpx.AsyncClient(
            timeout=60,
            # Seguir redirects — GitHub redirige a S3 para la descarga
            follow_redirects=True,
        ) as client:
            download_response = await client.get(
                download_url, headers=_github_headers()
            )

        if download_response.status_code != 200:
            return {
                "error": f"Error descargando artefacto: HTTP {download_response.status_code}"
            }

        # Descomprimir el ZIP en memoria — no escribimos al disco
        # El artefacto contiene security-report.json
        try:
            zip_buffer = io.BytesIO(download_response.content)
            with zipfile.ZipFile(zip_buffer) as zf:
                # Leer el JSON directo del ZIP
                with zf.open("security-report.json") as report_file:
                    report_data = json.load(report_file)

            return {
                "status": "ok",
                "report": report_data,
                "artifact_size_bytes": security_artifact.get("size_in_bytes"),
            }

        except Exception as e:
            return {
                "error": f"Error procesando el artefacto: {str(e)}",
                "artifact_name": security_artifact.get("name"),
            }