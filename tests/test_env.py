import importlib


def test_env_import_does_not_raise_without_required_values(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.delenv("NTFY_SERVER", raising=False)

    import src.env as env_module

    reloaded = importlib.reload(env_module)

    assert reloaded.SUPABASE_URL == ""
    assert reloaded.SUPABASE_KEY == ""
    assert reloaded.NTFY_TOPIC == "csmid_alerts"
    assert reloaded.NTFY_SERVER == "https://ntfy.sh"
