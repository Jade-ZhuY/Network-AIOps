from dataclasses import dataclass

from app.observability.tracing import RequestTrace
from app.schemas.models import Scope


@dataclass(frozen=True)
class InvocationContext:
    scope: Scope
    trace: RequestTrace
