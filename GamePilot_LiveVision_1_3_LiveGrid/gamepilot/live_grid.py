"""Transparent, noninteractive live visual grid, never a source of game input.

Windows uses WDA_EXCLUDEFROMCAPTURE to keep the overlay out of mss frames.
If display-affinity is unsupported, the overlay is hidden to avoid screen
feedback loops. This is screenshot hygiene, not concealment from the client.
"""
from __future__ import annotations
import sys
import math
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget
from .display_geometry import world_to_screen, grid_lines, adaptive_zoom


class LiveGridOverlay(QWidget):
    def __init__(self, cfg, world):
        super().__init__(None)
        self.cfg,self.world=cfg,world
        self.full_size=(0,0)
        self.detections=[]
        self.capture_supported=False
        self.show_mini_map=True
        self.setWindowTitle('GamePilot Live Grid')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground,True)

    def set_monitor(self,left,top,width,height):
        # QT uses logical screen pixels while mss uses physical pixels.
        # Correct for per-monitor scaling rather than assuming 100% DPI.
        self.full_size=(width,height)
        from PySide6.QtGui import QGuiApplication
        screens=QGuiApplication.screens()
        target=next((s for s in screens if s.geometry().contains(int(left/max(.01,s.devicePixelRatio())),int(top/max(.01,s.devicePixelRatio())))),None)
        dpr=target.devicePixelRatio() if target else (screens[0].devicePixelRatio() if screens else 1.)
        self.setGeometry(round(left/dpr),round(top/dpr),round(width/dpr),round(height/dpr))

    def enable(self):
        if sys.platform!='win32':
            return False
        self.show()
        try:
            import ctypes
            hwnd=int(self.winId())
            u=ctypes.windll.user32
            GWL_EXSTYLE=-20;WS_EX_TRANSPARENT=0x20;WS_EX_NOACTIVATE=0x08000000
            current=u.GetWindowLongW(hwnd,GWL_EXSTYLE)
            u.SetWindowLongW(hwnd,GWL_EXSTYLE,current|WS_EX_TRANSPARENT|WS_EX_NOACTIVATE)
            # WDA_EXCLUDEFROMCAPTURE is supported on Windows 10 2004+.
            # Do not keep overlay visible if it would contaminate captures.
            self.capture_supported=bool(u.SetWindowDisplayAffinity(hwnd,0x11))
        except (OSError,AttributeError,ValueError):
            self.capture_supported=False
        if not self.capture_supported:
            self.hide()
        return self.capture_supported

    def set_detections(self,detections):
        self.detections=list(detections)
        self.update()

    def paintEvent(self,event):
        super().paintEvent(event)
        fullw,fullh=self.full_size
        if not fullw or not fullh:return
        sx=self.width()/fullw;sy=self.height()/fullh
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        painter.scale(sx,sy)
        cell=self.world.cell_px
        # Screen grid is anchored to local-world coordinates; no visual sliding.
        origin_x=fullw*self.cfg.player_x_ratio-self.world.player_x
        origin_y=fullh*self.cfg.player_y_ratio-self.world.player_y
        painter.setPen(QPen(QColor(76,221,181,65),1/max(.2,sx)))
        for x in grid_lines(fullw,0,origin_x,cell):painter.drawLine(QPointF(x,0),QPointF(x,fullh))
        for y in grid_lines(fullh,0,origin_y,cell):painter.drawLine(QPointF(0,y),QPointF(fullw,y))
        # Resources already tracked and manually marked; dim unverified landmarks.
        font=QFont('Segoe UI',11);font.setBold(True);painter.setFont(font)
        for r in list(self.world.resources.values()):
            x,y=world_to_screen(r.x,r.y,self.world.player_x,self.world.player_y,
                                fullw,fullh,self.cfg.player_x_ratio,self.cfg.player_y_ratio)
            if not (-15<=x<=fullw+15 and -15<=y<=fullh+15):continue
            painter.setPen(QPen(QColor('#58efc2') if r.verified else QColor('#c3a46d'),2))
            painter.setBrush(QColor(7,27,29,145))
            painter.drawEllipse(QPointF(x,y),11,11)
            painter.drawText(QPointF(x+15,y-9),f'T{r.tier} #{r.id}'+(' ✓' if r.verified else ' ?'))
        # Frame detections are distinguished from persistent map resources.
        painter.setPen(QPen(QColor('#f5cb72'),2))
        for x,y,conf in self.detections:
            painter.drawEllipse(QPointF(x,y),16,16)
            painter.drawText(QPointF(x+19,y+4),f'T1 {conf:.2f}')
        if self.show_mini_map:
            self._paint_mini_map(painter,fullw,fullh)
        if self.world.uncertainty>self.cfg.max_position_uncertainty_px*.75:
            painter.setPen(QColor('#ffac6a'))
            painter.drawText(QPointF(26,40),'⚠ ПОЗИЦІЯ НЕТОЧНА — ПЕРЕВІР КАРТУ')
        else:
            painter.setPen(QColor('#8ff7d7'))
            painter.drawText(QPointF(26,40),'GAMEPILOT  •  LIVE GRID  /  T1')
        painter.end()

    def _paint_mini_map(self,p,screen_w,screen_h):
        """Top-right auto-fit survey map. This is local odometry, not game GPS."""
        mw=min(290,max(145,screen_w*.22))
        mh=min(215,max(110,screen_h*.25))
        x0=screen_w-mw-24; y0=25
        if x0<0:return
        p.setPen(QPen(QColor('#416c68'),2))
        p.setBrush(QColor(6,24,29,214))
        p.drawRoundedRect(QRectF(x0,y0,mw,mh),13,13)
        p.setFont(QFont('Segoe UI',10))
        p.setPen(QColor('#9bdaca'))
        p.drawText(QPointF(x0+14,y0+20),'ПРОЙДЕНА ТЕРИТОРІЯ  /  AUTO FIT')
        points=set(self.world.visited)|set(self.world.blocked)|set(self.world.exits)
        points.update(self.world.cell(r.x,r.y) for r in self.world.resources.values())
        points.add(self.world.cell(self.world.base_x,self.world.base_y))
        pc=(self.world.player_x/self.world.cell_px,self.world.player_y/self.world.cell_px)
        points.add(self.world.cell(self.world.player_x,self.world.player_y))
        if not points:return
        xs=[c[0] for c in points];ys=[c[1] for c in points]
        wx=(min(xs)+max(xs))/2;wy=(min(ys)+max(ys))/2
        step=adaptive_zoom(points,pc,(int(mw-22),int(mh-50)),previous=30,base=30,
                           padding_cells=2,min_zoom=.25,zoom_out_only=False)
        ox=x0+mw/2;oy=y0+mh/2+12
        def point(cx,cy):return QPointF(ox+(cx-wx)*step,oy+(cy-wy)*step)
        p.setPen(Qt.PenStyle.NoPen)
        for cx,cy in self.world.visited:
            a=point(cx,cy);p.fillRect(QRectF(a.x()-step/2,a.y()-step/2,step,step),QColor('#3b7c68'))
        for cx,cy in self.world.blocked:
            a=point(cx,cy);p.fillRect(QRectF(a.x()-step/2,a.y()-step/2,step,step),QColor('#899ca4'))
        for cx,cy in self.world.exits:
            a=point(cx,cy);p.setBrush(QColor('#e58b77'));p.drawEllipse(a,max(2,step*.45),max(2,step*.45))
        p.setBrush(QColor('#f5c576'));p.setPen(QPen(QColor('#ffeaca'),1))
        for r in self.world.resources.values():
            a=point(r.x/self.world.cell_px,r.y/self.world.cell_px)
            p.drawEllipse(a,3.5,3.5)
        p.setBrush(QColor('#6dbeff'));p.setPen(QPen(QColor('white'),1))
        p.drawEllipse(point(self.world.base_x/self.world.cell_px,self.world.base_y/self.world.cell_px),4,4)
        p.setBrush(QColor('#61ebbc'));p.drawEllipse(point(*pc),5,5)
