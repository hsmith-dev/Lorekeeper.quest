import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.user_settings import UserSettings
from app.db.models.model_evaluation import ModelEvaluation
from app.schemas.settings import (
    LLMSettingsResponse,
    LLMSettingsUpdate,
    TestConnectionRequest,
    TestConnectionResponse,
    EvaluationRequest,
    EvaluationResponse,
)
from app.api.deps import get_current_user, get_user_llm_config
from app.core.config import get_settings
from app.services.llm_provider import LLMConfig, test_provider_connection, is_hosted_default
from app.services.eval_service import run_evaluation
from app.services import billing_service

router = APIRouter()


def _to_response(us: UserSettings) -> LLMSettingsResponse:
    return LLMSettingsResponse(
        llm_provider=us.llm_provider,
        llm_api_url=us.llm_api_url,
        llm_api_key_set=bool(us.llm_api_key),
        llm_model=us.llm_model,
        llm_temperature=us.llm_temperature,
        llm_max_tokens=us.llm_max_tokens,
        narrative_paragraph_limit=us.narrative_paragraph_limit,
        hosted_model_variant=us.hosted_model_variant,
    )


def _hosted_variant_config(variant: str) -> LLMConfig:
    """Build an LLMConfig that hits the platform's hosted Ollama with a given
    variant, bypassing whatever the user has personally saved. api_url is set
    explicitly (not left None) so is_hosted_default's comparison against
    get_default_config() — which also resolves api_url from the same
    settings — actually matches; leaving it None here would make usage
    silently go unmetered (cfg.api_url None != default.api_url's real
    string)."""
    s = get_settings()
    model = s.kobold_base_model if variant == "base" else s.kobold_model
    return LLMConfig(provider="kobold", api_url=s.kobold_url, model=model)


async def _get_or_create(user_id: uuid.UUID, db: AsyncSession) -> UserSettings:
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    us = result.scalar_one_or_none()
    if us is None:
        us = UserSettings(user_id=user_id)
        db.add(us)
        await db.commit()
        await db.refresh(us)
    return us


@router.get("/", response_model=LLMSettingsResponse)
async def get_llm_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMSettingsResponse:
    us = await _get_or_create(user.id, db)
    return _to_response(us)


@router.put("/", response_model=LLMSettingsResponse)
async def update_llm_settings(
    body: LLMSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMSettingsResponse:
    us = await _get_or_create(user.id, db)

    if body.llm_provider is not None:
        us.llm_provider = body.llm_provider
    if body.llm_api_url is not None:
        us.llm_api_url = body.llm_api_url or None
    if body.llm_api_key is not None:
        us.llm_api_key = body.llm_api_key or None
    if body.llm_model is not None:
        us.llm_model = body.llm_model or None
    if body.llm_temperature is not None:
        us.llm_temperature = body.llm_temperature
    if body.llm_max_tokens is not None:
        us.llm_max_tokens = body.llm_max_tokens
    if body.narrative_paragraph_limit is not None:
        # 0 is the explicit "clear" sentinel (validated ge=0 in the schema);
        # a nullable field can't use None for it since None means "unchanged".
        us.narrative_paragraph_limit = body.narrative_paragraph_limit or None
    if body.hosted_model_variant is not None:
        us.hosted_model_variant = body.hosted_model_variant

    await db.commit()
    await db.refresh(us)
    return _to_response(us)


@router.post("/test", response_model=TestConnectionResponse)
async def test_connection(
    body: TestConnectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResponse:
    api_key = body.llm_api_key
    api_url = body.llm_api_url
    if not api_key or not api_url:
        result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
        us = result.scalar_one_or_none()
        if us:
            if not api_key:
                api_key = us.llm_api_key
            if not api_url:
                api_url = us.llm_api_url

    cfg = LLMConfig(
        provider=body.llm_provider,
        api_url=api_url,
        api_key=api_key,
        model=body.llm_model,
    )
    # Testing "Use Lorekeeper AI" mode (kobold provider, no URL of your own)
    # with "Base Model" selected — resolve the actual Ollama model name
    # server-side rather than trusting a client-supplied one, same reasoning
    # as _hosted_variant_config below.
    if body.llm_provider == "kobold" and not api_url and body.hosted_model_variant == "base":
        cfg.model = get_settings().kobold_base_model

    try:
        text = await test_provider_connection(cfg)
        return TestConnectionResponse(success=True, message=f"Connected! Model replied: {text[:80]}")
    except HTTPException as exc:
        return TestConnectionResponse(success=False, message=exc.detail)
    except Exception as exc:
        return TestConnectionResponse(success=False, message=str(exc))


@router.post("/evaluate", response_model=EvaluationResponse, status_code=201)
async def evaluate_model(
    body: EvaluationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    default_config: LLMConfig = Depends(get_user_llm_config),
) -> EvaluationResponse:
    """Run the validation set against a provider and store the result.

    hosted_model_variant is the "quick compare" path used by Settings' two
    dedicated buttons — Run vs Fine-Tuned / Run vs Base Model — and forces
    the platform's hosted Ollama with that variant regardless of what the
    user has saved, so comparing doesn't require changing (and remembering
    to change back) their real provider settings. Falls back to the older,
    more general llm_provider override, then to whatever's currently saved
    in Settings if neither is given."""
    if body.hosted_model_variant:
        cfg = _hosted_variant_config(body.hosted_model_variant)
    elif body.llm_provider:
        cfg = LLMConfig(
            provider=body.llm_provider,
            api_url=body.llm_api_url,
            api_key=body.llm_api_key,
            model=body.llm_model,
        )
    else:
        cfg = default_config

    try:
        result = await run_evaluation(cfg, body.sample_size)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # An evaluation run is many completions in a row, not one — meter it as
    # such (avg response length × how many were actually generated), same as
    # any other hosted-model usage, so it can't be used to bypass the quota.
    if is_hosted_default(cfg) and result.get("sample_size"):
        generated_chars = result["avg_length"] * result["sample_size"]
        await billing_service.record_hosted_usage(db, user, "x" * int(generated_chars))

    evaluation = ModelEvaluation(user_id=user.id, label=body.label.strip()[:100], **result)
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@router.get("/evaluations", response_model=list[EvaluationResponse])
async def list_evaluations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EvaluationResponse]:
    result = await db.execute(
        select(ModelEvaluation)
        .where(ModelEvaluation.user_id == user.id)
        .order_by(ModelEvaluation.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/evaluations/{evaluation_id}", status_code=204)
async def delete_evaluation(
    evaluation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(ModelEvaluation).where(ModelEvaluation.id == evaluation_id, ModelEvaluation.user_id == user.id)
    )
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    await db.delete(evaluation)
    await db.commit()
