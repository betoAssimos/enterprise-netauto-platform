# Feature Roadmap

Tracks what's been built, what's next, and ideas for later.
Not everything here will be implemented — some items are just worth keeping in mind.

---

## Phase 1 — Core Automation (Complete)

Everything in this phase is built and working.

- **Deployment pipeline orchestrator** — `automation/runner.py` is the single entry point for the full lifecycle: connect, validate, deploy, drift detection. CI/CD runs the same steps automatically on every push.
- **NetBox inventory integration** — dynamic inventory pulled from NetBox API into Nornir
- **Jinja2 config templates** — BGP and interface templates, no hardcoded config
- **Scrapli transport** — SSH-based config deployment for IOS XE and Arista cEOS
- **RESTCONF transport** — API-based config for IOS XE via YANG models (`automation/transports/restconf.py`)
- **BGP workflow** — eBGP deployment + connected redistribution on both routers, verified via RESTCONF
- **Drift detection** — DeepDiff-based engine comparing intended vs current state
- **Rollback** — config restoration module
- **pyATS precheck + postcheck** — validation before and after every deployment
- **Telemetry stack** — Prometheus, Grafana, SNMP exporter, gNMI collector

---

## Phase 2 — Transport and Observability (Next)

These two are the immediate next steps.

### NAPALM

Add a vendor-abstraction layer on top of the existing transports.
The goal is to stop writing `if iosxe... elif eos...` blocks in workflow code —
write the logic once and let NAPALM handle the vendor differences.

Fits into `automation/transports/` alongside the existing RESTCONF module.

### SuzieQ

Network state engine that lets you query BGP state, interface status, topology,
and routing tables across all devices without SSH-ing into each one.

Useful on its own for observability, and also a foundation for the topology
discovery work in Phase 3. Runs as a Docker container alongside the existing
telemetry stack.

---

## Phase 3 — Topology and AI (Planned)

### Lab Topology v2

Extend `containerlab/topology.yml` to a 3-tier WAN/enterprise design:

- rtr-01, rtr-02 as WAN/edge (eBGP between AS65001 and AS65002)
- rtr-03, rtr-04 as core (iBGP within AS65001, route reflectors)
- arista-01, arista-02 as access/ToR
- host-01, host-02 as endpoints

Requires updating the Nornir inventory, BGP templates, and pyATS testbed.
Check available RAM and CPU headroom before starting — current lab is already
heavy at idle.

### Topology Discovery

Automate collection of LLDP neighbors, BGP peers, and interface state from all devices.
Store the resulting relationships in NetBox using its cabling/connection model.
This makes NetBox the topology database, not just the device inventory.

Target module: `automation/discovery/topology.py`

### AI Incident Analysis

Build a layer that enriches alerts with topology context before passing them to an LLM.
A BGP-down alert without topology context is useless — the AI needs to know what depends
on the failed device before it can suggest a root cause.

Pipeline:

```
Topology Discovery → Topology Store (NetBox) → Topology Query API (FastAPI)
      → Incident Context Builder → AI Reasoning Engine (Ollama)
```

Target modules: `ai/agents/`, `ai/tools/`, topology query microservice

---

## Phase 4 — Infrastructure and Platform (Planned)

### Ansible

System-level and cross-platform tasks: bootstrapping Linux hosts, configuring SNMP
on servers, orchestrating workflows that cross the network/OS boundary.
Not a replacement for Nornir — they work at different layers.

### Terraform

Provisioning the infrastructure the lab runs on: Docker host setup, environment
bootstrapping. Potentially a cloud lab extension later.
This is the bottom layer of the stack — Terraform provisions, Ansible configures,
Nornir automates the network on top.

### Network Snapshot System

Capture device state before and after changes and diff the results.
Useful for troubleshooting and change validation beyond what pyATS covers.

Target: `automation/snapshots/`

Commands to capture: `show ip route`, `show ip bgp summary`, `show interfaces`, `show version`

### Golden Config Compliance

Check that all devices follow a baseline policy (NTP, SSH version, logging server,
no telnet, etc.) and report any deviations.

Target: `automation/compliance/` with a YAML policy file

---

## Future Ideas

These are worth keeping in mind but not scheduled.

- **Batfish** — analyze config files offline before deploying. Catches routing errors
  and policy violations without touching a device. High value for CI/CD.
- **HashiCorp Vault** — replace `.env` credential management with proper secrets storage
- **Neo4j** — swap NetBox as the topology store for native graph traversal when
  relationship queries get complex enough to need a real graph database
- **netclaw** — network-aware tooling for the AI agent layer
- **OpenConfig + gNMI push config** — vendor-neutral configuration via YANG,
  complementing the existing RESTCONF transport