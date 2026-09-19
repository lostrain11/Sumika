"""Bounded, explicit one-shot capture; no background sensing or model requests."""
from pathlib import Path


def capture_camera(output,*,device=0,approved=False,enabled=True,warmup=5):
    """One-shot capture. warmup frames are discarded: many cameras return a black
    first frame right after opening, which must not be mistaken for a dark scene."""
    if not enabled:return {'disabled':True}
    if approved is not True:raise PermissionError('camera capture needs native authorization')
    if type(warmup) is not int or not 0<=warmup<=60:raise ValueError('invalid warmup frame count')
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    import cv2
    camera=cv2.VideoCapture(device)
    try:
        if not camera.isOpened():raise RuntimeError('camera unavailable')
        ok,frame=False,None
        for _ in range(max(1,warmup+1)):
            ok,frame=camera.read()
            if not ok:raise RuntimeError('camera frame unavailable')
        output.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(output),frame):raise RuntimeError('camera output failed')
        return {'path':str(output),'device':device,'frames':max(1,warmup+1),'discarded':warmup}
    finally:camera.release()


def capture_audio(output,*,seconds=5,device=None,approved=False,enabled=True,sample_rate=16000):
    """Record mono PCM and always write the requested rate: if the device refuses
    it, capture at the device default and resample, reporting both rates."""
    if not enabled:return {'disabled':True}
    if approved is not True:raise PermissionError('microphone capture needs native authorization')
    if not isinstance(seconds,(int,float)) or not 0<seconds<=30:raise ValueError('capture must be 0..30 seconds')
    if type(sample_rate) is not int or not 8000<=sample_rate<=192000:raise ValueError('invalid sample rate')
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    import numpy as np
    import sounddevice as sd
    import wave
    captured_rate=sample_rate
    try:
        sd.check_input_settings(device=device,channels=1,samplerate=sample_rate,dtype='int16')
    except Exception:
        info=sd.query_devices(device if device is not None else sd.default.device[0],'input')
        captured_rate=int(round(info.get('default_samplerate') or 48000))
        sd.check_input_settings(device=device,channels=1,samplerate=captured_rate,dtype='int16')
    try:
        audio=sd.rec(int(seconds*captured_rate),samplerate=captured_rate,channels=1,dtype='int16',device=device)
        sd.wait()
    finally:sd.stop()
    samples=audio.reshape(-1)
    if captured_rate!=sample_rate:
        target=int(round(len(samples)*sample_rate/captured_rate))
        positions=np.linspace(0,len(samples)-1,target)
        samples=np.interp(positions,np.arange(len(samples)),samples.astype('float32'))
        samples=np.clip(np.round(samples),-32768,32767).astype('int16')
    output.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(output),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(sample_rate);f.writeframes(samples.tobytes())
    return {'path':str(output),'seconds':seconds,'sample_rate':sample_rate,
            'captured_rate':captured_rate,'resampled':captured_rate!=sample_rate,'frames':len(samples)}
