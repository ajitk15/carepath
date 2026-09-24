"""Tests for the FHIR $everything export route: consent gating and audit logging.

Scope of what is tested here, and why:

- The approved changes describe refusing export on withheld/never-recorded
  consent by raising the existing `ConsentWithheld` error, which is "already
  mapped to HTTP 403". No evidence of the FastAPI app assembly, exception
  handlers, or a TestClient fixture was supplied, so these tests call
  `export_everything` directly as a plain function and assert on the raised
  exception, not on an HTTP response/status code. The 403 mapping itself is
  outside what this evidence settles.

- The approved changes also describe wiring a purpose-built masked schema
  into `export_everything` for minimum-necessary field restriction (the
  "existence confirmation only" case). The `routes_fhir.py` content supplied
  as "the file as it will be after the change" contains no such wiring -
  only the consent check and audit logging are present. No test for masked
  fields is written here, because there is nothing in the shown
  implementation to exercise; this gap should be resolved before that part
  of the approved change can be verified.

- `Principal`'s internal shape is not part of the supplied evidence, and
  `export_everything` never inspects it - it is only forwarded opaquely to
  `record()` - so a bare sentinel object stands in for it below.
"""

from unittest.mock import MagicMock

import pytest

from carepath.api import routes_fhir
from carepath.errors import ConsentWithheld


class FakePrincipal:
    """Stand-in for security.auth.Principal; only ever forwarded, never read."""


@pytest.fixture
def connection():
    return object()


@pytest.fixture
def principal():
    return FakePrincipal()


def test_export_refused_when_consent_withheld(monkeypatch, connection, principal):
    monkeypatch.setattr(routes_fhir.consent, "current", MagicMock(return_value=False))
    fake_record = MagicMock()
    fake_bundle_for = MagicMock()
    monkeypatch.setattr(routes_fhir, "record", fake_record)
    monkeypatch.setattr(routes_fhir, "bundle_for", fake_bundle_for)

    with pytest.raises(ConsentWithheld) as excinfo:
        routes_fhir.export_everything(
            patient_id="patient-1",
            limit=50,
            connection=connection,
            principal=principal,
        )

    assert str(excinfo.value) == "consent withheld or never recorded for patient patient-1"
    routes_fhir.consent.current.assert_called_once_with(connection, "patient-1", "data-exchange")
    fake_bundle_for.assert_not_called()
    fake_record.assert_called_once_with(
        connection,
        principal,
        "export-refused",
        "patient",
        "patient-1",
        "data-exchange",
    )


def test_export_refused_when_consent_never_recorded(monkeypatch, connection, principal):
    """consent.current() returning a falsy 'never asked' value must refuse, same as withheld."""
    monkeypatch.setattr(routes_fhir.consent, "current", MagicMock(return_value=None))
    fake_record = MagicMock()
    fake_bundle_for = MagicMock()
    monkeypatch.setattr(routes_fhir, "record", fake_record)
    monkeypatch.setattr(routes_fhir, "bundle_for", fake_bundle_for)

    with pytest.raises(ConsentWithheld) as excinfo:
        routes_fhir.export_everything(
            patient_id="patient-2",
            limit=50,
            connection=connection,
            principal=principal,
        )

    assert str(excinfo.value) == "consent withheld or never recorded for patient patient-2"
    fake_bundle_for.assert_not_called()
    fake_record.assert_called_once_with(
        connection,
        principal,
        "export-refused",
        "patient",
        "patient-2",
        "data-exchange",
    )


def test_export_succeeds_and_logs_permitted_export_when_consent_granted(
    monkeypatch, connection, principal
):
    monkeypatch.setattr(routes_fhir.consent, "current", MagicMock(return_value=True))
    fake_bundle = {"resourceType": "Bundle", "id": "patient-3-everything"}
    fake_bundle_for = MagicMock(return_value=fake_bundle)
    fake_record = MagicMock()
    monkeypatch.setattr(routes_fhir, "bundle_for", fake_bundle_for)
    monkeypatch.setattr(routes_fhir, "record", fake_record)

    result = routes_fhir.export_everything(
        patient_id="patient-3",
        limit=25,
        connection=connection,
        principal=principal,
    )

    assert result is fake_bundle
    routes_fhir.consent.current.assert_called_once_with(connection, "patient-3", "data-exchange")
    fake_bundle_for.assert_called_once_with(connection, "patient-3", 25)
    fake_record.assert_called_once_with(
        connection,
        principal,
        "export",
        "patient",
        "patient-3",
        "data-exchange",
    )
