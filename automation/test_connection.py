from pathlib import Path
from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command

# Get automation directory dynamically
BASE_DIR = Path(__file__).resolve().parent

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