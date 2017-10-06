""" Assorted utils used throughout the service """

import json
import random
from flask import make_response

def formatResponse(status, message=None):
    payload = None
    if message:
        payload = json.dumps({'message': message, 'status': status})
    elif status >= 200 and status < 300:
        payload = json.dumps({'message': 'ok', 'status': status})
    else:
        payload = json.dumps({'message': 'Request failed', 'status': status})

    return make_response(payload, status)

def create_id():
    """ Generates a random hex id for managed entities """
    # TODO this is far too small for any practical deployment, but helps keep
    #      the demo process simple
    return '%04x' % random.randrange(16**4)
