import logging
import re


class OAuthQueryFilter(logging.Filter):
    def filter(self, record):
        def ocultar(value):
            return re.sub(r"(/calendario/google/retorno/)\?[^\s\"]*", r"\1?[omitido]", value) if isinstance(value, str) else value
        record.msg = ocultar(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(ocultar(arg) for arg in record.args)
        return True

