from pathlib import Path
import hashlib, re, sys, tempfile, threading, time, unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _source_paths import install_source_paths
install_source_paths(ROOT)
from lung_rt.screening import Screening
from lung_rt.screening_images import _axis, frame, save_views
from lung_rt.store import Store
import radai_queue_state as queue
import numpy as np
from scipy.spatial.distance import pdist
from PIL import Image
import SimpleITK as sitk

class Cases(unittest.TestCase):
    def test_native_axial_edge_axis_and_thumbnail(self):
        rng=np.random.default_rng(117)
        for i in range(20):
            plane=rng.random((7,12))>.65
            y,x=np.nonzero(plane)
            corners=np.vstack([np.column_stack((x+a,y+b)) for a in (0,1) for b in (0,1)])*[.9,1.4]
            self.assertAlmostEqual(_axis(plane,[.9,1.4]),pdist(corners).max())
        with tempfile.TemporaryDirectory() as d:
            ident='a'*64
            volume=np.full((8,32,32),-600.,np.float32)
            mask=np.zeros(volume.shape,bool);mask[3:6,11:19,8:14]=True
            ref=sitk.GetImageFromArray(volume);ref.SetSpacing((.8,1.25,2.5))
            views=save_views(Path(d),ident,ref,mask)
            n=views['N001'];self.assertEqual([n['first_slice'],n['last_slice']],[3,5])
            self.assertAlmostEqual(n['long_axis_mm'],np.hypot(6*.8,8*1.25))
            rt=SimpleNamespace(store=SimpleNamespace(directory=Path(d)))
            pix=np.array(Image.open(frame(rt,ident,'N001',4)))
            self.assertTrue(np.any((pix[:,:,0]>180)&(pix[:,:,2]<120)))
            self.assertTrue(frame(rt,ident,'N001',small=True).exists())
            with self.assertRaises(ValueError): frame(rt,ident,'N001',2)
    def test_queue_turns(self):
        queue.rastreio_status('watching',0,0)
        card=next(c for c in queue.para_tela(queue.cards()) if c['id']=='lung-screening')
        self.assertFalse(any(card['acoes'].values()))
        for owner in ['vigia','lung-screening','vigia','lung-screening']:
            other=next(o for o in ['lung-screening','vigia'] if o!=owner)
            self.assertTrue(queue.tentar_a_vez(owner));self.assertFalse(queue.tentar_a_vez(other))
            queue.soltar_a_vez(owner);self.assertFalse(queue.tentar_a_vez(owner))
        queue.rastreio_status('stopped');self.assertFalse(any(c['id']=='lung-screening' for c in queue.cards()))
    def test_failure_or_stop_releases_gpu_to_watcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'store')
            def fail(*args, **kwargs):
                raise RuntimeError("synthetic failure")
            core=SimpleNamespace(pasta_valida=lambda p,c:p, varrer=lambda p,c:[
                dict(uid='failure',pasta=p,cortes=20)],_inspecionar=lambda s:([],[],'sig'),processar_serie=fail)
            def new():
                return Screening(store,core,{},None,lambda:queue.tentar_a_vez('lung-screening'),
                                 lambda:queue.soltar_a_vez('lung-screening'),queue.rastreio_status)
            worker=new();worker.start(tmp,interval=1)
            end=time.monotonic()+6
            while worker.state['failed']==0 and time.monotonic()<end:time.sleep(.03)
            self.assertEqual(worker.state['failed'],1)
            self.assertTrue(queue.tentar_a_vez('vigia'))
            worker.cancel();worker.thread.join(3)
            try:
                worker.start(tmp,interval=1)
                end=time.monotonic()+5
                while worker.state['stage']!='waiting' and time.monotonic()<end:time.sleep(.03)
                self.assertEqual(worker.state['stage'],'waiting')
                worker.cancel();worker.thread.join(3)
            finally:
                queue.soltar_a_vez('vigia')
            self.assertTrue(queue.tentar_a_vez('vigia'))
            queue.soltar_a_vez('vigia')

    def test_folders_dedup_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/n for n in ('first','second')];[p.mkdir() for p in paths]
            store=Store(Path(tmp)/'store')
            seen=[]
            def process(s,c,esperado):
                seen.append(s['uid'])
                return dict(estado='vazio',paciente_chave='p',frame_uid='f',lesoes=[])
            core=SimpleNamespace(pasta_valida=lambda p,c:str(Path(p).resolve()),varrer=lambda p,c:[dict(uid=Path(p).name,pasta=p,cortes=20)],_inspecionar=lambda s:([],[],'sig'),processar_serie=process)
            def new():return Screening(store,core,{},None,lambda:True,lambda:None)
            service=new();service.start(list(map(str,paths))+[str(paths[0])],interval=1)
            end=time.monotonic()+6
            while len(store.list('cases'))<2 and time.monotonic()<end:time.sleep(.05)
            self.assertEqual(seen,['first','second']);service.cancel(shutdown=True);service.thread.join(3)
            self.assertTrue(service.options()['enabled'])
            other=new();other._launch(other.options(),1);time.sleep(2.2);other.cancel();other.thread.join(3)
            self.assertCountEqual(seen,['first','second']);self.assertFalse(other.options()['enabled'])
if __name__=='__main__':unittest.main(verbosity=2)
