import json
import sys
import traceback
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Max, Q, OuterRef, Subquery
# ... other existing imports
from .models import SensorData, DeviceCommandQueue
from core.models import Device # Assuming Device model is in core.models
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder # Import for serializing datetime objects

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

# Endpoint for devices to send sensor data
class DeviceDataReceive(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        device_api_key = request.data.get('device_api_key')
        device_type = request.data.get('device_type')
        sensor_data_payload = request.data.get('sensor_data')

        if not all([device_api_key, device_type, sensor_data_payload is not None]):
            return Response({'error': 'Missing data (device_api_key, device_type, or sensor_data).'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                device, created = Device.objects.get_or_create(
                    device_api_key=device_api_key,
                    defaults={
                        'device_type': device_type,
                        'name': f"{device_type.replace('_', ' ').title()} Device ({device_api_key[:4]})",
                        'is_online': True, # Mark as online on data receive
                        'last_seen': timezone.now() # Update last_seen on data receive
                    }
                )

                if not created:
                    # If device already existed, update its properties
                    if not device.device_type or device.device_type == 'UNSET_TYPE':
                        device.device_type = device_type
                        device.name = f"{device_type.replace('_', ' ').title()} Device ({device_api_key[:4]})"
                        # Ensure is_online and last_seen are updated for existing devices
                        device.is_online = True
                        device.last_seen = timezone.now()
                        device.save() # CRITICAL: Save the device object after updating fields
                    
                    

                if not isinstance(sensor_data_payload, dict):
                    try:
                        sensor_data_payload = json.loads(sensor_data_payload)
                    except json.JSONDecodeError:
                        return Response({'error': 'sensor_data must be a valid JSON object or dict.'}, status=status.HTTP_400_BAD_REQUEST)

                SensorData.objects.create(
                    device=device,
                    data=sensor_data_payload
                )
                return Response({'message': 'Data received successfully'}, status=status.HTTP_200_OK)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceDataReceive: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Endpoint for devices to poll for commands
class DeviceCommandPoll(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        device_api_key = request.query_params.get('device_api_key')

        if not device_api_key:
            return Response({'error': 'Missing device_api_key query parameter.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                device, created = Device.objects.get_or_create(
                    device_api_key=device_api_key,
                    defaults={
                        'device_type': 'UNSET_TYPE',
                        'name': f"Unknown Device ({device_api_key[:4]})",
                        'is_online': True, # Mark as online on command poll
                        'last_seen': timezone.now() # Update last_seen on command poll
                    }
                )
               
                if not created:
                    # Always update is_online and last_seen when device polls
                    device.is_online = True
                    device.last_seen = timezone.now()
                    device.save(update_fields=['is_online', 'last_seen']) # Only save changed fields

                command_to_execute = DeviceCommandQueue.objects.filter(device=device, is_pending=True).order_by('created_at').first()

                if command_to_execute:
                    command_to_execute.is_pending = False
                    command_to_execute.save() # Mark command as no longer pending
                    
                    parameters = command_to_execute.parameters
                    if isinstance(parameters, str): # Handle case where parameters might be a JSON string
                        try:
                            parameters = json.loads(parameters)
                        except json.JSONDecodeError:
                            logger.error(f"Error decoding JSON parameters for command {command_to_execute.id}: {command_to_execute.parameters}", exc_info=True)
                            parameters = {}
                    elif parameters is None:
                        parameters = {}

                    return Response({
                        'command': command_to_execute.command_type,
                        'parameters': parameters
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({'command': 'no_command'}, status=status.HTTP_200_OK)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceCommandPoll: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Public endpoint for device onboarding check
class DeviceOnboardingCheck(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        device_api_key = request.query_params.get('device_api_key')
        if not device_api_key:
            return Response({'status': 'error', 'message': 'device_api_key is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            device = get_object_or_404(Device, device_api_key=device_api_key)
            if device.is_registered:
                return Response({'status': 'error', 'message': 'This device is already registered to a user. Please login to manage it.'}, status=status.HTTP_409_CONFLICT)

            if not device.is_online or (timezone.now() - device.last_seen).total_seconds() > 30: # 30 seconds threshold
                return Response({'status': 'error', 'message': 'Device not recently online. Please ensure it is powered on and successfully connected to your Wi-Fi network first.'}, status=status.HTTP_412_PRECONDITION_FAILED)

            return Response({'status': 'success', 'message': 'Device is available for registration!', 'device_name': device.name, 'device_type': device.device_type}, status=status.HTTP_200_OK)
        except Device.DoesNotExist:
            print(f"Device Does Not Exist in OnboardingCheck for API Key: {device_api_key}", file=sys.stderr)
            return Response({'status': 'error', 'message': 'Invalid Device API Key. Please check the key on your physical device.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceOnboardingCheck: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DeviceLatestDataRetrieve(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, device_id, format=None):
        try:
            device = get_object_or_404(Device, pk=device_id)
            latest_sensor_data = SensorData.objects.filter(device=device).order_by('-timestamp').first()

            device_data = {
                'id': device.id,
                'name': device.name,
                'device_api_key': device.device_api_key,
                'device_type': device.device_type,
                'is_online': device.is_online,
                'last_seen': device.last_seen,
                'is_registered': device.is_registered
            }

            latest_data_payload = None
            if latest_sensor_data and latest_sensor_data.data:
                try:
                    latest_data_payload = json.loads(latest_sensor_data.data)
                except json.JSONDecodeError:
                    print(f"Error decoding JSON data for SensorData ID {latest_sensor_data.id}: {latest_sensor_data.data}", file=sys.stderr)
                    latest_data_payload = {}

            response_data = {
                'device': device_data,
                'latest_data': latest_data_payload
            }
            return Response(response_data, status=status.HTTP_200_OK)
        except Device.DoesNotExist:
            return Response({'error': 'Device not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceLatestData: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    authentication_classes = []
    permission_classes = []

    def get(self, request, device_id, format=None):
        try:
            # Get the device object based on the ID from the URL
            device = get_object_or_404(Device, id=device_id)

            # Fetch the latest sensor data for this device
            latest_sensor_data_entry = SensorData.objects.filter(device=device).order_by('-timestamp').first()

            # Determine online status based on last_seen (consistent with dashboard logic)
            is_online = False
            if device.last_seen:
                time_difference = timezone.now() - device.last_seen
                if time_difference.total_seconds() < 300:  # 5 minutes threshold
                    is_online = True
            
            # Prepare the response data
            response_data = {
                'device': {
                    'id': device.id,
                    'name': device.name,
                    'device_type': device.device_type,
                    'is_online': is_online, # Use the calculated online status
                    'last_seen': device.last_seen.isoformat() if device.last_seen else None,
                    'device_api_key': device.device_api_key, # Include API key for completeness
                },
                'latest_data': {} # Default empty payload
            }

            if latest_sensor_data_entry:
                # Assuming data is already a JSONField, so it's a Python dict/list
                # If it's a string, you might need json.loads(latest_sensor_data_entry.data)
                response_data['latest_data'] = latest_sensor_data_entry.data

            return Response(response_data, status=status.HTTP_200_OK)

        except Device.DoesNotExist:
            return Response({'error': 'Device not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceLatestDataRetrieve: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
