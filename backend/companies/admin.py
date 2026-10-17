# Company admin registration placeholder
from django.contrib import admin
from .models import Company, Route

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'areas_served', 'phone_number']
    search_fields = ['name', 'areas_served']

@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ['name', 'company', 'start_point', 'end_point', 'price']
    list_filter = ['company']