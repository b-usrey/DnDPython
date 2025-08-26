from pdb import set_trace as S
class Item:
    def __init__(self, name, type, **kwargs):
        self.name = name
        self.item_type = type
        for arg in kwargs:
            if "comment" in arg:
                continue
            setattr(self,arg,kwargs[arg])

    def __repr__(self):
        return f"{self.name} ({self.item_type})"
