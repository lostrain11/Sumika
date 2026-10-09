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


def transcribe(audio, *, model, provider='vosk', enabled=True):
    if not enabled:return {'disabled':True}
    if provider not in ('vosk', 'sherpa-onnx-sensevoice'):
        raise ValueError('unsupported ASR provider; no fallback')
    if provider == 'sherpa-onnx-sensevoice':
        return _transcribe_sensevoice(audio, model)
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


def _transcribe_sensevoice(audio, model):
    """Decode bounded file segments using the companion's existing provider."""
    import asyncio
    from extensions.companion.audio_providers import SenseVoicePcmProvider
    with wave.open(str(audio), 'rb') as source:
        if (source.getnchannels() != 1 or source.getsampwidth() != 2
                or source.getcomptype() != 'NONE' or source.getframerate() != 16000):
            raise ValueError('SenseVoice requires 16kHz 16-bit mono PCM WAV')
        recognizer = SenseVoicePcmProvider(model)
        recognizer.load_model()  # Initialize native dependencies on the owner.

        async def decode():
            parts = []
            while chunk := source.readframes(recognizer.max_bytes // 2):
                text = await recognizer(chunk, sample_rate=16000)
                if text:
                    parts.append(text)
            return ' '.join(parts)

        text = asyncio.run(decode())
    return {'text': text, 'provider': 'sherpa-onnx-sensevoice', 'model': Path(model).name}
