import pytest
import json
import unittest
from unittest.mock import Mock, MagicMock, patch, call

import requests
from DeviceManager.Logger import Log 
from DeviceManager.KafkaNotifier import DeviceEvent, NotificationMessage, KafkaNotifier

class TestKafkaNotifier(unittest.TestCase):

    def test_notification_message_to_json(self):
        data = {'label': 'test_device', 'id': 'test_device_id', 'templates': [1], 'attrs': {}}
        kafkaNotification = NotificationMessage(DeviceEvent.CREATE, data, m={"service": 'admin'})

        result = kafkaNotification.to_json()
        self.assertIsNotNone(result)
        self.assertIn('event', result)
        self.assertIn('data', result)
        self.assertIn('meta', result)

    def test_get_topic(self):
        with patch.object(KafkaNotifier, "__init__", lambda x: None):
            KafkaNotifier.topic_map = {}

            result = KafkaNotifier().get_topic('admin', 'dojot.device-manager.device')
            self.assertIsNotNone(result)
            self.assertEqual(result, 'admin.dojot.device-manager.device')
    
    def test_get_topic_with_suffix(self):
        with patch.object(KafkaNotifier, "__init__", lambda x: None):
            KafkaNotifier.topic_map = {}

            result = KafkaNotifier().get_topic('admin', 'dojot.device-manager.device', "configure")
            self.assertIsNotNone(result)
            self.assertEqual(result, 'admin.dojot.device-manager.device.configure')
    
    def test_send_notification(self):
        data = {'label': 'test_device', 'id': 'test_device_id', 'templates': [1], 'attrs': {}}

        with patch.object(KafkaNotifier, "__init__", lambda x: None):
            KafkaNotifier.kf_prod = Mock()
            self.assertIsNone(KafkaNotifier().send_notification(DeviceEvent.CREATE, data, meta={"service": 'admin'}))

            with patch.object(KafkaNotifier, "get_topic", return_value=None):
                self.assertIsNone(KafkaNotifier().send_notification(DeviceEvent.CREATE, data, meta={"service": 'admin'}))

    def test_send_raw(self):
        event = {
            "event": DeviceEvent.TEMPLATE,
            "data": {
                "affected": [],
                "template": {'label': 'SensorModelUpdated', 'config_attrs': [], 'id': 1, 'data_attrs': [], 'attrs': []}
            },
            "meta": {"service": 'admin'}
        }

        with patch.object(KafkaNotifier, "__init__", lambda x: None):
            self.assertIsNone(KafkaNotifier().send_raw(event, 'admin'))
            