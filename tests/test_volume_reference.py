"""Synthetic volume/editor identity tests; no models or patient data."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _source_paths import install_source_paths
install_source_paths(ROOT)
from lung_rt.plugin import Runtime
import radai_thumbnail
import SimpleITK as sitk


class VolumeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.runtime=object.__new__(Runtime)
        self.runtime.session_lock=threading.RLock()
        self.runtime.sessions={}
        self.signatures={}
        for name,size in (('selection-A',(6,7,8)),('report-lease-B',(9,10,11))):
            series={'pasta':str(Path(self.tmp.name)/name),'uid':'synthetic-'+name,'cortes':size[2]}
            self.runtime.sessions[name]={'series':series,'signature':'signature-'+name,'expires':time.time()+60}
            self.signatures[series['uid']]='signature-'+name
        @contextmanager
        def series_volume(series,signature):
            self.assertEqual(signature,self.signatures[series['uid']])
            size=(6,7,8) if series['uid'].endswith('A') else (9,10,11)
            image=sitk.Image(size,sitk.sitkFloat32)+17
            yield None,image,signature
        self.runtime.core=SimpleNamespace(_serie=series_volume,_inspecionar=lambda s:([],(),self.signatures[s['uid']]))

    def tearDown(self):self.tmp.cleanup()

    def test_metadata_ticket_uses_actual_report_volume_session(self):
        a=self.runtime.action({'action':'volume_meta','session':'selection-A'})
        b=self.runtime.action({'action':'volume_meta','session':'report-lease-B'})
        self.assertEqual(a['dims'],[6,7,8]);self.assertEqual(b['dims'],[9,10,11])
        self.assertNotEqual(a['reference_ticket'],b['reference_ticket'])
        actual=self.runtime.sessions['report-lease-B']['series']
        self.assertEqual(radai_thumbnail.resolver(b['reference_ticket']),(actual['pasta'],actual['uid']))
        self.assertNotIn(self.tmp.name,json.dumps(b))
        self.assertNotIn(actual['uid'],json.dumps(b))

    def test_cached_volume_does_not_issue_ticket_after_source_change(self):
        self.runtime.action({'action':'volume_meta','session':'report-lease-B'})
        self.signatures['synthetic-report-lease-B']='changed'
        with self.assertRaisesRegex(ValueError,'series_changed'):
            self.runtime.action({'action':'volume_meta','session':'report-lease-B'})

    def test_expired_selection_never_issues_ticket(self):
        self.runtime.sessions['selection-A']['expires']=time.time()-1
        with self.assertRaisesRegex(ValueError,'selection_expired'):
            self.runtime.action({'action':'volume_meta','session':'selection-A'})


if __name__=='__main__':unittest.main()
