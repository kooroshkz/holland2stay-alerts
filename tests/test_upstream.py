from conftest import FakeH2S, home

from h2s_alerts import upstream
from h2s_alerts.client import Changed


def statuses(checks):
    return {c.name: c.status for c in checks}


def healthy():
    return FakeH2S([home(1), home(2, city=25), home(3, status=180)])


def test_healthy_site_passes():
    checks = upstream.run(healthy(), codomo=False)
    assert all(c.status == "ok" for c in checks), checks


def test_ignored_filters_fail():
    class IgnoresPrice(FakeH2S):
        def products(self, filters, *a, **kw):
            return super().products([f for f in filters if f[0] != "price"], *a, **kw)

    checks = upstream.run(IgnoresPrice([home(1), home(2)]), codomo=False)
    assert statuses(checks)["Filters are applied"] == "fail"


def test_endpoint_error_fails():
    h2s = healthy()
    h2s.fail = Changed("Holland2Stay moved or removed the listing endpoint")
    checks = upstream.run(h2s, codomo=False)
    assert checks[0].status == "fail" and "moved" in checks[0].detail


def test_nothing_listed_fails():
    checks = upstream.run(FakeH2S([home(3, status=180)]), codomo=False)
    assert statuses(checks)["Homes are listed"] == "fail"


def test_new_city_is_a_notice_not_a_failure():
    checks = upstream.run(FakeH2S([home(1), home(2, city=7001)]), codomo=False)
    notice = [c for c in checks if c.status == "notice"]
    assert notice and "7001" in notice[0].detail
    assert not any(c.status == "fail" for c in checks)


def test_markdown_report():
    report = upstream.markdown([upstream.Check("A", "ok"), upstream.Check("B", "fail", "why"),
                                upstream.Check("C", "notice", "new")])
    assert "| ✅ | A |  |" in report and "| ❌ | B | why |" in report and "🆕" in report
