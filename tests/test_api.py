import logging
import socket
from pathlib import Path

import pytest

from claimtrace.core.models import Commitment

from .conftest import EXAMPLES, make_client

CANARY = "ZEBRA-CANARY-7731"


def _upload(client, name, text, **form):
    return client.post("/documents", files={"file": (name, text.encode() if isinstance(text, str) else text)},
                       data=form)


def test_health_exposes_no_secrets(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and "api_key" not in str(body).lower()


def test_full_flow_upload_analyze_poll_ask_review_report(client, store):
    r = _upload(client, "msa.md", (EXAMPLES / "msa-v1.md").read_text())
    assert r.status_code == 201
    doc = r.json()
    run = client.post(f"/documents/{doc['id']}/analyze").json()
    assert run["poll"].startswith("/runs/")
    again = client.post(f"/documents/{doc['id']}/analyze").json()  # idempotent
    assert again["run"]["id"] == run["run"]["id"]
    assert client.get(run["poll"]).json()["status"] == "done"
    cs = client.get(f"/documents/{doc['id']}/commitments?type=obligation").json()
    assert cs and all(c["type"] == "obligation" for c in cs)
    ans = client.post("/ask", json={"question": "How many days does the customer have to pay?"}).json()
    rv = client.post(f"/answers/{ans['id']}/review", json={"decision": "accept", "reviewer": "Sam"})
    assert rv.status_code == 200 and rv.json()["reviewer_verified"] is False
    assert client.get(f"/answers/{ans['id']}").json()["review_status"] == "accepted"
    c0 = cs[0]["id"]
    client.post(f"/commitments/{c0}/review", json={"decision": "resolve", "reviewer": "Sam", "lifecycle": "fulfilled"})
    assert store.get_object(Commitment, c0).status.value == "fulfilled"
    for fmt in ("json", "md", "html"):
        assert client.get(f"/documents/{doc['id']}/report?format={fmt}").status_code == 200
    rep = client.get(f"/documents/{doc['id']}/report?format=json").json()
    assert rep["summary"]["integrity_failures"] == 0 and rep["review_trail"]


def test_samples_and_verify(client):
    ids = client.post("/samples").json()["loaded"]
    run = client.post("/verify", json={"base_document_id": ids[0], "other_document_id": ids[1]}).json()
    assert run["mode"] == "amendment" and run["summary"]["contradicted"] >= 4
    f = run["findings"][0]["id"]
    client.post(f"/findings/{f}/review", json={"decision": "request_evidence", "reviewer": "Ana", "note": "check"})
    client.post(f"/findings/{f}/review", json={"decision": "resolve", "reviewer": "Ana"})
    trail = client.get(f"/reviews/{f}").json()
    assert [t["decision"] for t in trail] == ["request_evidence", "resolve"]  # history kept
    assert trail[1]["prior_status"] == "needs_evidence"


def test_structured_errors(client):
    assert client.get("/documents/doc_nope").json()["error"]["code"] == "not_found"
    bad = client.post("/ask", json={"question": "x" * 2000})
    assert bad.status_code == 422 and "x" * 50 not in bad.text  # never echo input
    assert client.post("/documents", files={"file": ("a.exe", b"MZ")}).status_code == 415


def test_xss_is_inert_in_reports_and_csv(client):
    evil = ('---\ntitle: <script>alert(1)</script>\n---\nThis Agreement is between Acme Ltd (the "Supplier") and '
            'Bolt plc (the "Customer").\n\n1.1 The Supplier shall deliver <img src=x onerror=alert(1)> by 1 June 2026.\n\n'
            '1.2 The Supplier shall send =HYPERLINK("http://evil") reports weekly.')
    doc = _upload(client, "evil.md", evil).json()
    client.post(f"/documents/{doc['id']}/analyze")
    html = client.get(f"/documents/{doc['id']}/report?format=html")
    assert "<script>alert" not in html.text and "<img src=x" not in html.text
    assert "default-src 'none'" in html.headers["content-security-policy"]
    csv = client.get(f"/documents/{doc['id']}/deadlines.csv").text
    assert ",=HYPERLINK" not in csv and '"=HYPERLINK' not in csv


def test_cross_origin_unsafe_requests_refused(client):
    ids = client.post("/samples").json()["loaded"]
    r = client.delete(f"/documents/{ids[0]}", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get(f"/documents/{ids[0]}").status_code == 200


def test_dns_rebinding_host_refused(client):
    assert client.get("/documents", headers={"host": "attacker.example"}).status_code == 400


def test_token_auth(store):
    c = make_client(store, api_token="s3cret-token")
    assert c.get("/documents").status_code == 401
    assert c.get("/documents", headers={"authorization": "Bearer s3cret-token"}).status_code == 200
    assert c.get("/health").status_code == 200


def test_non_loopback_without_token_refuses_to_start(store):
    with pytest.raises(RuntimeError):
        make_client(store, host="0.0.0.0")


def test_rate_limit(store):
    c = make_client(store, rate_limit_per_minute=3)
    codes = [c.get("/documents").status_code for _ in range(5)]
    assert 429 in codes


def test_url_ingestion_disabled_by_default(client):
    r = client.post("/documents", data={"url": "https://example.com/a.pdf"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "url_ingestion_disabled"


def test_delete_erases_content_including_db_file(tmp_path):
    from claimtrace.core.store import Store

    db = tmp_path / "ct.db"
    store = Store(str(db))
    c = make_client(store)
    text = (f'This Agreement is between Acme Ltd (the "Supplier") and Bolt plc (the "Customer").\n\n'
            f"1.1 The Supplier shall deliver {CANARY} by 1 June 2026.")
    doc = _upload(c, "canary.md", text).json()
    c.post(f"/documents/{doc['id']}/analyze")
    ans = c.post("/ask", json={"question": f"When must the Supplier deliver {CANARY}?"}).json()
    cmt = c.get(f"/documents/{doc['id']}/commitments").json()[0]["id"]
    c.post(f"/commitments/{cmt}/review", json={"decision": "note", "reviewer": "Sam", "note": f"see {CANARY}"})
    assert c.delete(f"/documents/{doc['id']}").status_code == 200
    assert c.get(f"/answers/{ans['id']}").status_code == 404
    store.conn.close()
    for f in Path(tmp_path).iterdir():
        assert CANARY.encode() not in f.read_bytes(), f"canary survived in {f.name}"
    assert Store(str(db)).tombstones()[0]["document_id"] == doc["id"]


def test_no_outbound_network_and_no_content_in_logs(client, monkeypatch, caplog):
    real_connect = socket.socket.connect

    def guard(self, addr):  # only loopback/unix sockets are allowed in the default configuration
        host = addr[0] if isinstance(addr, tuple) else "unix"
        if host not in ("127.0.0.1", "::1", "localhost", "unix"):
            raise AssertionError(f"unexpected outbound connection to {host}")
        return real_connect(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guard)
    logging.getLogger("claimtrace").setLevel(logging.INFO)
    logging.getLogger("claimtrace").addHandler(caplog.handler)
    ids = client.post("/samples").json()["loaded"]
    client.post("/ask", json={"question": "Is customer data kept in the UK?"})
    client.post("/verify", json={"base_document_id": ids[0], "other_document_id": ids[2]})
    logged = caplog.text
    assert "Dublin" not in logged and "United Kingdom" not in logged and "customer data" not in logged.lower()
    assert "msa-v1.md" not in logged  # filenames are personal data too
