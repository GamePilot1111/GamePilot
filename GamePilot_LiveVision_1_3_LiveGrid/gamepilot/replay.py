"""Offline recognition/mapping rehearsal from a recorded game video.

Never imports or invokes the input controller. Handy for calibrating resource
patterns without touching the active game client or the Windows mouse.

Usage:
  python -m gamepilot.replay --video recording.mp4 --template stone.png \
      --output rehearsal_report.json --preview rehearsal_last.jpg
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import time
import cv2
import numpy as np

from .config import Settings
from .mapping import WorldMap
from .vision import estimate_camera_shift,match_template,load_template,progress_bar_visible
from .terrain import TerrainSurvey,ExitSurvey


def analyze_video(video: Path, template: Path | None = None,
                  settings: Settings | None = None, every: int = 1,
                  max_frames: int = 0, terrain: TerrainSurvey | None = None,
                  progress_roi: tuple[int,int,int,int] | None = None,
                  exit_template: Path | None = None) -> tuple[dict,np.ndarray | None]:
    """Return machine-readable analysis and annotated last sampled frame."""
    if every<1: raise ValueError('every must be >=1')
    cfg=settings or Settings()
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise OSError(f'Cannot open video: {video}')
    tpl=load_template(template) if template else None
    exit_tpl=load_template(exit_template) if exit_template else None
    survey=terrain or TerrainSurvey()
    portals=ExitSurvey()
    wm=WorldMap(cell_px=cfg.cell_px)
    prev=None
    last_frame=None
    count=0
    processed=0
    motion_measurements=[]
    detection_counts=[]
    bar_frames=0
    rejected=0
    started=time.monotonic()
    source_fps=float(cap.get(cv2.CAP_PROP_FPS) or 0.)
    try:
        while True:
            ok,frame=cap.read()
            if not ok or (max_frames and count>=max_frames):break
            count+=1
            if (count-1)%every:continue
            processed+=1
            h,w=frame.shape[:2]
            motion=estimate_camera_shift(prev,frame)
            if prev is not None:
                if motion.confidence>=cfg.min_motion_confidence:
                    wm.update_motion(motion.dx,motion.dy,motion.confidence)
                    motion_measurements.append(motion.confidence)
                else:
                    rejected+=1
            prev=frame
            stones=match_template(frame,tpl,cfg.confidence) if tpl is not None else []
            wm.relocalize([(d.x,d.y) for d in stones],w,h,cfg.player_x_ratio,cfg.player_y_ratio)
            for d in stones:
                wm.add_observation(d.x,d.y,w,h,cfg.player_x_ratio,cfg.player_y_ratio)
            detection_counts.append(len(stones))
            if survey.profiles and cfg.enable_terrain_survey:
                survey.scan(frame,wm,cfg)
            if exit_tpl is not None and cfg.enable_exit_survey:
                detected=match_template(frame,exit_tpl,max(.91,cfg.confidence),scales=(1.,))
                portals.scan(detected,wm,w,h,cfg)
            if progress_bar_visible(frame,progress_roi):
                bar_frames+=1
            last_frame=frame.copy()
            for d in stones:
                cv2.rectangle(last_frame,(d.x-d.width//2,d.y-d.height//2),
                              (d.x+d.width//2,d.y+d.height//2),(85,225,175),2)
                cv2.putText(last_frame,f'T1 {d.confidence:.2f}',(d.x-d.width//2,max(18,d.y-d.height//2-5)),
                            cv2.FONT_HERSHEY_SIMPLEX,.5,(85,225,175),1,cv2.LINE_AA)
    finally:
        cap.release()
    if not count:raise ValueError('Video has no decoded frames')
    seconds=time.monotonic()-started
    result={
        'video':str(video),'source_frames':count,'source_fps':source_fps,
        'processed_frames':processed,'sample_every':every,
        'analysis_wall_seconds':round(seconds,3),
        'analysis_fps':round(processed/max(.000001,seconds),2),
        'frames_with_stone':sum(x>0 for x in detection_counts),
        'maximum_stones_in_frame':max(detection_counts,default=0),
        'unique_stone_candidates':len(wm.resources),
        'verified_stones':sum(r.verified for r in wm.resources.values()),
        'progress_bar_frames':bar_frames,
        'successful_motion_frames':len(motion_measurements),
        'rejected_motion_frames':rejected,
        'mean_motion_confidence':round(sum(motion_measurements)/len(motion_measurements),3) if motion_measurements else 0.,
        'relative_player_xy':[round(wm.player_x,2),round(wm.player_y,2)],
        'position_uncertainty_px':round(wm.uncertainty,2),
        'blocked_cells':len(wm.blocked),
        'exit_candidates_confirmed':len(wm.exits),
        'notes':['OFFLINE ANALYSIS ONLY: no game inputs performed',
                 'Detected objects are candidates; tooltips not verifiable from this replay',
                 'Relative coordinates are not calibrated world coordinates']
    }
    return result,last_frame


def main():
    parser=argparse.ArgumentParser(description='GamePilot offline video recognition rehearsal (no mouse clicks)')
    parser.add_argument('--video',required=True,type=Path)
    parser.add_argument('--template',type=Path)
    parser.add_argument('--exit-template',type=Path)
    parser.add_argument('--output',type=Path,default=Path('gamepilot_replay_report.json'))
    parser.add_argument('--preview',type=Path)
    parser.add_argument('--every',type=int,default=1)
    parser.add_argument('--max-frames',type=int,default=0)
    args=parser.parse_args()
    cfg=Settings()
    cfg.enable_exit_survey=bool(args.exit_template)
    report,frame=analyze_video(args.video,args.template,cfg,every=args.every,
                               max_frames=args.max_frames,exit_template=args.exit_template)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.preview and frame is not None:
        args.preview.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(args.preview),frame)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
