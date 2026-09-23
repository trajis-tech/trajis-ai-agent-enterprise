from __future__ import annotations


def rewrite_location(value: str, upstream: str) -> str:
    base = upstream.rstrip("/")
    if value.startswith(base):
        rest = value[len(base) :] or "/"
        if not rest.startswith("/"):
            rest = "/" + rest
        return "/n8n" + rest
    if value.startswith("/") and not value.startswith("/n8n"):
        return "/n8n" + value
    return value
