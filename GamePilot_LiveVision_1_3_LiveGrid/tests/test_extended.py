from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from gamepilot.config import Settings
from gamepilot.controller import InputBridge, Brain, Mode, Observation
from gamepilot.mapping import WorldMap
from gamepilot.terrain import TerrainProfile, TerrainSurvey


def test_terrain_learning_and_mask():
    bgr=np.full((48,48,3),(170,95,30),dtype=np.uint8)
    profile=TerrainProfile.learn('water',bgr)
    hsv=cv2.cvtColor(bgr,cv2.COLOR_BGR2HSV)
    assert profile.mask(hsv).mean()==1
    assert profile.mask(cv2.cvtColor(np.full_like(bgr,(0,0,240)),cv2.COLOR_BGR2HSV)).mean()==0


def test_terrain_rejects_gray():
    try:
        TerrainProfile.learn('bad',np.full((24,24,3),127,dtype=np.uint8))
    except ValueError:
        return
    assert False,'must reject gray sample'


def test_terrain_roundtrip():
    survey=TerrainSurvey([TerrainProfile('water',105,130,160)])
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'profiles.json'
        survey.save(path)
        reloaded=TerrainSurvey.load(path)
        assert len(reloaded.profiles)==1
        assert reloaded.profiles[0].name=='water'


def test_terrain_survey_requires_repeat_observation():
    world=WorldMap(cell_px=50)
    cfg=Settings(cell_px=50)
    frame=np.full((500,700,3),(185,100,30),dtype=np.uint8)
    survey=TerrainSurvey()
    survey.learn('water',frame[120:150,100:145])
    survey.scan(frame,world,cfg)
    assert not world.blocked
    for i in range(3):
        world.step+=1
        survey.scan(frame,world,cfg)
    assert world.blocked
    assert world.cell(world.player_x,world.player_y) not in world.blocked


def test_relocalization_two_landmarks():
    world=WorldMap(cell_px=75,player_x=0,player_y=0,uncertainty=85)
    for x,y in ((100,70),(-95,-90)):
        r=world.add_observation(400+x,300+y,800,600,.5,.5,True,now=100)
        r.observations=4
    world.player_x=11;world.player_y=-6
    old=world.uncertainty
    assert world.relocalize([(500,370),(305,210)],800,600,.5,.5)
    assert world.uncertainty<old
    assert abs(world.player_x)<11
    assert abs(world.player_y)<6


def test_relocalization_requires_two_landmarks():
    world=WorldMap()
    world.add_observation(450,300,800,600,.5,.5,True,now=100).observations=4
    assert not world.relocalize([(450,300)],800,600,.5,.5)


def test_resource_cooldown():
    world=WorldMap()
    res=world.add_observation(410,310,800,600,.5,.5,True,now=100)
    world.mark_failure(res.id,100,120)
    assert res.next_attempt_at==220
    assert res.failures==1


def test_session_limit_disarms():
    cfg=Settings(max_session_minutes=1)
    world=WorldMap()
    bridge=InputBridge();bridge.enabled=True
    brain=Brain(cfg,world,bridge,lambda _:None)
    brain.mode=Mode.SEARCH
    brain.session_started=10
    brain.tick(Observation(800,600,1.,[],now=80))
    assert brain.mode==Mode.IDLE
    assert not bridge.enabled


def test_input_click_limit():
    bridge=InputBridge();bridge.enabled=True
    bridge.configure_monitor(0,0,800,600)
    bridge.click_limit=1
    bridge._window_focused=lambda: True
    records=[]
    with patch.dict(sys.modules,{'pyautogui':SimpleNamespace(click=lambda *a:records.append(a))}):
        assert bridge.click(120,120,0)
        assert not bridge.click(120,120,0)
    assert len(records)==1


def test_export_map_json():
    world=WorldMap();world.set_blocked(76,0)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'map.json'
        world.export_geojson(path)
        import json
        data=json.loads(path.read_text(encoding='utf-8'))
        assert data['coordinate_system']=='local_relative_pixels'
        assert any(f['properties']['kind']=='blocked' for f in data['features'])


def test_exit_survey_requires_four_matches():
    from gamepilot.terrain import ExitSurvey
    from gamepilot.vision import Detection
    world=WorldMap(cell_px=50)
    survey=ExitSurvey(confirmations=4)
    cfg=Settings(cell_px=50)
    det=[Detection(600,240,40,40,.96)]
    for _ in range(3):
        assert survey.scan(det,world,800,600,cfg)==0
    assert not world.exits
    assert survey.scan(det,world,800,600,cfg)==1
    assert world.exits
    assert not world.passable(world.cell(200,-72))


def test_exit_survey_rejects_hud():
    from gamepilot.terrain import ExitSurvey
    from gamepilot.vision import Detection
    world=WorldMap()
    survey=ExitSurvey(2)
    for i in range(10):
        survey.scan([Detection(10,10,50,50,.99)],world,800,600,Settings())
    assert not world.exits


def test_window_focus_gate_fails_closed_on_nonwindows():
    bridge=InputBridge()
    bridge.window_title_contains='Private Test Game'
    # Linux does not expose Windows API; this should never silently permit clicks.
    if sys.platform != 'win32':
        assert not bridge._window_focused()


def test_controller_does_not_confirm_depletion_without_changed_stone():
    cfg=Settings()
    world=WorldMap()
    r=world.add_observation(480,320,800,600,.5,.5,True,now=100)
    bridge=InputBridge();bridge.enabled=True
    brain=Brain(cfg,world,bridge,lambda _:None)
    brain.mode=Mode.GATHER
    brain.target_id=r.id
    brain.gather_key_sent=True
    brain.gather_started=100
    brain.bar_seen=True
    brain.tick(Observation(800,600,1.,[],progress_bar=False,stone_changed=False,now=104))
    brain.tick(Observation(800,600,1.,[],progress_bar=False,stone_changed=False,now=107))
    assert r.depleted_at is None


def test_brain_does_not_start_unarmed():
    brain=Brain(Settings(),WorldMap(),InputBridge(),lambda _:None)
    brain.arm()
    assert brain.mode==Mode.IDLE


def test_click_segment_cannot_cross_exit_even_if_goal_open():
    world=WorldMap(cell_px=50)
    world.set_exit(150,0,radius=1)
    assert world.passable(world.cell(300,0))
    assert not world.line_passable((0,0),(300,0))
    assert world.line_passable((0,0),(0,100))


def test_focus_lost_pauses_instead_of_marking_obstacles():
    cfg=Settings(window_title_contains='Private Test Client')
    world=WorldMap()
    bridge=InputBridge();bridge.enabled=True;bridge.window_title_contains=cfg.window_title_contains
    brain=Brain(cfg,world,bridge,lambda _:None)
    brain.mode=Mode.SEARCH
    if sys.platform!='win32':
        brain.tick(Observation(800,600,1.,[],now=100))
        assert brain.mode==Mode.IDLE
        assert not world.blocked


def test_offline_replay_with_synthetic_video():
    from gamepilot.replay import analyze_video
    rng=np.random.default_rng(102)
    patch=rng.integers(12,230,size=(25,25,3),dtype=np.uint8)
    background=rng.integers(40,130,size=(260,360,3),dtype=np.uint8)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        path=root/'replay.avi'
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10,(360,260))
        assert writer.isOpened()
        for i in range(12):
            frame=background.copy()
            frame[110:135,175:200]=patch
            writer.write(frame)
        writer.release()
        templ=root/'stone.png'
        cv2.imwrite(str(templ),patch)
        report,annotated=analyze_video(path,templ,Settings(confidence=.7),every=2)
        assert report['source_frames']==12
        assert report['processed_frames']==6
        assert report['frames_with_stone']>0
        assert report['maximum_stones_in_frame']>=1
        assert annotated is not None and annotated.shape[:2]==(260,360)


def test_gather_click_denied_leads_to_skip_not_infinite_loop():
    cfg=Settings(cooldown_failure_seconds=60)
    world=WorldMap()
    r=world.add_observation(600,420,800,600,.5,.5,True,now=100)
    bridge=InputBridge();bridge.enabled=True  # no monitor configured, so point is denied
    bridge._window_focused=lambda: True
    brain=Brain(cfg,world,bridge,lambda _:None)
    brain.mode=Mode.GATHER
    brain.target_id=r.id
    brain.gather_started=100
    brain.tick(Observation(800,600,1.,[(600,420)],now=109))
    assert brain.mode==Mode.SEARCH
    assert r.next_attempt_at>0
