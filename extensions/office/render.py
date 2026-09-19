"""Headless LibreOffice conversion using a disposable isolated profile."""
from pathlib import Path
import subprocess
import tempfile


def convert(source, output_dir, *, executable, format='pdf', enabled=True):
    if not enabled:return {'disabled':True}
    source=Path(source).resolve(strict=True);executable=Path(executable).resolve(strict=True)
    if source.suffix.lower() not in ('.docx','.xlsx','.pptx','.odt','.ods','.odp'):raise ValueError('unsupported input')
    formats={'pdf':'pdf','xlsx':'xlsx:Calc MS Excel 2007 XML'}
    if format not in formats:raise ValueError('unsupported output format')
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    target=output/(source.stem+'.'+format)
    if target.exists():raise FileExistsError(target)
    with tempfile.TemporaryDirectory(prefix='sumika-office-profile-') as d:
        command=[str(executable),'-env:UserInstallation='+Path(d).as_uri(),'--headless','--nologo','--nodefault','--nofirststartwizard','--convert-to',formats[format],'--outdir',str(output),str(source)]
        r=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if r.returncode or not target.is_file() or not target.stat().st_size:raise RuntimeError('LibreOffice conversion failed: '+r.stderr[-1000:])
    return {'path':str(target),'provider':'libreoffice','format':format}
