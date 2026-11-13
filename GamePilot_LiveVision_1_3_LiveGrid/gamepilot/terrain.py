"""Opt-in colour-calibrated obstacle survey.

No terrain classification is made without a user-taught reference.  A patch of
water/rock can have visual lookalikes: observations are accumulated, not treated
as physical truth.  The map editor can correct mistaken labels.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import cv2
import numpy as np


@dataclass
class TerrainProfile:
    name: str
    hue: float
    saturation: float
    value: float
    hue_tolerance: float = 11.
    saturation_tolerance: float = 57.
    value_tolerance: float = 66.
    enabled: bool = True

    @classmethod
    def learn(cls, name: str, bgr: np.ndarray) -> 'TerrainProfile':
        if bgr is None or bgr.size == 0 or min(bgr.shape[:2]) < 8:
            raise ValueError('Reference patch must be at least 8x8 pixels')
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        flat = hsv.reshape(-1, 3).astype(float)
        sat = np.median(flat[:, 1])
        val = np.median(flat[:, 2])
        # Hue is unstable when saturation is low; these profiles are not usable.
        if sat < 28 or val < 35:
            raise ValueError('Patch is too dark or desaturated for colour recognition')
        angles = flat[:, 0] * (2*np.pi/180)
        z = np.mean(np.exp(1j*angles))
        hue = float((np.angle(z) % (2*np.pi)) * 180 / (2*np.pi))
        concentration = float(abs(z))
        if concentration < .73:
            raise ValueError('Select a more uniform colour patch')
        return cls(name, hue, float(sat), float(val))

    def mask(self, hsv: np.ndarray) -> np.ndarray:
        h = hsv[:,:,0].astype(np.float32)
        s = hsv[:,:,1].astype(np.float32)
        v = hsv[:,:,2].astype(np.float32)
        dist = np.abs(h-self.hue)
        dist = np.minimum(dist, 180-dist)
        return ((dist <= self.hue_tolerance) &
                (np.abs(s-self.saturation) <= self.saturation_tolerance) &
                (np.abs(v-self.value) <= self.value_tolerance)).astype(np.uint8)


class TerrainSurvey:
    def __init__(self, profiles: list[TerrainProfile] | None = None):
        self.profiles = profiles or []
        self.evidence: dict[tuple[int,int], tuple[int,int]] = {}
        self.confirmations = 3
        self.minimum_fraction = .78
        self.max_sampled_cells = 100

    def learn(self, name: str, patch: np.ndarray):
        profile = TerrainProfile.learn(name, patch)
        self.profiles = [p for p in self.profiles if p.name != name]+[profile]
        self.evidence.clear()
        return profile

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps([asdict(p) for p in self.profiles],ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path):
        try:
            return cls([TerrainProfile(**p) for p in json.loads(path.read_text(encoding='utf-8'))])
        except (OSError,ValueError,TypeError,KeyError):
            return cls()

    def scan(self, frame: np.ndarray, world, cfg) -> int:
        """Survey confidently matched colour cells away from character and HUD.

        Only accumulate blocked evidence. Never automatically unblock a cell.
        One scan can add at most max_sampled_cells; repeat independent frames
        required to confirm. A learned profile is needed for ANY classification.
        """
        if not any(p.enabled for p in self.profiles):
            return 0
        height,width=frame.shape[:2]
        hsv=cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask=np.zeros((height,width),dtype=np.uint8)
        for profile in self.profiles:
            if profile.enabled:
                mask |= profile.mask(hsv)
        # Screen-space sampling intentionally coarse and away from HUD.
        stride=max(20,min(64,round(cfg.cell_px*.55)))
        player_sx=width*cfg.player_x_ratio
        player_sy=height*cfg.player_y_ratio
        seen=set()
        confirmed=0
        for sy in range(int(height*.16),int(height*.79),stride):
            for sx in range(int(width*.1),int(width*.9),stride):
                if len(seen)>=self.max_sampled_cells:
                    return confirmed
                if abs(sx-player_sx)<85 and abs(sy-player_sy)<85:
                    continue
                x1=max(0,sx-stride//4); x2=min(width,sx+stride//4)
                y1=max(0,sy-stride//4); y2=min(height,sy+stride//4)
                if float(np.mean(mask[y1:y2,x1:x2]))<self.minimum_fraction:
                    continue
                wx=world.player_x+sx-player_sx
                wy=world.player_y+sy-player_sy
                cell=world.cell(wx,wy)
                if cell in seen or cell in world.visited or cell==world.cell(world.player_x,world.player_y):
                    continue
                seen.add(cell)
                n,last_step=self.evidence.get(cell,(0,-999))
                if last_step==world.step:
                    continue
                n+=1
                self.evidence[cell]=(n,world.step)
                if n>=self.confirmations and cell not in world.blocked:
                    world.blocked.add(cell)
                    confirmed+=1
        # Keep bounded on long sessions.
        if len(self.evidence)>12000:
            self.evidence={c:v for c,v in self.evidence.items() if v[0]>=self.confirmations}
        return confirmed

class ExitSurvey:
    """Conservative trained-exit detection; four matches before marking a portal.

    A portal template is an appearance cue only: repetitive textures can still
    yield false positives. The operator can disable this scanner or erase marks.
    """
    def __init__(self, confirmations: int = 4):
        self.confirmations=confirmations
        self.evidence: dict[tuple[int,int],int]={}

    def scan(self, detections, world, width: int, height: int, cfg) -> int:
        added=0
        for d in detections:
            # Ignore HUD, player center and unreliable edge matches.
            if d.x<width*.08 or d.x>width*.92 or d.y<height*.12 or d.y>height*.87:
                continue
            if abs(d.x-width*cfg.player_x_ratio)<60 and abs(d.y-height*cfg.player_y_ratio)<60:
                continue
            wx=world.player_x+d.x-width*cfg.player_x_ratio
            wy=world.player_y+d.y-height*cfg.player_y_ratio
            c=world.cell(wx,wy)
            if c in world.exits:
                continue
            # Evidence is counted per nearby map cell rather than exact pixels.
            n=self.evidence.get(c,0)+1
            self.evidence[c]=n
            if n>=self.confirmations:
                world.set_exit(wx,wy)
                self.evidence.pop(c,None)
                added+=1
        if len(self.evidence)>3000:
            self.evidence.clear()
        return added
