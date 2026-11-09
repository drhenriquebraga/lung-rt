import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian, generate_uid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _source_paths import install_source_paths
install_source_paths(ROOT)
from lung_rt import xray


ORIGIN = "http://127.0.0.1:8765"
HEADERS = {"Origin": ORIGIN}
PREFIX = "/api/lung-plugin/xray"
DRAFT = json.dumps({"achados": "Amostra sintética", "impressao": "Teste local"}).encode()


def synthetic_png():
    pixels = np.arange(64, dtype=np.uint8).reshape(8, 8)
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "synthetic-metadata-to-strip")
    Image.fromarray(pixels).save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def synthetic_dicom(view="PA", body="CHEST", modality="DX"):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(None, {}, file_meta=meta, preamble=bytes(128))
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = modality
    ds.BodyPartExamined = body
    ds.ViewPosition = view
    ds.PatientName = "Synthetic^NotARealPatient"
    ds.Rows = 8
    ds.Columns = 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = np.arange(64, dtype="<u2").tobytes()
    output = BytesIO()
    pydicom.dcmwrite(output, ds, enforce_file_format=True)
    return output.getvalue()


class ImageTests(unittest.TestCase):
    def test_png_removes_metadata_preserving_pixels(self):
        original = synthetic_png()
        clean = xray.sanitize_image(original)
        with Image.open(BytesIO(clean)) as image:
            self.assertEqual(image.info, {})
            self.assertEqual(image.getpixel((7, 7)), 63)

    def test_accepts_single_dx_and_normalizes_monochrome_1(self):
        clean = xray.sanitize_image(synthetic_dicom())
        with Image.open(BytesIO(clean)) as image:
            self.assertEqual(image.size, (8, 8))
            self.assertEqual(image.info, {})
            self.assertGreater(image.getpixel((0, 0)), image.getpixel((7, 7)))

    def test_rejects_non_frontal_or_non_thoracic_dicom(self):
        for payload in (synthetic_dicom(view="LAT"), synthetic_dicom(body="HAND"), synthetic_dicom(modality="CT")):
            with self.subTest(), self.assertRaisesRegex(xray.XrayError, "unsupported_xray"):
                xray.sanitize_image(payload)

    def test_dimensions_checked_before_decoding(self):
        with patch.object(xray, "MAX_DIMENSION", 4), self.assertRaisesRegex(xray.XrayError, "image_dimensions_invalid"):
            xray.sanitize_image(synthetic_png())


class XrayApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lung-rx-test-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        plugin = base / "plugin"
        (plugin / "catalog").mkdir(parents=True)
        data = base / "data"
        data.mkdir()
        runtime_bytes = BytesIO()
        with zipfile.ZipFile(runtime_bytes, "w") as archive:
            archive.writestr(xray.EXECUTABLE, b"synthetic-executable")
            archive.writestr("ggml.dll", b"synthetic-library")
        self.payload = {"runtime.zip": runtime_bytes.getvalue(), "model.gguf": b"fake-model", "mmproj.gguf": b"fake-vision"}
        manifest = {
            "schema": "lung-rt/xray-resources/1",
            "model_id": "google/medgemma-1.5-4b-it",
            "display_name": "MedGemma 1.5 4B",
            "revision": "a" * 40,
        }
        for key, filename, host in (
            ("runtime", "runtime.zip", "github.com"),
            ("model", "model.gguf", "huggingface.co"),
            ("mmproj", "mmproj.gguf", "huggingface.co"),
        ):
            content = self.payload[filename]
            manifest[key] = {
                "filename": filename, "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(), "url": f"https://{host}/synthetic-test/{filename}",
            }
        (plugin / "catalog" / "xray_resources.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.accepted = True
        self.owners = []
        self.released = []

        def acquire(name):
            self.owners.append(name)
            return True

        host = SimpleNamespace(root=plugin, store=SimpleNamespace(directory=data), consent_valid=lambda: self.accepted,
                               acquire=acquire, release=self.released.append)
        app = FastAPI()
        self.service = xray.mount_xray_api(app, host)
        self.client = TestClient(app, base_url=ORIGIN)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        memory = patch.object(xray, "_windows_memory", return_value=(16 * xray.GIB, 8 * xray.GIB))
        memory.start()
        self.addCleanup(memory.stop)

    def fake_download(self, urls, destination, size, digest, progress, cancelled):
        raw = self.payload[destination.name]
        self.assertEqual(len(urls), 1)
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (size, digest))
        self.assertFalse(cancelled())
        destination.write_bytes(raw)
        progress({"downloaded_bytes": size})
        return destination

    def prepare_model(self):
        with patch.object(xray, "_download", side_effect=self.fake_download):
            response = self.client.post(PREFIX + "/prepare", json={"accept": True}, headers=HEADERS)
            self.assertEqual(response.status_code, 200, response.text)
            until = time.monotonic() + 3
            while self.service.status()["preparing"] and time.monotonic() < until:
                time.sleep(0.01)
        state = self.service.status()
        self.assertTrue(state["ready"], state)
        self.assertEqual(state["downloaded_bytes"], state["total_bytes"])

    def test_preview_works_without_model_and_all_posts_require_origin(self):
        self.assertFalse(self.client.get(PREFIX + "/status").json()["ready"])
        for operation in ("preview", "report", "prepare"):
            response = self.client.post(PREFIX + "/" + operation, content=synthetic_png(), headers={"Origin": "https://outside.invalid"})
            self.assertEqual((response.status_code, response.json()["error"]), (403, "invalid_origin"))
        preview = self.client.post(PREFIX + "/preview", content=synthetic_png(), headers=HEADERS)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.headers["content-type"], "image/png")
        self.assertEqual(preview.headers["cache-control"], "no-store")
        self.assertFalse(self.service.root.exists())

    def test_prepare_requires_base_consent_and_explicit_license(self):
        self.accepted = False
        response = self.client.post(PREFIX + "/prepare", json={"accept": True}, headers=HEADERS)
        self.assertEqual((response.status_code, response.json()["error"]), (403, "consent_required"))
        self.accepted = True
        response = self.client.post(PREFIX + "/prepare", json={"accept": 1}, headers=HEADERS)
        self.assertEqual((response.status_code, response.json()["error"]), (403, "license_required"))
        self.assertFalse(self.service.root.exists())

    def test_preview_enforces_stream_size_and_report_rejects_wrong_content(self):
        with patch.object(xray, "MAX_BODY", 32):
            response = self.client.post(PREFIX + "/preview", headers=HEADERS, content=iter([b"X" * 20, b"Y" * 20]))
        self.assertEqual((response.status_code, response.json()["error"]), (413, "request_too_large"))
        response = self.client.post(PREFIX + "/report", content=synthetic_dicom(), headers={**HEADERS, "Content-Type": "image/png"})
        self.assertEqual((response.status_code, response.json()["error"]), (400, "invalid_xray"))

    def test_generate_with_verified_resources_cleans_scratch_and_releases_queue(self):
        self.prepare_model()
        image_path = None

        def fake_process(args, **kwargs):
            nonlocal image_path
            image_path = Path(args[args.index("--image") + 1])
            self.assertTrue(image_path.is_file())
            self.assertTrue(Path(args[0]).is_file())
            self.assertIn("--offline", args)
            self.assertIn("--json-schema", args)
            self.assertNotIn("--simple-io", args)
            self.assertEqual(kwargs["cwd"], Path(args[0]).parent)
            self.assertFalse(any(key.startswith("LLAMA_ARG_") for key in kwargs["env"]))
            self.assertTrue(self.service.running)
            return SimpleNamespace(communicate=lambda timeout: (DRAFT, None), returncode=0)

        with patch.object(xray.subprocess, "Popen", side_effect=fake_process):
            response = self.client.post(PREFIX + "/report", content=synthetic_png(), headers={**HEADERS, "Content-Type": "image/png"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"text": "Achados\nAmostra sintética\n\nImpressão\nTeste local", "model": "MedGemma 1.5 4B"})
        self.assertFalse(image_path.exists())
        self.assertEqual(self.owners, ["lung-xray-report"])
        self.assertEqual(self.released, self.owners)
        self.assertEqual(set(p.name for p in self.service.root.iterdir()), {*self.payload, "license.json"})

    def test_hash_tamper_same_size_refuses_to_start_cli(self):
        self.prepare_model()
        (self.service.root / "model.gguf").write_bytes(b"X" * len(self.payload["model.gguf"]))
        with patch.object(xray.subprocess, "Popen") as process:
            response = self.client.post(PREFIX + "/report", content=synthetic_png(), headers={**HEADERS, "Content-Type": "image/png"})
            process.assert_not_called()
        self.assertEqual((response.status_code, response.json()["error"]), (503, "resources_invalid"))
        self.assertFalse(self.service.status()["ready"])
        self.assertEqual(self.released, self.owners)

    def test_timeout_kills_process_cleans_scratch_and_releases_queue(self):
        self.prepare_model()
        process = SimpleNamespace(returncode=None)
        calls = []
        process.kill = lambda: calls.append("kill")

        def communicate(timeout=None):
            calls.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired("synthetic-only", timeout)
            return b"", None

        process.communicate = communicate
        with patch.object(xray.subprocess, "Popen", return_value=process):
            response = self.client.post(PREFIX + "/report", content=synthetic_png(), headers={**HEADERS, "Content-Type": "image/png"})
        self.assertEqual((response.status_code, response.json()["error"]), (504, "report_timeout"))
        self.assertEqual(calls, [xray.REPORT_TIMEOUT, "kill", None])
        self.assertEqual(self.released, self.owners)
        self.assertFalse(any(p.is_dir() for p in self.service.root.iterdir()))


class RuntimeTests(unittest.TestCase):
    def test_runtime_rejects_traversal_and_symlink(self):
        symlink = zipfile.ZipInfo("lib.dll")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in ("../escape.dll", symlink):
            with tempfile.TemporaryDirectory(prefix="lung-rx-zip-test-") as t:
                root = Path(t)
                archive = root / "runtime.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr(xray.EXECUTABLE, b"fake")
                    z.writestr(extra, b"not a binary")
                with self.assertRaises(ValueError):
                    xray._extract_runtime(archive, root / "unpacked")
                self.assertFalse((root / "escape.dll").exists())

    def test_report_rejects_truncated_or_reasoning_output(self):
        for stdout in (b'{"achados":"x"', b'{"achados":"<think>test</think>","impressao":"z"}'):
            with self.assertRaisesRegex(xray.XrayError, "report_failed"):
                xray._report_text(stdout)


if __name__ == "__main__":
    unittest.main()
