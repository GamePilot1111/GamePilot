from __future__ import annotations
import math
import time
from pathlib import Path
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QGridLayout,QLabel,QPushButton,QSpinBox,QDoubleSpinBox,QCheckBox,QComboBox,
    QTextEdit,QTabWidget,QScrollArea,QGroupBox,QFormLayout,QSplitter,QMessageBox,
    QFrame,QSlider,QInputDialog,QLineEdit,QFileDialog)

from .config import Settings,app_home
from .mapping import WorldMap
from .runtime import Runtime
from .controller import Mode
from .live_grid import LiveGridOverlay
from .display_geometry import adaptive_zoom

STYLE = r'''
QWidget { background:#0d141d; color:#dfebf0; font-family:"Segoe UI",Arial; font-size:12px; }
QMainWindow { background:#0d141d; }
QPushButton { background:#1b2b36; color:#deedf0; border:1px solid #304957; border-radius:9px; padding:10px 15px; font-weight:500; }
QPushButton:hover { background:#284453; border-color:#4d7180; }
QPushButton:pressed { background:#173f3f; }
QPushButton:disabled { color:#697d84; background:#152029; }
QPushButton#primary { background:#128c7c; border-color:#28b29c; color:#f3fffb; font-weight:700; }
QPushButton#primary:hover { background:#1da997; }
QPushButton#danger { background:#69323c; border-color:#a9515b; color:#ffe0e2; font-weight:700; }
QPushButton#danger:hover { background:#86404a; }
QLabel#big { font-size:24px; color:#eef9fa; font-weight:800; letter-spacing:.3px; }
QLabel#subtitle { color:#8aa4ad; }
QTabWidget::pane { background:#101c26; border:1px solid #263b47; border-radius:10px; top:-2px; }
QTabBar::tab { padding:12px 19px; background:#15222c; border:1px solid #263b46; border-radius:8px; margin-right:5px; color:#9db2bd; }
QTabBar::tab:selected { color:#b9fff0; background:#1b3e41; border-color:#32887c; }
QTabBar::tab:hover { background:#203640; }
QGroupBox { background:#111f2a; border:1px solid #293f4b; border-radius:11px; margin-top:14px; padding:16px 11px 11px; font-weight:650; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 9px; color:#bde3df; }
QSpinBox,QDoubleSpinBox,QComboBox,QLineEdit { background:#152936; border:1px solid #335160; border-radius:7px; padding:8px; selection-background-color:#137e76; }
QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus,QLineEdit:focus { border-color:#43b6a0; }
QTextEdit { background:#0e1a23; border:1px solid #2b424e; border-radius:9px; color:#b7d0d8; padding:8px; font-family:Consolas,"Segoe UI"; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#15222d; width:10px; border:0; }
QScrollBar::handle:vertical { background:#385461; min-height:28px; border-radius:5px; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:17px; height:17px; }
QSlider::groove:horizontal { background:#29424e; height:5px; border-radius:2px; }
QSlider::handle:horizontal { background:#41bda4; width:15px; margin:-5px 0; border-radius:7px; }
'''


class MiniOverlay(QWidget):
    """Optional always-on-top control strip; can interfere with capture if it covers the game."""
    def __init__(self, stop_callback):
        super().__init__()
        self.setWindowTitle('GamePilot Mini')
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(370,108)
        self.setStyleSheet('background:#11212c;color:#e7f6f5;')
        lay=QVBoxLayout(self);lay.setContentsMargins(15,10,15,10)
        header=QHBoxLayout()
        title=QLabel('◉ GAMEPILOT  /  LIVE CONTROL')
        title.setStyleSheet('font-size:12px;font-weight:800;color:#69e7c3;')
        header.addWidget(title);header.addStretch()
        stop=QPushButton('■ F8 СТОП');stop.setObjectName('danger')
        stop.setMinimumWidth(112);stop.clicked.connect(stop_callback)
        header.addWidget(stop);lay.addLayout(header)
        self.mode=QLabel('СПОСТЕРЕЖЕННЯ')
        self.mode.setStyleSheet('font-size:12px;color:#d9eff4;')
        lay.addWidget(self.mode)
        self.metrics=QLabel('FPS — | камені — | кліки —')
        self.metrics.setStyleSheet('font-size:11px;color:#91aab6;')
        lay.addWidget(self.metrics)
        self.setMinimumWidth(370)



class LiveImage(QLabel):
    selected=Signal(object)
    point_selected=Signal(object)
    def __init__(self):
        super().__init__('Запуск захоплення екрана…')
        self.setMinimumSize(480,300)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:#071018;border:1px solid #415361;border-radius:6px;')
        self.original:QImage|None=None
        self.drag_start:QPoint|None=None
        self.drag_end:QPoint|None=None
        self.detections=[]
        self.grid_enabled=False

    def set_image(self,image:QImage):
        self.original=image
        self.update()

    def _layout(self):
        if self.original is None:return (0,0,1,1,1.)
        w,h=self.original.width(),self.original.height()
        scale=min(self.width()/w,self.height()/h)
        dw,dh=max(1,int(w*scale)),max(1,int(h*scale))
        return ((self.width()-dw)//2,(self.height()-dh)//2,dw,dh,scale)

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.original is None:return
        painter=QPainter(self)
        x,y,w,h,scale=self._layout()
        painter.drawImage(QRect(x,y,w,h),self.original)
        if self.grid_enabled:
            painter.save()
            painter.setClipRect(QRect(x,y,w,h))
            painter.setPen(QPen(QColor(100,234,192,85),1))
            step=max(18,int(w/18))
            for px in range(x,x+w+step,step): painter.drawLine(px,y,px,y+h)
            for py in range(y,y+h+step,step): painter.drawLine(x,py,x+w,py)
            painter.restore()
        painter.setPen(QPen(QColor('#48e3a4'),2))
        # Detections are stored in full-resolution capture coordinates.
        sx=self.original.width()/max(1,self.capture_full_w)
        sy=self.original.height()/max(1,self.capture_full_h)
        for px,py,conf in self.detections:
            cx=x+px*sx*scale;cy=y+py*sy*scale
            painter.drawEllipse(QPoint(int(cx),int(cy)),11,11)
            painter.drawText(int(cx)+12,int(cy)-7,f'T1 {conf:.2f}')
        if self.drag_start and self.drag_end:
            painter.setPen(QPen(QColor('#ffca76'),2,Qt.PenStyle.DashLine))
            painter.drawRect(QRect(self.drag_start,self.drag_end).normalized())
        painter.end()

    capture_full_w=1
    capture_full_h=1

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.original is not None:
            self.drag_start=event.position().toPoint()
            self.drag_end=self.drag_start
            self.update()

    def mouseMoveEvent(self,event):
        if self.drag_start is not None:
            self.drag_end=event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self,event):
        if not self.drag_start or self.original is None:return
        self.drag_end=event.position().toPoint()
        r=QRect(self.drag_start,self.drag_end).normalized()
        self.drag_start=None;self.drag_end=None
        ox,oy,w,h,scale=self._layout()
        left=max(ox,r.left());top=max(oy,r.top())
        right=min(ox+w,r.right());bottom=min(oy+h,r.bottom())
        if right-left<8 or bottom-top<8:
            if self.grid_enabled and ox<=r.center().x()<ox+w and oy<=r.center().y()<oy+h:
                point=(round((r.center().x()-ox)*self.capture_full_w/max(1,w)),
                       round((r.center().y()-oy)*self.capture_full_h/max(1,h)))
                self.point_selected.emit(point)
            self.update();return
        ratio_x=self.capture_full_w/max(1,w)
        ratio_y=self.capture_full_h/max(1,h)
        area=(round((left-ox)*ratio_x),round((top-oy)*ratio_y),
              round((right-left)*ratio_x),round((bottom-top)*ratio_y))
        self.selected.emit(area)
        self.update()


class MapCanvas(QWidget):
    changed=Signal(str)
    def __init__(self,world:WorldMap):
        super().__init__()
        self.world=world
        self.tool='block'
        self.zoom=16
        self.auto_zoom=True
        self._fit_center=None
        self.setMinimumSize(440,390)
        self.setMouseTracking(True)
        self.setStyleSheet('background:#142018;')

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('#111d1c'))
        p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        center_x=self.width()*.5;center_y=self.height()*.5
        wx=self.world.player_x/self.world.cell_px
        wy=self.world.player_y/self.world.cell_px
        if self.auto_zoom:
            # Fit the known footprint, not the entire guessed world. Keep the
            # base, resources, exits and the present player within the view.
            points=set(self.world.visited)|set(self.world.blocked)|set(self.world.exits)
            points.update(self.world.cell(r.x,r.y) for r in self.world.resources.values())
            points.add(self.world.cell(self.world.base_x,self.world.base_y))
            self.zoom=adaptive_zoom(points,(wx,wy),(self.width()-35,self.height()-60),
                                    previous=self.zoom,base=16.,min_zoom=2.)
            if points:
                xs=[c[0] for c in points]+[wx];ys=[c[1] for c in points]+[wy]
                wx=(min(xs)+max(xs))/2
                wy=(min(ys)+max(ys))/2
        self._fit_center=(wx,wy)
        p.setPen(QPen(QColor('#223c33'),1))
        xleft=math.floor(wx-center_x/self.zoom)-1
        xright=math.ceil(wx+center_x/self.zoom)+1
        ytop=math.floor(wy-center_y/self.zoom)-1
        ybottom=math.ceil(wy+center_y/self.zoom)+1
        # Do not allocate thousands of primitives after a large map is loaded.
        if xright-xleft<600:
            for gx in range(xleft,xright+1):
                x=center_x+(gx-wx)*self.zoom
                p.drawLine(int(x),0,int(x),self.height())
        if ybottom-ytop<600:
            for gy in range(ytop,ybottom+1):
                y=center_y+(gy-wy)*self.zoom
                p.drawLine(0,int(y),self.width())
        def cell_rect(c):
            return QRect(round(center_x+(c[0]-wx-.5)*self.zoom),
                         round(center_y+(c[1]-wy-.5)*self.zoom),self.zoom,self.zoom)
        p.setPen(Qt.PenStyle.NoPen)
        for cell in self.world.visited:
            p.fillRect(cell_rect(cell),QColor('#456c54'))
        for cell in self.world.blocked:
            p.fillRect(cell_rect(cell),QColor('#8f969d'))
        for cell in self.world.forbidden:
            p.fillRect(cell_rect(cell),QColor(149,66,68,140))
        p.setPen(QPen(QColor('#f4c97a'),2))
        for cell in self.world.exits:
            rect=cell_rect(cell)
            p.drawRect(rect)
        for r in self.world.resources.values():
            rx=center_x+(r.x/self.world.cell_px-wx)*self.zoom
            ry=center_y+(r.y/self.world.cell_px-wy)*self.zoom
            p.setBrush(QColor('#e8b965') if r.verified else QColor('#767c77'))
            p.setPen(QPen(QColor('#fff1c9'),1))
            p.drawEllipse(QPoint(int(rx),int(ry)),5,5)
            p.drawText(int(rx)+7,int(ry)-5,f'{r.id}{"✓" if r.verified else "?"}')
        bx=center_x+(self.world.base_x/self.world.cell_px-wx)*self.zoom
        by=center_y+(self.world.base_y/self.world.cell_px-wy)*self.zoom
        p.setBrush(QColor('#71c1fc'));p.setPen(QPen(QColor('white'),2))
        p.drawRect(int(bx)-5,int(by)-5,10,10)
        p.setBrush(QColor('#48e3a4'))
        p.drawEllipse(QPoint(int(center_x+(self.world.player_x/self.world.cell_px-wx)*self.zoom),int(center_y+(self.world.player_y/self.world.cell_px-wy)*self.zoom)),7,7)
        p.setPen(QColor('#d4e6df'))
        p.drawText(12,22,f'Гравець ({self.world.player_x:.0f}, {self.world.player_y:.0f})')
        p.drawText(12,40,f'Інструмент: {self.tool} | Масштаб: {self.zoom:.1f}px/клітинку | '+('Авто' if self.auto_zoom else 'Ручний'))
        p.end()

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        wx,wy=self._fit_center or (self.world.player_x/self.world.cell_px,self.world.player_y/self.world.cell_px)
        x=((event.position().x()-self.width()/2)/self.zoom+wx)*self.world.cell_px
        y=((event.position().y()-self.height()/2)/self.zoom+wy)*self.world.cell_px
        if self.tool=='block':self.world.set_blocked(x,y)
        elif self.tool=='erase':
            self.world.erase(x,y)
        elif self.tool=='exit':self.world.set_exit(x,y)
        elif self.tool=='base':
            self.world.base_x=x;self.world.base_y=y
        self.changed.emit(f'Карту змінено: {self.tool}')
        self.update()


class MainWindow(QMainWindow):
    hotkey_start=Signal()
    hotkey_toggle_grid=Signal()
    hotkey_teach=Signal(str)
    def __init__(self):
        super().__init__()
        self.cfg=Settings.load()
        map_path=app_home()/'map.json'
        self.position_confirmed=not map_path.exists()
        try:self.world=WorldMap.load(map_path)
        except (OSError,ValueError,TypeError,KeyError):
            self.world=WorldMap(cell_px=self.cfg.cell_px)
            self.position_confirmed=True
        self.runtime=Runtime(self.cfg,self.world)
        self.runtime.status.connect(self.log)
        self.runtime.stats.connect(self.on_stats)
        self.runtime.recognition.connect(self.on_detection)
        self.runtime.map_changed.connect(self.refresh_map)
        self.runtime.capture.image.connect(self.on_frame)
        self.runtime.capture.capture_info.connect(self.on_monitor)
        self.live_grid=LiveGridOverlay(self.cfg,self.world)
        self.live_grid_enabled=False
        self.setWindowTitle('GamePilot Live Vision 1.3 | Live Grid')
        self.setMinimumSize(1050,690)
        self.resize(1230,780)
        self.setStyleSheet(STYLE)
        self.pending_tool='stone'
        self.last_frame_time=0.0
        self.display_fps=0.0
        self._build()
        self.mini_overlay=MiniOverlay(self.emergency_stop)
        self._hotkey_listener=None
        self.hotkey_start.connect(self._start_when_game_focused)
        self.hotkey_toggle_grid.connect(lambda:self.toggle_live_grid(not self.live_grid_enabled))
        self.hotkey_teach.connect(self.mark_cursor_hotkey)
        self._setup_hotkey()
        self.runtime.start()
        self.log('Live Vision запущено у режимі спостереження. F8 — аварійна зупинка.')
        if not self.position_confirmed:
            self.log('Завантажена карта з попередньої сесії. Підтвердіть позицію перед автоматизацією.')

    def _build(self):
        central=QWidget();self.setCentralWidget(central)
        outer=QVBoxLayout(central)
        header=QHBoxLayout()
        title=QLabel('◉  GAMEPILOT  /  LIVE VISION');title.setObjectName('big')
        header.addWidget(title)
        header.addStretch()
        overlay_btn=QPushButton('◫ Міні-панель')
        overlay_btn.setToolTip('Показати компактну панель. Не накривайте нею важливу область гри.')
        overlay_btn.clicked.connect(self.toggle_overlay)
        header.addWidget(overlay_btn)
        self.grid_overlay_button=QPushButton('▦ Сітка на грі: OFF / F5')
        self.grid_overlay_button.setCheckable(True)
        self.grid_overlay_button.toggled.connect(self.toggle_live_grid)
        header.addWidget(self.grid_overlay_button)
        self.state=QLabel('СПОСТЕРЕЖЕННЯ');self.state.setObjectName('subtitle')
        header.addWidget(self.state)
        outer.addLayout(header)
        self.tabs=QTabWidget();outer.addWidget(self.tabs,1)
        self._build_live()
        self._build_teaching()
        self._build_map()
        self._build_settings()
        self.stats=QLabel('Ініціалізація потоків…');self.stats.setObjectName('subtitle')
        outer.addWidget(self.stats)
        footer=QHBoxLayout()
        self.arm_box=QCheckBox('Дозволити автоматичні кліки (лише тестовий клієнт)')
        self.arm_box.toggled.connect(self.toggle_input)
        footer.addWidget(self.arm_box)
        self.start_btn=QPushButton('▶ СТАРТ / F6');self.start_btn.setObjectName('primary')
        self.start_btn.clicked.connect(self.start_bot)
        footer.addWidget(self.start_btn)
        stop=QPushButton('■ СТОП / F8');stop.setObjectName('danger')
        stop.clicked.connect(self.emergency_stop)
        footer.addWidget(stop)
        outer.addLayout(footer)

    def _build_live(self):
        tab=QWidget();self.tabs.addTab(tab,'📷  Живий екран')
        row=QHBoxLayout(tab)
        left=QVBoxLayout();row.addLayout(left,4)
        self.live=LiveImage()
        self.live.selected.connect(self.on_area_selected)
        self.live.point_selected.connect(self.on_teach_preview_click)
        left.addWidget(self.live,1)
        line=QHBoxLayout()
        line.addWidget(QLabel('Вибір області:'))
        self.tool_select=QComboBox()
        self.tool_select.addItem('Камінь T1','stone')
        self.tool_select.addItem('Виснажений камінь T1','depleted')
        self.tool_select.addItem('Назва в підказці при наведенні','tooltip')
        self.tool_select.addItem('Індикатор збору','progress')
        self.tool_select.addItem('Зразок води / річки','water')
        self.tool_select.addItem('Зразок скелі','rock')
        self.tool_select.addItem('Шаблон виходу','exit')
        self.tool_select.currentIndexChanged.connect(lambda:self.log('Виділіть область мишею на відео'))
        line.addWidget(self.tool_select)
        left.addLayout(line)
        hint=QLabel('Перетягніть ЛКМ по кадру, щоб навчити шаблон. Підказку навчайте під час наведення курсора на T1.')
        hint.setWordWrap(True);hint.setObjectName('subtitle')
        left.addWidget(hint)
        right=QVBoxLayout();row.addLayout(right,2)
        guide=QGroupBox('Модулі');guide_l=QVBoxLayout(guide)
        self.lab_stone=QLabel('Шаблон T1: —')
        self.lab_depleted=QLabel('Виснажений T1: —')
        self.lab_tip=QLabel('Підказка T1: —')
        self.lab_bar=QLabel('Індикатор: —')
        self.lab_terrain=QLabel('Місцевість: —')
        self.lab_exit=QLabel('Шаблон виходу: —')
        for lab in (self.lab_stone,self.lab_depleted,self.lab_tip,self.lab_bar,self.lab_terrain,self.lab_exit):guide_l.addWidget(lab)
        right.addWidget(guide)
        self._refresh_templates()
        log_box=QGroupBox('Журнал роботи');log_l=QVBoxLayout(log_box)
        self.logs=QTextEdit();self.logs.setReadOnly(True)
        log_l.addWidget(self.logs)
        right.addWidget(log_box,1)

    def _build_teaching(self):
        tab=QWidget()
        self.tabs.addTab(tab,'🧭 Навчання маршруту')
        lay=QVBoxLayout(tab)
        intro=QLabel('РЕЖИМ ПРОВІДНИКА  /  ТИ ПОКАЗУЄШ — GAMEPILOT ЗАПАМ’ЯТОВУЄ')
        intro.setStyleSheet('font-size:17px;font-weight:750;color:#82e8cf;padding:12px 2px;')
        lay.addWidget(intro)
        description=QLabel(
            '1. Увімкни навчання. Керуй персонажем вручну та проходь безпечними стежками. '
            'Система записуватиме відносну траєкторію за зміщенням нерухомих об’єктів.\n'
            '2. Наведи ігровий курсор на камінь або перешкоду й натисни відповідну гарячу клавішу. '
            'Можна також натиснути на зображення у вкладці «Живий екран».\n'
            '3. Перевір карту. Натисни «Зберегти», потім дозволи керування та запусти F6. '
            'У цьому режимі GamePilot не досліджує невідомі клітинки, а йде лише пройденими тобою маршрутами.'
        )
        description.setWordWrap(True)
        description.setStyleSheet('color:#b9cfd6;font-size:13px;padding:10px;')
        lay.addWidget(description)
        group=QGroupBox('Навчання без автоматичних кліків')
        form=QVBoxLayout(group)
        self.teacher_box=QCheckBox('Увімкнути режим «Я показую — бот повторює»')
        self.teacher_box.setChecked(self.cfg.guided_mode)
        self.teacher_box.toggled.connect(self.toggle_guided_mode)
        form.addWidget(self.teacher_box)
        self.teacher_state=QLabel('Готовий до розмітки' if self.cfg.guided_mode else 'Режим вимкнено')
        self.teacher_state.setObjectName('subtitle');form.addWidget(self.teacher_state)
        hotkeys=QLabel('F7 — камінь T1     F9 — перешкода     F10 — вихід (заборона)     F11 — прохідне місце\n'
                       'Під час позначення курсор має стояти над об’єктом у вікні гри. F8 — аварійна зупинка.')
        hotkeys.setWordWrap(True);form.addWidget(hotkeys)
        tool_row=QHBoxLayout()
        tool_row.addWidget(QLabel('Інструмент для кліку по прев’ю:'))
        self.teach_tool=QComboBox()
        for name,key in [('Камінь T1','stone'),('Перешкода','block'),('Вихід','exit'),
                         ('Вільний прохід','walkable'),('Стерти позначку','clear')]:
            self.teach_tool.addItem(name,key)
        tool_row.addWidget(self.teach_tool);tool_row.addStretch()
        form.addLayout(tool_row)
        save=QPushButton('✓ ЗБЕРЕГТИ НАВЧЕНУ КАРТУ')
        save.setObjectName('primary');save.clicked.connect(self.save_map)
        form.addWidget(save)
        lay.addWidget(group)
        attention=QLabel('ВАЖЛИВО: навчання не визначає реальні координати гри. Якщо локалізація втрачена, '
                         'повернися до бази та переприв’яжи позицію. Не запускай автоматичний режим до перевірки виходів. '
                         'Для проходу краще пройти весь маршрут особисто; поодиноке позначення «вільно» не підтверджує прохідність усієї дороги.')
        attention.setWordWrap(True);attention.setObjectName('subtitle');lay.addWidget(attention)
        lay.addStretch()
        self.live.grid_enabled=True

    def toggle_guided_mode(self,enabled:bool):
        if self.runtime.bridge.enabled: self.emergency_stop()
        self.runtime.brain.pause('Змінено режим навчання')
        self.cfg.guided_mode=bool(enabled)
        self.runtime.teacher_active=bool(enabled)
        self.live.grid_enabled=True
        self.live.update()
        self.teacher_state.setText('Ручне навчання активне — керуй персонажем сам' if enabled else 'Режим вимкнено')
        self.cfg.save()
        self.log('Режим провідника: '+('увімкнено' if enabled else 'вимкнено'))

    def on_teach_preview_click(self,point):
        if not self.cfg.guided_mode:return
        try:
            msg=self.runtime.mark_taught(self.teach_tool.currentData(),*point)
            self.log(msg)
        except ValueError as e:self.log(str(e))

    def mark_cursor_hotkey(self,kind:str):
        if not self.cfg.guided_mode or self.runtime.brain.mode!=Mode.IDLE:return
        if not self.runtime.bridge._window_focused():return
        try:
            from pynput.mouse import Controller
            sx,sy=Controller().position
            ox,oy=self.runtime.bridge.monitor_origin
            msg=self.runtime.mark_taught(kind,sx-ox,sy-oy)
            self.log(msg)
        except (ValueError,OSError) as exc:self.log(f'Не вдалося позначити: {exc}')

    def _build_map(self):
        tab=QWidget();self.tabs.addTab(tab,'🗺  Карта')
        lay=QVBoxLayout(tab)
        tools=QHBoxLayout()
        tools.addWidget(QLabel('Позначити:'))
        self.map_tools=QComboBox()
        self.map_tools.addItem('Перешкода','block')
        self.map_tools.addItem('Вихід / заборонена зона','exit')
        self.map_tools.addItem('Стерти перешкоду','erase')
        self.map_tools.addItem('Змінити базу','base')
        tools.addWidget(self.map_tools)
        btn=QPushButton('Зберегти карту');btn.clicked.connect(self.save_map)
        tools.addWidget(btn)
        export=QPushButton('Експорт JSON');export.clicked.connect(self.export_map)
        tools.addWidget(export)
        anchor=QPushButton('Я на базі')
        anchor.setToolTip('Використовуйте лише якщо персонаж фізично стоїть на збереженій базі.')
        anchor.clicked.connect(self.confirm_base_position)
        tools.addWidget(anchor)
        reset=QPushButton('Нова локація')
        reset.setToolTip('Очистити карту після підтвердження і створити нову базу (0,0).')
        reset.clicked.connect(self.reset_location)
        tools.addWidget(reset)
        zoom=QSlider(Qt.Orientation.Horizontal);zoom.setRange(2,32);zoom.setValue(16)
        zoom.setMaximumWidth(130);tools.addWidget(QLabel('Масштаб:'));tools.addWidget(zoom)
        tools.addStretch();lay.addLayout(tools)
        self.map_canvas=MapCanvas(self.world)
        self.map_tools.currentIndexChanged.connect(lambda:self._set_map_tool())
        zoom.valueChanged.connect(self.manual_map_zoom)
        self.auto_zoom_box=QCheckBox('Автомасштаб / пройдена територія')
        self.auto_zoom_box.setChecked(self.cfg.map_auto_zoom)
        self.map_canvas.auto_zoom=self.cfg.map_auto_zoom
        self.auto_zoom_box.toggled.connect(self.toggle_auto_zoom)
        tools.addWidget(self.auto_zoom_box)
        self.map_canvas.changed.connect(self.log)
        self.map_canvas.changed.connect(lambda _: self.runtime.save_map())
        lay.addWidget(self.map_canvas,1)
        legend=QLabel('🟢 Персонаж   🔵 База   🟠 Каміння   ▧ Сірий — непрохідно   ▧ Червоний — зона виходу')
        legend.setObjectName('subtitle');lay.addWidget(legend)

    def manual_map_zoom(self,value):
        self.map_canvas.auto_zoom=False
        self.auto_zoom_box.blockSignals(True)
        self.auto_zoom_box.setChecked(False)
        self.auto_zoom_box.blockSignals(False)
        self.cfg.map_auto_zoom=False
        self.map_canvas.zoom=value
        self.map_canvas.update()

    def toggle_auto_zoom(self,enabled):
        self.cfg.map_auto_zoom=bool(enabled)
        self.map_canvas.auto_zoom=bool(enabled)
        if enabled:self.map_canvas.zoom=16
        self.map_canvas.update()
        self.cfg.save()

    def toggle_live_grid(self,enabled):
        if enabled:
            if not self.live_grid.full_size[0]:
                self.log('Сітка: дочекайтеся визначення розміру монітора.')
                enabled=False
            elif not self.live_grid.enable():
                self.log('Сітка поверх гри недоступна: Windows не дозволяє виключити її із захоплення. Сітка в прев’ю працює.')
                enabled=False
        if not enabled:
            self.live_grid.hide()
        self.live_grid_enabled=bool(enabled)
        self.cfg.live_grid_enabled=bool(enabled)
        self.grid_overlay_button.blockSignals(True)
        self.grid_overlay_button.setChecked(bool(enabled))
        self.grid_overlay_button.setText('▦ Сітка на грі: ON / F5' if enabled else '▦ Сітка на грі: OFF / F5')
        self.grid_overlay_button.blockSignals(False)
        self.cfg.save()

    def _build_settings(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();scroll.setWidget(content)
        self.tabs.addTab(scroll,'⚙  Адмін-панель')
        lay=QVBoxLayout(content)
        group=QGroupBox('Збір та пошук');form=QFormLayout(group)
        self.goal=QSpinBox();self.goal.setRange(1,40);self.goal.setValue(self.cfg.stone_goal)
        form.addRow('Потрібно каменів:',self.goal)
        self.respawn=QSpinBox();self.respawn.setRange(15,86400);self.respawn.setValue(self.cfg.respawn_t1_seconds)
        form.addRow('Відновлення T1 (сек):',self.respawn)
        self.tier_boxes={}
        for tier in range(2,9):
            widget=QSpinBox();widget.setRange(30,86400)
            widget.setValue(self.cfg.timers_seconds.get(f'T{tier}',3600))
            widget.setSuffix(' сек')
            self.tier_boxes[tier]=widget
            form.addRow(f'Відновлення T{tier}:',widget)
        self.need_tooltip=QCheckBox('Вимагати підтвердження назви ресурсу');self.need_tooltip.setChecked(True)
        self.need_tooltip.setEnabled(False)
        form.addRow(self.need_tooltip)
        self.explore=QCheckBox('Автоматично досліджувати');self.explore.setChecked(self.cfg.auto_explore)
        self.gather=QCheckBox('Автоматично збирати');self.gather.setChecked(self.cfg.auto_gather)
        form.addRow(self.explore);form.addRow(self.gather)
        lay.addWidget(group)
        group2=QGroupBox('Розпізнавання / продуктивність');form2=QFormLayout(group2)
        self.fps=QSpinBox();self.fps.setRange(1,50);self.fps.setValue(self.cfg.capture_fps)
        self.monitor_index=QSpinBox();self.monitor_index.setRange(1,8);self.monitor_index.setValue(self.cfg.monitor_index)
        self.analysis=QDoubleSpinBox();self.analysis.setRange(.5,20);self.analysis.setSingleStep(.5);self.analysis.setValue(self.cfg.analysis_fps)
        self.threshold=QDoubleSpinBox();self.threshold.setRange(.55,.99);self.threshold.setSingleStep(.01);self.threshold.setValue(self.cfg.confidence)
        form2.addRow('Максимум FPS захоплення:',self.fps)
        form2.addRow('Монітор (потрібен перезапуск):',self.monitor_index)
        form2.addRow('Частота аналізу (FPS):',self.analysis)
        form2.addRow('Точність шаблону:',self.threshold)
        lay.addWidget(group2)
        group3=QGroupBox('Безпека пересування');form3=QFormLayout(group3)
        self.stall=QDoubleSpinBox();self.stall.setRange(2,20);self.stall.setValue(self.cfg.stall_seconds)
        self.uncertainty=QSpinBox();self.uncertainty.setRange(30,1000);self.uncertainty.setValue(round(self.cfg.max_position_uncertainty_px))
        form3.addRow('Час без прогресу (сек):',self.stall)
        form3.addRow('Максимальна похибка (пікс.):',self.uncertainty)
        lay.addWidget(group3)
        group4=QGroupBox('Контроль клієнта й захисні ліміти');form4=QFormLayout(group4)
        self.client_title=QLineEdit(self.cfg.window_title_contains)
        self.client_title.setPlaceholderText('Частина заголовка вікна тестової гри')
        self.client_title.setToolTip('Автоматичні кліки виконуватимуться лише коли це вікно активне.')
        self.terrain_survey=QCheckBox('Аналізувати навчені зразки води / скель')
        self.terrain_survey.setChecked(self.cfg.enable_terrain_survey)
        self.exit_survey_box=QCheckBox('Позначати виходи за навченим шаблоном (потребує перевірки)')
        self.exit_survey_box.setChecked(self.cfg.enable_exit_survey)
        self.session_minutes=QSpinBox();self.session_minutes.setRange(1,1440);self.session_minutes.setValue(self.cfg.max_session_minutes)
        self.max_clicks=QSpinBox();self.max_clicks.setRange(10,50000);self.max_clicks.setValue(self.cfg.max_automatic_clicks)
        self.cooldown=QSpinBox();self.cooldown.setRange(5,3600);self.cooldown.setValue(self.cfg.cooldown_failure_seconds)
        form4.addRow('Назва активного вікна:',self.client_title)
        form4.addRow(self.terrain_survey)
        form4.addRow(self.exit_survey_box)
        form4.addRow('Ліміт сесії (хв):',self.session_minutes)
        form4.addRow('Максимум кліків:',self.max_clicks)
        form4.addRow('Пауза після невдачі (сек):',self.cooldown)
        lay.addWidget(group4)
        save=QPushButton('Застосувати та зберегти параметри');save.clicked.connect(self.apply_settings)
        lay.addWidget(save)
        description=QLabel('⚠ Щоб змінити монітор, зупиніть застосунок, відредагуйте monitor_index у settings.json і перезапустіть. '
                           'Виходи позначайте на карті до запуску автоматичних кліків. Автоматичне розпізнавання виходів у цій версії ще не реалізоване.')
        description.setWordWrap(True);description.setObjectName('subtitle')
        lay.addWidget(description);lay.addStretch()

    def _setup_hotkey(self):
        try:
            from pynput import keyboard
            def pressed(key):
                if key==keyboard.Key.f6:
                    if self.runtime.bridge.enabled and self.runtime.bridge._window_focused():
                        self.hotkey_start.emit()
                if key==keyboard.Key.f5:self.hotkey_toggle_grid.emit()
                if key==keyboard.Key.f7: self.hotkey_teach.emit('stone')
                if key==keyboard.Key.f9: self.hotkey_teach.emit('block')
                if key==keyboard.Key.f10: self.hotkey_teach.emit('exit')
                if key==keyboard.Key.f11: self.hotkey_teach.emit('walkable')
                if key==keyboard.Key.f8:
                    # Directly disarm in listener thread to minimize stop latency.
                    self.runtime.bridge.disarm()
                    self.runtime.status.emit('АВАРІЙНИЙ СТОП F8')
            self._hotkey_listener=keyboard.Listener(on_press=pressed)
            self._hotkey_listener.daemon=True
            self._hotkey_listener.start()
        except Exception as e:
            self.log(f'Глобальна клавіша F8 недоступна: {e}. Використайте кнопку СТОП.')

    def _refresh_templates(self):
        self.lab_stone.setText('Шаблон T1: '+('✓' if self.runtime.resource_template is not None else 'не навчено'))
        self.lab_depleted.setText('Виснажений T1: '+('✓' if self.runtime.depleted_template is not None else 'не навчено'))
        self.lab_tip.setText('Підказка T1: '+('✓' if self.runtime.tooltip_template is not None else 'не навчено'))
        self.lab_bar.setText('Індикатор збору: '+('✓' if self.runtime.progress_roi else 'не налаштовано'))
        self.lab_terrain.setText('Зразки місцевості: '+(', '.join(p.name for p in self.runtime.survey.profiles) or 'немає'))
        self.lab_exit.setText('Шаблон виходу: '+('✓' if self.runtime.exit_template is not None else 'не навчено'))

    def _set_map_tool(self):
        self.map_canvas.tool=self.map_tools.currentData()
        self.map_canvas.update()

    def on_monitor(self,left,top,w,h):
        self.live.capture_full_w=w;self.live.capture_full_h=h
        self.live_grid.set_monitor(left,top,w,h)
        self.log(f'Монітор: {w}×{h}, початок ({left},{top})')

    def on_frame(self,image):
        now=time.monotonic()
        if self.last_frame_time>0:
            delta=now-self.last_frame_time
            self.display_fps=self.display_fps*.85+(1/max(.0001,delta))*.15
        self.last_frame_time=now
        self.live.set_image(image)

    def on_detection(self,detections):
        self.live.detections=detections
        self.live.update()
        if self.live_grid_enabled:
            self.live_grid.set_detections(detections)

    def on_area_selected(self,roi):
        kind=self.tool_select.currentData()
        if self.runtime.set_template(kind,roi):
            self._refresh_templates()
            self.log(f'Навчено {kind}: {roi}')
        else:self.log('Область занадто мала; виберіть більшу')

    def on_stats(self,text):
        if hasattr(self,'arm_box') and self.arm_box.isChecked() and not self.runtime.bridge.enabled:
            self.arm_box.blockSignals(True)
            self.arm_box.setChecked(False)
            self.arm_box.blockSignals(False)
        self.stats.setText(f'Прев’ю: {self.display_fps:.1f} FPS | {text}')
        state=self.runtime.brain.mode.value+' | '+('КЕРУВАННЯ УВІМКНЕНО' if self.runtime.bridge.enabled else 'БЕЗ КЛІКІВ')
        self.state.setText(state)
        self.mini_overlay.mode.setText(state)
        self.mini_overlay.metrics.setText(f'Прев’ю: {self.display_fps:.1f} FPS | T1: {len(self.world.resources)} | Кліки: {self.runtime.bridge.automatic_clicks}')

    def toggle_overlay(self):
        if self.mini_overlay.isVisible():
            self.mini_overlay.hide()
        else:
            self.mini_overlay.show()

    def refresh_map(self):
        self.map_canvas.update()
        if self.live_grid_enabled:self.live_grid.update()

    def log(self,message:str):
        # Append-only incident journal; roll at ~3 MB, not on every UI refresh.
        try:
            path=app_home()/'events.log'
            if path.exists() and path.stat().st_size>3_000_000:
                path.replace(app_home()/'events.previous.log')
            with path.open('a',encoding='utf-8') as stream:
                stream.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n')
        except OSError:
            pass
        if hasattr(self,'logs'):
            self.logs.append(f'[{time.strftime("%H:%M:%S")}] {message}')
            if self.logs.document().blockCount()>250:
                self.logs.clear();self.logs.append('[Журнал очищено: обмеження 250 записів]')

    def apply_settings(self):
        self.cfg.stone_goal=self.goal.value()
        self.cfg.respawn_t1_seconds=self.respawn.value()
        self.cfg.capture_fps=self.fps.value()
        self.cfg.monitor_index=self.monitor_index.value()
        self.cfg.analysis_fps=self.analysis.value()
        self.cfg.confidence=self.threshold.value()
        self.cfg.stall_seconds=self.stall.value()
        self.cfg.max_position_uncertainty_px=self.uncertainty.value()
        self.cfg.auto_explore=self.explore.isChecked()
        self.cfg.auto_gather=self.gather.isChecked()
        self.cfg.window_title_contains=self.client_title.text().strip()
        self.cfg.enable_terrain_survey=self.terrain_survey.isChecked()
        self.cfg.enable_exit_survey=self.exit_survey_box.isChecked()
        self.cfg.max_session_minutes=self.session_minutes.value()
        self.cfg.max_automatic_clicks=self.max_clicks.value()
        self.cfg.cooldown_failure_seconds=self.cooldown.value()
        self.cfg.timers_seconds['T1']=self.cfg.respawn_t1_seconds
        for tier,widget in self.tier_boxes.items():
            self.cfg.timers_seconds[f'T{tier}']=widget.value()
        self.runtime.bridge.window_title_contains=self.cfg.window_title_contains
        self.runtime.bridge.click_limit=self.cfg.max_automatic_clicks
        self.cfg.save()
        self.log('Параметри збережено')

    def toggle_input(self,checked):
        if not checked:
            self.runtime.brain.pause('Керування вимкнено')
            return
        self.apply_settings()
        problems=[]
        if self.runtime.resource_template is None:problems.append('Шаблон каменя T1')
        if self.runtime.tooltip_template is None:problems.append('Шаблон назви ресурсу при наведенні')
        if self.cfg.auto_gather and self.runtime.progress_roi is None:problems.append('Область прогрес-бару')
        if self.cfg.auto_gather and self.runtime.depleted_template is None:problems.append('Шаблон виснаженого каменя T1')
        if not self.position_confirmed:
            problems.append('Позиція після перезапуску: натисніть «Я на базі» або «Нова локація»')
        if self.cfg.auto_explore and len(self.world.exits)<2:
            problems.append('Для безпечного автодослідження спочатку позначте 2–4 виходи')
        if not self.cfg.window_title_contains:
            problems.append('Назва вікна тестового клієнта (адмін-панель)')
        if problems:
            QMessageBox.warning(self,'Потрібне навчання','Перед увімкненням керування налаштуйте:\n• '+'\n• '.join(problems))
            self.arm_box.blockSignals(True);self.arm_box.setChecked(False);self.arm_box.blockSignals(False)
            return
        confirm=QMessageBox.question(self,'Підтвердіть керування',
             'Автоматичні кліки керуватимуть реальною мишею на вибраному моніторі.\n'
             'Переконайтеся, що відкрита правильна тестова локація, а виходи позначені.\n'
             'Для зупинки натисніть F8. Увімкнути?',
             QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if confirm!=QMessageBox.StandardButton.Yes:
            self.arm_box.blockSignals(True);self.arm_box.setChecked(False);self.arm_box.blockSignals(False)
            return
        self.runtime.bridge.enabled=True
        self.log('Керування дозволено; поверніться у вікно гри й натисніть F6. F8 — стоп.')

    def _start_when_game_focused(self):
        if not self.runtime.bridge.enabled:
            self.log('Спочатку увімкніть керування')
            return
        if not self.runtime.bridge._window_focused():
            self.log('Старт відкладено: активуйте вікно тестової гри й натисніть F6')
            return
        if self.runtime.brain.mode!=Mode.IDLE:
            self.log('GamePilot уже працює')
            return
        if self.cfg.guided_mode:
            resources=[r for r in self.world.resources.values() if r.verified]
            if not resources:
                self.log('Немає позначених вручну каменів T1. Спочатку навчи карту (F7).')
                return
            if self.world.uncertainty>self.cfg.max_position_uncertainty_px*.75:
                self.log('Похибка позиції велика: переприв’яжи позицію на базі перед стартом')
                return
            viable=[r for r in resources if self.world.plan_taught((r.x,r.y))]
            if not viable:
                self.log('Немає перевіреного маршруту до позначених каменів. Пройди туди вручну.')
                return
        self.runtime.brain.arm()

    def start_bot(self):
        if not self.runtime.bridge.enabled:
            self.log('Спочатку увімкніть автоматичні кліки')
            return
        self.log('Старт через 5 секунд: активуйте вікно гри. Або натисніть F6 у грі.')
        QTimer.singleShot(5000, self._start_when_game_focused)

    def emergency_stop(self):
        self.runtime.brain.pause('АВАРІЙНИЙ СТОП')
        self.arm_box.blockSignals(True);self.arm_box.setChecked(False);self.arm_box.blockSignals(False)
        self.state.setText('ЗУПИНЕНО')

    def confirm_base_position(self):
        if self.runtime.bridge.enabled:
            self.emergency_stop()
        confirm=QMessageBox.question(self,'Підтвердження бази',
              'Персонаж зараз фізично стоїть у точці збереженої бази?\n'
              'Якщо ні, карта буде прив’язана неправильно.',
              QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if confirm!=QMessageBox.StandardButton.Yes:return
        self.world.player_x=self.world.base_x
        self.world.player_y=self.world.base_y
        self.world.uncertainty=0.
        self.world.visited.add(self.world.cell(self.world.player_x,self.world.player_y))
        self.position_confirmed=True
        self.runtime.survey.evidence.clear()
        self.runtime.save_map()
        self.log('Позицію підтверджено вручну: персонаж на базі')
        self.map_canvas.update()

    def reset_location(self):
        if self.runtime.bridge.enabled:
            self.emergency_stop()
        confirm=QMessageBox.question(self,'Очистити карту',
             'Створити нову карту? Поточні ресурси, перешкоди та виходи буде очищено.\n'
             'Спочатку збережіть резервну копію карти, якщо вона потрібна.',
             QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if confirm!=QMessageBox.StandardButton.Yes:return
        fresh=WorldMap(cell_px=self.cfg.cell_px)
        self.world.player_x=fresh.player_x;self.world.player_y=fresh.player_y
        self.world.base_x=fresh.base_x;self.world.base_y=fresh.base_y
        self.world.uncertainty=0.
        self.world.visited.clear();self.world.blocked.clear()
        self.world.exits.clear();self.world.forbidden.clear()
        self.world.resources.clear();self.world.next_resource_id=1
        self.world.step=0
        self.cfg.guided_mode=bool(self.teacher_box.isChecked())
        self.runtime.survey.evidence.clear();self.runtime.exit_survey.evidence.clear()
        self.runtime.brain.nav.clear()
        self.position_confirmed=True
        self.runtime.save_map()
        self.log('Нова локація: карту очищено, база (0, 0)')
        self.map_canvas.update()

    def export_map(self):
        path, _ = QFileDialog.getSaveFileName(self,'Експорт карти',str(app_home()/'map_export.json'),'JSON (*.json)')
        if not path:return
        try:
            self.world.export_geojson(Path(path))
            self.log(f'Карту експортовано: {path}')
        except (OSError,ValueError) as exc:
            self.log(f'Помилка експорту карти: {exc}')

    def save_map(self):
        self.runtime.save_map()
        self.log('Карту збережено')

    def closeEvent(self,event):
        self.runtime.stop()
        self.live_grid.hide()
        self.live_grid.close()
        self.mini_overlay.close()
        self.cfg.save()
        if self._hotkey_listener:
            self._hotkey_listener.stop()
        event.accept()


def main():
    import sys
    app=QApplication(sys.argv)
    app.setStyle('Fusion')
    window=MainWindow()
    window.show()
    sys.exit(app.exec())
