# Glosario — De cero a agente: desarrolla un MCP Server para automatizar seguridad DevSecOps

> Referencia rápida de términos, herramientas y estándares usados en el laboratorio.
> Mantén este archivo abierto durante las sesiones.

---

## Protocolo y Comunicación

### MCP — Model Context Protocol
Protocolo abierto creado por Anthropic que permite a los modelos de IA conectarse con herramientas, APIs y fuentes de datos externas de forma estandarizada. Es el "lenguaje común" entre un agente de IA y el mundo exterior.

### JSON-RPC
Protocolo de comunicación que usa JSON para hacer llamadas a funciones remotas. Es el formato que usan los mensajes entre cliente y servidor MCP. Cada mensaje tiene un `method`, `params` y un `id` para rastrear la respuesta.

### stdio — Standard Input/Output
Canales de comunicación nativos de cualquier proceso Unix/Linux/Mac. En MCP, el cliente y servidor se hablan escribiendo y leyendo por estos canales, como un pipe. Es el transport más simple y el primero que usaremos en el laboratorio.

### SSE — Server-Sent Events
Protocolo HTTP donde el servidor mantiene la conexión abierta y empuja mensajes al cliente cuando quiere, sin que este los solicite. En MCP se usa como transport alternativo a stdio cuando el servidor necesita ser remoto o accesible via HTTP. Analogía: el log streaming en tiempo real de un pipeline de Jenkins.

### Transport Layer
La capa que define cómo viajan los mensajes entre cliente y servidor MCP. Las dos opciones son:
- **stdio** → proceso local, más simple, ideal para desarrollo
- **SSE** → HTTP, útil para servidores remotos o multi-cliente

---

## Primitivas MCP

### Tool
Función que el agente de IA puede invocar para hacer algo: ejecutar un comando, llamar una API, consultar una base de datos. En el laboratorio, triggerear un pipeline de GitHub Actions es una tool.

### Resource
Fuente de datos que el servidor MCP expone para que el agente la lea. A diferencia de una tool, un resource no ejecuta acciones — solo provee información. Ejemplo: el reporte SARIF generado por el pipeline.

### Prompt
Plantilla de instrucciones predefinida que el servidor MCP puede ofrecer al agente. Útil para estandarizar cómo el agente debe razonar sobre ciertos datos, como interpretar hallazgos de seguridad.

### Host
La aplicación que contiene y gestiona el agente de IA. En el laboratorio, Claude Desktop o Claude.ai es el host.

### Client
Componente dentro del host que se comunica con el servidor MCP. El host puede tener múltiples clients conectados a múltiples servers simultáneamente.

### Server
El programa que desarrollamos nosotros. Expone tools, resources y prompts que el agente puede usar. Es el núcleo de lo que construimos en el laboratorio.

---

## Seguridad — Tipos de Análisis

### SAST — Static Application Security Testing
Análisis de seguridad del código fuente sin ejecutarlo. Busca vulnerabilidades leyendo el código directamente, como un revisor humano pero automatizado. Se ejecuta temprano en el pipeline, antes del build.

### DAST — Dynamic Application Security Testing
Análisis de seguridad atacando la aplicación mientras está corriendo. Simula lo que haría un atacante real desde afuera. Requiere que la app esté desplegada y accesible.

### SCA — Software Composition Analysis
Análisis de las dependencias y librerías de terceros que usa el proyecto. Detecta si se están usando componentes con vulnerabilidades conocidas (CVEs). Complementa al SAST que analiza el código propio.

### IAST — Interactive Application Security Testing
Combinación de SAST y DAST. Instrumenta la aplicación por dentro mientras corre y observa su comportamiento en tiempo real. Más preciso pero más complejo de implementar. No se usa en este laboratorio, pero es importante conocerlo.

### CVE — Common Vulnerabilities and Exposures
Identificador estándar para vulnerabilidades de seguridad conocidas públicamente. Formato: `CVE-2024-12345`. Cada CVE tiene un score de severidad (CVSS) que va de 0 a 10.

### CVSS — Common Vulnerability Scoring System
Sistema de puntuación que mide la severidad de una vulnerabilidad del 0 al 10. Define si es Low, Medium, High o Critical. Trivy y Snyk lo usan para priorizar hallazgos.

---

## Herramientas del Laboratorio

### Semgrep
Herramienta SAST open source y multilenguaje. Analiza código buscando patrones de vulnerabilidades usando reglas escritas en YAML. Tiene un registry público con miles de reglas listas para usar. Gratuita.
- **Rol en el lab:** Stage 1 del pipeline — análisis estático del código fuente

### CodeQL
Motor de análisis estático de GitHub. Trata el código como una base de datos y permite hacer queries sobre él para encontrar vulnerabilidades. Gratuito para repos públicos, integrado nativamente en GitHub Actions.
- **Rol en el lab:** Stage 1 del pipeline — análisis estático complementario a Semgrep

### Trivy
Scanner de seguridad open source de Aqua Security. Detecta vulnerabilidades en dependencias, imágenes de contenedor, configuraciones de Kubernetes y más. Es el navaja suiza del SCA y container security.
- **Rol en el lab:** Stage 2 del pipeline — análisis de dependencias e imagen de contenedor

### OWASP ZAP — Zed Attack Proxy
Herramienta DAST open source mantenida por OWASP. Actúa como un proxy que intercepta y ataca la aplicación mientras corre. La referencia estándar para pruebas de penetración automatizadas.
- **Rol en el lab:** Stage 3 del pipeline — análisis dinámico contra la app target

### Snyk
Plataforma SCA y SAST comercial con free tier generoso. Escanea dependencias, contenedores e IaC buscando vulnerabilidades. Tiene integración nativa con GitHub.
- **Rol en el lab:** Alternativa a Trivy para SCA, según decisión durante el laboratorio

### MCP Inspector
Herramienta oficial de debugging para servidores MCP. Permite probar tools y resources de forma interactiva sin necesitar conectar Claude. Es el equivalente a Postman pero para MCP.
- **Rol en el lab:** Testing local del MCP server antes de conectarlo a Claude

---

## Formatos y Estándares

### SARIF — Static Analysis Results Interchange Format
Formato JSON estándar para reportar resultados de herramientas de análisis estático. Semgrep, CodeQL y otras herramientas lo generan. El MCP server lo parsea para extraer hallazgos relevantes y pasárselos a Claude de forma estructurada.

Estructura básica:
```json
{
  "runs": [{
    "results": [{
      "ruleId": "javascript/sql-injection",
      "message": { "text": "SQL injection vulnerability" },
      "locations": [{
        "physicalLocation": {
          "artifactLocation": { "uri": "src/db.js" },
          "region": { "startLine": 42 }
        }
      }],
      "level": "error"
    }]
  }]
}
```

### YAML
Formato de configuración legible por humanos. Es el lenguaje de los GitHub Actions workflows, Helm charts, reglas de Semgrep y casi toda la configuración DevOps moderna.

### Webhook
Mecanismo HTTP donde un servicio notifica a otro cuando ocurre un evento, haciendo un POST a una URL predefinida. GitHub Actions puede recibir webhooks para triggerear pipelines.

---

## CI/CD y Plataforma

### GitHub Actions
Plataforma de CI/CD integrada en GitHub. Ejecuta workflows definidos en YAML que se disparan por eventos (push, PR, llamada manual via API). En el laboratorio, el MCP server triggeread y consulta estos workflows.

### Workflow
Archivo YAML en `.github/workflows/` que define un pipeline de GitHub Actions. Contiene jobs, steps y las condiciones que los disparan.

### Job
Unidad de ejecución dentro de un workflow de GitHub Actions. Corre en un runner (máquina virtual). Los jobs pueden correr en paralelo o en secuencia.

### Runner
Máquina virtual que ejecuta los jobs de GitHub Actions. GitHub provee runners con Ubuntu, Windows y macOS de forma gratuita para repos públicos.

### Artifact *(GitHub Actions)*
Archivo generado durante un workflow que se puede guardar y descargar después. En el laboratorio, los reportes SARIF son artifacts que el MCP server consulta para devolver resultados a Claude.

---

## Pipeline del Laboratorio — Referencia Rápida

```
Stage 1 — SAST
  ├── Semgrep      → análisis de patrones en código fuente
  └── CodeQL       → análisis semántico integrado en GitHub

Stage 2 — SCA + Container Security
  └── Trivy        → dependencias vulnerables + imagen de contenedor

Stage 3 — DAST
  └── OWASP ZAP   → ataque dinámico contra app target en el pipeline

Stage 4 — Reporte consolidado
  └── SARIF        → formato unificado que el MCP server parsea y entrega a Claude
```

---

*Documento generado durante el laboratorio "De cero a agente: desarrolla un MCP Server para automatizar seguridad DevSecOps"*
*Repositorio: mcp-devsecops-lab*
