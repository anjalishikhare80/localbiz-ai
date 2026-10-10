from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("Extra", {"fields": ("phone",)}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (("Extra", {"fields": ("email", "phone")}),)
    list_display = ("username", "email", "is_staff", "is_active")
    search_fields = ("username", "email")
