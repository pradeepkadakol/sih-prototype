"""Server-side access to a private Supabase Storage bucket."""

from typing import Protocol
from urllib.parse import quote

import httpx


class StorageError(Exception):
    """A Storage request failed without exposing its credentials to API clients."""


class EvidenceStore(Protocol):
    def upload(self, key: str, content: bytes, mime_type: str) -> None: ...

    def delete(self, key: str) -> None: ...


class SupabaseEvidenceStore:
    def __init__(self, url: str, service_role_key: str, bucket: str, client: httpx.Client | None = None):
        if not url.startswith("https://") or not service_role_key or not bucket:
            raise ValueError("Supabase URL, service role key, and bucket are required")
        self.base_url = url.rstrip("/") + "/storage/v1/object/" + quote(bucket, safe="")
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
        self.client = client or httpx.Client(timeout=30)

    def upload(self, key: str, content: bytes, mime_type: str) -> None:
        try:
            response = self.client.post(
                self.base_url + "/" + quote(key, safe="/"),
                content=content,
                headers={**self.headers, "Content-Type": mime_type, "x-upsert": "false"},
            )
        except httpx.RequestError as exc:
            raise StorageError("Supabase Storage upload is unavailable") from exc
        if response.status_code not in (200, 201):
            raise StorageError(f"Supabase Storage upload failed (HTTP {response.status_code})")

    def delete(self, key: str) -> None:
        try:
            response = self.client.request(
                "DELETE", self.base_url, json={"prefixes": [key]}, headers=self.headers
            )
        except httpx.RequestError as exc:
            raise StorageError("Supabase Storage cleanup is unavailable") from exc
        if response.status_code not in (200, 204):
            raise StorageError(f"Supabase Storage cleanup failed (HTTP {response.status_code})")
