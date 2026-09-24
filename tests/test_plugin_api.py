"""The dashboard backend: validation, both destination kinds, and the single-use contract.

The env-destination tests need the Hermes source tree (they exercise the real
``hermes_cli.config.save_env_value``) and skip without it; everything else runs anywhere.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from conftest import API_PREFIX, file_field, make_request

REQUESTS = f"{API_PREFIX}/requests"
FULFILL = f"{API_PREFIX}/fulfill"
CANCEL = f"{API_PREFIX}/cancel"


def _file_request(store, target, extra_fields=()):
    return store.add_request(
        title="File request",
        why="file destination",
        fields=[file_field(target), *extra_fields],
    )


def test_list_requests_exposes_destinations_but_no_values(client, store):
    request = make_request(store)

    response = client.get(REQUESTS)
    assert response.status_code == 200
    body = response.json()

    assert body["pending_count"] == 1
    assert body["tab_path"] == "/cred-requests"
    assert body["requests"][0]["id"] == request["id"]
    assert body["requests"][0]["fields"][0]["dest"] == {"kind": "env", "target": "TEST_TOKEN"}
    assert "value" not in json.dumps(body)


def test_fulfill_env_destination(client, store, hermes_config, sandbox):
    request = make_request(store)
    secret = "env-secret-value"

    response = client.post(FULFILL, json={"id": request["id"], "values": {"TOKEN": secret}})

    assert response.status_code == 200, response.text
    assert secret not in response.text
    assert response.json()["saved"] == [{"field": "TOKEN", "dest": "env:TEST_TOKEN"}]

    env_path = sandbox / ".hermes" / ".env"
    assert f"TEST_TOKEN={secret}" in env_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert store.get_request(request["id"])["status"] == "filled"


def test_fulfill_file_destination_writes_exact_bytes_0600(client, store, sandbox):
    target = sandbox / "secrets" / "nested" / "token.txt"
    request = _file_request(store, target)
    secret = "file-secret-value"          # deliberately no trailing newline

    response = client.post(FULFILL, json={"id": request["id"], "values": {"token": secret}})

    assert response.status_code == 200, response.text
    assert target.read_text(encoding="utf-8") == secret
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_refill_is_refused_and_does_not_overwrite(client, store, sandbox):
    target = sandbox / "token.txt"
    request = _file_request(store, target)
    assert client.post(FULFILL, json={"id": request["id"], "values": {"token": "first"}}).status_code == 200

    again = client.post(FULFILL, json={"id": request["id"], "values": {"token": "second"}})

    assert again.status_code == 409
    assert target.read_text(encoding="utf-8") == "first"


@pytest.mark.parametrize(
    "values, expected",
    [
        ({}, "still missing"),
        ({"TOKEN": "   "}, "still missing"),
        ({"TOKEN": "x", "nope": "y"}, "unknown field"),
    ],
)
def test_bad_values_are_rejected(client, store, values, expected):
    request = make_request(store)
    response = client.post(FULFILL, json={"id": request["id"], "values": values})
    assert response.status_code == 400
    assert expected in response.json()["detail"]


def test_oversized_value_is_rejected(client, store):
    request = make_request(store)
    response = client.post(FULFILL, json={"id": request["id"], "values": {"TOKEN": "x" * (16 * 1024 + 1)}})
    assert response.status_code == 400
    assert "too long" in response.json()["detail"]


def test_unknown_request_is_404(client):
    assert client.post(FULFILL, json={"id": "cr-nope", "values": {}}).status_code == 404
    assert client.post(CANCEL, json={"id": "cr-nope"}).status_code == 404


def test_expired_request_is_refused_and_closed(client, store):
    request = make_request(store)
    data = store.load_store()
    data["requests"][0]["expires_at"] = "2000-01-01T00:00:00+00:00"
    store.save_store(data)

    response = client.post(FULFILL, json={"id": request["id"], "values": {"TOKEN": "late"}})

    assert response.status_code == 409
    assert "expired" in response.json()["detail"]
    assert store.get_request(request["id"])["status"] == "cancelled"


def test_cancel_closes_a_pending_request(client, store):
    request = make_request(store)
    response = client.post(CANCEL, json={"id": request["id"]})
    assert response.status_code == 200
    assert store.get_request(request["id"])["status"] == "cancelled"
    assert store.pending_count() == 0


def test_symlink_destination_is_refused_without_writing(client, store, sandbox):
    real = sandbox / "real.txt"
    real.write_text("untouched", encoding="utf-8")
    link = sandbox / "link.txt"
    os.symlink(real, link)
    request = _file_request(store, link)

    response = client.post(FULFILL, json={"id": request["id"], "values": {"token": "new"}})

    assert response.status_code == 500
    assert "symlink" in response.json()["detail"]
    assert real.read_text(encoding="utf-8") == "untouched"
    assert store.get_request(request["id"])["status"] == "pending"


def test_partial_failure_records_what_landed_and_keeps_the_request_open(client, store, hermes_config, sandbox):
    link = sandbox / "link.txt"
    os.symlink(sandbox / "elsewhere.txt", link)
    request = store.add_request(
        title="Mixed request",
        fields=[
            {"name": "ok", "label": "Env part", "dest": {"kind": "env", "target": "TEST_PARTIAL"}},
            file_field(link, label="Broken part"),
        ],
    )

    response = client.post(FULFILL, json={"id": request["id"], "values": {"ok": "lands", "token": "fails"}})

    assert response.status_code == 500
    stored = store.get_request(request["id"])
    assert stored["status"] == "pending"
    assert [entry["dest"] for entry in stored["saved"]] == ["env:TEST_PARTIAL"]
    assert "partial save" in stored["note"]
    assert "TEST_PARTIAL=lands" in (sandbox / ".hermes" / ".env").read_text(encoding="utf-8")


def test_saved_destinations_carry_no_values(client, store, sandbox):
    target = sandbox / "token.txt"
    request = _file_request(store, target)
    secret = "value-that-must-not-be-stored"
    client.post(FULFILL, json={"id": request["id"], "values": {"token": secret}})

    blob = (sandbox / ".hermes" / "credential-requests.json").read_text(encoding="utf-8")
    assert secret not in blob
    assert json.loads(blob)["requests"][0]["saved"][0]["dest"] == f"file:{target}"