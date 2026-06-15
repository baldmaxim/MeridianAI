"""База знаний и кандидаты на обучение (Этап 7, controlled auto-learning).

LearningCandidate — предложения LLM после финализации (status pending), требуют ручного
approve/reject. Только approved knowledge-элементы используются в live-подсказках.
Scope — owner_user_id (seam под organization_id). Уникальность approved-элементов —
в миграции (partial unique), app-level dedup см. services/learning_dedup.py.
"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, Float, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LearningCandidate(Base):
    __tablename__ = "learning_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    object_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project_objects.id", ondelete="SET NULL"))
    meeting_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("meeting_sessions.id", ondelete="SET NULL"))
    # term | trigger_phrase | playbook | counterparty_trait | forbidden_phrase
    candidate_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_refs_json: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|approved|rejected
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_learning_candidates_owner_status", "owner_user_id", "status"),
        Index("ix_learning_candidates_customer", "customer_id"),
        Index("ix_learning_candidates_object", "object_id"),
        Index("ix_learning_candidates_meeting", "meeting_id"),
        Index("ix_learning_candidates_type_status", "candidate_type", "status"),
    )


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    object_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project_objects.id", ondelete="SET NULL"))
    term: Mapped[str] = mapped_column(String(300), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    aliases_json: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20), default="global")  # global|customer|object
    status: Mapped[str] = mapped_column(String(20), default="approved")  # approved|archived
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_from_candidate_id: Mapped[int | None] = mapped_column(Integer)
    created_from_meeting_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_glossary_owner_status", "owner_user_id", "status"),
        Index("ix_glossary_customer", "customer_id"),
        Index("ix_glossary_object", "object_id"),
    )


class TriggerPhrase(Base):
    __tablename__ = "trigger_phrases"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    object_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project_objects.id", ondelete="SET NULL"))
    phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    # price_pressure|deadline_pressure|liability_shift|concession_request|fixation_request|stalling|contradiction_signal|other
    event_type: Mapped[str] = mapped_column(String(30), default="other")
    recommended_reaction: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="global")
    status: Mapped[str] = mapped_column(String(20), default="approved")
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_from_candidate_id: Mapped[int | None] = mapped_column(Integer)
    created_from_meeting_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_triggers_owner_status", "owner_user_id", "status"),
        Index("ix_triggers_customer", "customer_id"),
        Index("ix_triggers_object", "object_id"),
    )


class NegotiationPlaybook(Base):
    __tablename__ = "negotiation_playbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    object_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project_objects.id", ondelete="SET NULL"))
    situation: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_phrase: Mapped[str] = mapped_column(Text, nullable=False)
    # conditional_concession|calibrated_question|fixation|reframing|risk_transfer_block|other
    technique: Mapped[str] = mapped_column(String(30), default="other")
    ask_in_return_json: Mapped[str | None] = mapped_column(Text)
    risks_json: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20), default="global")
    status: Mapped[str] = mapped_column(String(20), default="approved")
    success_score: Mapped[float | None] = mapped_column(Float)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_from_candidate_id: Mapped[int | None] = mapped_column(Integer)
    created_from_meeting_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_playbooks_owner_status", "owner_user_id", "status"),
        Index("ix_playbooks_customer", "customer_id"),
        Index("ix_playbooks_object", "object_id"),
    )


class CounterpartyTrait(Base):
    __tablename__ = "counterparty_traits"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    object_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project_objects.id", ondelete="SET NULL"))
    trait: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    recommended_strategy: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20), default="customer")  # customer|object
    status: Mapped[str] = mapped_column(String(20), default="approved")
    confidence: Mapped[float | None] = mapped_column(Float)
    created_from_candidate_id: Mapped[int | None] = mapped_column(Integer)
    created_from_meeting_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_traits_owner_status", "owner_user_id", "status"),
        Index("ix_traits_customer", "customer_id"),
        Index("ix_traits_object", "object_id"),
    )


class ForbiddenPhrase(Base):
    __tablename__ = "forbidden_phrases"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    object_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project_objects.id", ondelete="SET NULL"))
    phrase_or_risk: Mapped[str] = mapped_column(Text, nullable=False)
    better_alternative: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20), default="global")
    status: Mapped[str] = mapped_column(String(20), default="approved")
    created_from_candidate_id: Mapped[int | None] = mapped_column(Integer)
    created_from_meeting_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_forbidden_owner_status", "owner_user_id", "status"),
        Index("ix_forbidden_customer", "customer_id"),
        Index("ix_forbidden_object", "object_id"),
    )
