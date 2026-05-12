# server/main.py
"""
MCP Server — DevSecOps Lab
Módulo 1: Servidor mínimo con una tool de health check
"""

# FastMCP es la API de alto nivel del SDK oficial.
# Por qué FastMCP y no el Server de bajo nivel:
#   - El Server base requiere que registres handlers manualmente para cada
#     método del protocolo (tools/list, tools/call, etc.)
#   - FastMCP usa decoradores (@mcp.tool) y genera todo el boilerplate
#     del protocolo automáticamente
#   - Para producción real, FastMCP cubre el 95% de los casos
from mcp.server.fastmcp import FastMCP
from datetime import datetime
import platform
import sys

# Instancia del servidor.
# El string "devsecops-lab" es el nombre que verá el cliente MCP
# durante el handshake de inicialización.
mcp = FastMCP("devsecops-lab")


# El decorador @mcp.tool() registra esta función como una Tool MCP.
# Lo que ocurre internamente:
#   1. FastMCP inspecciona la firma de la función (type hints)
#   2. Genera automáticamente el JSON Schema del input
#   3. Registra el handler para cuando llegue un tools/call con este nombre
#   4. El docstring se convierte en la descripción que Claude ve al decidir
#      si usar esta tool o no — es crítico que sea descriptivo
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
    Lista todas las operaciones DevSecOps disponibles en este servidor.
    Usar para descubrir qué capacidades están implementadas antes de
    orquestar un pipeline completo.
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
                "status": "coming_soon",
                "description": "Triggerear pipeline SAST+SCA+DAST en GitHub Actions"
            },
            {
                "name": "get_pipeline_status",
                "status": "coming_soon",
                "description": "Consultar estado de un run en curso"
            },
            {
                "name": "get_security_report",
                "status": "coming_soon",
                "description": "Obtener hallazgos consolidados de seguridad"
            },
        ],
        "server_version": "0.1.0",
        "modules_loaded": ["health"],
    }


# El bloque de entrada.
# mcp.run() arranca el event loop y conecta el servidor al transport.
# Por defecto usa stdio — lee JSON-RPC de stdin, escribe en stdout.
# Esta es la razón por la que NO usamos if __name__ == "__main__": print()
# normal — stdout está reservado para el protocolo MCP.
if __name__ == "__main__":
    mcp.run()