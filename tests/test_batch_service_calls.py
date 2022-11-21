import pytest
import unittest
from unittest.mock import Mock, MagicMock, patch, call

from DeviceManager.DeviceHandler import create_devices_in_batch_service
from DeviceManager.DeviceHandler import ValidationException, BusinessException


from DeviceManager.Logger import Log
LOGGER = Log().color_log()

from DeviceManager.app import app

class TestServiceCallsHandler(unittest.TestCase):

    @staticmethod
    def create_mock_request(json_body):
        request = MagicMock()
        request.get_json.return_value = json_body
        return request

    @patch('DeviceManager.DeviceHandler.init_tenant_context')
    @patch('DeviceManager.DeviceHandler.retrieve_auth_token')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.create_devices_in_batch')
    @patch('DeviceManager.DeviceHandler.db')
    def test_method_calls_for_create_devices_in_batch_service(self, mock_database, mock_create_devices_in_batch, mock_retrieve_auth_token, mock_init_tenant_context):

        mock_retrieve_auth_token.return_value = "a-token"

        tenant = "a-tenant"
        prefix = "a-prefix"
        quantity = 42
        suffix = 123
        templates = [ 9 ]

        response_sample = { "it": "works" }

        mock_init_tenant_context.return_value = tenant
        mock_create_devices_in_batch.return_value = response_sample

        LOGGER.info("Checking if batch-creation controller call maps to the correct underlying method")
        with app.app_context():
            response = create_devices_in_batch_service(self.create_mock_request({
                'devicesPrefix': prefix,
                'quantity': quantity,
                'initialSuffixNumber': suffix,
                'templates': templates
            }))
            LOGGER.info(f"Got response {response}")
            mock_create_devices_in_batch.assert_called_once_with(prefix, quantity, suffix, templates, tenant, mock_database)

            self.assertNotEqual(response.status_code, "200")
            self.assertEqual(response.status_code, 200)


    @patch('DeviceManager.DeviceHandler.init_tenant_context')
    @patch('DeviceManager.DeviceHandler.retrieve_auth_token')
    @patch('DeviceManager.DeviceHandler.DeviceHandler.create_devices_in_batch')
    @patch('DeviceManager.DeviceHandler.db')
    def test_exceptions_for_create_devices_in_batch_service(self, mock_database, mock_create_devices_in_batch, mock_retrieve_auth_token, mock_init_tenant_context):

        tenant = "a-tenant"
        mock_init_tenant_context.return_value = tenant
        mock_retrieve_auth_token.return_value = "a-token"

        LOGGER.info("Checking if batch-creation controller call maps to the correct underlying method")
        with app.app_context():
            a_message = "any-message"

            mock_create_devices_in_batch.side_effect = ValidationException("any-validation-error-message");
            # with self.assertRaises(ValidationException) as context:
            response = create_devices_in_batch_service(self.create_mock_request({}))
            self.assertEqual(response.status_code, 400)

            mock_create_devices_in_batch.side_effect = BusinessException("any-business-error-message");
            # with self.assertRaises(ValidationException) as context:
            response = create_devices_in_batch_service(self.create_mock_request({}))
            self.assertEqual(response.status_code, 422)

            mock_create_devices_in_batch.side_effect = Exception("any-major-exception-message");
            # with self.assertRaises(ValidationException) as context:
            response = create_devices_in_batch_service(self.create_mock_request({}))
            self.assertEqual(response.status_code, 500)
