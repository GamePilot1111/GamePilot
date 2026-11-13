from pathlib import Path
import pytest
from gamepilot.config import Settings
from gamepilot.mapping import WorldMap
from gamepilot.controller import Brain, InputBridge, Observation, Mode, Navigator


def world():
    return WorldMap(cell_px=50)


def test_manual_resource_coordinates_and_deduplication():
    m=world()
    r=m.teach_resource(160,100,200,200,.5,.5)
    assert (r.x,r.y)==(60,0) and r.verified and r.tier==1
    same=m.teach_resource(162,102,200,200,.5,.5)
    assert same.id==r.id and len(m.resources)==1


def test_teacher_points_bounds_and_tier():
    m=world()
    with pytest.raises(ValueError):m.teach_resource(999,15,200,100,.5,.5)
    with pytest.raises(ValueError):m.teach_resource(10,15,200,100,.5,.5,tier=9)
    with pytest.raises(ValueError):m.teach_marker('unknown',10,15,200,100,.5,.5)


def test_marking_obstacles_exits_and_walkability():
    m=world()
    c=m.teach_marker('block',150,100,200,200,.5,.5)
    assert c==(1,0) and not m.passable(c)
    with pytest.raises(ValueError):m.teach_marker('walkable',150,100,200,200,.5,.5)
    m.teach_marker('clear',150,100,200,200,.5,.5)
    assert m.passable(c)
    m.teach_marker('exit',150,100,200,200,.5,.5)
    assert not m.passable((1,0)) and not m.passable((2,0))
    m.teach_marker('clear',150,100,200,200,.5,.5)
    assert m.passable((2,0))


def test_taught_segment_diagonal_connected():
    m=world()
    m.mark_walked_segment((0,0),(150,150))
    assert (0,0) in m.visited and (3,3) in m.visited
    assert m.plan_taught((150,150),arrival_radius_cells=0)


def test_taught_route_does_not_cross_unknown():
    m=world()
    m.visited={(0,0),(1,0),(2,0),(3,0)}
    assert m.plan_taught((300,0),arrival_radius_cells=0)==[]
    assert m.plan_taught((150,0),arrival_radius_cells=0)[-1]==(150,0)


def test_taught_route_reroutes_known_cells_around_wall():
    m=world()
    m.visited={(0,0),(0,1),(1,1),(2,1),(2,0)}
    m.blocked={(1,0)}
    route=m.plan_taught((100,0),arrival_radius_cells=0)
    assert (50,0) not in route
    assert route and route[-1]==(100,0)


def test_taught_route_respects_exit_buffer():
    m=world()
    m.visited={(0,0),(1,0),(2,0),(3,0),(4,0)}
    m.set_exit(100,0,radius=1)
    assert m.plan_taught((200,0),arrival_radius_cells=0)==[]


def test_taught_map_roundtrip(tmp_path:Path):
    m=world()
    m.mark_walked_segment((0,0),(100,0))
    r=m.teach_resource(160,100,200,200,.5,.5)
    m.teach_marker('exit',195,150,200,200,.5,.5)
    path=tmp_path/'map.json';m.save(path)
    copy=WorldMap.load(path)
    assert copy.visited==m.visited and copy.forbidden==m.forbidden
    assert copy.resources[r.id].verified


def test_manual_mode_never_starts_exploration():
    cfg=Settings(guided_mode=True,auto_explore=True)
    m=world();bridge=InputBridge()
    brain=Brain(cfg,m,bridge,lambda _:None)
    brain.mode=Mode.SEARCH
    obs=Observation(200,200,1,[])
    brain._seek(obs,0)
    assert brain.mode==Mode.SEARCH and brain.nav.goal is None


def test_no_guided_waypoints_means_failed_not_speculative_click():
    cfg=Settings(guided_mode=True,cell_px=50)
    m=world()
    nav=Navigator(m,cfg)
    nav.set_goal((400,0))
    assert nav.waypoints==[]
    assert nav.tick(InputBridge(),200,200,100.)=='failed'


def test_cannot_cut_diagonally_through_two_walls():
    m=world()
    m.visited={(0,0),(1,1)}
    m.blocked={(1,0),(0,1)}
    assert m.plan_taught((50,50),arrival_radius_cells=0)==[]


def test_guided_command_segment_must_be_walked():
    m=world()
    m.visited={(0,0),(1,0),(2,0)}
    assert m.line_taught_passable((0,0),(100,0))
    assert not m.line_taught_passable((0,0),(200,0))
    m.blocked.add((1,0))
    assert not m.line_taught_passable((0,0),(100,0))
