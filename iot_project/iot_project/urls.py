from django.contrib import admin
from django.urls import path, include
from core.views import (
    homepage,
    register_user,
    login_user,
    logout_user,
    device_onboarding_view,
    add_device_to_user,
    profile_view,        # ✅ make sure these are here
    settings_view        # ✅
)

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', homepage, name='homepage'),
    path('register/', register_user, name='register'),
    path('login/', login_user, name='login'),
    path('logout/', logout_user, name='logout'),

    path('device-setup/', device_onboarding_view, name='device_onboarding'),
    path('add-device/', add_device_to_user, name='add_device_to_user'),

    path('profile/', profile_view, name='profile'),         # 👤 Profile
    path('settings/', settings_view, name='settings'),

    path('api/v1/device/', include('device_api.urls')),
    path('dashboard/', include('dashboard.urls')),
]

# ONLY add this for development to serve media files
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
