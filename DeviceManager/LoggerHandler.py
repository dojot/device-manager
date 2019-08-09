from flask import Blueprint, request, jsonify, make_response

from DeviceManager.conf import CONFIG
from DeviceManager.Logger import Log

from DeviceManager.app import app

from DeviceManager.SerializationModels import parse_payload, load_attrs
from DeviceManager.SerializationModels import log_schema
from DeviceManager.utils import format_response, HTTPRequestError, get_pagination

logger = Blueprint('log', __name__)
LOG = Log()

class LoggerHandler:
    
    def _init_(self):
        pass
    
    @staticmethod
    def update_log_level(req):
        _, json_payload = parse_payload(req, log_schema)
        LOG.update_log_level(json_payload['level'])

        result = {
            'result': 'ok'
        }

        return result
    
    @staticmethod
    def get_log_level():
        result = {
            'level': LOG.get_log_level()
        }

        return result


@logger.route('/log', methods=['PUT'])
def flask_update_log_level():
    try:
        result = LoggerHandler.update_log_level(request)

        return make_response(jsonify(result), 200)

    except HTTPRequestError as error:
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)
        return format_response(error.error_code, error.message)

@logger.route('/log', methods=['GET'])
def flask_get_log_level():
    result = LoggerHandler.get_log_level()

    return make_response(jsonify(result), 200)

app.register_blueprint(logger)
