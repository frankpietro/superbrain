"""Historical data source fetchers for phase-2 backfill.

Each submodule returns raw polars frames in the source's native schema plus a
``source``, ``league`` and ``season`` column. Canonicalization and the merge
into ``Match`` / ``TeamMatchStats`` happens in
:mod:`superbrain.scrapers.historical.merge`.
"""
