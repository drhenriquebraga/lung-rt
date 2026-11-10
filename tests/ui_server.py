"""Isolated synthetic UI harness; does not invoke segmentation or inference."""
from pathlib import Path
import atexit
import json
import os
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _source_paths import install_source_paths
HOST,CONTOUR=install_source_paths(ROOT)
from fastapi import FastAPI
from lung_rt.plugin import mount
import radai_ui
import radai_menu
from contextlib import contextmanager
class Core:
    def pasta_valida(self,value,cfg=None):return value
    def _inspecionar(self,s):return [],(),"synthetic-signature"
    @contextmanager
    def _serie(self,s,expected=None):
        import numpy as np
        import SimpleITK as sitk
        arr=np.full((12,24,24),-1000,dtype=np.int16);arr[:,4:20,4:20]=50
        yield None,sitk.GetImageFromArray(arr),"synthetic-signature"
    def varrer(self,pasta,cfg):return []
app=FastAPI()
tmp=tempfile.TemporaryDirectory(prefix="lung-ui-synthetic-");atexit.register(tmp.cleanup)
policy=json.loads((ROOT/"catalog/consent.json").read_text(encoding="utf-8"))
consent=Path(tmp.name)/"consent.json";consent.write_text(json.dumps({"accepted":True,"version":policy["version"],"digest":policy["digest"]}))
services={"consent_path":str(consent),"plugin_root":str(ROOT),"data_dir":str(Path(tmp.name)/"data"),"core":Core(),"hardware":lambda:{"total_bytes":5*1000**3},"resolve_series":lambda s:{"uid":"synthetic","pasta":tmp.name,"cortes":12,"desc":"SYNTHETIC TEST ONLY"},"ui_apply":lambda page,active:radai_menu.aplicar(radai_ui.com_portao(page),active),"acquire_gpu":lambda name:True,"release_gpu":lambda name:None}
runtime=mount(app,services)
@app.get('/health')
def health():return {"synthetic_only":True}
if __name__=="__main__":
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get("LUNG_RT_TEST_PORT","18747")),log_level='warning')
