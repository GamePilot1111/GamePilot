from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path
import heapq
import json
import math
import time


@dataclass
class Resource:
    id: int
    x: float
    y: float
    tier: int = 1
    last_seen: float = 0.0
    depleted_at: float | None = None
    verified: bool = False
    failures: int = 0
    next_attempt_at: float = 0.0
    observations: int = 0
    label: str = 'T1 stone'


@dataclass
class WorldMap:
    cell_px: int = 76
    player_x: float = 0.0
    player_y: float = 0.0
    base_x: float = 0.0
    base_y: float = 0.0
    uncertainty: float = 0.0
    visited: set[tuple[int, int]] = field(default_factory=set)
    blocked: set[tuple[int, int]] = field(default_factory=set)
    forbidden: set[tuple[int, int]] = field(default_factory=set)
    exits: set[tuple[int, int]] = field(default_factory=set)
    resources: dict[int, Resource] = field(default_factory=dict)
    next_resource_id: int = 1
    step: int = 0

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return round(x / self.cell_px), round(y / self.cell_px)

    def center(self, cell: tuple[int, int]) -> tuple[float, float]:
        return cell[0] * self.cell_px, cell[1] * self.cell_px

    def update_motion(self, dx: float, dy: float, confidence: float) -> None:
        # A camera shift in one direction corresponds to player motion opposite.
        self.player_x -= dx
        self.player_y -= dy
        self.uncertainty += (abs(dx) + abs(dy)) * max(0.015, 0.25 * (1-confidence))
        self.visited.add(self.cell(self.player_x, self.player_y))
        self.step += 1

    def relocalize(self, detections: list[tuple[float,float]], width: int, height: int,
                   x_ratio: float, y_ratio: float) -> bool:
        """Correct accumulated odometry drift using >=2 independently known stones.

        Reject matching by index: a unique nearest-neighbour association is
        required for each stable landmark. A tight residual guards against
        false corrections from repeated similar-looking resources.
        """
        landmarks=[r for r in self.resources.values() if r.verified and r.observations>=2]
        if len(landmarks)<2 or len(detections)<2:
            return False
        candidates=[]
        used=set()
        cx=width*x_ratio;cy=height*y_ratio
        for sx,sy in detections:
            gx=self.player_x+sx-cx
            gy=self.player_y+sy-cy
            choices=sorted(((math.hypot(r.x-gx,r.y-gy),r) for r in landmarks if r.id not in used),
                           key=lambda pair: pair[0])
            if choices and choices[0][0]<self.cell_px*.65:
                r=choices[0][1]
                used.add(r.id)
                candidates.append((r.x-(sx-cx),r.y-(sy-cy)))
        if len(candidates)<2:
            return False
        mx=sorted(x for x,_ in candidates)[len(candidates)//2]
        my=sorted(y for _,y in candidates)[len(candidates)//2]
        good=[(x,y) for x,y in candidates if math.hypot(x-mx,y-my)<self.cell_px*.26]
        if len(good)<2:
            return False
        target_x=sum(x for x,y in good)/len(good)
        target_y=sum(y for x,y in good)/len(good)
        if math.hypot(target_x-self.player_x,target_y-self.player_y)>self.cell_px*.6:
            return False
        self.player_x=.75*self.player_x+.25*target_x
        self.player_y=.75*self.player_y+.25*target_y
        self.uncertainty=max(3.,self.uncertainty*.65)
        return True

    def reset_base(self) -> None:
        self.base_x, self.base_y = self.player_x, self.player_y

    def add_observation(self, screen_x: float, screen_y: float,
                        frame_width: int, frame_height: int,
                        player_x_ratio: float, player_y_ratio: float,
                        verified: bool = False, now: float | None = None) -> Resource:
        now = now or time.time()
        wx = self.player_x + screen_x - frame_width * player_x_ratio
        wy = self.player_y + screen_y - frame_height * player_y_ratio
        best = None
        for r in self.resources.values():
            if math.hypot(r.x-wx, r.y-wy) < self.cell_px * 0.9:
                best = r
                break
        if best is None:
            best = Resource(self.next_resource_id, wx, wy)
            self.resources[best.id] = best
            self.next_resource_id += 1
        else:
            # Smooth intermittent imperfect detections instead of jumping.
            best.x = 0.85*best.x + 0.15*wx
            best.y = 0.85*best.y + 0.15*wy
        best.last_seen = now
        best.observations += 1
        best.verified = best.verified or verified
        return best

    def teach_resource(self, screen_x: float, screen_y: float, frame_width: int,
                       frame_height: int, player_x_ratio: float, player_y_ratio: float,
                       tier: int = 1) -> Resource:
        """A trainer explicitly points at a stone in the live client.

        Unlike automatic template recognition this does not require image samples;
        the operator's annotation is the evidence. The measured world coordinate
        remains relative to camera odometry, not an exact game-server position.
        """
        if not (0 <= screen_x < frame_width and 0 <= screen_y < frame_height):
            raise ValueError('The marked point is outside the captured monitor')
        if not 1 <= tier <= 8:
            raise ValueError('Tier must be 1..8')
        resource = self.add_observation(screen_x, screen_y, frame_width, frame_height,
                                        player_x_ratio, player_y_ratio, verified=True)
        resource.tier = tier
        resource.label = f'T{tier} stone (taught)'
        return resource

    def teach_marker(self, kind: str, screen_x: float, screen_y: float,
                     frame_width: int, frame_height: int,
                     player_x_ratio: float, player_y_ratio: float) -> tuple[int,int]:
        """Convert a physical pointer annotation into a persistent local map cell."""
        if not (0 <= screen_x < frame_width and 0 <= screen_y < frame_height):
            raise ValueError('The marked point is outside the captured monitor')
        wx = self.player_x + screen_x - frame_width * player_x_ratio
        wy = self.player_y + screen_y - frame_height * player_y_ratio
        cell = self.cell(wx, wy)
        if kind == 'block':
            self.set_blocked(wx, wy)
        elif kind == 'exit':
            self.set_exit(wx, wy)
        elif kind == 'clear':
            self.erase(wx, wy)
        elif kind == 'walkable':
            if cell in self.forbidden or cell in self.blocked:
                raise ValueError('Explicit forbidden or blocked cell requires erasing first')
            self.visited.add(cell)
        else:
            raise ValueError('Unknown marker type')
        return cell

    def mark_walked_segment(self, start: tuple[float,float], end: tuple[float,float]) -> None:
        """Persist every crossed cell while the operator demonstrates a walk."""
        distance = math.dist(start, end)
        samples = max(1, math.ceil(distance / max(3., self.cell_px * .4)))
        for i in range(samples+1):
            t=i/samples
            cell=self.cell(start[0]+(end[0]-start[0])*t,
                           start[1]+(end[1]-start[1])*t)
            if self.passable(cell):
                self.visited.add(cell)

    def line_taught_passable(self, origin: tuple[float,float],
                            target: tuple[float,float]) -> bool:
        """Only permit a straight commanded move within demonstrated cells."""
        distance=math.dist(origin,target)
        samples=max(1,math.ceil(distance/max(3.,self.cell_px*.2)))
        for i in range(samples+1):
            t=i/samples
            c=self.cell(origin[0]+(target[0]-origin[0])*t,
                        origin[1]+(target[1]-origin[1])*t)
            if not self.passable(c) or (c not in self.visited and c != self.cell(*origin)):
                return False
        return True

    def plan_taught(self, target: tuple[float,float], arrival_radius_cells: int = 2,
                    max_nodes: int = 12000) -> list[tuple[float,float]]:
        """A* restricted to walkable cells actually demonstrated by the trainer.

        Prefer standing next to a resource on a visited cell. Unknown terrain is
        not silently presumed to be passable. Returns [] when no safe path exists.
        """
        start=self.cell(self.player_x,self.player_y)
        goal=self.cell(*target)
        if not self.passable(start): return []
        known=set(self.visited)
        known.add(start)
        candidates={c for c in known if self.passable(c) and
                    math.dist(c,goal)<=arrival_radius_cells}
        if not candidates: return []
        queue=[(min(math.dist(start,c) for c in candidates),0.,start)]
        came={}; costs={start:0.}; closed=set(); found=None
        while queue and len(closed)<max_nodes:
            _,g,current=heapq.heappop(queue)
            if current in closed: continue
            closed.add(current)
            if current in candidates:
                found=current;break
            x,y=current
            for nb in ((x+1,y),(x-1,y),(x,y+1),(x,y-1),
                       (x+1,y+1),(x+1,y-1),(x-1,y+1),(x-1,y-1)):
                if nb not in known or not self.passable(nb): continue
                if nb[0]!=x and nb[1]!=y:
                    # Never squeeze through the corner of two blocked cells.
                    if not (self.passable((nb[0],y)) and self.passable((x,nb[1]))):
                        continue
                new=g+math.dist(current,nb)
                if new<costs.get(nb,float('inf')):
                    costs[nb]=new;came[nb]=current
                    h=min(math.dist(nb,c) for c in candidates)
                    heapq.heappush(queue,(new+h,new,nb))
        if found is None:return []
        result=[found]
        while result[-1]!=start:
            result.append(came[result[-1]])
        result.reverse()
        return [self.center(c) for c in result[1:]] or [self.center(found)]

    def mark_failure(self, resource_id: int, now: float, cooldown: float) -> None:
        """Temporarily quarantine a bad candidate without losing the known resource."""
        r = self.resources.get(resource_id)
        if r:
            r.failures += 1
            r.next_attempt_at = max(r.next_attempt_at, now + cooldown)

    def export_geojson(self, path: Path) -> None:
        """Export a local relative-coordinate map (NOT real GPS coordinates)."""
        features = []
        for r in self.resources.values():
            features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [r.x, r.y]},
                             'properties': {'kind': 'resource', 'id': r.id, 'tier': r.tier,
                                            'verified': r.verified, 'depleted_at': r.depleted_at}})
        for kind, cells in [('blocked',self.blocked),('visited',self.visited),('exit',self.exits)]:
            for c in cells:
                features.append({'type':'Feature', 'geometry': {'type':'Point',
                                 'coordinates':[c[0]*self.cell_px,c[1]*self.cell_px]},
                                 'properties':{'kind':kind,'cell':list(c)}})
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'type':'FeatureCollection','coordinate_system':'local_relative_pixels',
                                    'features':features},ensure_ascii=False,indent=2),encoding='utf-8')

    def set_blocked(self, x: float, y: float, value: bool = True) -> None:
        c = self.cell(x, y)
        if value: self.blocked.add(c)
        else: self.blocked.discard(c)

    def set_exit(self, x: float, y: float, radius: int = 2) -> None:
        cell = self.cell(x, y)
        self.exits.add(cell)
        # Never click into a known exit's safety buffer.
        for xx in range(cell[0]-radius, cell[0]+radius+1):
            for yy in range(cell[1]-radius, cell[1]+radius+1):
                self.forbidden.add((xx, yy))

    def remove_exit(self, x: float, y: float, radius: int = 2) -> None:
        """Remove one marked exit and rebuild safety buffers for remaining exits."""
        self.exits.discard(self.cell(x, y))
        self.forbidden.clear()
        for cx, cy in self.exits:
            for xx in range(cx-radius, cx+radius+1):
                for yy in range(cy-radius, cy+radius+1):
                    self.forbidden.add((xx, yy))

    def erase(self, x: float, y: float) -> None:
        """Erase a cell marker and any exit originally placed at the cell."""
        self.set_blocked(x, y, False)
        if self.cell(x, y) in self.exits:
            self.remove_exit(x, y)

    def passable(self, c: tuple[int, int]) -> bool:
        return c not in self.blocked and c not in self.forbidden

    def line_passable(self, origin: tuple[float,float], target: tuple[float,float]) -> bool:
        """Verify a clicked straight-line segment avoids EVERY known excluded cell."""
        distance=math.dist(origin,target)
        samples=max(1,math.ceil(distance/max(3.,self.cell_px*.25)))
        return all(self.passable(self.cell(origin[0]+(target[0]-origin[0])*i/samples,
                                                origin[1]+(target[1]-origin[1])*i/samples))
                   for i in range(samples+1))

    def plan(self, target: tuple[float, float], radius_cells: int = 2,
             max_nodes: int = 6000) -> list[tuple[float, float]]:
        """Conservative A* in a bounded local search; unknown cells cost more."""
        start = self.cell(self.player_x, self.player_y)
        goal = self.cell(*target)
        if not self.passable(goal):
            opts = [(math.dist(c, goal), c) for c in
                    ((goal[0]+dx, goal[1]+dy)
                    for dx in range(-radius_cells, radius_cells+1)
                    for dy in range(-radius_cells, radius_cells+1)) if self.passable(c)]
            if not opts: return []
            goal = min(opts)[1]
        pq = [(0.0, start)]
        came: dict[tuple[int, int], tuple[int, int]] = {}
        cost = {start: 0.0}
        explored = 0
        while pq and explored < max_nodes:
            _, current = heapq.heappop(pq)
            explored += 1
            if current == goal:
                nodes = [current]
                while nodes[-1] != start:
                    nodes.append(came[nodes[-1]])
                nodes.reverse()
                if len(nodes) <= 1: return [target]
                # Simplify axis-aligned sections to reduce unnecessary clicks.
                result = []
                for i in range(1, len(nodes)):
                    if i == len(nodes)-1 or (nodes[i+1][0]-nodes[i][0], nodes[i+1][1]-nodes[i][1]) != (nodes[i][0]-nodes[i-1][0], nodes[i][1]-nodes[i-1][1]):
                        result.append(self.center(nodes[i]))
                return result
            x, y = current
            for nb in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if abs(nb[0]-start[0]) > 32 or abs(nb[1]-start[1]) > 32:
                    continue
                if not self.passable(nb): continue
                # Unknown cells are navigable hypotheses, never guaranteed safe.
                step_cost = 1.0 if nb in self.visited else 1.7
                new_cost = cost[current] + step_cost
                if new_cost < cost.get(nb, float('inf')):
                    cost[nb] = new_cost
                    came[nb] = current
                    priority = new_cost + abs(nb[0]-goal[0])+abs(nb[1]-goal[1])
                    heapq.heappush(pq, (priority, nb))
        return []

    def frontier(self, excluded: set[tuple[int,int]] | None = None) -> tuple[float, float] | None:
        """Choose nearby unexplored open cells, avoiding exits and attempted obstructions."""
        at = self.cell(self.player_x, self.player_y)
        excluded = excluded or set()
        choices = []
        for radius in range(2, 17):
            for dx in range(-radius, radius+1):
                for dy in (-radius, radius):
                    c = (at[0]+dx, at[1]+dy)
                    if c not in self.visited and c not in excluded and self.passable(c):
                        choices.append((abs(dx)+abs(dy), c))
            for dy in range(-radius+1, radius):
                for dx in (-radius, radius):
                    c = (at[0]+dx, at[1]+dy)
                    if c not in self.visited and c not in excluded and self.passable(c):
                        choices.append((abs(dx)+abs(dy), c))
            if choices: break
        if not choices: return None
        return self.center(min(choices)[1])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'version': 1, 'cell_px': self.cell_px,
            'player': [self.player_x, self.player_y], 'base': [self.base_x, self.base_y],
            'uncertainty': self.uncertainty,
            'visited': sorted(map(list, self.visited)),
            'blocked': sorted(map(list, self.blocked)),
            'forbidden': sorted(map(list, self.forbidden)),
            'exits': sorted(map(list, self.exits)),
            'resources': [asdict(r) for r in self.resources.values()],
            'next_resource_id': self.next_resource_id,
        }
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> 'WorldMap':
        raw = json.loads(path.read_text(encoding='utf-8'))
        if raw.get('version') != 1:
            raise ValueError('Unsupported map version')
        out = cls(cell_px=int(raw['cell_px']))
        out.player_x, out.player_y = raw['player']
        out.base_x, out.base_y = raw['base']
        out.uncertainty = raw.get('uncertainty', 0.0)
        for key in ('visited', 'blocked', 'forbidden', 'exits'):
            setattr(out, key, {tuple(map(int, c)) for c in raw.get(key, [])})
        out.resources = {int(r['id']): Resource(**r) for r in raw.get('resources', [])}
        out.next_resource_id = raw.get('next_resource_id', 1)
        return out
