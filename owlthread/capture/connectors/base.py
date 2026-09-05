"""Base interface for OwlThread pluggable connectors."""

from abc import ABC, abstractmethod
from typing import Optional

from owlthread.db.database import Database


class IConnector(ABC):
    """
    Common connector interface for watching local IDE or application storages.
    
    Subclasses implement Start(), Poll(), and Stop().
    """

    def __init__(self, db: Database, name: Optional[str] = None):
        self.db = db
        self.name = name or self.__class__.__name__
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Return True if connector is active."""
        return self._is_running

    @abstractmethod
    def start(self) -> None:
        """Initialize and start connector resources."""
        self._is_running = True

    @abstractmethod
    def poll(self) -> int:
        """
        Poll source storage for new/changed entries and write to DB.
        
        Returns:
            Number of newly captured entries.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop connector and release resources."""
        self._is_running = False

    # Capitalized aliases to satisfy explicit IConnector(Start(), Poll(), Stop()) requirement
    def Start(self) -> None:
        """Alias for start()."""
        return self.start()

    def Poll(self) -> int:
        """Alias for poll()."""
        return self.poll()

    def Stop(self) -> None:
        """Alias for stop()."""
        return self.stop()
