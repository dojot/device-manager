import os
import json
import logging
from time import time
from flask import Flask, Blueprint, request, make_response
from sqlalchemy.sql import text

from DatabaseModels import *
from SerializationModels import *
from TenancyManager import init_tenant_context

from app import app
from utils import *

LOGGER = logging.getLogger('device-manager.' + __name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)

template = Blueprint('template', __name__)

@template.route('/template', methods=['GET'])
def get_templates():
    try:
        init_tenant_context(request, db)

        page_number, per_page = get_pagination(request)
        page = DeviceTemplate.query.paginate(page=int(page_number), per_page=int(per_page),
                                             error_out=False)
        templates = template_list_schema.dump(page.items).data
        result = {
            'pagination': {
                'page': page.page,
                'total': page.pages,
                'has_next': page.has_next,
                'next_page': page.next_num
            },
            'templates': templates
        }
        return make_response(json.dumps(result), 200)

    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@template.route('/template', methods=['POST'])
def create_template():
    try:
        init_tenant_context(request, db)
        tpl, json_payload = parse_payload(request, template_schema)
        loaded_template = DeviceTemplate(**tpl)
        load_attrs(json_payload['attrs'], loaded_template, DeviceAttr, db)
        db.session.add(loaded_template)
        db.session.commit()
        results = json.dumps({
            'template': template_schema.dump(loaded_template).data,
            'result': 'ok'
        })
        return make_response(results, 200)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@template.route('/template/<templateid>', methods=['GET'])
def get_template(templateid):
    try:
        init_tenant_context(request, db)
        tpl = assert_template_exists(templateid)
        json_template = template_schema.dump(tpl).data
        return make_response(json.dumps(json_template), 200)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)

@template.route('/template/<templateid>', methods=['DELETE'])
def remove_template(templateid):
    try:
        init_tenant_context(request, db)
        tpl = assert_template_exists(templateid)

        json_template = template_schema.dump(tpl).data
        db.session.delete(tpl)
        db.session.commit()

        results = json.dumps({'result': 'ok', 'removed':json_template})
        return make_response(results, 200)
    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)


@template.route('/template/<templateid>', methods=['PUT'])
def update_template(templateid):
    try:
        init_tenant_context(request, db)

        # find old version of the template, if any
        old = assert_template_exists(templateid)
        # parse updated version from payload
        updated, json_payload = parse_payload(request, template_schema)
        old.label = updated['label']

        for attr in old.attrs:
            db.session.delete(attr)
        for attr in json_payload['attrs']:
            mapped = DeviceAttr(template=old, **attr)
            db.session.add(mapped)

        db.session.commit()
        results = {
            'updated': template_schema.dump(old).data,
            'result': 'ok'
        }
        return make_response(json.dumps(results), 200)

    except HTTPRequestError as e:
        if isinstance(e.message, dict):
            return make_response(json.dumps(e.message), e.error_code)
        else:
            return format_response(e.error_code, e.message)


app.register_blueprint(template)
