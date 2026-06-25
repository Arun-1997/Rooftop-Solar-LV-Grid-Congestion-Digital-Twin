"""Validation harness. P1: compare physics yield against PVGIS."""

from .pvgis_check import pvgis_reference_yield, validate_against_pvgis

__all__ = ["validate_against_pvgis", "pvgis_reference_yield"]
