"""Independent installer-driver tests. All destinations/processes/downloads are synthetic."""
import base64
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _source_paths import install_source_paths,resolve_sources
HOST,CONTOUR=install_source_paths(ROOT)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value

DRIVER=load("lung_installer_driver_under_test",ROOT/"installer/install.py")
BUILD=load("lung_build_setup_under_test",ROOT/"build/build_setup.py")
PROFILE=load("lung_profile_under_test",HOST/"build/configurar_ambiente.py")
import radai_lung_install as SDK
import radai_lung_plugin as HOST_PLUGIN
import radai_plugin_setup as HANDOFF


def fake_package(path,resources=False):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    payload=b"synthetic resource; never a model"
    recipe={"schema":"lung-rt/resource-recipe/1","files":[{"path":"models/nv-reason-ct-int4/test.data","size":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),"url":"https://invalid.test/synthetic-only"}] if resources else []}
    data={"code/module.json":json.dumps({"schema":"lung-rt/plugin-manifest/1","id":"lung-rt","version":"1.0.0","host_contract":"local-suite/plugins/1","host_min_version":"8.14"}).encode(),"code/catalog/resource_recipe.json":json.dumps(recipe).encode(),"code/catalog/consent.json":json.dumps(SDK.CONSENT_POLICY).encode()}
    data["code/integration/local_suite.py"]=b"# synthetic test-only adapter; never executed\n"
    entries=[]
    for name,value in data.items():
        file=path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(value)
        entries.append({"path":name,"size":len(value),"sha256":hashlib.sha256(value).hexdigest()})
    raw=json.dumps({"schema":"lung-rt/release-package/1","plugin_id":"lung-rt","version":"1.0.0","files":entries}).encode()
    (path/"release-manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest(),payload


class DriverTests(unittest.TestCase):
    def test_existing_suite_only_hands_off_no_base_or_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"Suite with spaces";root.mkdir();(root/"entrega.txt").write_text("VERSAO=8.16\n")
            (root/"python").mkdir();runtime=root/"python/python.exe";runtime.write_bytes(b"synthetic sentinel")
            with patch.object(DRIVER,"install_through_host") as host,patch.object(DRIVER,"unpack_suite") as unpack,patch.object(DRIVER.subprocess,"run") as run:
                DRIVER.standalone(root,False)
                host.assert_called_once_with(root,False);unpack.assert_not_called();run.assert_not_called()
            self.assertEqual(runtime.read_bytes(),b"synthetic sentinel")
    def test_old_suite_is_not_modified_or_prepared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"entrega.txt").write_text("VERSAO=8.15\n")
            with patch.object(DRIVER,"install_through_host") as host,patch.object(DRIVER,"unpack_suite") as unpack:
                with self.assertRaisesRegex(ValueError,"8.16"):DRIVER.standalone(root,False)
                host.assert_not_called();unpack.assert_not_called()
    def test_new_suite_profile_and_shared_python_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);root=tmp/"Nova Suite Clínica";work=tmp/"unpack";base=work/"programa";base.mkdir(parents=True)
            with patch.object(DRIVER,"unpack_suite",return_value=(work,base)),patch.object(DRIVER.subprocess,"run",return_value=SimpleNamespace(returncode=0)) as run,patch.object(DRIVER,"say"):
                DRIVER.standalone(root,True)
            calls=[c.args[0] for c in run.call_args_list]
            self.assertEqual(len(calls),2)
            self.assertIn('--profile',calls[0]);self.assertEqual(calls[0][calls[0].index('--profile')+1],'lung-rt')
            self.assertEqual(calls[0][calls[0].index('--instalar')+1],str(root))
            self.assertEqual(calls[1][0],str(root/'python/python.exe'))
            self.assertIn('--stage-plugin',calls[1]);self.assertIn('--accept-terms',calls[1]);self.assertIn('--reports',calls[1])
            self.assertFalse(work.exists())
            self.assertTrue((root/'LICENCAS_ACEITAS.txt').is_file())
    def test_failed_new_base_does_not_stage_plugin_or_remove_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);root=tmp/"new";work=tmp/"unpack";base=work/"programa";base.mkdir(parents=True)
            with patch.object(DRIVER,"unpack_suite",return_value=(work,base)),patch.object(DRIVER.subprocess,"run",return_value=SimpleNamespace(returncode=17)) as run,patch.object(DRIVER,"finish_new") as finish,patch.object(DRIVER,"say"):
                with self.assertRaisesRegex(ValueError,"não concluiu"):DRIVER.standalone(root,False)
                self.assertEqual(run.call_count,1);finish.assert_not_called()
            self.assertTrue((root/'_instalacao/_motor_comecou.txt').is_file());self.assertFalse(work.exists())
    def test_wrong_port_identity_never_inspects_or_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(DRIVER,"_api",return_value={"suite_fingerprint":"wrong-installation","token":"wrong-token"}) as api,patch.object(DRIVER,"start_suite") as start:
                with self.assertRaisesRegex(ValueError,"outra instalação"):DRIVER.install_through_host(Path(tmp),False)
                self.assertEqual(api.call_count,1);start.assert_not_called()
    def test_host_handoff_pins_source_token_and_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fingerprint=SDK.suite_identity(root);seen=[]
            def api(port,path,body=None,token=''):
                seen.append((port,path,body,token))
                if path=='/api/plugins/lung-rt':return {"suite_fingerprint":fingerprint,"token":"synthetic-token"}
                if path.endswith('/local/inspect'):return {"source_id":"opaque-source"}
                return {"state":"external_install"}
            with patch.object(DRIVER,"_api",side_effect=api),patch.object(DRIVER,"source_root",return_value=root/'package'),patch.object(DRIVER,"say"):
                DRIVER.install_through_host(root,True)
            self.assertEqual(len(seen),3)
            body=seen[-1][2];self.assertEqual(body['source_id'],'opaque-source');self.assertTrue(body['reports']);self.assertEqual(seen[-1][3],'synthetic-token')
            self.assertEqual(body['consent']['digest'],SDK.CONSENT_POLICY['digest'])
    def test_cli_acceptance_is_required_before_any_side_effect(self):
        with patch.object(sys,'argv',['install.py','--suite-root','SYNTHETIC']),patch.object(DRIVER,'standalone') as install,patch.object(DRIVER,'offline') as offline:
            with self.assertRaisesRegex(ValueError,'aceite'):DRIVER.main()
            install.assert_not_called();offline.assert_not_called()
    def test_finish_progress_and_same_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);messages=[]
            def run(plan,progress,**kwargs):
                self.assertEqual(kwargs['host_python'],sys.executable);self.assertEqual(kwargs['suite_root'],root)
                progress({'stage':'downloading','downloaded_bytes':1048576,'total_bytes':2097152});progress({'stage':'activating'});progress({'stage':'complete'})
            with patch.object(SDK,'prepare_external_plan',return_value={'schema':'synthetic'}) as prepare,patch.object(SDK,'run_external',side_effect=run),patch.object(DRIVER,'start_suite') as start,patch.object(DRIVER,'say',side_effect=messages.append),patch.object(DRIVER.time,'monotonic',return_value=100):
                DRIVER.finish_new(root,False)
            self.assertTrue(any('1.0 / 2.0 MB' in m for m in messages));start.assert_called_once_with(root)
            receipt=json.loads((root/'Plugins/LUNG RT/config/consent.json').read_text());self.assertEqual(receipt['digest'],SDK.CONSENT_POLICY['digest'])
    def test_offline_code_only_is_verified_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source';pin,_=fake_package(source);target=tmp/'offline'
            with patch.object(DRIVER,'source_root',return_value=source),patch.object(SDK,'TRUSTED_CODE_INVENTORIES',frozenset({pin})),patch.object(SDK,'_download') as download,patch.object(DRIVER,'say'):
                DRIVER.offline(target,False);download.assert_not_called()
            self.assertEqual((target/'code/module.json').read_bytes(),(source/'code/module.json').read_bytes())
            self.assertTrue((target/'release-manifest.json').is_file())
    def test_offline_resources_use_manifest_hash_and_progress_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source';pin,payload=fake_package(source,True);target=tmp/'offline';seen=[]
            def download(urls,dest,size,digest,progress):
                seen.append((urls,size,digest));dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload);progress({'downloaded_bytes':size,'total_bytes':size})
            with patch.object(DRIVER,'source_root',return_value=source),patch.object(SDK,'TRUSTED_CODE_INVENTORIES',frozenset({pin})),patch.object(SDK,'_download',side_effect=download),patch.object(DRIVER,'say'):
                DRIVER.offline(target,True)
            self.assertEqual(seen[0][2],hashlib.sha256(payload).hexdigest());self.assertEqual((target/'resources/models/nv-reason-ct-int4/test.data').read_bytes(),payload)


class ProfileTests(unittest.TestCase):
    def test_existing_runtime_is_reused_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'python').mkdir();runtime=root/'python/python.exe';runtime.write_bytes(b"test-only")
            with patch.object(PROFILE,'baixar') as download,patch.object(PROFILE,'log'),patch.object(PROFILE,'titulo'):
                PROFILE.etapa_runtime({'bundle':root,'cache':root/'cache'})
                download.assert_not_called()
            self.assertEqual(runtime.read_bytes(),b'test-only')
    def test_profile_persists_and_full_upgrade_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);PROFILE.gravar_perfil({'bundle':root,'profile':'lung-rt'})
            self.assertEqual(PROFILE.perfil_do_destino(None,root),'lung-rt')
            self.assertEqual(PROFILE.perfil_do_destino('full',root),'full')
            self.assertEqual(PROFILE.modelos_do_perfil({'profile':'lung-rt'}),())
            self.assertIn('lung_nodules',PROFILE.tasks_do_perfil({'profile':'lung-rt'}))
            self.assertNotIn('total_mr',PROFILE.tasks_do_perfil({'profile':'lung-rt'}))
    def test_lung_weights_do_not_request_other_model_registry(self):
        import radai_tasks
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);tasks=PROFILE.tasks_do_perfil({'profile':'lung-rt'})
            downloader=stack.enter_context(patch.object(PROFILE,'baixar_pesos_ts',return_value={}))
            registry=stack.enter_context(patch.object(PROFILE,'baixar_modelos_do_registro'))
            stack.enter_context(patch.object(PROFILE,'garantir_base',side_effect=lambda target,*args,**kwargs:target))
            for name in ('log','titulo','conferir_recorte_no_corpo','_ligar_caminho'):stack.enter_context(patch.object(PROFILE,name))
            stack.enter_context(patch.object(radai_tasks,'datasets_do_pacote',return_value=[123]))
            stack.enter_context(patch.object(radai_tasks,'baixados',return_value={123}))
            PROFILE.etapa_pesos({'profile':'lung-rt','bundle':root,'py':root/'python/python.exe','preparo':str(root)})
            registry.assert_not_called();self.assertEqual(downloader.call_args.args[1],[radai_tasks.nome_na_biblioteca(t) for t in tasks])


class HandoffTests(unittest.TestCase):
    def run_handoff(self,valid):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);events=[];process=SimpleNamespace(pid=4001,poll=lambda:None,terminate=lambda:events.append('terminate'))
            def popen(command,**kwargs):
                plan=Path(command[command.index('-PlanPath')+1]);envelope=json.loads(plan.read_text())
                HANDOFF._write(plan.parent/'ready.json',{'ready':True,'nonce':envelope['nonce'] if valid else 'wrong','supervisor_pid':4001,'worker_pid':4002})
                events.append('ready-written');return process
            shutdown=Mock();scheduled=[]
            setup=HANDOFF.ExternalInstaller(root,8777,shutdown,popen=popen,protect=lambda pid:events.append(('protected',pid)),schedule=lambda callback:scheduled.append(callback),wait_s=.2,plugin_id='lung-rt')
            with patch.object(HANDOFF,'_environment',return_value={}):
                if valid:
                    result=setup.launch({'source':'synthetic'});self.assertTrue(result['scheduled']);self.assertEqual(scheduled,[shutdown]);shutdown.assert_not_called()
                    self.assertEqual(setup.launch({}),result)
                else:
                    with self.assertRaisesRegex(ValueError,'continua aberta'):setup.launch({'source':'synthetic'})
                    self.assertFalse(scheduled);shutdown.assert_not_called();self.assertIn('terminate',events)
                    self.assertTrue(list(root.glob('Plugins/LUNG RT/staging/external/*/cancel.json')))
    def test_ready_nonce_precedes_shutdown(self):self.run_handoff(True)
    def test_invalid_handshake_keeps_suite_open(self):self.run_handoff(False)


class HostManagementTests(unittest.TestCase):
    def test_consent_source_token_and_failed_handoff_release_queue(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import radai_plugins,radai_queue_state,radai_atualizar
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);app=FastAPI();shutdown=Mock();app.state.radai_reabertura={'encerrar':shutdown}
            stack.enter_context(patch.object(radai_plugins,'_host_info',return_value={}))
            stack.enter_context(patch.object(radai_plugins,'discover_plugin',return_value={'state':'missing','active_version':None}))
            stack.enter_context(patch.object(SDK,'check_latest',return_value={'state':'current'}))
            stack.enter_context(patch.object(SDK,'inspect_local_source',return_value={'path':str(root/'source'),'version':'1.0.0','offline':True}))
            prepare=stack.enter_context(patch.object(SDK,'prepare_external_plan',return_value={'schema':'synthetic'}))
            stack.enter_context(patch.object(radai_queue_state,'quem_tem_a_vez',return_value={'dono':None}))
            stack.enter_context(patch.object(radai_queue_state,'fechando_ao_fim',return_value=False))
            closing=stack.enter_context(patch.object(radai_queue_state,'pedir_fechar_ao_fim'))
            stack.enter_context(patch.object(radai_atualizar,'etapa',return_value='idle'))
            launcher=Mock();launcher.launch.side_effect=ValueError('synthetic handshake failed')
            stack.enter_context(patch.object(HANDOFF,'ExternalInstaller',return_value=launcher))
            entry=HOST_PLUGIN.montar(app,{'suite_root':str(root)})
            with TestClient(app,base_url='http://127.0.0.1') as client:
                status=client.get('/api/plugins/lung-rt').json();token=status['token'];headers={'X-Lung-Plugin-Token':token,'Origin':'http://127.0.0.1'}
                self.assertFalse(status['accepted'])
                self.assertEqual(client.post('/api/plugins/lung-rt/local/inspect',json={'folder':str(root/'source')}).status_code,403)
                choice=client.post('/api/plugins/lung-rt/local/inspect',json={'folder':str(root/'source')},headers=headers).json()
                rejected=client.post('/api/plugins/lung-rt/install',json={'source_id':choice['source_id'],'reports':False},headers=headers)
                self.assertEqual(rejected.status_code,400);prepare.assert_not_called()
                policy=SDK.CONSENT_POLICY
                body={'source_id':choice['source_id'],'reports':False,'consent':{'accepted':True,'version':policy['version'],'digest':policy['digest']}}
                response=client.post('/api/plugins/lung-rt/install',json=body,headers=headers)
                self.assertEqual(response.status_code,400);self.assertFalse(entry['preparing']);shutdown.assert_not_called()
                self.assertEqual(closing.call_args_list[-1].args,(False,))
                self.assertEqual(prepare.call_args.kwargs['source_folder'],str(root/'source'))
                self.assertTrue(client.get('/api/plugins/lung-rt').json()['accepted'])
                self.assertEqual(client.get('/api/plugins/lung-rt',headers={'Host':'evil.example'}).status_code,403)


class BuildTests(unittest.TestCase):
    def source(self,path):
        path=Path(path)
        for directory in BUILD.DIRS:(path/directory).mkdir(parents=True,exist_ok=True)
        for name in BUILD.FILES:(path/name).write_text('{}' if name=='module.json' else 'synthetic test only')
        (path/'module.json').write_text(json.dumps({'version':'1.0.0'}))
        (path/'catalog/consent.json').write_text(json.dumps(SDK.CONSENT_POLICY))
        data=b"synthetic wasm marker"
        resource={'path':'runtimes/nvreason/ort-wasm-simd-threaded.asyncify.wasm','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'url':'https://invalid.test/never-requested'}
        (path/'catalog/resource_recipe.json').write_text(json.dumps({'files':[resource]}))
        return data
    def test_freeze_ignores_interpreter_cache_and_declared_external_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source';data=self.source(source)
            cache=source/'app/__pycache__/synthetic.cpython-314.pyc';cache.parent.mkdir();cache.write_bytes(b'synthetic cache')
            wasm=source/'web/vendor/nvreason/vendor/ort/ort-wasm-simd-threaded.asyncify.wasm';wasm.parent.mkdir(parents=True);wasm.write_bytes(data)
            with patch.object(BUILD,'SOURCE',source):BUILD.freeze(tmp/'frozen')
            inventory=json.loads((tmp/'frozen/release-manifest.json').read_text())
            self.assertFalse(any(e['path'].endswith(('.wasm','.pyc')) for e in inventory['files']))
    def test_freeze_refuses_unexpected_clinical_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source';self.source(source);(source/'app/forbidden.dcm').write_bytes(b'synthetic forbidden-extension marker')
            with patch.object(BUILD,'SOURCE',source),self.assertRaises(ValueError):BUILD.freeze(tmp/'frozen')


    def test_package_integrity_alias_and_code_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source';self.source(source)
            with patch.object(BUILD,'SOURCE',source):pin=BUILD.freeze(tmp/'frozen')
            sdk=tmp/'sdk.py';sdk.write_text("TRUSTED_CODE_INVENTORIES = frozenset(["+repr(pin)+"])\n")
            base=tmp/'suite.zip'
            with zipfile.ZipFile(base,'w') as archive:
                archive.writestr('programa/entrega.txt','PROJETO=LOCAL_SUITE\nVERSAO=8.14\n')
                archive.writestr('programa/app/radai_lung_install.py',sdk.read_text())
            result=BUILD.package(tmp/'frozen',base,sdk,tmp/'output')
            versioned=tmp/'output/LUNG_RT_SETUP_v1.0.0.zip';latest=tmp/'output/LUNG_RT_SETUP_LATEST.zip'
            self.assertEqual(versioned.read_bytes(),latest.read_bytes())
            self.assertFalse(result['runtime_or_weights_included'])
            with zipfile.ZipFile(versioned) as archive:
                self.assertIn('TERMS.txt',archive.namelist())
                self.assertIn('Extrair Tudo',archive.read('LEIA-ME.txt').decode())
                self.assertEqual(archive.read('suite-setup.sha256').decode().strip(),hashlib.sha256(base.read_bytes()).hexdigest())
            file=tmp/'frozen/code/LICENSE';file.write_text('modified after freeze')
            with self.assertRaisesRegex(ValueError,'freeze mudou'):BUILD.package(tmp/'frozen',base,sdk,tmp/'second')
    def test_suite_unpack_refuses_traversal_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);archive=tmp/'suite-setup.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside-test.py','never execute')
            (tmp/'suite-setup.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
            with patch.object(DRIVER,'HERE',tmp),self.assertRaises(ValueError):DRIVER.unpack_suite()
            self.assertFalse((tmp.parent/'outside-test.py').exists())

class PowerShellLayoutTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows launcher test')
    def test_launcher_preserves_partial_zip_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/'partial LUNG_RT_SETUP.zip.856'
            source.mkdir()
            launcher=source/'START_HERE.cmd'
            launcher.write_bytes((ROOT/'installer/START_HERE.cmd').read_bytes())
            result=subprocess.run(['cmd.exe','/d','/c','call',str(launcher)],
                                  env={**os.environ,'LOCALAPPDATA':str(root)},
                                  input='\n',capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertIn('Extrair Tudo',result.stdout)
            log=root/'RadioterapiaAI/LUNG RT/Logs/LUNG_RT_START_HERE.log'
            self.assertIn('PACKAGE_INCOMPLETE',log.read_text())

    @unittest.skipUnless(os.name=='nt','Windows installer test')
    def test_installer_logs_missing_companions_before_gui(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            script=root/'INSTALL.ps1'
            script.write_bytes((ROOT/'installer/INSTALL.ps1').read_bytes())
            log=root/'logs'
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],
                                  env={**os.environ,'LUNG_RT_INSTALL_LOG_DIR':str(log)},
                                  capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertIn('PACKAGE_INCOMPLETE',result.stdout)
            self.assertIn('TERMS.txt',result.stdout)
            transcript,=log.glob('LUNG_RT_INSTALL-*.log')
            self.assertIn('PACKAGE_INCOMPLETE',transcript.read_text(encoding='utf-8-sig'))

    def test_parser_and_hidden_form_default_controls(self):
        if os.name!='nt':self.skipTest('Windows form parser test')
        script_path=str(ROOT/'installer/INSTALL.ps1').replace("'","''")
        script=r"""
$ErrorActionPreference='Stop'
$tokens=$null;$parseErrors=$null
[void][System.Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw ($parseErrors | Out-String)}
$source=[IO.File]::ReadAllText('__SCRIPT__')
$start=$source.IndexOf('# Setup window')
$boundary=$source.IndexOf('[void]$form.ShowDialog()')
if($start -lt 0 -or $boundary -lt $start){throw 'Missing reviewed GUI boundary'}
$prefix=$source.Substring($start,$boundary-$start)
$prefix=[regex]::Replace($prefix,'(?m)^\$terms\s*=.*$',{param($match) '$terms = ''SYNTHETIC TEST ONLY. No installation or acceptance occurs.'' '})
$base=$env:LUNG_RT_LAYOUT_FIXTURE
Invoke-Expression $prefix
$form.CreateControl();$form.PerformLayout()
$outside=@($form.Controls | Where-Object {$_.Right -gt $form.ClientSize.Width -or $_.Bottom -gt $form.ClientSize.Height -or $_.Left -lt 0 -or $_.Top -lt 0})
$result=@{parse_errors=$parseErrors.Count;reports_default=$report.Checked;accept_default=$accept.Checked;install_enabled=$install.Enabled;offline_enabled=$offline.Enabled;outside_count=$outside.Count;controls=$form.Controls.Count;localized=($locale -eq 'ja' -and $setupUi -and $install.Text -eq $setupUi.install -and $install.Text -ne 'Instalar / atualizar');client_width=$form.ClientSize.Width;client_height=$form.ClientSize.Height}
$form.Dispose()
$result|ConvertTo-Json -Compress
""".replace('__SCRIPT__',script_path)
        encoded=base64.b64encode(script.encode('utf-16le')).decode()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'installer-i18n.json').write_bytes((ROOT/'installer/i18n.json').read_bytes())
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                                  env={**os.environ,'LUNG_RT_LAYOUT_FIXTURE':tmp,'LUNG_RT_LANGUAGE':'ja-JP'},
                                  capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout.strip().splitlines()[-1]);self.assertEqual(values['parse_errors'],0);self.assertFalse(values['reports_default']);self.assertFalse(values['accept_default']);self.assertFalse(values['install_enabled']);self.assertFalse(values['offline_enabled']);self.assertEqual(values['outside_count'],0,values)
        self.assertTrue(values['localized'],values)


class SourceCheckoutTests(unittest.TestCase):
    def make_source(self, root, marker):
        source=Path(root);file=source/marker;file.parent.mkdir(parents=True,exist_ok=True);file.write_text("# synthetic source marker\n")
        return source.resolve()
    def test_public_sibling_checkout_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);plugin=base/'lung-rt';plugin.mkdir()
            host=self.make_source(base/'local-suite','app/radai_panel.py')
            contour=self.make_source(base/'contourlab','app/radai_lung.py')
            self.assertEqual(resolve_sources(plugin,{}),(host,contour))
    def test_engineering_parent_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);host=self.make_source(base/'AUTO_CONTORNO','app/radai_panel.py')
            plugin=host/'RASTREIO_NODULO_PULMONAR';plugin.mkdir()
            contour=self.make_source(base/'CONTOURLAB','app/radai_lung.py')
            self.assertEqual(resolve_sources(plugin,{}),(host,contour))
    def test_explicit_source_roots_override_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);plugin=base/'lung-rt';plugin.mkdir()
            host=self.make_source(base/'separate suite','app/radai_panel.py')
            contour=self.make_source(base/'separate contour','app/radai_lung.py')
            self.assertEqual(resolve_sources(plugin,{'LOCAL_SUITE_SOURCE':str(host),'CONTOURLAB_SOURCE':str(contour)}),(host,contour))
    def test_invalid_override_fails_instead_of_loading_another_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);plugin=base/'lung-rt';plugin.mkdir()
            self.make_source(base/'local-suite','app/radai_panel.py')
            self.make_source(base/'contourlab','app/radai_lung.py')
            with self.assertRaisesRegex(RuntimeError,'LOCAL_SUITE_SOURCE'):
                resolve_sources(plugin,{'LOCAL_SUITE_SOURCE':str(base/'missing')})

if __name__=='__main__':unittest.main(verbosity=2)
