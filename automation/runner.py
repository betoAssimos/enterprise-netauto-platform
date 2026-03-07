import sys


def main():

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python automation/runner.py connect test")
        print("  python automation/runner.py deploy interfaces")
        print("  python automation/runner.py deploy bgp")
        sys.exit(1)

    module = sys.argv[1]
    action = sys.argv[2]

    if module == "connect" and action == "test":
        from automation.test_connection import nr
        from automation.test_connection import test_connection

        result = nr.run(task=test_connection)
        print(result)

    elif module == "deploy" and action == "interfaces":
        from automation.workflows.deploy_interfaces_workflow import run_workflow

        run_workflow()

    elif module == "deploy" and action == "bgp":
        from automation.test_connection import nr
        from automation.workflows.bgp_workflow import run_bgp_deploy

        result = run_bgp_deploy(nr)
        print(result)

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()