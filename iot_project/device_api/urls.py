from django.urls import path
from .views import DeviceDataReceive, DeviceCommandPoll, DeviceOnboardingCheck

app_name = 'device_api' # Namespace for API URLs

urlpatterns = [
    path('data/', DeviceDataReceive.as_view(), name='device_data_receive'),
    path('commands/', DeviceCommandPoll.as_view(), name='device_command_poll'),
    path('onboard-check/', DeviceOnboardingCheck.as_view(), name='device_onboarding_check'),
]