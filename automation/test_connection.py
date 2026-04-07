from pathlib import Path
from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command
import automation.inventory.netbox_inventory  # registers NetBoxInventory plugin

BASE_DIR = Path(__file__).resolve().parent

nr = InitNornir(
    config_file=str(BASE_DIR / "nornir_config.yaml")
)

nr = InitNornir(
    config_file=str(BASE_DIR / "nornir_config.yaml")
)


def test_connection(task):
    result = task.run(
        task=netmiko_send_command,
        command_string="show version",
    )
    print(f"\nDevice: {task.host}")
    print(result.result[:200])
if __name__ == "__main__":
    results = nr.run(task=test_connection)
    print(f"\nCompleted: {len(results)} devices")
