from django.contrib import admin

from .models import Business, BusinessMember


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "business_type", "is_active", "created_at")
    list_filter = ("business_type", "is_active")
    search_fields = ("name",)


@admin.register(BusinessMember)
class BusinessMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "business", "role", "is_active")
    list_filter = ("role", "is_active")
