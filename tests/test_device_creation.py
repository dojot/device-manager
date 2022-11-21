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

class TestDeviceCreationHandler(unittest.TestCase):

    app = Flask(__name__)

    @patch('DeviceManager.DeviceHandler.db')
    def test_device_insertion_with_invalid_device_id(self, mock_database):

        device_data = {
            "id": "invalid",
            "label": "any-label",
            "templates": [ 1 ]
        }

        with self.assertRaises(Exception) as context:
            DeviceHandler.insert_new_device_into_database(device_data, None)

        self.assertEqual(str(context.exception), 'invalid-deviceId')


    @patch('DeviceManager.DeviceHandler.DeviceHandler.generate_device_id')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists')
    @patch('DeviceManager.DeviceHandler.db')
    def test_device_insertion_with_no_device_id(self, mock_database, mock_label_check, mock_generate_device_id):
        mock_database.session = AlchemyMagicMock()
        mock_label_check.return_value = False
        mock_generate_device_id.return_value = "abc123"

        device_data = {
            # no device-id
            "label": "any-label",
            "templates": [ 1 ]
        }

        DeviceHandler.insert_new_device_into_database(device_data, mock_database)
        mock_generate_device_id.assert_called_once()


    @patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists')
    @patch('DeviceManager.DeviceHandler.db')
    def test_device_insertion_with_duplicated_label(self, mock_database, mock_label_check):
        mock_database.session = AlchemyMagicMock()
        mock_label_check.return_value = True

        device_data = {
            "id": "123abc",
            "label": "any-label",
            "templates": [ ]
        }

        with self.assertRaises(Exception) as context:
            DeviceHandler.insert_new_device_into_database(device_data, mock_database)

        self.assertEqual(str(context.exception), 'label-already-in-use')


    @patch('DeviceManager.DeviceHandler.DeviceHandler.label_already_exists')
    @patch('DeviceManager.DeviceHandler.db')
    def test_device_insertion_with_no_template(self, mock_database, mock_label_check):
        mock_database.session = AlchemyMagicMock()
        mock_label_check.return_value = False

        device_data = {
            "id": "123abc",
            "label": "any-label",
            "templates": [ ]
        }

        with self.assertRaises(Exception) as context:
            DeviceHandler.insert_new_device_into_database(device_data, mock_database)

        self.assertEqual(str(context.exception), 'no-templates-assigned')


    @patch('DeviceManager.DeviceHandler.DeviceHandler.publish_device_creation')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.insert_new_device_into_database')
    @patch('DeviceManager.DeviceHandler.db')
    def test_signature_safeguards_for_create_devices_in_batch(self, mock_database, mock_insert_new_device_into_database, mock_publish_device_creation):
        mock_database.session = AlchemyMagicMock()

        LOGGER.info("Checking if invalid batch-preffix is correctly handled")

        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch(None, 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-preffix')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch(1, 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-preffix')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("", 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-preffix')


        LOGGER.info("Checking if invalid batch-quantity is correctly handled")
        
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", None, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-quantity')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-quantity')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", -1, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-quantity')


        LOGGER.info("Checking if invalid batch-suffix is correctly handled")
        
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, None, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-suffix')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, "50", [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-suffix')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, -1, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-suffix')


        LOGGER.info("Checking if invalid template is correctly handled")
        
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, 10, None, "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-templates')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-templates')


        LOGGER.info("Checking if invalid tenant is correctly handled")
        
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, 10, [ 1 ], None, mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-tenant')
        with self.assertRaises(Exception) as context:
            DeviceHandler.create_devices_in_batch("a-preffix", 1, 10, [ 1 ], "", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-tenant')

        LOGGER.info("Checking if no sub-methods have been called in any of the invalid runs")
        mock_insert_new_device_into_database.assert_not_called()
        mock_publish_device_creation.assert_not_called()


    @patch('DeviceManager.DeviceHandler.DeviceHandler.publish_device_creation')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.insert_new_device_into_database')
    @patch('DeviceManager.DeviceHandler.db')
    def test_method_calls_for_create_devices_in_batch(self, mock_database, mock_insert_new_device_into_database, mock_publish_device_creation):
        mock_database.session = AlchemyMagicMock()

        LOGGER.info("Checking if a valid batch-creation calls the expected funcions")
        label = "a-preffix-10"
        templates = [ 1 ]
        DeviceHandler.create_devices_in_batch("a-preffix", 1, 10, templates, "tenant-id", mock_database)

        LOGGER.info("Checking if the creation call has been made and the proper arguments were passed")
        mock_insert_new_device_into_database.assert_called_once()
        mock_insert_new_device_into_database.assert_called_with({ 'label': label, 'templates': templates }, mock_database)

        mock_database.session.commit.assert_called_once()

        LOGGER.info("Checking if the event publish call has been made")
        mock_publish_device_creation
        mock_publish_device_creation.assert_called_once()
