from dataclasses import dataclass, field
from typing import Optional
import math

@dataclass(frozen=True)
class Target:
    kind: str
    level: int
    x: int
    y: int

@dataclass
class GameState:
    flasks: int
    energy: int
    deployed: int
    targets: list
    screen_w: int
    screen_h: int

@dataclass(frozen=True)
class Action:
    type: str
    target: Optional[Target] = None

def distance(ax: int, ay: int, bx: int, by: int) -> float:
    return math.hypot(ax - bx, ay - by)

def nearest(targets, cx: int, cy: int):
    if not targets:
        return None
    return min(targets, key=lambda t: distance(t.x, t.y, cx, cy))
