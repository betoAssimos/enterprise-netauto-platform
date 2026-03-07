from nornir_netmiko.tasks import netmiko_send_config
from automation.templates.renderer import render_template


def deploy_interfaces(task):

    config = render_template(
        template="interfaces/interfaces_base.j2",
        context=task.host.data
    )

    task.run(
        task=netmiko_send_config,
        config_commands=config.splitlines()
    )