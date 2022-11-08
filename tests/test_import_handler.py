import pytest
import json
import unittest
from unittest.mock import Mock, MagicMock, patch, call

from alchemy_mock.mocking import AlchemyMagicMock

from DeviceManager.ImportHandler import ImportHandler
from DeviceManager.DatabaseModels import Device, DeviceTemplate
from DeviceManager.utils import HTTPRequestError
from DeviceManager.BackendHandler import KafkaInstanceHandler, KafkaHandler

from .token_test_generator import generate_token


class TestImportHandler(unittest.TestCase):

    @patch('DeviceManager.ImportHandler.db')
    def test_drop_sequence(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.drop_sequences())

    def test_replaceIds_to_imoprtIds(self):
        json_import = '{"id": "test_value"}'

        result = ImportHandler.replace_ids_by_import_ids(json_import)
        self.assertIsNotNone(result)
        self.assertIn('import_id', result)

    @patch('DeviceManager.ImportHandler.db')
    def test_restore_template_sequence(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.restore_template_sequence())

    @patch('DeviceManager.ImportHandler.db')
    def test_restore_attr_sequence(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.restore_attr_sequence())

    @patch('DeviceManager.ImportHandler.db')
    def test_restore_sequences(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.restore_sequences())

    @patch("DeviceManager.BackendHandler.KafkaNotifier")
    @patch("DeviceManager.KafkaNotifier.KafkaProducer.flush")
    def test_notifies_deletion_to_kafka(self, kafka_instance_mock, kafka_flush):
        with patch('DeviceManager.ImportHandler.serialize_full_device') as mock_serialize_device_wrapper:
            mock_serialize_device_wrapper.return_value = {'templates': [369], 'label': 'test_device', 'id': 1,
                                                          'created': '2019-08-29T18:18:07.801602+00:00'}

            with patch.object(KafkaInstanceHandler, "getInstance", return_value=KafkaHandler()):
                ImportHandler().notifies_deletion_to_kafka('test_device', 'admin')
                self.assertTrue(kafka_flush.called)

    @patch('DeviceManager.ImportHandler.db')
    def test_delete_records(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.delete_records('admin'))

    @patch('DeviceManager.ImportHandler.db')
    def test_clear_db_config(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.clear_db_config('admin'))

    @patch('DeviceManager.ImportHandler.db')
    def test_restore_db_config(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        self.assertIsNone(ImportHandler.restore_db_config())

    @patch('DeviceManager.ImportHandler.db')
    def test_save_templates(self, db_mock):
        db_mock.session = AlchemyMagicMock()

        json_payload = {'templates': [{'import_id': 1, 'attrs': [
            {'label': 'temperature', 'type': 'dynamic', 'value_type': 'float'}]}], 'label': 'test_device', 'id': 1,
            'created': '2019-08-29T18:18:07.801602+00:00'}

        json_data = {"label": "test_device", "id": 1,
                     "templates": [{'id': 1, 'label': 'test_template'}]}

        result = ImportHandler.save_templates(json_data, json_payload)
        self.assertIsNotNone(result)
        self.assertTrue(result)

        json_data = {"label": "test_device", "id": 1,
                     "templates": [{'id': 2, 'label': 'test_template'}]}
        result = ImportHandler.save_templates(json_data, json_payload)
        self.assertIsNotNone(result)
        self.assertFalse(result[0].attrs)

    @patch('DeviceManager.ImportHandler.db')
    def test_set_templates_on_device(self, db_mock):
        db_mock.session = AlchemyMagicMock()

        json_payload = {'templates': [{'import_id': 1, 'attrs': [
            {'label': 'temperature', 'type': 'dynamic', 'value_type': 'float'}]}], 'label': 'test_device', 'id': 1,
            'created': '2019-08-29T18:18:07.801602+00:00'}

        saved_templates = [DeviceTemplate(label='test_template', attrs=[])]

        self.assertIsNone(ImportHandler.set_templates_on_device(
            Mock(), json_payload, saved_templates))

    @patch('DeviceManager.ImportHandler.db')
    def test_save_devices(self, db_mock):
        db_mock.session = AlchemyMagicMock()

        json_payload = {"devices": [{"id": "68fc", "label": "test_device_0"}, {
            "id": "94dc", "label": "test_device_1"}]}
        json_data = {"devices": [{"id": "68fc", "label": "test_device_0"}, {
            "id": "94dc", "label": "test_device_1"}]}

        saved_templates = [DeviceTemplate(label='test_template', attrs=[])]

        result = ImportHandler.save_devices(
            json_data, json_payload, saved_templates)
        self.assertIsNotNone(result)
        self.assertTrue(result)

    @patch("DeviceManager.BackendHandler.KafkaNotifier")
    @patch("DeviceManager.KafkaNotifier.KafkaProducer.flush")
    def test_notifies_creation_to_kafka(self, kafka_instance_mock, kafka_flush):
        with patch('DeviceManager.ImportHandler.serialize_full_device') as mock_serialize_device_wrapper:
            mock_serialize_device_wrapper.return_value = {'templates': [369], 'label': 'test_device', 'id': 1,
                                                          'created': '2019-08-29T18:18:07.801602+00:00'}

            with patch.object(KafkaInstanceHandler, "getInstance", return_value=KafkaHandler()):
                ImportHandler().notifies_creation_to_kafka(
                    [Device(id=1, label='test_device')], 'admin')
            self.assertTrue(kafka_flush.called)

    @patch('DeviceManager.ImportHandler.db')
    def test_import_data(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        data = """{"templates": [{"id": 1, "label": "template1", "attrs": [{"label": "temperature", "type": "dynamic", "value_type": "float"}]}], 
        "devices": [{"id": "68fc", "label": "test_device_0", "disabled": false, "templates": []},{"id": "94dc","label": "test_device_1", "disabled": false, "templates": []}]}"""

        with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
            result = ImportHandler.import_data(data, token, 'application/json')
            self.assertIsNotNone(result)
            self.assertEqual(result['message'], 'data imported!')

        data = """{"templates": {"id": 1, "label": "template1", "attrs": [{"label": "temperature", "type": "dynamic", "value_type": "float"}]}, 
        "devices": [{"id": "68fc", "label": "test_device_0", "disabled": false, "templates": []},{"id": "94dc","label": "test_device_1", "disabled": false, "templates": []}]}"""

        with self.assertRaises(HTTPRequestError):
            ImportHandler.import_data(data, token, 'application/json')
            