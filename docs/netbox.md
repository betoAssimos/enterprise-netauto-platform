NetBox deployment and integration

NetBox is used as the source of truth for the lab topology.

Deployment
- Docker Compose (official netbox-docker project)
- http://localhost:8000

Modeled objects
- Site: Lab
- Device Roles: edge-router, core-switch, host
- Device Types: IOSv, cEOS, Linux Host

Devices
rtr-01 172.20.20.11
rtr-02 172.20.20.12
arista-01 172.20.20.13
arista-02 172.20.20.14

Interfaces and cables modeled to match containerlab topology.

API Integration
Inventory is dynamically generated using:

automation/generate_inventory.py

This script queries NetBox using pynetbox and builds the Nornir hosts.yaml inventory.