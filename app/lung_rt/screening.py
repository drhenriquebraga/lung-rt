import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .longitudinal import suggest
from .screening_images import save_views


class Screening:
    def __init__(self, store, core, config, reports, acquire, release, announce=None):
        self.store, self.core, self.config, self.reports = store, core, config, reports
        self.acquire, self.release = acquire, release
        self.announce = announce
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.state = dict(active=False, completed=0, positive=0, failed=0, stage="idle", generate_reports=0)
        self.thread = None

    def _set(self, stage):
        self.state["stage"] = stage
        if self.announce:
            self.announce(stage, self.state["completed"], self.state["positive"])

    def _save(self, options):
        # Paths and restart intent are specific to the workstation; never sync them as events.
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('local-screening',?)", (json.dumps(options),))

    def options(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='local-screening'").fetchone()
        return json.loads(row[0]) if row else {}

    def resume(self):
        options = self.options()
        if options.get("enabled") is True:
            self._launch(options, 20)

    def start(self, folder, *, generate_reports=0, language="pt-BR", interval=20):
        entries = [folder] if isinstance(folder, str) else folder
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise ValueError("invalid_folders")
        folders = list(dict.fromkeys(self.core.pasta_valida(f, self.config) for f in entries))
        if generate_reports not in (0, 1):
            raise ValueError("invalid_report_flag")
        options = dict(enabled=True, folders=folders, generate_reports=int(generate_reports), language=language)
        with self.lock:
            if self.state["active"]:
                raise ValueError("screening_already_active")
            self._save(options)
            self._launch(options, interval)
            return dict(self.state)

    def _launch(self, options, interval):
        self.stop.clear()
        self.state.update(active=True, completed=0, positive=0, failed=0, generate_reports=options["generate_reports"])
        self._set("watching")
        self.thread = threading.Thread(target=self._run, args=(options, interval), daemon=True, name="lung-screening")
        self.thread.start()

    def _record(self, series, signature, case_id, options):
        views = {}
        def preview(image, mask, lungs):
            if mask is not None:
                try:
                    views.update(save_views(self.store.directory, case_id, image, mask))
                except (OSError, ValueError, MemoryError):
                    self.state["last_error"] = "preview_unavailable"

        receipt = self.core.processar_serie(series, dict(self.config, receber_resultado=preview), esperado=signature)
        lesions = [dict(lesion, **views.get(lesion["id"], {})) for lesion in receipt["lesoes"]]
        case = dict(id=case_id, series=dict(series), signature=signature, receipt=receipt,
                    patient_key=receipt["paciente_chave"], frame_uid=receipt["frame_uid"],
                    lesions=lesions, segmentation_state=receipt["estado"], created_at=time.time(),
                    review="pending", report_state="disabled" if not options["generate_reports"] else "requested")
        previous = self.store.list("cases")
        case["longitudinal_suggestions"] = [dict(match, previous_case=p["id"]) for p in previous
                                            if p["id"] != case_id for match in suggest(p, case)]
        self.store.put("cases", case_id, case)
        self.store.put("reviews", "case:"+case_id, dict(kind="case", id=case_id, state="pending", created_at=time.time()))
        self.state["completed"] += 1
        self.state["positive"] += int(receipt["estado"] == "positivo")
        self._report(case, series, options)

    def _report(self, case, series, options):
        if not options["generate_reports"] or self.stop.is_set() or case.get("report_state") not in ("disabled", "requested", None):
            return
        try:
            draft = self.reports.create(series, options["language"], case_id=case["id"])
            case["report_id"], case["report_state"] = draft["id"], draft["state"]
        except Exception:
            case["report_state"] = "failed"
        self.store.put("cases", case["id"], case)

    def _run(self, options, interval):
        seen, done = {}, set()
        try:
            while not self.stop.is_set():
                now, folders_seen = {}, {}
                self.state.pop("last_error", None)
                for folder in options["folders"]:
                    if self.stop.is_set():
                        break
                    try:
                        series_list = self.core.varrer(folder, self.config)
                    except (ValueError, OSError, RuntimeError):
                        self.state["last_error"] = "folder_unavailable"
                        continue
                    for series in series_list:
                        if self.stop.is_set():
                            break
                        uid = series["uid"]
                        if uid in now:
                            continue
                        case_id = signature = None
                        try:
                            path = series["pasta"]
                            if path not in folders_seen:
                                with os.scandir(path) as scan:
                                    entries = [(f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in scan
                                               if f.is_file() and not f.name.startswith("RS_RadAI")]
                                folders_seen[path] = hash(tuple(sorted(entries)))
                            change = (series["cortes"], folders_seen[path])
                            now[uid] = change
                            if seen.get(uid) != change or (uid,change) in done:
                                continue
                            _, _, signature = self.core._inspecionar(series)
                            case_id = hashlib.sha256((uid+signature).encode()).hexdigest()
                            previous = self.store.get("cases", case_id)
                            if previous and previous.get("segmentation_state") in ("positivo", "vazio"):
                                self._report(previous, series, options)
                                done.add((uid, change))
                                continue
                            self._set("waiting")
                            while not self.acquire():
                                if self.stop.wait(.5):
                                    return
                            try:
                                self._set("segmenting")
                                self._record(series, signature, case_id, options)
                            finally:
                                self.release()
                            done.add((uid, change))
                        except Exception:
                            if case_id:
                                done.add((uid, change))
                                self.state["failed"] += 1
                                self.store.put("cases", case_id, dict(id=case_id, series=dict(series),
                                    signature=signature, lesions=[], segmentation_state="falha",
                                    report_state="disabled", created_at=time.time(), review="pending",
                                    error="segmentation_failed"))
                            self.state["last_error"] = "segmentation_failed"
                seen = now
                done.intersection_update(now.items())
                self._set("watching")
                self.stop.wait(max(1, interval))
        finally:
            with self.lock:
                self.state["active"] = False
                self._set("stopped")

    def cancel(self, *, shutdown=False):
        with self.lock:
            if not shutdown:
                self._save(dict(self.options(), enabled=False))
            self.stop.set()
            self._set("cancelling" if self.state["active"] else "stopped")
            return dict(self.state)
