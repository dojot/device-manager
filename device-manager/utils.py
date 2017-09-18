""" Assorted utils used throughout the service """

import json
import random
from flask import make_response
from pymongo import MongoClient
import base64

class CollectionManager:
    def __init__(self, database, server='mongodb', port=27017):
        self.client = None
        self.collection = None
        self.database = database
        self.server = server
        self.port = port

    def getDB(self):
        if not self.client:
            self.client = MongoClient(self.server, self.port)
        return self.client[self.database]

    def getCollection(self, collection):
        return self.getDB()[collection]

    def __call__(self, collection):
        return self.getCollection(collection)

def formatResponse(status, message=None):
    payload = None
    if message:
        payload = json.dumps({'message': message, 'status': status})
    elif status >= 200 and status < 300:
        payload = json.dumps({'message': 'ok', 'status': status})
    else:
        payload = json.dumps({'message': 'Request failed', 'status': status})

    return make_response(payload, status)


def decode_base64(data):
    """Decode base64, padding being optional.

    :param data: Base64 data as an ASCII byte string
    :returns: The decoded byte string.

    """
    missing_padding = len(data) % 4
    if missing_padding != 0:
        data += b'='* (4 - missing_padding)
    return base64.decodestring(data)


def get_allowed_service(token):
    """
        Parses the authorization token, returning the service to be used when
        configuring the FIWARE backend

        :param token: JWT token to be parsed
        :returns: Fiware-service to be used on API calls
        :raises ValueError: for invalid token received
    """
    if not token or len(token) == 0:
        raise ValueError("Invalid authentication token")

    payload = token.split('.')[1]
    try:
        data = json.loads(decode_base64(payload))
        return data['service']
    except Exception as ex:
        raise ValueError("Invalid authentication token payload - not json object", ex)

    return None

def create_id():
    """ Generates a random hex id for managed entities """
    # TODO this is far too small for any practical deployment, but helps keep
    #      the demo process simple
    return '%04x' % random.randrange(16**4)
