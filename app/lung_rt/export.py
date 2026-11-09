import base64
import copy
from datetime import datetime
import hashlib
from pathlib import Path
import uuid


def pdf_from_pages(pages):
    if not isinstance(pages,list) or not 1 <= len(pages) <= 40:
        raise ValueError("invalid_pdf_pages")
    objects = []
    def add(data):
        objects.append(data if isinstance(data,bytes) else data.encode("ascii"))
        return len(objects)
    add("<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")
    kids = []
    for page in pages:
        image = base64.b64decode(page["jpeg"],validate=True)
        width,height = int(page["width"]),int(page["height"])
        if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9") or len(image)>6*1024*1024 or (width,height)!=(794,1123):
            raise ValueError("invalid_pdf_page")
        img = add((f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(image)} >>\nstream\n").encode()+image+b"\nendstream")
        stream = b"q 595.28 0 0 841.89 0 0 cm /Im0 Do Q"
        content = add(f"<< /Length {len(stream)} >>\nstream\n".encode()+stream+b"\nendstream")
        pg = add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /XObject << /Im0 {img} 0 R >> >> /Contents {content} 0 R >>")
        kids.append(pg)
    objects[1] = ("<< /Type /Pages /Kids [" + " ".join(f"{n} 0 R" for n in kids) + f"] /Count {len(kids)} >>").encode()
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data)); data.extend(f"{i} 0 obj\n".encode()+obj+b"\nendobj\n")
    start=len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(data)


def export_draft(reference, directory, report, pages):
    import pydicom
    from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    if report.get("state") != "exporting" or report.get("source") != "nv-reason-ct-local":
        raise ValueError("draft_not_exportable")
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("series_folder_unavailable")
    pdf = pdf_from_pages(pages)
    now = datetime.now()
    study = str(reference.StudyInstanceUID)
    frame = str(reference.get("FrameOfReferenceUID",""))
    own_series = generate_uid()
    def dataset(sop):
        meta=FileMetaDataset(); meta.MediaStorageSOPClassUID=sop;meta.MediaStorageSOPInstanceUID=generate_uid();meta.TransferSyntaxUID=ExplicitVRLittleEndian
        ds=FileDataset(None,{},file_meta=meta,preamble=b"\0"*128)
        ds.SOPClassUID=sop;ds.SOPInstanceUID=meta.MediaStorageSOPInstanceUID
        for keyword in ("PatientName","PatientID","IssuerOfPatientID","PatientBirthDate","PatientSex","StudyDate","StudyTime","AccessionNumber","StudyID","ReferringPhysicianName"):
            setattr(ds,keyword,copy.deepcopy(reference.get(keyword,"")))
        ds.SpecificCharacterSet="ISO_IR 192";ds.StudyInstanceUID=study;ds.SeriesInstanceUID=own_series
        if frame: ds.FrameOfReferenceUID=frame
        ds.SeriesNumber=990;ds.InstanceNumber=1;ds.Manufacturer="Radioterapia.AI";ds.ManufacturerModelName="LUNG RT"
        ds.SoftwareVersions="1.0.0";ds.SeriesDescription="LUNG RT - UNVERIFIED DRAFT"
        ds.ContentDate=now.strftime("%Y%m%d");ds.ContentTime=now.strftime("%H%M%S.%f")
        ds.InstanceCreationDate=ds.ContentDate;ds.InstanceCreationTime=ds.ContentTime
        source=Dataset();source.ReferencedSOPClassUID=reference.SOPClassUID;source.ReferencedSOPInstanceUID=reference.SOPInstanceUID
        ds.SourceInstanceSequence=Sequence([source])
        return ds
    def code(value,scheme,meaning):
        d=Dataset();d.CodeValue=value;d.CodingSchemeDesignator=scheme;d.CodeMeaning=meaning;return d
    enc=dataset("1.2.840.10008.5.1.4.1.1.104.1")
    enc.Modality="DOC";enc.ConversionType="WSD";enc.MIMETypeOfEncapsulatedDocument="application/pdf"
    enc.DocumentTitle="RASCUNHO NAO VERIFICADO / UNVERIFIED DRAFT"
    enc.BurnedInAnnotation="YES";enc.EncapsulatedDocument=pdf;enc.EncapsulatedDocumentLength=len(pdf)
    enc.AcquisitionDateTime="";enc.ConceptNameCodeSequence=Sequence([code("18748-4","LN","Diagnostic imaging study")])
    sr=dataset("1.2.840.10008.5.1.4.1.1.88.11")
    sr.Modality="SR";sr.InstanceNumber=2;sr.ValueType="CONTAINER";sr.ContinuityOfContent="SEPARATE"
    sr.CompletionFlag="COMPLETE";sr.CompletionFlagDescription="Complete experimental draft; not medically verified"
    sr.VerificationFlag="UNVERIFIED";sr.PreliminaryFlag="PRELIMINARY"
    sr.ConceptNameCodeSequence=Sequence([code("18748-4","LN","Diagnostic imaging study")])
    item=Dataset();item.RelationshipType="CONTAINS";item.ValueType="TEXT"
    item.ConceptNameCodeSequence=Sequence([code("121106","DCM","Comment")])
    item.TextValue="RASCUNHO NAO VERIFICADO / UNVERIFIED DRAFT\n"+report["display_text"]
    sr.ContentSequence=Sequence([item])
    study_ref=Dataset();study_ref.StudyInstanceUID=study
    series_ref=Dataset();series_ref.SeriesInstanceUID=reference.SeriesInstanceUID
    sop_ref=Dataset();sop_ref.ReferencedSOPClassUID=reference.SOPClassUID;sop_ref.ReferencedSOPInstanceUID=reference.SOPInstanceUID
    series_ref.ReferencedSOPSequence=Sequence([sop_ref]);study_ref.ReferencedSeriesSequence=Sequence([series_ref])
    sr.CurrentRequestedProcedureEvidenceSequence=Sequence([study_ref])
    sr.ReferencedPerformedProcedureStepSequence=Sequence([])
    outputs=[]
    for tag,obj in (("PDF",enc),("SR",sr)):
        name="LUNG_DRAFT_"+report["id"]+"_"+tag+"_"+uuid.uuid4().hex[:8]+".dcm"
        path=directory/name
        with path.open("xb") as handle:
            pydicom.dcmwrite(handle,obj,enforce_file_format=True)
        check=pydicom.dcmread(path,stop_before_pixels=True)
        if str(check.SOPInstanceUID)!=str(obj.SOPInstanceUID):
            raise RuntimeError("export_integrity_failed")
        outputs.append({"name":name,"sop_instance_uid":str(obj.SOPInstanceUID),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"size":path.stat().st_size})
    return outputs
