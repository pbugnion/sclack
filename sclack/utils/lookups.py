
class PartialMatchLookup:
    def __init__(self, lookup):
        self._lookup = lookup

    def get_all(self, text):
        result = {}
        for key, value in self._lookup.items():
            if text in key:
                result[key] = value
        return result



class PartialMatchList:
    def __init__(self, l):
        self._l = l

    def contains(self, text):
        for entry in self._l:
            if text in entry:
                return True
        return False
