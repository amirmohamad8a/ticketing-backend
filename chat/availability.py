from realtime import presence


def agents_available(site):
    return bool(presence.available_agent_ids())
