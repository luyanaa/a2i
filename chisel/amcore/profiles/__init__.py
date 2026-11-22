"""Pipeline profiles: parameterize the shared skeleton into a concrete core.
Each profile selects a control style around the same frozen kernel set."""

from .a2i import InOrderCore   # noqa: F401
from .a2o import OoOCore      # noqa: F401
