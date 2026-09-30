"""Static integration definitions. Availability never implies a live connection."""
from __future__ import annotations

from types import MappingProxyType
from typing import Iterable

from owlthread.integrations.models import IntegrationSpec, RiskTier, ScopeSpec


def scope(name: str, description: str, risk: RiskTier = "read", *,
          destructive: bool = False, trading: bool = False) -> ScopeSpec:
    return ScopeSpec(name, description, risk, destructive, trading)


def spec(integration_id: str, name: str, category: str, connector_type: str,
         description: str, scopes: Iterable[ScopeSpec]) -> IntegrationSpec:
    return IntegrationSpec(integration_id, name, category, connector_type, description, tuple(scopes))  # type: ignore[arg-type]


_CATALOG = (
    spec("cloudflare", "Cloudflare", "Infrastructure", "mcp", "Zones, DNS and Workers with account-scoped grants.", (
        scope("zones.read", "Read zone metadata and settings."),
        scope("dns.read", "Read DNS records."),
        scope("workers.read", "Read Worker metadata."),
        scope("pages.read", "Read Pages project metadata."),
        scope("dns.write", "Create or update DNS records.", "write"),
        scope("workers.deploy", "Create or update Worker deployments.", "write"),
        scope("account.admin", "Change account-wide administration settings.", "admin"),
        scope("zones.delete", "Delete zones or zone resources.", "admin", destructive=True),
    )),
    spec("github", "GitHub", "Development", "mcp", "Repositories, issues and pull requests.", (
        scope("repositories.read", "Read repository metadata and files."),
        scope("issues.read", "Read issues and comments."),
        scope("pull-requests.read", "Read pull requests and reviews."),
        scope("issues.write", "Create or update issues and comments.", "write"),
        scope("pull-requests.write", "Create reviews or update pull requests.", "write"),
        scope("repositories.admin", "Change repository administration settings.", "admin"),
    )),
    spec("gmail", "Gmail", "Communication", "app", "Mailbox search, reading and sending.", (
        scope("messages.read", "Search and read messages."),
        scope("messages.send", "Send messages.", "write"),
        scope("messages.delete", "Delete messages.", "write", destructive=True),
        scope("mailbox.admin", "Change mailbox-wide settings.", "admin"),
    )),
    spec("google-calendar", "Google Calendar", "Productivity", "app", "Calendars and events.", (
        scope("events.read", "Read calendars and events."),
        scope("events.write", "Create or update events.", "write"),
        scope("events.delete", "Delete events.", "write", destructive=True),
        scope("calendars.admin", "Change calendar administration settings.", "admin"),
    )),
    spec("google-drive", "Google Drive", "Files", "app", "Drive files and folders.", (
        scope("files.read", "Search and read files."),
        scope("files.write", "Create or update files.", "write"),
        scope("files.delete", "Delete files or folders.", "write", destructive=True),
        scope("drive.admin", "Change Drive administration settings.", "admin"),
    )),
    spec("dropbox", "Dropbox", "Files", "app", "Dropbox files and folders.", (
        scope("files.read", "Search and read files."), scope("files.write", "Create or update files.", "write"),
        scope("files.delete", "Delete files or folders.", "write", destructive=True),
    )),
    spec("box", "Box", "Files", "app", "Box files, folders and collaborations.", (
        scope("files.read", "Search and read files."), scope("files.write", "Create or update files.", "write"),
        scope("files.delete", "Delete files or folders.", "write", destructive=True), scope("tenant.admin", "Change tenant settings.", "admin"),
    )),
    spec("airtable", "Airtable", "Data", "app", "Bases, tables and records.", (
        scope("records.read", "Read bases, tables and records."), scope("records.write", "Create or update records.", "write"),
        scope("records.delete", "Delete records.", "write", destructive=True), scope("bases.admin", "Change base administration settings.", "admin"),
    )),
    spec("asana", "Asana", "Project Management", "app", "Projects, tasks and comments.", (
        scope("tasks.read", "Read projects and tasks."), scope("tasks.write", "Create or update tasks and comments.", "write"),
        scope("tasks.delete", "Delete tasks.", "write", destructive=True), scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("clickup", "ClickUp", "Project Management", "app", "Spaces, lists and tasks.", (
        scope("tasks.read", "Read spaces, lists and tasks."), scope("tasks.write", "Create or update tasks.", "write"),
        scope("tasks.delete", "Delete tasks.", "write", destructive=True), scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("trello", "Trello", "Project Management", "app", "Boards, lists and cards.", (
        scope("cards.read", "Read boards, lists and cards."), scope("cards.write", "Create or update cards.", "write"),
        scope("cards.delete", "Delete cards.", "write", destructive=True), scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("figma", "Figma", "Design", "app", "Design files, projects and comments.", (
        scope("files.read", "Read design metadata and files."), scope("comments.write", "Create comments.", "write"),
        scope("projects.admin", "Change project administration settings.", "admin"),
    )),
    spec("todoist", "Todoist", "Productivity", "app", "Projects and tasks.", (
        scope("tasks.read", "Read projects and tasks."), scope("tasks.write", "Create or update tasks.", "write"),
        scope("tasks.delete", "Delete tasks.", "write", destructive=True),
    )),
    spec("ticktick", "TickTick", "Productivity", "app", "Lists, tasks and calendar items.", (
        scope("tasks.read", "Read lists and tasks."), scope("tasks.write", "Create or update tasks.", "write"),
        scope("tasks.delete", "Delete tasks.", "write", destructive=True),
    )),
    spec("granola", "Granola", "Meetings", "app", "Meeting notes and summaries.", (
        scope("notes.read", "Read meeting notes."), scope("notes.write", "Create or update meeting notes.", "write"),
        scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("fathom", "Fathom", "Meetings", "app", "Call recordings, transcripts and summaries.", (
        scope("meetings.read", "Read meeting metadata and transcripts."), scope("highlights.write", "Create or update highlights.", "write"),
        scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("plaud", "Plaud", "Meetings", "app", "Recordings, transcripts and notes.", (
        scope("recordings.read", "Read recording metadata and transcripts."), scope("notes.write", "Create or update notes.", "write"),
        scope("recordings.delete", "Delete recordings.", "write", destructive=True),
    )),
    spec("spotify", "Spotify", "Media", "app", "Library, playlists and playback metadata.", (
        scope("library.read", "Read library and playlist metadata."), scope("playlists.write", "Create or update playlists.", "write"),
        scope("library.delete", "Remove saved library items.", "write", destructive=True),
    )),
    spec("apple-music", "Apple Music", "Media", "app", "Library and playlist metadata.", (
        scope("library.read", "Read library and playlist metadata."), scope("playlists.write", "Create or update playlists.", "write"),
        scope("library.delete", "Remove saved library items.", "write", destructive=True),
    )),
    spec("scispace", "SciSpace", "Research", "app", "Research papers and literature search.", (
        scope("papers.read", "Search and read research metadata."), scope("library.write", "Save or annotate library items.", "write"),
        scope("library.delete", "Delete library items.", "write", destructive=True),
    )),
    spec("consensus", "Consensus", "Research", "app", "Evidence search across research literature.", (
        scope("research.read", "Search and read research evidence."), scope("library.write", "Save research items.", "write"),
    )),
    spec("runway", "Runway", "Media", "app", "Generation jobs and project assets.", (
        scope("projects.read", "Read projects and generation metadata."), scope("generations.write", "Create generation jobs.", "write"),
        scope("assets.delete", "Delete project assets.", "write", destructive=True), scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("apollo", "Apollo.io", "Sales", "app", "Contacts, accounts and sequences.", (
        scope("contacts.read", "Search and read contacts and accounts."), scope("contacts.write", "Create or update contacts.", "write"),
        scope("sequences.write", "Add contacts to sequences.", "write"), scope("workspace.admin", "Change workspace settings.", "admin"),
    )),
    spec("maersk", "Maersk", "Logistics", "app", "Shipment schedules and tracking.", (
        scope("shipments.read", "Read schedules and shipment status."), scope("bookings.write", "Create or update shipment bookings.", "write"),
        scope("bookings.cancel", "Cancel shipment bookings.", "write", destructive=True),
    )),
    spec("coinmarketcap", "CoinMarketCap", "Market Data", "app", "Cryptocurrency reference and market data.", (
        scope("market-data.read", "Read cryptocurrency market data."), scope("watchlists.write", "Create or update watchlists.", "write"),
    )),
    spec("coingecko", "CoinGecko", "Market Data", "app", "Cryptocurrency reference and market data.", (
        scope("market-data.read", "Read cryptocurrency market data."), scope("watchlists.write", "Create or update watchlists.", "write"),
    )),
    spec("alpaca", "Alpaca", "Brokerage", "app", "Portfolio, market data and order controls.", (
        scope("market-data.read", "Read market data."), scope("portfolio.read", "Read account positions and balances."),
        scope("orders.place", "Place or modify orders.", "write", trading=True), scope("orders.cancel", "Cancel orders.", "write", destructive=True, trading=True),
        scope("account.admin", "Change brokerage account settings.", "admin"),
    )),
    spec("interactive-brokers", "Interactive Brokers", "Brokerage", "app", "Portfolio, market data and order controls.", (
        scope("market-data.read", "Read market data."), scope("portfolio.read", "Read account positions and balances."),
        scope("orders.place", "Place or modify orders.", "write", trading=True), scope("orders.cancel", "Cancel orders.", "write", destructive=True, trading=True),
        scope("account.admin", "Change brokerage account settings.", "admin"),
    )),
    spec("binance", "Binance", "Exchange", "app", "Balances, market data and order controls.", (
        scope("market-data.read", "Read market data."), scope("balances.read", "Read account balances."),
        scope("orders.place", "Place or modify orders.", "write", trading=True), scope("orders.cancel", "Cancel orders.", "write", destructive=True, trading=True),
        scope("account.admin", "Change exchange account settings.", "admin"),
    )),
)

if len({item.integration_id for item in _CATALOG}) != len(_CATALOG):
    raise RuntimeError("Integration catalog ids must be unique")

CATALOG = MappingProxyType({item.integration_id: item for item in _CATALOG})


def list_catalog() -> tuple[IntegrationSpec, ...]:
    return tuple(CATALOG.values())


def get_spec(integration_id: str) -> IntegrationSpec:
    if not isinstance(integration_id, str) or integration_id not in CATALOG:
        raise ValueError("Unknown integration_id")
    return CATALOG[integration_id]
