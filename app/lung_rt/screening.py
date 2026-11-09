import hashlib
import threading
import time
from .longitudinal import suggest


class Screening:
    def __init__(self, store, core, config, reports, acquire, release):
        self.store,self.core,self.config,self.reports=store,core,config,reports
        self.acquire,self.release=acquire,release
        self.stop=threading.Event()
        self.lock=threading.RLock()
        self.state={"active":False,"completed":0,"positive":0,"failed":0,"stage":"idle","generate_reports":0}
        self.thread=None

    def start(self, folder, *, generate_reports=0, language="pt-BR", interval=20):
        with self.lock:
            if self.state["active"]: raise ValueError("screening_already_active")
            folder=self.core.pasta_valida(folder,self.config)
            if generate_reports not in (0,1): raise ValueError("invalid_report_flag")
            self.stop.clear()
            self.state={"active":True,"completed":0,"positive":0,"failed":0,"stage":"watching","generate_reports":generate_reports}
            self.thread=threading.Thread(target=self._run,args=(folder,generate_reports,language,interval),daemon=True,name="lung-screening")
            self.thread.start()
        return dict(self.state)

    def _run(self, folder, generate_reports, language, interval):
        seen,attempted={},set()
        try:
            while not self.stop.is_set():
                stable={}
                for series in self.core.varrer(folder,self.config):
                    if self.stop.is_set(): break
                    try:
                        _,_,signature=self.core._inspecionar(series)
                        stable[series["uid"]]=signature
                        key=(series["uid"],signature)
                        if seen.get(series["uid"])!=signature or key in attempted: continue
                        while not self.acquire():
                            if self.stop.wait(.5): return
                        try:
                            self.state["stage"]="segmenting"
                            receipt=self.core.processar_serie(series,{**self.config,"cancel_event":self.stop},esperado=signature)
                        finally:
                            self.release()
                        attempted.add(key)
                        case_id=hashlib.sha256((series["uid"]+signature).encode()).hexdigest()
                        case={"id":case_id,"series":dict(series),"signature":signature,"receipt":receipt,
                              "patient_key":receipt["paciente_chave"],"frame_uid":receipt["frame_uid"],
                              "lesions":receipt["lesoes"],"segmentation_state":receipt["estado"],
                              "report_state":"disabled" if not generate_reports else "requested",
                              "created_at":time.time(),"review":"pending"}
                        previous=self.store.list("cases")
                        case["longitudinal_suggestions"]=[{**match,"previous_case":p["id"]}
                            for p in previous if p["id"]!=case_id for match in suggest(p,case)]
                        self.store.put("cases",case_id,case)
                        self.store.put("reviews","case:"+case_id,{"kind":"case","id":case_id,"state":"pending","created_at":time.time()})
                        self.state["completed"]+=1
                        self.state["positive"]+=int(receipt["estado"]=="positivo")
                        if generate_reports and not self.stop.is_set():
                            try:
                                draft=self.reports.create(series,language,case_id=case_id)
                                case["report_id"],case["report_state"]=draft["id"],draft["state"]
                            except Exception:
                                case["report_state"]="failed"
                            self.store.put("cases",case_id,case)
                    except Exception:
                        self.state["failed"]+=1
                        self.state["last_error"]="segmentation_failed"
                        if series.get("uid") in stable:
                            attempted.add((series["uid"],stable[series["uid"]]))
                            case_id=hashlib.sha256((series["uid"]+stable[series["uid"]]).encode()).hexdigest()
                            if not self.store.get("cases",case_id):
                                self.store.put("cases",case_id,{"id":case_id,"series":dict(series),"signature":stable[series["uid"]],"lesions":[],"segmentation_state":"adiado" if self.stop.is_set() else "falha","report_state":"disabled","created_at":time.time(),"review":"pending","error":"segmentation_failed"})
                seen=stable
                self.state["stage"]="watching"
                self.stop.wait(max(1,interval))
        except Exception:
            self.state["last_error"]="scan_failed"
        finally:
            self.state["active"]=False
            self.state["stage"]="stopped"

    def cancel(self):
        self.stop.set()
        self.state["stage"]="cancelling" if self.state["active"] else "stopped"
        return dict(self.state)
