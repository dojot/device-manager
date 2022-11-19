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


from DeviceManager.Logger import Log
LOGGER = Log().color_log()

class TestDeviceHandler(unittest.TestCase):

    app = Flask(__name__)

    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_device_insertion_with_invalid_device_id(self, db_mock_session, query_property_getter_mock):
        
        device_data = {
            "id": "invalid",
            "label": "any-label",
            "templates": [ 1 ]
        }

        with self.assertRaises(Exception) as context:
            DeviceHandler.insert_new_device_into_database(device_data, None)

        self.assertEqual(str(context.exception), 'invalid-deviceId')


    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_device_insertion_with_no_device_id(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()

        device_data = {
            # no device-id
            "label": "any-label",
            "templates": [ 1 ]
        }

        with patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists') as mock_label_check:
            mock_label_check.return_value = False

            with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:

                mock_device_id.return_value = "abc123"

                DeviceHandler.insert_new_device_into_database(device_data, db_mock_session)
                mock_device_id.assert_called_once()


    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_device_insertion_with_duplicated_label(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()
        token = generate_token()

        device_data = {
            "id": "123abc",
            "label": "any-label",
            "templates": [ ]
        }

        with patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists') as mock_label_check:
            mock_label_check.return_value = True

            with self.assertRaises(Exception) as context:
                DeviceHandler.insert_new_device_into_database(device_data, db_mock_session)

            self.assertEqual(str(context.exception), 'label-already-in-use')


    @patch('DeviceManager.DeviceHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_device_insertion_with_no_template(self, db_mock_session, query_property_getter_mock):
        db_mock_session.session = AlchemyMagicMock()

        device_data = {
            "id": "123abc",
            "label": "any-label",
            "templates": [ ]
        }

        with patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists') as mock_label_check:
            mock_label_check.return_value = False

            with self.assertRaises(Exception) as context:
                DeviceHandler.insert_new_device_into_database(device_data, db_mock_session)

            self.assertEqual(str(context.exception), 'no-templates-assigned')
        



    #     with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:

    #         data = {
    #             "devicesPrefix": "batch-test",
    #             "quantity": 10,
    #             "initialSuffixNumber": 50,
    #             "templates": [ 1 ]
    #         }

        
    #     with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
    #         mock_device_id.return_value = 'test_device_id'

    #         with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
    #             mock_validate_device_id.return_value = True

    #             with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):

    #                 params = {'count': '1', 'verbose': 'false',
    #                         'content_type': 'application/json', 'data': data}
    #                 result = DeviceHandler.create_device(params, token)

    #                 self.assertIsNotNone(result)
    #                 self.assertTrue(result['devices'])
    #                 self.assertEqual(result['message'], 'devices created')
    #                 self.assertEqual(result['devices'][0]['id'], 'test_device_id')
    #                 self.assertEqual(result['devices'][0]['label'], 'test_device')

    #                 params = {'count': '1', 'verbose': 'true',
    #                         'content_type': 'application/json', 'data': data}
    #                 result = DeviceHandler.create_device(params, token)
    #                 self.assertIsNotNone(result)
    #                 self.assertTrue(result['devices'])
    #                 self.assertEqual(result['message'], 'device created')

    #                 # Here contains the validation when the count is not a number
    #                 params = {'count': 'is_not_a_number', 'verbose': 'false',
    #                         'content_type': 'application/json', 'data': data}

    #                 with self.assertRaises(HTTPRequestError):
    #                     result = DeviceHandler.create_device(params, token)

    #                 # Here contains the HttpRequestError validating de count with verbose
    #                 params = {'count': '2', 'verbose': 'true',
    #                         'content_type': 'application/json', 'data': data}

    #                 with self.assertRaises(HTTPRequestError):
    #                     result = DeviceHandler.create_device(params, token)



    # @patch('DeviceManager.DeviceHandler.db')
    # @patch('flask_sqlalchemy._QueryProperty.__get__')
    # def garbaggio(self, db_mock_session, query_property_getter_mock):
    #     db_mock_session.session = AlchemyMagicMock()
    #     token = generate_token()

    #     device_data = {
    #         "label": "any-label",
    #         "templates": [ ]
    #     }

    #     with patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists') as mock_label_check:
    #         mock_label_check.return_value = True

    #         with self.assertRaises(Exception) as exception:
    #             DeviceHandler.insert_new_device_into_database(device_data, None)

    #         self.assertEqual(str(exception), 'invalid-deviceId')
        
    #     with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:

    #         data = {
    #             "devicesPrefix": "batch-test",
    #             "quantity": 10,
    #             "initialSuffixNumber": 50,
    #             "templates": [ 1 ]
    #         }

        
    #     with patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id') as mock_device_id:
    #         mock_device_id.return_value = 'test_device_id'

    #         with patch('DeviceManager.DeviceHandler.DeviceHandler.validate_device_id') as mock_validate_device_id:
    #             mock_validate_device_id.return_value = True

    #             with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):

    #                 params = {'count': '1', 'verbose': 'false',
    #                         'content_type': 'application/json', 'data': data}
    #                 result = DeviceHandler.create_device(params, token)

    #                 self.assertIsNotNone(result)
    #                 self.assertTrue(result['devices'])
    #                 self.assertEqual(result['message'], 'devices created')
    #                 self.assertEqual(result['devices'][0]['id'], 'test_device_id')
    #                 self.assertEqual(result['devices'][0]['label'], 'test_device')

    #                 params = {'count': '1', 'verbose': 'true',
    #                         'content_type': 'application/json', 'data': data}
    #                 result = DeviceHandler.create_device(params, token)
    #                 self.assertIsNotNone(result)
    #                 self.assertTrue(result['devices'])
    #                 self.assertEqual(result['message'], 'device created')

    #                 # Here contains the validation when the count is not a number
    #                 params = {'count': 'is_not_a_number', 'verbose': 'false',
    #                         'content_type': 'application/json', 'data': data}

    #                 with self.assertRaises(HTTPRequestError):
    #                     result = DeviceHandler.create_device(params, token)

    #                 # Here contains the HttpRequestError validating de count with verbose
    #                 params = {'count': '2', 'verbose': 'true',
    #                         'content_type': 'application/json', 'data': data}

    #                 with self.assertRaises(HTTPRequestError):
    #                     result = DeviceHandler.create_device(params, token)
