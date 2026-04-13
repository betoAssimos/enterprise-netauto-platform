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
- FastMCP server (ai/mcp_server.py) — HTTP transport, 8 read-only tools:
  get_device_inventory, get_bgp_state, get_ospf_neighbors,
  get_vrrp_state, get_mlag_state, get_interface_status,
  get_routing_table, get_ntp_status
- LangChain ReAct agent (ai/agents/agent.py) — Ollama llama3.1:8b
- Validated: all 8 tools confirmed across IOS XE and EOS
- EOS tools use device.execute() + regex (no Genie parsers for VRRP, MLAG, NTP)
- IOS XE tools use Genie parsers; get_routing_table uses entry-based structure

NetBox SoT migration complete:
- NetBox 4.5.4 fully seeded — all 6 network devices, 36 custom field definitions,
  all custom field values populated via automation/inventory/seed_netbox.py
- Custom Nornir inventory plugin (automation/inventory/netbox_inventory.py)
  queries NetBox at runtime and builds host objects with identical structure
  to the previous hosts.yaml — zero changes to workflows, intent builders,
  context builders, or test files
- nornir_config.yaml updated to use NetBoxInventory plugin
- hosts.yaml retained as reference but no longer drives automation
- Validated: full OSPF deploy confirmed end-to-end with live NetBox inventory

---

## Next — in order

1. Chaos injection framework — Phase 1 foundation complete (Scenario 3 OSPF validated).
   Remaining: mlag.py (1), access_uplink.py (2), bgp.py (4,5), vrrp.py (6),
   ntp.py (7), telemetry.py (8), pipeline.py (10), syslog_diagnosis.py (11),
   restconf.py (12). Then steady_state.py (Phase 2) and combined/ (Phase 3).
2. Tech debt: interface descriptions on MLAG/LACP physical members
3. Tech debt: refactor restconf_client.py to use persistent Session
4. Observability additions: Oxidized, Grafana Alertmanager, Loki + Promtail
5. Batfish — offline config analysis in CI prevalidation stage
6. Protocol fixes:
   a. OSPF passive-interface on GigabitEthernet2 (rtr-01 and rtr-02) — removes ospf_route_expected workaround
   b. VRRP load distribution — core-sw-01 master for groups 10/99, core-sw-02 master for group 20 + intent test update

---

## Architecture decisions

**NetBox as live SoT via custom Nornir inventory plugin**
NetBox is the authoritative data source for all device inventory and
automation data. The custom plugin (automation/inventory/netbox_inventory.py)
queries NetBox at Nornir initialization time and returns host objects with
the same structure previously produced by SimpleInventory + hosts.yaml.
Groups and defaults are still loaded from groups.yaml and defaults.yaml
so connection parameters remain in version control. ConnectionOptions
objects are constructed explicitly — Nornir requires typed objects, not
raw dicts, which SimpleInventory handled internally.

**NetBox seeding via script, not UI**
automation/inventory/seed_netbox.py reads hosts.yaml and pushes all
device data, custom field definitions, and custom field values via the
pynetbox API. Idempotent — uses get-or-create throughout. NetBox v4
requires IP addresses assigned to device interfaces before they can be
set as primary — the script creates a Management0 interface per device
before assigning the IP.

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
stored in NetBox as static_routes custom fields.

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

**Credentials in groups.yaml (Lab-Only)**
Device credentials (admin/admin) are stored in automation/inventory/groups.yaml
as Nornir group defaults. This is acceptable for a local lab environment with
no sensitive data. For production, migrate to HashiCorp Vault or environment
variables injected by CI/CD.

**AI Layer — FastMCP construction vs. NetClaw adoption**
Building custom FastMCP server rather than using NetClaw (automateyournetwork/netclaw)
to demonstrate MCP construction competence (AUTOCOR 4.3). NetClaw provides a
production-ready reference implementation with 82+ skills, but constructing the
server from scratch ensures deeper understanding of the Model Context Protocol
and tool exposure patterns. Architecture: FastMCP server exposing pyATS-based
network tools, LangChain for agent orchestration, Ollama for local LLM inference,
live device queries via pyATS testbed.

**AI tools are read-only**
All FastMCP tools query state only. No config-changing tools added until
explicit gates and confirmation workflow are designed. This is a hard rule,
not a guideline.

**get_routing_table uses entry-based Genie structure for IOS XE**
Genie's parser for `show ip route <host>` on IOS XE returns a top-level
`entry` key, not `vrf.default.address_family.ipv4.routes`. The tool
traverses `entry` → prefix → `paths` → path entries for next-hop data.
EOS uses a two-line-per-route format parsed with a state machine: line 1
captures protocol + prefix + optional AD/metric, line 2 captures
`via next-hop, interface` or `directly connected, interface`.

**VRRP master ownership imbalance (known gap)**
core-sw-01 is master for all three VRRP groups (10, 20, 99). Target state
distributes ownership: core-sw-01 masters groups 10 and 99, core-sw-02 masters
group 20. Fix requires priority adjustment in templates/vrrp_eos.j2 and
corresponding update to tests/postcheck/test_vrrp_intent.py. Deferred until
after observability additions.

**Chaos framework registry as standalone module**
SCENARIO_REGISTRY, PHASE_REGISTRY, and register_scenario() live exclusively in
tests/chaos/registry.py. When chaos_runner.py runs as __main__, Python creates
a separate module identity from tests.chaos.chaos_runner. Any injector importing
register_scenario from chaos_runner.py registers to the wrong identity and never
appears in --list. The standalone registry has a single identity regardless of
how chaos_runner.py is invoked. Each new injector requires one explicit import
line in chaos_runner.py to trigger registration at startup.

**Chaos fault window sizing**
Prometheus scrape interval is 15s. A fault must persist for at least 2× the scrape
interval (30s) to guarantee a dip appears in Grafana dashboards. Development/CI
runs use --wait 10. Portfolio demo runs use --wait 30.

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