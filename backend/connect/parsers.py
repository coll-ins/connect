from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjectJSONParser(JSONParser):
    """Every endpoint reads request.data as an object: a list, string or null
    body would crash request.data.get(), so refuse it with 400."""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError('Send a JSON object.')
        return data
