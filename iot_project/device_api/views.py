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
                # Attempt to get the device, or create it if it doesn't exist
                device, created = Device.objects.get_or_create(
                    device_api_key=device_api_key,
                    defaults={
                        'device_type': device_type,
                        'name': f"{device_type.replace('_', ' ').title()} Device ({device_api_key[:4]})",
                        'is_online': True,
                        'last_seen': timezone.now()
                    }
                )

                if not created:
                    # If device already existed, update its properties
                    if not device.device_type or device.device_type == 'UNSET_TYPE':
                        device.device_type = device_type
                        device.name = f"{device_type.replace('_', ' ').title()} Device ({device_api_key[:4]})"
                    device.is_online = True
                    device.last_seen = timezone.now()
                    device.save()

                SensorData.objects.create(
                    device=device,
                    data=json.dumps(sensor_data_payload)
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
                # Attempt to get the device, or create it if it doesn't exist
                # This ensures that even if a command poll happens before initial data send,
                # the device record is created. It will default to 'UNSET_TYPE'.
                device, created = Device.objects.get_or_create(
                    device_api_key=device_api_key,
                    defaults={
                        'device_type': 'UNSET_TYPE', # Default type if not provided during onboarding
                        'name': f"Unknown Device ({device_api_key[:4]})",
                        'is_online': True,
                        'last_seen': timezone.now()
                    }
                )
                
                if not created:
                    device.is_online = True
                    device.last_seen = timezone.now()
                    device.save()

                command_to_execute = DeviceCommandQueue.objects.filter(device=device, is_pending=True).order_by('created_at').first()

                if command_to_execute:
                    command_to_execute.is_pending = False
                    command_to_execute.save()
                    
                    parameters = command_to_execute.parameters
                    if isinstance(parameters, str):
                        try:
                            parameters = json.loads(parameters)
                        except json.JSONDecodeError:
                            print(f"Error decoding JSON parameters for command {command_to_execute.id}: {command_to_execute.parameters}", file=sys.stderr)
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

# Public endpoint for device onboarding check (remains same)
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

            if not device.is_online or (timezone.now() - device.last_seen).total_seconds() > 3:
                return Response({'status': 'error', 'message': 'Device not recently online. Please ensure it is powered on and successfully connected to your Wi-Fi network first.'}, status=status.HTTP_412_PRECONDITION_FAILED)

            return Response({'status': 'success', 'message': 'Device is available for registration!', 'device_name': device.name, 'device_type': device.device_type}, status=status.HTTP_200_OK)
        except Device.DoesNotExist:
            print(f"Device Does Not Exist in OnboardingCheck for API Key: {device_api_key}", file=sys.stderr)
            return Response({'status': 'error', 'message': 'Invalid Device API Key. Please check the key on your physical device.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"An unexpected error occurred in DeviceOnboardingCheck: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return Response({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # New API endpoint to fetch latest data for a specific device
class DeviceLatestData(APIView):
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
                'last_seen': device.last_seen, # Django datetime objects are JSON serializable by default in REST framework
                'is_registered': device.is_registered
            }

            latest_data_payload = None
            if latest_sensor_data and latest_sensor_data.data:
                try:
                    latest_data_payload = json.loads(latest_sensor_data.data)
                except json.JSONDecodeError:
                    print(f"Error decoding JSON data for SensorData ID {latest_sensor_data.id}: {latest_sensor_data.data}", file=sys.stderr)
                    latest_data_payload = {} # Fallback to empty dict if JSON is invalid

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
