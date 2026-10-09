"""Endpoint-level WASAPI loopback provider.

``soundcard`` exposes the default speaker loopback, not per-process capture.
This provider therefore refuses a process-specific request instead of claiming
that unrelated application audio is isolated.
"""
from pathlib import Path
import wave


def capability():
    try:
        import soundcard  # noqa: F401
    except (ImportError, OSError) as error:
        return {'supported': False, 'provider': 'wasapi-endpoint-loopback', 'reason': str(error)}
    return {'supported': True, 'provider': 'wasapi-endpoint-loopback',
            'reason': None, 'process_isolation': False}


def capture_loopback(output, *, seconds=2, process_id=None, approved=False,
                     sample_rate=16000, channels=1):
    if approved is not True:
        raise PermissionError('explicit application audio consent required')
    if type(seconds) not in (int, float) or not 0.1 <= seconds <= 30:
        raise ValueError('seconds must be between 0.1 and 30')
    if process_id is not None:
        if type(process_id) is not int or process_id <= 0:
            raise ValueError('process id must be positive')
        raise RuntimeError('process-specific WASAPI loopback provider is unavailable')
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 48000:
        raise ValueError('invalid sample rate')
    if type(channels) is not int or not 1 <= channels <= 2:
        raise ValueError('invalid channel count')
    destination = Path(output).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    import numpy as np
    import soundcard
    speaker = soundcard.default_speaker()
    if speaker is None:
        raise RuntimeError('default WASAPI speaker unavailable')
    frames = max(1, int(seconds * sample_rate))
    microphone = soundcard.get_microphone(speaker.id, include_loopback=True)
    if not microphone.isloopback:
        raise RuntimeError('WASAPI loopback device unavailable')
    with microphone.recorder(samplerate=sample_rate, channels=channels) as recorder:
        data = recorder.record(numframes=frames)
    data = np.asarray(data)
    if data.ndim == 1:
        data = data[:, None]
    pcm = np.clip(data * 32767, -32768, 32767).astype('<i2').tobytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), 'wb') as stream:
        stream.setnchannels(data.shape[1]); stream.setsampwidth(2); stream.setframerate(sample_rate)
        stream.writeframes(pcm)
    return {'path': str(destination), 'provider': 'wasapi-endpoint-loopback',
            'process_isolation': False, 'seconds': len(data) / sample_rate,
            'sample_rate': sample_rate, 'channels': data.shape[1]}
