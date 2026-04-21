"""Lake schema migrations.

Migrations are numbered Python modules under this package. Each defines a
module-level ``VERSION`` (int) and a ``def apply(layout: LakeLayout) -> None``.
``Lake.ensure_schema`` runs every migration whose version is higher than the
one currently written in ``schema_manifest.json``.
"""

from __future__ import annotations

from superbrain.data.migrations import m001_initial_lake, m002_match_id_index

MIGRATIONS = [m001_initial_lake, m002_match_id_index]
