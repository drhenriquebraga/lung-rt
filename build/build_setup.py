"""Freeze installable LUNG code, then package a lightweight installer. No weights."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
DIRS=('app','catalog','integration','web','docs')
FILES=('module.json','LICENSE','NOTICE','README.md')
FORBIDDEN={'.dcm','.onnx','.safetensors','.pth','.whl','.wasm','.bin','.sqlite','.db','.log','.gguf','.exe','.dll','.zip'}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def freeze(destination,host_sdk=None):
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Use uma pasta de freeze vazia.')
    destination.mkdir(parents=True,exist_ok=True)
    module=json.loads((SOURCE/'module.json').read_text(encoding='utf8'))
    paths=[SOURCE/name for name in FILES]
    for name in DIRS:paths.extend(p for p in (SOURCE/name).rglob('*') if p.is_file())
    entries=[]
    recipe=json.loads((SOURCE/'catalog/resource_recipe.json').read_text(encoding='utf8'))
    external={r['sha256'] for r in recipe.get('files',())}
    for path in sorted(paths):
        relative=path.relative_to(SOURCE)
        if '__pycache__' in relative.parts or path.suffix.lower() in ('.pyc','.pyo'):
            continue
        if path.suffix.lower() in FORBIDDEN:
            if path.suffix.lower() in ('.wasm','.onnx','.safetensors','.bin') and digest(path) in external:
                continue
            raise ValueError('Artefato proibido no código leve: '+relative.as_posix())
        if path.is_symlink() or path.stat().st_size>5*1024**2:
            raise ValueError('Recurso deve ser baixado no preparo: '+relative.as_posix())
        target=destination/'code'/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        entries.append({'path':'code/'+relative.as_posix(),'size':target.stat().st_size,'sha256':digest(target)})
    inventory={'schema':'lung-rt/release-package/1','plugin_id':'lung-rt','version':module['version'],'files':entries}
    manifest=destination/'release-manifest.json'
    manifest.write_text(json.dumps(inventory,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8')
    pin=digest(manifest)
    if host_sdk:
        sdk=Path(host_sdk);text=sdk.read_text(encoding='utf8')
        tree=ast.parse(text)
        existing=set()
        for node in tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TRUSTED_CODE_INVENTORIES' for t in node.targets):
                if not isinstance(node.value,ast.Call) or not isinstance(node.value.func,ast.Name) or node.value.func.id!='frozenset':
                    raise ValueError('Formato de pins do SDK não reconhecido.')
                existing.update(ast.literal_eval(node.value.args[0]) if node.value.args else ())
        if any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in existing):
            raise ValueError('SDK contém um pin inválido.')
        text,count=re.subn(r'^TRUSTED_CODE_INVENTORIES = .*$', 'TRUSTED_CODE_INVENTORIES = frozenset('+repr(sorted(existing|{pin}))+')',text,flags=re.M)
        if count!=1:raise ValueError('SDK host sem declaração única de pins.')
        policy=json.loads((SOURCE/'catalog/consent.json').read_text(encoding='utf8'))
        text,count=re.subn(r'^CONSENT_POLICY = .*$',lambda m:'CONSENT_POLICY = '+repr(policy),text,flags=re.M)
        if count!=1:raise ValueError('SDK host sem termo compartilhado.')
        ast.parse(text);sdk.write_text(text,encoding='utf8')
    return pin


def package(frozen,suite_setup,host_sdk,destination):
    frozen=Path(frozen);suite_setup=Path(suite_setup);host_sdk=Path(host_sdk);destination=Path(destination)
    inventory=json.loads((frozen/'release-manifest.json').read_text(encoding='utf8'))
    version=inventory['version'];pin=digest(frozen/'release-manifest.json')
    sdk=host_sdk.read_text(encoding='utf8')
    if pin not in sdk:raise ValueError('A base ainda não confia neste freeze do plugin.')
    with zipfile.ZipFile(suite_setup) as source:
        if source.testzip():raise ValueError('SETUP Suite corrompido.')
        if any('/python/' in n.lower() or '/ts_weights/' in n.lower() or n.lower().endswith(('.onnx','.pth','.safetensors')) for n in source.namelist()):
            raise ValueError('A base deve conter apenas o SETUP leve.')
        stamp=source.read('programa/entrega.txt').decode('utf-8-sig')
        base_version=re.search(r'^VERSAO=([0-9.]+)[ \t]*\r?$',stamp,re.M)
        module=json.loads((frozen/'code/module.json').read_text(encoding='utf8'))
        minimum=tuple(map(int,module.get('host_min_version','8.14').split('.')))
        if not base_version or tuple(map(int,base_version[1].split('.')))<minimum:
            raise ValueError('A base Suite não atende à versão mínima do plugin.')
        nested_sdk=source.read('programa/app/radai_lung_install.py').decode('utf-8-sig')
        nested_pins=set()
        for node in ast.parse(nested_sdk).body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TRUSTED_CODE_INVENTORIES' for t in node.targets):
                if isinstance(node.value,ast.Call) and node.value.args:nested_pins.update(ast.literal_eval(node.value.args[0]))
        if pin not in nested_pins:
            raise ValueError('O SETUP da base ainda não confia neste LUNG RT. Reempacote a Suite após o freeze.')
    for entry in inventory['files']:
        file=frozen/entry['path']
        if file.stat().st_size!=entry['size'] or digest(file)!=entry['sha256']:
            raise ValueError('O freeze mudou: '+entry['path'])
    policy=json.loads((frozen/'code/catalog/consent.json').read_text(encoding='utf8'))
    terms=policy['title']+'\n\n'+'\n\n'.join(policy['clauses'])
    terms+='\n\nA base compacta conserva as licenças Local Suite Apache-2.0, Python PSF e bibliotecas DICOM/TotalSegmentator. Leia LICENSE, NOTICE e catalog/sources.json distribuídos com este instalador. Nenhuma licença substitui as demais.\n'
    terms+='\nPré-laudos opcionais: NVReason CT INT4 (~3,01 GB, OpenMDW 1.1) e MedGemma 1.5 4B Q4 / RX (~3,37 GB, HAI-DEF), total ~6,38 GB. Leia web/vendor/nvreason/LICENSE-OpenMDW e https://developers.google.com/health-ai-developer-foundations/terms . O pacote para levar não inclui Python, TotalSegmentator ou recibos de aceite do MedGemma. O usuário deve aceitar os termos HAI-DEF na primeira abertura do app de RX, inclusive offline.\n'
    guide=(
        'LUNG RT | Instalação e pacote offline\n\n'
        'Local Suite já instalada: selecione o ZIP do SETUP na tela do LUNG RT.\n'
        'Para executar START HERE, clique com o botão direito no ZIP e selecione Extrair Tudo. '
        'Depois abra START_HERE.cmd na pasta extraída.\n'
        'Para levar o plugin a uma estação sem internet, prepare um pacote offline no START HERE '
        'de uma máquina conectada. Leve a pasta completa e selecione-a na tela do LUNG RT.\n'
        'O botão Pacote para levar gera a pasta e um ZIP equivalente ao lado dela. '
        'Com os pré-laudos selecionados, inclui recursos CT + RX (~6,38 GB), '
        'reutilizando arquivos locais conferidos. O Python e os pesos de segmentação '
        'permanecem na Local Suite instalada.\n'
    )
    destination.mkdir(parents=True,exist_ok=True)
    output=destination/('LUNG_RT_SETUP_v'+version+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        archive.write(frozen/'release-manifest.json','release-manifest.json')
        for entry in inventory['files']:archive.write(frozen/entry['path'],entry['path'])
        for name in ('START_HERE.cmd','INSTALL.ps1','install.py'):archive.write(SOURCE/'installer'/name,name)
        archive.write(SOURCE/'installer/i18n.json','installer-i18n.json')
        archive.write(host_sdk,'radai_lung_install.py')
        archive.write(suite_setup,'suite-setup.zip')
        archive.writestr('suite-setup.sha256',digest(suite_setup)+'\n')
        archive.writestr('TERMS.txt',terms)
        archive.writestr('LEIA-ME.txt',guide)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise ValueError('O SETUP final não passou no CRC.')
    latest=destination/'LUNG_RT_SETUP_LATEST.zip';shutil.copyfile(output,latest)
    result={'version':version,'code_pin':pin,'code_files':len(inventory['files']),'setup_bytes':output.stat().st_size,
            'setup_sha256':digest(output),'suite_setup_sha256':digest(suite_setup),'runtime_or_weights_included':False}
    (destination/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    return result


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='action',required=True)
    first=sub.add_parser('freeze');first.add_argument('destination',type=Path);first.add_argument('--host-sdk',type=Path)
    second=sub.add_parser('setup');second.add_argument('frozen',type=Path);second.add_argument('suite_setup',type=Path);second.add_argument('host_sdk',type=Path);second.add_argument('destination',type=Path)
    args=parser.parse_args()
    if args.action=='freeze':print(freeze(args.destination,args.host_sdk))
    else:print(json.dumps(package(args.frozen,args.suite_setup,args.host_sdk,args.destination),indent=2))

if __name__=='__main__':main()
