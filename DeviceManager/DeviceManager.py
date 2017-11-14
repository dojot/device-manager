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
from BackendHandler import BackendHandler, IotaHandler, PersistenceHandler, OrionHandler, KafkaHandler
from sqlalchemy.exc import IntegrityError

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
    data['attrs'] = {}
    for template in orm_device.templates:
        data['attrs'][template.id] = attr_list_schema.dump(template.attrs).data
    return data

def auto_create_template(json_payload, new_device):
    if ('attrs' in json_payload) and (new_device.templates is None):
        device_template = DeviceTemplate(label="device.%s template" % new_device.id)
        db.session.add(device_template)
        new_device.templates = [device_template]
        load_attrs(json_payload['attrs'], device_template, DeviceAttr, db)

def parse_template_list(template_list, new_device):
    new_device.templates = []
    for templateid in template_list:
        new_device.templates.append(assert_template_exists(templateid))

def generate_device_id():
    # TODO this is awful, makes me sad, but for now also makes demoing easier
    # We might want to look into an auto-configuration feature for devices, such that ids are
    # not input manually on devices
    _attempts = 0
    generated_id = ''
    while _attempts < 10 and len(generated_id) == 0:
        _attempts += 1
        new_id = create_id()
        if Device.query.filter_by(id=new_id).first() is None:
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

        result = json.dumps({
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'devices': devices
        })
        return make_response(result, 200)
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
        try:
            count = int(request.args.get('count', '1'))
            clength = len(str(count))
        except Exception as e:
            LOGGER.error(e)
            raise HTTPRequestError(400, "If provided, count must be integer")
        result = None
        devices = []
        for i in range(0, count):
            device_data, json_payload = parse_payload(request, device_schema)
            device_data['id'] = generate_device_id()
            device_data['label'] = device_data['label'] + "_%0*d" % (clength, i)
            device_data.pop('templates', None) # handled separatly by parse_template_list
            orm_device = Device(**device_data)
            parse_template_list(json_payload.get('templates', []), orm_device)
            auto_create_template(json_payload, orm_device)
            db.session.add(orm_device)

            devices.append({'id': device_data['id'], 'label': device_data['label']})

            full_device = serialize_full_device(orm_device)

            # TODO remove this in favor of kafka as data broker....
            ctx_broker_handler = OrionHandler(service=tenant)
            ctx_broker_handler.create(full_device)

            kafka_handler = KafkaHandler()
            kafka_handler.create(full_device, meta={"service": tenant})

        try:
            db.session.commit()
        except IntegrityError as error:
            handle_consistency_exception(error)

        if count == 1:
            result = json.dumps({
                'message': 'device created',
                'device': full_device
            })
        else:
            result = json.dumps({
                'message': 'devices created',
                'devices': devices
            })

        # TODO revisit iotagent notification procedure
        # protocol_handler = IotaHandler(service=tenant)
        # device_type = "virtual"
        # if orm_device.protocol != "virtual":
        #     device_type = "device"
        #     protocol_handler.create(orm_device)
        # TODO revisit history management
        # subscription_handler = PersistenceHandler(service=tenant)
        # orm_device.persistence = subscription_handler.create(orm_device.device_id, "device")

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
        old_device = assert_device_exists(deviceid)

        device_data, json_payload = parse_payload(request, device_schema)
        device_data.pop('templates')
        updated_device = Device(**device_data)
        parse_template_list(json_payload.get('templates', []), updated_device)
        updated_device.id = deviceid

        # update sanity check
        if 'attrs' in json_payload:
            error = "Attributes cannot be updated inline. Update the associated template instead."
            return format_response(400, error)

        # TODO revisit iotagent notification mechanism
        # protocolHandler = IotaHandler(service=tenant)
        # device_type = 'virtual'
        # old_type = old_device.protocol
        # new_type = updated_device.protocol
        # if (old_type != 'virtual') and (new_type != 'virtual'):
        #     device_type = 'device'
        #     protocolHandler.update(updated_device)
        # if old_type != new_type:
        #     if old_type == 'virtual':
        #         device_type = 'device'
        #         protocolHandler.create(updated_device)
        #     elif new_type == 'virtual':
        #         protocolHandler.remove(updated_device.id)

        # TODO revisit device data persistence
        # subsHandler = PersistenceHandler(service=tenant)
        # subsHandler.remove(old_device.persistence)
        # updated_device.persistence = subsHandler.create(deviceid, device_type)

        # TODO remove this in favor of kafka as data broker....
        ctx_broker_handler = OrionHandler(service=tenant)
        ctx_broker_handler.update(serialize_full_device(old_device))

        db.session.delete(old_device)
        db.session.add(updated_device)

        try:
            db.session.commit()
        except IntegrityError as error:
            handle_consistency_exception(error)

        result = {'message': 'device updated', 'device': serialize_full_device(updated_device)}
        return make_response(json.dumps(result))

    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device/<deviceid>/attrs', methods=['PUT'])
def configure_device(deviceid):
    try:
        tenant = init_tenant_context(request, db)
        # In fact, the actual device is not needed. We must be sure that it exists.
        assert_device_exists(deviceid)
        json_payload = json.loads(request.data)
        kafka_handler = KafkaHandler()
        # Remove topic metadata from JSON to be sent to the device
        # Should this be moved to a HTTP header?
        topic = json_payload["topic"]
        del json_payload["topic"]

        kafka_handler.configure(json_payload, meta = { "service" : tenant, "id" : deviceid, "topic": topic})

        result = {'message': 'configuration sent'}
        return make_response(result, 200)

    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

# Convenience template ops
@device.route('/device/<deviceid>/template/<templateid>', methods=['POST'])
def add_template_to_device(deviceid, templateid):
    """ associates given template with device """

    try:
        tenant = init_tenant_context(request, db)
        orm_device = assert_device_exists(deviceid)
        orm_template = assert_template_exists(templateid)

        orm_device.templates.append(orm_template)

        try:
            db.session.commit()
        except IntegrityError as error:
            handle_consistency_exception(error)

        result = {'message': 'device updated', 'device': serialize_full_device(orm_device)}
        return make_response(json.dumps(result))
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device/<deviceid>/template/<templateid>', methods=['DELETE'])
def remove_template_from_device(deviceid, templateid):
    """ removes given template from device """
    try:
        tenant = init_tenant_context(request, db)
        device = assert_device_exists(deviceid)
        relation = assert_device_relation_exists(deviceid, templateid)

        # Here (for now) there are no more validations to perform, as template removal
        # cannot violate attribute constraints

        db.session.remove(relation)
        db.session.commit()
        result = {'message': 'device updated', 'device': serialize_full_device(device)}
        return make_response(json.dumps(result))
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@device.route('/device/template/<templateid>', methods=['GET'])
def get_by_template(templateid):
    try:
        init_tenant_context(request, db)

        page_number, per_page = get_pagination(request)
        page = (
            db.session.query(Device)
            .join(DeviceTemplateMap)
            .filter_by(template_id=templateid)
            .paginate(page=page_number, per_page=per_page, error_out=False)
        )
        devices = []
        for d in page.items:
            devices.append(serialize_full_device(d))

        result = json.dumps({
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'devices': devices
        })
        return make_response(result, 200)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

app.register_blueprint(device)
