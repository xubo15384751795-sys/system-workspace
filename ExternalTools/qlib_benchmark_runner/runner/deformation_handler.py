"""Qlib handler that appends the sandboxed deformation feature fields.

This module belongs to the external Qlib runner.  It is intentionally not
imported by the main System; the only contract across the boundary is the
read-only sandbox input and the JSON job spec.
"""

from __future__ import annotations

from qlib.contrib.data.handler import Alpha158


DEFAULT_DEFORMATION_FIELDS = (
    "deform_M",
    "deform_D",
    "deform_K",
    "deform_X",
    "deform_M_vel5",
    "deform_D_vel5",
    "deform_K_vel5",
    "deform_X_vel5",
    "deform_M_vel10",
    "deform_D_vel10",
    "deform_K_vel10",
    "deform_X_vel10",
    "deform_M_vel20",
    "deform_D_vel20",
    "deform_K_vel20",
    "deform_X_vel20",
    "deform_cofire_5d",
    "deform_cofire_10d",
    "deform_cofire_20d",
    "deform_velocity_gate",
    "deform_stress_level",
    "deform_M_stress_flag",
    "deform_D_stress_flag",
    "deform_K_stress_flag",
    "deform_X_stress_flag",
    "deform_M_vol20d",
    "deform_D_vol20d",
    "deform_K_vol20d",
    "deform_X_vol20d",
)


class DeformationAlpha158(Alpha158):
    """Alpha158 plus explicit raw deformation fields from the sandbox."""

    def __init__(self, *args, deformation_fields=None, **kwargs):
        self.deformation_fields = tuple(deformation_fields or DEFAULT_DEFORMATION_FIELDS)
        if not self.deformation_fields:
            raise ValueError("deformation_fields must not be empty")
        super().__init__(*args, **kwargs)

    def get_feature_config(self):
        fields, names = super().get_feature_config()
        fields.extend(f"${field}" for field in self.deformation_fields)
        names.extend(field.upper() for field in self.deformation_fields)
        return fields, names


__all__ = ["DEFAULT_DEFORMATION_FIELDS", "DeformationAlpha158"]
