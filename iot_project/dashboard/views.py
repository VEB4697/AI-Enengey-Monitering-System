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
from device_api.views import  DeviceAnalysisAPIView

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

    sensor_data_entries_raw = SensorData.objects.filter(device=device).order_by('-timestamp')[:50]
    sensor_data_entries = list(reversed(sensor_data_entries_raw))

    context = {
        'device': device,
        'sensor_data_entries': sensor_data_entries,
    }
    return render(request, 'dashboard/analysis_page.html', context)

@login_required
def device_detail(request, device_id):
    """
    Renders the device details page, fetching and parsing sensor data for charts and table.
    Ensures data is correctly prepared as numbers for charting.
    """
    device = get_object_or_404(Device, id=device_id, owner=request.user)

    # FIX 1: Fetch the latest 50 sensor data entries, then reverse them for chronological order.
    # Chart.js time axis generally expects data in ascending time order.
    sensor_data_entries_raw = SensorData.objects.filter(device=device).order_by('-timestamp')[:50]
    sensor_data_entries = list(reversed(sensor_data_entries_raw))
    
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
        # FIX 2: Access the 'data' JSONField content directly for each entry in the loop.
        # Assuming entry.data is a JSONField and already deserialized into a Python dictionary.
        entry_sensor_data = entry.data 
        
        # Use strftime for chart labels to match the Chart.js 'yyyy-MM-dd HH:mm:ss' parser
        chart_labels.append(entry.timestamp.strftime('%Y-%m-%d %H:%M:%S'))

        # IMPORTANT: Explicitly convert to float, and handle None if key is missing.
        # Ensure that non-relevant fields for a device type are appended as None.
        if device.device_type == 'power_monitor':
            chart_data['power'].append(float(entry_sensor_data.get('power')) if entry_sensor_data.get('power') is not None else None)
            chart_data['voltage'].append(float(entry_sensor_data.get('voltage')) if entry_sensor_data.get('voltage') is not None else None)
            chart_data['current'].append(float(entry_sensor_data.get('current')) if entry_sensor_data.get('current') is not None else None)
            chart_data['energy'].append(float(entry_sensor_data.get('energy')) if entry_sensor_data.get('energy') is not None else None)
            chart_data['frequency'].append(float(entry_sensor_data.get('frequency')) if entry_sensor_data.get('frequency') is not None else None)
            chart_data['power_factor'].append(float(entry_sensor_data.get('power_factor')) if entry_sensor_data.get('power_factor') is not None else None)
            chart_data['water_level'].append(None) # Add None for non-existent fields for consistency
        elif device.device_type == 'water_level':
            chart_data['water_level'].append(float(entry_sensor_data.get('water_level')) if entry_sensor_data.get('water_level') is not None else None)
            # Add None for power_monitor fields if this is a water_level device for consistency
            chart_data['power'].append(None)
            chart_data['voltage'].append(None)
            chart_data['current'].append(None)
            chart_data['energy'].append(None)
            chart_data['frequency'].append(None)
            chart_data['power_factor'].append(None)
    
    # Debug prints (keep these for your own testing, remove in production)
    # print(f"Chart labels: {chart_labels}")
    # print(f"Chart data: {chart_data}")

    chart_labels_json = json.dumps(chart_labels)
    chart_data_json = json.dumps(chart_data)

    # Debug prints for JSON (keep these for your own testing, remove in production)
    # print(f"Chart labels JSON: {chart_labels_json}")
    # print(f"Chart data JSON: {chart_data_json}")
    
    # Calculate is_online based on last_seen timestamp
    current_time = timezone.now()
    is_online = False
    if device.last_seen: 
        time_difference = current_time - device.last_seen
        if time_difference.total_seconds() < 300: # 5 minutes threshold
            is_online = True

    context = { 
        'device': device, 
        'sensor_data_entries': sensor_data_entries, # This list is still used for your table display
        'chart_labels': chart_labels_json, 
        'chart_data': chart_data_json, 
        'is_online': is_online, 
    } 
    return render(request, 'dashboard/device_detail.html', context)