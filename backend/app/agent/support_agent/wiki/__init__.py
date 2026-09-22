"""Contract for exact lookup of reviewed support Wiki entries."""

from typing import Protocol

from app.agent.schemas import SupportProgramRef
from app.agent.support_agent.models import ReviewedSupportCatalog

__all__ = ["SupportWikiStore"]


class SupportWikiStore(Protocol):
    async def lookup(self, ref: SupportProgramRef) -> ReviewedSupportCatalog | None: ...
