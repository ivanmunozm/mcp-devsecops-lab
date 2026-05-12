# server/config.py
"""
Configuración centralizada del servidor MCP.
Carga variables desde .env y las expone como un objeto tipado.
Por qué un módulo de config separado:
  - Un solo lugar para cambiar variables
  - Falla en el arranque si falta algo crítico (fail-fast)
  - Fácil de mockear en tests
"""

import os
from dotenv import load_dotenv

# Carga el .env — si no existe, usa variables del entorno del sistema
# Esto permite que en GitHub Actions las variables vengan de Secrets
# sin cambiar ningún código
load_dotenv()

class Config:
    # Token de GitHub — requerido, falla si no está
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_OWNER: str = os.getenv("GITHUB_OWNER", "")
    GITHUB_REPO: str  = os.getenv("GITHUB_REPO", "")

    # URL base de la API de GitHub — no cambia
    GITHUB_API_BASE: str = "https://api.github.com"

    # Nombre del workflow file — debe coincidir con el archivo que creamos
    WORKFLOW_FILE: str = "devsecops-pipeline.yml"

    def validate(self) -> None:
        """Valida que las variables críticas están presentes."""
        missing = []
        if not self.GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if not self.GITHUB_OWNER:
            missing.append("GITHUB_OWNER")
        if not self.GITHUB_REPO:
            missing.append("GITHUB_REPO")

        if missing:
            raise ValueError(
                f"Variables de entorno faltantes: {', '.join(missing)}\n"
                f"Verifica tu archivo .env"
            )

# Instancia global — se importa desde cualquier módulo
config = Config()