"""FHIR R4 export. FR-10, BR-06, REG-07."""

from datetime import UTC, datetime

import pytest

from carepath.api.routes_fhir import export_everything
from carepath.errors import ConsentWithheld
from carepath.fhir import bundle_for, encounter_resource, patient_resource
from carepath.schemas import ConsentIn, EncounterIn, ObservationIn
from carepath.security.audit import events_for
from carepath.security.auth import TOKENS
from carepath.security.auth import digest as auth_digest
from carepath.services import consent, encounters

from .conftest import CLINICIAN, PARTNER

NOW = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)

#: The partner principal, for calling export_everything without a web request -
#: the same pattern conftest.py uses for the clinician principal.
PARTNER_PRINCIPAL = TOKENS[auth_digest("demo-partner-token")]


class TestResources:
    def test_a_patient_carries_its_medical_record_number_as_an_identifier(self, patient):
        resource = patient_resource(patient)
        assert resource["resourceType"] == "Patient"
        assert resource["identifier"][0]["value"] == patient["mrn"]

    def test_a_patient_without_a_telephone_number_has_an_empty_telecom(self, patient):
        resource = patient_resource({**patient, "phone": None})
        assert resource["telecom"] == []

    def test_a_discharged_encounter_is_finished(self, patient):
        resource = encounter_resource(
            {
                "id": "e1",
                "patient_id": patient["id"],
                "kind": "inpatient",
                "admitted_at": NOW.isoformat(),
                "discharged_at": NOW.isoformat(),
            }
        )
        assert resource["status"] == "finished"
        assert resource["class"]["code"] == "IMP"

    def test_an_open_encounter_is_in_progress(self, patient):
        resource = encounter_resource(
            {
                "id": "e1",
                "patient_id": patient["id"],
                "kind": "emergency",
                "admitted_at": NOW.isoformat(),
                "discharged_at": None,
            }
        )
        assert resource["status"] == "in-progress"
        assert resource["class"]["code"] == "EMER"
        assert "end" not in resource["period"]


class TestBundle:
    def test_a_bundle_holds_the_patient_and_everything_recorded(
        self, connection, principal, patient
    ):
        stay = encounters.open_encounter(
            connection,
            principal,
            patient["id"],
            EncounterIn(
                kind="inpatient",
                facility="Riverside General",
                admitted_at=NOW,
                discharged_at=NOW,
            ),
        )
        encounters.add_observation(
            connection,
            principal,
            stay["id"],
            ObservationIn(code="8867-4", value=80.0, unit="/min", recorded_at=NOW),
        )
        bundle = bundle_for(connection, patient["id"], 50)
        kinds = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
        assert kinds == ["Patient", "Encounter", "Observation"]
        assert bundle["total"] == 3
        assert bundle["type"] == "searchset"


class TestConsentGate:
    """export_everything refuses to build a bundle without current consent. BR-05."""

    def test_export_is_refused_when_consent_was_never_asked(self, connection, patient):
        with pytest.raises(ConsentWithheld):
            export_everything(
                patient["id"], limit=50, connection=connection, principal=PARTNER_PRINCIPAL
            )
        events = events_for(connection, "patient", patient["id"])
        assert any(event["action"] == "export-refused" for event in events)

    def test_export_is_refused_when_consent_is_withdrawn(self, connection, principal, patient):
        consent.record_decision(
            connection, principal, patient["id"], ConsentIn(purpose="data-exchange", granted=True)
        )
        consent.record_decision(
            connection, principal, patient["id"], ConsentIn(purpose="data-exchange", granted=False)
        )
        with pytest.raises(ConsentWithheld):
            export_everything(
                patient["id"], limit=50, connection=connection, principal=PARTNER_PRINCIPAL
            )
        events = events_for(connection, "patient", patient["id"])
        assert any(event["action"] == "export-refused" for event in events)

    def test_export_succeeds_when_consent_is_granted(self, connection, principal, patient):
        consent.record_decision(
            connection, principal, patient["id"], ConsentIn(purpose="data-exchange", granted=True)
        )
        bundle = export_everything(
            patient["id"], limit=50, connection=connection, principal=PARTNER_PRINCIPAL
        )
        assert bundle["resourceType"] == "Bundle"

    def test_export_succeeds_after_withdrawn_then_regranted_consent(
        self, connection, principal, patient
    ):
        for granted in (True, False, True):
            consent.record_decision(
                connection,
                principal,
                patient["id"],
                ConsentIn(purpose="data-exchange", granted=granted),
            )
        bundle = export_everything(
            patient["id"], limit=50, connection=connection, principal=PARTNER_PRINCIPAL
        )
        assert bundle["resourceType"] == "Bundle"


class TestApi:
    def test_a_partner_may_export_with_granted_consent(
        self, client, connection, principal, patient
    ):
        consent.record_decision(
            connection, principal, patient["id"], ConsentIn(purpose="data-exchange", granted=True)
        )
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert response.status_code == 200
        assert response.json()["resourceType"] == "Bundle"

    def test_a_clinician_may_not_export(self, client, patient):
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=CLINICIAN
        )
        assert response.status_code == 403

    def test_an_export_of_an_unknown_patient_is_a_404(self, client):
        response = client.get("/fhir/Patient/nobody/$everything", headers=PARTNER)
        assert response.status_code == 404
