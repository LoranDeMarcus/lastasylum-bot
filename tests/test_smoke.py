from config import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.flask_stop_threshold == 180
    assert cfg.energy_refill_threshold == 20
    assert cfg.farm_levels == frozenset({5})
    assert cfg.mob_squad == 2 and cfg.boss_squad == 1
