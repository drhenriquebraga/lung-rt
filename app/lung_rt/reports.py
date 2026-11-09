import hashlib
import secrets
import threading
import time
import uuid
from .nlp import extract_own_draft

LANGUAGES = {"pt-BR","en","de","es","fr","it","pl","ar","bn","ko","zh-CN","ja"}
TERMINAL = {"completed","failed","cancelled","timed_out","truncated"}


class Reports:
    def __init__(self, store, provider, acquire, release, inspect_series, export, timeout=3600):
        self.store,self.provider = store,provider
        self.acquire,self.release = acquire,release
        self.inspect_series,self.export = inspect_series,export
        self.timeout=min(3600,max(1,timeout))
        self.lock=threading.RLock()
        self.active=None
        self.secrets={}
        self.stop=threading.Event()
        # Jobs cannot survive a browser/process restart. Never silently rearm GPU work.
        for report in self.store.list("reports",10000):
            if report.get("station")==self.store.station and report["state"] not in TERMINAL:
                self._update(report["id"],state="failed",error="interrupted_restart")
        self.monitor=threading.Thread(target=self._watch,daemon=True,name="lung-report-deadline")
        self.monitor.start()

    def _update(self, ident, **changes):
        with self.lock:
            report=self.store.get("reports",ident)
            if report is None: raise ValueError("report_not_found")
            report.update(changes)
            report["updated_at"]=time.time()
            result=self.store.put("reports",ident,report)
            if "state" in changes and report.get("case_id"):
                case=self.store.get("cases",report["case_id"])
                if case:
                    case["report_state"]=changes["state"]
                    case["report_id"]=ident
                    self.store.put("cases",report["case_id"],case)
            return result

    def create(self, series, language, case_id=None):
        if language not in LANGUAGES: raise ValueError("invalid_language")
        now=time.time(); ident=uuid.uuid4().hex
        report={"id":ident,"case_id":case_id,"station":self.store.station,"series":dict(series),"language":language,
                "source":"nv-reason-ct-local","model_revision":self.provider.manifest["revision"],
                "state":"preflight","created_at":now,"updated_at":now,"deadline":now+self.timeout,
                "progress":None,"stage":"preflight","error":None,"review":"pending",
                "approval_status":"UNVERIFIED","preliminary":"PRELIMINARY"}
        self.store.put("reports",ident,report)
        self.secrets[ident]=secrets.token_urlsafe(32)
        try:
            _,_,signature=self.inspect_series(series)
            check=self.provider.preflight(verify=True)
            if not check["available"]:
                return self._update(ident,state="failed",error=check["errors"][0],capability=check)
            if time.time()>=report["deadline"]:
                return self.finish_failure(ident,"timed_out","timeout")
            return self._update(ident,state="waiting_browser",signature=signature)
        except Exception as exc:
            self._update(ident,state="failed",error="preflight_failed")
            raise ValueError("preflight_failed") from exc

    def start(self, ident):
        with self.lock:
            report=self.store.get("reports",ident)
            if not report or report["state"]!="waiting_browser": raise ValueError("report_not_waiting")
            if report.get("station")!=self.store.station: raise ValueError("report_belongs_to_other_station")
            if time.time()>report["deadline"]:
                return self.finish_failure(ident,"timed_out","timeout")
            if self.active or not self.acquire(): raise ValueError("gpu_busy")
            self.active=ident
            self.heartbeat=time.time()
            self._update(ident,state="processing",stage="loading",heartbeat=time.time())
            return {"id":ident,"lease":self.secrets[ident],"deadline":report["deadline"],
                    "language":report["language"],"model_revision":report["model_revision"]}

    def authorize(self, ident, lease):
        with self.lock:
            secret=self.secrets.get(ident)
            report=self.store.get("reports",ident)
            if not secret or not isinstance(lease,str) or not secrets.compare_digest(secret,lease):
                raise ValueError("invalid_report_lease")
            if not report or report["state"] not in {"processing","exporting"}:
                raise ValueError("report_not_active")
            if time.time()>=report["deadline"]:
                self.finish_failure(ident,"timed_out","timeout")
                raise ValueError("timeout")
            return report

    def progress(self, ident, lease, stage, fraction=None):
        self.authorize(ident,lease)
        if stage not in {"loading","preprocessing","encoding","prefill","generating","translating","exporting"}:
            raise ValueError("invalid_progress_stage")
        if fraction is not None:
            if not isinstance(fraction,(float,int)) or not 0<=fraction<=1: raise ValueError("invalid_progress")
            if stage in {"generating","translating","encoding"}: fraction=None
        # Do not persist heartbeats as sync events. Persist actual stage changes only.
        with self.lock:
            self.heartbeat=time.time()
            old=self.store.get("reports",ident)
            if old.get("stage")!=stage:
                self._update(ident,stage=stage,progress=fraction)
        return {"ok":True}

    def accept(self, ident, lease, *, original, translated, eos, tokens, truncated=False):
        report=self.authorize(ident,lease)
        if report["state"]!="processing": raise ValueError("report_not_processing")
        if truncated or not eos or not isinstance(tokens,int) or not 0<tokens<4096:
            return self.finish_failure(ident,"truncated","output_truncated")
        for text in (original,translated):
            if not isinstance(text,str) or not text.strip() or len(text)>120000 or "<think>" in text:
                raise ValueError("invalid_draft")
        extraction=extract_own_draft(original,source=report["source"],report_id=ident)
        display=original if report["language"]=="en" else translated
        return self._update(ident,state="exporting",stage="exporting",original=original,
                            translation=translated,display_text=display,extraction=extraction,
                            text_sha256=hashlib.sha256(display.encode()).hexdigest(),tokens=tokens)

    def finalize(self, ident, lease, pages, text_sha256):
        report=self.authorize(ident,lease)
        if report["state"]!="exporting" or text_sha256!=report.get("text_sha256"):
            raise ValueError("draft_export_mismatch")
        try:
            outputs=self.export(report,pages)
            if time.time()>=report["deadline"]: return self.finish_failure(ident,"timed_out","timeout")
            result=self._update(ident,state="completed",stage="completed",outputs=outputs,progress=1)
            self.store.put("reviews","report:"+ident,{"kind":"report","id":ident,"state":"pending","created_at":time.time()})
            self._release(ident)
            return result
        except Exception:
            self.finish_failure(ident,"failed","export_failed")
            raise

    def _release(self, ident):
        with self.lock:
            if self.active==ident:
                self.active=None
                self.release()
            self.secrets.pop(ident,None)

    def finish_failure(self, ident, state, error):
        if state not in TERMINAL-{ "completed"}: raise ValueError("invalid_failure_state")
        with self.lock:
            report=self.store.get("reports",ident)
            if not report: raise ValueError("report_not_found")
            if report["state"] in TERMINAL: return report
            if time.time()>=report["deadline"]: state,error="timed_out","timeout"
            result=self._update(ident,state=state,error=error,progress=None)
            self._release(ident)
            return result

    def _watch(self):
        while not self.stop.wait(2):
            for report in self.store.list("reports",10000):
                if report["state"] in TERMINAL or report.get("station")!=self.store.station: continue
                now=time.time()
                if now>=report["deadline"]:
                    self.finish_failure(report["id"],"timed_out","timeout")
                elif report["id"]==self.active and now-getattr(self,"heartbeat",report.get("heartbeat",now))>45:
                    self.finish_failure(report["id"],"failed","browser_disconnected")

    def close(self):
        self.stop.set()
        if self.active:
            self.finish_failure(self.active,"cancelled","application_closed")
