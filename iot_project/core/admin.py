from django.contrib import admin
from django.contrib.auth.admin import UserAdmin # Import UserAdmin for custom user models
from .models import CustomUser, Device # Import both CustomUser and Device
from django.utils import timezone # Import timezone for custom admin actions

# Register CustomUser with the admin site
# We use UserAdmin as a base to ensure all default user management features are present
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    # If you want to customize how CustomUser appears in the admin,
    # you can define list_display, fieldsets, add_fieldsets, etc., here.
    # For example, to show custom fields in the admin list view:
    # Removed 'is_online' as it's not a field on CustomUser
    list_display = UserAdmin.list_display + ('phone_number', 'date_of_birth', 'gender') 

    # To add custom fields to the user detail page in admin:
    fieldsets = UserAdmin.fieldsets + (
        ('Personal Info (IoT)', {
            'fields': ('phone_number', 'date_of_birth', 'gender', 'address', 'profile_picture'),
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Personal Info (IoT)', {
            'fields': ('phone_number', 'date_of_birth', 'gender', 'address', 'profile_picture'),
        }),
    )

# Register Device model with the admin site
@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'device_api_key', 'owner', 'device_type', 'is_online', 'last_seen', 'is_registered')
    list_filter = ('device_type', 'is_online', 'is_registered', 'owner')
    search_fields = ('name', 'device_api_key', 'owner__username')
    raw_id_fields = ('owner',) # Use a raw ID input for owner to improve performance with many users
    actions = ['mark_online', 'mark_offline', 'mark_registered', 'mark_unregistered']

    def mark_online(self, request, queryset):
        queryset.update(is_online=True, last_seen=timezone.now())
    mark_online.short_description = "Mark selected devices as online"

    def mark_offline(self, request, queryset):
        queryset.update(is_online=False)
    mark_offline.short_description = "Mark selected devices as offline"
    
    def mark_registered(self, request, queryset):
        queryset.update(is_registered=True)
    mark_registered.short_description = "Mark selected devices as registered"

    def mark_unregistered(self, request, queryset):
        queryset.update(is_registered=False, owner=None)
    mark_unregistered.short_description = "Mark selected devices as unregistered and remove owner"

