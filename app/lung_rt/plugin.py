import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from .provider import LocalProvider
from .reports import Reports, LANGUAGES
from .screening import Screening
from .store import Store
from .export import export_draft


class Runtime:
    def __init__(self, services):
        self.services=dict(services)
        self.root=Path(services["plugin_root"])
        self.store=Store(services.get("data_dir") or self.root/"data")
        self.cfg=dict(services.get("lung_cfg") or services.get("config") or {})
        import radai_lung
        self.core=services.get("core") or radai_lung
        self.provider=LocalProvider(self.root,services.get("model_root") or self.store.directory/"models/nv-reason-ct-int4",services.get("hardware"),services.get("resources_dir"))
        self.sessions={}
        self.session_lock=threading.RLock()
        self.reports=Reports(self.store,self.provider,lambda:self.acquire("lung-report"),lambda:self.release("lung-report"),self.core._inspecionar,self.export)
        self.screening=Screening(self.store,self.core,self.cfg,self.reports,lambda:self.acquire("lung-screening"),lambda:self.release("lung-screening"))

    def acquire(self, name):
        custom=self.services.get("acquire_gpu")
        if custom: return custom(name)
        import radai_queue_state
        return radai_queue_state.tentar_a_vez(name)

    def release(self, name):
        custom=self.services.get("release_gpu")
        if custom: return custom(name)
        import radai_queue_state
        return radai_queue_state.soltar_a_vez(name)

    def select(self, selection):
        resolver=self.services.get("resolve_series")
        if not callable(resolver): raise ValueError("series_resolver_unavailable")
        selected=resolver(selection)
        if not isinstance(selected,dict): raise ValueError("invalid_series_selection")
        series=dict(selected.get("series") or selected)
        for key in ("pasta","uid","cortes"):
            if key not in series and key in selected: series[key]=selected[key]
        self.core.pasta_valida(series.get("pasta"),self.cfg)
        _,_,signature=self.core._inspecionar(series)
        token=secrets.token_urlsafe(32)
        with self.session_lock:
            for old in list(self.sessions):
                if self.sessions[old]["expires"]<time.time(): self.sessions.pop(old,None)
            if len(self.sessions)>=4:
                oldest=min(self.sessions,key=lambda key:self.sessions[key]["expires"])
                self.sessions.pop(oldest,None)
            self.sessions[token]={"series":series,"signature":signature,"expires":time.time()+7200,"scan_root":selected.get("scan_root") or series["pasta"]}
        return {"session":token,"description":str(series.get("desc") or "CT"),"slices":series["cortes"]}

    def session(self, token):
        with self.session_lock:
            entry=self.sessions.get(token)
            if not entry or entry["expires"]<time.time(): raise ValueError("selection_expired")
            return entry

    def volume(self, token):
        import numpy as np
        import SimpleITK as sitk
        entry=self.session(token)
        with self.session_lock:
            if "volume" not in entry:
                with self.core._serie(entry["series"],entry["signature"]) as (_,ref,_):
                    dims=tuple(ref.GetSize())
                    if np.prod(dims)*4>512*1024**2: raise ValueError("volume_too_large")
                    arr=sitk.GetArrayFromImage(ref).astype("<f4")
                    if not np.isfinite(arr).all(): raise ValueError("invalid_volume")
                    matrix=np.array(ref.GetDirection()).reshape(3,3)
                    entry["volume"]=arr
                    entry["meta"]={"dims":list(dims),"spacing":list(ref.GetSpacing()),"dir":[matrix[:,i].tolist() for i in range(3)]}
            return entry["volume"],entry["meta"]

    def export(self, report, pages):
        import pydicom
        series=report["series"]
        with self.core._trava_serie(series,self.cfg) as confirm:
            files,_,signature=self.core._inspecionar(series)
            if signature!=report["signature"]: raise ValueError("series_changed")
            # Core already validates source instances; do not read any human report.
            reference=pydicom.dcmread(files[0],stop_before_pixels=True,force=True)
            confirm()
            return export_draft(reference,series["pasta"],report,pages)

    def volume_meta(self, token):
        """Bind the editor ticket to the displayed volume, including report leases."""
        _, meta = self.volume(token)
        with self.session_lock:
            entry = self.session(token)
            series = entry["series"]
            _, _, signature = self.core._inspecionar(series)
            if signature != entry["signature"]:
                raise ValueError("series_changed")
            if not series.get("pasta") or not series.get("uid"):
                raise ValueError("invalid_series_selection")
            import radai_thumbnail
            ticket = radai_thumbnail.bilhete(series["pasta"], series["uid"])
            return {**meta, "reference_ticket": ticket}

    def public_report(self, value):
        return {**{k:v for k,v in value.items() if k not in {"series","signature","capability","_revision","_key","heartbeat"}},"can_execute":value.get("station")==self.store.station}

    def state(self):
        cases=self.store.list("cases",500)
        public_cases=[]
        for case in cases:
            public_cases.append({k:case[k] for k in ("id","lesions","segmentation_state","report_state","created_at","review","longitudinal_suggestions") if k in case})
        reports=[self.public_report(r) for r in self.store.list("reports",500)]
        pending=[r for r in self.store.list("reviews") if r["state"]=="pending"]
        return {"screening":dict(self.screening.state),"cases":public_cases,"reports":reports,
                "pending":pending,"conflicts":self.store.conflicts(),"defaults":{"generate_reports":0,"sound":False}}

    def consent_valid(self):
        policy=json.loads((self.root/"catalog/consent.json").read_text(encoding="utf-8"))
        receipt_path=Path(self.services.get("consent_path") or self.store.directory.parent/"config/consent.json")
        try:
            receipt=json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            return receipt.get("accepted") is True and receipt.get("version")==policy["version"] and receipt.get("digest")==policy["digest"]
        except (OSError,ValueError): return False

    def action(self, data):
        action=data.get("action")
        if action in {"start_screening","create_report","start_report"} and not self.consent_valid():
            raise ValueError("consent_required")
        language=data.get("language","pt-BR")
        if language not in LANGUAGES: raise ValueError("invalid_language")
        if action=="select": return self.select(data.get("selection"))
        if action=="volume_meta": return self.volume_meta(data.get("session"))
        if action=="start_screening":
            if data.get("confirmed") is not True: raise ValueError("explicit_confirmation_required")
            selection=self.session(data.get("session"))
            return self.screening.start(selection["scan_root"],generate_reports=data.get("generate_reports",0),language=language)
        if action=="stop_screening": return self.screening.cancel()
        if action=="create_report":
            if data.get("confirmed") is not True: raise ValueError("explicit_confirmation_required")
            entry=self.session(data.get("session"))
            report=self.reports.create(entry["series"],language)
            self.report_sessions=getattr(self,"report_sessions",{})
            self.report_sessions[report["id"]]=data["session"]
            return self.public_report(report)
        ident=data.get("id")
        lease=data.get("lease")
        if action=="start_report":
            output=self.reports.start(ident)
            if output.get("lease"):
                sessions=getattr(self,"report_sessions",{})
                token=sessions.get(ident)
                if not token:
                    report=self.store.get("reports",ident)
                    token=secrets.token_urlsafe(32)
                    self.sessions[token]={"series":report["series"],"signature":report["signature"],"expires":report["deadline"]}
                output["session"]=token
            return output
        if action=="report_progress": return self.reports.progress(ident,lease,data.get("stage"),data.get("fraction"))
        if action=="report_result":
            return self.public_report(self.reports.accept(ident,lease,original=data.get("original"),translated=data.get("translated"),eos=data.get("eos") is True,tokens=data.get("tokens"),truncated=data.get("truncated",False)))
        if action=="report_export": return self.public_report(self.reports.finalize(ident,lease,data.get("pages"),data.get("text_sha256")))
        if action=="cancel_report": return self.public_report(self.reports.finish_failure(ident,"cancelled","cancelled"))
        if action=="report_error":
            self.reports.authorize(ident,lease)
            return self.public_report(self.reports.finish_failure(ident,"failed",data.get("error") if data.get("error") in {"webgpu_unavailable","worker_failed","model_load_failed","browser_disconnected"} else "worker_failed"))
        if action=="confirm_link":
            case=self.store.get("cases",data.get("case_id"))
            if not case: raise ValueError("case_not_found")
            match=next((m for m in case.get("longitudinal_suggestions",[]) if m["previous_case"]==data.get("previous_case") and m["previous_lesion"]==data.get("previous_lesion") and m["current_lesion"]==data.get("current_lesion")),None)
            if not match: raise ValueError("invalid_longitudinal_link")
            previous_key=match["previous_case"]+":"+str(match["previous_lesion"])
            prior=self.store.get("links",previous_key)
            stable_id=prior["stable_id"] if prior else hashlib.sha256(previous_key.encode()).hexdigest()
            return self.store.put("links",case["id"]+":"+str(match["current_lesion"]),{**match,"case_id":case["id"],"stable_id":stable_id,"status":"confirmed","confirmed_at":time.time()})
        if action=="review":
            key=data.get("key");record=self.store.get("reviews",key)
            if not record: raise ValueError("review_not_found")
            # Acknowledgment does not approve the clinical document or RTSTRUCT.
            record.update(state="reviewed",reviewed_at=time.time())
            collection="cases" if record["kind"]=="case" else "reports"
            source=self.store.get(collection,record["id"])
            if source:
                source["review"]="reviewed"
                self.store.put(collection,record["id"],source)
            return self.store.put("reviews",key,record,expected_revision=data.get("revision"))
        if action=="sync":
            if data.get("confirmed") is not True: raise ValueError("explicit_confirmation_required")
            return self.store.sync(data.get("folder"))
        if action=="backup":
            if data.get("confirmed") is not True: raise ValueError("explicit_confirmation_required")
            return self.store.backup(data.get("folder"))
        raise ValueError("unknown_action")

    def close(self):
        self.screening.cancel()
        self.reports.close()


def mount(app, host_services):
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
    from starlette.concurrency import run_in_threadpool
    from fastapi.staticfiles import StaticFiles
    if getattr(app.state,"lung_plugin",None): return app.state.lung_plugin
    runtime=Runtime(host_services)
    app.state.lung_plugin=runtime

    @app.middleware("http")
    async def local_boundary(request,call_next):
        from ipaddress import ip_address
        protected=request.url.path.startswith(("/api/lung-plugin/","/lung-assets/","/lung/rastreio","/lung/laudo"))
        if protected:
            def loopback(value):
                if value=="localhost": return True
                try: return ip_address(value or "").is_loopback
                except ValueError: return False
            peer=request.client.host if request.client else ""
            if not ((loopback(peer) or (peer=="testclient" and host_services.get("test_client") is True)) and loopback(request.url.hostname)):
                return JSONResponse({"error":"loopback_required"},status_code=403)
            if request.headers.get("sec-fetch-site")=="cross-site":
                return JSONResponse({"error":"invalid_origin"},status_code=403)
        response=await call_next(request)
        if protected:
            response.headers["Cache-Control"]="no-store"
            response.headers["X-Content-Type-Options"]="nosniff"
        return response
    app.mount("/lung-assets",StaticFiles(directory=str(runtime.root/"web")),name="lung-plugin-assets")

    def page(mode):
        from .ui import render
        return render(runtime,mode)

    @app.get("/lung/rastreio",response_class=HTMLResponse)
    def screening_page(): return page("screening")

    @app.get("/lung/laudo",response_class=HTMLResponse)
    def report_page(): return page("report")

    @app.get("/lung/laudo/rx",response_class=HTMLResponse)
    def xray_report_page():
        from .ui import render_xray
        return render_xray(runtime)

    from .xray import mount_xray_api
    xray=mount_xray_api(app,runtime)

    @app.get("/api/lung-plugin/status")
    def status():
        from . import __version__
        return {"version":__version__,"capability":runtime.provider.preflight(verify=False),
                "capabilities":{"rastreio":True,"nodulos":True,"4d":True,
                                "report_ct":{"resources_ready":runtime.provider.assets_ready()},
                                "report_rx":{"resources_ready":xray.status()['resources_ready']}},**runtime.state()}

    @app.get("/api/lung-plugin/state")
    def state(): return runtime.state()

    @app.post("/api/lung-plugin/action")
    async def action(request:Request):
        if request.headers.get("origin")!=f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"error":"invalid_origin"},status_code=403)
        raw=await request.body()
        if len(raw)>32*1024**2: return JSONResponse({"error":"request_too_large"},status_code=413)
        try:
            data=json.loads(raw)
            if not isinstance(data,dict): raise ValueError("invalid_request")
            return await run_in_threadpool(runtime.action,data)
        except (ValueError,KeyError,TypeError) as exc:
            allowed=str(exc)
            # Core errors may contain paths or identifiers. Return stable translated codes only.
            if not allowed.replace("_","").isalnum() or " " in allowed: allowed="operation_failed"
            return JSONResponse({"error":allowed[:80]},status_code=400)
        except Exception:
            return JSONResponse({"error":"operation_failed"},status_code=500)

    @app.get("/api/lung-plugin/volume/{token}")
    def volume(token:str):
        try:
            array,_=runtime.volume(token)
            return Response(array.tobytes(order="C"),media_type="application/octet-stream",headers={"Cache-Control":"no-store"})
        except Exception: return JSONResponse({"error":"volume_unavailable"},status_code=400)

    @app.get("/api/lung-plugin/provider-manifest")
    def provider_manifest(): return runtime.provider.manifest

    @app.get("/api/lung-plugin/runtime/{name}")
    def runtime_resource(name:str):
        if name not in {"ort-wasm-simd-threaded.asyncify.mjs","ort-wasm-simd-threaded.asyncify.wasm"}:
            return JSONResponse({"error":"invalid_resource"},status_code=404)
        try: path=runtime.provider.runtime_file(name,verify=True)
        except (OSError,ValueError): return JSONResponse({"error":"runtime_not_prepared"},status_code=404)
        return FileResponse(path,media_type="text/javascript" if name.endswith("mjs") else "application/wasm")

    @app.get("/api/lung-plugin/models/{name:path}")
    def model(name:str):
        try:
            path=runtime.provider.path(name)
            if not runtime.provider.resources(verify=True)["ready"]: raise ValueError("model_not_prepared")
            return FileResponse(path,headers={"Cache-Control":"private, no-cache"})
        except Exception: return JSONResponse({"error":"model_not_prepared"},status_code=404)

    app.router.add_event_handler("shutdown",runtime.close)
    return runtime
