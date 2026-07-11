"""Versioned, owner-scoped agent definitions and lifecycle persistence.

Agent edits never mutate queued/running work: every save creates an immutable ``AgentVersion`` and
the run layer snapshots that version again when it enqueues. This module contains no model-driven
authorization decisions; grants and limits are validated as typed data and enforced downstream.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import Agent, AgentSchedule, AgentVersion
from backend.features import team
from backend.security.secrets import redact_secrets

MAX_AGENT_CONFIG_BYTES = 256 * 1024
RESOURCE_LIMIT = 100


class AgentConfigError(ValueError):
    pass


class ToolGrantSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=80)
    actions: list[str] = Field(default_factory=lambda: ["execute"], max_length=20)
    resources: dict[str, list[str]] = Field(default_factory=dict)
    approval: Literal["risk_based", "always", "preapproved"] = "risk_based"

    @field_validator("actions")
    @classmethod
    def normalize_actions(cls, values: list[str]) -> list[str]:
        clean = [str(value).strip()[:80] for value in values if str(value).strip()]
        return list(dict.fromkeys(clean)) or ["execute"]

    @field_validator("resources")
    @classmethod
    def validate_resources(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(value) > 20:
            raise ValueError("A tool grant may constrain at most 20 resource fields")
        clean: dict[str, list[str]] = {}
        for field, entries in value.items():
            key = str(field).strip()
            if not key or len(key) > 80 or len(entries) > RESOURCE_LIMIT:
                raise ValueError("Invalid tool resource constraint")
            clean[key] = list(dict.fromkeys(str(item).strip()[:500] for item in entries if str(item).strip()))
        return clean


class ConnectorGrantSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector: Literal["slack", "gmail"]
    account_id: str = Field(min_length=1, max_length=80)
    actions: list[str] = Field(default_factory=list, max_length=20)
    resources: list[str] = Field(default_factory=list, max_length=RESOURCE_LIMIT)


class AgentBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps_per_run: int = Field(default=8, ge=1, le=30)
    max_runtime_seconds: int = Field(default=300, ge=15, le=3600)
    max_input_chars: int = Field(default=20_000, ge=1, le=100_000)
    max_output_chars: int = Field(default=20_000, ge=1, le=100_000)
    max_runs_per_day: int = Field(default=100, ge=1, le=10_000)
    max_cost_usd_per_day: float = Field(default=5.0, ge=0, le=10_000)


class AgentPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    life_access: Literal["none", "read", "propose"] = "none"
    allow_life_with_cloud_models: bool = False
    approval_risks: list[
        Literal["sensitive_read", "local_write", "external_write", "destructive", "credential_use", "network"]
    ] = Field(
        default_factory=lambda: ["local_write", "external_write", "destructive", "credential_use"]
    )


class AgentScheduleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    cron: str = Field(default="0 9 * * *", max_length=120)
    timezone: str = Field(default="UTC", max_length=80)
    misfire_policy: Literal["skip", "coalesce"] = "coalesce"
    concurrency_policy: Literal["forbid", "queue", "replace"] = "forbid"

    @model_validator(mode="after")
    def validate_cron_timezone(self):
        fields = self.cron.split()
        if len(fields) != 5 or not croniter.is_valid(self.cron):
            raise ValueError("Schedule must be a valid five-field cron expression")
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Schedule timezone must be a valid IANA timezone") from exc
        now = datetime.datetime.now(zone)
        iterator = croniter(self.cron, now)
        first = iterator.get_next(datetime.datetime)
        second = iterator.get_next(datetime.datetime)
        if (second - first).total_seconds() < 60:
            raise ValueError("Agent schedules cannot run more than once per minute")
        return self


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    goal: str = Field(min_length=1, max_length=8000)
    guidelines: list[str] = Field(default_factory=list, max_length=50)
    model: str = Field(min_length=1, max_length=220)
    effort: Literal["", "low", "medium", "high", "xhigh"] = ""
    skills: list[str] = Field(default_factory=list, max_length=RESOURCE_LIMIT)
    datasets: list[str] = Field(default_factory=list, max_length=RESOURCE_LIMIT)
    ontologies: list[str] = Field(default_factory=list, max_length=RESOURCE_LIMIT)
    projects: list[str] = Field(default_factory=list, max_length=RESOURCE_LIMIT)
    tool_grants: list[ToolGrantSpec] = Field(default_factory=list, max_length=50)
    connector_grants: list[ConnectorGrantSpec] = Field(default_factory=list, max_length=20)
    trigger_modes: list[Literal["manual", "schedule", "api", "slack", "gmail"]] = Field(
        default_factory=lambda: ["manual"]
    )
    budgets: AgentBudgets = Field(default_factory=AgentBudgets)
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)
    schedule: AgentScheduleSpec = Field(default_factory=AgentScheduleSpec)

    @field_validator("name", "description", "goal")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("guidelines")
    @classmethod
    def normalize_guidelines(cls, values: list[str]) -> list[str]:
        clean = [str(value).strip()[:2000] for value in values if str(value).strip()]
        return list(dict.fromkeys(clean))

    @field_validator("skills", "datasets", "ontologies", "projects")
    @classmethod
    def normalize_refs(cls, values: list[str]) -> list[str]:
        clean = [str(value).strip()[:200] for value in values if str(value).strip()]
        return list(dict.fromkeys(clean))

    @field_validator("trigger_modes")
    @classmethod
    def normalize_triggers(cls, values: list[str]) -> list[str]:
        clean = list(dict.fromkeys(values))
        if not clean:
            raise ValueError("At least one trigger mode is required")
        return clean

    @model_validator(mode="after")
    def cross_validate(self):
        tool_names = [grant.tool for grant in self.tool_grants]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("Each tool may be granted only once")
        if self.schedule.enabled and "schedule" not in self.trigger_modes:
            raise ValueError("Enable the schedule trigger mode before enabling a schedule")
        connector_modes = {grant.connector for grant in self.connector_grants}
        for connector in ("slack", "gmail"):
            if connector in self.trigger_modes and connector not in connector_modes:
                raise ValueError(f"The {connector} trigger needs a matching connector grant")
        return self


class AgentStatusUpdate(BaseModel):
    status: Literal["active", "paused", "archived"]


def _canonical(config: AgentConfig) -> tuple[str, str]:
    raw = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_AGENT_CONFIG_BYTES:
        raise AgentConfigError("Agent configuration is too large")
    if redact_secrets(raw) != raw:
        raise AgentConfigError("Agent configuration appears to contain a credential or secret")
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_config(config: AgentConfig) -> AgentConfig:
    """Validate registry references that Pydantic cannot know without importing the tool catalog."""
    from backend import tools

    available = {item["key"]: item for item in tools.list_tools()}
    for grant in config.tool_grants:
        if grant.tool not in available:
            raise AgentConfigError(f"Unknown tool grant: {grant.tool}")
        risk = available[grant.tool].get("risk", "read")
        if grant.approval == "preapproved" and risk in {
            "external_write", "destructive", "credential_use"
        }:
            raise AgentConfigError(f"{grant.tool} cannot be preapproved at risk level {risk}")
    _canonical(config)
    return config


def _next_fire(schedule: AgentScheduleSpec) -> datetime.datetime | None:
    if not schedule.enabled:
        return None
    zone = ZoneInfo(schedule.timezone)
    local_now = datetime.datetime.now(zone)
    next_local = croniter(schedule.cron, local_now).get_next(datetime.datetime)
    return next_local.astimezone(datetime.timezone.utc)


def _owned_filter(owner_id: str | None):
    return Agent.owner_id.is_(None) if owner_id is None else Agent.owner_id == owner_id


def _decode_config(row: AgentVersion) -> dict:
    try:
        return json.loads(row.config)
    except (TypeError, ValueError):
        return {}


def _agent_dict(agent: Agent, version: AgentVersion, schedule: AgentSchedule | None = None) -> dict:
    config = _decode_config(version)
    if schedule is not None:
        config["schedule"] = {
            "enabled": bool(schedule.enabled),
            "cron": schedule.cron,
            "timezone": schedule.timezone,
            "misfire_policy": schedule.misfire_policy,
            "concurrency_policy": schedule.concurrency_policy,
        }
    return {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description or "",
        "status": agent.status,
        "version": version.version,
        "version_id": str(version.id),
        "config_hash": version.config_hash,
        "config": config,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


async def list_agents(*, include_archived: bool = False, limit: int = 100, offset: int = 0) -> dict:
    owner_id = await team.current_owner_id()
    statement = (
        select(Agent, AgentVersion, AgentSchedule)
        .join(
            AgentVersion,
            (AgentVersion.agent_id == Agent.id) & (AgentVersion.version == Agent.current_version),
        )
        .outerjoin(AgentSchedule, AgentSchedule.agent_id == Agent.id)
        .where(_owned_filter(owner_id))
    )
    if not include_archived:
        statement = statement.where(Agent.status != "archived")
    statement = statement.order_by(Agent.updated_at.desc()).offset(max(0, offset)).limit(max(1, min(limit, 200)))
    async with get_sessionmaker()() as session:
        rows = (await session.execute(statement)).all()
    return {
        "agents": [_agent_dict(agent, version, schedule) for agent, version, schedule in rows],
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }


async def _get_rows(session, agent_id: str, owner_id: str | None, *, lock: bool = False):
    try:
        parsed = uuid.UUID(agent_id)
    except (ValueError, TypeError, AttributeError):
        return None
    statement = select(Agent).where(Agent.id == parsed, _owned_filter(owner_id))
    if lock:
        statement = statement.with_for_update()
    agent = (await session.execute(statement)).scalar_one_or_none()
    if agent is None:
        return None
    version = (await session.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id,
            AgentVersion.version == agent.current_version,
        )
    )).scalar_one()
    schedule = (await session.execute(
        select(AgentSchedule).where(AgentSchedule.agent_id == agent.id)
    )).scalar_one_or_none()
    return agent, version, schedule


async def get_agent(agent_id: str) -> dict | None:
    owner_id = await team.current_owner_id()
    async with get_sessionmaker()() as session:
        rows = await _get_rows(session, agent_id, owner_id)
        return _agent_dict(*rows) if rows else None


def _schedule_row(agent: Agent, owner_id: str | None, spec: AgentScheduleSpec, version: int) -> AgentSchedule:
    return AgentSchedule(
        agent_id=agent.id,
        owner_id=owner_id,
        enabled=spec.enabled,
        cron=spec.cron,
        timezone=spec.timezone,
        misfire_policy=spec.misfire_policy,
        concurrency_policy=spec.concurrency_policy,
        version=version,
        next_fire_at=_next_fire(spec),
    )


async def create_agent(config: AgentConfig) -> dict:
    config = validate_config(config)
    raw, digest = _canonical(config)
    owner_id = await team.current_owner_id()
    async with get_sessionmaker()() as session:
        agent = Agent(
            owner_id=owner_id,
            name=config.name,
            description=config.description,
            status="active",
            current_version=1,
        )
        session.add(agent)
        await session.flush()
        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            config=raw,
            config_hash=digest,
            created_by=owner_id or "solo",
        )
        schedule = _schedule_row(agent, owner_id, config.schedule, 1)
        session.add(version)
        session.add(schedule)
        await session.commit()
        await session.refresh(agent)
        await session.refresh(version)
        await session.refresh(schedule)
        return _agent_dict(agent, version, schedule)


async def update_agent(agent_id: str, config: AgentConfig) -> dict | None:
    config = validate_config(config)
    raw, digest = _canonical(config)
    owner_id = await team.current_owner_id()
    async with get_sessionmaker()() as session:
        rows = await _get_rows(session, agent_id, owner_id, lock=True)
        if rows is None:
            return None
        agent, current, schedule = rows
        if current.config_hash == digest:
            return _agent_dict(agent, current, schedule)
        next_version = agent.current_version + 1
        version = AgentVersion(
            agent_id=agent.id,
            version=next_version,
            config=raw,
            config_hash=digest,
            created_by=owner_id or "solo",
        )
        session.add(version)
        agent.name = config.name
        agent.description = config.description
        agent.current_version = next_version
        agent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        if schedule is None:
            schedule = _schedule_row(agent, owner_id, config.schedule, next_version)
            session.add(schedule)
        else:
            schedule.enabled = config.schedule.enabled
            schedule.cron = config.schedule.cron
            schedule.timezone = config.schedule.timezone
            schedule.misfire_policy = config.schedule.misfire_policy
            schedule.concurrency_policy = config.schedule.concurrency_policy
            schedule.version = next_version
            schedule.next_fire_at = _next_fire(config.schedule)
        await session.commit()
        await session.refresh(agent)
        await session.refresh(version)
        await session.refresh(schedule)
        return _agent_dict(agent, version, schedule)


async def set_agent_status(agent_id: str, status: str) -> dict | None:
    if status not in {"active", "paused", "archived"}:
        raise AgentConfigError("Invalid agent status")
    owner_id = await team.current_owner_id()
    async with get_sessionmaker()() as session:
        rows = await _get_rows(session, agent_id, owner_id, lock=True)
        if rows is None:
            return None
        agent, version, schedule = rows
        agent.status = status
        agent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        if schedule is not None and status != "active":
            schedule.enabled = False
            schedule.next_fire_at = None
        await session.commit()
        await session.refresh(agent)
        return _agent_dict(agent, version, schedule)
