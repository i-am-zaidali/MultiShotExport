class ReplaceError(Exception):
    def __init__(self, msg, errors):
        super(ReplaceError, self).__init__(msg)
        self.errors = errors
