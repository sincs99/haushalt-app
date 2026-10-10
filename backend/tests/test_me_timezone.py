"""/me liefert die Zeitzone des Haushalts — das Frontend rechnet „heute“ damit (CASA-39)."""


def test_me_includes_household_timezone(client, db, household_a, token_a):
    household_a.timezone = "America/New_York"
    db.commit()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    assert me["households"][0]["timezone"] == "America/New_York"
