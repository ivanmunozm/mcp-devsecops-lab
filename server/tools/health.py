# server/tools/health.py
"""Tools de health check y discovery del servidor."""

from mcp import FastMCP
from datetime import datetime
import platform
import sys

def register_health_tools(mcp: FastMCP) -> None:
    """
    Registra las tools de health en la instancia MCP.
    Por qué función en vez de decorador directo:
      - Permite que main.py controle qué tools se registran
      - Facilita agregar/quitar módulos sin tocar el core
    """

    @mcp.tool()
    def health_check() -> dict:
        """
        Verifica que el servidor MCP está operativo.
        Retorna información básica del sistema y timestamp.
        Usar para confirmar conectividad antes de operaciones de pipeline.
        """
        return {
            "status": "ok",
            "server": "devsecops-lab",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "python_version": sys.version,
            "platform": platform.system(),
        }

    @mcp.tool()
    def list_available_operations() -> dict:
        """
        Lista todas las operaciones DevSecOps disponibles.
        Usar para descubrir capacidades antes de orquestar un pipeline.
        """
        return {
            "operations": [
                {
                    "name": "health_check",
                    "status": "implemented",
                    "description": "Verifica conectividad del servidor"
                },
                {
                    "name": "trigger_pipeline",
                    "status": "implemented",
                    "description": "Triggerear pipeline SAST+SCA+DAST en GitHub Actions"
                },
                {
                    "name": "get_pipeline_status",
                    "status": "implemented",
                    "description": "Consultar estado de un run en curso"
                },
                {
                    "name": "get_security_report",
                    "status": "implemented",
                    "description": "Obtener hallazgos consolidados de seguridad"
                },
            ],
            "server_version": "0.2.0",
        }