class Listener():
    def __init__(self,observer):
        self.observer = observer
        self.observer.register(self)
    def notify(self,eventType,data):
        print(eventType,data)
    