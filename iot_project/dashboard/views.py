import json
import sys
import traceback
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q, OuterRef, Subquery
# ... other existing imports
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.models import Device
from device_api.models import DeviceCommandQueue, SensorData

# REQUIRED IMPORT FOR APIView
from rest_framework.views import APIView 
from rest_framework.response import Response # Also ensure Response is imported if used
from rest_framework import status # Also ensure status is imported if used

# For ML models and data manipulation
import pandas as pd
from sklearn.ensemble import IsolationForest
from prophet import Prophet
import logging

logger = logging.getLogger(__name__)

@login_required
def user_dashboard(request):
    """
    Renders the user dashboard, fetching data efficiently.
    """
    user_devices = Device.objects.filter(owner=request.user, is_registered=True).order_by('last_seen')

    latest_data_ids = SensorData.objects.values('device_id').annotate(
        max_timestamp=Max('timestamp')
    ).values_list('id', flat=True)

    latest_data_entries = SensorData.objects.filter(
        id__in=latest_data_ids,
        device__in=user_devices
    ).select_related('device')

    latest_data_dict = {entry.device_id: entry for entry in latest_data_entries}

    devices_with_latest_data = []
    current_time = timezone.now()

    for device in user_devices:
        latest_data_entry = latest_data_dict.get(device.id)
        latest_data = latest_data_entry.data if latest_data_entry else {} 
        is_online = False
        if latest_data_entry and device.last_seen:
            time_difference = current_time - device.last_seen
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
@require_POST
def control_device(request, device_id):
    device = get_object_or_404(Device, id=device_id, owner=request.user)
    
    command_type = request.POST.get('command')
    parameters_json_str = request.POST.get('parameters', '{}')

    try:
        parameters_dict = json.loads(parameters_json_str)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid parameters JSON format.'}, status=400)

    if device.device_type == 'power_monitor' and command_type == 'set_relay_state':
        state = parameters_dict.get('state')
        if not isinstance(state, bool):
             state = (state == 'ON')
        
        DeviceCommandQueue.objects.create(
            device=device,
            command_type=command_type,
            parameters={'relay_state': state},
            is_pending=True
        )
        
        response_state_str = "ON" if state else "OFF"
        return JsonResponse({'status': 'success', 'message': f'Command "{command_type}" queued for {device.name}.', 'state': response_state_str})
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid command type or not applicable for this device type.'}, status=400)
    
@login_required
def device_analysis_page(request, device_id):
    """
    Renders the device analysis page. The actual data fetching for charts and
    suggestions is done via JavaScript calling the /api/v1/devices/<id>/analysis/ API.
    """
    device = get_object_or_404(Device, pk=device_id, owner=request.user)
    context = {
        'device': device,
    }
    return render(request, 'dashboard/analysis_page.html', context)

@login_required 
def device_detail(request, device_id): 
    device = get_object_or_404(Device, id=device_id, owner=request.user) 

    sensor_data_entries = SensorData.objects.filter(device=device).order_by('timestamp')[:50] 
    
    chart_labels = [] 
    chart_data = { 
        'power': [], 
        'voltage': [], 
        'current': [], 
        'energy': [], 
        'frequency': [], 
        'power_factor': [], 
        'water_level': [] 
    } 

    for entry in sensor_data_entries: 
        # Ensure parsed_data is a dictionary, not a JSON string.
        try:
            parsed_data = json.loads(entry.data)
        except (json.JSONDecodeError, TypeError):
            parsed_data = {}
        
        chart_labels.append(entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')) 

        if device.device_type == 'power_monitor': 
            chart_data['power'].append(parsed_data.get('power')) 
            chart_data['voltage'].append(parsed_data.get('voltage')) 
            chart_data['current'].append(parsed_data.get('current')) 
            chart_data['energy'].append(parsed_data.get('energy')) 
            chart_data['frequency'].append(parsed_data.get('frequency')) 
            chart_data['power_factor'].append(parsed_data.get('power_factor')) 
        elif device.device_type == 'water_level': 
            chart_data['water_level'].append(parsed_data.get('water_level')) 
        
    chart_labels_json = json.dumps(chart_labels) 
    chart_data_json = json.dumps(chart_data) 

    # --- Added is_online calculation here ---
    current_time = timezone.now()
    is_online = False
    if device.last_seen: # device.last_seen is from the fetched Device object
        time_difference = current_time - device.last_seen
        if time_difference.total_seconds() < 300: # 5 minutes threshold
            is_online = True
    # --- End of added calculation ---

    context = { 
        'device': device, 
        'sensor_data_entries': sensor_data_entries, 
        'chart_labels': chart_labels_json, 
        'chart_data': chart_data_json, 
        'is_online': is_online, # Now correctly defined and passed
    } 
    return render(request, 'dashboard/device_detail.html', context)

    device = get_object_or_404(Device, id=device_id, owner=request.user)

    sensor_data_entries = SensorData.objects.filter(device=device).order_by('timestamp')[:50]
    
    chart_labels = []
    chart_data = {
        'power': [],
        'voltage': [],
        'current': [],
        'energy': [],
        'frequency': [],
        'power_factor': [],
        'water_level': []
    }

    for entry in sensor_data_entries:
        parsed_data = entry.data 
        
        chart_labels.append(entry.timestamp.strftime('%Y-%m-%d %H:%M:%S'))

        if device.device_type == 'power_monitor':
            chart_data['power'].append(parsed_data.get('power'))
            chart_data['voltage'].append(parsed_data.get('voltage'))
            chart_data['current'].append(parsed_data.get('current'))
            chart_data['energy'].append(parsed_data.get('energy'))
            chart_data['frequency'].append(parsed_data.get('frequency'))
            chart_data['power_factor'].append(parsed_data.get('power_factor'))
        elif device.device_type == 'water_level':
            chart_data['water_level'].append(parsed_data.get('water_level'))
        
    chart_labels_json = json.dumps(chart_labels)
    chart_data_json = json.dumps(chart_data)

    

    context = {
        'device': device,
        'sensor_data_entries': sensor_data_entries,
        'chart_labels': chart_labels_json,
        'chart_data': chart_data_json,
    }
    return render(request, 'dashboard/device_detail.html', context)
