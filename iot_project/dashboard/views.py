from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from core.models import Device
from device_api.models import SensorData, DeviceCommandQueue
from django.db.models import Max # For latest sensor data

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
    sensor_data_entries = SensorData.objects.filter(device=device).order_by('-timestamp')[:100] # Last 100 readings
    
    # Prepare data for Chart.js - this will need to be dynamic based on device_type
    chart_labels = []
    chart_data = {} # Dictionary to hold different data series (e.g., 'voltage', 'power')

    # Initialize data series based on expected keys for 'power_monitor' type
    if device.device_type == 'power_monitor':
        chart_data['voltage'] = []
        chart_data['current'] = []
        chart_data['power'] = []
        chart_data['frequency'] = []
        chart_data['pf'] = []
    # Add conditions for other device types here
    # elif device.device_type == 'water_level':
    #    chart_data['water_level'] = []

    for data_entry in reversed(sensor_data_entries): # Reverse for chronological order on chart
        chart_labels.append(data_entry.timestamp.strftime('%H:%M:%S'))
        if device.device_type == 'power_monitor':
            chart_data['voltage'].append(data_entry.data.get('voltage'))
            chart_data['current'].append(data_entry.data.get('current'))
            chart_data['power'].append(data_entry.data.get('power'))
            chart_data['frequency'].append(data_entry.data.get('frequency'))
            chart_data['pf'].append(data_entry.data.get('pf'))
        # Add data for other device types
        # elif device.device_type == 'water_level':
        #    chart_data['water_level'].append(data_entry.data.get('water_level'))

    context = {
        'device': device,
        'sensor_data_entries': sensor_data_entries, # Raw data for detailed view
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data), # Send all chart data as a single JSON object
    }
    return render(request, 'dashboard/device_detail.html', context)

@login_required
@require_POST
def control_device(request, device_id):
    device = get_object_or_404(Device, id=device_id, owner=request.user)
    command_type = request.POST.get('command')
    parameters = request.POST.get('parameters', '{}')

    try:
        parameters_dict = json.loads(parameters)
    except json.JSONDecodeError:
        parameters_dict = {}

    # Example: Specific command for power_monitor device
    if device.device_type == 'power_monitor' and command_type == 'set_relay_state':
        if 'state' not in parameters_dict or parameters_dict['state'] not in ['ON', 'OFF']:
            return JsonResponse({'status': 'error', 'message': 'Invalid state parameter for set_relay_state.'}, status=400)
        
        DeviceCommandQueue.objects.create(
            device=device,
            command_type=command_type,
            parameters=parameters_dict,
            is_pending=True
        )
        return JsonResponse({'status': 'success', 'message': f'Command "{command_type}" queued for {device.name}.'})
    # Add conditions for other device types and their specific commands
    # elif device.device_type == 'water_level' and command_type == 'turn_pump_on':
    #     DeviceCommandQueue.objects.create(...)
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid command type or not applicable for this device type.'}, status=400)