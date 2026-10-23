from dataclasses import dataclass

from app.observability.tracing import RequestTrace
from app.schemas.models import Scope
from app.security.auth import Principal


@dataclass(frozen=True)
class InvocationContext:
    scope: Scope
    trace: RequestTrace
    principal: Principal | None = None
