from pdb import set_trace as S
class EventManager:
    def __init__(self):
        self.observers = []

    def register(self, observer):
        self.observers.append(observer)

    def unregister(self, observer):
        self.observers.remove(observer)

    def broadcast(self, event_type, data):
        for observer in self.observers:
            observer.notify(event_type, data)
