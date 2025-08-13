from django.urls import path
from .views import user_dashboard, device_detail, control_device, device_analysis_page

app_name = 'dashboard' # Namespace for dashboard URLs

urlpatterns = [
    path('', user_dashboard, name='user_dashboard'),
    path('<int:device_id>/', device_detail, name='device_detail'),
    path('<int:device_id>/control/', control_device, name='control_device'),
    path('<int:device_id>/analysis_page/', device_analysis_page, name='device_analysis_page'),

]