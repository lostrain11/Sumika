"""Opt-in local audible playback acceptance; no microphone or cloud calls."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.capabilities import CapabilityStore
from extensions.desktop.audio_devices import env_python
from extensions.roles.speech_playback import SpeechPlayback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--play', action='store_true', help='Play a short Chinese sentence and cancel a second local playback')
    args = parser.parse_args()
    if not args.play:
        parser.error('--play is required for audible output')
    python = env_python()
    if not python:
        raise RuntimeError('configured local voice runtime unavailable')
    base = ROOT/'.sumika-next'/('playback-live-'+uuid.uuid4().hex)
    base.mkdir(parents=True)
    database = base/'capabilities.sqlite3'
    store = CapabilityStore(database)
    store.configure('voice', 'windows-sapi')
    selected = store.resolve('voice')
    store.close()
    config = dict(python=python, root=str(ROOT), capabilities=str(database),
                  voice_capability=selected,
                  voice_name='Microsoft Huihui Desktop - Chinese (Simplified)')
    service = SpeechPlayback(base/'jobs', lambda role: dict(config))
    report = dict(passed=False, microphone_used=False, cloud_calls=0,
                  audible_confirmation='not_observed', checks={})
    try:
        started = service.start('isolated-test', text='这是 Sumika 的本地语音测试。', approved=True)
        service.thread.join(timeout=65)
        report['checks']['playback_completed'] = service.status(started['id'])['state']=='completed'
        report['checks']['completed_process_reclaimed'] = service.process is None and service.job is None and not service.thread.is_alive()
        wav = base/'jobs'/started['id']/'speech.wav'
        with wave.open(str(wav), 'rb') as audio:
            report['wav'] = dict(channels=audio.getnchannels(), sample_width=audio.getsampwidth(),
                                 frames=audio.getnframes(), sample_rate=audio.getframerate())
        assert report['checks']['playback_completed'], 'local playback did not complete'
        second = service.start('isolated-test', text='这是停止测试，播放应当很快停止。'*15, approved=True)
        child = service.process
        wav = base/'jobs'/second['id']/'speech.wav'
        deadline=time.monotonic()+15
        duration=0
        while time.monotonic()<deadline and child.poll() is None:
            try:
                with wave.open(str(wav),'rb') as audio:
                    duration=audio.getnframes()/audio.getframerate()
                if duration>5: break
            except (OSError, EOFError, wave.Error): pass
            time.sleep(.05)
        assert duration>5 and child.poll() is None, 'long audio was not ready for cancellation'
        time.sleep(.5)
        begin=time.monotonic()
        stopped=service.cancel(second['id'])
        service.thread.join(timeout=6)
        report['cancel_ms']=round((time.monotonic()-begin)*1000)
        report['checks']['cancelled']=stopped['state']=='cancelled'
        report['checks']['cancelled_process_reclaimed']=child.poll() is not None and service.process is None and service.job is None and not service.thread.is_alive()
        report['checks']['no_late_completion']=service.status(second['id'])['state']=='cancelled'
        report['passed']=all(report['checks'].values())
    finally:
        try: service.close()
        finally:
            report['closed']=service.process is None and service.job is None
            (base/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(base)
            print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed'] and report['closed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
