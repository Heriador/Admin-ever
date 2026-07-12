from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Role, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "user_type", "client", "partner", "is_active")
    list_filter = ("user_type", "is_active", "roles")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Organization & roles", {"fields": ("user_type", "client", "partner", "roles")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Organization & roles", {"fields": ("user_type", "client", "partner", "roles")}),
    )
    filter_horizontal = BaseUserAdmin.filter_horizontal + ("roles",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
