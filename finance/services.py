from .models import ExpenseCategory

DEFAULT_CATEGORIES = ["Rent", "Electricity", "Internet", "Transportation", "Salaries", "Maintenance", "Marketing", "Other"]


def create_default_categories(business):
    for name in DEFAULT_CATEGORIES:
        ExpenseCategory.objects.get_or_create(business=business, name=name)
