from django.urls import path
from .views import DeviceDataReceive, DeviceCommandPoll, DeviceOnboardingCheck, DeviceLatestDataRetrieve, DeviceAnalysisAPIView
from dashboard.views import device_analysis_page
app_name = 'device_api' # Namespace for API URLs

urlpatterns = [
    path('data/', DeviceDataReceive.as_view(), name='device_data_receive'),
    path('commands/', DeviceCommandPoll.as_view(), name='device_command_poll'),
    path('onboard-check/', DeviceOnboardingCheck.as_view(), name='device_onboarding_check'),
    path('<int:device_id>/latest_data/', DeviceLatestDataRetrieve.as_view(), name='device-latest-data-retrieve'),
    path('<int:device_id>/analysis_page/', device_analysis_page, name='device_analysis_page'),
    path('<int:device_id>/analysis/', DeviceAnalysisAPIView.as_view(), name='device_analysis_api'),

]