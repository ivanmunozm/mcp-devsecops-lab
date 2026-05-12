# server/main.py
"""
MCP Server — DevSecOps Lab
Punto de entrada principal. Registra todos los módulos de tools.
"""

from mcp import FastMCP
from server.config import config
from server.tools.health import register_health_tools
from server.tools.github_actions import register_github_actions_tools

# Validar configuración en el arranque
# Si falta GITHUB_TOKEN, el servidor no arranca — mejor que fallar
# silenciosamente en el primer tools/call
config.validate()

mcp = FastMCP("devsecops-lab")

# Registrar módulos de tools
register_health_tools(mcp)
register_github_actions_tools(mcp)

if __name__ == "__main__":
    mcp.run()