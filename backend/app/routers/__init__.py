"""Route modules, one APIRouter per area (#170).

These are the web layer. A handler's job is to translate HTTP to a single
service call and back — `with translate_errors(): return project.<method>(...)`
— not to hold business logic or orchestrate across services. Logic and
cross-service orchestration live behind a `ProjectService` method under
`app/services/`; copy the nearest thin sibling when adding a route.

The dependency runs one way (routes -> services, never back), and that half is
enforced: `scripts/check_layer_imports.py` fails CI if a service imports the web
layer (ADR-0056, #977). "No logic in the handler" is not gated — it is held by
keeping every handler the same shape, so the correct pattern is the one you copy.
"""
