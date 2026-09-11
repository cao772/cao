from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import people_store

router = APIRouter(prefix="/api/v1")


class PersonCreateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=300)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class PersonUpdateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=300)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class IdentityBindIn(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    external_id: str = Field(min_length=1, max_length=500)
    display_name: str | None = Field(default=None, max_length=500)


def _bad_request(exc: Exception) -> HTTPException:
    if isinstance(exc, people_store.PeopleConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="person or identity not found")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/platform/people")
def get_people() -> dict[str, Any]:
    return people_store.list_people()


@router.get("/platform/identities")
def get_identities(
    unassigned_only: bool = Query(default=False),
) -> dict[str, Any]:
    identities = people_store.list_identities(unassigned_only=unassigned_only)
    return {"count": len(identities), "identities": identities}


@router.get("/platform/devices")
def get_devices() -> dict[str, Any]:
    devices = people_store.list_devices()
    summary = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
    for device in devices:
        status = str(device.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return {"count": len(devices), "summary": summary, "devices": devices}


@router.post("/platform/people")
def post_person(payload: PersonCreateIn) -> dict[str, Any]:
    try:
        person = people_store.create_person(payload.display_name, status=payload.status)
    except (ValueError, KeyError, people_store.PeopleConflict) as exc:
        raise _bad_request(exc) from exc
    return {"created": True, "person": person}


@router.put("/platform/people/{person_id}")
def put_person(person_id: str, payload: PersonUpdateIn) -> dict[str, Any]:
    try:
        person = people_store.update_person(
            person_id,
            display_name=payload.display_name,
            status=payload.status,
        )
    except (ValueError, KeyError, people_store.PeopleConflict) as exc:
        raise _bad_request(exc) from exc
    return {"updated": True, "person": person}


@router.post("/platform/people/{person_id}/identities")
def post_person_identity(person_id: str, payload: IdentityBindIn) -> dict[str, Any]:
    try:
        identity = people_store.bind_identity(
            person_id,
            provider=payload.provider,
            external_id=payload.external_id,
            display_name=payload.display_name,
        )
    except (ValueError, KeyError, people_store.PeopleConflict) as exc:
        raise _bad_request(exc) from exc
    return {"bound": True, "identity": identity}


@router.delete("/platform/people/{person_id}/identities/{identity_id}")
def delete_person_identity(person_id: str, identity_id: str) -> dict[str, Any]:
    try:
        identity = people_store.unbind_identity(person_id, identity_id)
    except (ValueError, KeyError, people_store.PeopleConflict) as exc:
        raise _bad_request(exc) from exc
    return {"unbound": True, "identity": identity}
