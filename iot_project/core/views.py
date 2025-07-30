from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt # Use cautiously, for APIs not standard forms
from .models import Device
from django.utils import timezone

def homepage(request):
    return render(request, 'core/homepage.html')

def register_user(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # Check if device_api_key was passed in the session or GET params for auto-linking
            device_api_key = request.GET.get('device_api_key') or request.session.pop('pending_device_api_key', None)
            if device_api_key:
                try:
                    device = Device.objects.get(device_api_key=device_api_key)
                    if not device.is_registered:
                        device.owner = user
                        device.is_registered = True
                        device.save()
                        # Optionally add success message
                except Device.DoesNotExist:
                    pass # Device key invalid or not found
            return redirect('dashboard:user_dashboard') # Redirect to dashboard
    else:
        form = UserCreationForm()
        # If user arrived from device_onboarding_view with a valid key, store it in session
        device_api_key = request.GET.get('device_api_key')
        if device_api_key:
            request.session['pending_device_api_key'] = device_api_key
    return render(request, 'core/register.html', {'form': form})

def login_user(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Check for pending device_api_key in session (if user came from onboarding)
            device_api_key = request.session.pop('pending_device_api_key', None)
            if device_api_key:
                try:
                    device = Device.objects.get(device_api_key=device_api_key)
                    if not device.is_registered:
                        device.owner = user
                        device.is_registered = True
                        device.save()
                        # Optionally add success message
                except Device.DoesNotExist:
                    pass
            return redirect('dashboard:user_dashboard')
    else:
        form = AuthenticationForm()
        # If user arrived from device_onboarding_view with a valid key, store it in session
        device_api_key = request.GET.get('device_api_key')
        if device_api_key:
            request.session['pending_device_api_key'] = device_api_key
    return render(request, 'core/login.html', {'form': form})

def logout_user(request):
    logout(request)
    return redirect('homepage')

def device_onboarding_view(request):
    """
    Public-facing view for users to enter device API key to check its status.
    This page guides them to login/register after a successful check.
    """
    return render(request, 'core/device_onboarding.html')

@login_required
def add_device_to_user(request):
    """
    Page for a logged-in user to explicitly add a device using its API key.
    This is for cases where the device wasn't linked during initial registration/login.
    """
    if request.method == 'POST':
        device_api_key = request.POST.get('device_api_key')
        if not device_api_key:
            return JsonResponse({'status': 'error', 'message': 'Device API Key is required.'}, status=400)

        try:
            device = Device.objects.get(device_api_key=device_api_key)
            if device.is_registered:
                return JsonResponse({'status': 'error', 'message': 'This device is already registered to a user.'}, status=409)
            if not device.is_online or (timezone.now() - device.last_seen).total_seconds() > 300: # Device must be recently online
                return JsonResponse({'status': 'error', 'message': 'Device not online or responsive. Please ensure it is powered on and connected to Wi-Fi.'}, status=412)

            device.owner = request.user
            device.is_registered = True
            device.save()
            return JsonResponse({'status': 'success', 'message': f'Device "{device.name}" successfully added to your account!', 'redirect_url': '/dashboard/'})
        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Invalid Device API Key. Please check the key on your device.'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=500)
    return render(request, 'core/add_device.html') # A simple form to input API key