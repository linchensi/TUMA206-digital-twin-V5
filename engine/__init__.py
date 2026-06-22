"""Simulation engine package.

Keep the two engine implementations lazy.  The cloud monitor only needs the
remote MQTT proxy; importing the full plant runtime there is unnecessary and
breaks under Streamlit Community Cloud's Python 3.14 module watcher.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .remote import RemoteEngineProxy
    from .runtime import SimulationEngine

__all__ = ["SimulationEngine", "RemoteEngineProxy"]


def __getattr__(name: str):
    if name == "SimulationEngine":
        from .runtime import SimulationEngine

        return SimulationEngine
    if name == "RemoteEngineProxy":
        from .remote import RemoteEngineProxy

        return RemoteEngineProxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
