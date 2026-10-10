class BusinessRuleError(Exception):
    """Raised by service functions when a business rule is violated (e.g. not enough stock)."""


class InsufficientStock(BusinessRuleError):
    pass
