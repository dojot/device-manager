# object to json sweetness
from marshmallow import Schema, fields, ValidationError, post_dump

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
    attrs = fields.Nested(AttrSchema, many=True)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}

template_schema = TemplateSchema()
template_list_schema = TemplateSchema(many=True)

class DeviceSchema(Schema):
    device_id = fields.String(dump_only=True)
    label = fields.Str(required=True)
    created = fields.DateTime(dump_only=True)
    updated = fields.DateTime(dump_only=True)
    template = fields.Nested(TemplateSchema, only=('id'))
    protocol = fields.Str(required=True)
    frequency = fields.Int()
    topic = fields.Str(load_only=True)

    @post_dump
    def remove_null_values(self, data):
        return {key: value for key, value in data.items() if value is not None}

device_schema = DeviceSchema()
device_list_schema = DeviceSchema(many=True)
