"""Ingestion ledger: exactly-once bookkeeping for measurement messages (T022).

Transitions (data-model.md, IngestionLedger):

    new -> received -> stored
    new -> rejected
    stored -> stored       duplicate retry: publish `duplicate`
    rejected -> rejected   terminal: publish `rejected` again

A message whose `message_id` or `(node_id, boot_id, sequence)` is reused with a
different payload hash is an identity conflict (security/contract event).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from energy_ingestion.persistence.db import IngestionLedger

MAX_DETAIL = 256


class Admission(StrEnum):
    NEW = "new"  # first sight: write the point, then mark_stored
    RESUME = "resume"  # received earlier but not stored: repeat the idempotent write
    DUPLICATE = "duplicate"  # already stored: ACK `duplicate`, no write
    REJECTED = "rejected"  # already rejected: ACK `rejected` again
    CONFLICT = "conflict"  # identity reused with other bytes: reject, raise event


@dataclass(frozen=True)
class MessageIdentity:
    message_id: str
    node_id: str
    boot_id: str
    sequence: int


def payload_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def lookup(
    session: Session, ident: MessageIdentity
) -> tuple[IngestionLedger | None, IngestionLedger | None]:
    """Rows matching the message_id and the (node_id, boot_id, sequence) tuple."""
    by_id = session.get(IngestionLedger, ident.message_id)
    by_tuple = session.scalar(
        select(IngestionLedger).where(
            IngestionLedger.node_id == ident.node_id,
            IngestionLedger.boot_id == ident.boot_id,
            IngestionLedger.sequence == ident.sequence,
        )
    )
    return by_id, by_tuple


def classify(
    by_id: IngestionLedger | None, by_tuple: IngestionLedger | None, sha256: str
) -> tuple[Admission, IngestionLedger | None]:
    """Admission for a message given its ledger matches (no writes)."""
    if by_id is None and by_tuple is None:
        return Admission.NEW, None
    existing = by_id or by_tuple
    assert existing is not None
    if by_id is not by_tuple or existing.payload_sha256 != sha256:
        return Admission.CONFLICT, existing
    match existing.state:
        case "stored":
            return Admission.DUPLICATE, existing
        case "rejected":
            return Admission.REJECTED, existing
        case _:
            return Admission.RESUME, existing


def admit(
    session: Session, ident: MessageIdentity, sha256: str, received_at: datetime
) -> tuple[Admission, IngestionLedger | None]:
    """Classify an incoming message and create its `received` row when new."""
    admission, existing = classify(*lookup(session, ident), sha256)
    if admission is not Admission.NEW:
        return admission, existing
    row = IngestionLedger(
        message_id=ident.message_id,
        node_id=ident.node_id,
        boot_id=ident.boot_id,
        sequence=ident.sequence,
        payload_sha256=sha256,
        state="received",
        received_at=received_at,
        ack_count=0,
    )
    session.add(row)
    session.flush()
    return Admission.NEW, row


def mark_stored(row: IngestionLedger, stored_at: datetime) -> None:
    if row.state not in ("received", "stored"):
        raise ValueError(f"cannot store a {row.state} message")
    if row.state == "received":
        row.state = "stored"
        row.stored_at = stored_at


def record_rejection(
    session: Session,
    ident: MessageIdentity,
    sha256: str,
    received_at: datetime,
    reject_code: str,
    reject_detail: str | None = None,
) -> IngestionLedger:
    """Store a terminal contract rejection (bounded, secret-free diagnostics)."""
    row = session.get(IngestionLedger, ident.message_id)
    if row is None:
        row = IngestionLedger(
            message_id=ident.message_id,
            node_id=ident.node_id,
            boot_id=ident.boot_id,
            sequence=ident.sequence,
            payload_sha256=sha256,
            received_at=received_at,
            ack_count=0,
        )
        session.add(row)
    elif row.state == "stored":
        raise ValueError("a stored message cannot be rejected")
    row.state = "rejected"
    row.reject_code = reject_code[:64]
    row.reject_detail = reject_detail[:MAX_DETAIL] if reject_detail else None
    session.flush()
    return row


def count_ack(row: IngestionLedger) -> None:
    row.ack_count += 1
