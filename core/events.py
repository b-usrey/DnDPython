from pdb import set_trace as S
'''
Type: "Initiative_Rolled" : Data:{ad;flkajd;flajk}
Type: "Attack_Rolled" : Data:{Attacker,Target,Attack_Roll_Data}
Type: "Attack_Hit" : Data:{}
'''
class EventBus:
    def __init__(self):
        # event_type -> list of callbacks
        self.subscribers = {}

    def subscribe(self, event_type, callback):
        """Register a function to be called when event_type is broadcast."""
        self.subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type, callback):
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(callback)
            if not self.subscribers[event_type]:
                del self.subscribers[event_type]

    def broadcast(self, event_type, context):
        """Send an event with context to all listeners."""
        for callback in self.subscribers.get(event_type, []):
            callback(context)

        # also send to any wildcard listeners
        #for callback in self.subscribers.get("*", []):
        #    S()
        #    callback(event_type, context)





