"""Immutable integration catalog models; no credentials or live clients live here."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal


RiskTier = Literal["read", "write", "admin"]
_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\Z")


@dataclass(frozen=True, slots=True)
class ScopeSpec:
    """One exact grant supported by an integration definition."""

    name: str
    description: str
    risk: RiskTier
    destructive: bool = False
    trading: bool = False

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.name):
            raise ValueError(f"Invalid integration scope: {self.name}")
        if self.risk not in {"read", "write", "admin"}:
            raise ValueError(f"Invalid integration risk tier: {self.risk}")
        if not self.description.strip():
            raise ValueError("Integration scope descriptions must not be empty")

    @property
    def blocked_via_mcp(self) -> bool:
        """MCP may configure ordinary reads/writes, never powerful actions."""
        return self.risk == "admin" or self.destructive or self.trading

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "destructive": self.destructive,
            "trading": self.trading,
            "configurable_via_mcp": not self.blocked_via_mcp,
        }


@dataclass(frozen=True, slots=True)
class IntegrationSpec:
    """Static metadata for an available, not necessarily installed, connector."""

    integration_id: str
    display_name: str
    category: str
    connector_type: Literal["mcp", "app"]
    description: str
    scopes: tuple[ScopeSpec, ...]

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.integration_id):
            raise ValueError(f"Invalid integration id: {self.integration_id}")
        if self.connector_type not in {"mcp", "app"}:
            raise ValueError(f"Invalid connector type: {self.connector_type}")
        if not self.display_name.strip() or not self.category.strip() or not self.description.strip():
            raise ValueError("Integration catalog text must not be empty")
        names = [scope.name for scope in self.scopes]
        if not names or len(names) != len(set(names)):
            raise ValueError(f"Integration {self.integration_id} must have unique scopes")

    @property
    def scope_map(self) -> dict[str, ScopeSpec]:
        return {scope.name: scope for scope in self.scopes}

    def to_dict(self, include_scope_details: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.integration_id,
            "name": self.display_name,
            "category": self.category,
            "connector_type": self.connector_type,
            "description": self.description,
            "available": True,
        }
        data["allowed_scopes"] = (
            [scope.to_dict() for scope in self.scopes]
            if include_scope_details
            else [scope.name for scope in self.scopes]
        )
        return data
