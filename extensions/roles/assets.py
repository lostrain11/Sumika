"""Inspect VRM containers and resource metadata without running imported code."""
import json
from pathlib import Path
import struct


def inspect_vrm(path):
    path=Path(path)
    with path.open('rb') as f:
        header=f.read(12)
        if len(header)!=12:raise ValueError('truncated GLB')
        magic,version,length=struct.unpack('<4sII',header)
        if magic!=b'glTF' or version!=2 or length!=path.stat().st_size:raise ValueError('invalid GLB container')
        chunk=f.read(8)
        if len(chunk)!=8:raise ValueError('missing GLB JSON chunk')
        size,kind=struct.unpack('<I4s',chunk)
        if kind!=b'JSON' or size>16*1024*1024 or 20+size>length:raise ValueError('invalid GLB JSON chunk')
        data=json.loads(f.read(size))
    extensions=data.get('extensions',{})
    vrm=extensions.get('VRMC_vrm',extensions.get('VRM'))
    if not isinstance(vrm,dict):raise ValueError('VRM extension missing')
    # External URLs in an imported model are never fetched by this inspector.
    external=[item['uri'] for key in ('buffers','images') for item in data.get(key,[]) if 'uri' in item and not item['uri'].startswith('data:')]
    return dict(format='vrm1' if 'VRMC_vrm' in extensions else 'vrm0',metadata=vrm.get('meta',{}),external_resources=external,bytes=length)
