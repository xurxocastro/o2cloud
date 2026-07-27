"""o2cloud — a scriptable, agent-friendly CLI for O2 Cloud.

O2 Cloud is the personal-cloud storage service of O2 / Telefónica España
(``cloud.o2online.es``). Its backend is **Funambol OneMediaHub**, reached through
the SAPI namespace at ``https://cloud.o2online.es/sapi/``.

The infrastructure, CLI surface, output contract, and typed models sit above a
SAPI client that speaks the reverse-engineered Funambol OneMediaHub API. The
observed endpoints, headers, and token mechanics are documented in
``docs/api-reference.md``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.4.0"
