# Telemetry Stack

Two complementary monitoring approaches running as Docker Compose services.

## Architecture
```
Devices
 ├─ SNMP (all 6 managed devices) → snmp-exporter → Prometheus
 └─ gNMI (4 Arista switches only) → gnmic → Prometheus

Prometheus → Grafana dashboards
```

## Services

| Service | Image | Port |
|---------|-------|------|
| Prometheus | prom/prometheus | 9090 |
| Grafana | grafana/grafana | 3000 |
| SNMP Exporter | prom/snmp-exporter | 9116 |
| gnmic | ghcr.io/karimra/gnmic | 9804 |

## Notes

- gNMI is limited to Arista cEOS nodes. Cisco c8000v does not support gNMI
  reliably in this lab image.
- gnmic runs as a Docker container. A systemd service was previously used
  but replaced for consistency with the rest of the stack.
- Grafana dashboards are version controlled in `dashboards/`.