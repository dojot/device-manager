from __future__ import absolute_import
import dredd_hooks as hooks
import json
import re

# This shouldn't be needed
from werkzeug.datastructures import MultiDict

from DeviceManager.DeviceHandler import DeviceHandler
from DeviceManager.TemplateHandler import TemplateHandler
from token_generator import generate_token


class Request:
    def __init__(self, data):
        self.headers = data['headers']
        self.args = data['args']
        self.data = data['body']


def sort_attributes(device, attribute):
    device[attribute] = sorted(device[attribute], key=lambda k: k['label'])

def create_sample_template():
    template = {
        "label": "SensorModel",
        "attrs": [
            {
                "label": "temperature",
                "type": "dynamic",
                "value_type": "float"
            },
            {
                "label": "position",
                "type": "dynamic",
                "value_type": "geopoint"
            },
            {
                "label": "model-id",
                "type": "static",
                "value_type": "string",
                "static_value": "model-001"
            },
            {
                "label": "shared_key",
                "type": "static",
                "value_type": "psk"
            }
        ]
    }
    req = {
        'headers': {
            'authorization': generate_token(),
            'Content-Type': 'application/json'
        },
        'args': {},
        'body': json.dumps(template)
    }

    params = {
        'content_type': 'application/json',
        'data': json.dumps(template)
    }

    result = TemplateHandler.create_template(params, generate_token())
    template_id = result['template']['id']
    return template_id

def create_actuator_template():
    template = {
        "label": "SensorModel",
        "attrs": [
            {
                "label": "temperature",
                "type": "dynamic",
                "value_type": "float"
            },
            {
                "label": "battery",
                "type": "actuator",
                "value_type": "float"
            },
            {
                "label": "position",
                "type": "dynamic",
                "value_type": "geopoint"
            },
            {
                "label": "model-id",
                "type": "static",
                "value_type": "string",
                "static_value": "model-001"
            },
            {
                "label": "shared_key",
                "type": "static",
                "value_type": "psk"
            }
        ]
    }
    req = {
        'headers': {
            'authorization': generate_token(),
            'Content-Type': 'application/json'
        },
        'args': {},
        'body': json.dumps(template)
    }

    params = {
        'content_type': 'application/json',
        'data': json.dumps(template)
    }

    result = TemplateHandler.create_template(params, generate_token())
    template_id = result['template']['id']
    return template_id

@hooks.before('Templates > Templates > Get the current list of templates')
@hooks.before('Devices > Device info > Get the current list of devices > Example 1')
@hooks.before('Devices > Device info > Get the current list of devices > Example 2')
def remove_filters(transaction):
    original = transaction['fullPath']
    if '?' in original:
        base = original[:original.index('?')]
        params = re.findall(r'(?<=[\?&])([\w-]+)=([\w-]+)', original)
        filtered = list(filter(lambda x: x[0] not in  ['attr', 'label'], params))
        transaction['fullPath'] = base + '?' + '&'.join(map(lambda x: "{}={}".format(x[0], x[1]), filtered))


@hooks.before('Templates > Templates > Get the current list of templates')
@hooks.before('Templates > Template info > Get template info')
@hooks.before('Templates > Template info > Update template info')
@hooks.before('Templates > Template info > Delete template')
def register_new_template(transaction):
    template_id = create_sample_template()
    if not 'proprietary' in transaction:
        transaction['proprietary'] = {}
    transaction['proprietary']['template_id'] = template_id


@hooks.before('Devices > Device info > Update device info')
@hooks.before('Devices > Devices > Register a new device')
def register_new_device(transaction):
    template_id = create_sample_template()
    if not 'proprietary' in transaction:
        transaction['proprietary'] = {}
    transaction['proprietary']['template_id'] = template_id
    device_json = json.loads(transaction['request']['body'])
    device_json['templates'] = [template_id]
    transaction['request']['body'] = json.dumps(device_json)


@hooks.before('Devices > Device info > Get the current list of devices > Example 2')
@hooks.before('Internal > Device > Get the current list of devices > Example 2')
def update_onlyids_query(transaction):
    transaction['request']['uri'] = transaction['request']['uri'].replace('idsOnly=false',
                                                                          'idsOnly=true')
    transaction['fullPath'] = transaction['fullPath'].replace('idsOnly=false', 'idsOnly=true')


@hooks.before('Devices > Device info > Get the current list of devices > Example 1')
@hooks.before('Devices > Device info > Get the current list of devices associated with given template')
def create_single_device(transaction):
    template_id = create_sample_template()
    if not 'proprietary' in transaction:
        transaction['proprietary'] = {}
    transaction['proprietary']['template_id'] = template_id
    device = {
        "label": "test_device",
        "templates": [template_id]
    }
    req = {
        'headers': {
            'authorization': generate_token(),
            'Content-Type': 'application/json'
        },
        'args': {
            'count': 1,
            'verbose': False
        },
        'body': json.dumps(device)
    }

    params = {
            'count': '1',
            'verbose': 'False',
            'content_type': 'application/json',
            'data': json.dumps(device)
        }

    result = DeviceHandler.create_device(params, generate_token())
    device_id = result['devices'][0]['id']
    transaction['proprietary']['device_id'] = device_id
    return device_id

@hooks.before('Devices > Device info > Configure device')
def create_actuator_device(transaction):
    template_id = create_actuator_template();
    if not 'proprietary' in transaction:
        transaction['proprietary'] = {}
    transaction['proprietary']['template_id'] = template_id
    device = {
        "label": "test_device",
        "templates": [template_id]
    }
    req = {
        'headers': {
            'authorization': generate_token(),
            'Content-Type': 'application/json'
        },
        'args': {
            'count': 1,
            'verbose': False
        },
        'body': json.dumps(device)
    }

    params = {
            'count': '1',
            'verbose': 'False',
            'content_type': 'application/json',
            'data': json.dumps(device)
        }


    result = DeviceHandler.create_device(params, generate_token())
    device_id = result['devices'][0]['id']
    transaction['proprietary']['device_id'] = device_id
    return device_id


@hooks.before('Internal > Device > Get the current list of devices > Example 1')
def create_single_device_and_gen_psk(transaction):
    device_id = create_single_device(transaction)
    DeviceHandler.gen_psk(generate_token(), device_id, 16, None)

@hooks.before('Devices > Device info > Get device info')
@hooks.before('Devices > Device info > Update device info')
@hooks.before('Devices > Device info > Delete device')
@hooks.before('Devices > PSK Manipulation > Generate PSK')
@hooks.before('Devices > Device info > Delete all devices')
def create_device_and_update_device_id(transaction):
    device_id = create_single_device(transaction)
    transaction['fullPath'] = transaction['fullPath'].replace('efac', device_id)
    return device_id

@hooks.before('Devices > Device info > Configure device')
def create_actuate_device_and_update_device_id(transaction):
    device_id = create_actuator_device(transaction)
    transaction['fullPath'] = transaction['fullPath'].replace('efac', device_id)
    return device_id

@hooks.before('Internal > Device > Get device info')
def prepare_env_psk(transaction):
    device_id = create_device_and_update_device_id(transaction)
    DeviceHandler.gen_psk(generate_token(), device_id, 16, None)

@hooks.before('Devices > PSK Manipulation > Copy PSK')
def prepare_copy_psk_env(transaction):
    device_id = create_single_device(transaction)
    transaction['fullPath'] = transaction['fullPath'].replace('efac', device_id)
    DeviceHandler.gen_psk(generate_token(), device_id, 16, None)
    device_id = create_single_device(transaction)
    transaction['fullPath'] = transaction['fullPath'].replace('acaf', device_id)

@hooks.before_validation('Devices > Device info > Get device info')
@hooks.before_validation('Internal > Device > Get device info')
def update_expected_ids_single_device(transaction):
    template_id = transaction['proprietary']['template_id']
    device_id = transaction['proprietary']['device_id']

    expected_body = json.loads(transaction['expected']['body'])
    str_template_id = "{}".format(template_id)
    expected_body["attrs"][str_template_id] = expected_body["attrs"].pop("4865")
    for attr in expected_body["attrs"][str_template_id]:
        attr['template_id'] = str_template_id
    expected_body["templates"] = [str_template_id]
    expected_body["id"] = device_id
    transaction['expected']['body'] = json.dumps(expected_body)


@hooks.before_validation('Devices > Device info > Update device info')
def update_expected_ids_single_device_update(transaction):
    template_id = transaction['proprietary']['template_id']
    device_id = transaction['proprietary']['device_id']

    expected_body = json.loads(transaction['expected']['body'])
    str_template_id = "{}".format(template_id)
    expected_body["device"]["attrs"][str_template_id] = expected_body["device"]["attrs"].pop("4865")
    for attr in expected_body["device"]["attrs"][str_template_id]:
        attr['template_id'] = str_template_id
    expected_body["device"]["templates"] = [str_template_id]
    expected_body["device"]["id"] = device_id
    transaction['expected']['body'] = json.dumps(expected_body)


@hooks.before('Devices > Device info > Delete device')
def update_expected_ids_single_device_delete(transaction):
    template_id = transaction['proprietary']['template_id']
    device_id = transaction['proprietary']['device_id']

    expected_body = json.loads(transaction['expected']['body'])
    str_template_id = "{}".format(template_id)
    expected_body["removed_device"]["attrs"][str_template_id] = expected_body["removed_device"]["attrs"].pop("4865")
    for attr in expected_body["removed_device"]["attrs"][str_template_id]:
        attr['template_id'] = str_template_id
    expected_body["removed_device"]["templates"] = [str_template_id]
    expected_body["removed_device"]["id"] = device_id
    transaction['expected']['body'] = json.dumps(expected_body)

@hooks.before('Devices > Device info > Delete all devices')
def update_expected_ids_single_device_actuator_delete(transaction):
    template_id = transaction['proprietary']['template_id']
    device_id = transaction['proprietary']['device_id']

    expected_body = json.loads(transaction['expected']['body'])
    str_template_id = "{}".format(template_id)
    expected_body["removed_devices"][0]["attrs"][str_template_id] = expected_body["removed_devices"][0]["attrs"].pop("4865")
    for attr in expected_body["removed_devices"][0]["attrs"][str_template_id]:
        attr['template_id'] = str_template_id
    expected_body["removed_devices"][0]["templates"] = [str_template_id]
    expected_body["removed_devices"][0]["id"] = device_id
    transaction['expected']['body'] = json.dumps(expected_body)

@hooks.before('Devices > Device info > Get the current list of devices associated with given template')
@hooks.before('Devices > Device info > Get the current list of devices > Example 1')
@hooks.before('Internal > Device > Get the current list of devices > Example 1')
def update_expected_ids_multiple_devices(transaction):
    template_id = transaction['proprietary']['template_id']
    device_id = transaction['proprietary']['device_id']

    expected_body = json.loads(transaction['expected']['body'])
    str_template_id = "{}".format(template_id)
    expected_body["devices"][0]["attrs"][str_template_id] = expected_body["devices"][0]["attrs"].pop("4865")
    for attr in expected_body["devices"][0]["attrs"][str_template_id]:
        attr['template_id'] = str_template_id
    expected_body["devices"][0]["templates"] = [str_template_id]
    expected_body["devices"][0]["id"] = device_id
    transaction['expected']['body'] = json.dumps(expected_body)


@hooks.before('Devices > Device info > Get the current list of devices associated with given template')
@hooks.before('Templates > Template info > Get template info')
@hooks.before('Templates > Template info > Update template info')
@hooks.before('Templates > Template info > Delete template')
def update_template_id(transaction):
    template_id = transaction['proprietary']['template_id']
    transaction['fullPath'] = transaction['fullPath'].replace('4865', '{}'.format(template_id))


@hooks.after_each
def clean_scenario(transaction):
    # This shouldn't be needed - controller class shouln't expose flask dependent params
    # TODO remove
    args = MultiDict([
        ('page_size', 10),
        ('page_num', 1),
        ('attr_format', 'both')
    ])
    req = {
        'headers': {
            'authorization': generate_token()
        },
        'args': args,
        'body': ''
    }

    params = {
        'page_size': 10,
        'page_num':  1,
        'attr_format': 'both',
        'attr': [],
        'attr_type': [],
        'idsOnly':'false'
    }

    token = generate_token()

    result = DeviceHandler.get_devices(token, params)

    for device in result['devices']:
        DeviceHandler.delete_device(device['id'], token)

    result = TemplateHandler.get_templates(params, token)
    for template in result['templates']:
        TemplateHandler.remove_template(template['id'], token)


@hooks.before_validation('Templates > Templates > Get the current list of templates')
def order_attributes(transaction):
    template = json.loads(transaction['expected']['body'])
    sort_attributes(template['templates'][0], 'data_attrs')
    sort_attributes(template['templates'][0], 'attrs')
    transaction['expected']['body'] = json.dumps(template)

    template = json.loads(transaction['real']['body'])
    sort_attributes(template['templates'][0], 'data_attrs')
    sort_attributes(template['templates'][0], 'attrs')
    transaction['real']['body'] = json.dumps(template)
