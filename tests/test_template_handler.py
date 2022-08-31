import pytest
import json
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from flask import Flask

from DeviceManager.DatabaseModels import DeviceTemplate
from DeviceManager.TemplateHandler import TemplateHandler, flask_get_templates, flask_delete_all_templates, \
     flask_get_template, flask_remove_template, paginate, attr_format, refresh_template_update_column
from DeviceManager.utils import HTTPRequestError
from DeviceManager.BackendHandler import KafkaInstanceHandler
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from .token_test_generator import generate_token

from alchemy_mock.mocking import AlchemyMagicMock, UnifiedAlchemyMagicMock


class TestTemplateHandler(unittest.TestCase):

    app = Flask(__name__)

    @patch('DeviceManager.TemplateHandler.db')
    def test_get_templates(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        params_query = {'page_number': 5, 'per_page': 1,
                        'sortBy': None, 'attr': [], 'attr_type': [], 'label': 'dummy'}
        result = TemplateHandler.get_templates(params_query, token)
        self.assertIsNotNone(result)

        # test using attrs
        params_query = {'page_number': 1, 'per_page': 1,
                        'sortBy': None, 'attr': ['foo=bar'], 'attr_type': []}
        result = TemplateHandler.get_templates(params_query, token)
        self.assertIsNotNone(result)

        # test using sortBy
        params_query = {'page_number': 1, 'per_page': 1,
                        'sortBy': 'label', 'attr': ['foo=bar'], 'attr_type': []}
        result = TemplateHandler.get_templates(params_query, token)
        self.assertIsNotNone(result)

        # test without querys
        params_query = {'page_number': 5, 'per_page': 1,
                        'sortBy': None, 'attr': [], 'attr_type': []}
        result = TemplateHandler.get_templates(params_query, token)
        self.assertIsNotNone(result)

    @patch('DeviceManager.TemplateHandler.db')
    def test_create_tempĺate(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        data = """{
            "label": "SensorModel",
            "attrs": [
                {
                    "label": "temperature",
                    "type": "dynamic",
                    "value_type": "float"
                },
                {
                    "label": "model-id",
                    "type": "static",
                    "value_type": "string",
                    "static_value": "model-001"
                }
            ]
        }"""

        params_query = {'content_type': 'application/json', 'data': data}
        result = TemplateHandler.create_template(params_query, token)
        self.assertIsNotNone(result)
        self.assertEqual(result['result'], 'ok')
        self.assertIsNotNone(result['template'])

    def test_create_template_integrity_errors(self):
        with patch('DeviceManager.TemplateHandler.init_tenant_context') as mock_init_tenant_context:
            mock_init_tenant_context.return_value = 'admin'
            with patch('DeviceManager.TemplateHandler.db') as db_mock:
                diag = Exception()
                diag.message_primary = 'test'
                orig = Exception()
                orig.diag = diag
                
                db_mock.session = AlchemyMagicMock()
                db_mock.session.commit = Mock()
                db_mock.session.commit.side_effect = IntegrityError(statement='test', params='test', orig=orig)

                token = generate_token()
                
                data = """{
                    "label": "SensorModel",
                    "attrs": [
                        {
                            "label": "temperature",
                            "type": "dynamic",
                            "value_type": "float"
                        },
                        {
                            "label": "model-id",
                            "type": "static",
                            "value_type": "string",
                            "static_value": "model-001"
                        }
                    ]
                }"""

                params_query = {'content_type': 'application/json', 'data': data}

                with self.assertRaises(HTTPRequestError):
                    TemplateHandler.create_template(params_query, token)

    @patch('DeviceManager.TemplateHandler.db')
    def test_get_template(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        template = DeviceTemplate(id=1, label='template1')
        params_query = {'attr_format': 'both'}

        with patch('DeviceManager.TemplateHandler.assert_template_exists') as mock_template_exist_wrapper:
            mock_template_exist_wrapper.return_value = template
            result = TemplateHandler.get_template(
                params_query, 'template_id_test', token)
            self.assertIsNotNone(result)

            mock_template_exist_wrapper.return_value = None
            result = TemplateHandler.get_template(
                params_query, 'template_id_test', token)
            self.assertFalse(result)

    @patch('DeviceManager.TemplateHandler.db')
    def test_delete_all_templates(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        result = TemplateHandler.delete_all_templates(token)
        self.assertIsNotNone(result)
        self.assertTrue(result)
        self.assertEqual(result['result'], 'ok')

    @patch('DeviceManager.TemplateHandler.db')
    def test_remove_template(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        template = DeviceTemplate(id=1, label='template1')

        with patch('DeviceManager.TemplateHandler.assert_template_exists') as mock_template_exist_wrapper:
            mock_template_exist_wrapper.return_value = template

            result = TemplateHandler.remove_template(1, token)
            self.assertIsNotNone(result)
            self.assertTrue(result)
            self.assertTrue(result['removed'])
            self.assertEqual(result['result'], 'ok')

    @patch('DeviceManager.TemplateHandler.db')
    def test_update_template(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        token = generate_token()

        template = DeviceTemplate(id=1, label='SensorModel')

        data = """{
            "label": "SensorModelUpdated",
            "attrs": [
                {
                    "label": "temperature",
                    "type": "dynamic",
                    "value_type": "float"
                },
                {
                    "label": "model-id",
                    "type": "static",
                    "value_type": "string",
                    "static_value": "model-001"
                }
            ]
        }"""

        params_query = {'content_type': 'application/json', 'data': data}

        with patch('DeviceManager.TemplateHandler.assert_template_exists') as mock_template_exist_wrapper:
            mock_template_exist_wrapper.return_value = template

            with patch.object(KafkaInstanceHandler, "getInstance", return_value=MagicMock()):
                result = TemplateHandler.update_template(
                    params_query, 1, token)
                self.assertIsNotNone(result)
                self.assertTrue(result)
                self.assertTrue(result['updated'])
                self.assertEqual(result['result'], 'ok')

    def test_attr_format(self):
        params = {'data_attrs': [], 'config_attrs': [],
                  'id': 1, 'attrs': [], 'label': 'template1'}

        result = attr_format('split', params)
        self.assertNotIn('attrs', result)

        result = attr_format('single', params)
        self.assertNotIn('config_attrs', result)
        self.assertNotIn('data_attrs', result)

    @patch('DeviceManager.TemplateHandler.db')
    def test_paginate(self, db_mock):
        db_mock.session = AlchemyMagicMock()

        result = paginate(db_mock.session.query, 0, 10, True)
        self.assertIsNone(result)

    @patch('DeviceManager.TemplateHandler.db')
    def test_endpoint_get_templates(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.TemplateHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()

                with patch.object(TemplateHandler, "get_templates") as mock_templates:
                    mock_templates.return_value = {'pagination': {}, 'templates': []}
                    result = flask_get_templates()
                    self.assertEqual(result.status, '200 OK')
                    self.assertIsNotNone(result)

    @patch('DeviceManager.TemplateHandler.db')
    def test_endpoint_delete_all_templates(self, db_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.TemplateHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()
                result = flask_delete_all_templates()
                self.assertIsNotNone(result)
                self.assertEqual(result.status, '200 OK')
                self.assertEqual(json.loads(result.response[0])['result'], 'ok')


    @patch('DeviceManager.TemplateHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_get_template(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.TemplateHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()

                with patch.object(TemplateHandler, "get_template") as mock_template:
                    mock_template.return_value = {'label': 'test_template', 'id':1, 'created': '2019-08-29T18:18:07.801602+00:00', 'attrs': []}
                    result = flask_get_template('test_template_id')
                    self.assertEqual(result.status, '200 OK')
                    self.assertIsNotNone(result.response)

    @patch('DeviceManager.TemplateHandler.db')
    @patch('flask_sqlalchemy._QueryProperty.__get__')
    def test_endpoint_delete_template(self, db_mock, query_property_getter_mock):
        db_mock.session = AlchemyMagicMock()
        with self.app.test_request_context():
            with patch("DeviceManager.TemplateHandler.retrieve_auth_token") as auth_mock:
                auth_mock.return_value = generate_token()

                with patch.object(TemplateHandler, "remove_template") as mock_remove_template:
                    mock_remove_template.return_value = {'result': 'ok', 'removed': {'id': 1, 'label': 'test_template', 'created': '2019-08-29T18:18:07.801602+00:00'}}
                    result = flask_remove_template('test_template_id')
                    self.assertEqual(result.status, '200 OK')
                    self.assertEqual(json.loads(result.response[0])['result'], 'ok')

    @patch('DeviceManager.TemplateHandler.db')
    def test_refresh_template_update_column(self, db_mock):
        template = DeviceTemplate(id=1, label='template1')
        refresh_template_update_column(db_mock, template)
        self.assertTrue(isinstance(template.updated, datetime))

    @patch('DeviceManager.TemplateHandler.db')
    def test_not_refresh_template_update_column(self, db_mock):
        template = DeviceTemplate(id=1, label='template1')
        db_mock.session.new = set()
        db_mock.session.deleted = set()
        refresh_template_update_column(db_mock, template)
        self.assertIsNone(template.updated)
