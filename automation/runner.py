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
        required = ["rtr-01", "rtr-02"]
        try:
            with open(path) as f:
                hosts = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"ERROR: {path} not found")
            sys.exit(1)
        missing = [d for d in required if d not in hosts]
        if missing:
            print(f"ERROR: Required devices missing: {missing}")
            sys.exit(1)
        print(f"Inventory OK -- {len(hosts)} devices: {list(hosts.keys())}")

    elif module == "deploy" and action == "interfaces":
        from automation.test_connection import nr
        from automation.workflows.deploy_interfaces_workflow import run_interfaces_deploy
        result = run_interfaces_deploy(nr)
        print(result)

    elif module == "deploy" and action == "bgp":
        from automation.test_connection import nr
        from automation.workflows.bgp_workflow import run_bgp_deploy
        result = run_bgp_deploy(nr)
        print(result)

    elif module == "drift" and action == "bgp":
        from automation.test_connection import nr
        from automation.workflows.bgp_workflow import run_bgp_drift_check
        result = run_bgp_drift_check(nr)
        print(result)

    else:
        print(f"Unknown command: {module} {action}")
        sys.exit(1)

if __name__ == "__main__":
    main()