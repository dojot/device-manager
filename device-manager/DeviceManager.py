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
from utils import *
from BackendHandler import BackendHandler, IotaHandler, PersistenceHandler
from BackendHandler import annotate_status

from DatabaseModels import *
from SerializationModels import *
from TenancyManager import init_tenant_context

from app import app

device = Blueprint('device', __name__)

LOGGER = logging.getLogger('device-manager.' + __name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)

def serialize_full_device(orm_device):
    data = device_schema.dump(orm_device).data
    data['attrs'] = attr_list_schema.dump(orm_device.template.attrs).data
    return data

def auto_create_template(json_payload, new_device):
    if ('attrs' in json_payload) and (new_device.template is None):
        device_template = DeviceTemplate(label="device.%s template" % new_device.device_id)
        db.session.add(device_template)
        new_device.template = device_template
        load_attrs(json_payload['attrs'], device_template, DeviceAttr, db)
    else:
        raise HTTPRequestError(400, 'A device must be given a list of attrs or a template')

def generate_device_id():
    # TODO this is awful, makes me sad, but for now also makes demoing easier
    # We might want to look into an auto-configuration feature for devices, such that ids are
    # not input manually on devices
    _attempts = 0
    generated_id = ''
    while _attempts < 10 and len(generated_id) == 0:
        _attempts += 1
        new_id = create_id()
        if Device.query.filter_by(device_id=new_id).first() is None:
            return new_id

    raise HTTPRequestError(500, "Failed to generate unique device_id")

@device.route('/device', methods=['GET'])
def get_devices():
    """
        Fetches known devices, potentially limited by a given value.
        Ordering might be user-configurable too.
    """
    try:
        init_tenant_context(request, db)

        page_number, per_page = get_pagination(request)
        page = Device.query.paginate(page=page_number, per_page=per_page, error_out=False)
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
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device', methods=['POST'])
def create_device():
    """ Creates and configures the given device (in json) """
    try:
        tenant = init_tenant_context(request, db)
        device_data, json_payload = parse_payload(request, device_schema)
        device_data['device_id'] = generate_device_id()
        orm_device = Device(**device_data)
        auto_create_template(json_payload, orm_device)

        protocol_handler = IotaHandler(service=tenant)
        subscription_handler = PersistenceHandler(service=tenant)
        # virtual devices are currently managed (i.e. created on orion) by orchestrator
        device_type = "virtual"
        if orm_device.protocol != "virtual":
            device_type = "device"
            protocol_handler.create(orm_device)

        orm_device.persistence = subscription_handler.create(orm_device.device_id, device_type)
        db.session.add(orm_device)
        db.session.commit()
        result = json.dumps({
            'message': 'device created',
            'device': serialize_full_device(orm_device)
        })
        return make_response(result, 200)

    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device/<deviceid>', methods=['GET'])
def get_device(deviceid):
    try:
        init_tenant_context(request, db)
        orm_device = assert_device_exists(deviceid)
        return make_response(json.dumps(serialize_full_device(orm_device)), 200)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device/<deviceid>', methods=['DELETE'])
def remove_device(deviceid):
    try:
        init_tenant_context(request, db)
        orm_device = assert_device_exists(deviceid)
        data = serialize_full_device(orm_device)
        db.session.delete(orm_device)
        db.session.commit()

        results = json.dumps({'result': 'ok', 'removed_device': data})
        return make_response(results, 200)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device/<deviceid>', methods=['PUT'])
def update_device(deviceid):
    try:
        tenant = init_tenant_context(request, db)
        device_data, json_payload = parse_payload(request, device_schema)
        updated_device = Device(**device_data)
        updated_device.device_id = deviceid

        # update sanity check
        if 'attrs' in json_payload:
            error = "Attributes cannot be updated inline. Update the associated template instead."
            return format_response(400, error)

        old_device = assert_device_exists(deviceid)
        # sanity check for template (allows us to bypass subsystem rollback)
        orm_template = assert_template_exists(updated_device.template_id)
        updated_device.template = orm_template

        subsHandler = PersistenceHandler(service=tenant)
        protocolHandler = IotaHandler(service=tenant)
        device_type = 'virtual'
        old_type = old_device.protocol
        new_type = updated_device.protocol
        if (old_type != 'virtual') and (new_type != 'virtual'):
            device_type = 'device'
            protocolHandler.update(updated_device)
        if old_type != new_type:
            if old_type == 'virtual':
                device_type = 'device'
                protocolHandler.create(updated_device)
            elif new_type == 'virtual':
                protocolHandler.remove(updated_device.device_id)

        subsHandler.remove(old_device.persistence)
        updated_device.persistence = subsHandler.create(deviceid, device_type)
        db.session.delete(old_device)
        db.session.add(updated_device)
        db.session.commit()

        result = {'message': 'device updated', 'device': serialize_full_device(updated_device)}
        return make_response(json.dumps(result))

    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

app.register_blueprint(device)
