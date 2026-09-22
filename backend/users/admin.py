from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from .models import CustomUser

# 1. Custom forms to explicitly support your new custom database fields
class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = CustomUser

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email', 'phone_number', 'location', 'company', 'role')

# 2. The corrected Admin controller
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    
    # Custom dashboard table columns
    list_display = ['username', 'phone_number', 'get_company', 'location', 'is_staff']
    search_fields = ['username', 'phone_number', 'email']
    ordering = ['username']
    
    # Clean field blocks for editing an existing user profile
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ('Connect Info', {'fields': ('phone_number', 'location', 'company', 'role', 'boarded_count', 'no_show_count')}),
    )

    # Clean field blocks for creating a brand new user via the dashboard (+)
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'phone_number', 'location', 'company', 'role', 'password1', 'password2'),
        }),
    )

    # Safe dynamic lookup to ensure empty companies don't crash the table
    @admin.display(ordering='company', description='Company')
    def get_company(self, obj):
        return obj.company.name if obj.company else "Independent / Admin"