"""
Microservicio mínimo para el laboratorio DevSecOps.
Simula un servicio de gestión de transacciones.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from prometheus_fastapi_instrumentator import Instrumentator
import uvicorn
import os

app = FastAPI(
    title="ms-devsecops",
    description="Microservicio de laboratorio para pipeline DevSecOps",
    version="0.1.0",
)

# Instrumentar la app con Prometheus
# Esto expone automáticamente el endpoint /metrics con:
#   - http_requests_total (counter por método, path, status)
#   - http_request_duration_seconds (histogram de latencia)
#   - http_request_size_bytes
#   - http_response_size_bytes
Instrumentator().instrument(app).expose(app)

# Modelo de datos — Pydantic valida automáticamente los tipos
class Transaction(BaseModel):
    transaction_id: str
    amount: float
    currency: str = "CLP"
    merchant_id: str

class TransactionResponse(BaseModel):
    transaction_id: str
    status: str
    timestamp: str
    environment: str

# Simulación de transacciones en memoria
# En producción real esto sería una DB
_transactions: dict = {}


@app.get("/health")
def health_check():
    """
    Endpoint de health check.
    Kubernetes lo usa para liveness y readiness probes.
    El pipeline de DAST lo verifica antes de correr ZAP.
    """
    return {
        "status": "healthy",
        "service": "ms-devsecops",
        "version": os.getenv("APP_VERSION", "0.1.0"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/transactions", response_model=TransactionResponse)
def create_transaction(transaction: Transaction):
    """
    Crea una nueva transacción.
    Endpoint de negocio que ZAP analizará en el DAST scan.
    """
    if transaction.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount debe ser positivo")

    _transactions[transaction.transaction_id] = transaction
    return TransactionResponse(
        transaction_id=transaction.transaction_id,
        status="approved",
        timestamp=datetime.utcnow().isoformat() + "Z",
        environment=os.getenv("ENVIRONMENT", "development"),
    )


@app.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: str):
    """Obtiene una transacción por ID."""
    if transaction_id not in _transactions:
        raise HTTPException(status_code=404, detail="Transacción no encontrada")
    return _transactions[transaction_id]


@app.get("/metrics")
def metrics():
    """Endpoint de métricas básicas — en producción usarías Prometheus."""
    return {
        "total_transactions": len(_transactions),
        "service": "ms-devsecops",
        "uptime_timestamp": datetime.utcnow().isoformat() + "Z",
    }


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=False,
    )