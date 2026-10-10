"""
Role -> permission map. One place to read and audit who can do what.

Permission strings are checked by views (BusinessViewMixin.required_permission)
and by the REST API (HasBusinessPermission).
"""

OWNER, MANAGER, EMPLOYEE = "OWNER", "MANAGER", "EMPLOYEE"

_EMPLOYEE = {
    "products.view",
    "sales.view",
    "sales.create",
    "customers.view",
    "notifications.view",
}

_MANAGER = _EMPLOYEE | {
    "products.manage",       # includes seeing purchase (cost) prices
    "suppliers.manage",
    "inventory.view",
    "inventory.manage",
    "sales.cancel",
    "customers.manage",
    "analytics.sales",       # sales dashboard, top products, low stock
    "reports.view",          # non-financial reports
    "ml.view",
}

_OWNER = _MANAGER | {
    "analytics.financial",   # profit, expenses, inventory value
    "reports.financial",
    "expenses.manage",
    "team.manage",
    "settings.manage",
    "audit.view",
    "ml.train",
}

ROLE_PERMISSIONS = {OWNER: _OWNER, MANAGER: _MANAGER, EMPLOYEE: _EMPLOYEE}


def perms_for_role(role):
    return ROLE_PERMISSIONS.get(role, set())


def has_perm(role, perm):
    return perm in perms_for_role(role)
