"""Provider profiles for live model discovery and capability-tier resolution.

Each concrete profile knows how to list its provider's models, declare
caching behaviour per model, and resolve a tier (Fast/Balanced/Premium/
Reasoning/Local) to a concrete model id.

The registry maps provider names to profile instances and is the single
entry point used by the rest of the app.
"""

from app.services.ai.profiles.base import (
    Capability,
    CapabilityTier,
    ModelDescriptor,
    ProviderProfile,
)

__all__ = [
    "Capability",
    "CapabilityTier",
    "ModelDescriptor",
    "ProviderProfile",
]
