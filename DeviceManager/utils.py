""" Assorted utils used throughout the service """

import json
import random
from flask import make_response


def format_response(status, message=None):
    """ Utility helper to generate default status responses """
    if message:
        payload = json.dumps({'message': message, 'status': status})
    elif 200 <= status < 300:
        payload = json.dumps({'message': 'ok', 'status': status})
    else:
        payload = json.dumps({'message': 'Request failed', 'status': status})

    return make_response(payload, status)


def create_id():
    """ Generates a random hex id for managed entities """
    # TODO this is far too small for any practical deployment, but helps keep
    #      the demo process simple
    return '%04x' % random.randrange(16**4)


# from auth service
class HTTPRequestError(Exception):
    """ Exception that represents end of processing on any given request. """
    def __init__(self, error_code, message):
        super(HTTPRequestError, self).__init__()
        self.message = message
        self.error_code = error_code


def get_pagination(request):
    try:
        page = 1
        per_page = 20
        if 'page_size' in request.args.keys():
            per_page = int(request.args['page_size'])
        if 'page_num' in request.args.keys():
            page = int(request.args['page_num'])

        # sanity checks
        if page < 1:
            raise HTTPRequestError(400, "Page numbers must be greater than 1")
        if per_page < 1:
            raise HTTPRequestError(400, "At least one entry per page is mandatory")
        return page, per_page

    except TypeError:
        raise HTTPRequestError(400, "page_size and page_num must be integers")
