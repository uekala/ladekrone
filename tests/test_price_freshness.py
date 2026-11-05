from datetime import UTC, datetime, timedelta

from custom_components.ladekrone.pricing import Offer, Price
from custom_components.ladekrone.sensor import _offer_dict


def make_offer(updated):
    return Offer(
        station_id="test:station", operator="Testnetz", address=None,
        latitude=51.0, longitude=6.0, distance_km=1.0,
        price=Price(kwh=0.44, updated=updated), power_kw=50.0,
        current="dc", connectors=["ccs"], points=2,
    )


def test_recent_price_is_current():
    updated = datetime.now(UTC).isoformat()
    data = _offer_dict(make_offer(updated))
    assert data["price_updated"] == updated
    assert data["price_freshness"] == "current"
    assert data["price_age_hours"] == 0.0


def test_old_price_is_stale():
    updated = (datetime.now(UTC) - timedelta(hours=72)).isoformat()
    data = _offer_dict(make_offer(updated))
    assert data["price_freshness"] == "stale"
    assert data["price_age_hours"] >= 72.0


def test_missing_timestamp_is_unknown():
    data = _offer_dict(make_offer(None))
    assert data["price_freshness"] == "unknown"
    assert "price_age_hours" not in data
