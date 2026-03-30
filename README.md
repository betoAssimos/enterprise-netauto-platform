# Enterprise Network Automation Platform

A production-grade network automation platform built for learning, certification prep
(CCNP AUTOCOR 350-901), and portfolio purposes. Simulates how a real organization manages
enterprise network infrastructure using modern automation tools and practices.

---

## Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Lab simulation | Containerlab | Orchestrates multi-vendor virtual network |
| Source of truth | NetBox v4.5.4 | Device inventory, IPAM, automation data |
| Automation engine | Nornir + Scrapli | SSH-based config deployment and validation |
| Config rendering | Jinja2 | Vendor-specific templates, no hardcoded config |
| Validation | pyATS / Genie | Pre/post deployment state verification |
| Drift detection | DeepDiff | Intended vs actual config comparison |
| Rollback | Custom (rollback.py) | Automatic config restoration on failure |
| Telemetry | Prometheus + Grafana | Metrics and dashboards |
| Observability | SNMP + gNMI (gnmic) | Device metrics collection |
| CI/CD | GitLab pipeline | Automated validation and deployment |
| AI layer | FastMCP + LangChain + Ollama | Planned — network operations agent |

---

## Project Status

> Updated at the end of each working session.

| Layer | Component | Status | Notes |
|-------|-----------|--------|-------|
| 0 | Repo structure, settings, logging | ✅ Complete | Domain-based layout, structlog |
| 1 | NetBox source of truth | ✅ Complete | hosts.yaml as static SoT, NetBox as reference |
| 2 | Jinja2 config templates | ✅ Complete | Multi-vendor templates per domain |
| 3 | Scrapli transport | ✅ Complete | SSH deployment for Cisco IOS XE + Arista EOS |
| 3 | RESTCONF transport | ✅ Complete | IOS XE YANG/JSON over HTTPS |
| 4 | Interface deployment | ✅ Complete | Multi-platform: IOS XE + EOS (L3 + SVIs) |
| 4 | OSPF deployment | ✅ Complete | Area 0 — edge routers + core switches |
| 4 | BGP deployment | ✅ Complete | eBGP AS65001 ↔ AS65002 |
| 4 | NAT deployment | ✅ Complete | PAT overload on edge WAN interfaces |
| 4 | VLAN deployment | ✅ Complete | VLANs 10/20/99/4094 on all Arista switches |
| 4 | Port-channel deployment | ✅ Complete | MLAG peer-link + member + access uplinks |
| 4 | MLAG deployment | ✅ Complete | core-sw-01/02 Active/Connected |
| 4 | VRRP deployment | ✅ Complete | VIPs 10.10.10.1, 10.20.20.1, 10.99.99.1 |
| 5 | pyATS pre/post checks | ✅ Complete | BGP state validation |
| 6 | Drift detection | ✅ Complete | DeepDiff engine |
| 7 | Rollback | ✅ Complete | Automatic on post-check failure |
| 8 | Telemetry stack | ✅ Complete | Prometheus + Grafana + SNMP + gNMI |
| 9 | GitLab CI/CD | 🔄 Rebuilding | Pipeline being updated for new topology |
| 10 | NTP | 🔜 Next | svc-01 as internal NTP server, MD5 auth |
| 10 | BGP routing policy | 🔜 Next | Prefix lists, route maps |
| 10 | SSH hardening | 🔜 Next | All devices |
| 10 | DHCP / Syslog | 🔜 Next | svc-01 as services host |
| 11 | NAPALM transport | 📋 Planned | Multi-vendor abstraction layer |
| 12 | AI layer | 📋 Planned | FastMCP + LangChain + Ollama |
| 12 | netclaw | 📋 Planned | Parallel AI network agent implementation |
| 13 | Ansible integration | 📋 Planned | System-level and cross-platform tasks |
| 13 | Terraform integration | 📋 Planned | Infrastructure provisioning |
| 14 | pyATS learn/diff | 📋 Planned | Full feature snapshot pipeline integration |
| 15 | Batfish | 🔮 Future | Pre-deployment config verification |
| 15 | HashiCorp Vault | 🔮 Future | Proper secrets management |
| 15 | Nokia SR Linux | 🔮 Future | gNMI-native telemetry node |

**Legend:** ✅ Complete · 🔄 In progress · 🔜 Next · 📋 Planned · 🔮 Future

---

## Architecture Principles

- Config is generated from templates, never hardcoded in automation code
- `hosts.yaml` is the single source of truth for all per-device automation data
- Every workflow is idempotent — safe to run multiple times
- Every deployment runs pre/post validation with automatic rollback on failure
- Platform is split by domain: routing, switching, services, security
- Multi-vendor by design: Cisco IOS XE at edge, Arista EOS at core and access

---

## Lab Topology — Current
```
                    [inet-host]
                   /           \
             rtr-01           rtr-02
             AS65001          AS65002
           Gi2 eBGP      eBGP Gi2
           Gi3/Gi4 OSPF  OSPF Gi3/Gi4
                │                │
          core-sw-01 ══ core-sw-02
          (MLAG primary)  (MLAG secondary)
          OSPF, VRRP, SVIs
               │                │
          Po10 (MLAG)      Po20 (MLAG)
         /       \          /       \
    arista-01         arista-02
    (access)           (access)
    /      \           /      \
host-01  host-03   host-02  host-04
VLAN10   VLAN10    VLAN20   VLAN20

svc-01 ── core-sw-01 Eth7 (VLAN 20)
```

**Node inventory:**

| Node | Image | Role | AS / Domain |
|------|-------|------|-------------|
| rtr-01 | cisco_c8000v:17.15.04c | Edge router | AS65001 |
| rtr-02 | cisco_c8000v:17.15.04c | Edge router | AS65002 |
| core-sw-01 | ceos:4.35.1F | Core switch | MLAG primary |
| core-sw-02 | ceos:4.35.1F | Core switch | MLAG secondary |
| arista-01 | ceos:4.35.1F | Access switch | — |
| arista-02 | ceos:4.35.1F | Access switch | — |
| svc-01 | netshoot | Services host | NTP, syslog, DNS, DHCP |
| inet-host | netshoot | Internet simulation | — |
| host-01..04 | netshoot | End hosts | VLAN 10/20 |

**Management network: 172.20.20.0/24**

| Device | IP |
|--------|----|
| rtr-01 | 172.20.20.11 |
| rtr-02 | 172.20.20.12 |
| arista-01 | 172.20.20.13 |
| arista-02 | 172.20.20.14 |
| core-sw-01 | 172.20.20.15 |
| core-sw-02 | 172.20.20.16 |
| svc-01 | 172.20.20.20 |
| inet-host | 172.20.20.30 |
| host-01..04 | 172.20.20.21-24 |

**Data plane IP plan:**

| Link | Subnet |
|------|--------|
| eBGP rtr-01 ↔ rtr-02 | 10.0.0.0/30 |
| rtr-01 → core-sw-01 | 10.1.0.0/30 |
| rtr-01 → core-sw-02 | 10.1.0.4/30 |
| rtr-02 → core-sw-01 | 10.2.0.0/30 |
| rtr-02 → core-sw-02 | 10.2.0.4/30 |
| rtr-01 → inet-host | 203.0.113.0/30 |
| rtr-02 → inet-host | 203.0.113.4/30 |
| VLAN 10 (users) | 10.10.10.0/24, VIP .1 |
| VLAN 20 (servers) | 10.20.20.0/24, VIP .1 |
| VLAN 99 (management) | 10.99.99.0/24, VIP .1 |

---

## Repository Structure
```
enterprise-netauto-platform/
├── containerlab/
│   ├── topology.yml                # 12-node enterprise topology
│   └── configs/                    # Reference device configs
├── automation/
│   ├── config.py                   # Pydantic settings, env variables
│   ├── runner.py                   # CLI entrypoint for all workflows
│   ├── test_connection.py          # Nornir init + connectivity test
│   ├── nornir_config.yaml
│   ├── inventory/
│   │   ├── hosts.yaml              # Single source of truth (all device data)
│   │   ├── groups.yaml             # Platform credentials and connection params
│   │   └── netbox_seed.py          # Seed NetBox from inventory
│   ├── templates/definitions/
│   │   ├── interfaces/             # Layer 3 interfaces (Cisco + EOS)
│   │   ├── routing/                # BGP, OSPF, NAT templates
│   │   ├── switching/              # VLANs, port-channels, MLAG, VRRP
│   │   ├── services/               # NTP, syslog (planned)
│   │   └── security/               # SSH hardening (planned)
│   ├── workflows/
│   │   ├── interfaces/             # Multi-platform interface deploy
│   │   ├── routing/                # BGP, OSPF, NAT workflows
│   │   ├── switching/              # VLANs, port-channels, MLAG, VRRP workflows
│   │   ├── services/               # NTP, syslog workflows (planned)
│   │   └── security/               # Hardening workflows (planned)
│   ├── tasks/                      # Core Nornir task functions
│   ├── validators/                 # Pre/post check state validation
│   ├── drift/                      # DeepDiff drift detection
│   ├── rollback/                   # Config rollback on failure
│   └── utils/                      # Structured logging
├── tests/
│   ├── testbed.yaml                # pyATS device definitions
│   ├── precheck/                   # Baseline state tests
│   └── postcheck/                  # Post-deployment regression tests
├── telemetry/
│   ├── docker-compose.yml
│   ├── prometheus.yml              # Scrape config (all 6 managed devices)
│   ├── snmp.yml                    # SNMP community: netauto
│   └── gnmic.yml                   # gNMI targets: all 4 Arista switches
├── netbox-docker/                  # NetBox Docker deployment
├── ai/                             # AI layer (planned)
│   ├── agents/
│   ├── prompts/
│   ├── tools/
│   └── memory/
└── docs/
    └── automation_feature_roadmap.md
```

---

## Runner Commands
```bash
# Connectivity
python automation/runner.py connect test
python automation/runner.py validate netbox
python automation/runner.py validate inventory

# Deployment — run in this order after lab restart
python automation/runner.py deploy interfaces
python automation/runner.py deploy ospf
python automation/runner.py deploy nat
python automation/runner.py deploy bgp
python automation/runner.py deploy vlans
python automation/runner.py deploy portchannels
python automation/runner.py deploy mlag
python automation/runner.py deploy vrrp

# Drift detection
python automation/runner.py drift bgp
```

---

## Lab Restart Sequence

Cisco c8000v does not persist config across Containerlab restarts.
Arista cEOS does. Run the full sequence after every restart.
```bash
# 1. Start NetBox
cd ~/enterprise-netauto-platform/netbox-docker && docker compose up -d

# 2. Start telemetry
cd ~/enterprise-netauto-platform/telemetry && docker compose up -d

# 3. Deploy topology (wait ~5 min for IOS XE to boot)
cd ~/enterprise-netauto-platform/containerlab && sudo containerlab deploy -t topology.yml

# 4. Activate venv and deploy
cd ~/enterprise-netauto-platform && source venv/bin/activate
python automation/runner.py connect test
python automation/runner.py deploy interfaces
python automation/runner.py deploy ospf
python automation/runner.py deploy nat
python automation/runner.py deploy bgp
python automation/runner.py deploy vlans
python automation/runner.py deploy portchannels
python automation/runner.py deploy mlag
python automation/runner.py deploy vrrp
```

---

## Validation
```bash
# pyATS BGP validation
pyats run job tests/precheck/test_bgp.py --testbed tests/testbed.yaml
pyats run job tests/postcheck/test_bgp.py --testbed tests/testbed.yaml

# End-to-end connectivity
docker exec clab-enterprise-netauto-lab-host-01 ping -c 3 10.20.20.10
```

---

## CI/CD Pipeline

Runs on GitLab CI/CD on every push. GitHub is kept in sync as a mirror.

Pipeline stages:

1. **build** — validate environment, dependencies, NetBox connectivity
2. **prevalidation** — pyATS baseline capture before any changes
3. **deploy** — run automation workflows (manual gate before touching devices)
4. **postvalidation** — pyATS regression check after deployment

Pipeline is being rebuilt for the new topology. Current `.gitlab-ci.yml` reflects
the previous v1 design.

---

## Tool Decisions

### Why these tools

| Tool | Role |
|------|------|
| Nornir | Core automation engine — Python-native, integrates with all platform components |
| Scrapli | SSH transport — faster and more reliable than Paramiko for network devices |
| pyATS / Genie | Validation — structured parsing, pre/post state comparison |
| NetBox | Source of truth — DCIM + IPAM, API-driven, industry standard |
| Prometheus + Grafana | Telemetry — time-series metrics, visual dashboards |
| gnmic | gNMI collector — streaming telemetry from Arista switches |
| Ansible | Planned — system-level tasks, Linux host configuration |
| Terraform | Planned — infrastructure provisioning |

### Nornir vs Ansible vs Terraform

These work at different layers and are complementary, not competing.

| Tool | Layer |
|------|-------|
| Nornir | Network device automation — config, validation, drift, AI integration |
| Ansible | System/OS layer — Linux hosts, cross-platform orchestration |
| Terraform | Infrastructure provisioning — Docker hosts, cloud extension |

---

## Environment

- WSL Ubuntu 24.04
- Python 3.12 (venv at `./venv`)
- Docker with Compose V2
- Containerlab v0.73+

---

## Getting Started
```bash
git clone https://github.com/betoAssimos/enterprise-netauto-platform
cd enterprise-netauto-platform
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env: NETBOX_TOKEN, DEVICE_USERNAME, DEVICE_PASSWORD

# Pull required images
docker pull vrnetlab/cisco_c8000v:17.15.04c
docker pull ceos:4.35.1F
docker pull nicolaka/netshoot:latest

# Start NetBox
cd netbox-docker && docker compose up -d

# Start telemetry
cd telemetry && docker compose up -d

# Deploy lab
cd containerlab && sudo containerlab deploy -t topology.yml

# Wait ~5 minutes for IOS XE to boot, then:
cd .. && source venv/bin/activate
python automation/runner.py connect test
python automation/runner.py deploy interfaces
python automation/runner.py deploy ospf
python automation/runner.py deploy nat
python automation/runner.py deploy bgp
python automation/runner.py deploy vlans
python automation/runner.py deploy portchannels
python automation/runner.py deploy mlag
python automation/runner.py deploy vrrp
```