"""Base protocol interface."""
from abc import ABC, abstractmethod
from ..council.session import Session, SessionResult
from ..config import CouncilConfig
from ..providers.router import ModelRouter


class BaseProtocol(ABC):
    def __init__(self, config: CouncilConfig, router: ModelRouter):
        self.config = config
        self.router = router

    @abstractmethod
    async def execute(self, session: Session) -> SessionResult:
        ...
