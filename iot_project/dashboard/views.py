from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
from core.models import Device
from device_api.models import SensorData, DeviceCommandQueue
from django.db.models import Max 

@login_required
def user_dashboard(request):
    user_devices = Device.objects.filter(owner=request.user, is_registered=True).order_by('-last_seen')
    
    # Fetch latest sensor data for each device to display on dashboard summary
    devices_with_latest_data = []
    for device in user_devices:
        latest_data_entry = SensorData.objects.filter(device=device).order_by('-timestamp').first()
        latest_data = latest_data_entry.data if latest_data_entry else {}
        devices_with_latest_data.append({
            'device': device,
            'latest_data': latest_data
        })

    context = {
        'devices_with_latest_data': devices_with_latest_data
    }
    return render(request, 'dashboard/dashboard.html', context)

@login_required
def device_detail(request, device_id):
    device = get_object_or_404(Device, id=device_id, owner=request.user)
    
    # Get recent sensor data for display/charts
    # IMPORTANT: Fetch the data and convert timestamps to ISO format for JSON serialization
    raw_sensor_data_entries = SensorData.objects.filter(device=device).order_by('-timestamp')[:100] # Last 100 readings
    
    # Prepare sensor data for JavaScript (graph and table)
    # This is crucial for the frontend JS to parse it correctly
    sensor_data_for_js = []
    for entry in raw_sensor_data_entries:
        sensor_data_for_js.append({
            'timestamp': entry.timestamp.isoformat(), # Convert datetime object to ISO 8601 string
            'data': entry.data # Assuming 'data' is a JSONField or stores a dict
        })

    context = {
        'device': device,
        # Pass the serialized JSON string of sensor data entries
        'sensor_data_entries': json.dumps(sensor_data_for_js), 
        # Removed chart_labels and chart_data from context, as frontend JS will generate them
        # from sensor_data_entries directly.
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