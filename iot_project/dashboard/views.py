import json
import sys
import traceback
from django.contrib.auth.decorators import login_required
from django.db.models import Max, OuterRef, Subquery
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
    user_devices = Device.objects.filter(owner=request.user, is_registered=True).order_by('-last_seen')

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


class DeviceAnalysisAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, device_id, format=None):
        try:
            device = get_object_or_404(Device, pk=device_id)
            
            duration_param = request.query_params.get('duration', '24h')
            end_time = timezone.now()
            
            if duration_param == '7d':
                start_time = end_time - timezone.timedelta(days=7)
            elif duration_param == '30d':
                start_time = end_time - timezone.timedelta(days=30)
            else:
                start_time = end_time - timezone.timedelta(hours=24)

            sensor_data_qs = SensorData.objects.filter(
                device=device,
                timestamp__gte=start_time,
                timestamp__lte=end_time
            ).order_by('timestamp').values('timestamp', 'data')

            if not sensor_data_qs.exists():
                return Response({
                    'device_id': device.id,
                    'device_name': device.name,
                    'device_type': device.device_type,
                    'message': 'No data available for analysis in the specified period.',
                    'data_points': [],
                    'anomalies': [],
                    'predictions': [],
                    'suggestions': ["No data to analyze. Please ensure your device is sending data."]
                }, status=status.HTTP_200_OK)

            data_list = []
            for entry in sensor_data_qs:
                row = {'timestamp': entry['timestamp']}
                row.update(entry['data'])
                data_list.append(row)
            
            df = pd.DataFrame(data_list)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')

            anomalies = []
            predictions = []
            suggestions = []

            if device.device_type == 'power_monitor':
                if 'power' in df.columns and len(df) > 10 and df['power'].nunique() > 1:
                    try:
                        iso_forest = IsolationForest(random_state=42, contamination=0.05) 
                        df['anomaly'] = iso_forest.fit_predict(df[['power']])
                        
                        anomalous_points = df[df['anomaly'] == -1]
                        for idx, row in anomalous_points.iterrows():
                            anomalies.append({
                                'timestamp': idx.isoformat(),
                                'metric': 'power',
                                'value': row['power'],
                                'description': f"Unusual power consumption detected: {row['power']:.2f} W"
                            })
                            suggestions.append(f"Consider checking devices connected at {idx.strftime('%Y-%m-%d %H:%M')}. Anomaly detected: Power spike to {row['power']:.2f} W.")
                    except Exception as e:
                        logger.error(f"Error running Isolation Forest for device {device_id}: {e}", exc_info=True)
                        suggestions.append("Could not run anomaly detection. Check data quality or sufficient data points.")
                else:
                    suggestions.append("Not enough diverse data to perform anomaly detection (needs > 10 varied power readings).")

                if 'power' in df.columns and len(df) > 20 and df['power'].nunique() > 1:
                    try:
                        prophet_df = df[['power']].reset_index().rename(columns={'timestamp': 'ds', 'power': 'y'})
                        
                        m = Prophet(daily_seasonality=True, changepoint_prior_scale=0.05) 
                        m.fit(prophet_df)

                        future = m.make_future_dataframe(periods=24, freq='H') 
                        forecast = m.predict(future)

                        for idx, row in forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(24).iterrows():
                            predictions.append({
                                'timestamp': row['ds'].isoformat(),
                                'predicted_power': row['yhat'],
                                'lower_bound': row['yhat_lower'],
                                'upper_bound': row['yhat_upper']
                            })
                        
                        positive_predicted_power = forecast['yhat'].tail(24)
                        positive_predicted_power = positive_predicted_power[positive_predicted_power > 0]
                        
                        if not positive_predicted_power.empty:
                            avg_predicted_power = positive_predicted_power.mean()
                            if avg_predicted_power > 500:
                                suggestions.append(f"Expected average power consumption over next 24 hours: {avg_predicted_power:.2f} W. Consider optimizing usage.")
                            else:
                                suggestions.append("Power consumption forecast looks normal for the next 24 hours.")
                        else:
                            suggestions.append("Forecast generated, but predicted power values are zero or negative. Check data for patterns.")

                    except Exception as e:
                        logger.error(f"Error running Prophet forecast for device {device_id}: {e}", exc_info=True)
                        suggestions.append("Could not generate power consumption forecast. Check data quality or sufficient data points (needs > 20 varied readings).")
                else:
                    suggestions.append("Not enough diverse data to generate power consumption forecast (needs > 20 varied readings).")

            elif device.device_type == 'water_level':
                if 'water_level' in df.columns and len(df) > 10 and df['water_level'].nunique() > 1:
                    try:
                        iso_forest = IsolationForest(random_state=42, contamination=0.05) 
                        df['anomaly'] = iso_forest.fit_predict(df[['water_level']])
                        anomalous_points = df[df['anomaly'] == -1]
                        for idx, row in anomalous_points.iterrows():
                            anomalies.append({
                                'timestamp': idx.isoformat(),
                                'metric': 'water_level',
                                'value': row['water_level'],
                                'description': f"Unusual water level detected: {row['water_level']:.2f}%"
                            })
                            if row['water_level'] < 10:
                                suggestions.append(f"Water level is critically low ({row['water_level']:.2f}%). Consider refilling the tank.")
                            elif row['water_level'] > 90:
                                suggestions.append(f"Water level is very high ({row['water_level']:.2f}%). Ensure no overflow issues.")
                    except Exception as e:
                        logger.error(f"Error running Isolation Forest for water_level on device {device_id}: {e}", exc_info=True)
                        suggestions.append("Could not run water level anomaly detection. Check data quality or sufficient data points.")
                else:
                    suggestions.append("Not enough diverse data to perform water level anomaly detection (needs > 10 varied readings).")

                if 'water_level' in df.columns and len(df) > 20 and df['water_level'].nunique() > 1:
                    try:
                        prophet_df = df[['water_level']].reset_index().rename(columns={'timestamp': 'ds', 'water_level': 'y'})
                        m = Prophet(daily_seasonality=True, changepoint_prior_scale=0.05)
                        m.fit(prophet_df)
                        future = m.make_future_dataframe(periods=24, freq='H')
                        forecast = m.predict(future)
                        for idx, row in forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(24).iterrows():
                            predictions.append({
                                'timestamp': row['ds'].isoformat(),
                                'predicted_water_level': row['yhat'],
                                'lower_bound': row['yhat_lower'],
                                'upper_bound': row['yhat_upper']
                            })
                        
                        predicted_water_levels = forecast['yhat'].tail(24)
                        predicted_water_levels = predicted_water_levels[(predicted_water_levels >= 0) & (predicted_water_levels <= 100)]

                        if not predicted_water_levels.empty:
                            avg_predicted_level = predicted_water_levels.mean()
                            if avg_predicted_level < 20:
                                suggestions.append(f"Predicted average water level over next 24 hours: {avg_predicted_level:.2f}%. Plan for refilling soon.")
                            else:
                                suggestions.append("Water level forecast looks stable for the next 24 hours.")
                        else:
                            suggestions.append("Forecast generated, but predicted water levels are outside expected range (0-100%). Check data for patterns.")
                    except Exception as e:
                        logger.error(f"Error running Prophet forecast for water_level on device {device_id}: {e}", exc_info=True)
                        suggestions.append("Could not generate water level forecast. Check data quality or sufficient data points (needs > 20 varied readings).")
                else:
                    suggestions.append("Not enough diverse data to generate water level forecast (needs > 20 varied readings).")
            
            else:
                suggestions.append("Analysis not yet configured for this device type.")
                suggestions.append("Ensure the device is sending 'power' or 'water_level' data for analysis.")

            historical_data_for_response = []
            for entry in data_list:
                historical_data_for_response.append({
                    'timestamp': entry['timestamp'].isoformat(),
                    'data': {k: v for k, v in entry.items() if k != 'timestamp'}
                })

            return Response({
                'device_id': device.id,
                'device_name': device.name,
                'device_type': device.device_type,
                'data_points': historical_data_for_response,
                'anomalies': anomalies,
                'predictions': predictions,
                'suggestions': suggestions
            }, status=status.HTTP_200_OK)

        except Device.DoesNotExist:
            logger.warning(f"Device Not Found for PK: {device_id} in DeviceAnalysisAPIView.")
            return Response({'error': 'Device not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"An unexpected error occurred in DeviceAnalysisAPIView for PK: {device_id}: {e}", exc_info=True)
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
