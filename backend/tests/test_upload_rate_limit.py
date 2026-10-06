"""Tests: Rate-Limit auf Upload-Endpunkten (H-14 / F-06).

Limit: ``UPLOAD_RATE_LIMIT`` (30/Minute; 300/Stunde) pro Client-IP.  Die Requests
müssen nicht erfolgreich sein — das Limit zählt jeden Request.
"""

import pytest

from app.core.rate_limit import limiter

PER_MINUTE = 30


@pytest.fixture(autouse=True)
def _enable_limiter():
    limiter.enabled = True
    limiter.reset()  # In-Memory-Zähler leeren
    yield
    limiter.reset()
    limiter.enabled = False


def _post(client, url, token):
    return client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("a.txt", b"x", "text/plain")},
    )


def test_file_upload_is_rate_limited(client, household_a, token_a):
    url = f"/api/households/{household_a.id}/files/"
    for i in range(PER_MINUTE):
        assert _post(client, url, token_a).status_code != 429, f"Request {i + 1}"
    assert _post(client, url, token_a).status_code == 429


def test_document_upload_is_rate_limited(client, household_a, token_a):
    url = f"/api/households/{household_a.id}/documents/upload"
    for i in range(PER_MINUTE):
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {token_a}"},
            files={"files": ("a.txt", b"x", "text/plain")},
        )
        assert resp.status_code != 429, f"Request {i + 1}"
    resp = client.post(
        url,
        headers={"Authorization": f"Bearer {token_a}"},
        files={"files": ("a.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 429
