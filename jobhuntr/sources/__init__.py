"""Registry of source adapters keyed by the 'type' field in sources.json."""
from . import icims, jibe, neogov, oracle, taleo, talentbrew, usajobs, workday
from .base import SourceContext

ADAPTERS = {
    "workday": workday,
    "talentbrew": talentbrew,
    "oracle": oracle,
    "icims": icims,
    "neogov": neogov,
    "usajobs": usajobs,
    "jibe": jibe,
    "taleo": taleo,
}

__all__ = ["ADAPTERS", "SourceContext"]
