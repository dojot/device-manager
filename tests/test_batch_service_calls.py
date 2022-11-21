import pytest
import json
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from flask import Flask
from sqlalchemy.exc import IntegrityError

from DeviceManager.DeviceHandler import DeviceHandler, flask_delete_all_device, flask_get_device, flask_remove_device, flask_add_template_to_device, flask_remove_template_from_device, flask_gen_psk,flask_internal_get_device, create_devices_in_batch_service
from DeviceManager.utils import HTTPRequestError
from DeviceManager.DatabaseModels import Device, DeviceAttrsPsk, DeviceAttr
from DeviceManager.DatabaseModels import assert_device_exists
from DeviceManager.BackendHandler import KafkaInstanceHandler
import DeviceManager.DatabaseModels
from DeviceManager.SerializationModels import ValidationError
from DeviceManager.ImportHandler import ImportHandler
from .token_test_generator import generate_token

from .test_utils import Request

from alchemy_mock.mocking import AlchemyMagicMock, UnifiedAlchemyMagicMock

from DeviceManager.Logger import Log
LOGGER = Log().color_log()

app = Flask(__name__)

class TestServiceCallsHandler(unittest.TestCase):


    @patch('DeviceManager.DeviceHandler.init_tenant_context')
    @patch('DeviceManager.DeviceHandler.retrieve_auth_token')
    @patch('DeviceManager.DeviceHandler.create_devices_in_batch_service')
    def test_method_calls_for_create_devices_in_batch(self, mock_create_devices_in_batch, mock_retrieve_auth_token, mock_init_tenant_context):

        mock_retrieve_auth_token.return_value = "a-token"

        tenant = "a-tenant"
        prefix = "a-prefix"
        quantity = 42
        suffix = 123
        templates = [ 9 ]

        response_sample = { 'it': "works" }

        mock_init_tenant_context.return_value = tenant
        mock_create_devices_in_batch.return_value = response_sample

        json_body = {
            'devicesPrefix': prefix,
            'quantity': quantity,
            'initialSuffixNumber': suffix,
            'templates': templates
        }

        request = MagicMock()
        request.get_json.return_value = json_body

        LOGGER.info("Checking if batch-creation controller call maps to the correct underlying method")
        response = mock_create_devices_in_batch(request)
        
        


        # DeviceHandler.create_devices_in_batch("a-preffix", 1, 10, templates, "tenant-id", mock_database)
