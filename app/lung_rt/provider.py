import hashlib
import json
from pathlib import Path
import subprocess
import threading


class LocalProvider:
    def __init__(self, plugin_root, model_root, hardware=None, resources_dir=None):
        self.root = Path(plugin_root)
        self.models = Path(model_root).resolve()
        self.manifest = json.loads((self.root / "catalog/models.json").read_text(encoding="utf-8-sig"))
        self.runtime_dir=Path(resources_dir or self.root/"web/vendor/nvreason/vendor/ort").resolve()
        self.hardware = hardware or self.detect_gpu
        self.verified = {}
        self.lock = threading.RLock()

    @staticmethod
    def detect_gpu():
        try:
            run = subprocess.run(["nvidia-smi","--query-gpu=index,memory.total,memory.free","--format=csv,noheader,nounits"],
                capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),check=True)
            cards = []
            for row in run.stdout.splitlines():
                index,total,free = [float(x.strip()) for x in row.split(",")]
                cards.append({"index":int(index),"total_bytes":int(total*1024**2),"free_bytes":int(free*1024**2)})
            return max(cards,key=lambda d:d["total_bytes"]) if cards else {}
        except (OSError,ValueError,subprocess.SubprocessError):
            return {}

    def path(self, name):
        if name not in {f["path"] for f in self.manifest["files"]}:
            raise ValueError("invalid_model_resource")
        path = (self.models / name).resolve()
        if self.models not in path.parents or path.is_symlink():
            raise ValueError("invalid_model_resource")
        return path

    def runtime_file(self,name,verify=False):
        recipe_path=self.root/"catalog/resource_recipe.json"
        if not recipe_path.exists():
            raise ValueError("runtime_not_prepared")
        recipe=json.loads(recipe_path.read_text(encoding="utf-8"))
        spec=next((entry for entry in recipe["files"] if entry["path"]=="runtimes/nvreason/"+name),None)
        if not spec: raise ValueError("invalid_resource")
        path=(self.runtime_dir/name).resolve()
        if self.runtime_dir not in path.parents or path.stat().st_size!=spec["size"]:
            raise ValueError("runtime_not_prepared")
        if verify:
            digest=hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda:stream.read(4*1024**2),b""): digest.update(block)
            if digest.hexdigest()!=spec["sha256"]: raise ValueError("runtime_hash_mismatch")
        return path

    def resources(self, verify=False, force=False):
        problems = []
        with self.lock:
            for entry in self.manifest["files"]:
                path = self.path(entry["path"])
                try:
                    stat = path.stat()
                    if stat.st_size != entry["size"]:
                        problems.append({"file":entry["path"],"state":"size_mismatch"})
                        continue
                    stamp = (stat.st_size,stat.st_mtime_ns)
                    if verify and (force or self.verified.get(entry["path"]) != stamp):
                        digest = hashlib.sha256()
                        with path.open("rb") as handle:
                            for block in iter(lambda:handle.read(4*1024*1024),b""):
                                digest.update(block)
                        if digest.hexdigest() != entry["sha256"]:
                            problems.append({"file":entry["path"],"state":"hash_mismatch"})
                            continue
                        self.verified[entry["path"]] = stamp
                except OSError:
                    problems.append({"file":entry["path"],"state":"missing"})
        return {"ready":not problems,"verified":verify and not problems,"problems":problems,
                "bytes":sum(f["size"] for f in self.manifest["files"]),"revision":self.manifest["revision"]}

    def assets_ready(self):
        if not self.resources(verify=False)['ready']:return False
        for name in ('ort-wasm-simd-threaded.asyncify.mjs','ort-wasm-simd-threaded.asyncify.wasm'):
            try:self.runtime_file(name,verify=False)
            except (OSError,ValueError):return False
        return True

    def preflight(self, verify=True):
        gpu = self.hardware()
        minimum = self.manifest["minimum_gpu_gb"] * 1000**3
        errors = []
        if not gpu.get("total_bytes"):
            errors.append("gpu_capacity_unverified")
        elif gpu["total_bytes"] < minimum:
            errors.append("gpu_below_6gb")
        resources = self.resources(verify=verify and not errors,force=verify)
        if not resources["ready"]:
            errors.append("model_not_prepared")
        if (self.root/"catalog/resource_recipe.json").is_file():
            for name in ("ort-wasm-simd-threaded.asyncify.mjs","ort-wasm-simd-threaded.asyncify.wasm"):
                try: self.runtime_file(name,verify=verify and not errors)
                except (OSError,ValueError):
                    errors.append("runtime_not_prepared")
                    break
        return {"available":not errors,"errors":errors,"gpu":gpu,"resources":resources,
                "experimental":True,"provider":"nv-reason-ct-local","cpu_fallback":False,
                "max_seconds":3600,"requires_webgpu":True}
