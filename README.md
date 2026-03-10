# Enterprise Network Automation Platform

A lab project simulating how a real organization could manage network infrastructure
using modern automation tools. Built for learning, certification prep (CCNP AUTOCOR),
and portfolio purposes.

Stack:

- **Containerlab** — lab topology running Cisco IOSv routers, Arista cEOS switches and Linux hosts
- **NetBox** — source of truth for device inventory, IP management and BGP data
- **Nornir + Scrapli** — automation engine and SSH transport for device config
- **RESTCONF** — API-based configuration for IOS XE using YANG models
- **Jinja2** — config templates so I'm not hardcoding anything
- **pyATS / Genie** — validation tests before and after config changes
- **Prometheus + Grafana + SNMP + gNMI** — telemetry and monitoring
- **GitLab CI/CD** — pipeline that runs everything automatically (GitHub is just a mirror)

---

## Project Status

> Updated at the end of each working session.

| Layer | Component | Status | Notes |
|-------|-----------|--------|-------|
| 0 | Repo structure, settings, logging | ✅ Complete | `load_dotenv`, modular layout |
| 1 | NetBox inventory → Nornir | ✅ Complete | Dynamic inventory pulled from NetBox API |
| 2 | Jinja2 config templates | ✅ Complete | BGP + interface templates |
| 3 | Scrapli transport (CLI) | ✅ Complete | SSH config deployment |
| 3 | RESTCONF transport | ✅ Complete | IOS XE YANG over HTTPS/JSON |
| 4 | BGP workflow deployment | ✅ Complete | eBGP + redistribute connected on both routers |
| 5 | pyATS precheck | ✅ Complete | Neighbors, sessions, prefix count |
| 5 | pyATS postcheck | ✅ Complete | Neighbor state, AS integrity |
| 6 | Drift detection | ✅ Complete | DeepDiff-based engine |
| 7 | Rollback | ✅ Complete | Config restoration module |
| 8 | Prometheus + Grafana | ✅ Complete | Telemetry stack running |
| 8 | SNMP exporter | ✅ Complete | Scraping rtr-01 and rtr-02 |
| 8 | gNMI | ✅ Complete | gnmic collector configured |
| 9 | GitLab CI/CD | ⚠️ Partial | 5/6 jobs pass |
| 10 | NAPALM transport | 🔜 Next | Multi-vendor abstraction layer |
| 10 | SuzieQ | 🔜 Next | Network state observability |
| 11 | Lab topology v2 | 📋 Planned | 3-tier WAN topology with iBGP |
| 12 | Topology discovery | 📋 Planned | LLDP/BGP discovery automation tasks |
| 12 | AI incident analysis | 📋 Planned | Topology-aware AI reasoning layer |
| 13 | Ansible integration | 📋 Planned | System-level and cross-platform tasks |
| 13 | Terraform integration | 📋 Planned | Infrastructure provisioning |
| 14 | Batfish | 🔮 Future | Config verification before deployment |
| 14 | HashiCorp Vault | 🔮 Future | Proper secrets management |
| 14 | Neo4j topology engine | 🔮 Future | Graph DB for dependency mapping |
| 14 | Ollama (local LLM) | 🔮 Future | Local AI reasoning agent |
| 14 | netclaw | 🔮 Future | Network-aware AI tooling |

**Legend:** ✅ Complete · ⚠️ Partial · 🔜 Next · 📋 Planned · 🔮 Future

---

## Architecture Principles

Things I'm trying to keep consistent throughout the project:

- Config is generated from templates, never hardcoded
- Automation tasks are safe to run more than once (idempotent)
- NetBox is the only source of truth — nothing is defined in two places
- Every deployment runs validation before and after
- Failures can be rolled back
- Everything goes through the CI/CD pipeline, not run manually in production
- Logs exist for every meaningful action

---

## Repository Structure

```
enterprise-netauto-platform/
├── containerlab/                   # Lab topology and device configs
│   ├── topology.yml                # Containerlab topology definition
│   └── configs/                    # Per-device startup configs
├── automation/                     # Core automation modules
│   ├── config.py                   # Settings and environment variables
│   ├── inventory/                  # NetBox-backed Nornir inventory
│   ├── templates/                  # Jinja2 config templates
│   │   └── definitions/
│   │       ├── bgp/                # BGP neighbor templates
│   │       └── interfaces/         # Interface config templates
│   ├── transports/                 # How we talk to devices
│   │   └── restconf.py             # RESTCONF for IOS XE
│   ├── tasks/                      # Low-level Nornir task functions
│   ├── workflows/                  # Per-feature workflow orchestration
│   ├── validators/                 # State validation checks
│   ├── drift/                      # Drift detection (DeepDiff)
│   ├── rollback/                   # Config rollback
│   └── utils/                      # Logging and helpers
├── tests/                          # pyATS validation test suites
│   ├── testbed.yaml                # Device connection definitions for pyATS
│   ├── precheck/                   # Tests that run before a change
│   └── postcheck/                  # Tests that run after a change
├── telemetry/                      # Monitoring stack
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   ├── snmp.yml
│   └── gnmic.yml
├── netbox-docker/                  # NetBox running in Docker
├── ai/                             # AI layer (not built yet)
│   ├── agents/
│   ├── prompts/
│   ├── tools/
│   └── memory/
├── docs/                           # Notes, roadmap, architecture docs
└── .gitlab-ci.yml                  # CI/CD pipeline
```

---

## Lab Topology — Current (v1)

```
rtr-01 (AS65001, IOS XE) ──eBGP── rtr-02 (AS65002, IOS XE)
        │                                   │
   arista-01 (cEOS)                   arista-02 (cEOS)
        │                                   │
     host-01                            host-02
```

eBGP between AS65001 and AS65002 over Loopback0. Both routers redistributing connected
routes. Verified: rtr-01 receiving 3 prefixes from rtr-02. Redistribution deployed via
RESTCONF.

---

## Lab Topology — Planned (v2)

3-tier WAN/enterprise design adding iBGP and route reflectors. Required for realistic
failure propagation testing and the AI incident analysis layer.

```
                 ┌─────────────────────────────────┐
                 │          WAN / Edge Tier          │
                 │                                   │
            rtr-01 (AS65001) ──eBGP── rtr-02 (AS65002)
                 │                           │
                 └──────────┬────────────────┘
                            │
                 ┌──────────▼────────────────────────┐
                 │      Core Tier (iBGP / RR)         │
                 │                                   │
            rtr-03 (AS65001) ────── rtr-04 (AS65001)
                 │                           │
                 └──────────┬────────────────┘
                            │
                 ┌──────────▼────────────────────────┐
                 │         Access / ToR               │
                 │                                   │
            arista-01                           arista-02
                 │                                   │
             host-01                             host-02
```

See `docs/automation_feature_roadmap.md`.

---

## Transport Layer

Three ways the platform talks to devices, each serving a different purpose:

**Scrapli** — SSH into the device and send CLI commands. Used for Arista cEOS and
anywhere RESTCONF is not available.

**RESTCONF** — HTTP API using YANG data models. Used on IOS XE to push config
programmatically without screen-scraping CLI. Implemented in
`automation/transports/restconf.py`.

**NAPALM** *(planned)* — sits on top of the other transports and gives a single API
that works across vendors. The idea is to stop writing `if iosxe... elif eos...` blocks
in the workflow code.

---

## Validation

Two test suites run against the devices using pyATS:

- **precheck** — runs before any change. Checks that BGP neighbors exist, sessions are
  established, and prefixes are being exchanged
- **postcheck** — runs after deployment. Confirms neighbor state and AS numbers are still correct

```bash
pyats run job tests/precheck/test_bgp.py --testbed tests/testbed.yaml
pyats run job tests/postcheck/test_bgp.py --testbed tests/testbed.yaml
```

---

## CI/CD Pipeline

Runs on GitLab CI/CD on every push. GitHub is kept in sync as a mirror.

The pipeline runs these steps in order:

1. **Check YAML and Python syntax** — makes sure nothing is broken before wasting time running anything
2. **Generate inventory from NetBox** — pulls current device data
3. **Run precheck tests** — validates current state before touching devices
4. **Deploy configuration** — runs the Nornir workflows
5. **Run postcheck tests** — confirms nothing broke after deployment
6. **Telemetry health check** — verifies the monitoring stack is still collecting

---

## Tool Decisions

Notes on why I chose specific tools so I don't have to think through this again.

### Nornir vs Ansible vs Terraform

These work at different layers and are not competing with each other.

| Tool | What it does here |
|------|-------------------|
| **Nornir** | Core automation engine — handles device config, inventory, templates, drift detection, and eventually the AI layer. All in Python. |
| **Ansible** | Planned for system-level tasks — setting up Linux hosts, cross-platform orchestration, anything that crosses the network/OS boundary |
| **Terraform** | Planned for provisioning the infrastructure the lab runs on — Docker hosts, environment setup, possibly a cloud extension later |

Nornir is the right choice for network devices here because everything else in the stack
(pyATS, NetBox API, RESTCONF, future AI layer) is Python. Ansible fits better at the
system layer where the logic is simpler and the module library covers more ground.

---

## Future Work

### Next up: NAPALM + SuzieQ

**NAPALM** — adds vendor abstraction to the transport layer. Write workflows once,
run them on IOS, EOS, or JunOS without changing the logic.

**SuzieQ** — network state engine. Lets me query BGP state, topology, and interface
status across all devices without SSHing into each one. Also a stepping stone toward
the AI topology layer.

### AI Incident Analysis

Alerts alone aren't enough for root cause analysis — topology context is required.
A BGP-down alert is meaningless without knowing what depends on that router. The
planned architecture:

```
Network Devices
      │
      ▼
Topology Discovery        ← collect LLDP, BGP peers, interface state via Nornir
      │
      ▼
Topology Builder          ← turn that data into structured device relationships
      │
      ▼
Topology Store            ← store in NetBox as cable/connection objects
      │
      ▼
Topology Query API        ← FastAPI — GET /topology/device/{device}
      │
      ▼
Incident Context Builder  ← combine alert + neighbors + services + recent changes
      │
      ▼
AI Reasoning Engine       ← feed context to LLM, get root cause and next steps
```

Local LLM via **Ollama** (air-gapped, no external API calls). **netclaw** for
network-specific tooling exposed to the agent. Long-term: swap NetBox topology store
for **Neo4j** when graph queries get complex enough to need a real graph database.

### Ansible and Terraform

Ansible for host-level setup and cross-platform tasks. Terraform for provisioning the
lab infrastructure itself, with a possible cloud extension later. Both planned once the
core network automation layer is stable.

### On the radar

- **Batfish** — analyze config files offline and catch routing mistakes before deploying
- **HashiCorp Vault** — replace the `.env` credential setup with proper secrets management
- **Neo4j** — graph database for topology if NetBox becomes a bottleneck for relationship queries

---

## Environment

- WSL Ubuntu 24.04
- Python 3.12 (venv at `./venv`)
- Docker with Compose v2
- Containerlab

---

## Getting Started

```bash
git clone https://github.com/betoAssimos/enterprise-netauto-platform
cd enterprise-netauto-platform
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env with your NetBox token and device credentials

# start NetBox
cd netbox-docker && docker compose up -d

# start telemetry stack
cd telemetry && docker compose up -d

# deploy lab topology
cd containerlab && sudo containerlab deploy -t topology.yml

# run validation
pyats run job tests/precheck/test_bgp.py --testbed tests/testbed.yaml
```