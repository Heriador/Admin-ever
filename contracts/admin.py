from django.contrib import admin

from .models import Contract


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("reference", "client", "status", "start_date", "end_date")
    list_filter = ("status",)
    search_fields = ("reference", "client__name")
    date_hierarchy = "start_date"
