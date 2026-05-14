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
load_dotenv(override=False)

class Config:
    # GitHub
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_OWNER: str = os.getenv("GITHUB_OWNER", "")
    GITHUB_REPO:  str = os.getenv("GITHUB_REPO", "")
    GITHUB_API_BASE: str = "https://api.github.com"
    WORKFLOW_FILE: str = "devsecops-pipeline.yml"

    # ArgoCD — Fase 3
    ARGOCD_SERVER:   str  = os.getenv("ARGOCD_SERVER", "localhost:8080")
    ARGOCD_TOKEN:    str  = os.getenv("ARGOCD_TOKEN", "")
    ARGOCD_INSECURE: bool = os.getenv("ARGOCD_INSECURE", "true").lower() == "true"

    def validate(self) -> None:
        missing = []
        for key in ["GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"]:
            if not getattr(self, key):
                missing.append(key)
        if missing:
            raise ValueError(f"Variables de entorno faltantes: {', '.join(missing)}")
        if not self.ARGOCD_TOKEN:
            print("⚠️  ARGOCD_TOKEN no configurado — get_argocd_status no funcionará")

config = Config()