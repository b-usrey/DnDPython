class Listener():
    def __init__(self,observer):
        self.observer = observer
        self.observer.subscribe("*",self.observer)
    def notify(self,eventType,data):
        print(eventType,data)
    