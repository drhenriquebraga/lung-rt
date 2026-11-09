import math


def suggest(previous, current, max_distance_mm=20.0):
    """Rank candidates from measured geometry only; never register images or confirm identities."""
    if not previous.get("patient_key") or previous.get("patient_key")!=current.get("patient_key"):
        return []
    same_frame=bool(previous.get("frame_uid") and previous["frame_uid"]==current.get("frame_uid"))
    candidates=[]
    for a in previous.get("lesions",[]):
        for b in current.get("lesions",[]):
            common={"previous_lesion":a["id"],"current_lesion":b["id"],"status":"suggested","confirmed":False}
            pa,pb=a.get("centro_lps_mm"),b.get("centro_lps_mm")
            if same_frame and pa and pb and len(pa)==len(pb)==3:
                distance=math.dist(pa,pb)
                if math.isfinite(distance) and distance<=max_distance_mm:
                    candidates.append({**common,"distance_mm":round(distance,3),"method":"same-frame-geometric-proximity","rank":distance/max_distance_mm})
                continue
            # Different FrameOfReference: absolute positions are not comparable. Offer explicitly
            # ambiguous morphology candidates using measured native volumes and bounding extents.
            va,vb=a.get("volume_mm3"),b.get("volume_mm3")
            ea,eb=a.get("extensao_xyz_mm"),b.get("extensao_xyz_mm")
            if not all(isinstance(v,(float,int)) and math.isfinite(v) and v>0 for v in (va,vb)):
                continue
            if not ea or not eb or len(ea)!=3 or len(eb)!=3 or min(*ea,*eb)<=0: continue
            la,lb=a.get("lobo"),b.get("lobo")
            if la and lb and "indeterminado" not in (la,lb) and la!=lb: continue
            volume_ratio=vb/va
            shape_ratio=max(max(x/y,y/x) for x,y in zip(sorted(ea),sorted(eb)))
            if .25<=volume_ratio<=4 and shape_ratio<=2:
                candidates.append({**common,"distance_mm":None,"volume_ratio":round(volume_ratio,5),"method":"native-volume-shape-without-registration","ambiguous":True,"rank":abs(math.log(volume_ratio))+abs(math.log(shape_ratio))})
    return sorted(candidates,key=lambda c:c["rank"])
