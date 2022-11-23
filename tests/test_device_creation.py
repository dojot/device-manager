import pytest
import unittest
from unittest.mock import Mock, MagicMock, patch, call

from DeviceManager.DeviceHandler import DeviceHandler
from DeviceManager.DeviceHandler import ValidationException, BusinessException

from DeviceManager.SerializationModels import DeviceSchema
from DeviceManager.DatabaseModels import Device as DatabaseDevice

from alchemy_mock.mocking import AlchemyMagicMock, UnifiedAlchemyMagicMock

from DeviceManager.Logger import Log
LOGGER = Log().color_log()

class TestDeviceCreationHandler(unittest.TestCase):

    @patch('DeviceManager.DeviceHandler.db')
    def test_device_insertion_with_invalid_device_id(self, mock_database):

        device_data = {
            "id": "invalid",
            "label": "any-label",
            "templates": [ 1 ]
        }

        with self.assertRaises(BusinessException) as context:
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

        with self.assertRaises(BusinessException) as context:
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

        with self.assertRaises(BusinessException) as context:
            DeviceHandler.insert_new_device_into_database(device_data, mock_database)

        self.assertEqual(str(context.exception), 'no-templates-assigned')


    @patch('DeviceManager.DeviceHandler.DeviceHandler.publish_device_creation')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.insert_new_device_into_database')
    @patch('DeviceManager.DeviceHandler.db')
    def test_signature_safeguards_for_create_devices_in_batch(self, mock_database, mock_insert_new_device_into_database, mock_publish_device_creation):
        mock_database.session = AlchemyMagicMock()

        LOGGER.info("Checking if invalid batch-prefix is correctly handled")

        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch(None, 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-prefix')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch(1, 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-prefix')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("", 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-prefix')


        LOGGER.info("Checking if invalid batch-quantity is correctly handled")
        
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", None, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-quantity')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 0, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-quantity')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", -1, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-quantity')


        LOGGER.info("Checking if invalid batch-suffix is correctly handled")
        
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, None, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-suffix')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, "50", [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-suffix')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, -1, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-suffix')


        LOGGER.info("Checking if invalid template is correctly handled")
        
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, 10, None, "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-templates')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, 10, [], "tenant-id", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-templates')


        LOGGER.info("Checking if invalid tenant is correctly handled")
        
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, 10, [ 1 ], None, mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-tenant')
        with self.assertRaises(ValidationException) as context:
            DeviceHandler.create_devices_in_batch("a-prefix", 1, 10, [ 1 ], "", mock_database)
        self.assertEqual(str(context.exception), 'invalid-batch-tenant')

        LOGGER.info("Checking if no sub-methods have been called in any of the invalid runs")
        mock_insert_new_device_into_database.assert_not_called()
        mock_publish_device_creation.assert_not_called()


    def test_template_attribute_duplication_when_loading(self):

        mock_return_first_value = MagicMock()
        mock_return_first_value.count = lambda : 1
        mock_return_first_value.one = lambda : {
                                        "attrs": [
                                            { "label":"one" }
                                        ]
                                    }

        mock_return_second_value = MagicMock()
        mock_return_second_value.count = lambda : 1
        mock_return_second_value.one = lambda : {
                                        "attrs": [
                                            { "label": "two"}
                                        ]
                                    }

        mock_return_third_value = MagicMock()
        mock_return_third_value.count = lambda : 0
        mock_return_third_value.one = lambda : {}

        def mock_get_template_by_id(template_id, database):
            if(template_id == 1):
                return mock_return_first_value
            elif(template_id == 2):
                return mock_return_second_value
            else:
                return mock_return_third_value


        LOGGER.info("Checking if an empty template_ids list raises an exception")
        with self.assertRaises(BusinessException) as context:
            DeviceHandler.load_template_models_from_database([ ], mock_get_template_by_id)
        self.assertEqual(str(context.exception), 'no-templates-assigned')

        LOGGER.info("Checking if two unique-set attrs will NOT raise an exception")
        DeviceHandler.load_template_models_from_database([ 1, 2 ], mock_get_template_by_id)

        LOGGER.info("Checking if duplicated template_ids raises an exception")
        with self.assertRaises(BusinessException) as context:
            DeviceHandler.load_template_models_from_database([ 1, 1 ], mock_get_template_by_id)
        self.assertEqual(str(context.exception), 'duplicated-attribute-across-templates')

        LOGGER.info("Checking if a template_id with no matches will raise the corresponding exception")
        with self.assertRaises(BusinessException) as context:
            DeviceHandler.load_template_models_from_database([ 3 ], mock_get_template_by_id)
        self.assertEqual(str(context.exception), 'template-id-does-not-exist')


    @patch('DeviceManager.DeviceHandler.DeviceHandler.publish_device_creation')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.insert_new_device_into_database')
    @patch('DeviceManager.DeviceHandler.db')
    def test_method_calls_for_create_devices_in_batch(self, mock_database, mock_insert_new_device_into_database, mock_publish_device_creation):
        mock_database.session = AlchemyMagicMock()

        LOGGER.info("Checking if a valid batch-creation calls the expected funcions")
        label = "a-prefix-10"
        templates = [ 1 ]
        DeviceHandler.create_devices_in_batch("a-prefix", 1, 10, templates, "tenant-id", mock_database)

        LOGGER.info("Checking if the creation call has been made and the proper arguments were passed")
        mock_insert_new_device_into_database.assert_called_once()
        mock_insert_new_device_into_database.assert_called_with({ 'label': label, 'templates': templates }, mock_database)

        mock_database.session.commit.assert_called_once()

        LOGGER.info("Checking if the event publish call has been made")
        mock_publish_device_creation.assert_called_once()


    @staticmethod
    def mocked_insertion(device_data, database):
        device_label = device_data['label']
        LOGGER.info(f"Starting a mocked insertion for device labelled {device_label}")
        if(device_label.endswith('11') or device_label.endswith('13')):
            raise BusinessException('a-business-error')
        else:
            response = Mock(DatabaseDevice)
            LOGGER.info(f"Returning {response}")
            return response

    @patch('DeviceManager.DeviceHandler.DeviceHandler.insert_new_device_into_database', new=mocked_insertion)
    @patch('DeviceManager.DeviceHandler.serialize_full_device')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.publish_device_creation')
    @patch('DeviceManager.DeviceHandler.db')
    def test_return_for_create_devices_in_batch(self, mock_database, mock_publish_device_creation, mock_serialize_full_device):
        mock_database.session = AlchemyMagicMock()

        mock_publish_device_creation.return_value = ""
        mock_serialize_full_device.return_value = { 'id': '123abc', 'label': 'a-prefix-11' }

        LOGGER.info("Checking response for a single failure")
        response = DeviceHandler.create_devices_in_batch("a-prefix", 1, 10, [ 1 ], "tenant-id", mock_database)
        self.assertFalse(response['devicesWithError'])
        self.assertEqual(len(response['successes']), 1)
        self.assertEqual(len(response['failures']), 0)


        LOGGER.info("Checking response for a single success")
        response = DeviceHandler.create_devices_in_batch("a-prefix", 1, 11, [ 1 ], "tenant-id", mock_database)
        self.assertTrue(response['devicesWithError'])
        self.assertEqual(len(response['successes']), 0)
        self.assertEqual(len(response['failures']), 1)


        LOGGER.info("Checking response for mixed success and failure")
        response = DeviceHandler.create_devices_in_batch("a-prefix", 5, 10, [ 1 ], "tenant-id", mock_database)
        self.assertTrue(response['devicesWithError'])
        self.assertEqual(len(response['successes']), 3)
        self.assertEqual(len(response['failures']), 2)
