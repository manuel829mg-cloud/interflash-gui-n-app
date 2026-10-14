"""Invoice documents are sent after payment, never at the due date."""
def process(now=None):
    return 0

def valid(c, outbox_id, now=None):
    return False
