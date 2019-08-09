# object to json sweetness
import json
import re
from marshmallow import Schema, fields, post_dump, post_load, ValidationError

from DeviceManager.utils import HTTPRequestError
from DeviceManager.DatabaseModels import DeviceAttr
from DeviceManager.Logger import Log

LOGGER = Log().color_log()

def validate_attr_label(input):
    if re.match(r'^[a-zA-Z0-9_-]+$', input) is None:
        raise ValidationError("Labels must contain letters, numbers or dashes(-_)")

def validate_children_attr_label(attr_label):
    unique = { each['label'] : each for each in attr_label }.values()
    if len(attr_label) > len(unique):
        raise ValidationError('a template can not have repeated attributes')

def set_id_with_import_id(data):
    if 'import_id' in data and data['import_id'] is not None:
        data['id'] = data['import_id']
        del(data['import_id'])
    return data

def validate_repeated_attrs(data):
    if ('attrs' in data):
        try:
            uniques = { each['label'] : each for each in data['attrs'] }.values()
            if len(data['attrs']) > len(uniques):
                raise ValidationError('a device can not have repeated attributes')
        except KeyError:
            raise ValidationError('missing label attribute')

class MetaSchema(Schema):
    id = fields.Int(dump_only=True)
    import_id = fields.Int(load_only=True)
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    type = fields.Str(required=True)
    value_type = fields.Str(required=True)
    static_value = fields.Field()
    is_static_overridden = fields.Bool(allow_none=True)

    @post_load
    def set_import_id(self, data):
        return set_id_with_import_id(data)

metaattr_schema = MetaSchema()

class AttrSchema(Schema):
    id = fields.Int()
    import_id = fields.Int(load_only=True)
    label = fields.Str(required=True, validate=validate_attr_label, allow_none=False, missing=None)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    type = fields.Str(required=True)
    value_type = fields.Str(required=True)
    static_value = fields.Field(allow_none=True)
    is_static_overridden = fields.Bool(allow_none=True)
    template_id = fields.Str(dump_only=True)

    metadata = fields.Nested(MetaSchema, many=True, attribute='children', validate=validate_children_attr_label)

    @post_load
    def set_import_id(self, data):
        return set_id_with_import_id(data)

    @post_dump
    def remove_null_values(self, data):
        return {
            key: value for key, value in data.items() \
            if (value is not None) and ((isinstance(value, list) and len(value)) or not isinstance(value, list))
        }

attr_schema = AttrSchema()
attr_list_schema = AttrSchema(many=True)

class TemplateSchema(Schema):
    id = fields.Int(dump_only=True)
    import_id = fields.Int(load_only=True)
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    attrs = fields.Nested(AttrSchema, many=True, dump_only=True)
    data_attrs = fields.Nested(AttrSchema, many=True, dump_only=True)
    config_attrs = fields.Nested(AttrSchema, many=True, dump_only=True)

    @post_load
    def set_import_id(self, data):
        return set_id_with_import_id(data)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}

template_schema = TemplateSchema()
template_list_schema = TemplateSchema(many=True)

class DeviceSchema(Schema):
    id = fields.String(dump_only=True)
    import_id = fields.String(load_only=True)
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    templates = fields.Nested(TemplateSchema, only=('id'), many=True)

    @post_load
    def set_import_id(self, data):
        return set_id_with_import_id(data)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}

device_schema = DeviceSchema()
device_list_schema = DeviceSchema(many=True)

class ImportSchema(Schema):
    templates = fields.Nested(TemplateSchema, many=True)
    devices = fields.Nested(DeviceSchema, many=True)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}

import_schema = ImportSchema()
import_list_schema = ImportSchema(many=True)

class LogSchema(Schema):
    level = fields.Str(required=True)

log_schema = LogSchema()

def parse_payload(request, schema):
    try:
        content_type = request.headers.get('Content-Type')
        if (content_type is None) or (content_type != "application/json"):
            raise HTTPRequestError(400, "Payload must be valid JSON, and Content-Type set accordingly")
        json_payload = json.loads(request.data)
        data = schema.load(json_payload)
    except ValueError:
        raise HTTPRequestError(400, "Payload must be valid JSON, and Content-Type set accordingly")
    except ValidationError as errors:
        results = {'message': 'failed to parse input', 'errors': errors.messages}
        raise HTTPRequestError(400, results)
    return data, json_payload

def load_attrs(attr_list, parent_template, base_type, db):
    """

    :rtype:
    """
    for attr in attr_list:
        try:
            entity = attr_schema.load(attr)
            try:
                children = entity.pop('children')
            except KeyError:
                children = []

            orm_entity = base_type(template=parent_template, **entity)
            db.session.add(orm_entity)

            for child in children:
                orm_child = DeviceAttr(parent=orm_entity, **child)
                db.session.add(orm_child)
        except ValidationError as errors:
            results = {'message': 'failed to parse attr', 'errors': errors.messages}
            raise HTTPRequestError(400, results)
