"""FHIR export route: consent gate. FR-10, BR-06, REG-07."""

from .conftest import PARTNER


class TestExportConsentGate:
    def test_a_partner_may_export_when_consent_is_granted(self, client, patient, monkeypatch):
        monkeypatch.setattr("carepath.services.consent.current", lambda *a, **k: True)
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert response.status_code == 200
        assert response.json()["resourceType"] == "Bundle"

    def test_export_is_refused_when_consent_is_withdrawn(self, client, patient, monkeypatch):
        monkeypatch.setattr("carepath.services.consent.current", lambda *a, **k: False)
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert response.status_code == 403

    def test_export_is_refused_when_the_patient_has_never_been_asked(
        self, client, patient, monkeypatch
    ):
        monkeypatch.setattr("carepath.services.consent.current", lambda *a, **k: None)
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert response.status_code == 403

    def test_a_partner_may_export_after_consent_is_withdrawn_then_regranted(
        self, client, patient, monkeypatch
    ):
        decisions = iter([False, True])
        monkeypatch.setattr(
            "carepath.services.consent.current", lambda *a, **k: next(decisions)
        )
        refused = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert refused.status_code == 403
        regranted = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert regranted.status_code == 200

    def test_a_refused_export_is_recorded_as_a_disclosure_event(
        self, client, patient, monkeypatch
    ):
        monkeypatch.setattr("carepath.services.consent.current", lambda *a, **k: False)
        calls = []
        monkeypatch.setattr(
            "carepath.api.routes_fhir.record", lambda *a, **k: calls.append(a)
        )
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert response.status_code == 403
        assert calls
        args = calls[0]
        assert args[2] == "export-refused"
        assert args[3] == "patient"
        assert args[4] == patient["id"]
        assert args[5] == "data-exchange"

    def test_a_permitted_export_is_recorded_as_an_export_event(
        self, client, patient, monkeypatch
    ):
        monkeypatch.setattr("carepath.services.consent.current", lambda *a, **k: True)
        calls = []
        monkeypatch.setattr(
            "carepath.api.routes_fhir.record", lambda *a, **k: calls.append(a)
        )
        response = client.get(
            f"/fhir/Patient/{patient['id']}/$everything", headers=PARTNER
        )
        assert response.status_code == 200
        assert calls
        args = calls[0]
        assert args[2] == "export"
        assert args[3] == "patient"
        assert args[4] == patient["id"]
        assert args[5] == "data-exchange"
