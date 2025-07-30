from django.db import models
from django.utils import timezone
from core.models import Device # Import Device from core app

class SensorData(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='sensor_data')
    timestamp = models.DateTimeField(auto_now_add=True)
    # Use JSONField to store generic sensor readings
    data = models.JSONField(help_text="JSON object containing sensor readings (e.g., {'voltage': 230, 'current': 1.5})")

    def __str__(self):
        return f"Sensor data from {self.device.name} at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

    class Meta:
        verbose_name = "Sensor Data"
        verbose_name_plural = "Sensor Data"
        ordering = ['-timestamp']

class CommandLog(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='command_logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    command_type = models.CharField(max_length=50, help_text="e.g., 'set_relay_state', 'turn_pump_on'")
    parameters = models.JSONField(blank=True, null=True, help_text="Optional JSON parameters for the command")
    executed = models.BooleanField(default=False, help_text="True if the device reported executing the command")
    executed_at = models.DateTimeField(null=True, blank=True)
    response = models.TextField(blank=True, null=True, help_text="Device's response to the command (optional)")

    def __str__(self):
        return f"Command '{self.command_type}' for {self.device.name} at {self.timestamp}"

    class Meta:
        verbose_name = "Command Log"
        verbose_name_plural = "Command Logs"
        ordering = ['-timestamp']

class DeviceCommandQueue(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='command_queue')
    command_type = models.CharField(max_length=50, help_text="Command to be sent to device")
    parameters = models.JSONField(blank=True, null=True, help_text="JSON parameters for the command")
    created_at = models.DateTimeField(auto_now_add=True)
    is_pending = models.BooleanField(default=True, help_text="True if command is waiting for device to poll")

    def __str__(self):
        return f"Pending '{self.command_type}' for {self.device.name} (Created: {self.created_at})"

    class Meta:
        verbose_name = "Device Command in Queue"
        verbose_name_plural = "Device Command Queue"
        ordering = ['created_at']