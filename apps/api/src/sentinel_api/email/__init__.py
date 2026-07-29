"""Credential-isolated execution for broker-authorized email actions."""

from sentinel_api.email.models import (
    ApprovedEmailPayload,
    DispatchDisposition,
    EmailDispatchRequest,
    EmailExecutionRecord,
    EmailMessage,
    ProviderAuditEvent,
    ProviderDispatchResult,
    ProviderReceipt,
    ProviderReconciliationResult,
    ReconciliationDisposition,
    normalize_email_address,
    validate_provider_message_id,
)
from sentinel_api.email.postgres import PostgresEmailExecutionStore
from sentinel_api.email.providers import (
    DeterministicFakeEmailProvider,
    EmailProvider,
    FakeProviderBehavior,
)
from sentinel_api.email.resend import (
    ResendEmailProvider,
    ResendTransport,
    ResendTransportError,
    ResendTransportResponse,
    TransportEffect,
)
from sentinel_api.email.service import (
    ControlledRecipientError,
    EmailAuthorizationError,
    EmailExecutionService,
)
from sentinel_api.email.store import (
    EmailExecutionStore,
    ExecutionStateConflict,
    InMemoryEmailExecutionStore,
)

__all__ = [
    "ApprovedEmailPayload",
    "ControlledRecipientError",
    "DeterministicFakeEmailProvider",
    "DispatchDisposition",
    "EmailAuthorizationError",
    "EmailDispatchRequest",
    "EmailExecutionRecord",
    "EmailExecutionService",
    "EmailExecutionStore",
    "EmailMessage",
    "EmailProvider",
    "ExecutionStateConflict",
    "FakeProviderBehavior",
    "InMemoryEmailExecutionStore",
    "PostgresEmailExecutionStore",
    "ProviderAuditEvent",
    "ProviderDispatchResult",
    "ProviderReceipt",
    "ProviderReconciliationResult",
    "ReconciliationDisposition",
    "ResendEmailProvider",
    "ResendTransport",
    "ResendTransportError",
    "ResendTransportResponse",
    "TransportEffect",
    "normalize_email_address",
    "validate_provider_message_id",
]
