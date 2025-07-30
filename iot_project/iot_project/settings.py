# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ... other settings ...

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework', # For API
    'core',         # Your core app
    'device_api',   # Your device API app
    'dashboard',    # Your dashboard app
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'iot_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')], # Add a project-wide templates directory if you want
        'APP_DIRS': True, # This allows Django to find templates in app's 'templates' folder
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'iot_project.wsgi.application'

# ... Database configuration (use PostgreSQL for production) ...
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# ... AUTH_PASSWORD_VALIDATORS ...

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata' # Set to your local timezone (Nashik, Maharashtra)
USE_I18N = True
USE_L10N = True
USE_TZ = True # Crucial for timezone-aware datetimes

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"), # If you have a project-level static folder
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles') # For collectstatic in production

# Media files (for user-uploaded content like profile pictures)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media') # This is where uploaded files will be stored

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/dashboard/' # Where to redirect after successful login
LOGOUT_REDIRECT_URL = '/'          # Where to redirect after logout

ALLOWED_HOSTS = ['127.0.0.1', 'localhost'] # Add your computer's local IP here if needed for ESP connection

DEBUG = True # Keep this as True for now

# IMPORTANT: Tell Django to use your custom user model
AUTH_USER_MODEL = 'core.CustomUser'

SECRET_KEY = 'django-insecure-your-very-long-and-random-secret-key-that-you-just-generated-and-copied-here!'