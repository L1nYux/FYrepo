"""Bundle the upstream hash-verified BPE files; no inference-time downloading."""
import hashlib
import json
import importlib.metadata
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
FILES={
    'cl100k_base':'223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7',
    'o200k_base':'446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d',
}

def prepare():
    directory=ROOT/'vendor/tokenizers'
    directory.mkdir(parents=True,exist_ok=True)
    result=[]
    for name,expected in FILES.items():
        url='https://openaipublic.blob.core.windows.net/encodings/'+name+'.tiktoken'
        path=directory/hashlib.sha1(url.encode()).hexdigest()
        data=path.read_bytes() if path.exists() else urlopen(url,timeout=30).read(6*1024*1024)
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Tokenizer hash mismatch: '+name)
        path.write_bytes(data)
        result.append({'encoding':name,'file':path.name,'url':url,'sha256':expected})
    (directory/'SOURCE.json').write_text(json.dumps({'upstream':'https://github.com/openai/tiktoken',
        'license':'MIT','files':result},indent=2)+'\n',encoding='utf-8')
    distribution=importlib.metadata.distribution('tiktoken')
    license_file=next(item for item in distribution.files if str(item).endswith('/licenses/LICENSE'))
    (directory/'LICENSE').write_bytes(distribution.locate_file(license_file).read_bytes())
    print(json.dumps({'files':len(result),'verified':True}))

if __name__=='__main__':prepare()
