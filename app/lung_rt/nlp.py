import hashlib
import re


def extract_own_draft(text, *, source, report_id):
    if source != "nv-reason-ct-local" or not report_id or not isinstance(text,str):
        raise ValueError("nlp_own_draft_only")
    if not text.strip() or len(text)>120000:
        raise ValueError("invalid_draft")
    # Extract headings and literal spans only. Generated measurements are never promoted to native geometry.
    sections = []
    heading = "text"
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(?:#{1,4}\s+|[A-Za-z][A-Za-z /-]{2,60}:\s*$)",line):
            if lines:
                sections.append({"heading":heading,"text":"\n".join(lines).strip()})
            heading = line.strip().lstrip("#").strip().rstrip(":")
            lines = []
        else:
            lines.append(line)
    if lines:
        sections.append({"heading":heading,"text":"\n".join(lines).strip()})
    return {"schema":"lung-rt/draft-extraction/1","report_id":report_id,
            "source":source,"text_sha256":hashlib.sha256(text.encode()).hexdigest(),
            "sections":sections,"measurements_verified":False}
