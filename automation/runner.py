import sys

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python automation/runner.py connect test")
        print("  python automation/runner.py validate netbox")
        print("  python automation/runner.py validate inventory")
        print("  python automation/runner.py deploy interfaces")
        print("  python automation/runner.py deploy bgp")
        print("  python automation/runner.py drift bgp")
        print("  python automation/runner.py deploy ospf")
        print("  python automation/runner.py deploy nat")
        print("  python automation/runner.py deploy vlans")
        print("  python automation/runner.py deploy portchannels")
        print("  python automation/runner.py deploy mlag")
        print("  python automation/runner.py deploy vrrp")
        print("  python automation/runner.py deploy ntp")
        print("  python automation/runner.py deploy bgp-policy")
        print("  python automation/runner.py deploy ssh")
        sys.exit(1)

    module = sys.argv[1]
    action = sys.argv[2]

    if module == "connect" and action == "test":
        from automation.test_connection import nr
        from automation.test_connection import test_connection
        result = nr.run(task=test_connection)
        print(result)

    elif module == "validate" and action == "netbox":
        import os, requests
        token = os.getenv("NETBOX_TOKEN")
        url   = os.getenv("NETBOX_URL")
        if not token or not url:
            print("ERROR: NETBOX_URL and NETBOX_TOKEN must be set")
            sys.exit(1)
        try:
            r = requests.get(
                f"{url}/api/status/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except requests.exceptions.ConnectionError as exc:
            print(f"ERROR: Cannot reach NetBox at {url}: {exc}")
            sys.exit(1)
        if r.status_code != 200:
            print(f"ERROR: NetBox API returned {r.status_code}")
            sys.exit(1)
        print(f"NetBox {r.json().get('netbox-version', 'unknown')} -- API OK")

    elif module == "validate" and action == "inventory":
        import yaml
        path = "automation/inventory/hosts.yaml"
        required_fields = ["hostname", "groups"]
        try:
            with open(path) as f:
                hosts = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"ERROR: {path} not found")
            sys.exit(1)
        if not hosts:
            print("ERROR: Inventory is empty")
            sys.exit(1)
        errors = []
        for device, config in hosts.items():
            for field in required_fields:
                if field not in config:
                    errors.append(f"{device}: missing required field '{field}'")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            sys.exit(1)
        print(f"Inventory OK -- {len(hosts)} devices: {list(hosts.keys())}")

    elif module == "deploy" and action == "interfaces":
        from automation.test_connection import nr
        from automation.workflows.interfaces.deploy_interfaces_workflow import run_interfaces_deploy
        result = run_interfaces_deploy(nr)
        print(result)

    elif module == "deploy" and action == "bgp":
        from automation.test_connection import nr
        from automation.workflows.routing.bgp_workflow import run_bgp_deploy
        result = run_bgp_deploy(nr)
        print(result)

    elif module == "deploy" and action == "ospf":
        from automation.test_connection import nr
        from automation.workflows.routing.ospf_workflow import run_ospf_deploy
        result = run_ospf_deploy(nr)
        print(result)

    elif module == "deploy" and action == "nat":
        from automation.test_connection import nr
        from automation.workflows.routing.nat_workflow import run_nat_deploy
        result = run_nat_deploy(nr)
        print(result)

    elif module == "drift" and action == "bgp":
        from automation.test_connection import nr
        from automation.workflows.routing.bgp_workflow import run_bgp_drift_check
        result = run_bgp_drift_check(nr)
        print(result)

    elif module == "deploy" and action == "vlans":
        from automation.test_connection import nr
        from automation.workflows.switching.vlans_workflow import run_vlans_deploy
        result = run_vlans_deploy(nr)
        print(result)

    elif module == "deploy" and action == "portchannels":
        from automation.test_connection import nr
        from automation.workflows.switching.portchannels_workflow import run_portchannels_deploy
        result = run_portchannels_deploy(nr)
        print(result)

    elif module == "deploy" and action == "mlag":
        from automation.test_connection import nr
        from automation.workflows.switching.mlag_workflow import run_mlag_deploy
        result = run_mlag_deploy(nr)
        print(result)

    elif module == "deploy" and action == "vrrp":
        from automation.test_connection import nr
        from automation.workflows.switching.vrrp_workflow import run_vrrp_deploy
        result = run_vrrp_deploy(nr)
        print(result)

    elif module == "deploy" and action == "ntp":
        from automation.test_connection import nr
        from automation.workflows.services.ntp_workflow import run_ntp_deploy
        result = run_ntp_deploy(nr)
        print(result)

    elif module == "deploy" and action == "ssh":
        from automation.test_connection import nr
        from automation.workflows.security.ssh_hardening_workflow import run_ssh_deploy
        result = run_ssh_deploy(nr)
        print(result)

    elif module == "deploy" and action == "bgp-policy":
        from automation.test_connection import nr
        from automation.workflows.routing.bgp_policy_workflow import run_bgp_policy_deploy
        result = run_bgp_policy_deploy(nr)
        print(result)

    else:
        print(f"Unknown command: {module} {action}")
        sys.exit(1)

if __name__ == "__main__":
    main()