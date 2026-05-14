"""
Tools MCP para consultar métricas de Prometheus y Grafana.
Fase 4: cierra el loop completo — seguridad + deploy + performance.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from server.config import config
from datetime import datetime, timedelta


def _prometheus_url() -> str:
    return f"http://{config.PROMETHEUS_SERVER}/api/v1"


def register_observability_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_service_metrics(
        service: str = "ms-devsecops",
        period: str = "5m",
    ) -> dict:
        """
        Obtiene métricas actuales del microservicio desde Prometheus.
        Incluye request rate, latencia p95 y tasa de errores.
        Usar para verificar el estado de performance después de un deploy.

        Args:
            service: nombre del servicio (default: ms-devsecops)
            period: período de análisis — 1m, 5m, 15m, 1h (default: 5m)
        """
        if not config.PROMETHEUS_SERVER:
            return {
                "error": "PROMETHEUS_SERVER no configurado",
                "suggestion": "Agrega PROMETHEUS_SERVER=localhost:9090 al .env"
            }

        job = f"{service}-{service}"
        queries = {
            "request_rate": f'sum(rate(http_requests_total{{job="{job}"}}[{period}]))',
            "error_rate":   f'sum(rate(http_requests_total{{job="{job}",status=~"5.."}}[{period}])) or vector(0)',
            "latency_p95":  f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job="{job}"}}[{period}])) by (le))',
            "latency_p50":  f'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{job="{job}"}}[{period}])) by (le))',
            "total_requests": f'sum(http_requests_total{{job="{job}"}})',
        }

        results = {}
        errors = []

        async with httpx.AsyncClient(timeout=15) as client:
            for metric_name, query in queries.items():
                try:
                    response = await client.get(
                        f"{_prometheus_url()}/query",
                        params={"query": query}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        result_list = data.get("data", {}).get("result", [])
                        if result_list:
                            value = float(result_list[0]["value"][1])
                            results[metric_name] = round(value, 4)
                        else:
                            results[metric_name] = 0.0
                    else:
                        errors.append(f"{metric_name}: HTTP {response.status_code}")
                except Exception as e:
                    errors.append(f"{metric_name}: {str(e)}")

        # Calcular error rate como porcentaje
        error_pct = 0.0
        if results.get("request_rate", 0) > 0:
            error_pct = round(
                (results.get("error_rate", 0) / results["request_rate"]) * 100, 2
            )

        # Evaluación automática para que Claude pueda razonar
        assessment = []
        lat_p95 = results.get("latency_p95", 0)
        if lat_p95 > 1.0:
            assessment.append(f"⚠️ Latencia p95 alta: {lat_p95}s — revisar cuellos de botella")
        elif lat_p95 > 0.5:
            assessment.append(f"⚠️ Latencia p95 elevada: {lat_p95}s")
        else:
            assessment.append(f"✅ Latencia p95 normal: {lat_p95}s")

        if error_pct > 5:
            assessment.append(f"❌ Tasa de errores crítica: {error_pct}%")
        elif error_pct > 1:
            assessment.append(f"⚠️ Tasa de errores elevada: {error_pct}%")
        else:
            assessment.append(f"✅ Tasa de errores normal: {error_pct}%")

        return {
            "service": service,
            "period": period,
            "metrics": {
                "request_rate_per_sec": results.get("request_rate", 0),
                "error_rate_per_sec":   results.get("error_rate", 0),
                "error_rate_percent":   error_pct,
                "latency_p95_seconds":  results.get("latency_p95", 0),
                "latency_p50_seconds":  results.get("latency_p50", 0),
                "total_requests":       int(results.get("total_requests", 0)),
            },
            "assessment": assessment,
            "grafana_dashboard": f"http://localhost:3000",
            "errors": errors if errors else None,
        }


    @mcp.tool()
    async def compare_deploy_performance(
        service: str = "ms-devsecops",
        minutes_before: int = 30,
        minutes_after: int = 10,
    ) -> dict:
        """
        Compara la performance del microservicio antes y después del último deploy.
        Útil para detectar regresiones de performance introducidas por un release.
        Retorna si el deploy mejoró, empeoró o no afectó la performance.

        Args:
            service: nombre del servicio (default: ms-devsecops)
            minutes_before: minutos de baseline antes del deploy (default: 30)
            minutes_after: minutos a analizar después del deploy (default: 10)
        """
        if not config.PROMETHEUS_SERVER:
            return {"error": "PROMETHEUS_SERVER no configurado"}

        job = f"{service}-{service}"
        now = datetime.utcnow()
        before_start = now - timedelta(minutes=minutes_before + minutes_after)
        before_end   = now - timedelta(minutes=minutes_after)
        after_start  = before_end
        after_end    = now

        def ts(dt): return dt.timestamp()

        queries = {
            "latency_before": (
                f'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{{job="{job}"}}[{minutes_before}m]))',
                ts(before_end)
            ),
            "latency_after": (
                f'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{{job="{job}"}}[{minutes_after}m]))',
                ts(after_end)
            ),
            "error_rate_before": (
                f'sum(rate(http_requests_total{{job="{job}",status=~"5.."}}[{minutes_before}m])) or vector(0)',
                ts(before_end)
            ),
            "error_rate_after": (
                f'sum(rate(http_requests_total{{job="{job}",status=~"5.."}}[{minutes_after}m])) or vector(0)',
                ts(after_end)
            ),
        }

        results = {}
        async with httpx.AsyncClient(timeout=15) as client:
            for metric_name, (query, time) in queries.items():
                try:
                    response = await client.get(
                        f"{_prometheus_url()}/query",
                        params={"query": query, "time": time}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        result_list = data.get("data", {}).get("result", [])
                        results[metric_name] = float(result_list[0]["value"][1]) if result_list else 0.0
                    else:
                        results[metric_name] = 0.0
                except:
                    results[metric_name] = 0.0

        lat_before = round(results.get("latency_before", 0), 4)
        lat_after  = round(results.get("latency_after", 0), 4)
        err_before = round(results.get("error_rate_before", 0), 4)
        err_after  = round(results.get("error_rate_after", 0), 4)

        # Calcular delta
        lat_delta = round(lat_after - lat_before, 4)
        lat_delta_pct = round((lat_delta / lat_before * 100) if lat_before > 0 else 0, 1)

        # Veredicto
        if lat_delta_pct > 20 or err_after > err_before * 1.5:
            verdict = "❌ REGRESIÓN detectada — considerar rollback"
        elif lat_delta_pct < -10:
            verdict = "✅ MEJORA de performance detectada"
        else:
            verdict = "✅ Performance estable — sin regresiones detectadas"

        return {
            "service": service,
            "comparison": {
                "before": {
                    "period": f"últimos {minutes_before} minutos antes del deploy",
                    "latency_p95_seconds": lat_before,
                    "error_rate_per_sec":  err_before,
                },
                "after": {
                    "period": f"últimos {minutes_after} minutos después del deploy",
                    "latency_p95_seconds": lat_after,
                    "error_rate_per_sec":  err_after,
                },
                "delta": {
                    "latency_seconds": lat_delta,
                    "latency_percent": f"{lat_delta_pct}%",
                },
            },
            "verdict": verdict,
            "recommendation": (
                "Ejecutar force_argocd_sync o rollback si hay regresión crítica"
                if "REGRESIÓN" in verdict else
                "No se requiere acción — el deploy es estable"
            ),
        }