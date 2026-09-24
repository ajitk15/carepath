"""Tests for the consent gate on FHIR $everything export.

Covers the approved requirement for "test coverage for granted, withdrawn,
never-asked, and withdrawn-then-regranted consent states, plus unchanged
behavior for a permitted export," and the requirement that a refused export
be written to the audit trail because "a refused disclosure is itself a
disclosure event."

The route handler is exercised as a plain function rather than through an
HTTP client: the evidence gives the body of ``export_everything`` but no
details of ``deps.unit_of_work``, ``deps.require``, or ``security.auth.
Principal``, so ``connection`` and ``principal`` are treated as opaque
values (mocks) exactly as the handler treats them -- it only ever passes
them through to ``consent_service.current``, ``bundle_for``, and ``record``
without inspecting them.
"""

from unittest.mock import MagicMock

import pytest

from carepath.api.routes_fhir import CONSENT_PURPOSE, export_everything
from carepath.errors import ConsentWithheld


def _stub(monkeypatch, *, consent_state, bundle=None):
    """Stub the collaborators export_everything calls: the consent lookup,
    the audit recorder, and the bundle assembler."""
    connection = MagicMock(name="connection")
    principal = MagicMock(name="principal")

    consent_current = MagicMock(return_value=consent_state)
    monkeypatch.setattr(
        "carepath.api.routes_fhir.consent_service.current", consent_current
    )

    record = MagicMock()
    monkeypatch.setattr("carepath.api.routes_fhir.record", record)

    bundle_for = MagicMock(
        return_value=bundle if bundle is not None else {"resourceType": "Bundle"}
    )
    monkeypatch.setattr("carepath.api.routes_fhir.bundle_for", bundle_for)

    return connection, principal, consent_current, record, bundle_for


def test_export_refused_when_consent_withdrawn(monkeypatch):
    """BR-05: an explicitly withdrawn/withheld consent must refuse export
    with the existing ConsentWithheld error (403), not return a bundle."""
    connection, principal, consent_current, record, bundle_for = _stub(
        monkeypatch, consent_state=False
    )

    with pytest.raises(ConsentWithheld):
        export_everything(
            patient_id="patient-withdrawn",
            connection=connection,
            principal=principal,
        )

    consent_current.assert_called_once_with(
        connection, "patient-withdrawn", CONSENT_PURPOSE
    )
    bundle_for.assert_not_called()
    record.assert_called_once_with(
        connection,
        principal,
        "export-refused",
        "patient",
        "patient-withdrawn",
        CONSENT_PURPOSE,
    )


def test_export_refused_when_consent_never_asked(monkeypatch):
    """BR-05: 'withheld or has never been recorded' -- a patient with no
    consent decision on file must be refused the same as one who
    explicitly withheld it."""
    connection, principal, consent_current, record, bundle_for = _stub(
        monkeypatch, consent_state=None
    )

    with pytest.raises(ConsentWithheld):
        export_everything(
            patient_id="patient-never-asked",
            connection=connection,
            principal=principal,
        )

    consent_current.assert_called_once_with(
        connection, "patient-never-asked", CONSENT_PURPOSE
    )
    bundle_for.assert_not_called()
    record.assert_called_once_with(
        connection,
        principal,
        "export-refused",
        "patient",
        "patient-never-asked",
        CONSENT_PURPOSE,
    )


def test_export_refusal_is_written_to_the_audit_trail(monkeypatch):
    """A refused export must itself be audited: 'a refused disclosure is
    itself a disclosure event.'"""
    connection, principal, consent_current, record, bundle_for = _stub(
        monkeypatch, consent_state=False
    )

    with pytest.raises(ConsentWithheld):
        export_everything(
            patient_id="patient-audited-refusal",
            connection=connection,
            principal=principal,
        )

    record.assert_called_once()
    call_args = record.call_args.args
    assert call_args[2] == "export-refused"
    assert call_args[5] == CONSENT_PURPOSE


def test_export_succeeds_when_consent_granted(monkeypatch):
    """Unchanged behavior for a permitted export: granted consent still
    returns the bundle and records an 'export' audit event."""
    bundle = {"resourceType": "Bundle", "entry": []}
    connection, principal, consent_current, record, bundle_for = _stub(
        monkeypatch, consent_state=True, bundle=bundle
    )

    result = export_everything(
        patient_id="patient-granted",
        limit=50,
        connection=connection,
        principal=principal,
    )

    assert result is bundle
    consent_current.assert_called_once_with(
        connection, "patient-granted", CONSENT_PURPOSE
    )
    bundle_for.assert_called_once_with(connection, "patient-granted", 50)
    record.assert_called_once_with(
        connection, principal, "export", "patient", "patient-granted", CONSENT_PURPOSE
    )


def test_export_succeeds_when_consent_withdrawn_then_regranted(monkeypatch):
    """The consent check reflects the patient's *current* decision, so a
    withdrawal followed by a regrant must permit export again, exactly as
    a straightforward grant would."""
    bundle = {"resourceType": "Bundle", "entry": []}
    connection, principal, consent_current, record, bundle_for = _stub(
        monkeypatch, consent_state=True, bundle=bundle
    )

    result = export_everything(
        patient_id="patient-regranted",
        limit=50,
        connection=connection,
        principal=principal,
    )

    assert result is bundle
    consent_current.assert_called_once_with(
        connection, "patient-regranted", CONSENT_PURPOSE
    )
    bundle_for.assert_called_once_with(connection, "patient-regranted", 50)
    record.assert_called_once_with(
        connection,
        principal,
        "export",
        "patient",
        "patient-regranted",
        CONSENT_PURPOSE,
    )


def test_permitted_export_still_honors_the_requested_limit(monkeypatch):
    """Confirms the new consent gate leaves the rest of a permitted export
    unchanged: a non-default limit still reaches bundle_for untouched."""
    bundle = {"resourceType": "Bundle", "entry": []}
    connection, principal, consent_current, record, bundle_for = _stub(
        monkeypatch, consent_state=True, bundle=bundle
    )

    result = export_everything(
        patient_id="patient-custom-limit",
        limit=10,
        connection=connection,
        principal=principal,
    )

    assert result is bundle
    bundle_for.assert_called_once_with(connection, "patient-custom-limit", 10)
