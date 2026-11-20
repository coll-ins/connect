from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjectJSONParser(JSONParser):
    """
    Views read request.data.get(...) everywhere; a JSON list, string or number
    would make that an AttributeError (500). Refuse such bodies up front.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError({
                'code': 'invalid_body',
                'detail': 'The request body must be a JSON object.',
            })
        return data
