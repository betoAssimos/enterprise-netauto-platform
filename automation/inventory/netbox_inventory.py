#!/usr/bin/env python3
import os
import yaml
import pynetbox
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

NETBOX_URL = os.getenv('NETBOX_URL')
NETBOX_TOKEN = os.getenv('NETBOX_TOKEN')

if not NETBOX_URL or not NETBOX_TOKEN:
    raise Exception("NETBOX_URL and NETBOX_TOKEN must be set in .env file")

nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)

hosts = {}
for device in nb.dcim.devices.filter(status='active'):
    # Skip devices without a primary IPv4 address
    if not device.primary_ip4:
        print(f"Skipping {device.name}: no primary IPv4")
        continue

    # Extract IP address without CIDR
    mgmt_ip = str(device.primary_ip4.address).split('/')[0]

    # Determine platform based on manufacturer
    manufacturer = device.device_type.manufacturer.name.lower()
    if 'cisco' in manufacturer:
        platform = 'ios'
    elif 'arista' in manufacturer:
        platform = 'eos'
    else:
        platform = 'linux'  # fallback for hosts

    hosts[device.name] = {
        'hostname': mgmt_ip,
        'username': 'admin',
        'password': 'admin',
        'platform': platform,
        'data': {
            'site': device.site.slug if device.site else None,
            'role': device.role.slug if device.role else None,
            'model': device.device_type.model,
            'manufacturer': device.device_type.manufacturer.name,
        }
    }

# Write to hosts.yaml
output_file = 'hosts.yaml'
with open(output_file, 'w') as f:
    yaml.dump(hosts, f, default_flow_style=False)

print(f"Generated inventory with {len(hosts)} devices -> {output_file}")