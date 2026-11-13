from __future__ import annotations
import collections
import math
import threading
import time
from pathlib import Path
import cv2
import numpy as np
import mss
from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtGui import QImage

from .config import Settings, app_home
from .mapping import WorldMap
from .vision import (load_template, match_template, estimate_camera_shift,
                     resource_tooltip_present, verify_tooltip_ocr, progress_bar_visible)
from .controller import Brain, InputBridge, Observation, Mode
from .terrain import TerrainSurvey, ExitSurvey


class CaptureWorker(QThread):
    image = Signal(QImage)
    error = Signal(str)
    capture_info = Signal(int,int,int,int)
    def __init__(self, shared:'SharedFrames', cfg:Settings):
        super().__init__()
        self.shared,self.cfg=shared,cfg
        self.running=True
        self.preview_interval=0.12

    def run(self):
        try:
            with mss.mss() as screen:
                monitors=screen.monitors
                if self.cfg.monitor_index<1 or self.cfg.monitor_index>=len(monitors):
                    raise RuntimeError('Монітор не знайдено')
                mon=monitors[self.cfg.monitor_index]
                w,h=mon['width'],mon['height']
                self.capture_info.emit(mon['left'],mon['top'],w,h)
                last_display=0.0
                while self.running:
                    started=time.monotonic()
                    raw=np.asarray(screen.grab(mon))
                    bgr=np.ascontiguousarray(raw[:,:,:3])
                    self.shared.push(bgr)
                    if started-last_display >= self.preview_interval:
                        factor=min(1.,self.cfg.max_preview_width/max(1,w))
                        if factor<1:
                            display=cv2.resize(bgr,(int(w*factor),int(h*factor)),interpolation=cv2.INTER_AREA)
                        else: display=bgr
                        rgb=cv2.cvtColor(display,cv2.COLOR_BGR2RGB)
                        hh,ww=rgb.shape[:2]
                        self.image.emit(QImage(rgb.data,ww,hh,ww*3,QImage.Format.Format_RGB888).copy())
                        last_display=started
                    sleep=max(0.,1.0/max(1,self.cfg.capture_fps)-(time.monotonic()-started))
                    if sleep: time.sleep(sleep)
        except Exception as exc:
            self.error.emit(f'Помилка захоплення: {exc}')
        finally:
            self.running=False

    def stop(self):
        self.running=False


class SharedFrames:
    def __init__(self):
        self.cv=threading.Condition()
        self.frame:np.ndarray|None=None
        self.seq=0
        self.closed=False
    def push(self,frame:np.ndarray):
        with self.cv:
            self.frame=frame
            self.seq+=1
            self.cv.notify()
    def pop(self,last_seq:int,timeout:float=.6):
        with self.cv:
            self.cv.wait_for(lambda:self.seq>last_seq or self.closed,timeout=timeout)
            return self.frame,self.seq
    def stop(self):
        with self.cv:
            self.closed=True
            self.cv.notify_all()


class Runtime(QObject):
    status=Signal(str)
    stats=Signal(str)
    map_changed=Signal()
    recognition=Signal(object)
    def __init__(self,cfg:Settings,world:WorldMap):
        super().__init__()
        self.cfg,self.map=cfg,world
        self.bridge=InputBridge()
        self.bridge.point_allowed=self._point_allowed
        self.bridge.window_title_contains=cfg.window_title_contains
        self.bridge.click_limit=cfg.max_automatic_clicks
        self.survey=TerrainSurvey.load(app_home()/'terrain_profiles.json')
        self.exit_survey=ExitSurvey()
        self.terrain_new_cells=0
        self.brain=Brain(cfg,world,self.bridge,self.status.emit)
        self.frames=SharedFrames()
        self.capture=CaptureWorker(self.frames,cfg)
        self.capture.capture_info.connect(self.bridge.configure_monitor)
        self.capture.error.connect(self._error)
        self.thread:threading.Thread|None=None
        self.running=False
        self.templates=app_home()/'templates'
        self.templates.mkdir(exist_ok=True)
        self.resource_template=load_template(self.templates/'stone_t1.png')
        self.depleted_template=load_template(self.templates/'stone_t1_depleted.png')
        self.tooltip_template=load_template(self.templates/'tooltip_t1.png')
        self.exit_template=load_template(self.templates/'exit.png')
        self.progress_roi:tuple[int,int,int,int]|None=None
        self.roi_file=app_home()/'progress_roi.txt'
        if self.roi_file.exists():
            try: self.progress_roi=tuple(map(int,self.roi_file.read_text().split(',')))
            except (ValueError,OSError):pass
        self.latest_frame:np.ndarray|None=None
        self.last_detections=[]
        self._last_map_save=0.0
        self._last_recognition=0.0
        self.teacher_active=bool(cfg.guided_mode)
        self._processing_fps=0.0

    def mark_taught(self, kind: str, screen_x: float, screen_y: float) -> str:
        """Invoked only while stationary/teaching, never by automated vision."""
        if not self.cfg.guided_mode or self.brain.mode != Mode.IDLE:
            raise ValueError('Pause automation and enable guided mode before marking')
        w,h=self.bridge.monitor_size
        if w<=0 or h<=0: raise ValueError('Screen capture is not yet configured')
        if self.map.uncertainty > self.cfg.max_position_uncertainty_px*.75:
            raise ValueError('Position uncertainty too high; return to base and relocalize')
        if kind=='stone':
            r=self.map.teach_resource(screen_x,screen_y,w,h,
                                     self.cfg.player_x_ratio,self.cfg.player_y_ratio)
            msg=f'Підтверджено вручну T1 #{r.id} у ({r.x:.0f},{r.y:.0f})'
        else:
            cell=self.map.teach_marker(kind,screen_x,screen_y,w,h,
                                      self.cfg.player_x_ratio,self.cfg.player_y_ratio)
            msg=f'Позначено {kind}: клітинка {cell}'
        self.save_map()
        self.map_changed.emit()
        return msg

    def _point_allowed(self, screen_x:float, screen_y:float) -> bool:
        """Hard deny-list on every click; exits are never clickable if marked."""
        w,h=self.bridge.monitor_size
        wx=self.map.player_x+screen_x-w*self.cfg.player_x_ratio
        wy=self.map.player_y+screen_y-h*self.cfg.player_y_ratio
        origin=(self.map.player_x,self.map.player_y)
        destination=(wx,wy)
        if not self.map.line_passable(origin,destination): return False
        if not self.cfg.guided_mode: return True
        if self.map.line_taught_passable(origin,destination): return True
        # Only the last interaction with a manually taught resource may point
        # outside the demonstrated walking corridor. It must be very close.
        return (math.dist(origin,destination)<=self.map.cell_px*1.2 and
                any(r.verified and math.dist((r.x,r.y),destination)<self.map.cell_px*.38
                    for r in self.map.resources.values()))

    def _error(self,s:str):
        self.brain.pause(s)
        self.status.emit(s)

    def set_template(self,kind:str,roi:tuple[int,int,int,int]) -> bool:
        frame=self.latest_frame
        if frame is None:return False
        x,y,w,h=map(int,roi)
        x=max(0,x);y=max(0,y)
        h0,w0=frame.shape[:2]
        w=min(w,w0-x);h=min(h,h0-y)
        if w<12 or h<9:return False
        if kind in ('water','rock'):
            try:
                profile=self.survey.learn(kind,frame[y:y+h,x:x+w])
                self.survey.save(app_home()/'terrain_profiles.json')
                self.status.emit(f'Навчено {kind}: колір HSV {profile.hue:.0f}/{profile.saturation:.0f}/{profile.value:.0f}')
                return True
            except ValueError as exc:
                self.status.emit(f'Не вдалося навчити тип місцевості: {exc}')
                return False
        if kind=='progress':
            self.progress_roi=(x,y,w,h)
            self.roi_file.write_text(','.join(map(str,self.progress_roi)),encoding='utf-8')
            self.status.emit('Область прогрес-бару збережена')
            return True
        path=self.templates/({'stone':'stone_t1.png','depleted':'stone_t1_depleted.png','tooltip':'tooltip_t1.png','exit':'exit.png'}.get(kind,'unknown.png'))
        cv2.imwrite(str(path),frame[y:y+h,x:x+w])
        if kind=='stone': self.resource_template=load_template(path)
        elif kind=='depleted': self.depleted_template=load_template(path)
        elif kind=='exit': self.exit_template=load_template(path)
        else: self.tooltip_template=load_template(path)
        self.status.emit(f'Шаблон {kind} збережено: {path}')
        return True

    def start(self):
        if self.running:return
        self.running=True
        self.capture.start()
        self.thread=threading.Thread(target=self._process,name='GamePilotVision',daemon=True)
        self.thread.start()

    def stop(self):
        self.running=False
        self.brain.pause('Зупинено')
        self.frames.stop()
        self.capture.stop()
        self.capture.wait(2500)
        if self.thread:self.thread.join(timeout=2.5)
        self.save_map()

    def save_map(self):
        try:
            self.map.save(app_home()/'map.json')
            self._last_map_save=time.monotonic()
        except Exception as exc:
            self.status.emit(f'Не вдалося зберегти карту: {exc}')

    def _process(self):
        seq=0
        previous=None
        previous_time=time.monotonic()
        lastmap=0.0
        while self.running:
            frame,seq_new=self.frames.pop(seq)
            if frame is None or seq_new==seq:continue
            seq=seq_new
            # Only the newest frame is kept; image capture is not blocked by recognition.
            self.latest_frame=frame
            started=time.monotonic()
            motion=estimate_camera_shift(previous,frame)
            previous=frame
            # Track manual walking too: observing the player at a new position
            # without odometry would contaminate the saved map.
            if motion.confidence>=self.cfg.min_motion_confidence:
                before=(self.map.player_x,self.map.player_y)
                self.map.update_motion(motion.dx,motion.dy,motion.confidence)
                if self.cfg.guided_mode and self.brain.mode==Mode.IDLE:
                    self.map.mark_walked_segment(before,(self.map.player_x,self.map.player_y))
            elif motion.tracks>0:
                self.map.uncertainty+=.8
            if self.cfg.enable_terrain_survey and self.survey.profiles and self.map.uncertainty < self.cfg.max_position_uncertainty_px*.8:
                self.terrain_new_cells+=self.survey.scan(frame,self.map,self.cfg)
            if self.cfg.enable_exit_survey and self.exit_template is not None and self.map.uncertainty < self.cfg.max_position_uncertainty_px*.65:
                portals=match_template(frame,self.exit_template,max(.91,self.cfg.confidence),max_results=8,scales=(1.,))
                found_exits=self.exit_survey.scan(portals,self.map,frame.shape[1],frame.shape[0],self.cfg)
                if found_exits:
                    self.status.emit(f'Позначено {found_exits} можливих виходів. Перевірте їх на карті.')
            det=match_template(frame,self.resource_template,self.cfg.confidence) if self.resource_template is not None else []
            self.last_detections=det
            self.map.relocalize([(d.x,d.y) for d in det],frame.shape[1],frame.shape[0],
                                self.cfg.player_x_ratio,self.cfg.player_y_ratio)
            for d in ([] if self.cfg.guided_mode else det):
                self.map.add_observation(d.x,d.y,frame.shape[1],frame.shape[0],
                         self.cfg.player_x_ratio,self.cfg.player_y_ratio)
            verified=False
            if self.brain.mode==Mode.VERIFY and started-self.bridge.last_hover>=self.cfg.hover_settle_seconds:
                verified=resource_tooltip_present(frame,self.tooltip_template,self.cfg.tooltip_confidence)
                if not verified and self.tooltip_template is None:
                    verified=verify_tooltip_ocr(frame,self.cfg.resource_names)
            bar=progress_bar_visible(frame,self.progress_roi)
            stone_changed=False
            target=self.map.resources.get(self.brain.target_id)
            if target is not None and self.brain.mode==Mode.GATHER:
                fx=frame.shape[1]*self.cfg.player_x_ratio+target.x-self.map.player_x
                fy=frame.shape[0]*self.cfg.player_y_ratio+target.y-self.map.player_y
                if self.depleted_template is not None:
                    # Positive evidence: a separately trained depleted appearance.
                    # Disappearance/occlusion of the original is NOT sufficient.
                    depleted=match_template(frame,self.depleted_template,max(.83,self.cfg.confidence),
                                            max_results=12,scales=(.85,1.,1.15))
                    stone_changed=any((d.x-fx)**2+(d.y-fy)**2 < (self.cfg.cell_px*.65)**2 for d in depleted)
            obs=Observation(frame.shape[1],frame.shape[0],motion.confidence,
                         [(d.x,d.y) for d in det],bar,verified,stone_changed,started)
            try:
                self.brain.tick(obs)
            except Exception as exc:
                self.brain.pause(f'Помилка керування: {exc}')
            self.recognition.emit([(d.x,d.y,round(d.confidence,2)) for d in det])
            elapsed=time.monotonic()-previous_time
            self._processing_fps=(.8*self._processing_fps+.2*(1/elapsed)) if elapsed>0 else 0
            previous_time=time.monotonic()
            if started-lastmap>1.0:
                self.stats.emit(f'Аналіз: {self._processing_fps:.1f} FPS | Камені: {len(self.map.resources)} | '
                                f'Підтверджено: {sum(r.verified for r in self.map.resources.values())} | '
                                f'Стан: {self.brain.mode.value} | Похибка ~{self.map.uncertainty:.0f}px | '
                                f'Перешкоди: {len(self.map.blocked)} | Кліки: {self.bridge.automatic_clicks}')
                self.map_changed.emit()
                lastmap=started
            if started-self._last_map_save>20:
                self.save_map()
            remain=1/max(.2,self.cfg.analysis_fps)-(time.monotonic()-started)
            if remain>0:time.sleep(remain)
