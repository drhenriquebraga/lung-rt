"""Local, transient chest radiograph drafts, independent of the CT model."""

import ctypes
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit
import zipfile

from radai_lung_install import _atomic, _download, _inside, _json, _sha


MIB = 1024**2
GIB = 1024**3
MAX_BODY = 32 * MIB
MAX_DIMENSION = 8192
MAX_PIXELS = 16 * MIB
PNG = b"\x89PNG\r\n\x1a\n"
REPORT_TIMEOUT = 900
MIN_MEMORY = 8 * 1000**3
MIN_AVAILABLE_MEMORY = 4 * GIB
SCRATCH_SPACE = 256 * MIB
EXECUTABLE = "llama-mtmd-cli.exe"
LICENSE = "health-ai-developer-foundations"
DRAFT_LANGUAGES = {
    "pt-BR": ("Brazilian Portuguese", "Achados", "Impressão"),
    "en": ("English", "Findings", "Impression"),
    "de": ("German", "Befunde", "Beurteilung"),
    "es": ("Spanish", "Hallazgos", "Impresión"),
    "fr": ("French", "Observations", "Conclusion"),
    "it": ("Italian", "Reperti", "Conclusioni"),
    "pl": ("Polish", "Wyniki", "Wnioski"),
    "ar": ("Arabic", "المشاهدات", "الخلاصة"),
    "bn": ("Bengali", "পর্যবেক্ষণ", "সারসংক্ষেপ"),
    "ko": ("Korean", "소견", "판독 요약"),
    "zh-CN": ("Simplified Chinese", "所见", "印象"),
    "ja": ("Japanese", "所見", "まとめ"),
}
REPORT_PROMPT = (
    "Write a concise experimental draft report in Brazilian Portuguese for this single frontal chest radiograph. "
    "Use achados for observations and impressao for a concise summary. Describe only visible evidence, "
    "acknowledge uncertainty and limitations, and do not invent measurements, history, identifiers, comparisons "
    "or recommendations. Return only the requested JSON object, without a diagnosis or any reasoning transcript."
)
REPORT_SCHEMA = {
    "type": "object",
    "properties": {"achados": {"type": "string"}, "impressao": {"type": "string"}},
    "required": ["achados", "impressao"],
    "additionalProperties": False,
}


class XrayError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def _check_dimensions(width, height):
    if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION and width * height <= MAX_PIXELS):
        raise XrayError("image_dimensions_invalid")


def _normalize_grayscale(pixels, mask=None, invert=False):
    import numpy as np
    from PIL import Image

    pixels = np.asarray(pixels, dtype=np.float32)
    valid = np.isfinite(pixels)
    if mask is not None:
        valid &= mask
    values = pixels[valid]
    if not values.size:
        raise XrayError("invalid_xray")
    low, high = np.percentile(values, (0.5, 99.5))
    if high <= low:
        low, high = values.min(), values.max()
    if high <= low:
        raise XrayError("invalid_xray")
    result = np.zeros(pixels.shape, dtype=np.uint8)
    scaled = np.clip((values - low) * (255 / (high - low)), 0, 255).astype(np.uint8)
    result[valid] = 255 - scaled if invert else scaled
    return Image.fromarray(result)


def _dicom_image(raw):
    import pydicom
    from pydicom.pixels import apply_modality_lut, apply_voi_lut

    ds = pydicom.dcmread(BytesIO(raw), force=False)
    view = str(ds.get("ViewPosition", "")).strip().upper()
    body = str(ds.get("BodyPartExamined", "")).strip().upper()
    if (
        ds.get("Modality") not in {"DX", "CR"}
        or ds.get("SOPClassUID") not in {
            pydicom.uid.DigitalXRayImageStorageForPresentation,
            pydicom.uid.DigitalXRayImageStorageForProcessing,
            pydicom.uid.ComputedRadiographyImageStorage,
        }
        or int(ds.get("NumberOfFrames", 1)) != 1
        or ds.get("SamplesPerPixel") != 1
        or ds.get("PhotometricInterpretation") not in {"MONOCHROME1", "MONOCHROME2"}
        or (view and view not in {"AP", "PA", "AP SUPINE", "AP ERECT", "PA ERECT"})
        or (body and body not in {"CHEST", "THORAX", "LUNG", "LUNGS", "TÓRAX", "TORAX"})
    ):
        raise XrayError("unsupported_xray")
    _check_dimensions(int(ds.Columns), int(ds.Rows))
    if int(ds.BitsAllocated) not in {8, 16, 32}:
        raise XrayError("unsupported_xray")
    ds.pixel_array_options(index=0, allow_excess_frames=False)
    pixels = ds.pixel_array
    if pixels.shape != (ds.Rows, ds.Columns):
        raise XrayError("invalid_xray")
    padding = ds.get("PixelPaddingValue")
    mask = None
    if padding is not None:
        end = ds.get("PixelPaddingRangeLimit", padding)
        mask = (pixels < min(padding, end)) | (pixels > max(padding, end))
    windowed = apply_voi_lut(apply_modality_lut(pixels, ds), ds)
    presentation = ds.get("PresentationLUTShape")
    invert = presentation == "INVERSE" if presentation else ds.PhotometricInterpretation == "MONOCHROME1"
    return _normalize_grayscale(windowed, mask, invert)


def sanitize_image(raw, png_only=False):
    from PIL import Image, ImageOps

    try:
        if raw[128:132] == b"DICM" and not png_only:
            image = _dicom_image(raw)
        else:
            formats = ["PNG"] if png_only else ["PNG", "JPEG"]
            with Image.open(BytesIO(raw), formats=formats) as source:
                _check_dimensions(*source.size)
                if getattr(source, "n_frames", 1) != 1:
                    raise XrayError("unsupported_xray")
                oriented = ImageOps.exif_transpose(source)
                if oriented.mode in {"I", "I;16", "I;16B", "I;16L", "F"}:
                    image = _normalize_grayscale(oriented)
                elif "A" in oriented.getbands() or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
                    image = Image.alpha_composite(background, rgba).convert("L")
                else:
                    image = oriented.convert("L")
        # Create a fresh raster: no DICOM tags, EXIF, text chunks or source filenames.
        clean = Image.frombytes("L", image.size, image.tobytes())
        output = BytesIO()
        clean.save(output, format="PNG")
        return output.getvalue()
    except XrayError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RuntimeError, Image.DecompressionBombError):
        raise XrayError("invalid_xray") from None


def _manifest(path):
    data = _json(path, limit=8192)
    if (
        data.get("schema") != "lung-rt/xray-resources/1"
        or data.get("model_id") != "google/medgemma-1.5-4b-it"
        or not re.fullmatch(r"[0-9a-f]{40}", data.get("revision", ""))
    ):
        raise ValueError("invalid_xray_manifest")
    filenames = set()
    for key, suffix, host, maximum in (
        ("runtime", ".zip", "github.com", 128 * MIB),
        ("model", ".gguf", "huggingface.co", 6 * GIB),
        ("mmproj", ".gguf", "huggingface.co", 2 * GIB),
    ):
        spec = data[key]
        name = spec["filename"]
        url = urlsplit(spec["url"])
        if (
            not re.fullmatch(r"[A-Za-z0-9._-]+", name)
            or not name.endswith(suffix)
            or name.casefold() in filenames
            or url.scheme != "https"
            or url.netloc != host
            or type(spec["size"]) is not int
            or not 0 < spec["size"] <= maximum
            or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])
        ):
            raise ValueError("invalid_xray_resource")
        filenames.add(name.casefold())
    return data


def _extract_runtime(archive_path, directory):
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > 256 or sum(item.file_size for item in members) > SCRATCH_SPACE:
            raise ValueError("runtime_archive_too_large")
        paths = set()
        candidates = []
        for item in members:
            name = item.filename.rstrip("/")
            target = _inside(directory, name)
            if (
                "\\" in name or name.casefold() in paths or item.flag_bits & 1
                or stat.S_ISLNK(item.external_attr >> 16) or item.external_attr & 0x400
            ):
                raise ValueError("invalid_runtime_archive")
            paths.add(name.casefold())
            if not item.is_dir():
                candidates.append((item, target))
        executables = [target for _, target in candidates if target.name.casefold() == EXECUTABLE]
        if len(executables) != 1:
            raise ValueError("missing_xray_runtime")
        executable = executables[0]
        executable.parent.mkdir(parents=True, exist_ok=True)
        for item, target in candidates:
            if target == executable or (target.parent == executable.parent and target.suffix.casefold() == ".dll"):
                with archive.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, MIB)
        return executable


def _windows_memory():
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in (
                "total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended"
            )
        ]

    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise XrayError("unsupported_platform", 503)
    memory = Memory()
    memory.length = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise XrayError("resources_unavailable", 503)
    return memory.total, memory.available


def _draft_language(accept_language):
    preferred = accept_language.partition(",")[0].partition(";")[0].strip().lower()
    primary = preferred.partition("-")[0]
    locale = {"pt": "pt-BR", "zh": "zh-CN"}.get(primary, primary)
    return locale if locale in DRAFT_LANGUAGES else "pt-BR"


def _report_text(stdout, language="pt-BR"):
    try:
        if len(stdout) > 32000:
            raise ValueError("report_too_large")
        data = json.loads(stdout.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"achados", "impressao"}:
            raise ValueError("invalid_report")
        findings, impression = data["achados"].strip(), data["impressao"].strip()
        if not findings or not impression or any(mark in (findings + impression).lower() for mark in ("<think", "</think")):
            raise ValueError("invalid_report")
    except (ValueError, AttributeError):
        raise XrayError("report_failed", 500) from None
    _, findings_label, impression_label = DRAFT_LANGUAGES[language]
    return f"{findings_label}\n{findings}\n\n{impression_label}\n{impression}"


class XrayService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.process = None
        self.preparing = False
        self.running = False
        self.downloaded = 0
        self.error = None
        self.invalid_resources = False
        self.manifest = None
        try:
            manifest = _manifest(runtime.root / "catalog/xray_resources.json")
            self.root = _inside(runtime.store.directory, "xray/" + manifest["revision"])
            self.manifest = manifest
            self.specs = [manifest[key] for key in ("runtime", "model", "mmproj")]
            self.receipt = {"accepted": True, "license": LICENSE, "model": manifest["model_id"], "revision": manifest["revision"]}
            self.total = sum(spec["size"] for spec in self.specs)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.error = "resources_unavailable"
            self.total = 0

    def _path(self, name):
        return _inside(self.root, name)

    def _matches(self, spec, verify=False):
        try:
            path = self._path(spec["filename"])
            return path.is_file() and path.stat().st_size == spec["size"] and (not verify or _sha(path) == spec["sha256"])
        except (OSError, ValueError):
            return False

    def _resources_ready(self):
        return bool(self.manifest and not self.invalid_resources and all(self._matches(spec) for spec in self.specs))

    def _ready(self):
        if not self._resources_ready():
            return False
        try:
            accepted = _json(self._path("license.json"), limit=2048) == self.receipt
            return accepted and all(self._matches(spec) for spec in self.specs)
        except (OSError, ValueError):
            return False

    def status(self):
        with self.lock:
            ready = not self.preparing and self._ready()
            return {
                "ready": ready,
                "resources_ready": not self.preparing and self._resources_ready(),
                "preparing": self.preparing,
                "running": self.running,
                "error": self.error,
                "downloaded_bytes": self.total if ready else self.downloaded,
                "total_bytes": self.total,
                "model_id": self.manifest["model_id"] if self.manifest else None,
                "revision": self.manifest["revision"] if self.manifest else None,
            }

    def _check_idle(self):
        if self.stop.is_set() or not self.manifest:
            raise XrayError("resources_unavailable", 503)
        if self.preparing or self.running:
            raise XrayError("xray_busy", 409)

    def prepare(self):
        with self.lock:
            self._check_idle()
            if _windows_memory()[0] < MIN_MEMORY:
                raise XrayError("insufficient_memory", 503)
            self.preparing = True
            self.downloaded = 0
            self.error = None
            try:
                worker = threading.Thread(target=self._prepare, daemon=True, name="lung-rx-download")
                worker.start()
            except RuntimeError:
                self.preparing = False
                raise XrayError("download_failed", 503) from None
        return self.status()

    def _prepare(self):
        error = None
        try:
            missing = [spec for spec in self.specs if not self._matches(spec, verify=True)]
            self._path("license.json").parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.root).free < SCRATCH_SPACE + sum(spec["size"] for spec in missing):
                raise XrayError("insufficient_disk", 503)
            offset = 0
            for spec in self.specs:
                if self.stop.is_set():
                    raise XrayError("download_failed", 503)
                if spec in missing:
                    def progress(event):
                        with self.lock:
                            self.downloaded = offset + event["downloaded_bytes"]
                    _download([spec["url"]], self._path(spec["filename"]), spec["size"], spec["sha256"], progress, self.stop.is_set)
                offset += spec["size"]
                with self.lock:
                    self.downloaded = offset
            _atomic(self._path("license.json"), self.receipt)
        except XrayError as exc:
            error = exc.code
        except Exception:
            error = "download_failed"
        finally:
            with self.lock:
                self.error = error
                self.invalid_resources = bool(error)
                self.preparing = False

    def generate(self, png, language="pt-BR"):
        with self.lock:
            self._check_idle()
            if not self._ready():
                raise XrayError("model_not_prepared", 503)
            total, free = _windows_memory()
            if total < MIN_MEMORY or free < MIN_AVAILABLE_MEMORY:
                raise XrayError("insufficient_memory", 503)
            if shutil.disk_usage(self.root).free < SCRATCH_SPACE:
                raise XrayError("insufficient_disk", 503)
            if not self.runtime.acquire("lung-xray-report"):
                raise XrayError("xray_busy", 409)
            self.running = True
            self.error = None
        try:
            clean = sanitize_image(png, png_only=True)
            runtime = self.manifest["runtime"]
            with self._path(runtime["filename"]).open("rb") as archive:
                runtime_bytes = archive.read(runtime["size"] + 1)
            if (
                len(runtime_bytes) != runtime["size"]
                or hashlib.sha256(runtime_bytes).hexdigest() != runtime["sha256"]
                or not all(self._matches(self.manifest[key], verify=True) for key in ("model", "mmproj"))
            ):
                with self.lock:
                    self.invalid_resources = True
                raise XrayError("resources_invalid", 503)
            with tempfile.TemporaryDirectory(prefix="lung-rx-", dir=self.root) as folder:
                scratch = Path(folder)
                exe = _extract_runtime(BytesIO(runtime_bytes), scratch / "runtime")
                image = scratch / "radiograph.png"
                image.write_bytes(clean)
                text = self._run(exe, image, scratch, language)
            return {"text": text, "model": self.manifest.get("display_name", self.manifest["model_id"]),
                    "requested_language": language}
        except XrayError as exc:
            with self.lock:
                self.error = exc.code
            raise
        except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError):
            with self.lock:
                self.error = "report_failed"
            raise XrayError("report_failed", 500) from None
        finally:
            try:
                self.runtime.release("lung-xray-report")
            finally:
                with self.lock:
                    self.process = None
                    self.running = False

    def _run(self, executable, image, scratch, language="pt-BR"):
        threads = min(4, max(1, (os.cpu_count() or 2) // 2))
        args = [
            str(executable), "-m", str(self._path(self.manifest["model"]["filename"])),
            "--mmproj", str(self._path(self.manifest["mmproj"]["filename"])),
            "--image", str(image), "--no-mmproj-offload", "-ngl", "0", "--offline",
            "-t", str(threads), "-c", "4096", "-n", "512", "--temp", "0",
            "--json-schema", json.dumps(REPORT_SCHEMA, separators=(",", ":")), "-p",
            REPORT_PROMPT.replace("Brazilian Portuguese", DRAFT_LANGUAGES[language][0]),
        ]
        system = os.environ.get("SystemRoot", r"C:\Windows")
        env = {
            "SystemRoot": system, "WINDIR": system, "TEMP": str(scratch), "TMP": str(scratch),
            "PATH": os.pathsep.join((str(executable.parent), str(Path(system) / "System32"))),
        }
        with self.lock:
            if self.stop.is_set():
                raise XrayError("resources_unavailable", 503)
            process = subprocess.Popen(
                args, cwd=executable.parent, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.process = process
        try:
            stdout, _ = process.communicate(timeout=REPORT_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise XrayError("report_timeout", 504) from None
        if process.returncode:
            raise XrayError("report_failed", 500)
        return _report_text(stdout, language)

    def close(self):
        self.stop.set()
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.kill()
                except OSError:
                    pass


async def _body(request, limit):
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise XrayError("invalid_request") from None
        if size < 0:
            raise XrayError("invalid_request")
        if size > limit:
            raise XrayError("request_too_large", 413)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise XrayError("request_too_large", 413)
        data.extend(chunk)
    if not data:
        raise XrayError("invalid_request")
    return bytes(data)


def mount_xray_api(app, runtime):
    from fastapi import Request
    from fastapi.responses import JSONResponse, Response
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import ClientDisconnect

    service = XrayService(runtime)
    app.state.lung_xray = service

    def guard(request, consent=False):
        if request.headers.get("origin") != f"{request.url.scheme}://{request.url.netloc}":
            raise XrayError("invalid_origin", 403)
        if consent and not runtime.consent_valid():
            raise XrayError("consent_required", 403)

    def failure(error):
        if isinstance(error, XrayError):
            return JSONResponse({"error": error.code}, status_code=error.status)
        if isinstance(error, ClientDisconnect):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        return JSONResponse({"error": "report_failed"}, status_code=500)

    @app.get("/api/lung-plugin/xray/status")
    def status():
        return service.status()

    @app.post("/api/lung-plugin/xray/prepare")
    async def prepare(request: Request):
        try:
            guard(request, consent=True)
            try:
                data = json.loads(await _body(request, 4096))
            except (ValueError, UnicodeError):
                raise XrayError("invalid_request") from None
            if not isinstance(data, dict) or data.get("accept") is not True:
                raise XrayError("license_required", 403)
            return await run_in_threadpool(service.prepare)
        except Exception as exc:
            return failure(exc)

    @app.post("/api/lung-plugin/xray/preview")
    async def preview(request: Request):
        try:
            guard(request)
            clean = await run_in_threadpool(sanitize_image, await _body(request, MAX_BODY))
            return Response(clean, media_type="image/png", headers={"Cache-Control": "no-store"})
        except Exception as exc:
            return failure(exc)

    @app.post("/api/lung-plugin/xray/report")
    async def report(request: Request):
        try:
            guard(request, consent=True)
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "image/png":
                raise XrayError("invalid_xray")
            raw = await _body(request, MAX_BODY)
            if not raw.startswith(PNG):
                raise XrayError("invalid_xray")
            language = _draft_language(request.headers.get("accept-language", ""))
            return await run_in_threadpool(service.generate, raw, language)
        except Exception as exc:
            return failure(exc)

    app.router.add_event_handler("shutdown", service.close)
    return service
