"""FHIR R4 export for partner systems. FR-10, BR-06, REG-07."""

from fastapi import APIRouter, Depends, Query

from ..config import settings
from ..errors import ConsentWithheld
from ..fhir import bundle_for
from ..security.audit import record
from ..security.auth import Principal
from ..security.rbac import Permission
from ..services import consent as consent_service
from .deps import require, unit_of_work

router = APIRouter(prefix="/fhir", tags=["fhir"])

#: The consent purpose that gates a partner export. Matches the purpose
#: already recorded on the audit event for a permitted export.
CONSENT_PURPOSE = "data-exchange"


@router.get("/Patient/{patient_id}/$everything")
def export_everything(
    patient_id: str,
    limit: int = Query(default=50, le=settings.max_page_size),
    connection=Depends(unit_of_work),
    principal: Principal = Depends(require(Permission.FHIR_EXPORT)),
) -> dict:
    """One patient's record as a FHIR R4 Bundle. FR-10.

    Refused, not merely skipped, when the patient's current data-exchange
    consent is withheld or has never been recorded (BR-05): `ConsentWithheld`
    is raised instead of returning a bundle. A refused export is itself a
    disclosure event, so the refusal is written to the audit trail just as a
    permitted export is.
    """
    if not consent_service.current(connection, patient_id, CONSENT_PURPOSE):
        record(
            connection,
            principal,
            "export-refused",
            "patient",
            patient_id,
            CONSENT_PURPOSE,
        )
        raise ConsentWithheld("The patient has not consented to this export.")
    bundle = bundle_for(connection, patient_id, limit)
    record(connection, principal, "export", "patient", patient_id, CONSENT_PURPOSE)
    return bundle
