"""Verify relocated packaged capability imports without opening audio/capture devices."""
import argparse
import json
from pathlib import Path
import subprocess
from tools.verify_portable_staging import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-process-audio', action='store_true')
    parser.add_argument('--require-office', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('report must be new')
    root = args.candidate.resolve(strict=True)
    report = {'passed': False, 'inventory': verify(root), 'probes': {},
              'scope': 'Packaged imports and capability detection only; no device capture or playback'}
    programs = {
        'python': "from pathlib import Path; from extensions.desktop.runtime import capability_python; "
                  "r=Path(__import__('sys').executable).parents[2]; "
                  "assert Path(capability_python('desktop'))==r/'runtime/desktop/python.exe'; "
                  "assert Path(capability_python('voice'))==r/'runtime/voice/python.exe'; print('paths passed')",
        'desktop': "from extensions.desktop.windows_capture import capability; "
                   "import pythoncom,win32com.client,sounddevice,vosk; "
                   "from winrt.windows.media.ocr import OcrEngine; "
                   "from winrt.windows.globalization import Language; "
                   "from winrt.windows.graphics.imaging import SoftwareBitmap; "
                   "from winrt.windows.storage.streams import DataWriter; "
                   "assert OcrEngine.try_create_from_language(Language('zh-Hans-CN')) is not None, 'Chinese OCR language unavailable'; "
                   "print(capability()); print('Chinese OCR engine available')",
        'voice': "from extensions.companion.pipecat_voice import build_study_voice_worker; "
                 "import numpy,sherpa_onnx; "
                 "from extensions.companion.sapi_playback import DirectSapiPlayback; "
                 "from pipecat.audio.vad.silero import SileroVADAnalyzer; "
                 "SileroVADAnalyzer(sample_rate=16000); print('voice model loaded')",
    }
    if args.require_office:
        programs['python'] += (
            "; from ui.readiness import probes; "
            "office=next(p for p in probes(r,home=r) if p['id']=='office'); "
            "assert office['ready'] and 'DSH原生依赖载荷' in office['detail'], office; print(office)")
        programs['office/dependencies/python'] = (
            "import json,sys,importlib.metadata as m; from pathlib import Path; "
            "import docx,openpyxl,pptx,pypdf,reportlab,pypdfium2,xlsxwriter,numpy,pandas; "
            "distributions=list(m.distributions()); "
            "names=[d.metadata['Name'].lower().replace('_','-') for d in distributions]; "
            "assert len(names)==len(set(names)), 'duplicate distributions'; "
            "manifest=json.loads((Path(sys.executable).parents[2]/'runtime.json').read_text()); "
            "assert all(m.version(name)==version for name,version in manifest['pythonPackages'].items()); "
            "assert pandas.DataFrame({'v':numpy.array([2,3])})['v'].sum()==5; "
            "print(json.dumps({'unique_distributions':len(names),'versions':manifest['pythonPackages']}))")
    try:
        for name, code in programs.items():
            result = subprocess.run([str(root/'runtime'/name/'python.exe'), '-I', '-X', 'utf8', '-B', '-c', code],
                cwd=root, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=60)
            report['probes'][name] = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
            if result.returncode:
                raise RuntimeError('packaged capability probe failed: ' + name)
        if args.require_process_audio:
            code = ("from pathlib import Path; from extensions.desktop.runtime import process_audio_helper; "
                    "from extensions.desktop.process_audio import ProcessAudioCapture; "
                    "r=Path(__import__('sys').executable).parents[2]; "
                    "h=process_audio_helper(); assert Path(h)==r/'runtime/process-audio/SumikaProcessAudio.exe'; "
                    "p=ProcessAudioCapture.capability(h); assert p['supported'] and p['process_isolation']; print(p)")
            result = subprocess.run([str(root/'runtime/python/python.exe'), '-I', '-X', 'utf8', '-B', '-c', code],
                cwd=root, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=30)
            report['probes']['process_audio'] = {'exit_code':result.returncode,
                'stdout':result.stdout, 'stderr':result.stderr}
            if result.returncode:
                raise RuntimeError('packaged process audio probe failed')
        report['passed'] = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf8') as stream:
            json.dump(report, stream, indent=2)
    print(json.dumps({'passed': report['passed'], 'report': str(args.output)}))


if __name__ == '__main__':
    main()
