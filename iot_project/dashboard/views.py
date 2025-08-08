from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
import json
from core.models import Device
from device_api.models import DeviceCommandQueue, SensorData

@login_required
def user_dashboard(request):
    """
    Renders the user dashboard, fetching data efficiently.
    """
    user_devices = Device.objects.filter(owner=request.user, is_registered=True).order_by('-last_seen')

    # Fix for Loading Delay: Use a single query to get the latest data ID for each device.
    latest_data_ids = SensorData.objects.values('device_id').annotate(
        max_timestamp=Max('timestamp')
    ).values_list('id', flat=True)

    # Fetch all latest data entries in one go.
    latest_data_entries = SensorData.objects.filter(
        id__in=latest_data_ids,
        device__in=user_devices
    ).select_related('device')

    # Create a dictionary for quick lookup of latest data by device ID
    latest_data_dict = {entry.device_id: entry for entry in latest_data_entries}

    devices_with_latest_data = []
    current_time = timezone.now()

    # Fix for Status Issue: Calculate the time difference in the view.
    for device in user_devices:
        latest_data_entry = latest_data_dict.get(device.id)
        latest_data = latest_data_entry.data if latest_data_entry else {}
        is_online = False
        if latest_data_entry and latest_data_entry.timestamp:
            time_difference = current_time - latest_data_entry.timestamp
            # A device is considered 'online' if it has sent data in the last 5 minutes.
            if time_difference.total_seconds() < 300:
                is_online = True

        devices_with_latest_data.append({
            'device': device,
            'latest_data': latest_data,
            'is_online': is_online,
        })

    context = {
        'devices_with_latest_data': devices_with_latest_data
    }
    return render(request, 'dashboard/dashboard.html', context)

@login_required
def device_detail(request, device_id):
    device = get_object_or_404(Device, id=device_id, owner=request.user)

    # Fetch the latest sensor data to check for its existence
    latest_data = SensorData.objects.filter(device=device).order_by('-timestamp').first()
    has_sensor_data = latest_data is not None

    context = {
        'device': device,
        'has_sensor_data': has_sensor_data,
    }
    return render(request, 'dashboard/device_detail.html', context)

@login_required
@require_POST
def control_device(request, device_id):
    device = get_object_or_404(Device, id=device_id, owner=request.user)
    
    # The frontend is sending FormData, so use request.POST
    command_type = request.POST.get('command')
    parameters_json_str = request.POST.get('parameters', '{}') # This will be a JSON string

    try:
        parameters_dict = json.loads(parameters_json_str)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid parameters JSON format.'}, status=400)

    # Example: Specific command for power_monitor device
    if device.device_type == 'power_monitor' and command_type == 'set_relay_state':
        state = parameters_dict.get('state')
        if state not in ['ON', 'OFF']:
            return JsonResponse({'status': 'error', 'message': 'Invalid state parameter for set_relay_state.'}, status=400)
        
        # Create a command in the queue
        DeviceCommandQueue.objects.create(
            device=device,
            command_type=command_type,
            parameters=parameters_dict,
            is_pending=True
        )
        
        # IMPORTANT: Return the 'state' in the JSON response for frontend feedback
        return JsonResponse({'status': 'success', 'message': f'Command "{command_type}" queued for {device.name}.', 'state': state})
    
    # Add conditions for other device types and their specific commands
    # elif device.device_type == 'water_level' and command_type == 'turn_pump_on':
    #     # ... your logic here ...
    #     return JsonResponse({'status': 'success', 'message': 'Water pump turned on.', 'state': 'ON'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid command type or not applicable for this device type.'}, status=400)