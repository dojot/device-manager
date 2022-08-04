import logging
import re
from flask import Blueprint, request, jsonify, make_response
from flask_sqlalchemy import BaseQuery, Pagination
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text, collate, func
from sqlalchemy import desc

from DeviceManager.DatabaseHandler import db
from DeviceManager.DatabaseModels import handle_consistency_exception, assert_template_exists, assert_device_exists
from DeviceManager.DatabaseModels import DeviceTemplate, DeviceAttr, DeviceTemplateMap
from DeviceManager.SerializationModels import template_list_schema, template_schema
from DeviceManager.SerializationModels import attr_list_schema, attr_schema, metaattr_schema
from DeviceManager.SerializationModels import parse_payload, load_attrs
from DeviceManager.SerializationModels import ValidationError
from DeviceManager.TenancyManager import init_tenant_context
from DeviceManager.KafkaNotifier import KafkaNotifier, DeviceEvent

from DeviceManager.app import app
from DeviceManager.utils import format_response, HTTPRequestError, get_pagination, retrieve_auth_token

from DeviceManager.Logger import Log
from datetime import datetime

from DeviceManager.BackendHandler import KafkaHandler, KafkaInstanceHandler
from DeviceManager.DeviceHandler import serialize_full_device

import time
import json

template = Blueprint('template', __name__)

LOGGER = Log().color_log()

def attr_format(attrs_format, result):
    """ formats output attr list acording to user input """

    def remove(d,k):
        try:
            LOGGER.info(f' will remove {k}')
            d.pop(k)
        except KeyError:
            pass

    if attrs_format == 'split':
        remove(result, 'attrs')
    elif attrs_format == 'single':
        remove(result, 'config_attrs')
        remove(result, 'data_attrs')

    return result

def paginate(query, page, per_page=20, error_out=False):
    if error_out and page < 1:
        return None
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    if not items and page != 1 and error_out:
        return None

    if page == 1 and len(items) < per_page:
        total = len(items)
    else:
        total = query.count()

    return Pagination(query, page, per_page, total, items)

def refresh_template_update_column(db, template):
    if db.session.new or db.session.deleted:
        LOGGER.debug('The template structure has changed, refreshing "updated" column.')
        template.updated = datetime.now()

class TemplateHandler():

    kafka = KafkaInstanceHandler()

    def __init__(self):
        pass

    @staticmethod
    def get_templates(params, token):
        """
        Fetches known templates, potentially limited by a given value. Ordering
        might be user-configurable too.

        :param params: Parameters received from request (page_number, per_page,
        sort_by, attr, attr_type, label, attrs_format)
        as created by Flask
        :param token: The authorization token (JWT).
        :return A JSON containing pagination information and the template list
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        """
        LOGGER.debug(f"Retrieving templates.")
        LOGGER.debug(f"Initializing tenant context...")
        init_tenant_context(token, db)
        LOGGER.debug(f"... tenant context initialized.")

        pagination = {'page': params.get('page_number'), 'per_page': params.get('per_page'), 'error_out': False}

        LOGGER.debug(f"Pagination configuration is {pagination}")

        parsed_query = []
        query = params.get('attr')

        for attr in query:
            LOGGER.debug(f"Analyzing query parameter: {attr}...")
            parsed = re.search('^(.+){1}=(.+){1}$', attr)
            parsed_query.append(DeviceAttr.label == parsed.group(1))
            parsed_query.append(DeviceAttr.static_value == parsed.group(2))
            LOGGER.debug("... query parameter was added to filter list.")

        query = params.get('attr_type')

        for attr_type_item in query:
            parsed_query.append(DeviceAttr.value_type == attr_type_item)

        target_label = params.get('label')

        if target_label:
            LOGGER.debug(f"Adding label filter to query...")
            parsed_query.append(DeviceTemplate.label.like("%{}%".format(target_label)))
            LOGGER.debug(f"... filter was added to query.")

        SORT_CRITERION = {
            'id': DeviceTemplate.id,
            'asc:id': DeviceTemplate.id,
            'desc:id': desc(DeviceTemplate.id),
            'label': DeviceTemplate.label,
            'asc:label': DeviceTemplate.label,
            'desc:label': desc(DeviceTemplate.label),
            'created': DeviceTemplate.created,
            'asc:created': DeviceTemplate.created,
            'desc:created': desc(DeviceTemplate.created),
            'updated': DeviceTemplate.updated,
            'asc:updated': DeviceTemplate.updated,
            'desc:updated': desc(DeviceTemplate.updated),
            None: None
        }

        sortBy = SORT_CRITERION.get(params.get('sortBy'), None)
        LOGGER.debug(f" Sorting templates by {sortBy}")

        LOGGER.debug(f"Sortby filter is {sortBy}")
        if parsed_query:
            LOGGER.debug(f" Filtering template by {parsed_query}")

            # Always sort by DeviceTemplate.id
            page = db.session.query(DeviceTemplate) \
                             .join(DeviceAttr, isouter=True) \
                             .filter(*parsed_query) \
                             .order_by(DeviceTemplate.id)
            if sortBy:
                page = page.order_by(sortBy)

            page = page.distinct(DeviceTemplate.id)

            LOGGER.debug(f"Current query: {type(page)}")
            page = paginate(page, **pagination)
        else:
            LOGGER.debug(f" Querying templates sorted by {sortBy}")
            page = db.session.query(DeviceTemplate).order_by(sortBy).paginate(**pagination)

        templates = []
        for template in page.items:
            formatted_template = attr_format(params.get('attrs_format'), template_schema.dump(template))
            LOGGER.debug(f"Adding resulting template to response...")
            LOGGER.debug(f"Template is: {formatted_template['label']}")
            templates.append(formatted_template)
            LOGGER.debug(f"... template was added to response.")

        result = {
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'templates': templates
        }

        LOGGER.debug(f"Full response is {result}")

        return result

    @staticmethod
    def create_template(params, token):
        """
        Creates a new template.

        :param params: Parameters received from request (content_type, data)
        as created by Flask
        :param token: The authorization token (JWT).
        :return The created template.
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If template attribute constraints were
        violated. This might happen if two attributes have the same name, for
        instance.
        """
        init_tenant_context(token, db)

        content_type = params.get('content_type')
        data_request = params.get('data')
        tpl, json_payload = parse_payload(content_type, data_request, template_schema)

        loaded_template = DeviceTemplate(**tpl)
        load_attrs(json_payload['attrs'], loaded_template, DeviceAttr, db)
        db.session.add(loaded_template)

        try:
            db.session.commit()
            LOGGER.debug(f" Created template in database")
        except IntegrityError as e:
            LOGGER.error(f' {e}')
            raise HTTPRequestError(400, 'Template attribute constraints are violated by the request')

        results = {
            'template': template_schema.dump(loaded_template),
            'result': 'ok'
        }
        return results

    @staticmethod
    def get_template(params, template_id, token):
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
        init_tenant_context(token, db)
        tpl = assert_template_exists(template_id)
        json_template = template_schema.dump(tpl)
        attr_format(params.get('attr_format'), json_template)
        return json_template

    @staticmethod
    def delete_all_templates(token):
        """
        Deletes all templates.

        :param token: The authorization token (JWT).
        :raises HTTPRequestError: If this template could not be found in
        database.
        """
        init_tenant_context(token, db)
        json_templates = []

        try:
            templates = db.session.query(DeviceTemplate)
            for template in templates:
                db.session.delete(template)
                json_templates.append(template_schema.dump(template))

            db.session.commit()
        except IntegrityError:
            raise HTTPRequestError(400, "Templates cannot be removed as they are being used by devices")

        results = {
            'result': 'ok',
            'removed': json_templates
        }

        return results

    @staticmethod
    def remove_template(template_id, token):
        """
        Deletes a single template.

        :param template_id: The template to be removed.
        :param token: The authorization token (JWT).
        :return The removed template.
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this template could not be found in
        database.
        :raises HTTPRequestError: If the template is being currently used by
        a device.
        """
        init_tenant_context(token, db)
        tpl = assert_template_exists(template_id)

        json_template = template_schema.dump(tpl)
        try:
            db.session.delete(tpl)
            db.session.commit()
        except IntegrityError:
            raise HTTPRequestError(400, "Templates cannot be removed as they are being used by devices")

        results = {
            'result': 'ok',
            'removed': json_template
        }

        return results

    @classmethod
    def update_template(cls, params, template_id, token):
        """
        Updates a single template.

        :param params: Parameters received from request (content_type, data)
        as created by Flask
        :param template_id: The template to be updated.
        :param token: The authorization token (JWT).
        :return The old version of this template (previous to the update).
        :rtype JSON
        :raises HTTPRequestError: If no authorization token was provided (no
        tenant was informed)
        :raises HTTPRequestError: If this template could not be found in
        database.
        """
        service = init_tenant_context(token, db)

        content_type = params.get('content_type')
        data_request = params.get('data')

        # find old version of the template, if any
        old = assert_template_exists(template_id)
        # parse updated version from payload
        updated, json_payload = parse_payload(content_type, data_request, template_schema)
        
        LOGGER.debug(f" Current json payload: {json_payload}")

        old.label = updated['label']

        new = json_payload['attrs']
        LOGGER.debug(f" Checking old template attributes")
        def attrs_match(attr_from_db, attr_from_request):
            return ((attr_from_db.label == attr_from_request["label"]) and
              (attr_from_db.type == attr_from_request["type"]))

        def update_attr(attrs_from_db, attrs_from_request):
            attrs_from_db.value_type = attrs_from_request.get('value_type', None)
            attrs_from_db.static_value = attrs_from_request.get('static_value', None)

        def validate_attr(attr_from_request, is_meta):
            if is_meta is False:
                attr_schema.load(attr_from_request)
            else:
                metaattr_schema.load(attr_from_request)

        def analyze_attrs(attrs_from_db, attrs_from_request, parentAttr=None):
            for attr_from_db in attrs_from_db:
                found = False
                for idx, attr_from_request in enumerate(attrs_from_request):
                    validate_attr(attr_from_request, parentAttr is not None)
                    if attrs_match(attr_from_db, attr_from_request):
                        update_attr(attr_from_db, attr_from_request)
                        if "metadata" in attr_from_request:
                            analyze_attrs(attr_from_db.children, attr_from_request["metadata"], attr_from_db)
                        attrs_from_request.pop(idx)
                        found = True
                        break
                if not found:
                    LOGGER.debug(f" Removing attribute {attr_from_db.label}")
                    db.session.delete(attr_from_db)
            if parentAttr and attrs_from_request is not None:
                for attr_from_request in attrs_from_request:
                    orm_child = DeviceAttr(parent=parentAttr, **attr_from_request)
                    db.session.add(orm_child)
            return attrs_from_request

        to_be_added = analyze_attrs(old.attrs, new)
        for attr in to_be_added:
            LOGGER.debug(f" Adding new attribute {attr}")
            if "id" in attr:
                del attr["id"]
            child = DeviceAttr(template=old, **attr)
            db.session.add(child)
            if "metadata" in attr and attr["metadata"] is not None:
                for metadata in attr["metadata"]:
                    LOGGER.debug(f" Adding new metadata {metadata}")
                    orm_child = DeviceAttr(parent=child, **metadata)
                    db.session.add(orm_child)
        try:
            LOGGER.debug(f" Commiting new data...")
            refresh_template_update_column(db, old)
            db.session.commit()
            LOGGER.debug("... data committed.")
        except IntegrityError as error:
            LOGGER.debug(f"  ConsistencyException was thrown.")
            handle_consistency_exception(error)

        # notify interested parties that a set of devices might have been implicitly updated
        affected = db.session.query(DeviceTemplateMap) \
                             .filter(DeviceTemplateMap.template_id==template_id) \
                             .all()

        affected_devices = []
        
        kafka_handler_instance = cls.kafka.getInstance(cls.kafka.kafkaNotifier)
        for device in affected:
            orm_device = assert_device_exists(device.device_id)
            kafka_handler_instance.update(serialize_full_device(orm_device, service), meta={"service": service})
            affected_devices.append(device.device_id)

        event = {
            "event": DeviceEvent.TEMPLATE,
            "data": {
                "affected": affected_devices,
                "template": template_schema.dump(old)
            },
            "meta": {"service": service}
        }
        kafka_handler_instance.kafkaNotifier.send_raw(event, service)

        results = {
            'updated': template_schema.dump(old),
            'result': 'ok'
        }
        return results


@template.route('/template', methods=['GET'])
def flask_get_templates():
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
            'attrs_format': request.args.get('attr_format', 'both')
        }

        result = TemplateHandler.get_templates(params, token)

        for templates in result.get('templates'):
            LOGGER.info(f" Getting template with id {templates.get('id')}")

        return make_response(jsonify(result), 200)

    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f" {e}")
        return make_response(jsonify(results), 500)

    except HTTPRequestError as e:
        LOGGER.error(f" {e}")
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)
        return format_response(e.error_code, e.message)


@template.route('/template', methods=['POST'])
def flask_create_template():
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        params = {
            'content_type': request.headers.get('Content-Type'),
            'data': request.data
        }

        result = TemplateHandler.create_template(params, token)

        LOGGER.info(f"Creating a new template")

        return make_response(jsonify(result), 200)

    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f" {e}")
        return make_response(jsonify(results), 400)
    except HTTPRequestError as error:
        LOGGER.error(f" {error}")
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)
        return format_response(error.error_code, error.message)


@template.route('/template', methods=['DELETE'])
def flask_delete_all_templates():

    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        result = TemplateHandler.delete_all_templates(token)

        LOGGER.info(f"deleting all templates")

        return make_response(jsonify(result), 200)

    except HTTPRequestError as error:
        LOGGER.error(f" {error}")
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)
        return format_response(error.error_code, error.message)


@template.route('/template/<template_id>', methods=['GET'])
def flask_get_template(template_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        params = {'attrs_format': request.args.get('attr_format', 'both')}

        result = TemplateHandler.get_template(params, template_id, token)
        LOGGER.info(f"Getting template with id: {template_id}")
        return make_response(jsonify(result), 200)
    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f" {e}")
        return make_response(jsonify(results), 500)
    except HTTPRequestError as e:
        LOGGER.error(f" {e}")
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)
        return format_response(e.error_code, e.message)


@template.route('/template/<template_id>', methods=['DELETE'])
def flask_remove_template(template_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        result = TemplateHandler.remove_template(template_id, token)
        LOGGER.info(f"Removing template with id: {template_id}")
        return make_response(jsonify(result), 200)
    except ValidationError as e:
        results = {'message': 'failed to parse attr', 'errors': e}
        LOGGER.error(f" {e.message}")
        return make_response(jsonify(results), 500)
    except HTTPRequestError as e:
        LOGGER.error(f" {e.message}")
        if isinstance(e.message, dict):
            return make_response(jsonify(e.message), e.error_code)
        return format_response(e.error_code, e.message)


@template.route('/template/<template_id>', methods=['PUT'])
def flask_update_template(template_id):
    try:
        # retrieve the authorization token
        token = retrieve_auth_token(request)

        params = {
            'content_type': request.headers.get('Content-Type'),
            'data': request.data
        }

        result = TemplateHandler.update_template(params, template_id, token)
        LOGGER.info(f"Updating template with id: {template_id}")
        return make_response(jsonify(result), 200)
    except ValidationError as errors:
        results = {'message': 'failed to parse attr', 'errors': errors.messages}
        LOGGER.error(f' Error in load attrs {errors.messages}')
        return make_response(jsonify(results), 400)
    except HTTPRequestError as error:
        LOGGER.error(f" {error.message}")
        if isinstance(error.message, dict):
            return make_response(jsonify(error.message), error.error_code)
        return format_response(error.error_code, error.message)


app.register_blueprint(template)
