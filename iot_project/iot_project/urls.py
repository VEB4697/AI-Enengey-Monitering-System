from django.contrib import admin
from django.urls import path, include
from core.views import homepage, register_user, login_user, logout_user, device_onboarding_view, add_device_to_user

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', homepage, name='homepage'),
    path('register/', register_user, name='register'),
    path('login/', login_user, name='login'),
    path('logout/', logout_user, name='logout'),

    # Public facing device onboarding (before login/register)
    path('device-setup/', device_onboarding_view, name='device_onboarding'),
    # Page after login/register to associate device
    path('add-device/', add_device_to_user, name='add_device_to_user'),

    path('api/v1/device/', include('device_api.urls')), # Device API endpoints
    path('dashboard/', include('dashboard.urls')),     # User dashboard
]