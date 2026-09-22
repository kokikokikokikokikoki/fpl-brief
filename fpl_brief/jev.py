"""Optional Jev decision-layer status. Network use stays opt-in."""


def status(config):
    settings = config.get("jev", {})
    if not settings.get("enabled", False):
        return {
            "enabled": False,
            "status": "disabled",
            "message": "Jev is disabled. The desk is using deterministic rules only.",
        }
    return {
        "enabled": True,
        "status": "not_configured",
        "message": "Jev is enabled in config but has no reviewed endpoint or credential.",
    }
