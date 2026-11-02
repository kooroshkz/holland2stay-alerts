from datetime import date, time

import pytest

from h2s_alerts import catalog
from h2s_alerts.config import MIN_INTERVAL, ConfigError, build, load


def test_defaults_watch_everything():
    cfg = build({}, {})
    assert cfg.search.cities == []
    assert cfg.search.lottery is True
    assert cfg.schedule.preset == "normal"
    assert cfg.dashboard.port == 8080
    assert cfg.search.summary() == "All cities"


def test_names_and_aliases():
    s = build({"search": {"cities": ["Den Haag", "eindhoven", "'s-Hertogenbosch", "6310"]}}, {}).search
    assert s.cities == [90, 29, 28, 6310]
    assert build({"search": {"cities": "Delft"}}, {}).search.cities == [26, 6186]


def test_bedrooms_ranges():
    assert catalog.bedroom_ids("2+") == [106, 108, 382]
    assert catalog.bedroom_ids("studio-1") == [104, 6137, 105]
    assert catalog.bedroom_ids("2 bedrooms") == [106]
    s = build({"search": {"bedrooms": ["studio", "2+"]}}, {}).search
    assert s.bedrooms == [104, 106, 108, 382]


def test_contract_words():
    assert build({"search": {"contract": "long"}}, {}).search.contracts == [21, 6125, 20]
    assert build({"search": {"contract": ["short stay"]}}, {}).search.contracts == [318, 606]


def test_env_wins_over_file():
    raw = {"search": {"cities": ["Rotterdam"], "price_max": 2000}}
    env = {"H2S_CITIES": "Amsterdam, Utrecht", "H2S_PRICE_MAX": "€1,600", "H2S_LOTTERY": "no"}
    s = build(raw, env).search
    assert s.cities == [24, 27]
    assert s.price_max == 1600
    assert s.lottery is False


def test_notify_urls_split_on_space_not_comma():
    env = {"H2S_NOTIFY": "tgram://a/b  mailto://u:p@x.com?to=a@x.com,b@x.com"}
    assert build({}, env).notify.urls == ["tgram://a/b", "mailto://u:p@x.com?to=a@x.com,b@x.com"]


def test_notify_file(tmp_path):
    secret = tmp_path / "urls"
    secret.write_text("ntfy://topic\n")
    assert build({}, {"H2S_NOTIFY_FILE": str(secret)}).notify.urls == ["ntfy://topic"]


@pytest.mark.parametrize("raw, message", [
    ({"search": {"cities": ["Atlantis"]}}, "unknown value 'Atlantis'"),
    ({"search": {"bedrooms": ["7"]}}, "bedrooms"),
    ({"search": {"price_min": 2000, "price_max": 1000}}, "higher than"),
    ({"search": {"cities": ["Utrecht"], "exclude_cities": ["Utrecht"]}}, "both"),
    ({"search": {"move_in_before": "next week"}}, "YYYY-MM-DD"),
    ({"schedule": {"preset": "turbo"}}, "preset"),
    ({"general": {"base_url": "http://example.com"}}, "https"),
    ({"notify": {"quiet_hours": "late"}}, "range"),
    ({"search": "Eindhoven"}, "table"),
])
def test_errors_are_readable(raw, message):
    with pytest.raises(ConfigError, match=message):
        build(raw, {})


def test_too_fast_is_slowed_down_with_a_warning():
    cfg = build({"schedule": {"hot_seconds": 5}}, {})
    assert cfg.schedule.hot == MIN_INTERVAL
    assert cfg.warnings


def test_presets():
    cfg = build({"schedule": {"preset": "relaxed"}}, {})
    assert (cfg.schedule.hot, cfg.schedule.day, cfg.schedule.night) == (300, 600, 1800)


def test_quiet_hours_and_dates():
    cfg = build({"notify": {"quiet_hours": "23:00-07:30"}, "search": {"move_in_before": "2027-02-01"}}, {})
    assert cfg.notify.quiet_hours == (time(23, 0), time(7, 30))
    assert cfg.search.move_in_before == date(2027, 2, 1)


def test_summary_reads_well():
    s = build({"search": {"cities": ["Eindhoven", "Rotterdam"], "bedrooms": ["studio"],
                          "price_max": 1500, "contract": "long"}}, {}).search
    assert s.summary() == "Eindhoven, Rotterdam · Studio · up to €1,500 · Long stay"


def test_fingerprint_ignores_lottery_toggle():
    a = build({"search": {"cities": ["Eindhoven"], "lottery": True}}, {}).search
    b = build({"search": {"cities": ["Eindhoven"], "lottery": False}}, {}).search
    c = build({"search": {"cities": ["Utrecht"]}}, {}).search
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()


def test_load_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text('[search]\ncities = ["Leiden"]\n')
    cfg = load(env={})
    assert cfg.search.cities == [6293]
    assert cfg.source.name == "config.toml"


def test_missing_and_broken_files(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load(str(tmp_path / "nope.toml"), env={})
    bad = tmp_path / "bad.toml"
    bad.write_text("[search\n")
    with pytest.raises(ConfigError):
        load(str(bad), env={})
