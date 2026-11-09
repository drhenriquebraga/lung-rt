import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _source_paths import install_source_paths
HOST,CONTOUR=install_source_paths(ROOT)
from lung_rt.store import Store,canonical
from lung_rt.provider import LocalProvider
from lung_rt.reports import Reports
from lung_rt.nlp import extract_own_draft
from lung_rt.longitudinal import suggest
from lung_rt.export import export_draft,pdf_from_pages


class StoreTests(unittest.TestCase):
    def test_sync_idempotent_conflict_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);a=Store(p/"a");b=Store(p/"b");share=p/"share"
            a.put("cases","case",{"state":"pending"});a.sync(share);b.sync(share)
            self.assertEqual(b.get("cases","case")["state"],"pending")
            self.assertEqual(b.sync(share)["applied"],0)
            a.put("cases","case",{"state":"reviewed"});b.put("cases","case",{"state":"recheck"})
            a.sync(share);out=b.sync(share)
            self.assertEqual(out["conflict"],1)
            self.assertEqual(b.get("cases","case")["state"],"recheck")
            (share/"bad.lung-event.json").write_text('{"id":"tampered"}')
            self.assertGreaterEqual(a.sync(share)["rejected"],1)
            self.assertTrue(a.conflicts())
            backup=a.backup(p/"backup")
            self.assertEqual(backup["sha256"],hashlib.sha256((p/"backup"/backup["file"]).read_bytes()).hexdigest())

    def test_local_database_and_optimistic_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp);first=s.put("reviews","r",{"state":"pending"})
            s.put("reviews","r",{"state":"reviewed"},expected_revision=first["_revision"])
            with self.assertRaises(ValueError):s.put("reviews","r",{},expected_revision=first["_revision"])
        with self.assertRaises(ValueError):Store(r"\\server\share\lung-test")


class ProviderTests(unittest.TestCase):
    def test_hardware_guard_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/"catalog").mkdir();models=p/"models";models.mkdir();data=b"synthetic model bytes";(models/"x").write_bytes(data)
            manifest={"minimum_gpu_gb":6,"revision":"synthetic","files":[{"path":"x","size":len(data),"sha256":hashlib.sha256(data).hexdigest()}]}
            (p/"catalog/models.json").write_text(json.dumps(manifest))
            provider=LocalProvider(p,models,lambda:{"total_bytes":5*1000**3})
            self.assertEqual(provider.preflight()["errors"],["gpu_below_6gb"])
            provider.hardware=lambda:{"total_bytes":8*1000**3}
            self.assertTrue(provider.preflight()["available"])
            stamp=(models/"x").stat()
            (models/"x").write_bytes(b"x"*len(data))
            import os
            os.utime(models/"x",ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertFalse(provider.preflight()["available"])
            with self.assertRaises(ValueError):provider.path("../escape")


class FakeProvider:
    manifest={"revision":"synthetic-test-only"}
    def preflight(self,verify=True):return {"available":True}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.held=False
        def acquire():
            if self.held:return False
            self.held=True;return True
        def release():self.held=False
        self.manager=Reports(self.store,FakeProvider(),acquire,release,lambda s:([],(),"signature"),lambda r,p:[{"name":"synthetic-only.dcm"}])
    def tearDown(self):self.manager.close();self.manager.monitor.join(3);self.tmp.cleanup()
    def create(self):return self.manager.create({"uid":"synthetic-series"},"pt-BR")
    def test_complete_requires_eos_and_export(self):
        report=self.create();lease=self.manager.start(report["id"]);self.assertTrue(self.held)
        with self.assertRaises(ValueError):self.manager.accept(report["id"],"wrong",original="test",translated="teste",eos=True,tokens=3)
        draft=self.manager.accept(report["id"],lease["lease"],original="Findings:\nSynthetic test only",translated="Achados:\nTeste sintético",eos=True,tokens=5)
        self.assertEqual(draft["state"],"exporting");self.assertTrue(self.held)
        completed=self.manager.finalize(report["id"],lease["lease"],[],draft["text_sha256"])
        self.assertEqual(completed["state"],"completed");self.assertFalse(self.held)
        self.assertEqual(len(self.store.list("reviews")),1)
    def test_truncation_cancellation_and_deadline(self):
        report=self.create();lease=self.manager.start(report["id"])
        result=self.manager.accept(report["id"],lease["lease"],original="incomplete",translated="incompleto",eos=False,tokens=4096)
        self.assertEqual(result["state"],"truncated");self.assertFalse(self.held)
        report=self.create();lease=self.manager.start(report["id"])
        self.manager.finish_failure(report["id"],"cancelled","cancelled")
        with self.assertRaises(ValueError):self.manager.authorize(report["id"],lease["lease"])
        report=self.create();self.manager._update(report["id"],deadline=time.time()-1)
        self.assertEqual(self.manager.start(report["id"])["state"],"timed_out")
    def test_foreign_station_queue_cannot_execute(self):
        report=self.create();self.manager._update(report["id"],station="other-station")
        with self.assertRaisesRegex(ValueError,"other_station"):
            self.manager.start(report["id"])
        self.assertFalse(self.held)

    def test_restart_marks_interrupted_without_rearming(self):
        report=self.create();self.manager.close()
        second=Reports(self.store,FakeProvider(),lambda:True,lambda:None,lambda s:([],(),"signature"),lambda r,p:[])
        self.assertEqual(self.store.get("reports",report["id"])["state"],"failed")
        second.close();second.monitor.join(3)
    def test_nlp_only_own_draft(self):
        with self.assertRaises(ValueError):extract_own_draft("human report",source="human",report_id="r")
        extraction=extract_own_draft("Findings:\nSynthetic",source="nv-reason-ct-local",report_id="r")
        self.assertFalse(extraction["measurements_verified"])
        self.assertEqual(extraction["sections"][0]["heading"],"Findings")


class ExportTests(unittest.TestCase):
    def test_unicode_pdf_sr_new_objects_and_status(self):
        import numpy as np
        import cv2
        import pydicom
        from pydicom.dataset import Dataset
        from pydicom.uid import generate_uid
        image=np.full((1123,794,3),255,dtype=np.uint8);ok,jpg=cv2.imencode('.jpg',image);self.assertTrue(ok)
        pages=[{"width":794,"height":1123,"jpeg":base64.b64encode(jpg.tobytes()).decode()}]
        self.assertTrue(pdf_from_pages(pages).startswith(b"%PDF-1.4"))
        source=Dataset();source.PatientID="SYNTHETIC";source.PatientName="TEST^SYNTHETIC";source.StudyInstanceUID=generate_uid();source.SeriesInstanceUID=generate_uid();source.FrameOfReferenceUID=generate_uid();source.SOPClassUID="1.2.840.10008.5.1.4.1.1.2";source.SOPInstanceUID=generate_uid()
        report={"id":"synthetic","state":"exporting","source":"nv-reason-ct-local","display_text":"Teste sintético / اختبار / 测试 / পরীক্ষা"}
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/"human-original.txt";original.write_text("do not touch")
            outputs=export_draft(source,tmp,report,pages)
            self.assertEqual(len(outputs),2);self.assertEqual(original.read_text(),"do not touch")
            docs=[pydicom.dcmread(Path(tmp)/o["name"]) for o in outputs]
            self.assertNotEqual(docs[0].SOPInstanceUID,source.SOPInstanceUID)
            self.assertEqual(docs[0].EncapsulatedDocument[:4],b"%PDF")
            self.assertEqual(docs[1].PreliminaryFlag,"PRELIMINARY")
            self.assertEqual(docs[1].VerificationFlag,"UNVERIFIED")
            self.assertIn("اختبار",docs[1].ContentSequence[0].TextValue)
            self.assertEqual(str(docs[1].StudyInstanceUID),str(source.StudyInstanceUID))
    def test_no_failed_draft_export(self):
        with self.assertRaises(ValueError):export_draft(None,".",{"state":"failed"},[])


class LongitudinalTests(unittest.TestCase):
    def test_no_cross_patient_or_cross_frame_matching(self):
        a={"patient_key":"p","frame_uid":"f","lesions":[{"id":"1","centro_lps_mm":[1,2,3]}]}
        b={"patient_key":"p","frame_uid":"f","lesions":[{"id":"2","centro_lps_mm":[2,2,3]}]}
        self.assertEqual(suggest(a,b)[0]["distance_mm"],1)
        b["frame_uid"]="different";self.assertEqual(suggest(a,b),[])
        b["frame_uid"]="f";b["patient_key"]="other";self.assertEqual(suggest(a,b),[])


class ScreeningTests(unittest.TestCase):
    def test_default_nodules_only_and_explicit_report_failure_independent(self):
        from lung_rt.screening import Screening
        class Core:
            def pasta_valida(self,p,cfg):return p
            def varrer(self,p,cfg):return [{"uid":"synthetic","pasta":p,"cortes":5}]
            def _inspecionar(self,s):return [],(),"signature"
            def processar_serie(self,s,cfg,esperado=None):
                return {"paciente_chave":"synthetic-patient","frame_uid":"synthetic-frame","lesoes":[],"estado":"vazio"}
        class Drafts:
            calls=0
            def create(self,*args,**kwargs):self.calls+=1;return {"id":"synthetic-report","state":"failed"}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);reports=Drafts();screen=Screening(store,Core(),{},reports,lambda:True,lambda:None)
            screen.start(tmp,interval=1)
            until=time.time()+5
            while screen.state["completed"]<1 and time.time()<until:time.sleep(.02)
            screen.cancel();screen.thread.join(3)
            self.assertEqual(screen.state["completed"],1);self.assertEqual(reports.calls,0)
            screen.start(tmp,generate_reports=1,interval=1)
            until=time.time()+5
            while reports.calls<1 and time.time()<until:time.sleep(.02)
            screen.cancel();screen.thread.join(3)
            case=store.list("cases")[0]
            self.assertEqual(case["segmentation_state"],"vazio");self.assertEqual(case["report_state"],"failed")
            restarted=Screening(store,Core(),{},reports,lambda:True,lambda:None)
            self.assertFalse(restarted.state["active"])


class APITests(unittest.TestCase):
    def test_loopback_csrf_picker_and_guard(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from lung_rt.plugin import mount
        class Core:
            def pasta_valida(self,value,cfg=None):return value
            def _inspecionar(self,series):return [],(),"synthetic-signature"
        with tempfile.TemporaryDirectory() as tmp:
            app=FastAPI();policy=json.loads((ROOT/"catalog/consent.json").read_text(encoding="utf-8"))
            consent=Path(tmp)/"consent.json";consent.write_text(json.dumps({"accepted":True,"version":policy["version"],"digest":policy["digest"]}))
            def resolve(selection):
                if selection!={"scan_id":"synthetic-job","bilhete":"synthetic-ticket","uid":"synthetic"}:
                    raise ValueError("invalid_series_selection")
                return {"uid":"synthetic","pasta":tmp,"scan_root":tmp,"cortes":5}
            rt=mount(app,{"plugin_root":str(ROOT),"data_dir":tmp,"core":Core(),"hardware":lambda:{"total_bytes":5*1000**3},"test_client":True,"consent_path":str(consent),"resolve_series":resolve,"acquire_gpu":lambda n:True,"release_gpu":lambda n:None})
            with TestClient(app,base_url="http://127.0.0.1") as client:
                self.assertEqual(client.get('/api/lung-plugin/state',headers={"host":"evil.example"}).status_code,403)
                self.assertEqual(client.get('/api/lung-plugin/state',headers={"sec-fetch-site":"cross-site"}).status_code,403)
                self.assertEqual(client.post('/api/lung-plugin/action',json={"action":"select"}).status_code,403)
                headers={"origin":"http://127.0.0.1"}
                self.assertEqual(client.post('/api/lung-plugin/action',json={"action":"select","selection":{"uid":"synthetic"}},headers=headers).status_code,400)
                choice=client.post('/api/lung-plugin/action',json={"action":"select","selection":{"scan_id":"synthetic-job","bilhete":"synthetic-ticket","uid":"synthetic"}},headers=headers).json()
                report=client.post('/api/lung-plugin/action',json={"action":"create_report","session":choice["session"],"confirmed":True},headers=headers).json()
                self.assertEqual(report["state"],"failed");self.assertEqual(report["error"],"gpu_below_6gb")
                self.assertNotIn("series",report)
                state=client.get('/api/lung-plugin/state');self.assertEqual(state.headers["cache-control"],"no-store")
                self.assertFalse(state.json()["screening"]["active"])
                self.assertEqual(state.json()["defaults"]["generate_reports"],0)
            rt.reports.monitor.join(3)


class QueueIntegrationTests(unittest.TestCase):
    def test_actual_host_gpu_queue_distinct_owners(self):
        import radai_queue_state as queue
        self.assertTrue(queue.tentar_a_vez("lung-report"))
        try:
            self.assertFalse(queue.tentar_a_vez("lung-screening"))
            self.assertFalse(queue.tentar_a_vez("lung"))
        finally:queue.soltar_a_vez("lung-report")
        self.assertTrue(queue.tentar_a_vez("lung-screening"))
        queue.soltar_a_vez("lung-screening")


class ContractTests(unittest.TestCase):
    def test_packaging_and_no_remote_inference(self):
        manifest=json.loads((ROOT/"module.json").read_text())
        self.assertEqual(manifest["defaults"]["gerar_pre_laudos"],0)
        recipe=json.loads((ROOT/"catalog/resource_recipe.json").read_text())
        for item in recipe["files"]:
            self.assertTrue(item["path"].startswith(("models/","runtimes/")))
            self.assertEqual(len(item["sha256"]),64)
            self.assertGreater(item["size"],0)
        worker=(ROOT/"web/report-worker.js").read_text()
        self.assertNotIn("https://",worker)
        self.assertIn("device:'webgpu'",worker)
        self.assertIn("EOS.has(R.pending)",worker)
        self.assertNotIn("post('text'",worker)
        self.assertIn("signal.deadline*1000",worker)
        self.assertIn("browser_disconnected",worker)
        self.assertIn("self.close()",worker)

if __name__=="__main__":unittest.main(verbosity=2)
