"""Screen/relative-world transforms and bounded adaptive map scale.

Screen position is an estimate only: it requires synchronized camera tracking.
"""
from __future__ import annotations
import math


def world_to_screen(world_x:float, world_y:float, player_x:float, player_y:float,
                    width:float,height:float,x_ratio:float=.5,y_ratio:float=.52)->tuple[float,float]:
    return (width*x_ratio + world_x-player_x,
            height*y_ratio + world_y-player_y)


def screen_to_world(x:float,y:float,player_x:float,player_y:float,
                    width:float,height:float,x_ratio:float=.5,y_ratio:float=.52)->tuple[float,float]:
    return (player_x+x-width*x_ratio,player_y+y-height*y_ratio)


def grid_lines(screen_length:float,player_offset:float,anchor:float,cell_px:float):
    """Grid lines anchored in map space despite moving follow-camera."""
    if cell_px<=0: return []
    first=(anchor-player_offset)%cell_px
    n=math.ceil(screen_length/cell_px)+1
    return [first+idx*cell_px for idx in range(n) if 0<=first+idx*cell_px<=screen_length]


def adaptive_zoom(cells:set[tuple[int,int]], player_cell:tuple[float,float],
                  viewport:tuple[int,int], previous:float=16.,base:float=16.,
                  padding_cells:float=4.,min_zoom:float=2.,max_zoom:float=32.,
                  zoom_out_only:bool=True)->float:
    """Fit explored footprint in viewport; optionally never zoom back in."""
    if not cells:return min(previous,base) if zoom_out_only else base
    xs=[c[0] for c in cells]; ys=[c[1] for c in cells]
    xs.append(player_cell[0]); ys.append(player_cell[1])
    dx=max(xs)-min(xs)+padding_cells*2
    dy=max(ys)-min(ys)+padding_cells*2
    w,h=viewport
    fit=min(max(1,w)/max(1,dx),max(1,h)/max(1,dy))
    target=max(min_zoom,min(max_zoom,base,fit))
    return min(previous,target) if zoom_out_only else target
