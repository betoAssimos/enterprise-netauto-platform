# Working Roadmap

Internal tracking document. Covers current state, next steps, architecture
decisions, and the ideas backlog. Not a changelog — see git log for that.

---

## Current state

Core automation complete. CI/CD pipeline running 5 stages: build, prevalidation,
deploy, postvalidation, remediation. End-to-end connectivity verified and monitored
via Grafana. Fault injection demo working — port shutdown detected by pyATS
connectivity test, remediation stage restores switching domain via idempotent
port-channel templates. All 4 Arista switches reporting via gNMI (containerized).
Telemetry stack fully containerized: Prometheus, Grafana, SNMP exporter, gnmic.
---

## Next — in order

1. OSPF intent validation — neighbor state + advertised networks
2. VRRP intent validation — master/standby state per VLAN per device
3. MLAG intent validation — domain state, peer-link, member ports
4. BGP received prefixes — complement to existing advertised check
5. NTP intent validation — sync state per device against configured server
6. AI layer — FastMCP + LangChain + Ollama, start with a basic ops agent
7. NetBox as live SoT — replace hosts.yaml with dynamic inventory from API
---

## Architecture decisions

**hosts.yaml as static SoT instead of NetBox**
NetBox is deployed and seeded but not used as the live inventory source.
The decision was to keep the automation engine working and validate the
full pipeline first. Migrating to dynamic NetBox inventory is planned but
not a blocker for any current work.

**Intent derived from policy, not raw config**
BGP advertised prefix intent is derived from the prefix-list referenced
by the outbound route-map on each neighbor, not from bgp_networks or
rendered config. This reflects how the control plane actually makes
forwarding decisions — a router can have a network statement but not
advertise it if a route-map filters it out. Intent must follow the
policy chain.

**Intent builder separate from context builder**
`bgp_intent_builder.py` is a standalone module, not merged into the
BGP context builder. Context builders produce data for rendering.
Intent builders produce data for validation. Mixing them would couple
rendering logic with validation logic and make both harder to test
independently.

**Nornir for network devices, Ansible for Linux hosts**
These work at different layers. Nornir with Scrapli handles SSH-based
config deployment and validation on network devices. Ansible handles
OS-level configuration on Linux hosts (svc-01 NTP server, syslog
receiver). Not competing tools — complementary layers.

**Specific static routes instead of policy-based routing for internet reachability**
Containerlab injects a kernel-level default route via Management0 on
cEOS nodes at AD 1. OSPF external routes have AD 110 and can never win.
Removing the management default doesn't persist — the container
networking layer re-injects it. The solution is specific static routes
toward the inet-host subnets (203.0.113.0/30, 203.0.113.4/30) on the
core switches. Longest-prefix match wins over the management default
regardless of AD. These routes are deployed via the OSPF workflow and
tracked in hosts.yaml.

**gNMI limited to Arista**
Cisco c8000v in this lab does not support gNMI reliably. SNMP covers
all 6 devices. gNMI provides streaming telemetry from core-sw-01 and
core-sw-02 only. This is a lab constraint, not a design choice.

**gnmic containerization**
gnmic was originally running as a systemd service on the WSL host. Moved to
Docker Compose to keep the telemetry stack consistent and portable. The systemd
service was disabled. Image used is ghcr.io/karimra/gnmic — the original image
before the project moved to the openconfig org, cached locally due to registry
access restrictions in this environment.

**process.j2 renamed to process_ios.j2**
The original name was ambiguous when EOS already had process_eos.j2.
Renamed to make the vendor split explicit and consistent across the
template directory.

**Credentials in hosts.yaml (Lab-Only)**
Credentials are stored in automation/inventory/hosts.yaml for all devices 
(admin/admin). This is acceptable for a local lab environment with no 
sensitive data. For production, migrate to HashiCorp Vault or environment 
variables injected by CI/CD.

---

## Ideas backlog

- pyATS learn/diff snapshots — full feature state capture before/after changes
- Golden config compliance — policy file defines baseline, report deviations
- Batfish — offline config analysis before deploy, catches routing errors without touching a device
- SuzieQ — network state query engine, complements pyATS for ad-hoc queries
- NAPALM — vendor abstraction layer, removes platform if/elif in workflow code
- Terraform — provision the infrastructure the lab runs on
- Nokia SR Linux node — gNMI-native, cleaner streaming telemetry story
- Neo4j — graph database for topology when NetBox relationship queries  become complex enough to need native graph traversal

**Infrastructure Hardening**
- Distributed Locking - Prevent concurrent deploys via file-based lock or Redis
- Pipeline Metrics - Instrument runner.py with Prometheus client for deploy duration/failure rates
- Negative Testing - Fault injection (kill container mid-deploy, verify rollback)
- Golden Config Snapshots - store post-validation configs in versioned storage
- RESTCONF - IOS-XE YANG/JSON workflow alongside existing SSH