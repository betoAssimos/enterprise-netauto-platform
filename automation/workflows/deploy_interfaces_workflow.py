from nornir import InitNornir
from automation.tasks.deploy_interfaces import deploy_interfaces


def run_workflow():

    nr = InitNornir(config_file="/home/beto/enterprise-netauto-platform/automation/nornir_config.yaml")

    result = nr.run(task=deploy_interfaces)

    print(result)