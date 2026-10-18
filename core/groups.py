AGENTS_QUEUE_GROUP = "agents.queue"


def ticket_group(ticket_id):
    return f"ticket.{ticket_id}"


def user_group(user_id):
    return f"user.{user_id}"
