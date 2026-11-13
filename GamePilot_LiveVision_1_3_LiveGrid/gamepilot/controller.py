"""Guarded event-driven decision engine.

All input goes through InputBridge and is forbidden until an operator arms it.
State transitions are driven by actual visual observations rather than optimistic timers.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Callable

from .config import Settings
from .mapping import WorldMap, Resource


class Mode(str, Enum):
    IDLE='PAUSE'
    SEARCH='SEARCH'
    VERIFY='VERIFY'
    NAVIGATE='NAVIGATE'
    GATHER='GATHER'
    RECOVER='RECOVER'
    HELP='NEED HELP'


class InputBridge:
    def __init__(self) -> None:
        self.enabled=False
        self.monitor_origin=(0,0)
        self.monitor_size=(0,0)
        self.last_click=0.0
        self.last_hover=0.0
        self.last_key=0.0
        self.events: list[str]=[]
        self.window_title_contains = ''
        self.automatic_clicks=0
        self.click_limit=2000
        self.point_allowed: Callable[[float,float],bool] | None = None

    def configure_monitor(self, left:int,top:int,width:int,height:int):
        self.monitor_origin=(left,top)
        self.monitor_size=(width,height)

    def disarm(self):
        self.enabled=False
        try:
            import pyautogui
            for key in ('f','w','a','s','d','shift','ctrl'):
                pyautogui.keyUp(key)
            pyautogui.mouseUp()
        except Exception:
            pass

    def _window_focused(self) -> bool:
        """Fail closed for automation if configured foreground window is absent."""
        if not self.window_title_contains:
            return False
        try:
            import ctypes
            hwnd=ctypes.windll.user32.GetForegroundWindow()
            buf=ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd,buf,512)
            return self.window_title_contains.casefold() in buf.value.casefold()
        except (AttributeError,OSError):
            return False

    def _safe_point(self,x:float,y:float) -> bool:
        w,h=self.monitor_size
        return 12 <= x < w-12 and 12 <= y < h-12

    def hover(self,x:float,y:float) -> bool:
        if not self.enabled or not self._safe_point(x,y) or not self._window_focused(): return False
        if self.point_allowed is not None and not self.point_allowed(x,y): return False
        import pyautogui
        ox,oy=self.monitor_origin
        pyautogui.moveTo(ox+int(x),oy+int(y),duration=.12)
        self.last_hover=time.monotonic()
        return True

    def click(self,x:float,y:float,minimum_interval:float=1.2) -> bool:
        now=time.monotonic()
        if (not self.enabled or not self._safe_point(x,y) or not self._window_focused()
                or now-self.last_click<minimum_interval or self.automatic_clicks>=self.click_limit): return False
        if self.point_allowed is not None and not self.point_allowed(x,y): return False
        import pyautogui
        ox,oy=self.monitor_origin
        pyautogui.click(ox+int(x),oy+int(y))
        self.last_click=now
        self.automatic_clicks+=1
        return True

    def key(self,k:str) -> bool:
        if not self.enabled or not k or not self._window_focused(): return False
        if len(k)>20: return False
        import pyautogui
        pyautogui.press(k)
        self.last_key=time.monotonic()
        return True


@dataclass
class Observation:
    screen_width: int
    screen_height: int
    motion_confidence: float
    stones: list[tuple[float,float]]
    progress_bar: bool = False
    tooltip_verified: bool = False
    stone_changed: bool = False
    now: float = 0.0


class Navigator:
    def __init__(self, wm: WorldMap, settings: Settings):
        self.map=wm
        self.cfg=settings
        self.waypoints: list[tuple[float,float]]=[]
        self.goal: tuple[float,float] | None=None
        self.last_progress_time=time.monotonic()
        self.best_distance=float('inf')
        self.retries=0
        self.last_attempt=0.0
        self.last_click_target: tuple[float,float] | None=None

    def set_goal(self, goal: tuple[float,float]):
        if self.goal and math.dist(self.goal,goal) < self.cfg.cell_px*.6: return
        self.goal=goal
        self.waypoints=self.map.plan_taught(goal) if self.cfg.guided_mode else self.map.plan(goal)
        self.last_progress_time=time.monotonic()
        self.best_distance=float('inf')
        self.retries=0
        self.last_click_target=None

    def clear(self):
        self.waypoints=[]
        self.goal=None
        self.retries=0
        self.last_click_target=None

    def tick(self, bridge:InputBridge, frame_w:int,frame_h:int, now:float, arrival_radius:float|None=None) -> str:
        if self.goal is None: return 'no_goal'
        if self.cfg.guided_mode and not self.waypoints and math.dist((self.map.player_x,self.map.player_y),self.goal) > (arrival_radius or self.cfg.waypoint_radius_px): return 'failed'
        if self.map.cell(*self.goal) in self.map.forbidden: return 'failed'
        if not math.isfinite(self.map.player_x) or not math.isfinite(self.map.player_y): return 'failed'
        distance=math.dist((self.map.player_x,self.map.player_y),self.goal)
        if distance < (arrival_radius or self.cfg.waypoint_radius_px): return 'arrived'
        while self.waypoints and math.dist((self.map.player_x,self.map.player_y),self.waypoints[0])<self.cfg.waypoint_radius_px:
            self.waypoints.pop(0)
        if not self.waypoints:
            self.waypoints=self.map.plan_taught(self.goal) if self.cfg.guided_mode else self.map.plan(self.goal)
        if distance < self.best_distance-8:
            self.best_distance=distance
            self.last_progress_time=now
        if now-self.last_progress_time>self.cfg.stall_seconds:
            self.retries+=1
            if self.retries>=3: return 'failed'
            if self.waypoints:
                wx,wy=self.waypoints[0]
                # Mark the next contact cell and try a newly planned alternative.
                self.map.set_blocked(wx,wy,True)
            else:
                dx=self.goal[0]-self.map.player_x
                dy=self.goal[1]-self.map.player_y
                factor=min(1.,self.cfg.cell_px/max(1.,math.hypot(dx,dy)))
                self.map.set_blocked(self.map.player_x+dx*factor,self.map.player_y+dy*factor,True)
            self.waypoints=self.map.plan_taught(self.goal) if self.cfg.guided_mode else self.map.plan(self.goal)
            self.best_distance=float('inf')
            self.last_progress_time=now
            return 'reroute'
        if not self.waypoints: return 'failed'
        tx,ty=self.waypoints[0]
        sx=frame_w*self.cfg.player_x_ratio+tx-self.map.player_x
        sy=frame_h*self.cfg.player_y_ratio+ty-self.map.player_y
        # Limit clicks within visible, non-HUD play area; progress checked on next frames.
        px=frame_w*self.cfg.player_x_ratio
        py=frame_h*self.cfg.player_y_ratio
        dx,dy=sx-px,sy-py
        ratio=min(1.,frame_w*.32/max(1.,abs(dx)),frame_h*.29/max(1.,abs(dy)))
        sx=px+dx*ratio; sy=py+dy*ratio
        start_world=(self.map.player_x,self.map.player_y)
        end_world=(self.map.player_x+sx-px,self.map.player_y+sy-py)
        if not (self.map.line_passable(start_world,end_world) and
                (not self.cfg.guided_mode or self.map.line_taught_passable(start_world,end_world))):
            self.retries+=1
            if self.retries>=3: return 'failed'
            self.map.set_blocked(tx,ty,True)
            self.waypoints=self.map.plan_taught(self.goal) if self.cfg.guided_mode else self.map.plan(self.goal)
            self.last_progress_time=now
            return 'reroute'
        if bridge.click(sx,sy,self.cfg.click_interval_seconds):
            self.last_click_target=(sx,sy)
            return 'moving'
        return 'waiting'


class Brain:
    def __init__(self, cfg:Settings, wm:WorldMap, bridge:InputBridge, report:Callable[[str],None]):
        self.cfg,self.map,self.bridge,self.report=cfg,wm,bridge,report
        self.mode=Mode.IDLE
        self.nav=Navigator(wm,cfg)
        self.target_id: int|None=None
        self.verify_started=0.0
        self.gather_started=0.0
        self.bar_seen=False
        self.bar_lost_at=0.0
        self.gather_key_sent=False
        self.interact_key_sent=False
        self.last_cycle_seen=0.0
        self.search_failures=0
        self.explore_failures:dict[tuple[int,int],float]={}
        self.last_motion_ok=time.monotonic()
        self.last_tick=time.monotonic()
        self.session_started=0.0

    def pause(self,message:str='Пауза'):
        self.mode=Mode.IDLE
        self.bridge.disarm()
        self.nav.clear()
        self.report(message)

    def arm(self):
        if not self.bridge.enabled:
            self.report('Увімкніть керування мишею в адмін-панелі')
            return
        self.session_started=time.monotonic()
        self.bridge.automatic_clicks=0
        self.bridge.click_limit=self.cfg.max_automatic_clicks
        self.mode=Mode.SEARCH
        self.report('Запущено прохід по навчених точках' if self.cfg.guided_mode else 'Почато пошук ресурсів')

    def _available(self, now:float) -> list[Resource]:
        return [r for r in self.map.resources.values()
                if r.verified and now>=r.next_attempt_at and
                (r.depleted_at is None or now-r.depleted_at>=self.cfg.timers_seconds.get(f'T{r.tier}',self.cfg.respawn_t1_seconds))]

    def _frontier(self):
        now=time.monotonic()
        return self.map.frontier(excluded={c for c,until in self.explore_failures.items() if until>now})

    def _seek(self,obs:Observation,now:float):
        candidates=self._available(time.time())
        if not self.cfg.guided_mode and len([r for r in self.map.resources.values() if r.verified])<self.cfg.stone_goal:
            # Hover candidate for verification, otherwise explore.
            fresh=[r for r in self.map.resources.values() if not r.verified and time.time()>=r.next_attempt_at
                   and r.observations>=2 and time.time()-r.last_seen<12]
            if fresh:
                r=min(fresh,key=lambda x:math.dist((x.x,x.y),(self.map.player_x,self.map.player_y)))
                self.target_id=r.id
                sx=obs.screen_width*self.cfg.player_x_ratio+r.x-self.map.player_x
                sy=obs.screen_height*self.cfg.player_y_ratio+r.y-self.map.player_y
                if self.bridge.hover(sx,sy):
                    self.verify_started=now
                    self.mode=Mode.VERIFY
                else:
                    self.map.mark_failure(r.id,time.time(),max(8,self.cfg.cooldown_failure_seconds//3))
                    self.report(f'T1 #{r.id}: не вдалося навести курсор, відкладаю перевірку')
                return
            if self.cfg.auto_explore and not self.cfg.guided_mode:
                point=self._frontier()
                if point:
                    self.nav.set_goal(point)
                    self.target_id=None
                    self.mode=Mode.NAVIGATE
                else:
                    self.mode=Mode.HELP
                    self.bridge.disarm()
                    self.report('Немає доступного напрямку дослідження')
            return
        if not candidates:
            if self.cfg.auto_explore and not self.cfg.guided_mode:
                point=self._frontier()
                if point:
                    self.nav.set_goal(point)
                    self.target_id=None
                    self.mode=Mode.NAVIGATE
            return
        r=min(candidates,key=lambda x:math.dist((x.x,x.y),(self.map.player_x,self.map.player_y)))
        self.target_id=r.id
        self.nav.set_goal((r.x,r.y))
        self.mode=Mode.NAVIGATE
        self.report(f'Рух до каменя #{r.id}')

    def tick(self,obs:Observation):
        now=obs.now or time.monotonic()
        if self.mode in (Mode.IDLE,Mode.HELP): return
        if not self.bridge.enabled:
            self.pause('Керування вимкнено')
            return
        if self.session_started and now-self.session_started>self.cfg.max_session_minutes*60:
            self.pause('Досягнуто ліміту часу сесії')
            return
        if self.bridge.automatic_clicks>=self.cfg.max_automatic_clicks:
            self.pause('Досягнуто ліміту автоматичних кліків')
            return
        if not self.bridge._window_focused():
            self.pause('Фокус втрачено: активне вікно гри закрито або змінено')
            return
        if self.map.uncertainty>self.cfg.max_position_uncertainty_px:
            self.mode=Mode.HELP
            self.bridge.disarm()
            self.report('Локалізація невпевнена: потрібна допомога адміністратора')
            return
        if self.mode==Mode.SEARCH:
            self._seek(obs,now)
        elif self.mode==Mode.VERIFY:
            if now-self.verify_started<self.cfg.hover_settle_seconds: return
            r=self.map.resources.get(self.target_id)
            if not r:
                self.mode=Mode.SEARCH;return
            sx=obs.screen_width*self.cfg.player_x_ratio+r.x-self.map.player_x
            sy=obs.screen_height*self.cfg.player_y_ratio+r.y-self.map.player_y
            target_visible=any(math.hypot(x-sx,y-sy)<self.cfg.cell_px for x,y in obs.stones)
            if obs.tooltip_verified and target_visible:
                r.verified=True
                self.report(f'Підтверджено T1 #{r.id}')
            else:
                self.map.mark_failure(r.id,time.time(),self.cfg.cooldown_failure_seconds)
                self.report(f'T1 #{r.id}: назва не підтверджена')
            self.mode=Mode.SEARCH
        elif self.mode==Mode.NAVIGATE:
            status=self.nav.tick(self.bridge,obs.screen_width,obs.screen_height,now,
                                 (max(self.cfg.resource_radius_px,self.cfg.cell_px*1.1) if self.cfg.guided_mode else self.cfg.resource_radius_px) if self.target_id is not None else None)
            if status=='arrived':
                self.nav.clear()
                if self.target_id is not None and self.cfg.auto_gather:
                    self.mode=Mode.GATHER
                    self.gather_started=now
                    self.bar_seen=False
                    self.bar_lost_at=0
                    self.gather_key_sent=False
                    self.interact_key_sent=False
                    self.last_cycle_seen=now
                    self.report('Біля каменя, починаю збір')
                else:
                    self.mode=Mode.SEARCH
            elif status=='failed':
                if self.target_id is None and self.nav.goal is not None:
                    self.explore_failures[self.map.cell(*self.nav.goal)]=now+max(30,self.cfg.cooldown_failure_seconds)
                if self.target_id is not None and self.target_id in self.map.resources:
                    self.map.mark_failure(self.target_id,time.time(),self.cfg.cooldown_failure_seconds)
                self.report('Маршрут недоступний після трьох спроб — пропускаю')
                self.nav.clear()
                self.mode=Mode.SEARCH
            elif status=='reroute':
                self.report(f'Перебудова маршруту, спроба {self.nav.retries}/3')
        elif self.mode==Mode.GATHER:
            r=self.map.resources.get(self.target_id)
            if not r:
                self.mode=Mode.SEARCH;return
            if not self.gather_key_sent:
                sx=obs.screen_width*self.cfg.player_x_ratio + r.x-self.map.player_x
                sy=obs.screen_height*self.cfg.player_y_ratio + r.y-self.map.player_y
                # Mouse click on resource may initiate approach/interact; optional key is configurable.
                if self.bridge.click(sx,sy,self.cfg.click_interval_seconds):
                    self.gather_key_sent=True
                    self.gather_started=now
                elif now-self.gather_started>8.0:
                    self.map.mark_failure(r.id,time.time(),self.cfg.cooldown_failure_seconds)
                    self.report(f'Камінь #{r.id}: неможливо почати взаємодію — пропускаю')
                    self.mode=Mode.SEARCH
                return
            if not self.bar_seen and not self.interact_key_sent and now-self.gather_started>2.0 and self.cfg.gather_key:
                self.interact_key_sent=self.bridge.key(self.cfg.gather_key)
            if obs.progress_bar:
                self.bar_seen=True
                self.bar_lost_at=0.0
                self.last_cycle_seen=now
            elif self.bar_seen:
                if self.bar_lost_at==0: self.bar_lost_at=now
                # Bar may blink between gathering cycles; verify disappearance persists.
                if now-self.bar_lost_at>2.7 and obs.stone_changed:
                    r.depleted_at=time.time()
                    self.report(f'Камінь #{r.id}: збір завершено (індикатор + зміна вигляду)')
                    self.mode=Mode.SEARCH
                elif now-self.bar_lost_at>8.0:
                    self.map.mark_failure(r.id,time.time(),self.cfg.cooldown_failure_seconds)
                    self.report(f'Камінь #{r.id}: стан неясний; пропускаю до перевірки')
                    self.mode=Mode.SEARCH
            if now-self.gather_started>150 or (not self.bar_seen and now-self.gather_started>12):
                self.map.mark_failure(r.id,time.time(),self.cfg.cooldown_failure_seconds)
                self.report('Збір не підтверджено — пропускаю камінь')
                self.mode=Mode.SEARCH
