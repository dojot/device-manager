import os
import json
import logging
from time import time
from flask import Flask, Blueprint, request, make_response
from sqlalchemy.sql import text

from DatabaseModels import db, DeviceTemplate, DeviceAttr
import SerializationModels
from TenancyManager import init_tenant_context

from app import app
from utils import formatResponse

LOGGER = logging.getLogger('device-manager.' + __name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)

template = Blueprint('template', __name__)

@template.route('/template', methods=['GET'])
def get_templates():
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    # TODO those should come from querystring
    page = 1
    per_page = 20

    page = DeviceTemplate.query.paginate(page=page, per_page=per_page)
    templates = SerializationModels.template_list_schema.dump(page.items).data

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

@template.route('/template', methods=['POST'])
def create_template():
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    json_payload = request.get_json()
    if json_payload is None:
        return formatResponse(400, "Payload must be valid JSON, and Content-Type set accordingly")
    tpl, errors = SerializationModels.template_schema.load(json_payload)
    if errors:
        results = json.dumps({'message':'failed to parse input', 'errors': errors})
        LOGGER.info("failed to parse input - %s", results)
        return make_response(results, 400)

    loaded_template = DeviceTemplate(label=tpl['label'])
    for attr in tpl['attrs']:
        mapped = DeviceAttr(template=loaded_template, **attr)
        db.session.add(mapped)
    db.session.add(loaded_template)
    db.session.commit()
    results = json.dumps({
        'template': SerializationModels.template_schema.dump(loaded_template).data,
        'result': 'ok'
    })
    return make_response(results, 200)

@template.route('/template/<templateid>', methods=['GET'])
def get_template(templateid):
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    tpl = DeviceTemplate.query.filter_by(id=templateid).first()
    if tpl is None:
        return formatResponse(404, 'No such template')

    json_template = SerializationModels.template_schema.dump(tpl).data
    return make_response(json.dumps(json_template), 200)

@template.route('/template/<templateid>', methods=['DELETE'])
def remove_template(templateid):
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    tpl = DeviceTemplate.query.filter_by(id=templateid).first()
    if tpl is None:
        return formatResponse(404, 'No such template')

    json_template = SerializationModels.template_schema.dump(tpl).data
    db.session.delete(tpl)
    db.session.commit()

    results = json.dumps({'result': 'ok', 'removed':json_template})
    return make_response(json.dumps(json_template), 200)

@template.route('/template/<templateid>', methods=['PUT'])
def update_template(templateid):
    try:
        init_tenant_context(request, db)
    except Exception as e:
        return formatResponse(400, e.message)

    # find old version of the template, if any
    old = DeviceTemplate.query.filter_by(id=templateid).first()
    if old is None:
        return formatResponse(404, 'No such template')


    # parse updated version from payload
    json_payload = request.get_json()
    if json_payload is None:
        return formatResponse(400, "Payload must be valid JSON, and Content-Type set accordingly")
    tpl, errors = SerializationModels.template_schema.load(json_payload)
    if errors:
        results = json.dumps({'message':'failed to parse input', 'errors': errors})
        LOGGER.info("failed to parse input - %s", results)
        return make_response(results, 400)

    old.label = tpl['label']
    for attr in old.attrs:
        db.session.delete(attr)
    for attr in tpl['attrs']:
        mapped = DeviceAttr(template=old, **attr)
        db.session.add(mapped)

    db.session.commit()
    results = {
        'updated': SerializationModels.template_schema.dump(old).data,
        'result': 'ok'
    }
    return make_response(json.dumps(results), 200)

app.register_blueprint(template)
