"""Local interchangeable file-audio backends; no microphone capture or playback."""
import json
from pathlib import Path
import wave


def synthesize(text, output, *, voice_name='Microsoft Huihui Desktop - Chinese (Simplified)', enabled=True):
    if not enabled:return {'disabled':True}
    if not isinstance(text,str) or not text.strip():raise ValueError('text required')
    import win32com.client
    speaker=win32com.client.Dispatch('SAPI.SpVoice')
    voices=[v for v in speaker.GetVoices() if v.GetDescription()==voice_name]
    if len(voices)!=1:raise ValueError('configured voice unavailable; no fallback')
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    stream=win32com.client.Dispatch('SAPI.SpFileStream')
    stream.Format.Type=22  # SAFT22kHz16BitMono
    stream.Open(str(output),3)
    try:
        speaker.Voice=voices[0];speaker.AudioOutputStream=stream;speaker.Speak(text,16)
    finally:stream.Close()
    return {'path':str(output),'provider':'windows-sapi','voice':voice_name}


def transcribe(audio, *, model, enabled=True):
    if not enabled:return {'disabled':True}
    if not Path(model).is_dir():raise ValueError('local Vosk model missing')
    from vosk import Model,KaldiRecognizer
    with wave.open(str(audio),'rb') as f:
        if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getcomptype()!='NONE':raise ValueError('16-bit mono PCM WAV required')
        recognizer=KaldiRecognizer(Model(str(model)),f.getframerate())
        parts=[]
        while chunk:=f.readframes(4000):
            if recognizer.AcceptWaveform(chunk):parts.append(json.loads(recognizer.Result()).get('text',''))
        parts.append(json.loads(recognizer.FinalResult()).get('text',''))
    return {'text':' '.join(p for p in parts if p),'provider':'vosk','model':Path(model).name}
