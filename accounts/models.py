from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Platform-wide user account.

    Roles are NOT stored here. A person's role (owner/manager/employee)
    belongs to their membership in a specific business.
    """

    email = models.EmailField("email address", unique=True)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.username
