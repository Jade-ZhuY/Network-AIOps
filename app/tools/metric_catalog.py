"""Compatibility export; definitions live in data/metric_catalog.json."""

from app.semantics.catalog import public_catalog

CATALOG = public_catalog()["metrics"]
