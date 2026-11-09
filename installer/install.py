"""LUNG RT installer orchestration, using the existing Suite runtime when present."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import radai_lung_install as SDK


def say(message):
    print(time.strftime('%H:%M:%S')+' '+message,flush=True)


def suite_version(root):
    try:
        return next(line.split('=',1)[1].strip() for line in (root/'entrega.txt').read_text(encoding='utf-8-sig').splitlines() if line.startswith('VERSAO='))
    except (OSError,StopIteration):
        return ''


def port_for(root):
    try:
        for line in (root/'radai_watcher.config').read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('PORT='):
                return int(line.split('=',1)[1].strip())
    except (OSError,ValueError):
        pass
    return 8777


def _api(port,path,body=None,token=''):
    data=None if body is None else json.dumps(body).encode()
    request=Request('http://127.0.0.1:%d%s'%(port,path),data=data,
                    headers={'Content-Type':'application/json','X-Lung-Plugin-Token':token})
    # Loopback must never be sent to a clinical network proxy.
    from urllib.request import build_opener,ProxyHandler
    with build_opener(ProxyHandler({})).open(request,timeout=35) as response:
        return json.loads(response.read(1024**2))


def source_root():
    return HERE.parent if (HERE.parent/'code/module.json').is_file() else HERE


def unpack_suite():
    archive=HERE/'suite-setup.zip'
    expected=(HERE/'suite-setup.sha256').read_text(encoding='ascii').strip()
    if SDK._sha(archive)!=expected:
        raise ValueError('O código da base não confere. Baixe o instalador completo novamente.')
    work=Path(tempfile.mkdtemp(prefix='lung-base-setup-'))
    try:
        with zipfile.ZipFile(archive) as z:
            seen=set()
            if len(z.infolist())>20000 or sum(i.file_size for i in z.infolist())>256*1024**2:
                raise ValueError('Instalador base excede o limite.')
            for item in z.infolist():
                if item.is_dir():continue
                target=SDK._inside(work,item.filename)
                if item.filename.casefold() in seen:
                    raise ValueError('Instalador base contém entradas repetidas.')
                seen.add(item.filename.casefold())
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
        base=work/'programa'
        if not (base/'build/configurar_ambiente.py').is_file():
            raise ValueError('O instalador base está incompleto.')
        return work,base
    except BaseException:
        shutil.rmtree(work)
        raise


def consent(root):
    policy=SDK.CONSENT_POLICY
    SDK._atomic(SDK._inside(root,'Plugins/LUNG RT/config/consent.json'),{
        'schema':'lung-rt/consent-receipt/1','version':policy['version'],'digest':policy['digest'],
        'accepted':True,'accepted_at':time.time()})


def start_suite(root):
    port=port_for(root)
    launcher=root/'radai_lancador.py'
    command=[str(root/'python/python.exe'),'-B',str(launcher),'--url','http://127.0.0.1:%d/lung'%port,'--abrir-janela']
    subprocess.Popen(command,cwd=str(root),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return port


def install_through_host(root,reports):
    port=port_for(root)
    try:
        state=_api(port,'/api/plugins/lung-rt')
    except (OSError,ValueError):
        say('Abrindo a Local Suite para preparar a manutenção controlada...')
        start_suite(root)
        state=None
        for _ in range(120):
            time.sleep(1)
            try:state=_api(port,'/api/plugins/lung-rt');break
            except (OSError,ValueError):pass
        if state is None:
            raise ValueError('Abra a Local Suite e use Configurações > LUNG RT > pacote de uma pasta.')
    if state.get('suite_fingerprint') != SDK.suite_identity(root):
        raise ValueError('A porta está ocupada por outra instalação da Local Suite. Feche a outra instância ou confira a pasta escolhida.')
    token=state['token']
    inspected=_api(port,'/api/plugins/lung-rt/local/inspect',{'folder':str(source_root())},token)
    policy=SDK.CONSENT_POLICY
    say('Preparando encerramento controlado. O PowerShell mostrará cada etapa e reabrirá a suíte.')
    _api(port,'/api/plugins/lung-rt/install',{'source_id':inspected['source_id'],'reports':reports,
         'consent':{'accepted':True,'version':policy['version'],'digest':policy['digest']}},token)
    say('Manutenção iniciada. Acompanhe a janela do instalador externo.')


def standalone(root,reports):
    if suite_version(root):
        if SDK._version(suite_version(root))<(8,14):
            raise ValueError('Atualize a Local Suite existente para 8.14 pelo instalador da base e abra este START HERE novamente. Seus dados são preservados.')
        return install_through_host(root,reports)
    if root.exists():
        allowed={'python','LICENCAS_ACEITAS.txt','Plugins','.lung-bootstrap','_instalacao'}
        own_attempt=(root/'_instalacao/_motor_comecou.txt').is_file()
        if not own_attempt and any(p.name not in allowed for p in root.iterdir()):
            raise ValueError('Escolha uma pasta vazia para a nova base compacta ou a pasta da Local Suite já instalada.')
    root.mkdir(parents=True,exist_ok=True)
    work,base=unpack_suite()
    try:
        say('1/4 Preparando a base compacta LUNG RT com os mesmos motores da Local Suite.')
        marker=root/'_instalacao/_motor_comecou.txt'
        marker.parent.mkdir(parents=True,exist_ok=True)
        marker.write_text('LUNG RT compact prepare initiated by START HERE\n',encoding='utf8')
        (root/'LICENCAS_ACEITAS.txt').write_text('LICENCAS ACEITAS\n[ACEITA] Local Suite Apache-2.0 e dependências pulmonares apresentadas no instalador\n[ACEITA] LUNG RT — termos '+SDK.CONSENT_POLICY['version']+'\n',encoding='utf8')
        command=[sys.executable,'-B',str(base/'build/configurar_ambiente.py'),'--instalar',str(root),'--profile','lung-rt']
        completed=subprocess.run(command,cwd=str(base))
        if completed.returncode:
            raise ValueError('A base compacta não concluiu o preparo. O progresso já baixado permanece para tentar novamente.')
        target=root/'python/python.exe'
        if Path(sys.executable).resolve()!=target.resolve():
            result=subprocess.run([str(target),'-I','-B',str(HERE/'install.py'),'--stage-plugin','--suite-root',str(root),'--accept-terms']+(['--reports'] if reports else []))
            if result.returncode:raise ValueError('O plugin não concluiu o preparo. Reabra o START HERE.')
            return
        finish_new(root,reports)
    finally:
        shutil.rmtree(work)


def finish_new(root,reports):
    say('2/4 Usando o Python existente da Local Suite.')
    consent(root)
    plan=SDK.prepare_external_plan({'reports':reports},source_folder=str(source_root()))
    last=[0.0]
    def progress(value):
        now=time.monotonic()
        if now-last[0]<1 and value.get('stage') not in ('activating','complete'):return
        last[0]=now
        text={'checking':'Conferindo a base','verifying':'Conferindo o código','resources':'Preparando recursos',
              'downloading':'Baixando recursos novos','activating':'Ativando LUNG RT','complete':'LUNG RT conferido'}.get(value.get('stage'),'Preparando')
        if value.get('total_bytes'):text+=' %.1f / %.1f MB'%(value.get('downloaded_bytes',0)/1024**2,value['total_bytes']/1024**2)
        say(text)
    SDK.run_external(plan,progress,suite_root=root,host_python=sys.executable)
    say('3/4 Plugin instalado. O rastreio inicia com laudos desligados.')
    start_suite(root)
    say('4/4 Abrindo LUNG RT. Os demais módulos ficam disponíveis ao instalar a suíte completa.')


def offline(destination,reports):
    destination=Path(destination).absolute()
    package=SDK.Package(source_root())
    try:
        manifest,digest,raw=SDK._inventory(package)
        marker=destination/'.lung-offline-preparation.json'
        if destination.exists() and any(destination.iterdir()):
            try:previous=SDK._json(marker,8192)
            except (OSError,ValueError):previous={}
            if previous.get('schema')!='lung-rt/offline-preparation/1' or previous.get('code_pin')!=digest:
                raise ValueError('Escolha uma pasta vazia ou retome a preparação deste mesmo pacote.')
            say('Retomando a preparação; arquivos íntegros serão reaproveitados.')
        destination.mkdir(parents=True,exist_ok=True)
        SDK._atomic(marker,{'schema':'lung-rt/offline-preparation/1','code_pin':digest,'reports':reports,'complete':False})
        for entry in manifest['files']:
            data=package.read(entry['path'],entry['size'])
            if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('Código incompleto.')
            target=SDK._inside(destination,entry['path']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        (destination/'release-manifest.json').write_bytes(raw)
        if reports:
            recipe=json.loads(package.read('code/catalog/resource_recipe.json'))
            for item in recipe['files']:
                say('Preparando recurso offline: '+item['path'])
                SDK._download(item.get('urls') or [item['url']],SDK._inside(destination/'resources',item['path']),item['size'],item['sha256'],
                    lambda v: say('Download %.1f / %.1f MB'%(v.get('downloaded_bytes',0)/1024**2,v.get('total_bytes',1)/1024**2)))
        (destination/'LEIA-ME.txt').write_text('Pacote LUNG RT para uma Local Suite 8.14 ou superior. Na máquina offline: Configurações > Plugin LUNG RT > Usar instalador ou pacote offline de uma pasta. Selecione esta pasta inteira. Os pesos de segmentação pulmonar devem estar na instalação base. Nenhum Python é substituído.\n',encoding='utf8')
        SDK._atomic(marker,{'schema':'lung-rt/offline-preparation/1','code_pin':digest,'reports':reports,'complete':True})
        say('Pacote conferido. Leve a pasta inteira e use a interface da Local Suite para instalar.')
    finally:package.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite-root',type=Path,required=True)
    parser.add_argument('--offline',type=Path)
    parser.add_argument('--reports',action='store_true')
    parser.add_argument('--accept-terms',action='store_true')
    parser.add_argument('--stage-plugin',action='store_true')
    args=parser.parse_args()
    if not args.accept_terms:raise ValueError('Leia e aceite os termos no START HERE antes de baixar.')
    if args.offline:return offline(args.offline,args.reports)
    if args.stage_plugin:return finish_new(args.suite_root,args.reports)
    standalone(args.suite_root,args.reports)

if __name__=='__main__':
    try:main()
    except Exception as error:
        say('Instalação não concluída: '+str(error));raise SystemExit(1)
