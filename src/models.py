from dataclasses import dataclass
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

@dataclass(frozen=True)
class Box:
    """Прямоугольник кнопки: центр (x, y) и размер (w, h).

    Кнопка — не точка: тап в одну и ту же выверенную координату это машинный
    признак. Размер нужен, чтобы прийти в случайную точку ВНУТРИ кнопки.
    У шаблонных кнопок он берётся даром из размеров шаблона, у фиксированных
    координат — из cfg.tap_sizes."""
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self):
        return (self.x, self.y)

    @classmethod
    def at(cls, xy, size):
        return cls(int(xy[0]), int(xy[1]), int(size[0]), int(size[1]))

def distance(ax: int, ay: int, bx: int, by: int) -> float:
    return math.hypot(ax - bx, ay - by)

def nearest(targets, cx: int, cy: int):
    if not targets:
        return None
    return min(targets, key=lambda t: distance(t.x, t.y, cx, cy))
