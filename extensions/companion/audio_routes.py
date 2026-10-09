"""Windows audio route discovery with explicit loopback limitations."""
import os


def validate_application_route(*, process_id, device_id=None):
    """Return a process-bound route request; recording is provider-owned."""
    if type(process_id) is not int or process_id <= 0:
        raise ValueError('positive process id required')
    if device_id is not None and (type(device_id) is not int or device_id < 0):
        raise ValueError('invalid audio device id')
    return {'kind': 'wasapi-process-loopback', 'process_id': process_id,
            'device_id': device_id, 'supported': os.name == 'nt',
            'reason': None if os.name == 'nt' else 'Windows WASAPI required'}


def validate_microphone_route(device_id=None):
    if device_id is not None and (type(device_id) is not int or device_id < 0):
        raise ValueError('invalid microphone device id')
    return {'kind': 'microphone', 'device_id': device_id, 'separate_track': True}
