import logging
import re
from flask import Blueprint, request, jsonify, make_response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text, collate, func

from DeviceManager.DatabaseHandler import db
from DeviceManager.DatabaseModels import handle_consistency_exception, assert_template_exists
from DeviceManager.DatabaseModels import DeviceTemplate, DeviceAttr, DeviceTemplateMap
from DeviceManager.SerializationModels import template_list_schema, template_schema
from DeviceManager.SerializationModels import attr_list_schema, attr_schema
from DeviceManager.SerializationModels import parse_payload, load_attrs
from DeviceManager.SerializationModels import ValidationError
from DeviceManager.TenancyManager import init_tenant_context
from DeviceManager.KafkaNotifier import send_raw, DeviceEvent

from DeviceManager.app import app
from DeviceManager.utils import format_response, HTTPRequestError, get_pagination

from DeviceManager.Logger import Log
from datetime import datetime
import time


template = Blueprint('template', __name__)
timeStamp = datetime.fromtimestamp(time.time()).strftime('%d/%m/%Y:%H:%M:%S')
LOGGER = Log().color_log()

def attr_format(req, result):
    """ formats output attr list acording to user input """
    attrs_format = req.args.get('attr_format', 'both')

    def remove(d,k):
        try:
            LOGGER.info(f'[{timeStamp}] |{__name__}| will remove {k}')
            d.pop(k)
        except KeyError:
            pass

    if attrs_format == 'split':
        remove(result, 'attrs')
    elif attrs_format == 'single':
        remove(result, 'config_attrs')
        remove(result, 'data_attrs')

    return result


class TemplateHandler:

    def __init__(self):
        pass

    @staticmethod
    def get_templates(req):
        """
        Fetches known templates, potentially limited by a given value. Ordering
        might be user-configurable too.

        :param req: The received HTTP request, as created by Flask.
        :return A JSON containing pagination information and the template list
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        """
        init_tenant_context(req, db)

        page_number, per_page = get_pagination(req)
        pagination = {'page': page_number, 'per_page': per_page, 'error_out': False}

        parsed_query = []
        query = req.args.getlist('attr')
        for attr in query:
            parsed = re.search('^(.+){1}=(.+){1}$', attr)
            parsed_query.append(text("attrs.label = '{}'".format(parsed.group(1))))
            parsed_query.append(text("attrs.static_value = '{}'".format(parsed.group(2))))

        target_label = req.args.get('label', None)
        if target_label:
            parsed_query.append(text("templates.label like '%{}%'".format(target_label)))

        SORT_CRITERION = {
            'label': DeviceTemplate.label,
            None: DeviceTemplate.id
        }
        sortBy = SORT_CRITERION.get(req.args.get('sortBy', None), DeviceTemplate.id)

        if parsed_query:
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Filtering template by {parsed_query}")
            page = db.session.query(DeviceTemplate) \
                             .join(DeviceAttr, isouter=True) \
                             .filter(*parsed_query) \
                             .order_by(sortBy) \
                             .paginate(**pagination)
        else:
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Querying templates sorted by {sortBy}")
            page = db.session.query(DeviceTemplate).order_by(sortBy).paginate(**pagination)

        templates = []
        for template in page.items:
            templates.append(attr_format(req, template_schema.dump(template)))

        result = {
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'templates': templates
        }

        return result

    @staticmethod
    def create_template(req):
        """
        Creates a new template.

        :param req: The received HTTP request, as created by Flask.
        :return The created template.
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If template attribute constraints were
        violated. This might happen if two attributes have the same name, for
        instance.
        """
        init_tenant_context(req, db)
        tpl, json_payload = parse_payload(req, template_schema)
        loaded_template = DeviceTemplate(**tpl)
        load_attrs(json_payload['attrs'], loaded_template, DeviceAttr, db)
        db.session.add(loaded_template)

        try:
            db.session.commit()
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Created template in database")
        except IntegrityError as e:
            LOGGER.error(f'[{timeStamp}] |{__name__}| {e}')
            raise HTTPRequestError(400, 'Template attribute constraints are violated by the request')

        results = {
            'template': template_schema.dump(loaded_template),
            'result': 'ok'
        }
        return results

    @staticmethod
    def get_template(req, template_id):
        """
        Fetches a single template.
        :param req: The received HTTP request, as created by Flask.
        :param template_id: The requested template ID.
        :return A Template
        :rtype Template, as described in DatabaseModels package
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this template could not be found in
        database.
        """
        init_tenant_context(req, db)
        tpl = assert_template_exists(template_id)
        json_template = template_schema.dump(tpl)
        attr_format(req, json_template)
        return json_template

    @staticmethod
    def remove_template(req, template_id):
        """
        Deletes a single template.

        :param req: The received HTTP request, as created by Flask.
        :param template_id: The template to be removed.
        :return The removed template.
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this template could not be found in
        database.
        :raises HTTPRequestError: If the template is being currently used by
        a device.
        """
        init_tenant_context(req, db)
        tpl = assert_template_exists(template_id)

        json_template = template_schema.dump(tpl)
        try:
            db.session.delete(tpl)
            db.session.commit()
        except IntegrityError:
            raise HTTPRequestError(400, "Template cannot be removed as it is \
                    being used by devices")

        results = {
            'result': 'ok',
            'removed': json_template
        }

        return results

    @staticmethod
    def update_template(req, template_id):
        """
        Updates a single template.

        :param req: The received HTTP request, as created by Flask.
        :param template_id: The template to be updated.
        :return The old version of this template (previous to the update).
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this template could not be found in
        database.
        """
        service = init_tenant_context(req, db)

        # find old version of the template, if any
        old = assert_template_exists(template_id)
        # parse updated version from payload
        updated, json_payload = parse_payload(req, template_schema)

        LOGGER.debug(f"[{timeStamp}] |{__name__}| Current json payload: {json_payload}")

        old.label = updated['label']

        new = json_payload['attrs']
        LOGGER.debug(f"[{timeStamp}] |{__name__}| Checking old template attributes")
        for a in old.attrs:
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Checking attribute {a}...")
            found = False
            for idx, b in enumerate(new):
                LOGGER.debug(f"[{timeStamp}] |{__name__}| Comparing against new attribute {b}")
                if (a.label == b['label']) and (a.type == b['type']):
                    found = True
                    a.value_type = b.get('value_type', None)
                    a.static_value = b.get('static_value', None)
                    new.pop(idx)
                    LOGGER.debug(f"[{timeStamp}] |{__name__}| They match. Attribute data will be updated.")
                    break
            if not found:
                LOGGER.debug(f"[{timeStamp}] |{__name__}| No match for this attribute. It will be removed.")
                db.session.delete(a)

        for a in new:
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Adding new attribute {a}")
            if "id" in a:
                del a["id"]
            db.session.add(DeviceAttr(template=old, **a))

        try:
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Commiting new data...")
            db.session.commit()
            LOGGER.debug("... data committed.")
        except IntegrityError as error:
            LOGGER.debug(f"[{timeStamp}] |{__name__}|  ConsistencyException was thrown.")
            handle_consistency_exception(error)

        # notify interested parties that a set of devices might have been implicitly updated
        affected = db.session.query(DeviceTemplateMap) \
                             .filter(DeviceTemplateMap.template_id==template_id) \
                             .all()

        affected_devices = []
        for device in affected:
            affected_devices.append(device.device_id)

        event = {
            "event": DeviceEvent.TEMPLATE,
            "data": {
                "affected": affected_devices,
                "template": template_schema.dump(old)
            },
            "meta": {"service": service}
        }
        send_raw(event, service)

        results = {
            'updated': template_schema.dump(old),
            'result': 'ok'
        }
        return results


@template.route('/template', methods=['GET'])
def flask_get_templates():
    try:
        result = TemplateHandler.get_templates(request)

        for templates in result.get('templates'):
            LOGGER.info(f"[{timeStamp}] |{__name__}| Getting template with id {templates.get('id')}")
        
        return make_response(jsonify(result), 200)

    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e}")
        return make_response(jsonify(results), 500)

    except HTTPRequestError as e:
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e}")
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)


@template.route('/template', methods=['POST'])
def flask_create_template():
    try:
        result = TemplateHandler.create_template(request)
        
        LOGGER.info(f"{timeStamp}] |{__name__}| Creating a new template")        
        
        return make_response(jsonify(result), 200)

    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e}")
        return make_response(jsonify(results), 400)
    except HTTPRequestError as error:
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e}")
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)
        else:
            return format_response(error.error_code, error.message)


@template.route('/template/<template_id>', methods=['GET'])
def flask_get_template(template_id):
    try:
        result = TemplateHandler.get_template(request, template_id)
        LOGGER.info(f"Getting template with id: {template_id}")
        return make_response(jsonify(result), 200)
    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e}")
        return make_response(jsonify(results), 500)
    except HTTPRequestError as e:
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e}")
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)


@template.route('/template/<template_id>', methods=['DELETE'])
def flask_remove_template(template_id):
    try:
        result = TemplateHandler.remove_template(request, template_id)
        LOGGER.info(f"Removing template with id: {template_id}")
        return make_response(jsonify(result), 200)
    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e.message}")
        return make_response(jsonify(results), 500)
    except HTTPRequestError as e:
        LOGGER.error(f"[{timeStamp}] |{__name__}| {e.message}")
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)


@template.route('/template/<template_id>', methods=['PUT'])
def flask_update_template(template_id):
    try:
        result = TemplateHandler.update_template(request, template_id)
        LOGGER.info(f"Updating template with id: {template_id}")
        return make_response(jsonify(result), 200)
    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f"[{timeStamp}] |{__name__}| {error.message}")
        return make_response(jsonify(results), 500)
    except HTTPRequestError as error:
        LOGGER.error(f"[{timeStamp}] |{__name__}| {error.message}")
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)
        else:
            return format_response(error.error_code, error.message)


app.register_blueprint(template)
