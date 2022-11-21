import pytest
import json
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from flask import Flask
from sqlalchemy.exc import IntegrityError

from DeviceManager.DeviceHandler import DeviceHandler, flask_delete_all_device, flask_get_device, flask_remove_device, flask_add_template_to_device, flask_remove_template_from_device, flask_gen_psk,flask_internal_get_device
from DeviceManager.utils import HTTPRequestError
from DeviceManager.DatabaseModels import Device, DeviceAttrsPsk, DeviceAttr
from DeviceManager.DatabaseModels import assert_device_exists
from DeviceManager.BackendHandler import KafkaInstanceHandler
import DeviceManager.DatabaseModels
from DeviceManager.SerializationModels import ValidationError
from DeviceManager.ImportHandler import ImportHandler
from .token_test_generator import generate_token

from alchemy_mock.mocking import AlchemyMagicMock, UnifiedAlchemyMagicMock


class TestDeviceHandler(unittest.TestCase):

    app = Flask(__name__)

    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_generate_deviceId(self, query_property_getter_mock):
        query_property_getter_mock.return_value.filter_by.return_value.first.return_value = None
        self.assertIsNotNone(DeviceHandler.generate_device_id())

        query_property_getter_mock.return_value.filter_by.return_value.first.return_value = 'existed_device_id'
        with pytest.raises(HTTPRequestError):
            DeviceHandler.generate_device_id()

    @patch('DeviceManager.DeviceHandler.db')
    def test_get_devices(self, db_mock):
        db_mock.session = UnifiedAlchemyMagicMock()

        db_mock.session.paginate().items = [Device(id=1, label='test_device1')]

        params_query = {'page_number': 5, 'per_page': 1, 'sortBy': None, 'attr': [
        ], 'idsOnly': 'false', 'attr_type': [], 'label': 'test_device1'}
        token = generate_token()

        result = DeviceHandler.get_devices(token, params_query)

        self.assertIsNotNone(result)
        self.assertTrue(json.dumps(result['devices']))

        params_query = {'page_number': 1, 'per_page': 1, 'sortBy': None,
                        'attr': [], 'idsOnly': 'false', 'attr_type': []}
        result = DeviceHandler.get_devices(token, params_query)
        self.assertTrue(json.dumps(result['devices']))
        self.assertIsNotNone(result)

        params_query = {'page_number': 1, 'per_page': 1, 'sortBy': None, 'attr': [
            'foo=bar'], 'idsOnly': 'false', 'attr_type': []}
        result = DeviceHandler.get_devices(token, params_query)
        self.assertTrue(json.dumps(result['devices']))
        self.assertIsNotNone(result)

        params_query = {'sortBy': None, 'attr': [],
                        'idsOnly': 'true', 'attr_type': []}

        with patch.object(DeviceHandler, "get_only_ids", return_value=['4f2b', '1e4a']) as DeviceOnlyIds:
            result = DeviceHandler.get_devices(token, params_query)
            self.assertTrue(json.dumps(result))
            DeviceOnlyIds.assert_called_once()

        params_query = {'page_number': 5, 'per_page': 1, 'sortBy': None, 'attr': [
        ], 'idsOnly': 'false', 'attr_type': [], 'label': 'test_device1'}
        result = DeviceHandler.get_devices(token, params_query, True)
        self.assertTrue(json.dumps(result['devices']))
        self.assertIsNotNone(result)

    @patch('DeviceManager.DeviceHandler.db')
    def test_list_devicesId(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        db_mock.session.query(Device.id).all.return_value = ['4f2b', '1e4a']

        result = DeviceHandler.list_ids(token)
        self.assertTrue(json.dumps(result))
        self.assertIsNotNone(result)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_get_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        query_property_getter_mock.filter_by.one.return_value = Device(
            id=1, label='teste')
        result = DeviceHandler.get_device(token, 'device_id')
        self.assertIsNotNone(result)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_delete_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()) as KafkaInstanceMock:
            result = DeviceHandler.delete_device('device_id', token)
            KafkaInstanceMock.assert_called_once()
            self.assertIsNotNone(result)
            self.assertEqual(result['result'], 'ok')

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_delete_all_devices(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        db_mock.session.query(Device).return_value = [
            Device(id=1, label='device_label')]
        result = DeviceHandler.delete_all_devices(token)

        self.assertIsNotNone(result)
        self.assertEqual(result['result'], 'ok')

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_add_template_to_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        query_property_getter_mock.filter_by.one.return_value = Device(
            id=1, label='device_label')
        result = DeviceHandler.add_template_to_device(
            token, 'device_id', 'template_id')
        self.assertIsNotNone(result)
        self.assertIsNotNone(result['device'])
        self.assertEqual(result['message'], 'device updated')

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_remove_template_to_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        query_property_getter_mock.filter_by.one.return_value = Device(
            id=1, label='device_label')
        result = DeviceHandler.remove_template_from_device(
            token, 'device_id', 'template_id')
        self.assertIsNotNone(result)
        self.assertIsNotNone(result['device'])
        self.assertEqual(result['message'], 'device updated')

    @patch('DeviceManager.DeviceHandler.db')
    def test_get_devices_by_templateId(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        params_query = {'page_number': 1, 'per_page': 1}

        db_mock.session.paginate().items = [Device(id=1, label='test_device1')]
        result = DeviceHandler.get_by_template(
            token, params_query, 'template_id')
        self.assertIsNotNone(result)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_generate_shared_key(self, db_mock_session, query_property_getter_mock):

        device = Device(id=1, label='test_device')
        token = generate_token()
        result = None

        with patch('DeviceManager.DeviceHandler.assert_device_exists') as mock_device_exist_wrapper:
            mock_device_exist_wrapper.return_value = None

            with self.assertRaises(HTTPRequestError):
                DeviceHandler.gen_psk(token, 'device_id', 1024)

            mock_device_exist_wrapper.return_value = device

            with patch('DeviceManager.DeviceHandler.serialize_full_device') as mock_serialize_device_wrapper:
                mock_serialize_device_wrapper.return_value = {'templates': [369], 'label': 'test_device', 'id': 1,
                                                              'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {369: [
                                                                  {'label': 'shared_key', 'template_id': '369', 'id': 1504, 'type': 'static', 'created': '2019-08-29T18:18:07.778178+00:00',
                                                                   'value_type': 'psk'}]}}

                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                    query_property_getter_mock.return_value.session.return_value.query.return_value.filter_by.first.return_value = None
                    result = DeviceHandler.gen_psk(token, 'device_id', 1024)
                    self.assertIsNotNone(result)

                    query_property_getter_mock.return_value.session.return_value.query.return_value.filter_by.first.return_value = MagicMock()
                    result = DeviceHandler.gen_psk(token, 'device_id', 1024)
                    self.assertIsNotNone(result)

                    result = DeviceHandler.gen_psk(
                        token, 'device_id', 1024, ['shared_key'])
                    self.assertIsNotNone(result)

                    with self.assertRaises(HTTPRequestError):
                        DeviceHandler.gen_psk(token, 'device_id', 1024, [
                                              'shared_key_not_contains'])

        with self.assertRaises(HTTPRequestError):
            DeviceHandler.gen_psk(token, 'device_id', 1025)

        with self.assertRaises(HTTPRequestError):
            DeviceHandler.gen_psk(token, 'device_id', 0)

        with self.assertRaises(HTTPRequestError):
            DeviceHandler.gen_psk(token, 'device_id', -1)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_copy_shared_key(self, db_mock_session, query_property_getter_mock):

        deviceSrc = Device(id=1, label='test_device')
        token = generate_token()
        result = None

        with patch('DeviceManager.DeviceHandler.assert_device_exists') as mock_device_exist_wrapper:
            mock_device_exist_wrapper.return_value = None

            with self.assertRaises(HTTPRequestError):
                DeviceHandler.copy_psk(
                    token, 'device_id_src', 'label', 'device_id_dest', 'label')

            mock_device_exist_wrapper.return_value = deviceSrc

            with patch('DeviceManager.DeviceHandler.serialize_full_device') as mock_serialize_device_wrapper:
                mock_serialize_device_wrapper.return_value = {'templates': [369], 'label': 'test_device', 'id': 1,
                                                              'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {369: [
                                                                  {'static_value': 'model-001', 'label': 'shared_key', 'value_type': 'psk',
                                                                   'type': 'static', 'template_id': '391', 'id': 1591,
                                                                   'created': '2019-08-29T18:24:43.490221+00:00', 'is_static_overridden': False}]}}

                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                    query_property_getter_mock.return_value.session.return_value.query.return_value.filter_by.first.return_value = None

                    with self.assertRaises(HTTPRequestError):
                        DeviceHandler.copy_psk(
                            token, 'device_id_src', 'label_not_exist_dest_src', 'device_id_dest', 'label_not_exist_dest')

                    result = DeviceHandler.copy_psk(
                        token, 'device_id_src', 'shared_key', 'device_id_dest', 'shared_key')
                    self.assertIsNone(result)

    def test_validate_device_id__should_pass_validation(self):      
        DeviceHandler.validate_device_id('8d73f1')
        
        self.assertTrue(True)

    def test_validate_device_id__should_raise_an_error__when_id_is_invalid(self):
        with pytest.raises(ValidationError) as validationError:
            DeviceHandler.validate_device_id('8dp3p1')
        
        self.assertEqual(validationError.value.messages[0], 'Device ID must be 2-6 characters and must be hexadecimal (0-9,a-f,A-F).')        

    def test_validate_device_id__should_raise_an_error__when_id_longer_than_6(self):
        with pytest.raises(ValidationError) as validationError:
            DeviceHandler.validate_device_id('8d33f222')
        
            self.assertEqual(validationError.value.messages[0], 'Device ID must be 2-6 characters and must be hexadecimal (0-9,a-f,A-F).') 

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_create_device(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()
        token = generate_token()

        data = '{"label":"test_device","templates":[1],"disabled": false}'

        with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
            mock_device_id.return_value = 'test_device_id'

            with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
                mock_validate_device_id.return_value = True

                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):

                    params = {'count': '1', 'verbose': 'false',
                            'content_type': 'application/json', 'data': data}
                    result = DeviceHandler.create_device(params, token)

                    self.assertIsNotNone(result)
                    self.assertTrue(result['devices'])
                    self.assertEqual(result['message'], 'devices created')
                    self.assertEqual(result['devices'][0]['id'], 'test_device_id')
                    self.assertEqual(result['devices'][0]['label'], 'test_device')

                    params = {'count': '1', 'verbose': 'true',
                            'content_type': 'application/json', 'data': data}
                    result = DeviceHandler.create_device(params, token)
                    self.assertIsNotNone(result)
                    self.assertTrue(result['devices'])
                    self.assertEqual(result['message'], 'device created')

                    # Here contains the validation when the count is not a number
                    params = {'count': 'is_not_a_number', 'verbose': 'false',
                            'content_type': 'application/json', 'data': data}

                    with self.assertRaises(HTTPRequestError):
                        result = DeviceHandler.create_device(params, token)

                    # Here contains the HttpRequestError validating de count with verbose
                    params = {'count': '2', 'verbose': 'true',
                            'content_type': 'application/json', 'data': data}

                    with self.assertRaises(HTTPRequestError):
                        result = DeviceHandler.create_device(params, token)
    
    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_create_disabled_device(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()
        token = generate_token()

        data = '{"label":"test_device","templates":[1],"disabled": true}'

        with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
            mock_device_id.return_value = 'test_device_id'

            with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
                mock_validate_device_id.return_value = True

                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):

                    params = {'count': '1', 'verbose': 'false',
                            'content_type': 'application/json', 'data': data}
                    result = DeviceHandler.create_device(params, token)

                    self.assertIsNotNone(result)
                    self.assertTrue(result['devices'])
                    self.assertEqual(result['message'], 'devices created')
                    self.assertEqual(result['devices'][0]['id'], 'test_device_id')
                    self.assertEqual(result['devices'][0]['label'], 'test_device')

    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_create_device_integrity_errors(self, query_get_mock):
        with patch('DeviceManager.DeviceHandler.init_tenant_context') as mock_init_tenant_context:
            mock_init_tenant_context.return_value = 'admin'
            with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
                mock_device_id.return_value = 'test_device_id'
                with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
                    mock_validate_device_id.return_value = True
                    with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                        with patch('DeviceManager.DeviceHandler.db') as db_mock:
                            diag = Exception()
                            diag.message_primary = 'test'
                            orig = Exception()
                            orig.diag = diag
                            
                            db_mock.session = AlchemyMagicMock()
                            db_mock.session.commit = Mock()
                            db_mock.session.commit.side_effect = IntegrityError(statement='test', params='test', orig=orig)

                            token = generate_token()
                            data = '{"label":"test_device","templates":[1],"disabled": false}'
                            params = {'count': '1', 'verbose': 'false',
                                'content_type': 'application/json', 'data': data}

                            with self.assertRaises(HTTPRequestError):
                                DeviceHandler.create_device(params, token)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_update_device(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()
        token = generate_token()

        data = '{"label": "test_updated_device", "templates": [4865], "disabled": false}'

        with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
            params = {'content_type': 'application/json', 'data': data}
            result = DeviceHandler.update_device(
                params, 'test_device_id', token)
            self.assertIsNotNone(result)
            self.assertEqual(result['message'], 'device updated')
            self.assertIsNotNone(result['device'])

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_configure_device(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()
        token = generate_token()

        device = Device(id=1, label='test_device')

        with patch('DeviceManager.DeviceHandler.assert_device_exists') as mock_device_exist_wrapper:
            mock_device_exist_wrapper.return_value = device

            with patch('DeviceManager.DeviceHandler.serialize_full_device') as mock_serialize_device_wrapper:
                mock_serialize_device_wrapper.return_value = {'templates': [369], 'label': 'test_device', 'id': 1,
                                                              'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {369: [
                                                                  {'label': 'temperature', 'template_id': '369', 'id': 1504, 'type': 'actuator', 'created': '2019-08-29T18:18:07.778178+00:00',
                                                                   'value_type': 'psk'}]}}
                                                                   
                data = '{"topic": "/admin/efac/config", "attrs": {"temperature": 10.6}}'
                params = {'data': data}

                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                    result = DeviceHandler.configure_device(params, 'test_device_id', token)
                    self.assertIsNotNone(result)
                    self.assertEqual(result[' status'], 'configuration sent to device')
                
                data = '{"topic": "/admin/efac/config", "attrs": {"test_attr": "xpto"}}'
                params = {'data': data}

                with self.assertRaises(HTTPRequestError):
                    DeviceHandler.configure_device(params, 'test_device_id', token)
    
    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_delete_all_devices(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()
                result = flask_delete_all_device()
                self.assertFalse(json.loads(result.response[0])['removed_devices'])
                self.assertEqual(json.loads(result.response[0])['result'], 'ok')
                
    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_get_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()
                with patch.object(DeviceHandler, "get_device") as mock_device:
                    mock_device.return_value = {'label': 'test_device', 'id':1, 'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {}}
                    result = flask_get_device('test_device_id')
                    self.assertIsNotNone(result.response)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_remove_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                    auth_mock.return_value = generate_token()
                    
                    with patch.object(DeviceHandler, "delete_device") as mock_remove_device:
                        mock_remove_device.return_value = {'result': 'ok', 'removed_device': {'id': 1, 'label': 'test_device', 'created': '2019-08-29T18:18:07.801602+00:00'}}
                        result = flask_remove_device('test_device_id')
                        self.assertIsNotNone(result.response)
                        self.assertEqual(json.loads(result.response[0])['result'], 'ok')

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_flask_add_template_to_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()

                with patch.object(DeviceHandler, "add_template_to_device") as mock_template_to_device:
                    mock_template_to_device.return_value = {'message': 'device updated', 'id':1, 'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {}}
                    result = flask_add_template_to_device('test_device_id', 'test_template_id')
                    self.assertIsNotNone(result.response)
                    self.assertEqual(json.loads(result.response[0])['message'], 'device updated')

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_flask_remove_template_from_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()
                with patch.object(DeviceHandler, "remove_template_from_device") as mock_template_to_device:
                    mock_template_to_device.return_value = {'message': 'device updated', 'id':140088130054016, 'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {}}
                    result = flask_remove_template_from_device('test_device_id', 'test_template_id')
                    self.assertIsNotNone(result.response)
                    self.assertEqual(json.loads(result.response[0])['message'], 'device updated')

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_generate_psk(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                result = flask_gen_psk('test_device_id')
                self.assertEqual(json.loads(result.response[0])['message'], 'Missing key_length parameter')
                self.assertEqual(json.loads(result.response[0])['status'], 400)
                
                with patch("DeviceManager.DeviceHandler.request") as req:
                    req.args = {
                        "key_length": "200"
                    }

                    auth_mock.return_value = generate_token()
                    result = flask_gen_psk('test_device_id')
                    self.assertEqual(json.loads(result.response[0])['message'], 'ok')
                    self.assertEqual(json.loads(result.response[0])['status'], 204)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_internal_get_device(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.DeviceHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()
                with patch.object(DeviceHandler, "get_device") as mock_getDevice:
                    mock_getDevice.return_value = {'id': 140110840862312, 'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': {}}
                    result = flask_internal_get_device('test_device_id')
                    self.assertIsNotNone(result.response)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_filter_device_label(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()
        
        data = '{"label":"device001","templates":[1],"disabled": false}'
        with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
            mock_device_id.return_value = 'device001_id'

            with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
                mock_validate_device_id.return_value = True
        
                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                
                     params = {'count': '1', 'verbose': 'false',
                                    'content_type': 'application/json', 'data': data}
                     result = DeviceHandler.create_device(params, token)

                     params_query = {'page_number': 6, 'per_page': 0, 
                                    'attr': [], 'attr_type': [],'sortBy': 'label', 
                                    'idsOnly': 'false', 'label': 'de'}
                     result = DeviceHandler.get_devices(token, params_query)

                     self.assertIsNotNone(result)
   
    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_filter_device_label_template(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()
        data = '{"label":"device002","templates":[1],"disabled": false}'

        with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
            mock_device_id.return_value = 'device002_id'

            with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
                mock_validate_device_id.return_value = True
     
                with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                    
                    params = {'count': '1', 'verbose': 'false',
                                        'content_type': 'application/json', 'data': data}
                    result = DeviceHandler.create_device(params, token)
                    
                    params_query = {'page_number': 6, 'per_page': 0, 
                                    'attr': [], 'attr_type': [],'sortBy': 'label',
                                    'idsOnly': 'false', 'label': 'de','template': '1'}
                    result = DeviceHandler.get_devices(token, params_query)

                    self.assertIsNotNone(result)