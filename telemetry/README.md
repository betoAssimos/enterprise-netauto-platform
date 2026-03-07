# Telemetry Stack

This platform uses two monitoring approaches:

1. SNMP monitoring
2. Streaming telemetry (gNMI)

Architecture:

Devices
 ├─ SNMP → SNMP Exporter → Prometheus
 └─ gNMI → gNMIc → Prometheus

Prometheus → Grafana dashboards

Services:

- Prometheus
- Grafana
- SNMP Exporter
- gNMIc