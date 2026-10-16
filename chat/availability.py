from realtime import presence


def any_agents_available():
    return bool(presence.available_agent_ids())


def agents_available(site):
    return any_agents_available()
