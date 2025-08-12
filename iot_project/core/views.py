from django.shortcuts import render, redirect, get_object_or_404
from .forms import CustomUserCreationForm
import requests
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import Device
from django.utils import timezone
from django.contrib import messages
from .forms import CustomUserChangeForm
from django.shortcuts import redirect


@login_required
def profile_view(request):
    """
    Handles displaying and processing the user profile update form.
    
    On a GET request, it initializes a CustomUserChangeForm with the current
    user's data and renders the profile page.
    
    On a POST request, it validates the form submission, saves the changes
    to the user's profile, and provides feedback using Django messages.
    """
    if request.method == 'POST':
        # Pass the current user instance and request.FILES to the form
        form = CustomUserChangeForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile') # Redirect back to the profile page
        else:
            # THIS IS THE CORRECTED PART:
            # Instead of a generic error, we'll display specific form errors.
            for field, error_list in form.errors.items():
                for error in error_list:
                    # We can log the error for debugging on the server-side as well
                    print(f"Form error on field '{field}': {error}")
                    messages.error(request, f"Error in {field}: {error}")
            
            # Keep the form instance for rendering on the page with errors
            return render(request, 'core/profile.html', {'form': form})
    else:
        # For a GET request, pre-populate the form with existing user data
        form = CustomUserChangeForm(instance=request.user)
    
    return render(request, 'core/profile.html', {'form': form})

@login_required
def settings_view(request):
    return render(request, 'core/settings.html')

def homepage(request):
    return render(request, 'core/homepage.html')

def register_user(request):
    if request.method == 'POST':
        # *** ADDED FOR DEBUGGING: Print raw POST and FILES data ***
        print("Received POST data:", request.POST)
        print("Received FILES data:", request.FILES)

        # Use your CustomUserCreationForm and pass request.FILES for profile picture
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.username}! Your account has been created.")

            # Check if device_api_key was passed in the session or GET params for auto-linking
            device_api_key = request.GET.get('device_api_key') or request.session.pop('pending_device_api_key', None)
            if device_api_key:
                try:
                    device = Device.objects.get(device_api_key=device_api_key)
                    if not device.is_registered:
                        device.owner = user
                        device.is_registered = True
                        device.save()
                        messages.success(request, f"Device '{device.name}' has been linked to your account.")
                    else:
                        messages.info(request, f"Device '{device.name}' is already registered to another user.")
                except Device.DoesNotExist:
                    messages.error(request, "The provided Device API Key was invalid or not found.")
            return redirect('dashboard:user_dashboard') # Redirect to dashboard
        else:
            # Form is not valid, add error messages for user feedback
            print("Form errors (from form.errors):", form.errors) # *** ADDED FOR DEBUGGING ***
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error in {field}: {error}")
    else:
        # For GET request, initialize the form
        form = CustomUserCreationForm()
        # If user arrived from device_onboarding_view with a valid key, store it in session
        device_api_key = request.GET.get('device_api_key')
        if device_api_key:
            request.session['pending_device_api_key'] = device_api_key
            messages.info(request, "Please create an account to link your device.")

    return render(request, 'core/register.html', {'form': form})

def login_user(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")

            # Check for pending device_api_key in session (if user came from onboarding)
            device_api_key = request.session.pop('pending_device_api_key', None)
            if device_api_key:
                try:
                    device = Device.objects.get(device_api_key=device_api_key)
                    if not device.is_registered:
                        device.owner = user
                        device.is_registered = True
                        device.save()
                        messages.success(request, f"Device '{device.name}' has been linked to your account.")
                    else:
                        messages.info(request, f"Device '{device.name}' is already registered to another user.")
                except Device.DoesNotExist:
                    messages.error(request, "The provided Device API Key was invalid or not found.")
            return redirect('dashboard:user_dashboard')
        else:
            messages.error(request, "Invalid username or password. Please try again.")
    else:
        form = AuthenticationForm()
        # If user arrived from device_onboarding_view with a valid key, store it in session
        device_api_key = request.GET.get('device_api_key')
        if device_api_key:
            request.session['pending_device_api_key'] = device_api_key
            messages.info(request, "Please login to link your device.")
    return render(request, 'core/login.html', {'form': form})

def logout_user(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('homepage')

def device_onboarding_view(request):
    if request.method == 'POST':
        device_api_key = request.POST.get('device_api_key')
        URL = '192.168.0.116'
        
        if not device_api_key:
            messages.error(request, "Please enter a Device API Key.", extra_tags='device_onboarding')
            return redirect('device_onboarding')
        
        try:
<<<<<<< HEAD
            api_url = f"http://{URL}:8000/api/v1/device/onboard-check/?device_api_key={device_api_key}"
=======
            api_url = f"http://127.0.0.1:8000/api/v1/device/onboard-check/?device_api_key={device_api_key}"
>>>>>>> d73c3e2384d1c0794391d819931557b916313724
            response = requests.get(api_url)
            data = response.json()

            if response.status_code == 200:
                messages.success(request, f"Device '{data.get('device_name')}' is online and available for registration!", extra_tags='device_onboarding')
<<<<<<< HEAD
=======
            elif response.status_code == 409:
                messages.info(request, "API key is already registered.", extra_tags='device_onboarding')
>>>>>>> d73c3e2384d1c0794391d819931557b916313724
            elif response.status_code == 412:
                messages.warning(request, data.get('message', 'Device is offline. Please check its connection.'), extra_tags='device_onboarding')
            elif response.status_code == 404:
                messages.error(request, data.get('message', 'API key is not registered.'), extra_tags='device_onboarding')
            else:
                messages.error(request, data.get('message', 'An unexpected error occurred.'), extra_tags='device_onboarding')

        except requests.exceptions.RequestException:
            messages.error(request, "Network error. The server is unreachable.", extra_tags='device_onboarding')

        return redirect('device_onboarding')
    
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
            messages.error(request, 'Device API Key is required.')
            return JsonResponse({'status': 'error', 'message': 'Device API Key is required.'}, status=400)

        try:
            device = Device.objects.get(device_api_key=device_api_key)
            if device.is_registered:
                messages.warning(request, 'This device is already registered to a user.')
                return JsonResponse({'status': 'error', 'message': 'This device is already registered to a user.'}, status=409)
            if not device.is_online or (timezone.now() - device.last_seen).total_seconds() > 300: # Device must be recently online
                messages.warning(request, 'Device not online or responsive. Please ensure it is powered on and connected to Wi-Fi.')
                return JsonResponse({'status': 'error', 'message': 'Device not online or responsive. Please ensure it is powered on and connected to Wi-Fi.'}, status=412)

            device.owner = request.user
            device.is_registered = True
            device.save()
            messages.success(request, f'Device "{device.name}" successfully added to your account!')
            return JsonResponse({'status': 'success', 'message': f'Device "{device.name}" successfully added to your account!', 'redirect_url': '/dashboard/'})
        except Device.DoesNotExist:
            messages.error(request, 'Invalid Device API Key. Please check the key on your device.')
            return JsonResponse({'status': 'error', 'message': 'Invalid Device API Key. Please check the key on your device.'}, status=404)
        except Exception as e:
            messages.error(request, f'An unexpected error occurred: {str(e)}')
            return JsonResponse({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=500)
    return render(request, 'core/add_device.html') # A simple form to input API key

@login_required
def remove_device(request, device_id):
    """
    Handles removing a device from the user's account.
    """
    device = get_object_or_404(Device, id=device_id, owner=request.user)
    device.owner = None
    device.is_registered = False
    device.save()
    messages.success(request, f'Device "{device.name}" has been removed from your account.')
    return redirect('settings') # Assuming 'settings' is the name of your settings page URL