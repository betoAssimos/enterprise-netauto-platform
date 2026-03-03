# Enterprise Network Automation Platform

End-to-End Enterprise Network Automation Platform built with:

- **Containerlab** — Lab infrastructure
- **Nautobot** — Source of Truth (API-driven)
- **Nornir + Scrapli** — Orchestration and transport
- **Jinja2** — Declarative config templates
- **pyATS / Genie** — Pre-check and post-check validation
- **GitHub Actions** — CI/CD pipeline
- **Prometheus + Grafana** — Observability and telemetry
- **Ollama (Local LLM)** — AI reasoning layer for autonomous operations

## Architecture Principles

- Declarative Desired State
- Idempotent Deployments
- Separation of Concerns
- Drift Detection
- Pre-check / Post-check / Rollback
- CI/CD Controlled Changes
- Structured Logging and Observability
- AI-Assisted Decision Making (local, air-gapped via Ollama)

## Repository Structure
```
enterprise-netauto-platform/
├── containerlab/           # Lab topology and device configs
├── automation/             # Core platform modules
│   ├── inventory/          # Nautobot-backed Nornir inventory
│   ├── templates/          # Jinja2 config templates
│   ├── tasks/              # Nornir task lifecycle (deploy)
│   ├── validators/         # pyATS/Genie pre/post checks
│   ├── drift/              # Drift detection engine
│   ├── rollback/           # Config rollback and audit
│   ├── workflows/          # Per-feature workflow modules
│   └── utils/              # Logging, helpers
├── ai/                     # AI layer — Ollama-powered agents
│   ├── agents/             # Autonomous reasoning agents
│   ├── prompts/            # Prompt templates per use case
│   ├── tools/              # Tool definitions exposed to the LLM
│   └── memory/             # Conversation and state memory
├── tests/                  # Unit, precheck, postcheck tests
├── telemetry/              # Prometheus metrics, Grafana dashboards
└── .github/workflows/      # CI/CD pipelines
```

## Layers

| Layer | Module | Description |
|-------|--------|-------------|
| 0 | Foundation | Repo structure, settings, logging |
| 1 | Inventory | Nautobot → Nornir inventory |
| 2 | Templates | Jinja2 desired state rendering |
| 3 | Deploy | Nornir task lifecycle |
| 4 | Validation | pyATS/Genie pre/post checks |
| 5 | Drift | Drift detection and reporting |
| 6 | Rollback | Config restoration and audit |
| 7 | Telemetry | Prometheus + Grafana |
| 8 | CI/CD | GitHub Actions pipeline |
| 9 | AI | Ollama agents for autonomous ops |
