# Host contract — LUNG RT 1.1.2

Discovery: module.json schema lung-rt/plugin-manifest/1, id lung-rt, host >=8.17.
Adapter integration/local_suite.py:mount(app, code=None, *, host_services=None)
imports app/lung_rt/plugin.py:mount(app, host_services). It does not redefine /lung,
/lung/nodulos, /lung/4d or /api/lung/*.

Required host services: plugin_root (code directory), data_dir (local durable data),
lung_cfg (core config: marcadores claim/renovar/unclaim/lock_e_meu, maquina, device,
log, raizes_protegidas; optional heartbeat_s, timeout_task_s, min_cortes),
resolve_series(selection) where selection contains scan_id, bilhete, uid; returns
verified series with pasta, uid, cortes and optional scan_root. No UID-only lookup.

Optional/installed services: ui_apply(page, active), consent_path, model_root,
resources_dir, acquire_gpu(owner), release_gpu(owner), language(request=None).
The default queue adapter uses radai_queue_state with distinct owners lung-report
and lung-screening. The host queue allowlist must include both, as well as legacy lung.

Data files stay outside immutable code: data/lung.sqlite3; config/consent.json;
models/nv-reason-ct-int4/; runtimes/nvreason/. Resources are pin-verified from recipe.
The local model endpoint accepts only manifest entries. The runtime endpoint accepts
only its two declared WASM loader/runtime files and checks their hashes. Reports
perform forced full SHA256 verification before work, regardless of unchanged stat.
All plugin routes require loopback peer/Host and reject Sec-Fetch-Site cross-site.
POST actions additionally require exact same Origin. Responses use no-store.

Routes: /lung/rastreio, /lung/laudo; /api/lung-plugin/status, /state,
/action (POST), /volume/{opaque-session}, /provider-manifest, /models/{manifest-path},
/runtime/{allowlisted-file}. Browser-only GPU inference uses a random report lease;
server verifies job state, EOS/truncation metadata, deadline, source signature and
series lock before export. Browser canvas renders Unicode report pages; the server
builds PDF and DICOM using stdlib/pydicom. No new Python dependency.

Consent receipt: schema lung-rt/consent-receipt/1, accepted=true, version and digest
exactly equal catalog/consent.json, accepted_at. Starting either workflow requires it.
No watcher or report job rearms after process restart.

X-ray drafts use /lung/laudo/rx and /api/lung-plugin/xray/{status,preview,prepare,report}.
Preview accepts one local DX/CR chest radiograph, PNG or JPEG and returns a sanitized PNG.
The optional MedGemma resources are pinned in catalog/xray_resources.json and prepared
only with separate license acceptance. A transient report acquires the lung-xray-report
queue owner and does not enter the CT report store.

The status response has `capabilities`: `rastreio`, `nodulos`, `4d` are true for
the code-only plugin. `report_ct.resources_ready` requires the CT model files and
both ORT runtime assets; `report_rx.resources_ready` requires the three pinned
MedGemma/runtime files. These flags describe available assets, independently of
hardware and the model license receipt. Inference still verifies SHA256, consent,
hardware and the local queue before executing. The RX status `ready` additionally
requires its local HAI-DEF receipt; the offline bundle never creates that receipt.

Native `Pacote para levar` emits a folder and an adjacent ZIP with identical known
package entries, rooted at `code/`, `release-manifest.json` and optional `resources/`.
CT resources keep `resources/models/...` and `resources/runtimes/...`; RX uses
`resources/xray/<pinned-revision>/<filename>`. The host importer verifies sizes and
hashes and copies RX into `Plugins/LUNG RT/data/xray/<pinned-revision>/`, without a
license receipt. It must support both a folder source and a ZIP source. Preparing
with `--reports` includes CT + RX (~6.38 GB), reusing matching destination/Suite
assets. This routine does not download or package Python or TotalSegmentator weights.
