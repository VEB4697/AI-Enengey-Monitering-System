from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils import timezone

class Device(models.Model):
    # device_api_key is unique and used for both initial setup and runtime ID
    device_api_key = models.CharField(max_length=36, unique=True, default=uuid.uuid4,
                                      help_text="Unique API key for the device, displayed on hardware")
    name = models.CharField(max_length=100, default="Unnamed Device")
    location = models.CharField(max_length=100, blank=True, null=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                              help_text="The user who owns this device. Null if not yet registered.")
    is_online = models.BooleanField(default=False, help_text="Indicates if the device has recently checked in.")
    last_seen = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful communication.")
    created_at = models.DateTimeField(auto_now_add=True)
    is_registered = models.BooleanField(default=False,
                                        help_text="True if device is linked to a user account.")

    # New field: device_type to categorize functionality
    DEVICE_TYPES = [
        ('power_monitor', 'Power Monitoring & Switch'),
        ('water_level', 'Water Level Sensor'),
        # Add more types as you expand your project
    ]
    device_type = models.CharField(max_length=50, choices=DEVICE_TYPES, default='power_monitor',
                                   help_text="The type of functionality this device provides.")

    def __str__(self):
        owner_name = self.owner.username if self.owner else 'Unregistered'
        return f"{self.name} ({self.get_device_type_display()}) - Owner: {owner_name} (Key: {self.device_api_key[:8]}...)"

    class Meta:
        verbose_name = "IoT Device"
        verbose_name_plural = "IoT Devices"
        ordering = ['name']