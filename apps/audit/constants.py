"""Nilai enum audit; dipakai model, service, dan tampilan read-only."""

ENTITY_VALUES = (
    "transaction",
    "stock_movement",
    "item",
    "category",
    "stock_item",
    "account",
    "account_transfer",
    "period_lock",
    "attachment",
    "company_profile",
    "user",
    "export",
)

ACTION_VALUES = (
    "create",
    "update",
    "delete",
    "lock",
    "unlock",
    "export",
    "upload",
    "login_failed",
)

NON_ENTITY_ACTIONS = frozenset({"export", "login_failed"})
