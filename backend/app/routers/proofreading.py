"""Proofreading routes (ADR-0102 §7, slice 2).

Thin routes onto `ProofreadingMixin`. Every write answers with the whole merged
setup, so the lens reloads from one shape. The frontend never touches the
files; these are the only way in.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    ProofreadingDialectRequest,
    ProofreadingIgnoreRequest,
    ProofreadingRuleRequest,
    ProofreadingSetup,
    ProofreadingWordRequest,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.get("/api/proofreading", response_model=ProofreadingSetup)
def read_proofreading(project: CurrentProject) -> ProofreadingSetup:
    with translate_errors():
        return project.read_proofreading()


@router.post("/api/proofreading/words", response_model=ProofreadingSetup)
def add_proofreading_word(project: CurrentProject, request: ProofreadingWordRequest) -> ProofreadingSetup:
    with translate_errors():
        return project.add_proofreading_word(request)


@router.post("/api/proofreading/words/remove", response_model=ProofreadingSetup)
def remove_proofreading_word(project: CurrentProject, request: ProofreadingWordRequest) -> ProofreadingSetup:
    with translate_errors():
        return project.remove_proofreading_word(request)


@router.put("/api/proofreading/rules", response_model=ProofreadingSetup)
def set_proofreading_rule(project: CurrentProject, request: ProofreadingRuleRequest) -> ProofreadingSetup:
    with translate_errors():
        return project.set_proofreading_rule(request)


@router.put("/api/proofreading/dialect", response_model=ProofreadingSetup)
def set_proofreading_dialect(project: CurrentProject, request: ProofreadingDialectRequest) -> ProofreadingSetup:
    with translate_errors():
        return project.set_proofreading_dialect(request)


@router.post("/api/proofreading/ignores", response_model=ProofreadingSetup)
def ignore_proofreading_spot(project: CurrentProject, request: ProofreadingIgnoreRequest) -> ProofreadingSetup:
    with translate_errors():
        return project.ignore_proofreading_spot(request)
