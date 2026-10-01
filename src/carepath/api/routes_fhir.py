"""FHIR R4 export for partner systems. FR-10, BR-06, REG-07."""

from fastapi import APIRouter, Depends, Query

from ..config import settings
from ..errors import ConsentWithheld
from ..fhir import bundle_for
from ..security.audit import record
from ..security.auth import Principal
from ..security.rbac import Permission
from ..services import consent
from ..services.patients import fetch as fetch_patient
from .deps import require, unit_of_work

router = APIRouter(prefix="/fhir", tags=["fhir"])


@router.get("/Patient/{patient_id}/$everything")
def export_everything(
    patient_id: str,
    limit: int = Query(default=50, le=settings.max_page_size),
    connection=Depends(unit_of_work),
    principal: Principal = Depends(require(Permission.FHIR_EXPORT)),
) -> dict:
    """One patient's record as a FHIR R4 Bundle. FR-10, BR-05.

    An unknown patient is still a 404, exactly as before. For a patient that
    exists, export is refused when their current data-exchange consent is
    withheld or has never been recorded: the refusal is written to the audit
    trail and that write is committed immediately, because `unit_of_work`
    rolls the whole transaction back on any exception, and an audit row for a
    refusal that was never committed would disappear along with the error
    that reported it. When consent is currently granted, the bundle is built
    and returned exactly as before.
    """
    fetch_patient(connection, patient_id)
    if not consent.current(connection, patient_id, "data-exchange"):
        record(connection, principal, "export-refused", "patient", patient_id, "data-exchange")
        connection.commit()
        raise ConsentWithheld("The patient has not consented to this export.")
    bundle = bundle_for(connection, patient_id, limit)
    record(connection, principal, "export", "patient", patient_id, "data-exchange")
    return bundle
