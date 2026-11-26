"""`energyctl`: local management command for the registry (T094, T099; T083 extends it).

Runs on the server host against the SQLite registry (`SQLITE_PATH`, or `--db`).

    energyctl node register --node-id node-001 --display-name "Bench node" \
        --hardware-revision proto-a [--circuit-id lab-load-001 --circuit-name "12 V bulb"]
    energyctl calibration register config/calibration.example.yaml
    energyctl calibration accept REVISION --by "operator A"
    energyctl calibration list [--node node-001]
    energyctl threshold validate config/thresholds.example.yaml

A `nominal` calibration uses datasheet coefficients and no reference meter; every
value derived from it stays labelled "not validated" (constitution 2.0.0). Only
an accepted `reference` calibration would make ingestion label data `validated`.
Calibration rows are immutable once accepted (database triggers).
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import re
import secrets
import ssl
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import yaml
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.contracts.topics import topic_for
from energy_ingestion.contracts.validate import ContractError, validate_payload
from energy_ingestion.persistence.db import (
    CalibrationArtifact,
    Circuit,
    MonitoringNode,
    ThresholdConfiguration,
    make_engine,
    make_session_factory,
    sqlite_url,
    transaction,
)
from energy_ingestion.persistence.influx import InfluxWriter

MVP_MAX_LIMIT_W = Decimal(25)  # plan: 20 W bulb on a 2 A adapter; wire bound is larger
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")

CALIBRATION_FIELDS = {
    "calibration_revision": str,
    "node_id": str,
    "hardware_revision": str,
    "firmware_commit": str,
    "calibration_kind": str,
    "reference_meter_id": str,
    "current_sensor_variant": str,
    "voltage_gain": Decimal,
    "current_gain": Decimal,
    "phase_correction_samples": Decimal,
    "zero_noise_current_a": Decimal,
    "procedure_version": str,
    "dataset_manifest_sha256": str,
}
CALIBRATION_OPTIONAL = {"reference_meter_id"}


class UsageError(Exception):
    """A user-facing error: printed as `error: ...`, exit status 2."""


# ---- helpers ---------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise UsageError(f"{path}: invalid YAML") from exc
    if not isinstance(doc, dict):
        raise UsageError(f"{path}: expected a mapping at the top level")
    return doc


def _decimal(key: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise UsageError(f"{key}: expected a number")
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise UsageError(f"{key}: expected a number") from exc
    if not d.is_finite():
        raise UsageError(f"{key}: must be finite")
    return d


def _emit(doc: dict[str, Any]) -> None:
    print(json.dumps(doc, default=str, sort_keys=True))


# ---- calibration -----------------------------------------------------------------


def parse_calibration(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate a calibration YAML document; return column values for the registry."""
    unknown = sorted(set(doc) - set(CALIBRATION_FIELDS))
    if unknown:
        raise UsageError(f"unknown calibration fields: {', '.join(unknown)}")
    missing = sorted(set(CALIBRATION_FIELDS) - CALIBRATION_OPTIONAL - set(doc))
    if missing:
        raise UsageError(f"missing calibration fields: {', '.join(missing)}")
    out: dict[str, Any] = {}
    for key, kind in CALIBRATION_FIELDS.items():
        value = doc.get(key)
        if value is None:
            out[key] = None
        elif kind is Decimal:
            out[key] = _decimal(key, value)
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()
        else:
            raise UsageError(f"{key}: expected a non-empty string")
    if not 1 <= len(out["calibration_revision"]) <= 64:
        raise UsageError("calibration_revision: 1 to 64 characters")
    if not _ID.match(out["node_id"]):
        raise UsageError("node_id: lowercase letters, digits and hyphens, at most 32")
    if out["calibration_kind"] not in ("nominal", "reference"):
        raise UsageError("calibration_kind: nominal or reference")
    if (out["calibration_kind"] == "reference") != (out["reference_meter_id"] is not None):
        raise UsageError("reference_meter_id is required for reference and forbidden for nominal")
    if out["current_sensor_variant"] not in ("05B", "20A", "30A"):
        raise UsageError("current_sensor_variant: 05B, 20A or 30A")
    if not _COMMIT.match(out["firmware_commit"]):
        raise UsageError("firmware_commit: a lowercase hex git commit")
    if not _SHA256.match(out["dataset_manifest_sha256"]):
        raise UsageError("dataset_manifest_sha256: 64 lowercase hex characters")
    for key in ("voltage_gain", "current_gain"):
        if out[key] <= 0:
            raise UsageError(f"{key}: must be positive")
    if out["zero_noise_current_a"] < 0:
        raise UsageError("zero_noise_current_a: must not be negative")
    if abs(out["phase_correction_samples"]) > 4:
        raise UsageError("phase_correction_samples: at most 4 samples either way")
    return out


def calibration_register(sessions: sessionmaker[Session], path: Path) -> dict[str, Any]:
    values = parse_calibration(_load_yaml(path))
    with transaction(sessions) as s:
        if s.get(MonitoringNode, values["node_id"]) is None:
            raise UsageError(
                f"node {values['node_id']} is not registered (energyctl node register)"
            )
        existing = s.get(CalibrationArtifact, values["calibration_revision"])
        if existing is not None:
            raise UsageError(
                f"calibration {values['calibration_revision']} already exists; "
                "revisions are immutable, register a new revision"
            )
        s.add(CalibrationArtifact(**values))
    return {"registered": values["calibration_revision"], "kind": values["calibration_kind"]}


def calibration_accept(
    sessions: sessionmaker[Session], revision: str, by: str, now: datetime | None = None
) -> dict[str, Any]:
    if not by.strip():
        raise UsageError("--by: the accepting operator is required")
    with transaction(sessions) as s:
        cal = s.get(CalibrationArtifact, revision)
        if cal is None:
            raise UsageError(f"calibration {revision} not found")
        if cal.accepted_at is not None:
            raise UsageError(f"calibration {revision} was already accepted")
        cal.accepted_at = now or datetime.now(UTC)
        cal.accepted_by = by.strip()
        node = s.get(MonitoringNode, cal.node_id)
        if node is not None:
            node.calibration_revision = revision
    return {"accepted": revision, "by": by.strip(), "validation": label_for(cal)}


def label_for(cal: CalibrationArtifact) -> str:
    accepted_reference = cal.calibration_kind == "reference" and cal.accepted_at is not None
    return "validated" if accepted_reference else "not_validated"


def calibration_list(sessions: sessionmaker[Session], node: str | None) -> list[dict[str, Any]]:
    with sessions() as s:
        query = select(CalibrationArtifact).order_by(CalibrationArtifact.calibration_revision)
        if node is not None:
            query = query.where(CalibrationArtifact.node_id == node)
        return [
            {
                "calibration_revision": c.calibration_revision,
                "node_id": c.node_id,
                "kind": c.calibration_kind,
                "accepted_at": c.accepted_at,
                "accepted_by": c.accepted_by,
                "validation": label_for(c),
            }
            for c in s.scalars(query)
        ]


# ---- nodes -----------------------------------------------------------------------


def node_register(
    sessions: sessionmaker[Session],
    node_id: str,
    display_name: str,
    hardware_revision: str,
    circuit_id: str | None = None,
    circuit_name: str | None = None,
) -> dict[str, Any]:
    if not _ID.match(node_id):
        raise UsageError("--node-id: lowercase letters, digits and hyphens, at most 32")
    if circuit_id is not None and not _ID.match(circuit_id):
        raise UsageError("--circuit-id: lowercase letters, digits and hyphens, at most 32")
    try:
        with transaction(sessions) as s:
            s.add(
                MonitoringNode(
                    node_id=node_id,
                    display_name=display_name,
                    certificate_subject=f"CN={node_id}",
                    hardware_revision=hardware_revision,
                )
            )
            s.flush()
            if circuit_id is not None:
                s.add(
                    Circuit(
                        circuit_id=circuit_id,
                        node_id=node_id,
                        display_name=circuit_name or circuit_id,
                    )
                )
    except IntegrityError as exc:
        raise UsageError(f"node {node_id} or circuit {circuit_id} already exists") from exc
    return {"registered": node_id, "circuit_id": circuit_id}


# ---- thresholds ------------------------------------------------------------------


def threshold_validate(path: Path) -> dict[str, Any]:
    """Check a threshold file against the contract and the MVP bounds (no storage yet: T083)."""
    doc = _load_yaml(path)
    if isinstance(doc.get("effective_at"), datetime):  # YAML parses bare timestamps
        doc["effective_at"] = (
            doc["effective_at"].astimezone(UTC).isoformat(timespec="milliseconds")
        ).replace("+00:00", "Z")
    try:
        validate_payload("threshold-config", json.dumps(doc).encode())
    except ContractError as exc:
        raise UsageError(f"{path}: {exc.reason_code}: {exc.detail}") from exc
    limit = _decimal("active_power_limit_W", doc["active_power_limit_W"])
    clear = _decimal("clear_below_W", doc["clear_below_W"])
    if limit > MVP_MAX_LIMIT_W:
        raise UsageError(f"active_power_limit_W: {limit} W is above the MVP bound of 25 W")
    if not 0 <= clear < limit:
        raise UsageError("clear_below_W: must be at least 0 and below active_power_limit_W")
    return {"valid": str(path), "node_id": doc["node_id"], "limit_W": float(limit)}


def publish_threshold_config(node_id: str, payload: bytes) -> None:
    """Publish retained config as the authenticated ingestion service identity."""
    try:
        ca_file = os.environ["MQTT_CA_FILE"]
        cert_file = os.environ["MQTT_CERT_FILE"]
        key_file = os.environ["MQTT_KEY_FILE"]
    except KeyError as exc:
        raise UsageError(f"missing MQTT client configuration: {exc.args[0]}") from exc
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"energyctl-{node_id}-{secrets.token_hex(4)}",
        protocol=mqtt.MQTTv5,
    )
    host = os.environ.get("MQTT_HOST", "mosquitto")
    try:
        port = int(os.environ.get("MQTT_PORT", "8883"))
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
        client.tls_set_context(ctx)
        client.connect(host, port, keepalive=30)
        client.loop_start()
        info = client.publish(topic_for(node_id, "config"), payload, qos=1, retain=True)
        info.wait_for_publish(timeout=10)
        if not info.is_published():
            raise TimeoutError("broker did not acknowledge retained threshold config")
    except Exception as exc:
        raise UsageError(f"threshold config publish failed: {type(exc).__name__}") from exc
    finally:
        try:
            client.disconnect()
            client.loop_stop()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "threshold MQTT client cleanup failed: %s", type(exc).__name__
            )


def threshold_publish(
    sessions: sessionmaker[Session],
    path: Path,
    created_by: str,
    publisher: Any | None = None,
) -> dict[str, Any]:
    """Validate, persist, and publish one strictly newer threshold revision."""
    if not created_by.strip():
        raise UsageError("--by: the operating user is required")
    threshold_validate(path)
    doc = _load_yaml(path)
    effective_at = doc["effective_at"]
    if isinstance(effective_at, datetime):
        effective_at = (
            effective_at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    doc["effective_at"] = str(effective_at)
    wire_payload = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode("utf-8")
    limit = _decimal("active_power_limit_W", doc["active_power_limit_W"])
    clear = _decimal("clear_below_W", doc["clear_below_W"])
    node_id = str(doc["node_id"])
    circuit_id = str(doc["circuit_id"])
    config_version = int(doc["config_version"])
    effective = datetime.fromisoformat(doc["effective_at"].replace("Z", "+00:00"))

    with transaction(sessions) as session:
        if session.get(MonitoringNode, node_id) is None:
            raise UsageError(f"node {node_id} is not registered")
        circuit = session.get(Circuit, circuit_id)
        if circuit is None or circuit.node_id != node_id:
            raise UsageError(f"circuit {circuit_id} is not registered to node {node_id}")
        latest = session.scalar(
            select(func.max(ThresholdConfiguration.config_version)).where(
                ThresholdConfiguration.node_id == node_id
            )
        )
        if latest is not None and config_version <= latest:
            raise UsageError(
                f"config_version {config_version} must be greater than stored version {latest}"
            )
        session.add(
            ThresholdConfiguration(
                node_id=node_id,
                config_version=config_version,
                circuit_id=circuit_id,
                active_power_limit_w=limit,
                confirm_ms=int(doc["confirm_ms"]),
                clear_below_w=clear,
                clear_ms=int(doc["clear_ms"]),
                severity=str(doc["severity"]),
                local_warning_enabled=bool(doc["local_warning_enabled"]),
                effective_at=effective,
                created_by=created_by.strip(),
            )
        )
        session.flush()
        (publisher or publish_threshold_config)(node_id, wire_payload)

    return {
        "node_id": node_id,
        "config_version": config_version,
        "created_by": created_by.strip(),
        "stored": True,
        "published": True,
    }


def threshold_show(sessions: sessionmaker[Session], node_id: str) -> dict[str, Any]:
    with sessions() as session:
        row = session.scalar(
            select(ThresholdConfiguration)
            .where(ThresholdConfiguration.node_id == node_id)
            .order_by(ThresholdConfiguration.config_version.desc())
            .limit(1)
        )
        if row is None:
            raise UsageError(f"no threshold configuration stored for node {node_id}")
        return {
            "node_id": row.node_id,
            "config_version": row.config_version,
            "circuit_id": row.circuit_id,
            "active_power_limit_W": row.active_power_limit_w,
            "confirm_ms": row.confirm_ms,
            "clear_below_W": row.clear_below_w,
            "clear_ms": row.clear_ms,
            "severity": row.severity,
            "local_warning_enabled": row.local_warning_enabled,
            "effective_at": row.effective_at,
            "created_by": row.created_by,
        }


def _alert_document(alert: Any) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "event_id": alert.event_id,
        "node_id": alert.node_id,
        "circuit_id": alert.circuit_id,
        "kind": alert.kind,
        "severity": alert.severity,
        "status": alert.status,
        "opened_at": alert.opened_at,
        "acknowledged_at": alert.acknowledged_at,
        "resolved_at": alert.resolved_at,
        "observed_value": alert.observed_value,
        "threshold_value": alert.threshold_value,
        "unit": alert.unit,
        "quality": alert.quality,
    }


def alert_list(sessions: sessionmaker[Session], status: str | None) -> list[dict[str, Any]]:
    try:
        from energy_ingestion.thresholds import alerts
    except ImportError as exc:
        raise UsageError("alert lifecycle is not available") from exc
    with sessions() as session:
        return [_alert_document(row) for row in alerts.list_alerts(session, status)]


def alert_ack(
    sessions: sessionmaker[Session],
    alert_id: str,
    actor: str,
    writer: InfluxWriter | None = None,
) -> dict[str, Any]:
    if not actor.strip():
        raise UsageError("--by: the operating user is required")
    try:
        from energy_ingestion.thresholds import alerts
    except ImportError as exc:
        raise UsageError("alert lifecycle is not available") from exc
    try:
        with transaction(sessions) as session:
            now = datetime.now(UTC)
            if writer is None:
                row = alerts.acknowledge(session, alert_id, actor.strip(), now)
            else:
                row = alerts.acknowledge(session, alert_id, actor.strip(), now, writer=writer)
            result = _alert_document(row)
    except KeyError as exc:
        raise UsageError(f"alert {alert_id} not found") from exc
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    return result


# ---- entry point -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="energyctl", description=__doc__.split("\n", 1)[0])
    p.add_argument("--db", help="SQLAlchemy URL (default: sqlite:///$SQLITE_PATH)")
    sub = p.add_subparsers(dest="group", required=True)

    node = sub.add_parser("node", help="monitoring nodes").add_subparsers(dest="cmd", required=True)
    reg = node.add_parser("register", help="register a node and, optionally, its circuit")
    reg.add_argument("--node-id", required=True)
    reg.add_argument("--display-name", required=True)
    reg.add_argument("--hardware-revision", required=True)
    reg.add_argument("--circuit-id")
    reg.add_argument("--circuit-name")

    cal = sub.add_parser("calibration", help="calibration registry").add_subparsers(
        dest="cmd", required=True
    )
    creg = cal.add_parser("register", help="register a calibration revision from YAML")
    creg.add_argument("file", type=Path)
    acc = cal.add_parser("accept", help="accept a registered revision (irreversible)")
    acc.add_argument("revision")
    acc.add_argument("--by", required=True, help="accepting operator")
    lst = cal.add_parser("list", help="list calibration revisions")
    lst.add_argument("--node")

    thr = sub.add_parser("threshold", help="threshold configuration").add_subparsers(
        dest="cmd", required=True
    )
    val = thr.add_parser("validate", help="check a threshold YAML file (limit at most 25 W)")
    val.add_argument("file", type=Path)
    pub = thr.add_parser("publish", help="store and publish a retained threshold config")
    pub.add_argument("file", type=Path)
    pub.add_argument("--by", required=True, help="operating user")
    show = thr.add_parser("show", help="show the latest stored threshold config")
    show.add_argument("node")

    alert = sub.add_parser("alert", help="alert lifecycle")
    alert_sub = alert.add_subparsers(dest="cmd", required=True)
    alert_list_parser = alert_sub.add_parser("list", help="list alerts")
    alert_list_parser.add_argument("--status", choices=("open", "acknowledged", "resolved"))
    ack = alert_sub.add_parser("ack", help="acknowledge an alert")
    ack.add_argument("alert_id")
    ack.add_argument("--by", default=getpass.getuser(), help="operating user")
    return p


def run(args: argparse.Namespace) -> Any:
    if (args.group, args.cmd) == ("threshold", "validate"):
        return threshold_validate(args.file)
    if args.group == "alert":
        engine = make_engine(args.db or sqlite_url())
        sessions = make_session_factory(engine)
        try:
            if args.cmd == "list":
                return alert_list(sessions, args.status)
            try:
                writer = InfluxWriter.from_env()
            except (KeyError, OSError) as exc:
                logging.getLogger(__name__).warning(
                    "alert acknowledgment operations writer unavailable: %s",
                    type(exc).__name__,
                )
                writer = None
            try:
                return alert_ack(sessions, args.alert_id, args.by, writer)
            finally:
                if writer is not None:
                    writer.close()
        finally:
            engine.dispose()
    if args.group == "threshold" and args.cmd == "publish":
        engine = make_engine(args.db or sqlite_url())
        sessions = make_session_factory(engine)
        try:
            return threshold_publish(sessions, args.file, args.by)
        finally:
            engine.dispose()
    if args.group == "threshold" and args.cmd == "show":
        engine = make_engine(args.db or sqlite_url())
        sessions = make_session_factory(engine)
        try:
            return threshold_show(sessions, args.node)
        finally:
            engine.dispose()
    engine = make_engine(args.db or sqlite_url())
    sessions = make_session_factory(engine)
    try:
        if args.group == "node":
            return node_register(
                sessions,
                args.node_id,
                args.display_name,
                args.hardware_revision,
                args.circuit_id,
                args.circuit_name,
            )
        if args.cmd == "register":
            return calibration_register(sessions, args.file)
        if args.cmd == "accept":
            return calibration_accept(sessions, args.revision, args.by)
        return calibration_list(sessions, args.node)
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for doc in result if isinstance(result, list) else [result]:
        _emit(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
