from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os


def app_home() -> Path:
    root = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'GamePilotLiveVision'
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Settings:
    capture_fps: int = 20
    analysis_fps: float = 3.0
    max_preview_width: int = 940
    confidence: float = 0.82
    tooltip_confidence: float = 0.77
    stone_goal: int = 4
    cell_px: int = 76
    player_x_ratio: float = 0.5
    player_y_ratio: float = 0.52
    min_motion_confidence: float = 0.47
    max_position_uncertainty_px: float = 230.0
    stall_seconds: float = 5.0
    click_interval_seconds: float = 1.3
    waypoint_radius_px: float = 40.0
    resource_radius_px: float = 75.0
    respawn_t1_seconds: int = 90
    hover_settle_seconds: float = 0.55
    gather_key: str = 'f'
    require_tooltip: bool = True
    guided_mode: bool = False
    live_grid_enabled: bool = False
    map_auto_zoom: bool = True
    map_show_full_footprint: bool = True
    auto_explore: bool = True
    auto_gather: bool = True
    enable_input: bool = False
    window_title_contains: str = ""
    enable_terrain_survey: bool = False
    enable_exit_survey: bool = False
    auto_revisit_timers: bool = True
    max_session_minutes: int = 120
    max_automatic_clicks: int = 2000
    cooldown_failure_seconds: int = 180
    safety_margin_cells: int = 1
    # Pixel-perfect capture: defaults to primary display, chosen by dropdown.
    monitor_index: int = 1
    # Optional OCR backup; the image tooltip template can verify without OCR.
    resource_names: list[str] = field(default_factory=lambda: ['грубий камінь', 'rough stone', 'камень'])
    timers_seconds: dict[str, int] = field(default_factory=lambda: {
        'T1': 90, 'T2': 600, 'T3': 600, 'T4': 600,
        'T5': 2400, 'T6': 5400, 'T7': 19800, 'T8': 23760
    })

    @classmethod
    def load(cls, path: Path | None = None) -> 'Settings':
        path = path or app_home() / 'settings.json'
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            allowed = cls.__dataclass_fields__
            return cls(**{k: v for k, v in raw.items() if k in allowed})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or app_home() / 'settings.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
