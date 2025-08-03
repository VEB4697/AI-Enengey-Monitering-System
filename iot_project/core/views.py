from django.shortcuts import render, redirect
from .forms import CustomUserCreationForm
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

@login_required
def profile_view(request):
    """
    Handles displaying and processing the user profile update form.
    
    On a GET request, it initializes a CustomUserChangeForm with the current
    user's data and renders the profile page.
    
    On a POST request, it validates the form submission, saves the changes
    to the user's profile, and provides feedback using Django messages.
    """
    # The view correctly handles both GET and POST requests.
    if request.method == 'POST':
        # Pass the current user instance and request.FILES to the form
        form = CustomUserChangeForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile') # Redirect back to the profile page
        else:
            # THIS IS THE DEBUGGING LINE I HAVE ADDED
            print(form.errors)
            messages.error(request, 'There was an error updating your profile. Please check the form.')
    else:
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