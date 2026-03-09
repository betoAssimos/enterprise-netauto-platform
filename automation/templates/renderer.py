"""
automation/templates/renderer.py

Jinja2 template rendering engine for the platform.

Design principles:
- StrictUndefined: typos in variable names raise immediately at render
  time, not silently producing broken configs
- Templates loaded from filesystem — version controlled, never inline
- Rendered output validated for minimum content before returning
- Dry-run aware: logs rendered config without sending to device
- No business logic in templates; all logic lives here or in workflows

Custom filters registered:
- ipaddr_to_netmask : converts CIDR prefix to IOS address+mask pair
                      e.g. "10.0.0.1/30" → "10.0.0.1 255.255.255.252"
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateNotFound,
    TemplateError,
)

from automation.utils.logger import get_logger

log = get_logger(__name__)

# Default template directory
_DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "definitions"


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------

def _ipaddr_to_netmask(cidr: str) -> str:
    """
    Convert a CIDR address string to IOS-style 'address mask' format.

    Used in layer3.j2 to convert interface IP/prefix to IOS syntax.

    Examples
    --------
    >>> _ipaddr_to_netmask("10.0.0.1/30")
    '10.0.0.1 255.255.255.252'
    >>> _ipaddr_to_netmask("1.1.1.1/32")
    '1.1.1.1 255.255.255.255'

    Raises
    ------
    ValueError
        If the input is not a valid CIDR notation string.
    """
    try:
        interface = ipaddress.IPv4Interface(cidr)
        return f"{interface.ip} {interface.netmask}"
    except ValueError as exc:
        raise ValueError(
            f"ipaddr_to_netmask: invalid CIDR input '{cidr}': {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class TemplateRenderer:
    """
    Renders Jinja2 templates from the templates/definitions directory.

    Directory layout:
        automation/templates/definitions/
            bgp/
                neighbors.j2
            interfaces/
                layer3.j2
            prefix_lists/
                base.j2

    Usage:
        renderer = TemplateRenderer()
        config_block = renderer.render("bgp/neighbors.j2", context)
    """

    def __init__(self, template_dir: Path | None = None) -> None:
        self._template_dir = template_dir or _DEFAULT_TEMPLATE_DIR
        self._env = self._build_env()

    def _build_env(self) -> Environment:
        env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            autoescape=False,  # Network configs are not HTML
        )
        # Register custom filters
        env.filters["ipaddr_to_netmask"] = _ipaddr_to_netmask
        return env

    def render(self, template_path: str, context: dict[str, Any]) -> str:
        """
        Render a template and return the config string.

        Parameters
        ----------
        template_path : str
            Relative path from the definitions root.
            Example: "bgp/neighbors.j2"
        context : dict
            Variables injected into the template.
            Built from Nautobot device data by workflow modules.

        Raises
        ------
        TemplateNotFound
            If the template file does not exist.
        TemplateError
            If rendering fails due to undefined variable or syntax error.
        ValueError
            If rendered output is empty after stripping whitespace.
        """
        log.debug(
            "Rendering template",
            template=template_path,
            context_keys=list(context.keys()),
        )

        try:
            template = self._env.get_template(template_path)
            rendered = template.render(**context)
        except TemplateNotFound:
            log.error(
                "Template not found",
                template=template_path,
                search_dir=str(self._template_dir),
            )
            raise
        except TemplateError as exc:
            log.error(
                "Template render error",
                template=template_path,
                error=str(exc),
            )
            raise

        stripped = rendered.strip()
        if not stripped:
            raise ValueError(
                f"Template '{template_path}' rendered to empty output. "
                "Check that the context contains the required variables."
            )

        log.debug(
            "Template rendered",
            template=template_path,
            line_count=stripped.count("\n") + 1,
        )
        return stripped

    def render_all(
        self,
        templates: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, str]:
        """
        Render multiple templates and return a mapping of name to output.

        All templates are attempted before raising, so the caller sees
        the full set of failures at once rather than one at a time.

        Parameters
        ----------
        templates : list of (template_path, context) tuples

        Returns
        -------
        dict[str, str]
            {template_path: rendered_config_block}
        """
        results: dict[str, str] = {}
        errors: list[str] = []

        for template_path, context in templates:
            try:
                results[template_path] = self.render(template_path, context)
            except Exception as exc:
                errors.append(f"{template_path}: {exc}")

        if errors:
            raise TemplateError(
                f"Failed to render {len(errors)} template(s):\n"
                + "\n".join(errors)
            )

        return results

    def list_templates(self, subdir: str | None = None) -> list[str]:
        """List available templates, optionally scoped to a subdirectory."""
        base = (
            self._template_dir
            if subdir is None
            else self._template_dir / subdir
        )
        return sorted(
            str(p.relative_to(self._template_dir))
            for p in base.rglob("*.j2")
        )


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly across the platform
# ---------------------------------------------------------------------------

renderer = TemplateRenderer()