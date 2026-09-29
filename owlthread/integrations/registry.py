"""Fail-closed integration configuration stored in OwlThread's settings table."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from owlthread.integrations.catalog import get_spec, list_catalog
from owlthread.integrations.models import IntegrationSpec


SETTING_PREFIX = "integration_config:"


class SettingsStore(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...
    def set_setting(self, key: str, value: str) -> None: ...
    def get_project_by_id(self, project_id: int) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class IntegrationConfig:
    enabled: bool = False
    scopes: tuple[str, ...] = ()
    project_id: int | None = None


class IntegrationRegistry:
    """Catalog plus durable grants; it deliberately owns no credentials or clients."""

    def __init__(self, db: SettingsStore) -> None:
        self.db = db

    @staticmethod
    def _key(integration_id: str) -> str:
        return SETTING_PREFIX + integration_id

    def _load(self, spec: IntegrationSpec) -> tuple[IntegrationConfig, str | None]:
        raw = self.db.get_setting(self._key(spec.integration_id))
        if raw is None:
            return IntegrationConfig(), None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != {"enabled", "scopes", "project_id"}:
                raise ValueError
            enabled, scopes, project_id = value["enabled"], value["scopes"], value["project_id"]
            if type(enabled) is not bool or not isinstance(scopes, list) or any(type(item) is not str for item in scopes):
                raise ValueError
            if len(scopes) != len(set(scopes)) or any(item not in spec.scope_map for item in scopes):
                raise ValueError
            if project_id is not None and (type(project_id) is not int or project_id <= 0 or not self.db.get_project_by_id(project_id)):
                raise ValueError
            return IntegrationConfig(enabled, tuple(scopes), project_id), None
        except (TypeError, ValueError, json.JSONDecodeError):
            # A corrupted or manually edited grant must never become permissive.
            return IntegrationConfig(), "Stored configuration is invalid; integration disabled"

    def status(self, integration_id: str, *, include_scope_details: bool = True) -> dict[str, Any]:
        spec = get_spec(integration_id)
        config, error = self._load(spec)
        result = spec.to_dict(include_scope_details=include_scope_details)
        result.update({
            "enabled": config.enabled,
            "connected": False,
            "can_execute": False,
            "connection_state": "invalid_configuration" if error else (
                "enabled_unconnected" if config.enabled else "disabled_unconnected"
            ),
            "configured_scopes": list(config.scopes),
            "project_id": config.project_id,
            "configuration_valid": error is None,
        })
        if error:
            result["configuration_error"] = error
        return result

    def list(self) -> list[dict[str, Any]]:
        return [self.status(item.integration_id, include_scope_details=False) for item in list_catalog()]

    def configure(self, integration_id: str, *, enabled: bool, scopes: list[str],
                  project_id: int | None = None, via_mcp: bool = False) -> dict[str, Any]:
        spec = get_spec(integration_id)
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if not isinstance(scopes, list) or any(type(item) is not str for item in scopes):
            raise ValueError("scopes must be a list of exact scope names")
        if len(scopes) != len(set(scopes)):
            raise ValueError("scopes must not contain duplicates")
        unknown = [item for item in scopes if item not in spec.scope_map]
        if unknown:
            raise ValueError("Unsupported scope(s): " + ", ".join(unknown))
        if project_id is not None:
            if type(project_id) is not int or project_id <= 0 or not self.db.get_project_by_id(project_id):
                raise ValueError("Unknown project_id")
        if via_mcp:
            prohibited = [item for item in scopes if spec.scope_map[item].blocked_via_mcp]
            if prohibited:
                raise PermissionError(
                    "MCP cannot grant admin, destructive, or trading scopes: " + ", ".join(prohibited)
                )
        payload = {"enabled": enabled, "scopes": sorted(scopes), "project_id": project_id}
        self.db.set_setting(self._key(integration_id), json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return self.status(integration_id)
