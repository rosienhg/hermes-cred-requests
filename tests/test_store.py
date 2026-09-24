"""The request store: normalization, guards, lifecycle, and the on-disk contract."""

from __future__ import annotations

import json
import os
import stat

import pytest

from conftest import file_field, make_request


def test_add_request_persists_a_pending_record(sandbox, store):
    request = make_request(store)

    assert request["status"] == "pending"
    assert request["filled_at"] is None
    assert request["expires_at"] > request["created_at"]
    assert request["id"].startswith("cr-")

    path = sandbox / ".hermes" / "credential-requests.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert [r["id"] for r in on_disk["requests"]] == [request["id"]]


def test_store_file_is_private(sandbox, store):
    make_request(store)
    path = sandbox / ".hermes" / "credential-requests.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_store_never_holds_a_value(sandbox, store, api):
    request = make_request(store)
    secret = "super-secret-value"
    target = sandbox / "secrets" / "token.txt"

    store.add_request(title="File request", fields=[file_field(target)])
    file_request = store.list_requests()[0]

    api._write_secret_file(str(target), secret)

    blob = (sandbox / ".hermes" / "credential-requests.json").read_text(encoding="utf-8")
    assert secret not in blob
    assert request["id"] in blob and file_request["id"] in blob


def test_corrupt_store_is_kept_aside_and_does_not_raise(sandbox, store):
    path = sandbox / ".hermes" / "credential-requests.json"
    path.write_text("{not json", encoding="utf-8")

    assert store.list_requests() == []
    assert path.with_name(path.name + ".corrupt").exists()


def test_request_needs_a_title_and_a_field(store):
    with pytest.raises(ValueError):
        store.add_request(title="  ", fields=[file_field("/tmp/x")])
    with pytest.raises(ValueError):
        store.add_request(title="No fields", fields=[])


def test_field_names_must_be_unique(store):
    with pytest.raises(ValueError):
        store.add_request(
            title="Dupe",
            fields=[
                {"name": "same", "dest": {"kind": "env", "target": "A"}},
                {"name": "same", "dest": {"kind": "env", "target": "B"}},
            ],
        )


def test_ttl_days_is_clamped(store):
    assert store.add_request(title="Long", ttl_days=10000, fields=[
        {"name": "x", "dest": {"kind": "env", "target": "X"}}])["expires_at"] is not None
    request = store.add_request(title="Short", ttl_days=1, fields=[
        {"name": "x", "dest": {"kind": "env", "target": "X"}}])
    assert request["expires_at"] > request["created_at"]


@pytest.mark.parametrize(
    "target",
    [
        "relative/path",
        "/etc/passwd-ish",
        "/tmp/outside-home",
    ],
)
def test_file_destinations_outside_home_are_refused(sandbox, store, target):
    with pytest.raises(ValueError):
        store.add_request(title="Nope", fields=[file_field(target)])


def test_file_destination_inside_hermes_home_is_refused(sandbox, store):
    with pytest.raises(ValueError):
        store.add_request(title="Nope", fields=[file_field(sandbox / ".hermes" / "leak.txt")])


def test_file_destination_accepts_tilde_and_a_directory_is_refused(sandbox, store):
    field = store.normalize_field(file_field("~/.config/acme/token"))
    assert field["dest"]["target"] == str(sandbox / ".config" / "acme" / "token")

    (sandbox / "adir").mkdir()
    with pytest.raises(ValueError):
        store.add_request(title="Nope", fields=[file_field(sandbox / "adir")])


@pytest.mark.parametrize("target", ["9bad", "has space", "", "with-dash"])
def test_invalid_env_names_are_refused(store, target):
    with pytest.raises(ValueError):
        store.add_request(title="Nope", fields=[{"name": "x", "dest": {"kind": "env", "target": target}}])


def test_unknown_destination_kind_is_refused(store):
    with pytest.raises(ValueError):
        store.add_request(title="Nope", fields=[{"name": "x", "dest": {"kind": "carrier-pigeon", "target": "x"}}])


def test_lifecycle_transitions(sandbox, store):
    request = make_request(store)
    assert [r["id"] for r in store.list_requests(include_closed=False)] == [request["id"]]

    store.cancel_request(request["id"])
    assert store.get_request(request["id"])["status"] == "cancelled"
    assert store.list_requests(include_closed=False) == []

    other = make_request(store)
    store.mark_filled(other["id"], [{"field": "TOKEN", "dest": "env:TEST_TOKEN", "at": store.now_iso()}])
    filled = store.get_request(other["id"])
    assert filled["status"] == "filled"
    assert filled["saved"][0]["dest"] == "env:TEST_TOKEN"


def test_expiry_is_computed_not_stored(sandbox, store):
    request = make_request(store)
    data = store.load_store()
    data["requests"][0]["expires_at"] = "2000-01-01T00:00:00+00:00"
    store.save_store(data)

    listed = store.get_request(request["id"])
    assert listed["status"] == "pending" and listed["expired"] is True
    assert store.list_requests(include_closed=False) == []


def test_pending_count_and_deep_link(sandbox, store):
    make_request(store)
    assert store.pending_count() == 1
    request = store.list_requests()[0]
    assert store.deep_link(request["id"]) == f"http://hermes.local/cred-requests?req={request['id']}"

    data = store.load_store()
    data["url_base"] = "https://hermes.example.com/"
    store.save_store(data)
    assert store.deep_link(request["id"]).startswith("https://hermes.example.com/cred-requests?req=")


def test_atomic_write_leaves_no_temp_files(sandbox, store):
    make_request(store)
    leftovers = [p.name for p in (sandbox / ".hermes").iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_os_chmod_is_applied_even_if_the_file_preexisted(sandbox, store):
    path = sandbox / ".hermes" / "credential-requests.json"
    path.write_text(json.dumps({"version": 1, "requests": []}), encoding="utf-8")
    os.chmod(path, 0o644)

    make_request(store)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600