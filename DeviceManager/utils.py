""" Assorted utils used throughout the service """
import base64
import json
import random
from flask import make_response, jsonify
from Crypto.Cipher import AES

from DeviceManager.conf import CONFIG

BS = AES.block_size


def pad(s): return s + (BS - len(s) % BS) * chr(BS - len(s) % BS)


def unpad(s): return s[:-ord(s[len(s)-1:])]


def format_response(status, message=None):
    """ Utility helper to generate default status responses """
    if message:
        payload = {'message': message, 'status': status}
    elif 200 <= status < 300:
        payload = {'message': 'ok', 'status': status}
    else:
        payload = {'message': 'Request failed', 'status': status}

    return make_response(jsonify(payload), status)


def create_id():
    """ Generates a random hex id for managed entities """
    return '%05x' % random.randrange(16**6)

# from auth service


class HTTPRequestError(Exception):
    """ Exception that represents end of processing on any given request. """

    def __init__(self, error_code, message):
        super(HTTPRequestError, self).__init__()
        self.message = message
        self.error_code = error_code


def get_pagination(request):
    try:
        page = int(request.args.get('page_num', '1'))
        per_page = int(request.args.get('page_size', '20'))

        # sanity checks
        if page < 1:
            raise HTTPRequestError(400, "Page numbers must be greater than 1")
        if per_page < 1:
            raise HTTPRequestError(
                400, "At least one entry per page is mandatory")
        return page, per_page

    except TypeError:
        raise HTTPRequestError(400, "page_size and page_num must be integers")


def decode_base64(data):
    """Decode base64, padding being optional.

    :param data: Base64 data as an ASCII byte string
    :returns: The decoded byte string.

    """
    missing_padding = len(data) % 4
    if missing_padding != 0:
        data += '=' * (4 - missing_padding)
    return base64.decodebytes(data.encode()).decode()


def get_allowed_service(token):
    """
        Parses the authorization token, returning the service to be used when
        configuring the FIWARE backend

        :param token: JWT token to be parsed
        :returns: Fiware-service to be used on API calls
        :raises ValueError: for invalid token received
    """
    if not token:
        raise ValueError("Invalid authentication token")

    payload = token.split('.')[1]
    try:
        data = json.loads(decode_base64(payload))
        # to ensure backward compatibility
        if ('service' in data):
            return data['service']
        elif ('iss' in data):
            iss = data['iss']
            return iss[iss.rindex('/') + 1:]
        return None
    except Exception as ex:
        raise ValueError(
            "Invalid authentication token payload - not json object", ex)


def encrypt(plain_text):
    # plain_text is padded so its length is multiple of cipher block size
    plain_text_pad = pad(plain_text)

    cipher = AES.new(CONFIG.crypto['key'], AES.MODE_CBC, CONFIG.crypto['iv'])
    encrypted = cipher.encrypt(plain_text_pad)

    return encrypted


def decrypt(encrypted):

    cipher = AES.new(CONFIG.crypto['key'], AES.MODE_CBC, CONFIG.crypto['iv'])
    plain_text_pad = cipher.decrypt(encrypted)
    plain_text = unpad(plain_text_pad)

    return plain_text


def retrieve_auth_token(request):
    token = None
    try:
        token = request.headers['authorization']
    except KeyError:
        raise HTTPRequestError(401, "No authorization token has been supplied")
    return token
