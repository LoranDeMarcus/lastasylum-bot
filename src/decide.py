# src/decide.py
from src.models import Action, nearest

def decide(state, cfg):
    cx, cy = state.screen_w // 2, state.screen_h // 2

    if state.flasks < cfg.flask_stop_threshold:
        return Action('stop')
    if state.energy < cfg.energy_refill_threshold:
        return Action('refill')
    if state.deployed > 0:
        return Action('wait')

    bosses = [t for t in state.targets if t.kind == 'boss']
    if bosses:
        return Action('assault_boss', nearest(bosses, cx, cy))

    mobs = [t for t in state.targets
            if t.kind == 'mob' and t.level in cfg.farm_levels]
    if mobs:
        return Action('attack_mob', nearest(mobs, cx, cy))

    return Action('explore')
