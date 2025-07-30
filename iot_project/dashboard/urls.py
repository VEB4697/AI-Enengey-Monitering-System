from django.urls import path
from .views import user_dashboard, device_detail, control_device

app_name = 'dashboard' # Namespace for dashboard URLs

urlpatterns = [
    path('', user_dashboard, name='user_dashboard'),
    path('<int:device_id>/', device_detail, name='device_detail'),
    path('<int:device_id>/control/', control_device, name='control_device'),
]