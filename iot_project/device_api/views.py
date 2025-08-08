from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import SensorData, DeviceCommandQueue
from core.models import Device
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction

# Endpoint for devices to send sensor data
class DeviceDataReceive(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        device_api_key = request.data.get('device_api_key')
        device_type = request.data.get('device_type') # New: device type
        sensor_data_payload = request.data.get('sensor_data') # New: generic sensor_data JSON

        if not all([device_api_key, device_type, sensor_data_payload is not None]):
            return Response({'error': 'Missing data (device_api_key, device_type, or sensor_data).'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                device = get_object_or_404(Device, device_api_key=device_api_key)

                # Update device info if it's the first time or type is unset
                if not device.device_type or device.device_type == 'UNSET_TYPE':
                    device.device_type = device_type
                    device.name = f"{device_type.replace('_', ' ').title()} Device ({device_api_key[:4]})" # Auto-name
                device.is_online = True
                device.last_seen = timezone.now()
                device.save()

                SensorData.objects.create(
                    device=device,
                    data=sensor_data_payload # Store the entire JSON payload
                )
                return Response({'message': 'Data received successfully'}, status=status.HTTP_200_OK)
        except Device.DoesNotExist:
            return Response({'error': 'Invalid device_api_key.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Endpoint for devices to poll for commands (remains largely same, handles generic commands)
class DeviceCommandPoll(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        device_api_key = request.query_params.get('device_api_key')

        if not device_api_key:
            return Response({'error': 'Missing device_api_key query parameter.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                device = get_object_or_404(Device, device_api_key=device_api_key)
                device.is_online = True
                device.last_seen = timezone.now()
                device.save()

                command_to_execute = DeviceCommandQueue.objects.filter(device=device, is_pending=True).order_by('created_at').first()

                if command_to_execute:
                    command_to_execute.is_pending = False
                    command_to_execute.save()

                    return Response({
                        'command': command_to_execute.command_type,
                        'parameters': command_to_execute.parameters or {}
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({'command': 'no_command'}, status=status.HTTP_200_OK)
        except Device.DoesNotExist:
            return Response({'error': 'Invalid device_api_key.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
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
            return Response({'status': 'error', 'message': 'Invalid Device API Key. Please check the key on your physical device.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)