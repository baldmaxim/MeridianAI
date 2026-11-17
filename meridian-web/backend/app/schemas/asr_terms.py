"""Схемы словаря названий для распознавания речи (asr_terms)."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

MAX_TERM_LEN = 300
MAX_ALIASES = 20
MAX_ALIAS_LEN = 100


class AsrTermCreate(BaseModel):
    term: str
    aliases: list[str] = Field(default_factory=list)
    common: bool = False

    @model_validator(mode="after")
    def _normalize(self) -> "AsrTermCreate":
        term = self.term.strip()
        if not 1 <= len(term) <= MAX_TERM_LEN:
            raise ValueError(f"Название: от 1 до {MAX_TERM_LEN} символов")
        aliases: list[str] = []
        seen = {term.casefold()}
        for raw in self.aliases:
            alias = raw.strip()
            if not alias:
                continue
            if len(alias) > MAX_ALIAS_LEN:
                raise ValueError(f"Вариант: не более {MAX_ALIAS_LEN} символов")
            key = alias.casefold()
            if key in seen:
                continue
            seen.add(key)
            aliases.append(alias)
        if len(aliases) > MAX_ALIASES:
            raise ValueError(f"Вариантов не более {MAX_ALIASES}")
        self.term = term
        self.aliases = aliases
        return self


class AsrTermOut(BaseModel):
    id: int
    term: str
    aliases: list[str]
    is_common: bool
    can_delete: bool
    created_at: datetime
