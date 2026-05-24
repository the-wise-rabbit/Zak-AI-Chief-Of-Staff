"""Pydantic config model. Reads config.yaml + .env on import."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(dotenv_path=os.getenv("ZAK_ENV_FILE"))  # override with ZAK_ENV_FILE=/path/to/.env

_ROOT = Path(__file__).parent.parent.parent  # repo root


# ── Sub-models ────────────────────────────────────────────────────────────────

class ModelProfile(BaseModel):
    model: str
    max_tokens: int = 2000
    temperature: float = 0.7


class LLMConfig(BaseModel):
    profiles: dict[str, ModelProfile]

    @property
    def openrouter_api_key(self) -> str:
        key = os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
        return key


class GmailConfig(BaseModel):
    enabled: bool = False
    credentials_file: str = "data/credentials/google_token.json"
    max_emails_per_sync: int = 50
    labels_to_watch: list[str] = Field(default_factory=lambda: ["INBOX"])


class GCalConfig(BaseModel):
    enabled: bool = False
    lookahead_hours: int = 24


class SlackConfig(BaseModel):
    enabled: bool = False
    workspace_id: str = ""


class IntegrationsConfig(BaseModel):
    gmail: GmailConfig = Field(default_factory=GmailConfig)
    gcal: GCalConfig = Field(default_factory=GCalConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)


class SignalsConfig(BaseModel):
    high_keywords: list[str] = Field(default_factory=list)
    high_senders: list[str] = Field(default_factory=list)
    low_domains: list[str] = Field(default_factory=list)


class SchedulerConfig(BaseModel):
    agent_loop_interval_minutes: int = 2
    reflection_interval_minutes: int = 30
    daily_briefing_time: str = "08:00"
    eod_recap_time: str = "18:00"
    weekly_recap_day: str = "sunday"
    weekly_recap_time: str = "09:00"
    pre_meeting_brief_enabled: bool = True


class MemoryConfig(BaseModel):
    context_window_episodes: int = 20
    reflection_lookback_hours: int = 8
    relationship_decay_days: int = 30


class FeaturesConfig(BaseModel):
    chromadb: bool = False
    proactive_messages: bool = True
    pre_meeting_briefs: bool = True


class AgentConfig(BaseModel):
    name: str = "Zak"
    timezone: str = "Africa/Cairo"
    soul_file: str = "soul.md"


class DatabaseConfig(BaseModel):
    path: str = "data/zak.db"
    audit_dir: str = "data/audit/"


# ── Root config ───────────────────────────────────────────────────────────────

class Config(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    llm: LLMConfig
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)

    @property
    def telegram_bot_token(self) -> str:
        t = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not t:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")
        return t

    @property
    def telegram_chat_id(self) -> int:
        cid = os.getenv("TELEGRAM_CHAT_ID", "")
        if not cid:
            raise RuntimeError("TELEGRAM_CHAT_ID is not set in .env")
        return int(cid)

    @property
    def soul(self) -> str:
        p = _ROOT / self.agent.soul_file
        return p.read_text() if p.exists() else ""

    @property
    def db_path(self) -> Path:
        p = _ROOT / self.database.path
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def audit_dir(self) -> Path:
        p = _ROOT / self.database.audit_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_config(config_path: Optional[Path] = None) -> Config:
    path = config_path or (_ROOT / "config.yaml")
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    return Config.model_validate(raw)


# Module-level singleton — import and use directly.
cfg: Config = load_config()
