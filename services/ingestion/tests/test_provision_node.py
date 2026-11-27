"""T030: scripts/provision-node.py validates the manifest and speaks the protocol."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "provision-node.py"
CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
KEY = "-----BEGIN PRIVATE KEY-----\nMIGH\n-----END PRIVATE KEY-----\n"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("provision_node", SCRIPT)
    assert spec
    assert spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prov = _module()


@pytest.fixture
def secrets(tmp_path: Path) -> Path:
    manifest = {
        "node_id": "node-001",
        "wifi_ssid": "lab-wifi",
        "wifi_password": "correct horse",
        "mqtt_host": "broker.lab.internal",
        "mqtt_port": 8883,
    }
    (tmp_path / "secrets.local.node-node-001.json").write_text(json.dumps(manifest))
    (tmp_path / "ca.crt").write_text(CERT)
    (tmp_path / "node-node-001.crt").write_text(CERT)
    (tmp_path / "node-node-001.key").write_text(KEY)
    return tmp_path


def test_lines_follow_the_firmware_protocol(secrets: Path) -> None:
    lines = prov.command_lines(prov.load_values("node-001", secrets))
    assert [ln.split(" ")[1] for ln in lines[:-1]] == list(prov.WIRE_KEYS)
    assert lines[-1] == "commit"
    assert bytes.fromhex(lines[2].split(" ")[2]).decode() == "correct horse"


def test_redaction_hides_values(secrets: Path) -> None:
    for line in prov.command_lines(prov.load_values("node-001", secrets)):
        shown = prov.redacted(line)
        assert "correct" not in shown
        assert "BEGIN" not in shown
        assert line.split(" ")[-1] not in shown or line == "commit"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("wifi_password", "short", "8-63"),
        ("mqtt_host", "bad host", "host name"),
        ("mqtt_port", 70000, "1-65535"),
        ("node_id", "node-002", "does not match"),
    ],
)
def test_bad_manifest_is_refused(secrets: Path, field: str, value: object, message: str) -> None:
    path = secrets / "secrets.local.node-node-001.json"
    doc = json.loads(path.read_text())
    doc[field] = value
    path.write_text(json.dumps(doc))
    with pytest.raises(prov.ManifestError, match=message):
        prov.load_values("node-001", secrets)


def test_missing_key_file_is_refused(secrets: Path) -> None:
    (secrets / "node-node-001.key").unlink()
    with pytest.raises(prov.ManifestError, match="dev-certs"):
        prov.load_values("node-001", secrets)


class FakeLink:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = replies
        self.sent: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.sent.append(data)
        return len(data)

    def readline(self) -> bytes:
        return self.replies.pop(0)


def test_send_skips_log_lines_and_requires_ok() -> None:
    link = FakeLink([b"I (123) wifi: log line\n", b"PROV ok\n", b"PROV ok\n"])
    prov.send(link, ["set node_id 61", "commit"])
    assert link.sent == [b"set node_id 61\n", b"commit\n"]


def test_send_reports_refusal_without_values() -> None:
    link = FakeLink([b"PROV err invalid_value wifi_pass\n"])
    with pytest.raises(RuntimeError, match="invalid_value wifi_pass") as exc:
        prov.send(link, ["set wifi_pass 7365637265742d70617373"])
    assert "7365637265742d70617373" not in str(exc.value)


def test_sync_clears_a_partial_line_before_the_session() -> None:
    """Keys left by a serial monitor end in an error reply, then `abort` answers ok."""
    link = FakeLink([b"PROV err unknown_command\n", b"PROV ok\n"])
    prov.sync(link)
    assert link.sent == [b"\nabort\n"]


def test_sync_times_out_when_the_node_is_silent() -> None:
    link = FakeLink([b""] * 1000)
    with pytest.raises(TimeoutError, match="waiting for provisioning"):
        prov.sync(link, timeout_s=0.0)
