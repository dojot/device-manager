"""
    Handles CRUD operations for devices, and their configuration on the
    FIWARE backend
"""
import re
import logging
import json
import time
from datetime import datetime
import secrets
from flask import request, jsonify, Blueprint, make_response
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_, func, text, desc

from DeviceManager.utils import *
from DeviceManager.utils import create_id, get_pagination, format_response
from DeviceManager.utils import HTTPRequestError
from DeviceManager.conf import CONFIG
from DeviceManager.BackendHandler import KafkaHandler, KafkaInstanceHandler

from DeviceManager.DatabaseHandler import db
from DeviceManager.DatabaseModels import assert_device_exists, assert_template_exists
from DeviceManager.DatabaseModels import handle_consistency_exception, assert_device_relation_exists
from DeviceManager.DatabaseModels import DeviceTemplate, DeviceAttr, Device, DeviceTemplateMap, DeviceAttrsPsk
from DeviceManager.DatabaseModels import DeviceOverride
from DeviceManager.SerializationModels import device_list_schema, device_schema, ValidationError
from DeviceManager.SerializationModels import attr_list_schema
from DeviceManager.SerializationModels import parse_payload, load_attrs, validate_repeated_attrs
from DeviceManager.TenancyManager import init_tenant_context
from DeviceManager.app import app
from DeviceManager.Logger import Log

from DeviceManager.SerializationModels import template_schema

device = Blueprint('device', __name__)


LOGGER = Log().color_log()

def fill_overridden_flag(attrs):
    # Update all static attributes with "is_static_overridden" attribute
    for templateId in attrs:
        for attr in attrs[templateId]:
            if 'is_static_overridden' not in attr and 'static_value' in attr:
                attr['is_static_overridden'] = False
            if 'metadata' in attr:
                for metadata in attr['metadata']:
                    if 'is_static_overridden' not in metadata and 'static_value' in metadata:
                        metadata['is_static_overridden'] = False



def serialize_override_attrs(orm_overrides, attrs):

    fill_overridden_flag(attrs)

    for override in orm_overrides:
        if override.attr.template_id is not None:
            for attr in attrs[override.attr.template_id]:
                if attr['id'] == override.aid:
                    attr['static_value'] = override.static_value
                    attr['is_static_overridden'] = True
        else:
            # If override attr does not have template_id it means we have a metadata override
            # TODO: Here we do not handle multiple hierarchical levels of metadata
            for attr in attrs[override.attr.parent.template_id]:
                if attr['id'] == override.attr.parent_id:
                    for metadata in attr['metadata']:
                        if metadata['id'] == override.aid:
                            metadata['static_value'] = override.static_value
                            metadata['is_static_overridden'] = True

def serialize_full_device(orm_device, tenant, sensitive_data=False):
    data = device_schema.dump(orm_device)
    data['attrs'] = {}
    for template in orm_device.templates:
        data['attrs'][template.id] = attr_list_schema.dump(template.attrs)

    # Override device regular and metadata attributes
    serialize_override_attrs(orm_device.overrides, data['attrs'])

    if sensitive_data:
        for psk_data in orm_device.pre_shared_keys:
            for template_id in data['attrs']:
                for attr in data['attrs'][template_id]:
                    if attr['id'] == psk_data.attr_id:
                        dec = decrypt(psk_data.psk)
                        attr['static_value'] = dec.decode('ascii')
    
    return data

def find_template(template_list, id):
    LOGGER.debug(f" Finding template from template list")
    for template in template_list:
        if template.id == int(id):
            return template

def create_orm_override(attr, orm_device, orm_template):
    try:
        target = int(attr['id'])
    except ValueError:
        LOGGER.error(f" Unknown attribute {attr['id']} in override list")
        raise HTTPRequestError(400, 'Unknown attribute {} in override list'.format(attr['id']))

    found = False
    for orm_attr in orm_template.attrs:
        if target == orm_attr.id:
            found = True
            if 'static_value' in attr and attr['static_value'] is not None:
                orm_override = DeviceOverride(
                    device=orm_device,
                    attr=orm_attr,
                    static_value=attr['static_value']
                )
                db.session.add(orm_override)
                LOGGER.debug(f" Added overrided form {orm_override}")

            # Update possible metadata field
            if 'metadata' in attr:
                for metadata in attr['metadata']:
                    try:
                        metadata_target = int(metadata['id'])
                        LOGGER.debug(f" Updated metadata {metadata_target}")
                    except ValueError:
                        LOGGER.error(f" metadata attribute {attr['id']} in override list")
                        raise HTTPRequestError(400, 'Unknown metadata attribute {} in override list'.format(
                            metadata['id']))

                    found = False
                    # WARNING: Adds no-autoflush here, without it metadata override fail during device update
                    with db.session.no_autoflush:
                        for orm_attr_child in orm_attr.children:
                            if metadata_target == orm_attr_child.id:
                                found = True
                                if 'static_value' in metadata and metadata['static_value'] is not None:
                                    orm_override = DeviceOverride(
                                        device=orm_device,
                                        attr=orm_attr_child,
                                        static_value=metadata['static_value']
                                    )
                                    db.session.add(orm_override)
                                    LOGGER.debug(f" Added overrided form {orm_override}")


    if not found:
        LOGGER.error(f" Unknown attribute {attr['id']} in override list")
        raise HTTPRequestError(400, 'Unknown attribute {} in override list'.format(target))


def auto_create_template(json_payload, new_device):
    if ('attrs' in json_payload) and (new_device.templates is None):
        device_template = DeviceTemplate(
            label="device.%s template" % new_device.id)
        db.session.add(device_template)
        LOGGER.debug(f" Adding auto-created template {device_template} into database")
        new_device.templates = [device_template]
        load_attrs(json_payload['attrs'], device_template, DeviceAttr, db)

    # TODO: perhaps it'd be best if all ids were random hex strings?
    if ('attrs' in json_payload) and (new_device.templates is not None):
        for attr in json_payload['attrs']:
            orm_template = find_template(new_device.templates, attr['template_id'])
            if orm_template is None:
                LOGGER.error(f" Unknown template {orm_template} in attr list")
                raise HTTPRequestError(400, 'Unknown template {} in attr list'.format(orm_template))
            create_orm_override(attr, new_device, orm_template)

def parse_template_list(template_list, new_device):
    new_device.templates = []
    LOGGER.debug(f" Adding new template list for device {new_device}")
    for template_id in template_list:
        new_device.templates.append(assert_template_exists(template_id, db.session))

def find_attribute(orm_device, attr_name, attr_type):
    """
    Find a particular attribute in a device retrieved from database.
    Return the attribute, if found, 'None' otherwise
    """
    for template_id in orm_device['attrs']:
        for attr in orm_device['attrs'][template_id]:
            if (attr['label'] == attr_name) and (attr['type'] == attr_type):
                LOGGER.debug(f" retrieving attribute {attr}")
                return attr
    return None

class DeviceHandler(object):

    kafka = KafkaInstanceHandler()

    def __init__(self):
        pass

    @staticmethod
    def indexed_label(count, c_length, base, index):
        if count == 1:
            return base
        else:
            return "{}_{:0{width}d}".format(base, index, width=c_length)

    @staticmethod
    def generate_device_id():
        """
        Creates a new device id
        :return The new ID
        :rtype int
        :raises HTTPRequestError: If this function can't generate a new valid
        ID after 10 attempts.
        """

        # TODO this is awful, makes me sad, but for now also makes demoing
        # easier We might want to look into an auto-configuration feature for
        # devices, such that ids are not input manually on devices

        _attempts = 0
        generated_id = ''
        while _attempts < 10 and len(generated_id) == 0:
            _attempts += 1
            new_id = create_id()
            if Device.query.filter_by(id=new_id).first() is None:
                LOGGER.debug(f" Generated a new device id {new_id}")
                return new_id

        LOGGER.error(f" Failed to generate unique device_id")
        raise HTTPRequestError(500, "Failed to generate unique device_id")

    @staticmethod
    def list_ids(token):
        """
        Fetches the list of known device ids.
        :param token: The authorization token (JWT).
        :return A JSON containing a list of devices ids
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        """

        init_tenant_context(token, db)

        data = []
        LOGGER.debug(f" Fetching list with known devices")
        for id in db.session.query(Device.id).all():
            data.append(id[0])
        return data

    @staticmethod
    def get_devices(token, params, sensitive_data=False):
        """
        Fetches known devices, potentially limited by a given value. Ordering
        might be user-configurable too.

        :param token: The authorization token (JWT).
        :param params: Parameters received from request (page_number, per_page, 
        sortBy, attr, attr_type, label, template, idsOnly)
        :param sensitive_data: Informs if sensitive data like keys should be
        returned
        :return A JSON containing pagination information and the device list
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        """
        tenant = init_tenant_context(token, db)

        pagination = {'page': params.get('page_number'), 'per_page': params.get('per_page'), 'error_out': False}

        SORT_CRITERION = {
            'id': Device.id,
            'asc:id': Device.id,
            'desc:id': desc(Device.id),
            'label': Device.label,
            'asc:label': Device.label,
            'desc:label': desc(Device.label),
            'created': Device.created,
            'asc:created': Device.created,
            'desc:created': desc(Device.created),
            'updated': Device.updated,
            'asc:updated': Device.updated,
            'desc:updated': desc(Device.updated),
            None: None
        }
        
        sortBy = SORT_CRITERION.get(params.get('sortBy'), None)
        LOGGER.debug(f" Sorting devices by {sortBy}")

        attr_filter = []
        query = params.get('attr')

        for attr_label_item in query:
            parsed = re.search('^(.+){1}=(.+){1}$', attr_label_item)
            attr_label = []
            attr_label.append(DeviceAttr.label == parsed.group(1))
            # static value must be the override, if any
            attr_label.append(text("coalesce(overrides.static_value, attrs.static_value)=:static_value ").bindparams(static_value=parsed.group(2)))
            attr_filter.append(and_(*attr_label))

        query = params.get('attr_type')
        for attr_type_item in query:
            attr_filter.append(DeviceAttr.value_type == attr_type_item)

        label_filter = []
        target_label = params.get('label')
        if target_label:
            label_filter.append(Device.label.like("%{}%".format(target_label)))

        template_filter = []
        target_template = params.get('template')
        if target_template:
            template_filter.append(DeviceTemplateMap.template_id == target_template)

        if (attr_filter): #filter by attr
            LOGGER.debug(f" Filtering devices by {attr_filter}")

            page = db.session.query(Device) \
                            .join(DeviceTemplateMap, isouter=True)

            page = page.join(DeviceTemplate) \
                    .join(DeviceAttr, isouter=True) \
                    .join(DeviceOverride, (Device.id == DeviceOverride.did) & (DeviceAttr.id == DeviceOverride.aid), isouter=True)

            page = page.filter(*label_filter) \
                    .filter(*template_filter) \
                    .filter(*attr_filter) \
                    .order_by(sortBy) \
                    .paginate(**pagination)


        elif label_filter or template_filter: # only filter by label or/and template
            
            page = db.session.query(Device)
            
            if label_filter:
                LOGGER.debug(f"Filtering devices by label: {target_label}")

            if template_filter:
                page = page.join(DeviceTemplateMap, isouter=True)
                LOGGER.debug(f"Filtering devices with template: {target_template}")     
            
            if sensitive_data: #aditional joins for sensitive data
                page = page.join(DeviceTemplate) \
                        .join(DeviceAttr, isouter=True) \
                        .join(DeviceOverride, (Device.id == DeviceOverride.did) & (DeviceAttr.id == DeviceOverride.aid), isouter=True)

            page = page.filter(*label_filter) \
                    .filter(*template_filter) \
                    .order_by(sortBy) \
                    .paginate(**pagination)

        else:
            LOGGER.debug(f" Querying devices sorted by device id")
            page = db.session.query(Device).order_by(sortBy).paginate(**pagination)

        devices = []
        
        if params.get('idsOnly').lower() in ['true', '1', '']:
            return DeviceHandler.get_only_ids(page)

        for d in page.items:
            devices.append(serialize_full_device(d, tenant, sensitive_data))


        result = {
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'devices': devices
        }

        return result

    @staticmethod
    def get_only_ids(page):

        device_id = []

        for device in page.items:
            data_device = device_schema.dump(device)
            id_device = data_device.get('id')
            device_id.append(id_device)

        return device_id

    @staticmethod
    def get_device(token, device_id, sensitive_data=False):
        """
        Fetches a single device.

        :param token: The authorization token (JWT).
        :param device_id: The requested device.
        :param sensitive_data: Informs if sensitive data like keys should be
        returned
        :return A Device
        :rtype Device, as described in DatabaseModels package
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device could not be found in
        database.
        """

        tenant = init_tenant_context(token, db)
        orm_device = assert_device_exists(device_id)
        return serialize_full_device(orm_device, tenant, sensitive_data)

    @staticmethod
    def is_device_id_valid(device_id):
        regex = re.compile(r'^[0-9a-fA-F]{2,6}$')
        return regex.match(device_id) != None

    @staticmethod
    def validate_device_id(device_id):
        """
        Validates if the device id follows the rules implemented by dojot 

        :param device_id: The device id

        :raises ValidationError: If the device id violated the rules or is too long
        """
        if not DeviceHandler.is_device_id_valid(device_id):
            raise ValidationError('Device ID must be 2-6 characters and must be hexadecimal (0-9,a-f,A-F).')  


    @classmethod
    def create_device(cls, params, token):
        """
        Creates and configures the given device.

        :param params: Parameters received from request (count, verbose, 
        content_type, data)
        :param token: The authorization token (JWT).
        
        :return The created device or a list of device summary. This depends on
        which value the verbose (/?verbose=true) has - if true, only one device
        can be created ("count" argument can't be used or - at least - it must
        be exactly "1") and the full device is returned. If false, "count" can
        be used with higher values and only the devices summary (a structure
        containing all device IDs and their labels) is returned.
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If verbose is used with multiple device
        creation request.
        :raises HTTPRequestError: If count argument ("?count=X") is provided
        and it is not an integer.

        """
        tenant = init_tenant_context(token, db)
        try:
            count = int(params.get('count'))
        except ValueError as e:
            LOGGER.error(e)
            raise HTTPRequestError(400, "If provided, count must be integer")

        c_length = len(str(count))
        verbose = params.get('verbose') in ['true', '1', 'True']
        if verbose and count != 1:
            raise HTTPRequestError(
                400, "Verbose can only be used for single device creation")

        devices = []
        full_device = None
        orm_devices = []

        try:
            for i in range(0, count):
                content_type = params.get('content_type')
                data_request = params.get('data')
                device_data, json_payload = parse_payload(content_type, data_request, device_schema)
                validate_repeated_attrs(json_payload)

                if json_payload.get('id', None) is None or count > 1 : 
                    device_data['id'] = DeviceHandler.generate_device_id()
                else:
                    DeviceHandler.validate_device_id(json_payload['id'])
                    device_data['id'] = json_payload['id']

                device_data['label'] = DeviceHandler.indexed_label(count, c_length, device_data['label'], i)
                device_data.pop('templates', None)
                orm_device = Device(**device_data)
                parse_template_list(json_payload.get('templates', []), orm_device)
                auto_create_template(json_payload, orm_device)
                db.session.add(orm_device)
                orm_devices.append(orm_device)
            db.session.commit()
        except IntegrityError as error:
            handle_consistency_exception(error)
        except ValidationError as error:
            raise HTTPRequestError(400, error.messages)


        for orm_device in orm_devices:
            devices.append(
                {
                    'id': orm_device.id,
                    'label': orm_device.label
                }
            )

            full_device = serialize_full_device(orm_device, tenant)

            # Updating handlers
            kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
            kafka_handler_instance.create(full_device, meta={"service": tenant})

        if verbose:
            result = {
                'message': 'device created',
                'devices': [full_device]
            }
        else:
            result = {
                'message': 'devices created',
                'devices': devices
            }
        return result

    def get_template_by_id(template_id, database):
        return database.session.query(DeviceTemplate) \
                                .join(DeviceAttr, isouter=True) \
                                .filter(DeviceTemplate.id == template_id)


    @classmethod
    def publish_device_creation(cls, full_device_data, tenant):

        LOGGER.debug(f"Publishing creation event into kafka for tenant {tenant}")
        # Updating handlers
        kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
        kafka_handler_instance.create(full_device_data, meta={"service": tenant})

        return;


    @classmethod
    def insert_new_device_into_database(cls, device_data, database):

        device_label = device_data['label']
        device_templates = device_data['templates']
        
        if('id' in device_data):
            device_id = device_data['id']
            LOGGER.debug(f"DeviceId is preset as: {device_id}")
            if(not DeviceHandler.is_device_id_valid(device_id)):
                LOGGER.debug(f"Preset deviceId '{device_id}' invalid pattern. Aborting...")
                raise Exception("invalid-deviceId");
            else:
                LOGGER.debug(f"Preset deviceId '{device_id}' follows the expected pattern.")
        else:
            device_id = DeviceHandler.generate_device_id()

        LOGGER.debug(f"New device will be ID'ed as: {device_id}")

        LOGGER.debug(f"Checking if the label {device_label} can be assigned to it...")
        if(DeviceHandler.label_already_exists(device_label, db)):
            LOGGER.info(f"[device {device_id}] Label {device_label} already in use")
            raise Exception("label-already-in-use");

        LOGGER.debug(f"Checking {len(device_templates)} associated templates ...")

        full_templates = []

        if(len(device_templates) == 0):
            LOGGER.info(f"[device {device_label} ({device_id})] No template IDs were informed. Aborting...")
            raise Exception("no-templates-assigned");

        template_attrs_map = {}
        for template_id in device_templates:
            LOGGER.debug(f"Checking template for templateId {template_id}")
            template_rows = DeviceHandler.get_template_by_id(template_id, db)
            
            if(template_rows.count() == 0):
                LOGGER.debug(f"No template found for templateId {template_id}")
                raise Exception("template-id-does-not-exist");

            template_data = template_rows.one()
            for attr in template_schema.dump(template_data)['attrs']:
                attr_label = attr['label']
                LOGGER.debug(f"Checking attr {attr_label} from templateId {template_id}")

                if attr_label in template_attrs_map:
                    LOGGER.info(f"Attribute named {attr_label} is duplicated between templates {template_id} and {template_attrs_map[attr_label]}")
                    raise Exception("duplicated-attribute-across-templates")
                else:
                    LOGGER.debug(f"Flagging attribute named {attr_label} as seen on the map")
                    template_attrs_map[attr_label] = template_id
            
            LOGGER.debug(f"Appending templateId {template_id} into the device")
            full_templates.append(template_data)
           
        LOGGER.debug(f"Template validation complete. Associating {len(full_templates)} templates with device {device_label} ({device_id})")
        orm_device = Device(id=device_id, label=device_label, templates=full_templates)
        database.session.add(orm_device)
        LOGGER.debug(f"Saved deviceId {device_id} entity into the database")
        return orm_device;


    def label_already_exists(label, database):
        
        LOGGER.debug(f"Checking if label {label} is already in use by a device")
        already_exists = database.session.query(database.session.query(Device).filter(Device.label == label).exists()).scalar()
        LOGGER.debug(f"Label '{label}' is {'ALREADY' if already_exists else 'NOT'} in use")
        return already_exists


    def create_devices_in_batch(devices_prefix, quantity, initial_suffix_number, templates, tenant, database):

        LOGGER.debug("Guardchecking parameters")

        if((not isinstance(devices_prefix, str)) or len(devices_prefix) == 0 ):
            raise Exception('invalid-batch-preffix')

        if((not isinstance(quantity, int)) or quantity <= 0 ):
            raise Exception('invalid-batch-quantity')

        if((not isinstance(initial_suffix_number, int)) or initial_suffix_number < 0 ):
            raise Exception('invalid-batch-suffix')

        if((not isinstance(templates, list)) or len(templates) == 0 ):
            raise Exception('invalid-batch-templates')

        if((not isinstance(tenant, str)) or len(tenant) == 0 ):
            raise Exception('invalid-batch-tenant')

        LOGGER.info(f"Starting the creation of {quantity} devices prefixed with '{devices_prefix}' for tenant {tenant}")

        devices_created = []
        devices_failed = []

        for counter in range(initial_suffix_number, (initial_suffix_number + quantity)):
            device_label = f"{devices_prefix}-{counter}"
            LOGGER.info(f"Creating device named {device_label}")

            try:
                orm_device = DeviceHandler.insert_new_device_into_database({
                    'label': device_label,
                    'templates': templates
                }, database)
                LOGGER.info(f"Serializing device data for insertion")
                full_device_data = serialize_full_device(orm_device, tenant)
                devices_created.append(full_device_data)
            except Exception as e:
                LOGGER.debug(f"[device {device_label}] Failed to create device: {e}")
                devices_failed.append({
                    'label': device_label,
                    'reason': repr(e)
                })

        database.session.commit()
        LOGGER.debug(f"Batch-insertions finished")
        LOGGER.debug(f"{len(devices_created)} successes / {len(devices_failed)} failures")

        if(len(devices_created) > 0):
            LOGGER.debug(f"Notifying created devices to kafka")

            for full_device_data in devices_created:
                device_id = full_device_data['id']
                device_label = full_device_data['label']

                LOGGER.debug(f"-- Notifying device {device_label} (id {device_id})")
                DeviceHandler.publish_device_creation(full_device_data, tenant)

        return {
            'successes': devices_created,
            'failures': devices_failed
        }

    @classmethod
    def delete_device(cls, device_id, token):
        """
        Deletes a single device.

        :param device_id: The device to be removed.
        :param token: The authorization token (JWT).
        :return The removed device.
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device could not be found in
        database.
        """

        tenant = init_tenant_context(token, db)
        orm_device = assert_device_exists(device_id)
        data = serialize_full_device(orm_device, tenant)

        kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
        kafka_handler_instance.remove(data, meta={"service": tenant})

        db.session.delete(orm_device)
        db.session.commit()

        results = {'result': 'ok', 'removed_device': data}
        return results

    @staticmethod
    def delete_all_devices(token):
        """
        Deletes all devices.

        :param token: The authorization token (JWT).
        :raises HTTPRequestError: If this device could not be found in
        database.
        """
        tenant = init_tenant_context(token, db)
        json_devices = []

        devices = db.session.query(Device)
        for device in devices:
            db.session.delete(device)
            json_devices.append(serialize_full_device(device, tenant))

        db.session.commit()

        results = {
            'result': 'ok', 
            'removed_devices': json_devices
        }

        return results

    @classmethod
    def update_device(cls, params, device_id, token):
        """
        Updated the information about a particular device

        :param params: Parameters received from request (content_type, data)
        as created by Flask
        :param device_id: The device to be updated.
        :param token: The authorization token (JWT).
        :return The updated device.
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device could not be found in
        database.
        """
        try:
            content_type = params.get('content_type')
            data_request = params.get('data')

            device_data, json_payload = parse_payload(content_type, data_request, device_schema)
            validate_repeated_attrs(json_payload)

            tenant = init_tenant_context(token, db)
            old_orm_device = assert_device_exists(device_id)
            db.session.delete(old_orm_device)
            db.session.flush()

            # handled separately by parse_template_list
            device_data.pop('templates')
            updated_orm_device = Device(**device_data)
            parse_template_list(json_payload.get('templates', []), updated_orm_device)
            auto_create_template(json_payload, updated_orm_device)
            updated_orm_device.id = device_id
            updated_orm_device.updated = datetime.now()
            updated_orm_device.created = old_orm_device.created

            db.session.add(updated_orm_device)

            db.session.commit()
        except IntegrityError as error:
            handle_consistency_exception(error)
        except ValidationError as error:
            raise HTTPRequestError(400, error.messages)

        full_device = serialize_full_device(updated_orm_device, tenant)

        kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
        kafka_handler_instance.update(full_device, meta={"service": tenant})

        result = {
            'message': 'device updated',
            'device': serialize_full_device(updated_orm_device, tenant)
        }
        return result

    @classmethod
    def configure_device(cls, params, device_id, token):
        """
        Send actuation commands to the device

        :param params: Parameters received from request (data)
        as created by Flask
        :param device_id: The device which should receive the actuation message
        :param token: The authorization token (JWT).
        :return A status on whether the message was sent to the device or not.
        Note that this is not a guarantee that the device actually performed
        what was requested.
        :rtype JSON
        """
        # Meta information to be published along with device actuation message
        meta = {
            'service': ''
        }
        invalid_attrs = []

        meta['service'] = init_tenant_context(token, db)

        meta['timestamp'] = int(time.time() * 1000)

        orm_device = assert_device_exists(device_id)
        full_device = serialize_full_device(orm_device, meta['service'])
        LOGGER.debug(f" Full device: {json.dumps(full_device)}")

        data = params.get('data')
        payload = json.loads(data)
        LOGGER.debug(f' Parsed request payload: {json.dumps(payload)}')

        payload['id'] = orm_device.id

        for attr in payload['attrs']:
            if find_attribute(full_device, attr, 'actuator') is None:
                invalid_attrs.append(attr)

        if not invalid_attrs:
            LOGGER.debug(f' Sending configuration message through Kafka.')
            kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
            kafka_handler_instance.configure(payload, meta)
            LOGGER.debug(f' Configuration sent.')
            result = {f' status': 'configuration sent to device'}
        else:
            LOGGER.warning(f' invalid attributes detected in command: {invalid_attrs}')
            result = {
                'status': 'some of the attributes are not configurable',
                'attrs': invalid_attrs
            }
            raise HTTPRequestError(403, result)

        return result

    @staticmethod
    def add_template_to_device(token, device_id, template_id):
        """
        Associates given template with device

        :param token: The authorization token (JWT).
        :param device_id: The device which should be updated
        :param template_id: The template to be added to this device.
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device or template could not be found
        in database.
        :return A status on whether the device was updated, and the new
        structure for that device.
        :rtype JSON
        """
        tenant = init_tenant_context(token, db)
        orm_device = assert_device_exists(device_id)
        orm_template = assert_template_exists(template_id)

        orm_device.templates.append(orm_template)

        try:
            db.session.commit()
        except IntegrityError as error:
            handle_consistency_exception(error)

        result = {
            'message': 'device updated',
            'device': serialize_full_device(orm_device, tenant)
        }

        return result

    @staticmethod
    def remove_template_from_device(token, device_id, template_id):
        """
        Disassociates given template with device

        :param token: The authorization token (JWT).
        :param device_id: The device which should be updated
        :param template_id: The template to be removed from this device.
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device or template could not be found
        in database.
        :return A status on whether the device was updated, and the new
        structure for that device.
        :rtype JSON
        """
        tenant = init_tenant_context(token, db)
        updated_device = assert_device_exists(device_id)
        relation = assert_device_relation_exists(device_id, template_id)

        # Here (for now) there are no more validations to perform, as template
        # removal cannot violate attribute constraints

        db.session.delete(relation)
        db.session.commit()
        result = {
            'message': 'device updated',
            'device': serialize_full_device(updated_device, tenant)
        }

        return result

    @staticmethod
    def get_by_template(token, params, template_id):
        """
        Return a list of devices that have a particular template associated to
        it

        :param token: The authorization token (JWT).
        :param params: Parameters received from request (page_number, per_page)
        as created by Flask
        :param template_id: The template to be considered
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device or template could not be found
        in database.
        :return A list of devices that are associated to the selected template.
        :rtype JSON
        """
        tenant = init_tenant_context(token, db)
        page = (
            db.session.query(Device)
            .join(DeviceTemplateMap)
            .filter_by(template_id=template_id)
            .paginate(page=params.get('page_number'), 
                per_page=params.get('per_page'), error_out=False)
        )
        devices = []
        for d in page.items:
            devices.append(serialize_full_device(d, tenant))

        result = {
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'devices': devices
        }
        return result

    @classmethod
    def gen_psk(cls, token, device_id, key_length, target_attributes=None):
        """
        Generates pre shared keys to a specifics device

        :param token: The authorization token (JWT).
        :param device_id: The target device.
        :param key_length: The key length to be generated.
        :param target_attributes: A list with the target attributes, None means
        all suitable attributes.
        :return The keys generated.
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this device could not be found in
        database.
        """

        tenant = init_tenant_context(token, db)

        device_orm = assert_device_exists(device_id, db.session)
        if not device_orm:
            raise HTTPRequestError(404, "No such device: {}".format(device_id))

        device = serialize_full_device(device_orm, tenant, True)

        # checks if the key length has been specified
        # todo remove this magic number
        if key_length > 1024 or key_length <= 0:
            raise HTTPRequestError(400, "key_length must be greater than 0 and lesser than {}".format(1024))

        is_all_psk_attr_valid = False
        target_attrs_data = []

        # find the target attributes
        # first case: if there are specified attributes
        if target_attributes:
            for template_id in device["templates"]:
                for attr in device["attrs"][template_id]:
                    if attr["value_type"] == "psk" and attr["label"] in target_attributes:
                        target_attrs_data.append(attr)
                        is_all_psk_attr_valid = True

            if not is_all_psk_attr_valid:
                raise HTTPRequestError(400, "Not found some attributes, "
                    "please check them")

            if len(target_attributes) != len(target_attrs_data):
                if not is_all_psk_attr_valid:
                    raise HTTPRequestError(400,
                                    "Some attribute is not a 'psk' type_value")
                else:
                    raise HTTPRequestError(400, "Not found some attributes, "
                        "please check them")
        else: # second case: if there are not specified attributes
            for template_id in device["templates"]:
                for attr in device["attrs"][template_id]:
                    if attr["value_type"] == "psk":
                        target_attrs_data.append(attr)
                        is_all_psk_attr_valid = True

            if not is_all_psk_attr_valid:
                # there is no psk key, do not worry it is not a problem
                raise HTTPRequestError(204, "")

        # generate the pre shared key on selected attributes
        result = []
        for attr in target_attrs_data:
            psk = secrets.token_hex(key_length)
            psk_hex = psk
            attr["static_value"] = psk_hex
            encrypted_psk = encrypt(psk)
            psk_entry = DeviceAttrsPsk.query.filter_by(device_id=device["id"],
                                                       attr_id=attr["id"]).first()
            if not psk_entry:
                db.session.add(DeviceAttrsPsk(device_id=device["id"],
                                              attr_id=attr["id"],
                                              psk=encrypted_psk))
            else:
                psk_entry.psk = encrypted_psk

            result.append( {'attribute': attr["label"], 'psk': psk_hex} )

        device_orm.updated = datetime.now()
        db.session.commit()

        # send an update message on kafka
        kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
        kafka_handler_instance.update(device, meta={"service": tenant})

        return result

    @classmethod
    def copy_psk(cls, token, src_device_id, src_attr, dest_device_id, dest_attr):
        """
        Copies a pre shared key from a device attribute to another

        :param token: The authorization token (JWT).
        :param src_device_id: The source device (from).
        :param src_attr: The source attribute (from).
        :param dest_device_id: The destination device (to).
        :param dest_attr: The destination attribute (to).
        :return None.
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        todo list the others exceptions
        """

        tenant = init_tenant_context(token, db)

        src_device_orm = assert_device_exists(src_device_id, db.session)
        if not src_device_orm:
            raise HTTPRequestError(404, "No such device: {}".format(src_device_id))

        src_device = serialize_full_device(src_device_orm, tenant, True)

        found_attr = False
        src_attr_ref = None
        for template_id in src_device["templates"]:
            for attr in src_device["attrs"][template_id]:
                if attr["label"] == src_attr:
                    if attr["value_type"] == "psk":
                        found_attr = True
                        src_attr_ref = attr
                        break
                    else:
                        raise HTTPRequestError(400,
                                "Attribute {} is not a 'psk' type_value".format(src_attr))

        if not found_attr:
            raise HTTPRequestError(404, "Not found attributes {}".format(src_attr))

        dest_device_orm = assert_device_exists(dest_device_id, db.session)
        if not dest_device_orm:
            raise HTTPRequestError(404, "No such device: {}".format(dest_device_id))

        dest_device = serialize_full_device(dest_device_orm, tenant, True)

        found_attr = False
        dest_attr_ref = None
        for template_id in dest_device["templates"]:
            for attr in dest_device["attrs"][template_id]:
                if attr["label"] == dest_attr:
                    if attr["value_type"] == "psk":
                        found_attr = True
                        dest_attr_ref = attr
                        break
                    else:
                        raise HTTPRequestError(400,
                                "Attribute {} is not a 'psk' type_value".format(dest_attr))

        if not found_attr:
            raise HTTPRequestError(404, "Not found attributes {}".format(dest_attr))

        # copy the pre shared key
        src_psk_entry = DeviceAttrsPsk.query.filter_by(device_id=src_device["id"],
                                                    attr_id=src_attr_ref["id"]).first()
        if not src_psk_entry:
            raise HTTPRequestError(400, "There is not a psk generated to {}".format(src_attr))

        dest_psk_entry = DeviceAttrsPsk.query.filter_by(device_id=dest_device["id"],
            attr_id=dest_attr_ref["id"]).first()
        if not dest_psk_entry:
            db.session.add(DeviceAttrsPsk(device_id=dest_device["id"],
                                            attr_id=dest_attr_ref["id"],
                                            psk=src_psk_entry.psk))
        else:
            dest_psk_entry.psk = src_psk_entry.psk

        dest_device_orm.updated = datetime.now()
        db.session.commit()

        dest_attr_ref['static_value'] = src_attr_ref['static_value']

        # send an update message on kafka
        kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
        kafka_handler_instance.update(dest_device, meta={"service": tenant})


@device.route('/device', methods=['GET'])
def flask_get_devices():
    """
    Fetches known devices, potentially limited by a given value. Ordering might
    be user-configurable too.

    Check API description for more information about request parameters and
    headers.
    """
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        # retrieve pagination
        page_number, per_page = get_pagination(request)

        params = {
            'page_number': page_number,
            'per_page': per_page,
            'sortBy': request.args.get('sortBy', None),
            'attr': request.args.getlist('attr'),
            'attr_type': request.args.getlist('attr_type'),
            'label': request.args.get('label', None),
            'template': request.args.get('template', None),
            'idsOnly': request.args.get('idsOnly', 'false'),
        }

        result = DeviceHandler.get_devices(token, params)
        LOGGER.info(f' Getting latest added device(s).')

        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/batch', methods=['POST'])
def flask_create_devices_in_batch_service():
    """
    Creates and configures the given device (in json).

    Check API description for more information about request parameters and
    headers.
    """
    LOGGER.info(f"Requisição recebida de criação de dispositivos em lote")
    return create_devices_in_batch_service(request)

def create_devices_in_batch_service(request):
    try:
        # retrieve the authorization token
        LOGGER.debug(f"Retrieving token...")
        token = retrieve_auth_token(request)
        LOGGER.debug(f"Retrieved token: {token}")

        tenant = init_tenant_context(token, db)
    
        request_body = request.get_json()
        devices_prefix = request_body.get('devicesPrefix', '')
        quantity = request_body.get('quantity', 1)
        initial_suffix_number = request_body.get('initialSuffixNumber', 1)
        templates = request_body.get('templates', [])

        LOGGER.debug(f"Creating {quantity} devices. Prefix: '{devices_prefix}' with suffix counter starting at {initial_suffix_number}")

        result = DeviceHandler.create_devices_in_batch(devices_prefix, quantity, initial_suffix_number, templates, tenant, db)
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device', methods=['POST'])
def flask_create_device():
    """
    Creates and configures the given device (in json).

    Check API description for more information about request parameters and
    headers.
    """
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        params = {
            'count': request.args.get('count', '1'),
            'verbose': request.args.get('verbose', 'false'),
            'content_type': request.headers.get('Content-Type'),
            'data': request.data
        }

        result = DeviceHandler.create_device(params, token)
        devices = result.get('devices')
        deviceId = devices[0].get('id')
        LOGGER.info(f' Creating a new device with id {deviceId}.')
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)

@device.route('/device', methods=['DELETE'])
def flask_delete_all_device():
    """
    Creates and configures the given device (in json).

    Check API description for more information about request parameters and
    headers.
    """
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        result = DeviceHandler.delete_all_devices(token)

        LOGGER.info('Deleting all devices.')
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')

        return format_response(e.error_code, e.message)

@device.route('/device/<device_id>', methods=['GET'])
def flask_get_device(device_id):
    try:
         # retrieve the authorization token
        token = retrieve_auth_token(request)

        result = DeviceHandler.get_device(token, device_id)
        LOGGER.info(f' Getting the device with id {device_id}.')
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)

@device.route('/device/<device_id>', methods=['DELETE'])
def flask_remove_device(device_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        LOGGER.info(f' Removing the device with id {device_id}.')
        results = DeviceHandler.delete_device(device_id, token)
        return make_response(jsonify(results), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/<device_id>', methods=['PUT'])
def flask_update_device(device_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        params = {
            'content_type': request.headers.get('Content-Type'),
            'data': request.data
        }

        LOGGER.info(f' Updating the device with id {device_id}.')
        results = DeviceHandler.update_device(params, device_id, token)
        return make_response(jsonify(results), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/<device_id>/actuate', methods=['PUT'])
def flask_configure_device(device_id):
    """
    Send actuation commands to the device
    """
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        params = {'data': request.data}

        LOGGER.info(f' Actuating in the device with id {device_id}.')
        result = DeviceHandler.configure_device(params, device_id, token)
        return make_response(jsonify(result), 200)

    except HTTPRequestError as error:
        LOGGER.error(f' {error.message} - {error.error_code}.')
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)

        return format_response(error.error_code, error.message)


# Convenience template ops
@device.route('/device/<device_id>/template/<template_id>', methods=['POST'])
def flask_add_template_to_device(device_id, template_id):
    try:
         # retrieve the authorization token
        token = retrieve_auth_token(request)

        LOGGER.info(f' Adding template with id {template_id} in the device {device_id}.')
        result = DeviceHandler.add_template_to_device(
            token, device_id, template_id)
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/<device_id>/template/<template_id>', methods=['DELETE'])
def flask_remove_template_from_device(device_id, template_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        LOGGER.info(f' Removing template with id {template_id} in the device {device_id}.')
        result = DeviceHandler.remove_template_from_device(
            token, device_id, template_id)
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/template/<template_id>', methods=['GET'])
def flask_get_by_template(template_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        # retrieve pagination
        page_number, per_page = get_pagination(request)

        params = {
            'page_number': page_number,
            'per_page': per_page,
        }

        LOGGER.info(f' Getting devices with template id {template_id}.')
        result = DeviceHandler.get_by_template(token, params, template_id)
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/gen_psk/<device_id>', methods=['POST'])
def flask_gen_psk(device_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        # retrieve the key_length parameter (mandatory)
        if not 'key_length' in request.args.keys():
            raise HTTPRequestError(400, "Missing key_length parameter")
        key_length = int(request.args['key_length'])

        # retrieve the attrs parameter (optional)
        target_attributes = None
        if 'attrs' in request.args.keys():
            target_attributes = request.args['attrs'].split(",")

        result = DeviceHandler.gen_psk(token,
                                       device_id,
                                       key_length,
                                       target_attributes)

        LOGGER.info(f' Successfully generated psk for the device: {device_id}.')
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/device/<device_id>/attrs/<attr_label>/psk', methods=['PUT'])
def flask_copy_psk(device_id, attr_label):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        # retrieve the parameters
        if ((not 'from_dev_id' in request.args.keys()) or
            (not 'from_attr_label' in request.args.keys())):
            raise HTTPRequestError(400, "Missing mandatory parameter: from_dev_id "
                "or/and from_attr_label")

        from_dev_id = request.args['from_dev_id']
        from_attr_label = request.args['from_attr_label']

        DeviceHandler.copy_psk(token,
                                from_dev_id,
                                from_attr_label,
                                device_id,
                                attr_label)

        return make_response("", 204)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


# Internal endpoints
@device.route('/internal/device', methods=['GET'])
def flask_internal_get_devices():
    """
    Fetches known devices, potentially limited by a given value. Ordering might
    be user-configurable too.

    Check API description for more information about request parameters and
    headers.
    """
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        # retrieve pagination
        page_number, per_page = get_pagination(request)

        params = {
            'page_number': page_number,
            'per_page': per_page,
            'sortBy': request.args.get('sortBy', None),
            'attr': request.args.getlist('attr'),
            'attr_type': request.args.getlist('attr_type'),
            'label': request.args.get('label', None),
            'template': request.args.get('template', None),
            'idsOnly': request.args.get('idsOnly', 'false'),
        }

        result = DeviceHandler.get_devices(token, params, True)
        LOGGER.info(f' Getting known internal devices.')
        
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


@device.route('/internal/device/<device_id>', methods=['GET'])
def flask_internal_get_device(device_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        result = DeviceHandler.get_device(token, device_id, True)
        LOGGER.info(f'Get known device with id: {device_id}.')
        return make_response(jsonify(result), 200)
    except HTTPRequestError as e:
        LOGGER.error(f' {e.message} - {e.error_code}.')
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)

        return format_response(e.error_code, e.message)


app.register_blueprint(device)
