"""
    Handles CRUD operations for devices, and their configuration on the
    FIWARE backend
"""

import json
import logging
from time import time
from flask import request
from flask import make_response
from flask import Blueprint
import pymongo
import utils
from BackendHandler import BackendHandler, IotaHandler, PersistenceHandler
from BackendHandler import annotate_status

device = Blueprint('device', __name__)
db = utils.CollectionManager('device_management')

LOGGER = logging.getLogger('device-manager.' + __name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)

def get_mongo_collection(token):
    """
        Returns a pymongo collection object pointing to the service-enabled
        collection to be used

        :param token: JWT token received
        :returns: pymongo collection object
        :raises ValueError: Invalid token received
    """
    service = utils.get_allowed_service(token)
    collection = db("dev_service_%s" % service)
    return collection

class ParseError(Exception):
    """ Thrown indicating that an invalid device representation has been given """

    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return self.msg

def sanitize(device):
    """ validates the given device, sanitizing any missing fields with their defaults """

    if 'label' not in device.keys():
        device['label'] = 'unnammed device'
    if 'id' not in device.keys():
        raise ParseError("missing unique id")
    if 'protocol' not in device.keys():
        raise ParseError("missing protocol information")
    if 'templates' not in device.keys():
        device['templates'] = []
    if 'tags' not in device.keys():
        device['tags'] = []
    if 'attrs' not in device.keys():
        device['attrs'] = []
    if 'static_attrs' not in device.keys():
        device['static_attrs'] = []



@device.route('/device', methods=['GET'])
def get_devices():
    """
        Fetches known devices, potentially limited by a given value.
        The ordering might be user-configurable too.
    """
    collection = get_mongo_collection(request.headers['authorization'])
    field_filter = {'_id': False, 'persistence': False}
    if 'limit' in request.args.keys():
        try:
            cursor = collection.find({}, field_filter,
                                     limit=int(request.args['limit']))
        except (TypeError, ValueError):
            return utils.formatResponse(400, 'Limit must be an integer value')
    else:
        cursor = collection.find({}, field_filter)

    sort = []
    if 'sortAsc' in request.args.keys():
        sort.append((request.args['sortAsc'], pymongo.ASCENDING))
    if 'sortDsc' in request.args.keys():
        sort.append((request.args['sortDsc'], pymongo.DESCENDING))
    if len(sort) > 0:
        cursor.sort(sort)

    device_list = []
    for dev_it in cursor:
        device_list.append(dev_it)

    all_devices = {"devices" : device_list}
    annotate_status(device_list, service=utils.get_allowed_service(request.headers['authorization']))
    return make_response(json.dumps(all_devices), 200)

@device.route('/device', methods=['POST'])
def create_device():
    """ Creates and configures the given device (in json) """

    collection = get_mongo_collection(request.headers['authorization'])
    device_data = {}
    if request.mimetype == 'application/json':
        try:
            device_data = json.loads(request.data)
        except ValueError:
            return utils.formatResponse(400, 'Failed to parse payload as JSON')
    else:
        return utils.formatResponse(400, 'Unknown request format')

    # TODO this is awful, makes me sad, but for now also makes demoing easier
    # We might want to look into an auto-configuration feature using the service
    # and device name on automate to be able to remove this
    _attempts = 0
    device_data['id'] = ''
    while _attempts < 10 and len(device_data['id']) == 0:
        new_id = utils.create_id()
        if not collection.find_one({'id' : new_id}):
            device_data['id'] = new_id
            break
    if not len(device_data['id']):
        return utils.formatResponse(500, 'Failed to generate unique id')

    # sanity checks
    try:
        sanitize(device_data)
    except ParseError as e:
        return utils.formatResponse(400, str(e))

    try:
        service = utils.get_allowed_service(request.headers['authorization'])
        protocolHandler = IotaHandler(service=service)
        subsHandler = PersistenceHandler(service=service)
    except (AttributeError, KeyError):
        return utils.formatResponse(400, 'Device has missing fields')
    except (ValueError):
        return utils.formatResponse(304, 'Missing authorization info')

    # virtual devices are currently managed (i.e. created on orion) by orchestrator
    device_type = "virtual"
    if device_data['protocol'] != "virtual":
        device_type = "device"
        if not protocolHandler.create(device_data):
            return utils.formatResponse(500, 'Failed to configure device')

    device_data['created'] = time()
    device_data['updated'] = time()
    device_data['persistence'] = subsHandler.create(device_data['id'], device_type)
    collection.insert_one(device_data.copy())
    result = {'message': 'device created', 'device': device_data}
    return make_response(json.dumps(result))

@device.route('/device/<deviceid>', methods=['GET'])
def get_device(deviceid):
    collection = get_mongo_collection(request.headers['authorization'])
    stored_device = collection.find_one({'id' : deviceid}, {"_id" : False, 'persistence': False})
    if stored_device is None:
        return utils.formatResponse(404, 'Given device was not found')

    annotated = annotate_status([stored_device],
                                service=utils.get_allowed_service(request.headers['authorization']))
    if len(annotated) > 0:
        LOGGER.debug('annotation success')
        return make_response(json.dumps(annotated[0]), 200)
    else:
        LOGGER.debug('annotation failure')
        return make_response(json.dumps(stored_device), 200)


@device.route('/device/<deviceid>', methods=['DELETE'])
def remove_device(deviceid):
    collection = get_mongo_collection(request.headers['authorization'])
    # sanity check
    old_device = collection.find_one({'id': deviceid})
    if not old_device:
        return utils.formatResponse(404, 'Given device was not found')

    service = utils.get_allowed_service(request.headers['authorization'])
    subsHandler = PersistenceHandler(service=service)

    if old_device['protocol'] != 'virtual':
        protocolHandler = IotaHandler(service=service)
        if not protocolHandler.remove(deviceid):
            return utils.formatResponse(500, 'Failed to remove device')

    subsHandler.remove(old_device['persistence'])
    collection.delete_one({'id' : deviceid})
    return utils.formatResponse(200)


@device.route('/device/<deviceid>', methods=['PUT'])
def update_device(deviceid):
    collection = get_mongo_collection(request.headers['authorization'])
    if request.mimetype == 'application/json':
        try:
            device_data = json.loads(request.data)
        except ValueError:
            return utils.formatResponse(400, 'Failed to parse payload as JSON')
    else:
        return utils.formatResponse(400, 'Unknown request format')

    if 'id' not in device_data.keys():
        device_data["id"] = deviceid

    # sanity checks
    # since this is a PUT and not a patch, it is safe to override all non declared fields
    try:
        sanitize(device_data)
    except ParseError as e:
        return utils.formatResponse(400, str(e))

    old_device = collection.find_one({'id': deviceid})
    if not old_device:
        return utils.formatResponse(404, 'Given device was not found')

    service = utils.get_allowed_service(request.headers['authorization'])
    subsHandler = PersistenceHandler(service=service)
    protocolHandler = IotaHandler(service=service)

    device_type = 'virtual'
    if (old_device['protocol'] != 'virtual') and (device_data['protocol'] != 'virtual'):
        device_type = 'device'
        if not protocolHandler.update(device_data):
            return utils.formatResponse(500, 'Failed to update device configuration')
    if old_device['protocol'] != device_data['protocol']:
        if old_device['protocol'] == 'virtual':
            device_type = 'device'
            if not protocolHandler.create(device_data):
                return utils.formatResponse(500, 'Failed to update device configuration (device creation)')
        elif device_data['protocol'] == 'virtual':
            if not protocolHandler.remove(device_data['id']):
                return utils.formatResponse(500, 'Failed to update device configuration (device removal)')

    subsHandler.remove(old_device['persistence'])
    device_data['persistence'] = subsHandler.create(device_data['id'], device_type)
    device_data['updated'] = time()
    collection.replace_one({'id' : deviceid}, device_data)
    result = {'message': 'device updated', 'device': device_data}
    return make_response(json.dumps(result))

@device.route('/device/query', methods=['GET'])
def find_device():
    collection = get_mongo_collection(request.headers['authorization'])
    for k,v in request.args.iteritems():
        if len(v) == 0:
            return utils.formatResponse(400, 'Given query is invalid. Field %s cannot be empty' % k)

    stored_device = collection.find_one(request.args, {"_id" : False, 'persistence': False})
    if stored_device is None:
        return utils.formatResponse(404, 'Given device was not found')

    annotated = annotate_status([stored_device],
                                service=utils.get_allowed_service(request.headers['authorization']))
    if len(annotated) > 0:
        return make_response(json.dumps(annotated[0]), 200)
    else:
        return make_response(json.dumps(stored_device), 200)

    return make_response(json.dumps(stored_device), 200)
