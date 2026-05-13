# server/tools/microservice.py
"""
Tools MCP para orquestar el ciclo de vida completo del microservicio.
Fase 2: build → security scan → GitOps → estado del release.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from server.config import config


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def register_microservice_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def trigger_microservice_pipeline(
        microservice: str = "ms-devsecops",
        branch: str = "master",
    ) -> dict:
        """
        Triggerea el pipeline CI completo del microservicio:
        build de imagen Docker, push a GHCR, security scan completo
        (SAST + SCA + DAST) y actualización GitOps si pasa el security gate.
        Retorna el run_id para hacer seguimiento con get_deployment_status.

        Args:
            microservice: nombre del microservicio (default: ms-devsecops)
            branch: branch a buildear y escanear (default: master)
        """
        # El CI del microservicio vive en el mismo repo en el laboratorio
        # En producción apuntaría al repo del microservicio específico
        url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/workflows"
            f"/microservice-ci.yml/dispatches"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=_github_headers(),
                json={"ref": branch},
            )

        if response.status_code == 204:
            import asyncio
            await asyncio.sleep(2)

            # Obtener el run recién creado
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
                    "microservice": microservice,
                    "run_id": latest_run.get("id"),
                    "run_number": latest_run.get("run_number"),
                    "run_url": latest_run.get("html_url"),
                    "branch": branch,
                    "pipeline_stages": [
                        "1. Build & Push imagen → GHCR",
                        "2. Security Scan → SAST + SCA + DAST",
                        "3. GitOps → actualiza values.yaml si pasa el gate",
                    ],
                    "message": (
                        "Pipeline iniciado. Usa get_deployment_status con "
                        "este run_id para hacer seguimiento del release completo."
                    ),
                }

        error_messages = {
            401: "Token inválido — verifica GITHUB_TOKEN",
            403: "Sin permisos — el token necesita scope 'workflow'",
            404: "Workflow microservice-ci.yml no encontrado",
            422: f"Branch '{branch}' no existe en el repo",
        }

        return {
            "error": error_messages.get(
                response.status_code,
                f"Error inesperado: HTTP {response.status_code}"
            ),
            "details": response.text[:300],
        }


    @mcp.tool()
    async def get_deployment_status(run_id: int) -> dict:
        """
        Consulta el estado completo de un release del microservicio.
        Muestra el estado de cada etapa: build, security scan y GitOps.
        Indica si el security gate pasó y si el values.yaml fue actualizado.
        Usar periódicamente hasta que todos los jobs estén completados.

        Args:
            run_id: ID del run obtenido de trigger_microservice_pipeline
        """
        url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=_github_headers())

        if response.status_code != 200:
            return {
                "error": f"Run {run_id} no encontrado",
                "http_status": response.status_code,
            }

        run = response.json()

        # Obtener jobs del run
        jobs_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}/jobs"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            jobs_response = await client.get(
                jobs_url, headers=_github_headers()
            )

        # Mapear jobs a etapas del release
        stages = {
            "build": None,
            "security_scan": None,
            "gitops": None,
        }

        jobs_detail = []
        if jobs_response.status_code == 200:
            for job in jobs_response.json().get("jobs", []):
                name = job.get("name", "")
                info = {
                    "name": name,
                    "status": job.get("status"),
                    "conclusion": job.get("conclusion"),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                }
                jobs_detail.append(info)

                # Clasificar el job en su etapa
                if "Build" in name:
                    stages["build"] = info
                elif "Security" in name or "Stage" in name:
                    stages["security_scan"] = info
                elif "GitOps" in name or "Deploy" in name:
                    stages["gitops"] = info

        overall_status = run.get("status")
        conclusion = run.get("conclusion")

        # Determinar el estado del security gate
        security_passed = None
        if stages["gitops"]:
            # Si el job de GitOps corrió, el security gate pasó
            security_passed = stages["gitops"].get("conclusion") != "skipped"
        elif stages["security_scan"] and stages["security_scan"].get("status") == "completed":
            security_passed = stages["security_scan"].get("conclusion") == "success"

        result = {
            "run_id": run_id,
            "overall_status": overall_status,
            "conclusion": conclusion,
            "run_url": run.get("html_url"),
            "stages": {
                "build": {
                    "status": stages["build"].get("conclusion") if stages["build"] else "pending",
                    "description": "Build Docker image + push to GHCR",
                },
                "security_scan": {
                    "status": stages["security_scan"].get("conclusion") if stages["security_scan"] else "pending",
                    "description": "SAST + SCA (Trivy imagen real) + DAST",
                },
                "gitops_update": {
                    "status": stages["gitops"].get("conclusion") if stages["gitops"] else "pending",
                    "description": "Actualización values.yaml con nuevo SHA",
                },
            },
            "security_gate_passed": security_passed,
            "jobs": jobs_detail,
        }

        # Guiar a Claude sobre qué hacer a continuación
        if overall_status == "completed":
            if conclusion == "success":
                result["next_action"] = (
                    "Release completado exitosamente. "
                    "Usa get_release_summary para obtener el reporte "
                    "consolidado de seguridad y estado del despliegue."
                )
            else:
                result["next_action"] = (
                    f"Release terminó con conclusión '{conclusion}'. "
                    "Revisa los stages fallidos. Si falló el security gate, "
                    "el microservicio NO fue desplegado."
                )
        else:
            result["next_action"] = (
                f"Release en curso (status: {overall_status}). "
                "El pipeline completo tarda ~3-4 minutos. "
                "Consulta nuevamente en 60 segundos."
            )

        return result


    @mcp.tool()
    async def get_release_summary(run_id: int) -> dict:
        """
        Obtiene el resumen completo de un release: hallazgos de seguridad,
        estado del security gate, imagen desplegada y tag en values.yaml.
        Solo disponible cuando get_deployment_status retorna status 'completed'.
        Usar para reportar el estado final de un release a stakeholders.

        Args:
            run_id: ID del run completado
        """
        import json, zipfile, io

        # 1. Verificar que el run está completado
        run_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            run_response = await client.get(run_url, headers=_github_headers())

        if run_response.status_code != 200:
            return {"error": f"Run {run_id} no encontrado"}

        run_data = run_response.json()
        if run_data.get("status") != "completed":
            return {
                "error": "El release aún no ha terminado",
                "current_status": run_data.get("status"),
                "suggestion": "Usa get_deployment_status para hacer seguimiento",
            }

        # 2. Obtener el reporte de seguridad del artefacto
        artifacts_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/actions/runs/{run_id}/artifacts"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            artifacts_response = await client.get(
                artifacts_url, headers=_github_headers()
            )

        security_report = None
        if artifacts_response.status_code == 200:
            artifacts = artifacts_response.json().get("artifacts", [])
            security_artifact = next(
                (a for a in artifacts if a.get("name") == "security-report"),
                None,
            )

            if security_artifact:
                download_url = security_artifact.get("archive_download_url")
                async with httpx.AsyncClient(
                    timeout=60,
                    follow_redirects=True,
                ) as client:
                    download_response = await client.get(
                        download_url, headers=_github_headers()
                    )

                if download_response.status_code == 200:
                    try:
                        zip_buffer = io.BytesIO(download_response.content)
                        with zipfile.ZipFile(zip_buffer) as zf:
                            with zf.open("security-report.json") as f:
                                security_report = json.load(f)
                    except Exception as e:
                        security_report = {"parse_error": str(e)}

        # 3. Leer el values.yaml actual para saber qué tag fue desplegado
        values_url = (
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_OWNER}"
            f"/{config.GITHUB_REPO}/contents/microservice/helm/ms-devsecops/values.yaml"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            values_response = await client.get(
                values_url, headers=_github_headers()
            )

        deployed_tag = "unknown"
        if values_response.status_code == 200:
            import base64
            content = base64.b64decode(
                values_response.json().get("content", "")
            ).decode("utf-8")
            # Extraer el tag del values.yaml
            for line in content.split("\n"):
                if "tag:" in line:
                    deployed_tag = line.split("tag:")[-1].strip().strip('"')
                    break

        # 4. Construir el resumen consolidado
        summary = {
            "release": {
                "run_id": run_id,
                "run_url": run_data.get("html_url"),
                "conclusion": run_data.get("conclusion"),
                "microservice": "ms-devsecops",
                "deployed_image": f"ghcr.io/{config.GITHUB_OWNER}/ms-devsecops:{deployed_tag}",
                "deployed_tag": deployed_tag,
                "timestamp": run_data.get("updated_at"),
            },
            "security": {
                "gate_passed": run_data.get("conclusion") == "success",
                "report": security_report.get("summary") if security_report else None,
                "findings_detail": security_report.get("findings") if security_report else None,
            },
            "gitops": {
                "values_updated": deployed_tag != "unknown",
                "current_tag": deployed_tag,
                "registry": f"ghcr.io/{config.GITHUB_OWNER}/ms-devsecops",
            },
        }

        # Agregar evaluación para que Claude pueda razonar
        if summary["security"]["report"]:
            total = summary["security"]["report"].get("total_findings", 0)
            critical = summary["security"]["report"].get("critical", 0)
            summary["security"]["assessment"] = (
                f"{total} hallazgos totales, {critical} críticos. "
                + ("✅ Apto para producción." if critical == 0
                   else f"❌ {critical} hallazgos críticos requieren remediación antes de producción.")
            )

        return summary