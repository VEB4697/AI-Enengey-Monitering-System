import json
import sys
import traceback
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import SensorData, DeviceCommandQueue
from core.models import Device # Assuming Device model is in core.models
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder # Import for serializing datetime objects

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
                    # Ensure is_online and last_seen are updated for existing devices
                    device.is_online = True
                    device.last_seen = timezone.now()
                    device.save() # CRITICAL: Save the device object after updating fields

                command_to_execute = DeviceCommandQueue.objects.filter(device=device, is_pending=True).order_by('created_at').first()

                # ... (rest of the DeviceCommandPoll logic) ...
                if command_to_execute:
                    # ... (logic for command_to_execute) ...
                    pass # Keep your existing return for commands
                else:
                    return Response({'command': 'no_command'}, status=status.HTTP_200_OK)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceCommandPoll: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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


# --- NEW APIVIEW ADDED FOR FETCHING LATEST SENSOR DATA ---
class DeviceLatestDataRetrieve(APIView):
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

