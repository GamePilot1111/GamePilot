from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass
class Detection:
    x: int
    y: int
    width: int
    height: int
    confidence: float


@dataclass
class Motion:
    dx: float = 0.0
    dy: float = 0.0
    confidence: float = 0.0
    tracks: int = 0


def load_template(path: Path) -> np.ndarray | None:
    if not path.exists(): return None
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def match_template(frame: np.ndarray, templ: np.ndarray | None,
                   threshold: float = .8, max_results: int = 16,
                   scales: tuple[float, ...] = (.85, 1., 1.15)) -> list[Detection]:
    if templ is None or templ.size == 0: return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tplgray = cv2.cvtColor(templ, cv2.COLOR_BGR2GRAY)
    candidates: list[Detection] = []
    for scale in scales:
        w = round(tplgray.shape[1] * scale)
        h = round(tplgray.shape[0] * scale)
        if w < 9 or h < 9 or w > gray.shape[1] or h > gray.shape[0]: continue
        patch = cv2.resize(tplgray, (w, h), interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
        if float(patch.std()) < 7: continue
        heat = cv2.matchTemplate(gray, patch, cv2.TM_CCOEFF_NORMED)
        for _ in range(max_results):
            _, peak, _, xy = cv2.minMaxLoc(heat)
            if peak < threshold: break
            candidates.append(Detection(xy[0]+w//2, xy[1]+h//2, w, h, float(peak)))
            margin_x, margin_y = max(8,w//2), max(8,h//2)
            cv2.rectangle(heat, (max(0,xy[0]-margin_x),max(0,xy[1]-margin_y)),
                          (min(heat.shape[1]-1,xy[0]+margin_x),min(heat.shape[0]-1,xy[1]+margin_y)), -1, -1)
    candidates.sort(key=lambda d: d.confidence, reverse=True)
    selected = []
    for d in candidates:
        if not any((d.x-q.x)**2+(d.y-q.y)**2 < (min(d.width,q.width)*.7)**2 for q in selected):
            selected.append(d)
        if len(selected)>=max_results: break
    return selected


def estimate_camera_shift(prev: np.ndarray | None, frame: np.ndarray,
                          max_side: int = 800) -> Motion:
    if prev is None or prev.shape != frame.shape: return Motion()
    h,w = frame.shape[:2]
    ratio = min(1.0, max_side/max(h,w))
    new_size = (max(1,round(w*ratio)),max(1,round(h*ratio)))
    a = cv2.cvtColor(cv2.resize(prev,new_size),cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(frame,new_size),cv2.COLOR_BGR2GRAY)
    mask = np.full(a.shape, 255, dtype=np.uint8)
    # Suppress fixed HUD edges, center player and gathering bar from optical-flow matching.
    nh,nw = a.shape
    mask[:round(nh*.12),:] = 0
    mask[round(nh*.87):,:] = 0
    mask[:,:round(nw*.08)] = 0
    mask[:,round(nw*.92):] = 0
    cv2.circle(mask,(nw//2,round(nh*.52)),round(min(nh,nw)*.12),0,-1)
    corners = cv2.goodFeaturesToTrack(a, maxCorners=260, qualityLevel=.014,
                                     minDistance=10, mask=mask)
    if corners is None or len(corners)<12: return Motion()
    future, status, _ = cv2.calcOpticalFlowPyrLK(a,b,corners,None,
                          winSize=(23,23),maxLevel=3,
                          criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,25,.03))
    if future is None or status is None: return Motion()
    old=corners.reshape(-1,2)[status.ravel()==1]
    new=future.reshape(-1,2)[status.ravel()==1]
    if len(old)<10: return Motion()
    delta=new-old
    median=np.median(delta,axis=0)
    errors=np.linalg.norm(delta-median,axis=1)
    inliers=errors<max(2.,ratio*3.5)
    coherent=float(inliers.sum()/len(old))
    if inliers.sum()<9 or coherent<.35: return Motion(confidence=coherent, tracks=len(old))
    chosen=np.median(delta[inliers],axis=0)
    # Guard against a scene cut / minimap / teleport being treated as motion.
    full=chosen/ratio
    if np.linalg.norm(full)>max(h,w)*.12: return Motion(confidence=0,tracks=len(old))
    return Motion(float(full[0]),float(full[1]),coherent, len(old))


def resource_tooltip_present(frame: np.ndarray, tooltip_template: np.ndarray | None,
                             threshold: float = .77) -> bool:
    if tooltip_template is None: return False
    return bool(match_template(frame,tooltip_template,threshold,max_results=1,scales=(1.,)))


def verify_tooltip_ocr(frame: np.ndarray, names: list[str]) -> bool:
    """Optional OCR fallback. Tesseract executable + language packs are external."""
    try:
        import pytesseract
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        raw=pytesseract.image_to_string(rgb,config='--psm 11').lower()
        return any(s.lower() in raw for s in names if s)
    except Exception:
        return False


def progress_bar_visible(frame: np.ndarray, roi: tuple[int,int,int,int] | None) -> bool:
    """Image-based progress ROI heuristic: green filled pixels plus a dark rail.
    Calibrate ROI on an active gathering bar, never on the entire screen.
    """
    if roi is None: return False
    x,y,w,h=roi
    hframe,wframe=frame.shape[:2]
    x=max(0,min(wframe-1,x)); y=max(0,min(hframe-1,y))
    cut=frame[y:min(hframe,y+h),x:min(wframe,x+w)]
    if cut.size<120: return False
    hsv=cv2.cvtColor(cut,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([34,55,50]),np.array([94,255,255]))
    return float(np.count_nonzero(green))/green.size > .035
