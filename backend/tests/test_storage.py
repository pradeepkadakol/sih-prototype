import httpx
import pytest

from app.storage import StorageError, SupabaseEvidenceStore


def test_upload_uses_private_server_key_and_content_type():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"Key": "evidence/inspections/7/photo.png"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    store = SupabaseEvidenceStore("https://project.supabase.co", "test-service-key", "evidence", client=client)
    store.upload("inspections/7/photo.png", b"image-bytes", "image/png")
    request = requests[0]
    assert str(request.url) == "https://project.supabase.co/storage/v1/object/evidence/inspections/7/photo.png"
    assert request.headers["authorization"] == "Bearer test-service-key"
    assert request.headers["apikey"] == "test-service-key"
    assert request.headers["content-type"] == "image/png"
    assert request.content == b"image-bytes"


def test_storage_delete_uses_api():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    store = SupabaseEvidenceStore("https://project.supabase.co", "test-service-key", "evidence", client=httpx.Client(transport=httpx.MockTransport(respond)))
    store.delete("inspections/7/photo.png")
    assert requests[0].method == "DELETE"
    assert str(requests[0].url) == "https://project.supabase.co/storage/v1/object/evidence"
    assert requests[0].read() == b'{"prefixes":["inspections/7/photo.png"]}'


def test_storage_failure_raises_safe_error():
    store = SupabaseEvidenceStore("https://project.supabase.co", "test-service-key", "evidence", client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))))
    with pytest.raises(StorageError, match="403") as exc:
        store.upload("inspections/7/photo.png", b"image", "image/png")
    assert "test-service-key" not in str(exc.value)
