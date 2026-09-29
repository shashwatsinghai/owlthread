"""Shared immutable browser privacy boundary for local ingestion."""
from __future__ import annotations

from urllib.parse import urlsplit


HARD_BLOCKED_SITES: tuple[str, ...] = (
    "youtube.com", "youtu.be", "netflix.com", "primevideo.com", "disneyplus.com",
    "hotstar.com", "hulu.com", "twitch.tv", "spotify.com", "tiktok.com",
    "instagram.com", "facebook.com", "x.com", "twitter.com", "reddit.com",
    "snapchat.com", "pinterest.com", "vimeo.com", "dailymotion.com", "kick.com",
    "soundcloud.com", "discord.com",
)


def normalize_host(hostname: str | None) -> str:
    return (hostname or "").strip().lower().rstrip(".").removeprefix("www.")


def is_hard_blocked_host(hostname: str | None) -> bool:
    clean = normalize_host(hostname)
    return any(clean == site or clean.endswith("." + site) for site in HARD_BLOCKED_SITES)


def is_hard_blocked_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return False
    return parsed.scheme in {"http", "https"} and is_hard_blocked_host(parsed.hostname)
