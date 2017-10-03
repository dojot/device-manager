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
from utils import formatResponse, create_id
from BackendHandler import BackendHandler, IotaHandler, PersistenceHandler
from BackendHandler import annotate_status

from DatabaseModels import *
import SerializationModels
from TenancyManager import init_tenant_context

from app import app

device = Blueprint('device', __name__)

LOGGER = logging.getLogger('device-manager.' + __name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)

def serialize_full_device(orm_device):
    data = SerializationModels.device_schema.dump(orm_device).data
    data['attrs'] = SerializationModels.attr_list_schema.dump(orm_device.template.attrs).data
    return data

@device.route('/device', methods=['GET'])
def get_devices():
    """
        Fetches known devices, potentially limited by a given value.
        Ordering might be user-configurable too.
    """
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    page = 1
    per_page = 20
    page = Device.query.paginate(page=page, per_page=per_page)
    devices = []
    for d in page.items:
        devices.append(serialize_full_device(d))

    result = {
        'pagination': {
            'page': page.page,
            'total': page.pages,
            'has_next': page.has_next,
            'next_page': page.next_num
        },
        'devices': devices
    }
    return make_response(json.dumps(result), 200)

@device.route('/device', methods=['POST'])
def create_device():
    """ Creates and configures the given device (in json) """
    tenant=None
    try:
        tenant = init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    json_payload = request.get_json()
    if json_payload is None:
        return formatResponse(400, "Payload must be valid JSON, and Content-Type set accordingly")
    device_data, errors = SerializationModels.device_schema.load(json_payload)
    if errors:
        results = json.dumps({'message':'failed to parse input', 'errors': errors})
        LOGGER.info("failed to parse input - %s", results)
        return make_response(results, 400)

    # TODO this is awful, makes me sad, but for now also makes demoing easier
    # We might want to look into an auto-configuration feature using the service
    # and device name on automate to be able to remove this
    _attempts = 0
    device_data['device_id'] = ''
    while _attempts < 10 and len(device_data['device_id']) == 0:
        _attempts += 1
        new_id = create_id()
        if Device.query.filter_by(device_id=new_id).first() is None:
            device_data['device_id'] = new_id

    orm_device = Device(**device_data)
    if ('attrs' in json_payload) and ('template' not in device_data):
        device_template = DeviceTemplate(label="Device.%s template" % device_data['device_id'])
        db.session.add(device_template)
        orm_device.template = device_template
        for attr in json_payload['attrs']:
            entity, errors = SerializationModels.attr_schema.load(attr)
            if errors:
                results = json.dumps({'message':'failed to parse attr', 'errors': errors})
                return make_response(results, 400)
            orm_attr = DeviceAttr(template=device_template, **entity)
            db.session.add(orm_attr)
    else:
        return formatResponse(400, 'A device must be given a list of attrs or a template')

    protocol_handler = IotaHandler(service=tenant)
    subscription_handler = PersistenceHandler(service=tenant)
    # virtual devices are currently managed (i.e. created on orion) by orchestrator
    device_type = "virtual"
    if orm_device.protocol != "virtual":
        device_type = "device"
        if not protocol_handler.create(orm_device):
            return formatResponse(500, 'Failed to configure device')

    orm_device.persistence = subscription_handler.create(orm_device.device_id, device_type)
    db.session.add(orm_device)
    db.session.commit()
    result = json.dumps({
        'message': 'device created',
        'device': serialize_full_device(orm_device)
    })
    return make_response(result, 200)

@device.route('/device/<deviceid>', methods=['GET'])
def get_device(deviceid):
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    orm_device = Device.query.filter_by(device_id=deviceid).first()
    if orm_device is None:
        return formatResponse(404, 'No such device: %s' % deviceid)
    return make_response(json.dumps(serialize_full_device(orm_device)), 200)


@device.route('/device/<deviceid>', methods=['DELETE'])
def remove_device(deviceid):
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    orm_device = Device.query.filter_by(device_id=deviceid).first()
    if orm_device is None:
        return formatResponse(404, 'No such device: %s' % deviceid)
    data = serialize_full_device(orm_device)
    db.session.delete(orm_device)
    db.session.commit()

    results = json.dumps({'result': 'ok', 'removed_device': data})
    return make_response(results, 200)


@device.route('/device/<deviceid>', methods=['PUT'])
def update_device(deviceid):
    tenant=None
    try:
        tenant = init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    json_payload = request.get_json()
    if json_payload is None:
        return formatResponse(400, "Payload must be valid JSON, and Content-Type set accordingly")
    updated_device_data, errors = SerializationModels.device_schema.load(json_payload)
    if errors:
        results = json.dumps({'message':'failed to parse input', 'errors': errors})
        LOGGER.info("failed to parse input - %s", results)
        return make_response(results, 400)
    updated_device = Device(**updated_device_data)

    if 'attrs' in json_payload:
        return formatResponse(400, "Attributes cannot be updated inline. Update the associated template instead.")

    orm_device = Device.query.filter_by(device_id=deviceid).first()
    if orm_device is None:
        return formatResponse(404, 'No such device: %s' % deviceid)
    updated_device.device_id = orm_device.device_id

    # sanity check for template (allows to bypass subsystem rollback)
    orm_template = DeviceTemplate.query.filter_by(id=updated_device_data['template']['id']).first()
    if orm_template is None:
        error = 'Given template (%s) does not exist' % updated_device_data['template']['id']
        return formatResponse(400, error)
    updated_device.template = orm_template

    subsHandler = PersistenceHandler(service=tenant)
    protocolHandler = IotaHandler(service=tenant)

    device_type = 'virtual'
    old_type = orm_device.protocol
    new_type = updated_device.protocol
    if (old_type != 'virtual') and (new_type != 'virtual'):
        device_type = 'device'
        if not protocolHandler.update(updated_device):
            return formatResponse(500, 'Failed to update device configuration')
    if old_type != new_type:
        if old_type == 'virtual':
            device_type = 'device'
            if not protocolHandler.create(updated_device):
                return formatResponse(500, 'Failed to update device configuration (device creation)')
        elif new_type == 'virtual':
            if not protocolHandler.remove(updated_device.device_id):
                return formatResponse(500, 'Failed to update device configuration (device removal)')

    subsHandler.remove(orm_device.persistence)
    updated_device.persistence = subsHandler.create(orm_device.device_id, device_type)
    db.session.delete(orm_device)
    db.session.add(updated_device)
    db.session.commit()

    result = {'message': 'device updated', 'device': serialize_full_device(updated_device)}
    return make_response(json.dumps(result))

app.register_blueprint(device)
