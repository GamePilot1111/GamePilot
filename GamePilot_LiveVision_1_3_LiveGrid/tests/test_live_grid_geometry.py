import math
from gamepilot.display_geometry import (world_to_screen,screen_to_world,
                                        grid_lines,adaptive_zoom)


def test_world_screen_roundtrip():
    for x,y in [(-260.,90.),(0.,0.),(1362.,-45.)]:
        sx,sy=world_to_screen(x,y,140,230,1920,1080,.5,.52)
        result=screen_to_world(sx,sy,140,230,1920,1080,.5,.52)
        assert result==(x,y)


def test_grid_stays_on_map_while_camera_pans():
    screen_w=1000
    cell=75
    # Vertical line positions at two camera offsets; both correspond to
    # the same world-spaced grid shifted by the camera motion.
    a=grid_lines(screen_w,0,500-0,cell)
    b=grid_lines(screen_w,0,500-18,cell)
    assert all(0<=q<=screen_w for q in a+b)
    assert math.isclose((a[0]-b[0])%cell,18%cell)


def test_grid_bounded_and_empty_cell():
    assert grid_lines(100,0,0,0)==[]
    assert len(grid_lines(100,0,31,10))<=12


def test_map_zoom_decreases_with_territory():
    small={(x,y) for x in range(-2,3) for y in range(-2,3)}
    large=small|{(40,30),(-35,-28)}
    z1=adaptive_zoom(small,(0,0),(640,420),previous=16)
    z2=adaptive_zoom(large,(0,0),(640,420),previous=z1)
    assert z1==16
    assert 2<=z2<z1
    assert adaptive_zoom(small,(0,0),(640,420),previous=z2)==z2


def test_auto_fit_handles_empty_and_small_windows():
    assert adaptive_zoom(set(),(0,0),(0,0),previous=8)==8
    assert math.isfinite(adaptive_zoom({(0,0),(9999,9999)},(0,0),(0,0)))


def test_screen_grid_positions_change_continuously():
    lines1=grid_lines(840,0,425.1,76)
    lines2=grid_lines(840,0,425.2,76)
    assert abs(lines2[0]-lines1[0])<.2
