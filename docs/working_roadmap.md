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

Intent validation suite complete. All tests pass at 100%:
- OSPF: neighbor FULL state + loopback /32 convergence (4 devices)
- VRRP: Master/Backup state + virtual IP per group (2 core switches)
- MLAG: domain Active/Connected/peer-link Up + interfaces active-full
- BGP received prefixes: complement to existing advertised check
- NTP: sync state + server match (6 devices)
- BGP advertised prefixes: policy chain validation (pre-existing)
- End-to-end connectivity (pre-existing)

Pipeline prevalidation expanded: BGP baseline, OSPF baseline, connectivity
baseline — all captured before deploy. Postvalidation: 8 parallel jobs covering
full intent validation suite.

All test files are inventory-driven — no hardcoded device names anywhere.
test_bgp.py (precheck) and test_bgp_intent.py corrected as tech debt.

AI layer complete:
- FastMCP server (ai/mcp_server.py) — HTTP transport, 3 read-only tools:
  get_device_inventory, get_bgp_state, get_ospf_neighbors
- LangChain ReAct agent (ai/agents/agent.py) — Ollama llama3.1:8b
- Validated: inventory queries, live BGP state, live OSPF neighbors

---

## Next — in order

1. Expand FastMCP server — additional read-only tools (see ideas below)
2. NetBox as live SoT — replace hosts.yaml with dynamic inventory from API

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

**Multiple intent functions per module when same domain**
`build_bgp_received_intent()` lives in `bgp_intent_builder.py` alongside
`build_bgp_intent()`. Same domain = same module. Splitting into separate
files would fragment cohesive logic without architectural benefit.

**Device names never hardcoded in test files**
All test files derive the device list from inventory by role filter via
Nornir. Hardcoding names couples tests to topology and violates the
single source of truth principle. test_bgp.py and test_bgp_intent.py
corrected — both are now inventory-driven.

**Genie parser availability must be verified before writing test logic**
EOS has no Genie parsers for OSPF, MLAG, VRRP, or NTP in the current
Genie version. IOS XE has parsers for all of these. Pattern: detect
device.os == "iosxe" and use Genie; else use device.execute() + regex.
Always verify with os.walk on the genie.libs.parser directory before
assuming a parser exists.

**ospf_route_expected: false on eBGP peering neighbors**
rtr-01 and rtr-02 peer over 10.0.0.0/30. Their loopbacks (1.1.1.1/32,
2.2.2.2/32) are learned via eBGP (AD 20), not OSPF (AD 110). The OSPF
neighbor state check still runs — both are FULL. Only the route presence
check is skipped via the flag. Without this, the test would incorrectly
fail because the route is reachable but not in the OSPF RIB.

**BGP received prefixes use installed routes, not soft-reconfiguration**
`show bgp ipv4 unicast neighbors X routes` returns routes accepted and
installed from a neighbor without requiring `soft-reconfiguration inbound`.
This avoids unnecessary config changes just for observability.

**EOS NTP spelling normalization**
EOS reports "synchronised" (British spelling). IOS XE reports "synchronized".
Normalize both before string comparison — do not add a platform branch just
for a spelling difference.

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
all 6 devices. gNMI provides streaming telemetry from arista switches only.
This is a lab constraint, not a design choice.

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

**AI Layer — FastMCP construction vs. NetClaw adoption**
Building custom FastMCP server rather than using NetClaw (automateyournetwork/netclaw)
to demonstrate MCP construction competence (AUTOCOR 4.3). NetClaw provides a
production-ready reference implementation with 82+ skills, but constructing the
server from scratch ensures deeper understanding of the Model Context Protocol
and tool exposure patterns. Architecture: FastMCP server exposing pyATS-based
network tools, LangChain for agent orchestration, Ollama for local LLM inference,
integration with existing hosts.yaml inventory.

**AI tools are read-only**
All FastMCP tools query state only. No config-changing tools added until
explicit gates and confirmation workflow are designed. This is a hard rule,
not a guideline.

---

## Ideas backlog

- pyATS learn/diff snapshots — full feature state capture before/after changes
- Golden config compliance — policy file defines baseline, report deviations
- Batfish — offline config analysis before deploy, catches routing errors without touching a device
- SuzieQ — network state query engine, complements pyATS for ad-hoc queries
- NAPALM — vendor abstraction layer, removes platform if/elif in workflow code
- Terraform — provision the infrastructure the lab runs on
- Nokia SR Linux node — gNMI-native, cleaner streaming telemetry story
- Neo4j — graph database for topology when NetBox relationship queries become complex enough to need native graph traversal

**Infrastructure Hardening**
- Distributed Locking — prevent concurrent deploys via file-based lock or Redis
- Pipeline Metrics — instrument runner.py with Prometheus client for deploy duration/failure rates
- Negative Testing — fault injection (kill container mid-deploy, verify rollback)
- Golden Config Snapshots — store post-validation configs in versioned storage
- RESTCONF — IOS-XE YANG/JSON workflow alongside existing SSH