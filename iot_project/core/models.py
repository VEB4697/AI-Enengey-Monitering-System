from django.db import models
from django.contrib.auth.models import AbstractUser # Import AbstractUser
import uuid
from django.utils import timezone

# Define choices for Gender - THIS MUST BE INSIDE THE CustomUser CLASS
# OR defined globally if you want it reusable and then referenced.
# For simplicity and direct association, let's keep it inside CustomUser for now.

class CustomUser(AbstractUser):
    # Define GENDER_CHOICES directly within the class
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('N', 'Prefer not to say'),
    ]

    # Add your custom fields here
    phone_number = models.CharField(max_length=15, blank=True, null=True, unique=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.username

class Device(models.Model):
    device_api_key = models.CharField(max_length=36, unique=True, default=uuid.uuid4,
                                      help_text="Unique API key for the device, displayed on hardware")
    name = models.CharField(max_length=100, default="Unnamed Device")
    location = models.CharField(max_length=100, blank=True, null=True)
    owner = models.ForeignKey('core.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, # Use string reference
                              help_text="The user who owns this device. Null if not yet registered.")
    is_online = models.BooleanField(default=False, help_text="Indicates if the device has recently checked in.")
    last_seen = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful communication.")
    created_at = models.DateTimeField(auto_now_add=True)
    is_registered = models.BooleanField(default=False,
                                        help_text="True if device is linked to a user account.")

    DEVICE_TYPES = [
        ('power_monitor', 'Power Monitoring & Switch'),
        ('water_level', 'Water Level Sensor'),
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
