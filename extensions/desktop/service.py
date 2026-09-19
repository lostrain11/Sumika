"""CLI dispatch for configured local providers. Invoke through native tool approval."""
import argparse
import json
from pathlib import Path
from extensions.capabilities import CapabilityStore


def execute(store, request):
    capability=request['capability'];operation=request['operation'];args=request.get('arguments',{})
    selected=store.resolve(capability);provider=selected['provider'];settings=selected['options']
    if capability=='ocr' and operation=='recognize':
        from extensions.desktop.ocr.ocr import recognize
        return recognize(args['image'],provider=provider,language=args.get('language','eng'))
    if capability=='desktop' and provider=='windows-uia':
        from extensions.desktop.control.uia import WindowsController
        c=WindowsController()
        if operation=='inspect':return c.inspect(**args)
        if operation=='act':return c.act(**args)
    if capability=='voice' and provider=='windows-sapi' and operation=='synthesize':
        from extensions.roles.voice import synthesize
        return synthesize(**args,**settings)
    if capability=='asr' and provider=='vosk' and operation=='transcribe':
        from extensions.roles.voice import transcribe
        return transcribe(**args,**settings)
    if capability=='camera' and provider=='opencv' and operation=='capture':
        from extensions.desktop.perception import capture_camera
        return capture_camera(**args)
    if capability=='microphone' and provider=='sounddevice' and operation=='capture':
        if settings.get('user_authorized') is not True:
            raise PermissionError('microphone permission is disabled in capability details')
        from extensions.desktop.perception import capture_audio
        return capture_audio(**args)
    if capability=='office-render' and provider=='libreoffice' and operation=='convert':
        from extensions.office.render import convert
        return convert(**args,**settings)
    raise ValueError('unsupported capability/provider/operation; no fallback')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();store=None
    try:
        if not a.store.is_file():raise ValueError('capability store must be configured first')
        store=CapabilityStore(a.store)
        print(json.dumps(execute(store,json.loads(a.request.read_text(encoding='utf8'))),ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError,ImportError,RuntimeError) as e:
        p.exit(2,'desktop service: '+str(e)+'\n')
    finally:
        if store:store.close()


if __name__=='__main__':raise SystemExit(main())
