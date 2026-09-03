"""Tag-node routes (ADR-0082 slice 1, #1782).

`/api/tag-entries` — the `tag` kind's own CRUD, thin routes onto
`TagNodesMixin`. Deliberately NOT `/api/tags`: that path is the legacy
name/colour registry (`routers/metadata.py:50-71`), retired only in a later
slice — the two coexist until then.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CreateTagEntryRequest,
    SaveTagEntryRequest,
    TagEntry,
    TagEntryList,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.get("/api/tag-entries", response_model=TagEntryList)
def list_tag_entries(project: CurrentProject) -> TagEntryList:
    with translate_errors():
        return project.list_tag_entries()


@router.post("/api/tag-entries", response_model=TagEntry)
def create_tag_entry(project: CurrentProject, request: CreateTagEntryRequest) -> TagEntry:
    with translate_errors():
        return project.create_tag_entry(request)


@router.get("/api/tag-entries/{tag_id}", response_model=TagEntry)
def get_tag_entry(project: CurrentProject, tag_id: str) -> TagEntry:
    with translate_errors():
        return project.read_tag_entry(tag_id)


@router.put("/api/tag-entries/{tag_id}", response_model=TagEntry)
def save_tag_entry(project: CurrentProject, tag_id: str, request: SaveTagEntryRequest) -> TagEntry:
    with translate_errors():
        return project.save_tag_entry(tag_id, request)


@router.delete("/api/tag-entries/{tag_id}", response_model=TagEntryList)
def delete_tag_entry(project: CurrentProject, tag_id: str) -> TagEntryList:
    with translate_errors():
        return project.delete_tag_entry(tag_id)
