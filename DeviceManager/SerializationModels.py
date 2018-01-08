# object to json sweetness
import json
from marshmallow import Schema, fields, post_dump
from utils import HTTPRequestError


class AttrSchema(Schema):
    id = fields.Int()
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    type = fields.Str(required=True)
    value_type = fields.Str(required=True)
    static_value = fields.Str()
    template_id = fields.Str()

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}


attr_schema = AttrSchema()
attr_list_schema = AttrSchema(many=True)


class TemplateSchema(Schema):
    id = fields.Int()
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    attrs = fields.Nested(AttrSchema, many=True, dump_only=True)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}


template_schema = TemplateSchema()
template_list_schema = TemplateSchema(many=True)


class DeviceSchema(Schema):
    id = fields.String(dump_only=True)
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    templates = fields.Nested(TemplateSchema, only=('id'), many=True)
    # protocol = fields.Str(required=True)
    # frequency = fields.Int()
    # topic = fields.Str(load_only=True)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}


device_schema = DeviceSchema()
device_list_schema = DeviceSchema(many=True)


def parse_payload(request, schema):
    try:
        content_type = request.headers.get('Content-Type')
        if (content_type is None) or (content_type != "application/json"):
            raise HTTPRequestError(400, "Payload must be valid JSON, and Content-Type set accordingly")
        json_payload = json.loads(request.data)
    except ValueError:
        raise HTTPRequestError(400, "Payload must be valid JSON, and Content-Type set accordingly")

    data, errors = schema.load(json_payload)
    if errors:
        results = {'message':'failed to parse input', 'errors': errors}
        raise HTTPRequestError(400, results)
    return data, json_payload


def load_attrs(attr_list, parent_template, base_type, db):
    for attr in attr_list:
        entity, errors = attr_schema.load(attr)
        if errors:
            results = {'message':'failed to parse attr', 'errors': errors}
            raise HTTPRequestError(400, results)

        orm_attr = base_type(template=parent_template, **entity)
        db.session.add(orm_attr)
